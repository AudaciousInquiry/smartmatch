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

from detail_extractor import extract_detail_content

def scrape_cdc_foundation(site):
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
        detail_url = site['url']
        content_parts = []
        for p in group[1:]:
            link = p.find('a', href=True)
            if link:
                detail_url = link['href']
            content_parts.append(p.get_text(separator=' ', strip=True))
        content = '\n'.join(content_parts)

        detail = extract_detail_content(detail_url)
        detail_content = detail["content"]
        detail_source = detail["source_url"]

        results.append({
            'title': title,
            'url': detail_url,
            'site': site['name'],
            'content': content,
            'detail_content': detail_content,
            'detail_source_url': detail_source,
        })
        logger.debug(f"Parsed CDC RFP: {title} ({detail_url})")
        logger.debug(f"Detail content preview for '{title}': {detail_content[:400].replace(chr(10),' ')}")

    logger.info(f"Extracted {len(results)} CDC RFP(s)")
    return results