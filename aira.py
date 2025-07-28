from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests

from configuration_values import ConfigurationValues


def scrape_aira(site):
    logger.info(f"Scraping AIRA site: {site['url']}")
    try:
        resp = requests.get(site['url'], timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    header = soup.find(lambda t: t.name == 'p' and t.find('span') and 'Requests for Proposals' in t.get_text())
    if not header:
        logger.warning('Could not find Requests for Proposals header.')
        return []

    default = header.find_next_sibling(lambda t: t.name == 'p' and 'There are no requests for proposals' in t.get_text())
    if default:
        logger.info('No active AIRA RFPs (found default text).')
        return []

    content_chunks = []
    for sib in header.next_siblings:
        if isinstance(sib, Tag) and sib.name == 'hr':
            break
        if isinstance(sib, Tag):
            text = sib.get_text(separator=' ', strip=True)
            if text:
                content_chunks.append(text)

    content = '\n'.join(content_chunks)
    if not content:
        content = 'AIRA RFP section has been updated.'

    results = [{
        'title': 'AIRA – RFP Section Updated',
        'url': site['url'],
        'site': site['name'],
        'content': content
    }]
    logger.info(f"Extracted {len(results)} AIRA RFP(s)")
    return results
