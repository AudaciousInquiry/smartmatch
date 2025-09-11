import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

UA_BASE: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch_page(url: str) -> BeautifulSoup:
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    headers = dict(UA_BASE)
    headers["Referer"] = origin
    resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def fetch_page_with_session(session: requests.Session, url: str) -> BeautifulSoup:
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    headers = dict(UA_BASE)
    headers["Referer"] = origin
    r = session.get(url, headers=headers, timeout=20, allow_redirects=True)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def soup_text(soup: BeautifulSoup, max_chars: int = 20000) -> str:
    txt = soup.get_text(separator="\n", strip=True)
    return txt[:max_chars]

def _link_context(a: Any, max_len: int = 500) -> str:
    try:
        node = a
        for _ in range(8):
            if node is None:
                break
            if getattr(node, "name", None) in ("li", "article", "section", "div", "tr", "td", "table", "tbody"):
                txt = node.get_text(" ", strip=True)
                return txt[:max_len]
            node = getattr(node, "parent", None)
    except Exception:
        pass
    try:
        return (a.get_text(" ", strip=True) or "")[:max_len]
    except Exception:
        return ""

def _nearest_heading(a: Any) -> str:
    try:
        h = a.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        if h is not None:
            return h.get_text(" ", strip=True)[:300]
    except Exception:
        pass
    return ""

def _link_flags(text: str, href: str) -> Dict[str, Any]:
    t = (text or "").lower()
    h = (href or "").lower()
    is_pdf_flag = h.endswith(".pdf")
    return {
        "is_learn_more": any(k in t for k in ["learn more", "read more", "details", "more info", "about this opportunity", "view details"]),
        "is_apply": any(k in t for k in ["apply", "application"]) or "qualtrics" in h,
        "is_pdf": is_pdf_flag,
        "is_generic_listing": any(seg in h for seg in ["/events", "/event", "/news", "/blog", "/calendar"]) and not is_pdf_flag,
        "depth": (urlparse(href).path or "/").strip("/").count("/")
    }

def _is_within(a: Any, tag_names: tuple[str, ...]) -> bool:
    try:
        node = a
        for _ in range(6):
            if node is None:
                return False
            name = getattr(node, "name", None)
            if name in tag_names:
                return True
            node = getattr(node, "parent", None)
    except Exception:
        return False
    return False

def gather_links(soup: BeautifulSoup, base: str, max_links: int = 50, page_url: Optional[str] = None) -> List[Dict[str, str]]:
    links = []
    seen = set()
    can_page = _canonical_no_frag_query(page_url) if page_url else None
    page_host = urlparse(page_url).netloc if page_url else None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        full = urljoin(base, href)
        can = _canonical_no_frag_query(full)
        if can_page and can == can_page:
            continue
        if _is_within(a, ("header", "nav", "footer")):
            continue
        host = urlparse(full).netloc
        if page_host and host != page_host and not is_pdf(full):
            continue
        if full in seen:
            continue
        seen.add(full)
        text = a.get_text(" ", strip=True)[:200]
        heading = _nearest_heading(a)
        flags = _link_flags(text, full)
        links.append({
            "text": text,
            "href": full,
            "context": _link_context(a),
            "heading": heading,
            **flags,
        })
        if len(links) >= max_links:
            break
    return links

def is_pdf(u: str) -> bool:
    try:
        return urlparse(u).path.lower().endswith(".pdf")
    except Exception:
        return False

def _canonical_no_frag_query(u: str) -> str:
    try:
        p = urlparse(u)
        path = (p.path or "").rstrip("/").lower()
        return f"{p.scheme}://{p.netloc}{path}"
    except Exception:
        return u

