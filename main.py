from bs4 import BeautifulSoup, Tag
from loguru import logger
import hashlib
import datetime

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from langchain_aws import ChatBedrock
import requests
import re

from chains import get_competency_check_chain, get_default_chain
from configuration_values import ConfigurationValues
from competencies import get_competencies;
from cdc_foundation import load_site
from prompts import get_prompt, get_competency_match_prompt
from sqlalchemy import create_engine, Table, Column, String, MetaData, select

# --- SCRAPER FUNCTIONS --- this can be moved to a separate file maybe siteloader
def scrape_cdc_foundation(site):
    logger.info(f"Scraping site: {site['url']}")
    try:
        response = requests.get(site['url'], timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    start_tag = soup.find(lambda tag: tag.name == 'p' and 'OPEN REQUESTS FOR PROPOSALS' in tag.get_text())
    end_tag = soup.find(lambda tag: tag.name == 'p' and 'Please note that the CDC Foundation is not a traditional grantmaking foundation' in tag.get_text())
    if not start_tag or not end_tag:
        logger.warning("Could not find RFP content between markers.")
        return []

    snippet_html = ''
    for elem in start_tag.next_siblings:
        if elem == end_tag:
            break
        snippet_html += str(elem)
    logger.debug(f"RFP HTML snippet for CDC site:\n{snippet_html}")

    snippet_soup = BeautifulSoup(snippet_html, 'html.parser')
    proposals = []
    current_group = []
    for elem in snippet_soup.children:
        if isinstance(elem, Tag) and elem.name == 'hr':
            if current_group:
                proposals.append(current_group)
                current_group = []
        elif isinstance(elem, Tag) and elem.name == 'p':
            current_group.append(elem)
    if current_group:
        proposals.append(current_group)

    results = []
    for group in proposals:
        title_p = group[0]
        strong = title_p.find('strong')
        title = strong.get_text(strip=True) if strong else title_p.get_text(strip=True)
        url = site['url']
        content_parts = []
        for p in group[1:]:
            link = p.find('a', href=True)
            if link:
                url = link['href']
            content_parts.append(p.get_text(separator=' ', strip=True))
        content = '\n'.join(content_parts)
        results.append({
            'title': title,
            'url': url,
            'site': site['name'],
            'content': content
        })
        logger.debug(f"Parsed CDC RFP: {title} ({url})\nContent Preview: {content[:80]}...")
    logger.info(f"Extracted {len(results)} CDC RFP(s)")
    return results

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

# --- SCRAPER MAP ---
SCRAPER_MAP = {
    "cdcfoundation": scrape_cdc_foundation,
    "cste": scrape_cste,
    "nnphi": scrape_nnphi,
    "astho": scrape_astho,
    "aira": scrape_aira,
}

def main():
    logger.info("Initializing vector store and persistence store")
    vector_store = PGVector(
        embeddings=HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2"),
        collection_name="rfps",
        connection=ConfigurationValues.get_pgvector_connection(),
        use_jsonb=True,
    )

    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    metadata = MetaData(schema="public")
    processed = Table(
        'processed_rfps', metadata,
        Column('hash', String, primary_key=True),
        Column('title', String),
        Column('url', String),
        Column('site', String),
        Column('processed_at', String),
    )
    metadata.create_all(engine)

    with engine.begin() as conn:
        all_new_rfps = []
        for site in ConfigurationValues.get_websites():
            for rfp in scrape_cdc_foundation(site):
                h = hashlib.sha256((rfp['title'] + rfp['url'] + rfp['content']).encode()).hexdigest()
                exists = conn.execute(select(processed.c.hash).where(processed.c.hash == h)).first()
                if exists:
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
                all_new_rfps.append(rfp)

    if all_new_rfps:
        print("New RFPs found:")
        for r in all_new_rfps:
            print(f"{r['site']}: {r['title']} ({r['url']})")
    else:
        print("No new RFPs found.")
  #source_url = load_site()
  
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
main()

if __name__ == '__main__':
    import sys
    if "--list" in sys.argv:
        print_processed_rfps()
    else:
        main()