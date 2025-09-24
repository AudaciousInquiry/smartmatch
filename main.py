from dotenv import load_dotenv
load_dotenv()

from bs4 import BeautifulSoup, Tag
from loguru import logger
import hashlib
from datetime import datetime, timezone
import sys

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_aws import ChatBedrock

from chains import get_competency_check_chain, get_default_chain
from configuration_values import ConfigurationValues
from competencies import get_competencies;
from prompts import get_prompt, get_competency_match_prompt
from sqlalchemy import create_engine, Table, Column, String, MetaData, select, text
from sqlalchemy import LargeBinary
import requests

from bedrock_scrape import process_listing, init_exclusions_table

from email_utils import send_email
from bedrock_utils import summarize_rfp
import os
from io import StringIO

LOG_BUFFER = StringIO()
logger.add(LOG_BUFFER, level="DEBUG")

def print_processed_rfps():
    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    processed = init_processed_table(engine)
    
    with engine.connect() as conn:
        rows = conn.execute(
            select(processed).order_by(processed.c.processed_at.desc())
        ).fetchall()

    print('\nAlready-processed RFPs:')
    for row in rows:
        print('=' * 100)
        print(f"Processed At: {row.processed_at}")
        print(f"Site: {row.site}")
        print(f"Title: {row.title}")
        print(f"URL: {row.url}")
        print(f"Hash: {row.hash}")

        if row.detail_content:
            content = row.detail_content[:300] + "..." if len(row.detail_content) > 300 else row.detail_content
            print(f"\nContent Preview:\n{content}")
        
        if row.ai_summary:
            summary = row.ai_summary[:300] + "..." if len(row.ai_summary) > 300 else row.ai_summary
            print(f"\nAI Summary:\n{summary}")
        
        if row.pdf_content:
            print(f"\nPDF Size: {len(row.pdf_content):,} bytes")
        
        print('\n' + '-' * 100)

def init_processed_table(engine):
    metadata = MetaData(schema='public')
    processed = Table(
        'processed_rfps', metadata,
        Column('hash', String, primary_key=True),
        Column('title', String),
        Column('url', String),
        Column('site', String),
        Column('processed_at', String),
        Column('detail_content', String),
        Column('ai_summary', String),
        Column('pdf_content', LargeBinary)
    )
    metadata.create_all(engine)
    
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE public.processed_rfps 
            ADD COLUMN IF NOT EXISTS detail_content TEXT,
            ADD COLUMN IF NOT EXISTS ai_summary TEXT,
            ADD COLUMN IF NOT EXISTS pdf_content BYTEA;
        """))
    
    return processed

from sqlalchemy import text

def clear_processed(engine):
    logger.warning('Clearing all processed RFP records...')
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE TABLE public.processed_rfps'))

def list_processed(engine, processed):
    with engine.connect() as conn:
        rows = conn.execute(
            select(processed).order_by(processed.c.processed_at.desc())
        ).fetchall()

    print('\nAlready-processed RFPs:')
    for row in rows:
        print('=' * 100)
        print(f"Processed At: {row.processed_at}")
        print(f"Site: {row.site}")
        print(f"Title: {row.title}")
        print(f"URL: {row.url}")
        print(f"Hash: {row.hash}")

        if row.detail_content:
            content = row.detail_content[:300] + "..." if len(row.detail_content) > 300 else row.detail_content
            print(f"\nContent Preview:\n{content}")
        
        if row.ai_summary:
            summary = row.ai_summary[:300] + "..." if len(row.ai_summary) > 300 else row.ai_summary
            print(f"\nAI Summary:\n{summary}")
        
        if row.pdf_content:
            print(f"\nPDF Size: {len(row.pdf_content):,} bytes")
        
        print('\n' + '-' * 100)

def list_exclusions(engine):
    excluded = init_exclusions_table(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(excluded).order_by(excluded.c.decided_at.desc())
        ).fetchall()

    print('\nExcluded RFPs:')
    if not rows:
        print('(none)')
        return
    for row in rows:
        print('=' * 100)
        print(f"Decided At: {row.decided_at}")
        print(f"Site: {row.site}")
        print(f"Reason: {row.reason}")
        print(f"Title: {row.title}")
        print(f"Listing URL: {row.listing_url}")
        if row.detail_url:
            print(f"Detail URL: {row.detail_url}")
        print(f"Hash: {row.hash}")
        print('\n' + '-' * 100)

def clear_exclusions(engine):
    excluded = init_exclusions_table(engine)
    logger.warning('Clearing all excluded RFP records...')
    with engine.begin() as conn:
        # Ensure table exists then truncate
        conn.execute(text('TRUNCATE TABLE public.rfp_exclusions'))

SCRAPER_MAP = {}

def format_new_rfps(new_rfps):
    if not new_rfps:
        return "No new RFPs found."
    lines = ["New RFPs found:"]
    for r in new_rfps:
        lines.append(f"{r['site']}: {r['title']} ({r['url']})")
    return "\n".join(lines)

def format_email_body(new_rfps):
    lines = ["New RFPs found:\n"]
    for r in new_rfps:
        lines.append(f"• **{r['site']}** — {r['title']}")
        lines.append(f"Link: {r['url']}")
        pdf = r.get('detail_source_url')
        if pdf and pdf.lower().endswith('.pdf') and pdf != r['url']:
            lines.append(f"PDF: {pdf}")
        summary = r.get('summary')
        if summary:
            lines.append("\nSummary:")
            lines.append(summary)
        lines.append("")
    return "\n".join(lines)

def main():
    logger.info('Initializing vector store and persistence store')
    vector_store = PGVector(
        embeddings=HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2'),
        collection_name='rfps',
        connection=ConfigurationValues.get_pgvector_connection(),
        use_jsonb=True,
    )
    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    processed = init_processed_table(engine)

    new_rfps = []
    with engine.begin() as conn:
        for site in ConfigurationValues.get_websites():
            site_name = site['name']
            url = site['url']
            logger.info(f"Processing listing via Bedrock probe: {site_name} -> {url}")
            try:
                rows = process_listing(url, site_name=site_name, engine=engine)
            except Exception as e:
                logger.exception(f"Site processing failed; continuing: {site_name} ({url})")
                rows = []
            for r in rows:
                new_rfps.append({
                    'title': r['title'],
                    'url': r['url'],
                    'site': site_name,
                    'detail_source_url': r.get('detail_source_url'),
                    'detail_content': None,
                    'ai_summary': r.get('ai_summary'),
                    'summary': r.get('ai_summary'),
                })

    engine.dispose()
    return new_rfps

def process_and_email(send_main: bool, send_debug: bool):
    new_rfps = main()
    main_body = format_email_body(new_rfps)
    full_log_text = LOG_BUFFER.getvalue()

    def _parse_env_list(key: str) -> list[str]:
        raw = os.environ.get(key, "")
        return [e.strip() for e in raw.split(',') if e and e.strip()]

    def _get_db_recipients() -> tuple[list[str], list[str]]:
        try:
            eng = create_engine(ConfigurationValues.get_pgvector_connection())
            with eng.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT main_recipients, debug_recipients
                        FROM public.email_settings
                        WHERE id = 'singleton'
                    """)
                ).first()
            eng.dispose()
            if not row:
                return [], []
            m = getattr(row, "_mapping", row)
            main_lst = list(m.get("main_recipients") or [])
            debug_lst = list(m.get("debug_recipients") or [])
            main_norm = [str(x).strip() for x in main_lst if str(x).strip()]
            debug_norm = [str(x).strip() for x in debug_lst if str(x).strip()]
            return main_norm, debug_norm
        except Exception:
            logger.exception("Failed to load email recipients from DB; falling back to environment variables")
            return [], []

    db_main, db_debug = _get_db_recipients()

    if send_main and new_rfps:
        to_main = db_main or _parse_env_list('MAIN_RECIPIENTS')
        if to_main:
            logger.info(f"Sending main email to: {to_main} (source={'db' if db_main else 'env'})")
            send_email('SmartMatch: New RFPs Found', main_body, to_main)
        else:
            logger.warning("No main recipients configured (db/env); skipping main email")

    if send_debug:
        debug_body = f"{main_body}\n\n--- FULL LOG ---\n{full_log_text}"
        to_debug = db_debug or _parse_env_list('DEBUG_RECIPIENTS')
        if to_debug:
            logger.info(f"Sending debug email to: {to_debug} (source={'db' if db_debug else 'env'})")
            send_email('SmartMatch: Debug Log', debug_body, to_debug)
        else:
            logger.info("No debug recipients configured (db/env); skipping debug email")

    return new_rfps

