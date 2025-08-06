from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests

from configuration_values import ConfigurationValues
from detail_extractor import extract_detail_content


def scrape_nnphi(site):
    logger.info(f"Scraping NNPHI site: {site['url']}")
    try:
        resp = requests.get(site["url"], timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
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
        detail_pdf_url = None
        try:
            dresp = requests.get(detail_page, timeout=15)
            dresp.raise_for_status()
            dsoup = BeautifulSoup(dresp.text, "html.parser")
            btn = dsoup.find(
                "a", href=True,
                text=lambda t: t and ("Download the RFP" in t or "DOWNLOAD THE RFP" in t)
            )
            if btn:
                detail_pdf_url = btn["href"]
        except Exception as e:
            logger.error(f"Failed to fetch detail page {detail_page}: {e}")

        extractor_url = detail_pdf_url or detail_page
        detail = extract_detail_content(extractor_url)

        if isinstance(detail, dict):
            detail_content = detail.get("content", "")
        else:
            detail_content = detail

        results.append({
            "title": title,
            "url": detail_pdf_url or detail_page,
            "site": site["name"],
            "content": "",
            "detail_content": detail_content,
            "detail_source_url": detail.get("source_url", extractor_url) if isinstance(detail, dict) else extractor_url,
        })

        preview = (detail_content[:200] + "...") if detail_content else "<no detail>"
        logger.debug(f"Parsed NNPHI RFP: {title} extracted {len(detail_content)} chars (preview: {preview})")

    logger.info(f"Extracted {len(results)} NNPHI RFP(s)")
    return results
