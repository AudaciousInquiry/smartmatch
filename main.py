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

from cdc_foundation import scrape_cdc_foundation
from nnphi import scrape_nnphi
from astho import scrape_astho
from cste import scrape_cste
from aira import scrape_aira

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

SCRAPER_MAP = {
    "cdcfoundation": scrape_cdc_foundation,
    "cste": scrape_cste,
    "nnphi": scrape_nnphi,
    "astho": scrape_astho,
    "aira": scrape_aira,
}

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
            scraper = SCRAPER_MAP.get(site['name'])
            if not scraper:
                continue

            for rfp in scraper(site):
                h = hashlib.sha256((rfp["title"] + rfp["url"]).encode()).hexdigest()
                if conn.execute(select(processed.c.hash).where(processed.c.hash == h)).first():
                    continue

                pdf_content = None
                detail_src = rfp.get("detail_source_url", "")
                if detail_src.lower().endswith('.pdf'):
                    try:
                        response = requests.get(detail_src, timeout=15)
                        response.raise_for_status()
                        pdf_content = response.content
                        logger.info(f'Retrieved PDF content ({len(pdf_content)} bytes) for "{rfp["title"]}"')
                    except Exception as e:
                        logger.exception(f'Failed to fetch PDF for "{rfp["title"]}"')

                ai_summary = None
                if rfp.get('detail_content'):
                    try:
                        ai_summary = summarize_rfp(rfp['detail_content'])
                        logger.info(f'Generated AI summary for "{rfp["title"]}"')
                    except Exception as e:
                        logger.exception(f'Failed to generate AI summary for "{rfp["title"]}"')

                conn.execute(
                    processed.insert().values(
                        hash=h,
                        title=rfp["title"],
                        url=rfp["url"],
                        site=rfp["site"],
                        processed_at=datetime.now(timezone.utc).isoformat(),
                        detail_content=rfp.get('detail_content'),
                        ai_summary=ai_summary,
                        pdf_content=pdf_content
                    )
                )
                
                rfp['summary'] = ai_summary
                new_rfps.append(rfp)

    engine.dispose()
    return new_rfps

def process_and_email(send_main: bool, send_debug: bool):
    new_rfps = main()
    main_body = format_email_body(new_rfps)
    full_log_text = LOG_BUFFER.getvalue()

    if send_main and new_rfps:
        to_main = os.environ['MAIN_RECIPIENTS'].split(',')
        send_email('SmartMatch: New RFPs Found', main_body, to_main)

    if send_debug:
        debug_body = f"{main_body}\n\n--- FULL LOG ---\n{full_log_text}"
        to_debug = os.environ['DEBUG_RECIPIENTS'].split(',')
        send_email('SmartMatch: Debug Log', debug_body, to_debug)

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

    if args.email or args.debug_email:
        process_and_email(send_main=args.email, send_debug=args.debug_email)
    else:
        main()

    sys.exit(0)
