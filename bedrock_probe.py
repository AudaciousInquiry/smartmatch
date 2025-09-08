import os
import sys
import json
import re
import time
from datetime import datetime, timezone
import random
import hashlib
import argparse
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from requests import ReadTimeout, ConnectTimeout
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy import create_engine, select, text

from configuration_values import ConfigurationValues
from detail_extractor import extract_detail, extract_detail_content
from main import init_processed_table
from bedrock_utils import summarize_rfp

DEFAULT_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
DEFAULT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
DEFAULT_ENDPOINT = os.getenv("BEDROCK_ENDPOINT", f"https://bedrock-runtime.{DEFAULT_REGION}.amazonaws.com/model/{DEFAULT_MODEL_ID}/invoke")

UA_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_DETAIL_TEXT_CHARS = int(os.getenv("MAX_DETAIL_TEXT_CHARS", "400000"))

def build_bedrock_endpoint(model_id: str, region: str) -> str:
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/invoke"

def _post_with_retries(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: Tuple[float, float],
    retries: int,
) -> requests.Response:
    attempt = 0
    last_exc: Optional[Exception] = None
    while attempt <= retries:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code in (429,) or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            return resp
        except (ReadTimeout, ConnectTimeout, requests.ConnectionError, requests.HTTPError) as e:
            last_exc = e
            if attempt == retries:
                break
            backoff = min(2 ** attempt, 10) + random.uniform(0, 0.5)
            logger.warning(f"Bedrock request failed (attempt {attempt+1}/{retries+1}): {e}; retrying in {backoff:.1f}s")
            time.sleep(backoff)
            attempt += 1
    assert last_exc is not None
    raise last_exc


def call_bedrock(
    prompt: str,
    max_tokens: int = 8000,
    timeout_read: float = 60.0,
    timeout_connect: float = 10.0,
    retries: int = 2,
    log_raw: bool = False,
    log_raw_chars: int = 2000,
    system: Optional[str] = None,
    temperature: Optional[float] = 0.0,
    bedrock_url: Optional[str] = None,
) -> str:
    api_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not api_key:
        raise RuntimeError("Set AWS_BEARER_TOKEN_BEDROCK")

    payload: Dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }
    if system:
        payload["system"] = system
    if temperature is not None:
        payload["temperature"] = temperature
    endpoint = bedrock_url or DEFAULT_ENDPOINT
    logger.debug(f"Bedrock prompt size: {len(prompt)} chars; endpoint={endpoint}")
    resp = _post_with_retries(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        payload=payload,
        timeout=(timeout_connect, timeout_read),
        retries=retries,
    )
    logger.info(f"Bedrock HTTP {resp.status_code}")
    if log_raw:
        req_id = resp.headers.get("x-amzn-requestid") or resp.headers.get("x-amzn-request-id")
        body = resp.text or ""
        truncated = body[:log_raw_chars]
        note = " (truncated)" if len(body) > len(truncated) else ""
        if req_id:
            logger.debug(f"Bedrock response requestId={req_id}; content-type={resp.headers.get('content-type')}")
        logger.debug(f"Bedrock raw response first {len(truncated)} chars{note}:\n{truncated}")
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception:
        txt = resp.text[:500]
        raise RuntimeError(f"Bedrock non-JSON response (first 500 chars): {txt}")
    return data.get("content", [{}])[0].get("text", "")

