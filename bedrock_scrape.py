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
from sqlalchemy import create_engine, select, text, Table, Column, String, MetaData, LargeBinary

from configuration_values import ConfigurationValues
from detail_extractor import extract_detail, extract_detail_content
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

def sanitize_text(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    return re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", " ", val)

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

_GENERIC_TITLE_PATTERNS = [
    re.compile(r"^request for proposals?$", re.I),
    re.compile(r"^invitation for bids?$", re.I),
    re.compile(r"^invitation to bid$", re.I),
    re.compile(r"^request for qualifications?$", re.I),
    re.compile(r"^request for information$", re.I),
    re.compile(r"^notice of (funding|funds) opportunity$", re.I),
    re.compile(r"^notice of funding availability$", re.I),
    re.compile(r"^rfp$", re.I),
]

def is_generic_title(t: Optional[str]) -> bool:
    if not t:
        return True
    tt = t.strip()
    if len(tt) < 6:
        return True
    core = re.sub(r"^(rfp|rfa|rfq)\s*#?\d+[-: ]+", "", tt, flags=re.I).strip()
    for pat in _GENERIC_TITLE_PATTERNS:
        if pat.fullmatch(core.lower()):
            return True
    return False

def init_processed_table(engine):
    """Create processed_rfps table (idempotent). Duplicated locally to avoid circular import with main."""
    metadata = MetaData(schema='public')
    processed = Table(
        'processed_rfps', metadata,
        Column('hash', String, primary_key=True),
        Column('title', String),
        Column('url', String),
        Column('site', String),
        Column('processed_at', String),
        Column('detail_content', String),
        Column('ai_summary', String),
        Column('pdf_content', LargeBinary),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE public.processed_rfps 
            ADD COLUMN IF NOT EXISTS detail_content TEXT,
            ADD COLUMN IF NOT EXISTS ai_summary TEXT,
            ADD COLUMN IF NOT EXISTS pdf_content BYTEA;
        """))
    return processed

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
Return strict JSON only, no comments or markdown. IMPORTANT: Only include an item if the date you rely on is clearly a submission / application / proposal deadline (NOT just a posted/published/announcement date). If the only visible date is a posted/publish date, include the item, it should only be excluded if you are certain it is past the deadline. Your answer will be evaluated primarily by whether detail_link_index correctly references a link in "Top links" that provides specific details for the item.
"""

PROMPT_TEMPLATE = """You are analyzing a single web page for RFP/Opportunity items.
You are given:
1) A plain-text snapshot of the page (truncated).
2) A list of anchor links (text + href).
3) A list of existing items already in the database (title + url).
 4) Today's date (YYYY-MM-DD): {today}

Task:
- Identify any new RFP/Opportunity items not already in the database (exclude jobs/employment postings).
- Prefer concrete detail pages or direct PDF links if available.
- detail_source_url must be selected from the provided Top links (anchor list) or be a direct .pdf link on the same site. Do not repeat the page URL unless the page is itself a single-item detail page.
- Only include an item if you can determine a future submission/proposal/application deadline (words like "Due", "Deadline", "Closing Date", "Applications Due", "Proposal Due"). If only a posted/published date is present, EXCLUDE the item. If multiple deadlines, choose the primary final proposal deadline.
- Ignore or omit items whose deadline is before today's date.
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
- Exclude items where the only date is clearly a posted/announcement date (e.g., "June 6, 2025" under an author name without deadline wording). You must see deadline-related wording.

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
    #today = "2025-06-08"  
    return PROMPT_TEMPLATE.format(
        existing=existing_lines or "(none)",
        text=page_text,
    links=link_lines,
    page_url=page_url,
    today=today,
    )

NAV_SYSTEM = (
    "You are navigating toward the actual full RFP page or PDF. "
    "At every hop you are given the current page text and its links. "
    "Decide if CURRENT page is the final RFP (full opportunity details including scope, deadlines, funding, how to apply). "
    "If yes, return status='final' and no next_link_index. If not, select the single most promising link index to continue navigation. "
    "Prefer links that look like they contain full details, PDF downloads, application packets, or solicitations. Avoid navigation loops and generic site pages."
)

NAV_PROMPT_TEMPLATE = """CURRENT PAGE URL: {page_url}
HOP: {hop}/{max_hops}
TODAY: {today}

Existing final RFPs (titles) for this site (context only):
{existing_titles}

Page text (truncated):
<<<PAGE_TEXT_START>>>
{page_text}
<<<PAGE_TEXT_END>>>

Links (indexed):
{links}

Return ONLY strict JSON with this schema:
{{
    "status": "final" | "continue" | "give_up",
    "reason": "short explanation",
    "final": {{
            "title": "string (required if status=final)",
            "url": "string (absolute, required if status=final)"
    }} ,
    "next_link_index": integer (required if status=continue)
}}

Rules:
- status=final only if this page or a direct PDF link is clearly the full RFP.
- status=continue if you are confident another link leads closer to the RFP; pick best next_link_index.
- status=give_up if page is unrelated or no meaningful path after careful inspection.
- No markdown, comments, or extra keys.
"""

def build_nav_prompt(page_text: str, links: List[Dict[str, str]], existing: List[Dict[str, str]], page_url: str, hop: int, max_hops: int) -> str:
    existing_titles = ", ".join(e.get('title','').strip() for e in existing[:40] if e.get('title')) or "(none)"
    def fmt(l: Dict[str, Any], i: int) -> str:
        return (
            f"- [{i}] {l.get('text','')} -> {l.get('href','')}"
            f" | heading: {l.get('heading','')}"
            f" | flags: learn_more={l.get('is_learn_more', False)}, apply={l.get('is_apply', False)}, pdf={l.get('is_pdf', False)}, depth={l.get('depth',0)}"
        )
    link_lines = "\n".join(fmt(l, i) for i, l in enumerate(links))
    today = time.strftime("%Y-%m-%d", time.gmtime())
    return NAV_PROMPT_TEMPLATE.format(
        page_url=page_url,
        hop=hop,
        max_hops=max_hops,
        today=today,
        existing_titles=existing_titles,
        page_text=page_text,
        links=link_lines,
    )

def _canonical_no_frag_query(u: str) -> str:
    try:
        p = urlparse(u)
        path = (p.path or "").rstrip("/").lower()
        return f"{p.scheme}://{p.netloc}{path}"
    except Exception:
        return u

def upsert_new_items(engine, processed_table, site_name: str, items: List[Dict[str, Any]], page_url: str, links: List[Dict[str, str]], max_hops: int, per_page_max_text: int) -> List[Dict[str, Any]]:
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

            original_title = title
            final_url, final_title, final_text = navigate_to_final(detail_src, existing=[], max_hops=max_hops, per_page_max_text=per_page_max_text)
            if not final_url or not final_text:
                logger.info(f"Navigation failed to resolve final RFP for '{original_title}'")
                continue
            chosen_title = original_title
            if final_title and not is_generic_title(final_title) and is_generic_title(original_title):
                chosen_title = final_title.strip()
            pdf_bytes = None
            if is_pdf(final_url):
                try:
                    headers = dict(UA_BASE)
                    headers["Referer"] = url
                    rpdf = requests.get(final_url, headers=headers, timeout=30, allow_redirects=True)
                    if rpdf.status_code == 200 and rpdf.content:
                        pdf_bytes = rpdf.content
                except Exception:
                    logger.exception(f"Failed to download final PDF {final_url}")
            detail_content = (final_text or "")[:MAX_DETAIL_TEXT_CHARS]
            ai_summary = None
            if detail_content.strip():
                try:
                    content_hash = hashlib.sha256(detail_content.encode('utf-8')).hexdigest()
                    if content_hash in summary_cache:
                        ai_summary = summary_cache[content_hash]
                    else:
                        ai_summary = summarize_rfp(detail_content)
                        if ai_summary:
                            summary_cache[content_hash] = ai_summary
                except Exception:
                    logger.exception(f"Failed to summarize final page for {final_url}")
            detail_content = sanitize_text(detail_content) or None
            if ai_summary:
                ai_summary = sanitize_text(ai_summary)
            conn.execute(
                processed_table.insert().values(
                    hash=h,
                    title=chosen_title,
                    url=final_url,
                    site=site_name,
                    processed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    detail_content=detail_content or None,
                    ai_summary=ai_summary,
                    pdf_content=pdf_bytes,
                )
            )
            new_rows.append({
                "title": chosen_title,
                "url": final_url,
                "detail_source_url": final_url,
                "hash": h,
                "has_detail": bool(detail_content),
                "ai_summary": ai_summary,
            })
            logger.info(f"Inserted (final): {chosen_title} -> {final_url}")
    return new_rows

def _fetch_links_and_text(url: str, max_text: int = 20000, max_links: int = 120) -> Tuple[str, List[Dict[str,str]]]:
    soup = fetch_page(url)
    txt = soup_text(soup, max_chars=max_text)
    lnks = gather_links(soup, url, max_links=max_links, page_url=url)
    return txt, lnks

def navigate_to_final(start_url: str, existing: List[Dict[str,str]], max_hops: int, per_page_max_text: int = 16000) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Iteratively call Bedrock to reach a final RFP page.
    Returns (final_url, final_title, final_page_text) or (None,None,None).
    """
    visited = set()
    current_url = start_url
    final_title = None
    for hop in range(1, max_hops + 1):
        if current_url in visited:
            logger.info(f"Loop detected at {current_url}; aborting navigation")
            return None, None, None
        visited.add(current_url)
        try:
            page_text, page_links = _fetch_links_and_text(current_url, max_text=per_page_max_text)
        except Exception:
            logger.exception(f"Failed to fetch during navigation: {current_url}")
            return None, None, None
        if is_pdf(current_url):
            return current_url, "(PDF)" if not final_title else final_title, page_text
        nav_prompt = build_nav_prompt(page_text, page_links, existing, current_url, hop, max_hops)
        try:
            raw = call_bedrock(nav_prompt, system=NAV_SYSTEM, temperature=0.0, max_tokens=1200)
            decision = extract_json(raw)
        except Exception:
            logger.exception("Navigation model call failed; stopping")
            return None, None, None
        status = (decision.get('status') or '').lower()
        if status == 'final':
            fin = decision.get('final') or {}
            fu = (fin.get('url') or current_url).strip()
            final_title = (fin.get('title') or '').strip() or final_title or '(untitled RFP)'
            if is_pdf(fu):
                return fu, final_title, page_text
            if fu == current_url:
                return fu, final_title, page_text
            try:
                new_text, _links = _fetch_links_and_text(fu, max_text=per_page_max_text)
            except Exception:
                logger.exception(f"Failed to fetch declared final URL {fu}")
                return None, None, None
            return fu, final_title, new_text
        if status == 'give_up':
            logger.info(f"Navigation gave up at hop {hop} for {start_url}")
            return None, None, None
        if status == 'continue':
            idx = decision.get('next_link_index')
            if isinstance(idx, int) and 0 <= idx < len(page_links):
                nxt = page_links[idx]['href']
                if is_pdf(nxt):
                    try:
                        text, pdf_url = extract_detail(nxt, referer=current_url)
                        if pdf_url and text:
                            return pdf_url, page_links[idx].get('text') or '(PDF)', text
                    except Exception:
                        logger.exception(f"Failed PDF extraction {nxt}")
                        return None, None, None
                current_url = nxt
                continue
            else:
                logger.info(f"Invalid next_link_index at hop {hop}; aborting navigation")
                return None, None, None
        logger.info(f"Unknown status '{status}' from navigation model; aborting")
        return None, None, None
    logger.info(f"Reached hop limit ({max_hops}) without final RFP: {start_url}")
    return None, None, None

def main():
    parser = argparse.ArgumentParser(description="LLM-driven RFP probe (single URL)")
    parser.add_argument("--url", required=True, help="Page URL to analyze")
    parser.add_argument("--site", default=None, help="Site name to store (default = domain)")
    parser.add_argument("--max-text", type=int, default=16000)
    parser.add_argument("--max-links", type=int, default=400)
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--max-hops", type=int, default=int(os.getenv("MAX_RFP_HOPS", "5")))
    parser.add_argument("--nav-page-max-text", type=int, default=int(os.getenv("NAV_PAGE_MAX_TEXT", "16000")))
    parser.add_argument("--timeout-read", type=float, default=60.0)
    parser.add_argument("--timeout-connect", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--no-system-prompt", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--region", default=None)
    parser.add_argument("--endpoint", default=None)
    default_log_raw = os.getenv("LOG_BEDROCK_RAW", "").strip().lower() in ("1", "true", "yes", "on")
    default_log_raw_chars = int(os.getenv("LOG_BEDROCK_RAW_CHARS", "2000"))
    parser.add_argument("--log-bedrock-raw", action="store_true", default=default_log_raw)
    parser.add_argument("--log-bedrock-raw-chars", type=int, default=default_log_raw_chars)
    args = parser.parse_args()

    new_rows = process_listing(
        args.url,
        site_name=args.site,
        engine=None,
        max_text=args.max_text,
        max_links=args.max_links,
        max_items=args.max_items,
        max_hops=args.max_hops,
        nav_page_max_text=args.nav_page_max_text,
        timeout_read=args.timeout_read,
        timeout_connect=args.timeout_connect,
        retries=args.retries,
        no_system_prompt=args.no_system_prompt,
        temperature=args.temperature,
        model_id=args.model_id,
        region=args.region,
        endpoint=args.endpoint,
        log_bedrock_raw=args.log_bedrock_raw,
        log_bedrock_raw_chars=args.log_bedrock_raw_chars,
    )
    if not new_rows:
        print("No new items detected.")
    else:
        print("Inserted new items:")
        for r in new_rows:
            print(f"- {r['title']} ({r['url']}) [detail: {r['has_detail']}]")


def process_listing(listing_url: str, site_name: Optional[str], engine=None, *, max_text: int = 16000, max_links: int = 400, max_items: Optional[int] = None,
                    max_hops: int = 5, nav_page_max_text: int = 16000, timeout_read: float = 60.0, timeout_connect: float = 10.0, retries: int = 2,
                    no_system_prompt: bool = False, temperature: float = 0.0, model_id: Optional[str] = None, region: Optional[str] = None,
                    endpoint: Optional[str] = None, log_bedrock_raw: bool = False, log_bedrock_raw_chars: int = 2000) -> List[Dict[str, Any]]:
    domain = urlparse(listing_url).netloc
    site = site_name or domain
    created_engine = False
    if engine is None:
        engine = create_engine(ConfigurationValues.get_pgvector_connection())
        created_engine = True
    processed = init_processed_table(engine)
    soup = fetch_page(listing_url)
    page_text = soup_text(soup, max_chars=max_text)
    links = gather_links(soup, listing_url, max_links=max_links, page_url=listing_url)
    existing = load_existing(engine, domain, limit=200)
    prompt = build_prompt(page_text, links, existing, page_url=listing_url)
    system_prompt = None if no_system_prompt else SYSTEM_PROMPT
    chosen_model = (model_id or os.getenv("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID).strip()
    chosen_region = (region or os.getenv("BEDROCK_REGION") or DEFAULT_REGION).strip()
    chosen_endpoint = (endpoint or os.getenv("BEDROCK_ENDPOINT") or build_bedrock_endpoint(chosen_model, chosen_region)).strip()
    logger.info(f"Using Bedrock model={chosen_model} region={chosen_region} for listing {listing_url}")
    try:
        raw = call_bedrock(
            prompt,
            timeout_read=timeout_read,
            timeout_connect=timeout_connect,
            retries=retries,
            log_raw=bool(log_bedrock_raw),
            log_raw_chars=int(log_bedrock_raw_chars),
            system=system_prompt,
            temperature=temperature,
            bedrock_url=chosen_endpoint,
        )
        parsed = extract_json(raw)
    except Exception:
        logger.exception("Bedrock call failed or returned invalid JSON for listing page")
        if created_engine:
            engine.dispose()
        return []
    items = parsed.get("items") or []
    if not isinstance(items, list):
        logger.error(f"Unexpected JSON schema: {parsed}")
        if created_engine:
            engine.dispose()
        return []
    if max_items is not None:
        items = items[: max(0, int(max_items))]
    new_rows = upsert_new_items(
        engine,
        processed,
        site,
        items,
        page_url=listing_url,
        links=links,
        max_hops=max_hops,
        per_page_max_text=nav_page_max_text,
    )
    if created_engine:
        engine.dispose()
    return new_rows

if __name__ == "__main__":
    main()