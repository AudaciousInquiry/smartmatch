from bs4 import BeautifulSoup, Tag
from loguru import logger
import requests
from urllib.parse import urljoin

from detail_extractor import extract_detail_content


def scrape_aira(site):
    logger.info(f"Scraping AIRA site: {site['url']}")
    try:
        response = requests.get(site["url"], timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch {site['url']}: {e}")
        return []
    
    soup = BeautifulSoup(response.text, "html.parser")
    rfp_section = soup.find("a", {"name": "RFP"})
    if not rfp_section:
        logger.warning("Could not find AIRA RFP section.")
        return []

    results = []
    rfp_content = rfp_section.find_parent("p")
    if not rfp_content:
        logger.warning("Could not find AIRA RFP content.")
        return []

    for p in rfp_content.find_next_siblings("p"):
        if p.find("span", style=lambda s: s and "color: #629f44" in s):
            break

        content_parts = []
        pdf_urls = []

        text = p.get_text(separator=" ", strip=True)
        if text:
            content_parts.append(text)

        for a in p.find_all("a", href=True):
            href = a["href"]
            if "pdf" in href.lower():
                pdf_urls.append(href)

        if not pdf_urls:
            continue

        main_pdf_url = pdf_urls[0]
        detail_content = extract_detail_content(main_pdf_url)

        pdf_links = [f"PDF: {url}" for url in pdf_urls]
        inline_content = "\n".join(content_parts + pdf_links)

        title = content_parts[0][:80].strip()
        if len(content_parts[0]) > 80:
            title += "..."

        result = {
            "title": title, 
            "url": main_pdf_url,
            "site": site["name"],
            "content": inline_content,
            "detail_content": detail_content,
            "detail_source_url": main_pdf_url,
        }
        results.append(result)

        logger.debug(f"Parsed AIRA RFP: {title} ({main_pdf_url})")
        if detail_content:
            preview = detail_content[:200].replace("\n", " ")
            logger.debug(f"Detail preview: {preview}")

    logger.info(f"Extracted {len(results)} AIRA RFP(s)")
    return results