def extract_json(text_out: str) -> Dict[str, Any]:
    s = text_out.strip()
    if s.startswith("```"):
        s = "\n".join(s.splitlines()[1:])
        if s.rstrip().endswith("```"):
            s = "\n".join(s.splitlines()[:-1])
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = s[start : end + 1]
        for _ in range(3):
            try:
                return json.loads(candidate)
            except Exception:
                candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
                candidate = re.sub(r"//.*?$", "", candidate, flags=re.M)
                candidate = re.sub(r"/\*.*?\*/", "", candidate, flags=re.S)
                candidate = candidate.replace("\r", "\\r").replace("\t", " ")
                candidate = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", " ", candidate)
                def _esc(js: str) -> str:
                    out = []
                    in_str = False
                    esc = False
                    q = ''
                    for ch in js:
                        if esc:
                            out.append(ch)
                            esc = False
                            continue
                        if ch == '\\':
                            out.append(ch)
                            esc = True
                            continue
                        if ch in ('"', "'"):
                            if not in_str:
                                in_str = True
                                q = ch
                            elif q == ch:
                                in_str = False
                            out.append(ch)
                            continue
                        if in_str and ch == '\n':
                            out.append('\\n'); continue
                        if in_str and ch == '\r':
                            out.append('\\r'); continue
                        if in_str and ord(ch) < 0x20:
                            out.append(' '); continue
                        out.append(ch)
                    return ''.join(out)
                candidate = _esc(candidate).strip()
    m = re.search(r'"items"\s*:\s*\[', s)
    items: List[Dict[str, Any]] = []
    if m:
        idx = m.end()
        bracket = 1
        j = idx
        while j < len(s) and bracket > 0:
            ch = s[j]
            if ch == '[':
                bracket += 1
            elif ch == ']':
                bracket -= 1
            j += 1
        items_block = s[idx:j-1] if bracket == 0 else s[idx:]
        parts = re.split(r'}\s*,\s*\{', items_block.strip().strip('[]').strip())
        for part in parts:
            frag = part.strip()
            if not frag:
                continue
            if not frag.startswith('{'):
                frag = '{' + frag
            if not frag.endswith('}'):
                frag = frag + '}'
            frag = re.sub(r",\s*([}\]])", r"\1", frag)
            frag = re.sub(r"//.*?$", "", frag, flags=re.M)
            frag = re.sub(r"/\*.*?\*/", "", frag, flags=re.S)
            frag = frag.replace("\r", "\\r").replace("\t", " ")
            frag = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", " ", frag)
            try:
                obj = json.loads(frag)
                if isinstance(obj, dict) and 'title' in obj and 'url' in obj:
                    items.append(obj)
            except Exception:
                continue
    if items:
        return {"items": items}
    obj_re = re.compile(r"\{[^{}]*\"title\"\s*:\s*\"[^\"]+\"[^{}]*\"url\"\s*:\s*\"[^\"]+\"[^{}]*\}")
    for mm in obj_re.finditer(s):
        frag = mm.group(0)
        frag = re.sub(r",\s*([}\]])", r"\1", frag)
        frag = re.sub(r"//.*?$", "", frag, flags=re.M)
        frag = re.sub(r"/\*.*?\*/", "", frag, flags=re.S)
        frag = frag.replace("\r", "\\r").replace("\t", " ")
        frag = re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", " ", frag)
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict) and 'title' in obj and 'url' in obj:
                items.append(obj)
        except Exception:
            continue
    if items:
        return {"items": items}
    raise ValueError("Failed to parse JSON from model output")

def soup_text(soup: BeautifulSoup, max_chars: int = 20000) -> str:
    txt = soup.get_text(separator="\n", strip=True)
    return txt[:max_chars]

def _link_context(a: Any, max_len: int = 500) -> str:
    try:
        node = a
        for _ in range(4):
            if node is None:
                break
            if getattr(node, "name", None) in ("li", "article", "section", "div"):
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