def get_pdf(hash: str):
    with engine.connect() as conn:
        result = conn.execute(
            select(processed.c.pdf_content, processed.c.title)
            .where(processed.c.hash == hash)
        ).first()
        
        if result and result.pdf_content:
            return result.pdf_content, result.title

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--email', action='store_true')
    parser.add_argument('--debug-email', action='store_true')
    parser.add_argument('--list', action='store_true', help='List processed RFPs')
    parser.add_argument('--list-exclusions', action='store_true', help='List excluded (expired/out-of-scope/etc.) RFPs')
    parser.add_argument('--clear-exclusions', action='store_true', help='Clear exclusions list')
    parser.add_argument('--clear', action='store_true', help='Clear processed RFPs')
    parser.add_argument('--clear-schedule', action='store_true', help='Clear scheduled run (reset scrape_config singleton)')
    args = parser.parse_args()

    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    processed = init_processed_table(engine)

    if args.clear_schedule:
        logger.warning('Clearing schedule configuration (scrape_config.singleton)...')
        with engine.begin() as conn:
            res = conn.execute(text("""
                UPDATE scrape_config
                SET enabled = false,
                    next_run_at = NULL,
                    last_run_at = NULL,
                    updated_at = NOW()
                WHERE id = 'singleton'
            """))
            if res.rowcount == 0:
                conn.execute(text("""
                    INSERT INTO scrape_config (id, enabled, interval_hours, next_run_at, last_run_at, created_at, updated_at)
                    VALUES ('singleton', false, 24.0, NULL, NULL, NOW(), NOW())
                """))
        print("Cleared schedule configuration")
        sys.exit(0)

    if args.clear:
        clear_processed(engine)
        print("Cleared processed_rfps")
        sys.exit(0)

    if args.list:
        list_processed(engine, processed)
        sys.exit(0)

    if args.list_exclusions:
        list_exclusions(engine)
        sys.exit(0)

    if args.clear_exclusions:
        clear_exclusions(engine)
        print("Cleared rfp_exclusions")
        sys.exit(0)

    if args.email or args.debug_email:
        process_and_email(send_main=args.email, send_debug=args.debug_email)
    else:
        main()

    sys.exit(0)
