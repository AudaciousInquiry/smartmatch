from loguru import logger
import requests
from bs4 import BeautifulSoup, Tag
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_postgres import PGVector
from sqlalchemy import create_engine, Table, MetaData, delete

from smartmatch_site_loader import SmartMatchSiteLoader
from configuration_values import ConfigurationValues


def scrape_cdc_foundation(site):
    """
    Scrape the CDC Foundation RFPs from the given site configuration.
    Returns a list of dicts with keys: title, url, site, content
    """
    logger.info(f"Scraping CDC site: {site['url']}")
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
        logger.warning('Could not find CDC RFP section markers.')
        return []

    snippet_html = ''
    for elem in start_tag.next_siblings:
        if elem == end_tag:
            break
        snippet_html += str(elem)
    logger.debug(f"CDC HTML snippet:\n{snippet_html}")

    snippet_soup = BeautifulSoup(snippet_html, 'html.parser')
    proposals = []
    current = []
    for elem in snippet_soup.children:
        if isinstance(elem, Tag) and elem.name == 'hr':
            if current:
                proposals.append(current)
                current = []
        elif isinstance(elem, Tag) and elem.name == 'p':
            current.append(elem)
    if current:
        proposals.append(current)

    results = []
    for group in proposals:
        title_elem = group[0].find('strong') or group[0]
        title = title_elem.get_text(strip=True)
        url = site['url']
        content_parts = []
        for p in group[1:]:
            link = p.find('a', href=True)
            if link:
                url = link['href']
            content_parts.append(p.get_text(separator=' ', strip=True))
        content = '\n'.join(content_parts)
        results.append({'title': title, 'url': url, 'site': site['name'], 'content': content})
        logger.debug(f"Parsed CDC RFP: {title} ({url})")
    logger.info(f"Extracted {len(results)} CDC RFP(s)")
    return results

  
def delete_by_metadata(metadata_filter: dict) -> int:
    """
    Delete rows from a PGVector table based on metadata.

    Args:
        connection_string: SQLAlchemy connection string to Postgres.
        table_name: The PGVector table name.
        metadata_filter: Dictionary of metadata to filter by (e.g., {"category": "langchain"}).

    Returns:
        The number of rows deleted.
    """
    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    metadata = MetaData(schema="public")
    conn = engine.connect()

    doc_table = Table("langchain_pg_embedding", metadata, autoload_with=engine)

    if 'cmetadata' not in doc_table.columns:
        raise ValueError(f"'cmetadata' column not found in table 'langchain_pg_embedding'. Available columns: {doc_table.columns.keys()}")

    # Build WHERE clause from metadata
    conditions = [
        doc_table.c.cmetadata[key].astext == str(value)
        for key, value in metadata_filter.items()
    ]

    delete_stmt = delete(doc_table).where(*conditions)
    result = conn.execute(delete_stmt)
    conn.commit()
    conn.close()

    return result.rowcount
