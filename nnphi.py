from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests
from urllib.parse import urljoin

from detail_extractor import extract_detail_content


def scrape_nnphi(site):
    logger.info(f"Scraping NNPHI site: {site['url']}")
    try:
        response = requests.get(site["url"], timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    posts_list = soup.find("ul", class_="posts preview block-list")
    if not posts_list:
        logger.warning("Could not find NNPHI posts list.")
        return []

    results = []
    for article in posts_list.find_all("article"):
        h2 = article.find("h2")
        link = h2.find("a", href=True) if h2 else None
        title = link.get_text(strip=True) if link else "No Title"
        detail_page = link["href"] if link else site["url"]

        logger.info(f"Fetching detail page for: {title}")
        try:
            dresp = requests.get(detail_page, timeout=15)
            dresp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch detail page {detail_page}: {e}")
            detail_pdf_url = None
        else:
            dsoup = BeautifulSoup(dresp.text, "html.parser")
            btn = dsoup.find("a", href=True, text=lambda t: "Download the RFP" in t or "DOWNLOAD THE RFP" in t)
            detail_pdf_url = btn["href"] if btn else None

        extractor_url = detail_pdf_url or detail_page
        detail_content = extract_detail_content(extractor_url)

        results.append({
            "title": title,
            "url": pdf_url or site["url"],
            "site": site["name"],
            "content": inline_content,
            "detail_content": detail_content,
            "detail_source_url": detail_source,
        })

        logger.debug(f"Parsed NNPHI RFP: {title} ({detail_page}) — extracted {len(detail_text)} chars")

    logger.info(f"Extracted {len(results)} NNPHI RFP(s)")
    return results
