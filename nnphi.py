from bs4 import BeautifulSoup
from loguru import logger
import requests

from configuration_values import ConfigurationValues


def scrape_nnphi(site):
    logger.info(f"Scraping NNPHI site: {site['url']}")
    try:
        response = requests.get(site['url'], timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    posts_list = soup.find('ul', class_='posts preview block-list')
    if not posts_list:
        logger.warning('Could not find NNPHI posts list.')
        return []

    results = []
    for article in posts_list.find_all('article'):
        header = article.find('h2')
        link = header.find('a', href=True) if header else None
        title = link.get_text(strip=True) if link else 'No Title'
        url = link['href'] if link else site['url']
        results.append({
            'title': title,
            'url': url,
            'site': site['name'],
            'content': ''
        })
        logger.debug(f"Parsed NNPHI RFP: {title} ({url})")

    logger.info(f"Extracted {len(results)} NNPHI RFP(s)")
    return results
