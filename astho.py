from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests
from urllib.parse import urljoin, urlparse

from detail_extractor import extract_detail_content


def scrape_astho(site):
    logger.info(f"Scraping ASTHO site: {site['url']}")
    try:
        response = requests.get(site["url"], timeout=15)
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
    for h2 in container.find_all("h2"):
        title = h2.get_text(strip=True)
        content_parts = []
        pdf_url = None
        detail_page_url = None

        for sib in h2.next_siblings:
            if isinstance(sib, Tag) and sib.name == "h2":
                break
            if isinstance(sib, Tag):
                for a in sib.find_all("a", href=True):
                    href = a["href"].strip()
                    full_url = urljoin(site["url"], href)

                    if not pdf_url and urlparse(full_url).path.lower().endswith(".pdf"):
                        pdf_url = full_url

                    if not detail_page_url:
                        parsed = urlparse(full_url)
                        if (
                            parsed.netloc.endswith("astho.org")
                            and "/members/opportunities/" in parsed.path
                        ):
                            detail_page_url = full_url

                text_chunk = sib.get_text(separator=" ", strip=True)
                if text_chunk:
                    content_parts.append(text_chunk)

        inline_content = "\n".join(content_parts)

        if pdf_url:
            detail_source = pdf_url
            detail_content = extract_detail_content(pdf_url, referer=site["url"])
        elif detail_page_url:
            detail_source = detail_page_url
            detail_content = extract_detail_content(detail_page_url, referer=site["url"])
        else:
            detail_source = site["url"]
            detail_content = inline_content

        results.append({
            "title": title,
            "url": detail_page_url or pdf_url or site["url"],
            "site": site["name"],
            "content": inline_content,
            "detail_content": detail_content,
            "detail_source_url": detail_source,
        })

        logger.debug(f"Parsed ASTHO RFP: {title} ({detail_page_url or pdf_url or site['url']})")
        if detail_content:
            preview = detail_content[:200].replace("\n", " ")
            logger.debug(f"Detail preview for '{title}': {preview}")

    logger.info(f"Extracted {len(results)} ASTHO RFP(s)")
    return results
