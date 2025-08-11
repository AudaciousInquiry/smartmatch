from bs4 import BeautifulSoup
from loguru import logger
import requests
import json
from urllib.parse import urljoin, urlparse

from detail_extractor import extract_detail_content

UA_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

START_URL = "https://resources.cste.org/rfp/home/rfp"

def _origin(u: str) -> str:
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}"

def _get(session: requests.Session, url: str, referer: str | None = None, timeout: int = 20) -> requests.Response:
    headers = dict(UA_BASE)
    if referer:
        headers["Referer"] = referer
    resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp

def _read_token(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "__RequestVerificationToken"})
    if inp and inp.get("value"):
        return inp["value"]
    return None

def _try_read_api(session: requests.Session, base_origin: str, referer: str, token: str | None) -> list[dict]:
    paths = ["/RFP/RFP/Read", "/rfp/rfp/read"]
    params = {"page": 1, "pageSize": 100}
    headers = {
        "User-Agent": UA_BASE["User-Agent"],
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    if token:
        headers["RequestVerificationToken"] = token
    results = []
    for path in paths:
        url = urljoin(base_origin, path)
        for method in ("GET", "POST"):
            try:
                if method == "GET":
                    r = session.get(url, headers=headers, params=params, timeout=20)
                else:
                    r = session.post(url, headers=headers, data=params, timeout=20)
                if r.status_code != 200:
                    logger.warning(f"CSTE API {method} {url} -> {r.status_code}")
                    continue
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    continue
                rows = data.get("Data") or data.get("data") or []
                if isinstance(rows, dict) and "Data" in rows:
                    rows = rows["Data"]
                if not isinstance(rows, list):
                    continue
                for item in rows:
                    title = (item.get("Title") or "").strip()
                    file_url = (item.get("FileUrl") or "").strip()
                    if not title or not file_url:
                        continue
                    full = urljoin(base_origin, file_url)
                    results.append({"title": title, "url": full})
                if results:
                    return results
            except Exception as e:
                logger.warning(f"CSTE API read failed at {url}: {e}")
    return results

def _fallback_parse_anchors(listing_html: str, listing_base: str) -> list[dict]:
    soup = BeautifulSoup(listing_html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        txt = a.get_text(strip=True)
        if not txt:
            continue
        if href.lower().startswith("javascript:"):
            continue
        full = urljoin(listing_base, href)
        out.append({"title": txt, "url": full})
    return out

def scrape_cste(site):
    logger.info(f"Scraping CSTE site: {site['url']}")
    session = requests.Session()
    try:
        page = _get(session, START_URL, referer="https://www.google.com/")
    except Exception as e:
        logger.error(f"Failed to fetch {START_URL}: {e}")
        return []
    base_origin = _origin(START_URL)
    token = _read_token(page.text)
    pairs = _try_read_api(session, base_origin, START_URL, token)
    if not pairs:
        pairs = _fallback_parse_anchors(page.text, START_URL)
    results = []
    for pair in pairs:
        title = pair["title"]
        full_url = pair["url"]
        detail_text = extract_detail_content(full_url, session=session, referer=START_URL)
        results.append({
            "title": title,
            "url": full_url,
            "site": site["name"],
            "content": "",
            "detail_content": detail_text,
            "detail_source_url": full_url,
        })
        logger.debug(f"Parsed CSTE RFP: {title} ({full_url}) — extracted {len(detail_text)} chars")
    logger.info(f"Extracted {len(results)} CSTE RFP(s)")
    return results