def fetch_page(url: str) -> BeautifulSoup:
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    headers = dict(UA_BASE)
    headers["Referer"] = origin
    resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def load_existing(engine, domain: str, limit: int = 200) -> List[Dict[str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT title, url
                FROM public.processed_rfps
                WHERE url ILIKE :pat
                ORDER BY processed_at DESC
                LIMIT :lim
            """),
            {"pat": f"%{domain}%", "lim": limit},
        ).mappings().all()
        if rows:
            return [dict(r) for r in rows]
        rows = conn.execute(
            text("""
                SELECT title, url
                FROM public.processed_rfps
                ORDER BY processed_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).mappings().all()
        return [dict(r) for r in rows]

def is_pdf(u: str) -> bool:
    try:
        return urlparse(u).path.lower().endswith(".pdf")
    except Exception:
        return False

def _resolve_final_pdf(start_url: str, referer: str, max_secondary_links: int = 8, timeout: int = 20) -> Tuple[Optional[str], Optional[str]]:
    """Attempt up to two hops to resolve and extract a final PDF.
    Returns (pdf_text, pdf_url) or (None, None).
    Hop 0/1 handled by extract_detail (direct or linked PDF within page)
    Hop 2: probe a small set of candidate sub-links if first pass didn't yield a PDF.
    """
    try:
        text, pdf_url = extract_detail(start_url, referer=referer)
        if pdf_url and text:
            return text, pdf_url
        headers = dict(UA_BASE)
        headers["Referer"] = referer
        r = requests.get(start_url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type", "").lower()):
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")
        candidates: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#"):
                continue
            full = urljoin(start_url, href)
            if is_pdf(full):
                try:
                    t2, p2 = extract_detail(full, referer=start_url)
                    if p2 and t2:
                        return t2, p2
                except Exception:
                    logger.exception(f"Secondary direct PDF failed: {full}")
                continue
            low = full.lower()
            if any(k in low for k in ["rfp", "request", "proposal", "fund", "grant", "apply", "solicit", "download", "application"]):
                candidates.append(full)
            if len(candidates) >= max_secondary_links:
                break
        seen = set()
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            try:
                t3, p3 = extract_detail(cand, referer=start_url)
                if p3 and t3:
                    return t3, p3
            except Exception:
                logger.exception(f"Secondary hop failed: {cand}")
        return None, None
    except Exception:
        logger.exception(f"_resolve_final_pdf fatal error for {start_url}")
        return None, None

def _find_due_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    t = ' '.join(text.split())
    patterns = [
        r"(due\s*(date|by|\son)?|deadline|closing\s*date|applications?\s*due|submissions?\s*due|responses?\s*due|proposals?\s*due|bids?\s*due|submission\s*deadline)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
        r"(due\s*(date|by|\son)?|deadline|closing\s*date|applications?\s*due|submissions?\s*due|responses?\s*due|proposals?\s*due|bids?\s*due|submission\s*deadline)\s*[:\-]?\s*(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})",
        r"(due\s*(date|by|\son)?|deadline|closing\s*date|applications?\s*due|submissions?\s*due|responses?\s*due|proposals?\s*due|bids?\s*due|submission\s*deadline)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        r"(due\s*(date|by|\son)?|deadline|closing\s*date|applications?\s*due|submissions?\s*due|responses?\s*due|proposals?\s*due|bids?\s*due|submission\s*deadline)\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]
    def parse_date(ds: str) -> Optional[datetime]:
        ds = ds.strip()
        fmts = [
            "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y",
            "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%m-%d-%Y", "%m-%d-%y",
        ]
        for f in fmts:
            try:
                return datetime.strptime(ds, f)
            except Exception:
                continue
        return None
    for pat in patterns:
        m = re.search(pat, t, flags=re.I)
        if m:
            ds = m.group(m.lastindex)
            dt = parse_date(ds)
            if dt:
                return dt
    generic = [
        r"([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})",
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]
    for pat in generic:
        m = re.search(pat, t, flags=re.I)
        if m:
            ds = m.group(1)
            try:
                return datetime.fromisoformat(ds)
            except Exception:
                pass
            return _find_due_date(ds)
    return None

def filter_expired_items(items: List[Dict[str, Any]], links: List[Dict[str, str]], today: datetime, page_url: str) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for it in items:
        idx = it.get("detail_link_index")
        snippet = (it.get("content_snippet") or "")
        title = (it.get("title") or "")
        texts = [title, snippet]
        if isinstance(idx, int) and 0 <= idx < len(links):
            ln = links[idx]
            texts.extend([ln.get("text") or "", ln.get("heading") or "", ln.get("context") or ""])
        combined = " \n ".join(t for t in texts if t)
        due = _find_due_date(combined)
        if not due and isinstance(idx, int) and 0 <= idx < len(links):
            href = links[idx].get("href") or ""
            if href and not is_pdf(href):
                try:
                    headers = dict(UA_BASE)
                    headers["Referer"] = page_url
                    r = requests.get(href, headers=headers, timeout=10, allow_redirects=True)
                    if r.status_code == 200 and "html" in (r.headers.get("content-type", "").lower()):
                        sub = BeautifulSoup(r.text, "html.parser")
                        txt = soup_text(sub, max_chars=5000)
                        due = _find_due_date(txt)
                except Exception:
                    pass
        if due and due.date() < today.date():
            logger.info(f"Dropping expired item: {title} (due {due.date()} < {today.date()})")
            continue
        kept.append(it)
    return kept

SYSTEM_PROMPT = """
You are a careful web analysis assistant. When returning detail_source_url:
- It MUST be chosen from the list under "Top links" or be a direct .pdf link.
- Do NOT use the page URL unless it is clearly a single-item detail page (rare for listing pages).
- Prefer links whose local context mentions the item title or contains descriptive details (e.g., Learn more, Apply, Details, PDF).
- Prefer deeper, specific paths over general section pages.
- If you cannot find a suitable detail link for an item, OMIT that item.
Prefer links that:
- are marked is_learn_more=true,
- or have a nearest heading matching the item title,
- or are is_pdf=true and clearly about the item,
and avoid links where is_generic_listing=true.
Return strict JSON only, no comments or markdown. Your answer will be evaluated primarily by whether detail_link_index correctly references a link in "Top links" that provides specific details for the item.
"""

PROMPT_TEMPLATE = """You are analyzing a single web page for RFP/Opportunity items.
You are given:
1) A plain-text snapshot of the page (truncated).
2) A list of anchor links (text + href).
3) A list of existing items already in the database (title + url).
 4) Today's date (YYYY-MM-DD): {today}

Task:
- Identify any new RFP/Opportunity items not already in the database, be careful that they are RFPs and not employment opportunities or anything else.
- Prefer concrete detail pages or direct PDF links if available.
- detail_source_url must be selected from the provided Top links (anchor list) or be a direct .pdf link on the same site. Do not repeat the page URL unless the page is itself a single-item detail page.
- Ignore or omit items whose due date is before today's date. Look for phrases like Due Date, Applications Due, Deadline, Closing Date, etc., and compare against today's date. Make absolutely sure that we avoid these and do not bother processing them, the due date must be in the future for you to process it.
- Return ONLY strict JSON with this schema:

{{
  "items": [
    {{
      "title": "string (required)",
      "url": "string (required, human-friendly landing/detail URL)",
    "detail_link_index": "integer (required, index of the chosen link from Top links)",
    "detail_source_url": "string (optional, should equal the href of the chosen Top link)",
      "content_snippet": "string (optional, short excerpt from the page supporting the find)"
    }}
  ]
}}

Rules:
- Do not include markdown or comments. JSON only.
- Ensure URLs are absolute and valid (use the provided anchors).
- If nothing new is found, return {{"items":[]}}.
 - Listing page URL: {page_url}. Do NOT select this as a detail link.

Existing DB items (title,url):
{existing}

Page text (truncated):
\"\"\"
{text}
\"\"\"

Top links (indexed, with metadata):
{links}
"""

def build_prompt(page_text: str, links: List[Dict[str, str]], existing: List[Dict[str, str]], page_url: str) -> str:
    existing_lines = "\n".join(f"- {e.get('title','').strip()} | {e.get('url','').strip()}" for e in existing[:100])
    def fmt(l: Dict[str, Any], i: int) -> str:
        return (
            f"- [{i}] {l.get('text','')} -> {l.get('href','')}"
            f" | heading: {l.get('heading','')}"
            f" | context: {l.get('context','')}"
            f" | flags: learn_more={l.get('is_learn_more', False)}, apply={l.get('is_apply', False)}, pdf={l.get('is_pdf', False)}, generic_listing={l.get('is_generic_listing', False)}, depth={l.get('depth', 0)}"
        )
    link_lines = "\n".join(fmt(l, i) for i, l in enumerate(links))
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return PROMPT_TEMPLATE.format(
        existing=existing_lines or "(none)",
        text=page_text,
    links=link_lines,
    page_url=page_url,
    today=today,
    )

def _canonical_no_frag_query(u: str) -> str:
    try:
        p = urlparse(u)
        path = (p.path or "").rstrip("/").lower()
        return f"{p.scheme}://{p.netloc}{path}"
    except Exception:
        return u


def _score_detail_candidate(title: str, link_text: str, href: str, page_host: str) -> int:
    score = 0
    href_l = href.lower()
    text_l = (link_text or "").lower()
    if urlparse(href).netloc == page_host:
        score += 1
    if href_l.endswith(".pdf"):
        score += 6
    kw_href = ["learn", "read", "detail", "apply", "application", "rfp", "fund", "grant", "opportun", "workshop", "training", "solicit", "notice"]
    kw_text = ["learn more", "read more", "details", "apply", "application", "rfp", "request for proposals", "opportunity", "download", "pdf"]
    score += sum(1 for k in kw_href if k in href_l)
    score += sum(1 for k in kw_text if k in text_l)
    title_tokens = [t for t in (title or "").lower().split() if len(t) >= 5]
    if title_tokens:
        overlap = sum(1 for t in title_tokens if t in href_l or t in text_l)
        score += min(3, overlap)
    path_depth = (urlparse(href).path or "/").strip("/").count("/")
    score += min(3, path_depth)
    if href_l.endswith("/#") or href_l.endswith("#") or href_l.startswith("#"):
        score -= 4
    return score


def upsert_new_items(engine, processed_table, site_name: str, items: List[Dict[str, Any]], page_url: str, links: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    new_rows = []
    content_cache: Dict[str, Tuple[str, Optional[bytes]]] = {}
    summary_cache: Dict[str, str] = {}
    with engine.begin() as conn:
        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            detail_src = ""
            idx = item.get("detail_link_index")
            if not title or not url:
                continue
            if isinstance(idx, int) and 0 <= idx < len(links):
                mapped = links[idx].get("href") or ""
                if mapped:
                    logger.debug(f"Model selected detail_link_index={idx} -> {mapped}")
                    detail_src = mapped
            else:
                logger.warning(f"Skipping item '{title}': missing or invalid detail_link_index={idx}")
                continue
            if _canonical_no_frag_query(detail_src) == _canonical_no_frag_query(page_url):
                logger.warning(f"Skipping item '{title}': model selected listing URL as detail link")
                continue

            h = hashlib.sha256((title + url).encode("utf-8")).hexdigest()
            exists = conn.execute(
                select(processed_table.c.hash).where(processed_table.c.hash == h)
            ).first()
            if exists:
                logger.info(f"Skipping existing: {title}")
                continue

            pdf_text: Optional[str] = None
            final_pdf_url: Optional[str] = None
            pdf_bytes: Optional[bytes] = None
            cache_key = detail_src
            try:
                if cache_key in content_cache and content_cache[cache_key][0]:
                    pdf_text = content_cache[cache_key][0]
                else:
                    pdf_text, final_pdf_url = _resolve_final_pdf(detail_src, referer=url)
                    if final_pdf_url:
                        cache_key = final_pdf_url
                if final_pdf_url and cache_key not in content_cache:
                    headers = dict(UA_BASE)
                    headers["Referer"] = url
                    try:
                        rpdf = requests.get(final_pdf_url, headers=headers, timeout=30, allow_redirects=True)
                        if rpdf.status_code == 200 and rpdf.content:
                            pdf_bytes = rpdf.content
                        else:
                            logger.warning(f"PDF fetch non-200/empty for {final_pdf_url}: {rpdf.status_code}")
                    except Exception:
                        logger.exception(f"Download failed for {final_pdf_url}")
            except Exception:
                logger.exception(f"PDF resolution failed for {detail_src}")

            if not final_pdf_url or not pdf_text:
                logger.info(f"Skipping item '{title}' – no final PDF resolved after multi-hop")
                continue

            detail_content = pdf_text[:MAX_DETAIL_TEXT_CHARS]

            ai_summary = None
            try:
                content_hash = hashlib.sha256(detail_content.encode('utf-8')).hexdigest()
                if content_hash in summary_cache:
                    ai_summary = summary_cache[content_hash]
                else:
                    ai_summary = summarize_rfp(detail_content)
                    if ai_summary:
                        summary_cache[content_hash] = ai_summary
            except Exception:
                logger.exception(f"Failed to summarize PDF for {final_pdf_url}")

            if cache_key not in content_cache:
                content_cache[cache_key] = (detail_content, pdf_bytes)

            conn.execute(
                processed_table.insert().values(
                    hash=h,
                    title=title,
                    url=url,
                    site=site_name,
                    processed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    detail_content=detail_content or None,
                    ai_summary=ai_summary,
                    pdf_content=pdf_bytes,
                )
            )

            new_rows.append({
                "title": title,
                "url": url,
                "detail_source_url": final_pdf_url,
                "hash": h,
                "has_detail": bool(detail_content),
            })
            logger.info(f"Inserted (PDF): {title} ({url}) -> {final_pdf_url}")
    return new_rows

def main():
    parser = argparse.ArgumentParser(description="LLM-driven RFP probe (single URL)")
    parser.add_argument("--url", required=True, help="Page URL to analyze")
    parser.add_argument("--site", default=None, help="Site name to store (default = domain)")
    parser.add_argument("--max-text", type=int, default=16000, help="Max chars of page text sent to model")
    parser.add_argument("--max-links", type=int, default=400, help="Max links sent to model")
    parser.add_argument("--max-items", type=int, default=None, help="Max number of items to process from model output")
    parser.add_argument("--timeout-read", type=float, default=60.0, help="Bedrock read timeout (seconds)")
    parser.add_argument("--timeout-connect", type=float, default=10.0, help="Bedrock connect timeout (seconds)")
    parser.add_argument("--retries", type=int, default=2, help="Bedrock request retry count")
    parser.add_argument("--no-system-prompt", action="store_true", help="Do not send the stricter system prompt to the model")
    parser.add_argument("--temperature", type=float, default=0.0, help="Model temperature (0.0-1.0)")
    parser.add_argument("--model-id", default=None, help="Bedrock model ID to use (overrides env BEDROCK_MODEL_ID)")
    parser.add_argument("--region", default=None, help="Bedrock region (overrides env BEDROCK_REGION)")
    parser.add_argument("--endpoint", default=None, help="Full Bedrock endpoint URL (overrides model/region)")
    default_log_raw = os.getenv("LOG_BEDROCK_RAW", "").strip().lower() in ("1", "true", "yes", "on")
    default_log_raw_chars = int(os.getenv("LOG_BEDROCK_RAW_CHARS", "2000"))
    parser.add_argument("--log-bedrock-raw", action="store_true", default=default_log_raw, help="Log raw Bedrock response body at DEBUG level")
    parser.add_argument("--log-bedrock-raw-chars", type=int, default=default_log_raw_chars, help="Max chars of raw Bedrock response to log")
    args = parser.parse_args()

    target_url = args.url
    domain = urlparse(target_url).netloc
    site_name = args.site or domain

    engine = create_engine(ConfigurationValues.get_pgvector_connection())
    processed = init_processed_table(engine)

    soup = fetch_page(target_url)
    page_text = soup_text(soup, max_chars=args.max_text)
    links = gather_links(soup, target_url, max_links=args.max_links, page_url=target_url)
    existing = load_existing(engine, domain, limit=200)

    prompt = build_prompt(page_text, links, existing, page_url=target_url)
    system_prompt = None if args.no_system_prompt else SYSTEM_PROMPT

    chosen_model = (args.model_id or os.getenv("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID).strip()
    chosen_region = (args.region or os.getenv("BEDROCK_REGION") or DEFAULT_REGION).strip()
    chosen_endpoint = (args.endpoint or os.getenv("BEDROCK_ENDPOINT") or build_bedrock_endpoint(chosen_model, chosen_region)).strip()
    logger.info(f"Using Bedrock model={chosen_model} region={chosen_region}")

    try:
        raw = call_bedrock(
            prompt,
            timeout_read=args.timeout_read,
            timeout_connect=args.timeout_connect,
            retries=args.retries,
            log_raw=bool(args.log_bedrock_raw),
            log_raw_chars=int(args.log_bedrock_raw_chars),
            system=system_prompt,
            temperature=args.temperature,
            bedrock_url=chosen_endpoint,
        )
        parsed = extract_json(raw)
    except Exception:
        logger.exception("Bedrock call failed or returned invalid JSON")
        print("Bedrock call failed")
        sys.exit(1)

    items = parsed.get("items") or []
    if not isinstance(items, list):
        logger.error(f"Unexpected JSON schema: {parsed}")
        sys.exit(2)

    try:
        today_dt = datetime.now(timezone.utc)
        items = filter_expired_items(items, links, today_dt, target_url)
    except Exception:
        logger.exception("Expired-items filtering failed; proceeding without filter")

    if args.max_items is not None:
        items = items[: max(0, int(args.max_items))]

    new_rows = upsert_new_items(
        engine,
        processed,
        site_name,
        items,
        page_url=target_url,
        links=links,
    )

    if not new_rows:
        print("No new items detected.")
    else:
        print("Inserted new items:")
        for r in new_rows:
            print(f"- {r['title']} ({r['url']}) [detail: {r['has_detail']}]")

    engine.dispose()

if __name__ == "__main__":
    main()