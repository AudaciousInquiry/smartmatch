from dotenv import load_dotenv
load_dotenv()

from bs4 import BeautifulSoup, Tag
from loguru import logger
import hashlib
import datetime
import sys

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_aws import ChatBedrock

from chains import get_competency_check_chain, get_default_chain
from configuration_values import ConfigurationValues
from competencies import get_competencies;
from prompts import get_prompt, get_competency_match_prompt
from sqlalchemy import create_engine, Table, Column, String, MetaData, select, text

from cdc_foundation import scrape_cdc_foundation
from nnphi import scrape_nnphi
from astho import scrape_astho
from cste import scrape_cste
from aira import scrape_aira

from email_utils import send_email
import os
from io import StringIO
LOG_BUFFER = StringIO()
logger.add(LOG_BUFFER, level="DEBUG")

def print_processed_rfps():
    from sqlalchemy import MetaData, Table, select
    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    metadata = MetaData(schema="public")
    processed = Table("processed_rfps", metadata, autoload_with=engine)

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                processed.c.processed_at,
                processed.c.site,
                processed.c.title,
                processed.c.url,
                processed.c.hash
            ).order_by(processed.c.processed_at.desc())
        ).all()

    print("\nAlready-processed RFPs:\n")
    for processed_at, site, title, url, h in rows:
        print(f"{processed_at} | {site:12} | {title[:50]:50} | {url} | {h}")

def init_processed_table(engine):
    metadata = MetaData(schema='public')
    processed = Table(
        'processed_rfps', metadata,
        Column('hash', String, primary_key=True),
        Column('title', String),
        Column('url', String),
        Column('site', String),
        Column('processed_at', String),
    )
    metadata.create_all(engine)
    return processed

from sqlalchemy import text

def clear_processed(engine):
    logger.warning('Clearing all processed RFP records...')
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE TABLE public.processed_rfps'))

def list_processed(engine, processed):
    """
    Print all processed RFP records from the database.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                processed.c.processed_at,
                processed.c.site,
                processed.c.title,
                processed.c.url,
                processed.c.hash
            ).order_by(processed.c.processed_at.desc())
        ).fetchall()

    print('Already-processed RFPs:')
    for processed_at, site, title, url, h in rows:
        print(f"{processed_at} | {site} | {title} | {url} | {h}")


# --- SCRAPER MAP ---
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
                h = hashlib.sha256((rfp['title'] + rfp['url'] + rfp['content']).encode()).hexdigest()
                if conn.execute(select(processed.c.hash).where(processed.c.hash == h)).first():
                    logger.debug(f"Skipping existing RFP: {rfp['title']}")
                    continue
                vector_store.add_texts([rfp['content']], metadatas=[{'url': rfp['url'], 'site': rfp['site']}])
                conn.execute(
                    processed.insert().values(
                        hash=h,
                        title=rfp['title'],
                        url=rfp['url'],
                        site=rfp['site'],
                        processed_at=datetime.datetime.utcnow().isoformat()
                    )
                )
                new_rfps.append(rfp)
    return new_rfps
  
    ''' chain = get_default_chain(get_prompt(), vector_store, get_chat_model(), source_url)
  response = chain.invoke("""Provide a summary of the document and its contents focusing on technical requirements found in the document. 
                          In the summary highlight any dates, deadlines, or timelines mentioned in the document. Also, provide any dollar 
                          amounts if mentioned.""")
  logger.info(f"Response: {response['answer']}")
  
  input("Press any key continue...")
  competencies = get_competencies(vector_store)
  competency_match_chain = get_competency_check_chain(get_competency_match_prompt(competencies), vector_store, get_chat_model(), source_url)

  input("Press any key continue...")
  response = competency_match_chain.invoke("On a scale of 1-10, do you think this aligns with the competencies listed below and should Audacious Inquiry bid on on the project and provide reasons.")
  logger.info(f"Response: {response['answer']}")
  
def get_chat_model() -> ChatBedrock:
  return ChatBedrock(model_id="us.meta.llama3-3-70b-instruct-v1:0",
          max_tokens=1024,
          temperature=0.0,
        )
 '''
    
    
def process_and_email(send_main: bool, send_debug: bool):
    new_rfps = main()
    main_body = format_new_rfps(new_rfps)
    full_log_text = LOG_BUFFER.getvalue()
    if send_main and new_rfps:
        to_main = os.environ['MAIN_RECIPIENTS'].split(',')
        send_email('SmartMatch: New RFPs Found', main_body, to_main)
    if send_debug:
        debug_body = f"{main_body}\n\n--- FULL LOG ---\n{full_log_text}"
        to_debug = os.environ['DEBUG_RECIPIENTS'].split(',')
        send_email('SmartMatch: Debug Log', debug_body, to_debug)
    return new_rfps

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', action='store_true')
    parser.add_argument('--debug-email', action='store_true')
    args = parser.parse_args()

    if args.email or args.debug_email:
        process_and_email(send_main=args.email, send_debug=args.debug_email)
    else:
        main()

    engine.dispose()
    sys.exit(0)