def _find_kendo_read_urls(soup: BeautifulSoup, base_url: str) -> List[str]:
    urls: List[str] = []
    try:
        for script in soup.find_all("script"):
            txt = script.string or script.get_text() or ""
            for m in re.finditer(r"transport\s*:\s*\{[^}]*read\s*:\s*(?:\{|\[)?\s*url\s*:\s*['\"]([^'\"]+)['\"]", txt, flags=re.I|re.S):
                u = m.group(1)
                if u:
                    urls.append(urljoin(base_url, u))
            for m in re.finditer(r"transport\s*:\s*\{[^}]*read\s*:\s*['\"]([^'\"]+)['\"]", txt, flags=re.I|re.S):
                u = m.group(1)
                if u and not u.lower().endswith(('.js', '.css')) and 'dataType' not in u:
                    urls.append(urljoin(base_url, u))
    except Exception:
        pass
    return list(dict.fromkeys(urls))

def _extract_request_verification_token(soup: BeautifulSoup) -> Optional[str]:
    try:
        inp = soup.find('input', attrs={'name': '__RequestVerificationToken'})
        if inp and inp.get('value'):
            return inp.get('value')
        meta = soup.find('meta', attrs={'name': '__RequestVerificationToken'})
        if meta and meta.get('content'):
            return meta.get('content')
    except Exception:
        pass
    return None

def _fetch_json(url: str, referer: Optional[str] = None, timeout: float = 20.0, session: Optional[requests.Session] = None, token: Optional[str] = None) -> Optional[Any]:
    try:
        headers = dict(UA_BASE)
        if referer:
            headers["Referer"] = referer
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
        headers["X-Requested-With"] = "XMLHttpRequest"
        params = {"page": 1, "pageSize": 50, "skip": 0, "take": 50}
        sess = session or requests.Session()
        r = sess.get(url, headers=headers, params=params, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            body = {"take": 50, "skip": 0, "page": 1, "pageSize": 50, "sort": []}
            headers_post = dict(headers)
            headers_post["Content-Type"] = "application/json"
            if token:
                headers_post["RequestVerificationToken"] = token
            r = sess.post(url, headers=headers_post, json=body, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r.json()
    except Exception:
        try:
            snippet = r.text[:300] if 'r' in locals() and hasattr(r, 'text') else ''
            logger.error(f"Failed to fetch Kendo JSON: {url} (status={getattr(r,'status_code',None)}) snippet={snippet}")
        except Exception:
            logger.exception(f"Failed to fetch Kendo JSON: {url}")
        return None

def _extract_items_from_kendo_json(data: Any, base_url: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    try:
        rows = []
        if isinstance(data, dict):
            for key in ("data", "Data", "results", "Results"):
                if key in data and isinstance(data[key], list):
                    rows = data[key]
                    break
            if not rows and isinstance(data.get("Data"), dict) and isinstance(data["Data"].get("items"), list):
                rows = data["Data"]["items"]
        elif isinstance(data, list):
            rows = data
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = (row.get("Title") or row.get("title") or row.get("Name") or row.get("name") or "").strip()
            file_url = (row.get("FileUrl") or row.get("Url") or row.get("url") or "").strip()
            exp = (row.get("DateExpiration") or row.get("ExpirationDate") or row.get("CloseDate") or row.get("Deadline") or "").strip()
            if not title and not file_url and not exp:
                continue
            href = urljoin(base_url, file_url) if file_url else base_url
            ctx_bits = []
            if title:
                ctx_bits.append(title)
            if exp:
                ctx_bits.append(f"Expiration Date: {exp}")
            context = " | ".join(ctx_bits)
            out.append({
                "text": title or (file_url or "(item)"),
                "href": href,
                "context": context,
                "heading": "",
                **_link_flags(title or file_url, href),
            })
    except Exception:
        logger.exception("Failed to parse Kendo JSON structure")
    return out

def _find_iframe_srcs(soup: BeautifulSoup, base_url: str) -> List[str]:
    srcs: List[str] = []
    try:
        for f in soup.find_all("iframe"):
            src = (f.get("src") or "").strip()
            if src:
                srcs.append(urljoin(base_url, src))
    except Exception:
        pass
    return list(dict.fromkeys(srcs))
