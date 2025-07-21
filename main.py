from bs4 import BeautifulSoup, Tag
from loguru import logger
import hashlib
import datetime
import sys

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_aws import ChatBedrock
import requests
import re

from chains import get_competency_check_chain, get_default_chain
from configuration_values import ConfigurationValues
from competencies import get_competencies;
from cdc_foundation import scrape_cdc_foundation
from prompts import get_prompt, get_competency_match_prompt
from sqlalchemy import create_engine, Table, Column, String, MetaData, select, text

# --- SCRAPER FUNCTIONS --- this can be moved to a separate file maybe siteloader
def scrape_nnphi(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
    # TODO: add scraping logic
    return rfps

def scrape_astho(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
    # TODO: add scraping logic
    return rfps

def scrape_cste(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
    # TODO: add scraping logic
    return rfps

def scrape_aira(site):
    response = requests.get(site["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    rfps = []
    # TODO: add scraping logic
    return rfps

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

    if new_rfps:
        print('New RFPs found:')
        for r in new_rfps:
            print(f"{r['site']}: {r['title']} ({r['url']})")
    else:
        print('No new RFPs found.')
  
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

if __name__ == '__main__':
    args = sys.argv[1:]
    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    processed = init_processed_table(engine)

    if '--clear' in args:
        clear_processed(engine)
    elif '--list' in args:
        list_processed(engine, processed)
    else:
        main()
