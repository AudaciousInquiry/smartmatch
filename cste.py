from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests
import re
from urllib.parse import urljoin

HEADER_TEXTS = {"title", "type of service", "date posted", "rfp expiration"}

def scrape_cste(site):
    logger.info(f"Scraping CSTE site: {site['url']}")
    try:
        resp = requests.get(site["url"], timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    iframe = soup.find("iframe", src=True)
    if not iframe:
        logger.warning("CSTE: no iframe found.")
        return []

    iframe_url = urljoin(site["url"], iframe["src"])
    logger.debug(f"CSTE iframe src: {iframe_url}")

    try:
        iresp = requests.get(iframe_url, timeout=15)
        iresp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch iframe {iframe_url}: {e}")
        return []

    isoup = BeautifulSoup(iresp.text, "html.parser")
    results = []
    for a in isoup.find_all("a", href=True):
        txt = a.get_text(strip=True)
        href = a["href"].strip()

        if not txt:
            continue
        if href.lower().startswith("javascript:"):
            continue
        if txt.lower() in HEADER_TEXTS:
            continue

        if "LaunchThis" in a.get("onclick", "") and not href:
            m = re.search(r"LaunchThis\(.*?'([^']+)'", a["onclick"])
            if m:
                href = m.group(1)

        full_url = urljoin(iframe_url, href)
        results.append({
            "title": txt,
            "url": full_url,
            "site": site["name"],
            "content": ""
        })
        logger.debug(f"Parsed CSTE RFP: {txt} ({full_url})")

    logger.info(f"Extracted {len(results)} CSTE RFP(s)")
    return results
