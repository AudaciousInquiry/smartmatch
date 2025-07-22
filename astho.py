from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests


def scrape_astho(site):
    logger.info(f"Scraping ASTHO site: {site['url']}")
    try:
        response = requests.get(site['url'], timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    container = soup.find("div", class_="c-richtext")
    if not container:
        logger.warning("Could not find ASTHO container.")
        return []
    
    results = []
    h2_tags = container.find_all("h2")
    for h2 in h2_tags:
        title = h2.get_text(strip=True)
        url = site["url"]
        content_parts = []

        for sib in h2.next_siblings:
            if isinstance(sib, Tag) and sib.name == "h2":
                break
            if isinstance(sib, Tag):
                a = sib.find("a", href=True)
                if a and url == site["url"]:
                    url = a["href"]
                text_chunk = sib.get_text(separator=" ", strip=True)
                if text_chunk:
                    content_parts.append(text_chunk)

        content = "\n".join(content_parts)
        results.append({
            "title": title,
            "url": url,
            "site": site["name"],
            "content": content
        })
        logger.debug(f"Parsed ASTHO RFP: {title} ({url})")

    logger.info(f"Extracted {len(results)} ASTHO RFP(s)")
    return results
