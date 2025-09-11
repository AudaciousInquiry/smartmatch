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
from bs4 import BeautifulSoup
from loguru import logger
from sqlalchemy import create_engine, select, text, Table, Column, String, MetaData, LargeBinary
import requests
import llm_utils

from configuration_values import ConfigurationValues
from detail_extractor import extract_detail, extract_detail_content
import llm_utils
from scrape_utils import (
    UA_BASE,
    fetch_page,
    fetch_page_with_session,
    soup_text,
    _link_context,
    _nearest_heading,
    _link_flags,
    _is_within,
    gather_links,
    is_pdf,
    _canonical_no_frag_query,
    _find_kendo_read_urls,
    _extract_request_verification_token,
    _fetch_json,
    _extract_items_from_kendo_json,
    _find_iframe_srcs,
)

DEFAULT_REGION = llm_utils.DEFAULT_REGION
DEFAULT_MODEL_ID = llm_utils.DEFAULT_MODEL_ID
DEFAULT_ENDPOINT = os.getenv("BEDROCK_ENDPOINT", llm_utils.build_bedrock_endpoint(DEFAULT_MODEL_ID, DEFAULT_REGION))

 

MAX_DETAIL_TEXT_CHARS = int(os.getenv("MAX_DETAIL_TEXT_CHARS", "400000"))

def sanitize_text(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    return re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", " ", val)

 

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
            idx = item.get("detail_link_index")
            if not title or not url:
                continue
            if not isinstance(idx, int) or not (0 <= idx < len(links)):
                logger.warning(f"Skipping item '{title}': missing or invalid detail_link_index={idx}")
                continue
            detail_src = links[idx].get("href") or ""
            if not detail_src:
                continue
            if _canonical_no_frag_query(detail_src) == _canonical_no_frag_query(page_url):
                logger.warning(f"Skipping item '{title}': model selected listing URL as detail link")
                continue

            h = hashlib.sha256((title + url).encode("utf-8")).hexdigest()
            exists = conn.execute(select(processed_table.c.hash).where(processed_table.c.hash == h)).first()
            if exists:
                logger.info(f"Skipping existing: {title}")
                continue

            final_url, final_title, final_text = navigate_to_final(detail_src, existing=[], max_hops=max_hops, per_page_max_text=per_page_max_text)
            if not final_url or not final_text:
                logger.info(f"Navigation failed to resolve final RFP for '{title}'")
                continue

            if is_pdf(final_url) and (not final_text or len(final_text) < 50):
                try:
                    pdf_text, pdf_url = extract_detail(final_url, referer=page_url)
                    if pdf_text and pdf_url:
                        final_text = pdf_text
                        final_url = pdf_url
                except Exception:
                    logger.exception(f"Failed to extract PDF text for final URL {final_url}")
                    continue

            final_check = llm_utils.classify_final_page(final_text or "", final_url)
            status_lower = (final_check.get("status") or "").lower()
            enforce = os.getenv("FINAL_DATE_ENFORCE", "1").strip().lower() in ("1", "true", "yes", "on")
            if enforce:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                dline = final_check.get("deadline_iso")
                try:
                    if dline and len(dline) == 10 and dline <= today:
                        status_lower = "expired"
                except Exception:
                    pass
            if status_lower in ("expired", "unknown"):
                orig_status = (final_check.get('status') or '').lower()
                reason = final_check.get('reason') or ''
                dline = final_check.get('deadline_iso') or ''
                if enforce and dline and len(dline) == 10 and orig_status != status_lower:
                    logger.info(
                        f"Skipping '{title}' due to final page effective_status={status_lower} "
                        f"(overridden: orig_status={orig_status}, deadline_iso={dline} <= today={today}) reason={reason}"
                    )
                else:
                    if dline:
                        logger.info(f"Skipping '{title}' due to final page status={status_lower} deadline_iso={dline} reason={reason}")
                    else:
                        logger.info(f"Skipping '{title}' due to final page status={status_lower} reason={reason}")
                continue

            chosen_title = title
            if final_title and not is_generic_title(final_title) and is_generic_title(title):
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
                        ai_summary = llm_utils.summarize_rfp(detail_content)
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
            try:
                text, pdf_url = extract_detail(current_url, referer=current_url)
                if text and pdf_url:
                    return pdf_url, "(PDF)" if not final_title else final_title, text
            except Exception:
                logger.exception(f"Failed to extract PDF at {current_url}")
            return current_url, "(PDF)" if not final_title else final_title, page_text
        nav_prompt = llm_utils.build_nav_prompt(page_text, page_links, existing, current_url, hop, max_hops)
        try:
            raw = llm_utils.call_bedrock(nav_prompt, system=llm_utils.SCRAPE_NAV_SYSTEM, temperature=0.0, max_tokens=1200)
            decision = llm_utils.extract_json(raw)
        except Exception:
            logger.exception("Navigation model call failed; stopping")
            return None, None, None
        status = (decision.get('status') or '').lower()
        reason = decision.get('reason') or ''
        try:
            logger.info(f"NAV: hop={hop} status={status} reason={reason[:180]} url={current_url}")
        except Exception:
            pass
        if status == 'final':
            fin = decision.get('final') or {}
            fu = (fin.get('url') or current_url).strip()
            final_title = (fin.get('title') or '').strip() or final_title or '(untitled RFP)'
            if is_pdf(fu):
                try:
                    text, pdf_url = extract_detail(fu, referer=current_url)
                    if text and pdf_url:
                        return pdf_url, final_title, text
                except Exception:
                    logger.exception(f"Failed to extract declared final PDF {fu}")
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
        if status == 'expired':
            logger.info(f"Navigation detected expired at hop {hop} for {start_url}")
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
    session = requests.Session()
    soup = fetch_page_with_session(session, listing_url)

    page_text = soup_text(soup, max_chars=max_text)
    links = gather_links(soup, listing_url, max_links=max_links, page_url=listing_url)

    try:
        kendo_urls = _find_kendo_read_urls(soup, listing_url)
        token = _extract_request_verification_token(soup)
        kendo_items: List[Dict[str, str]] = []
        for ku in kendo_urls[:3]: 
            data = _fetch_json(ku, referer=listing_url, session=session, token=token)
            if data is None:
                continue
            kendo_items.extend(_extract_items_from_kendo_json(data, listing_url))
        if kendo_items:
            logger.info(f"Augmented {len(kendo_items)} Kendo items into Top links")
            links = kendo_items[:max(0, max_links//2)] + links
            ktxt_lines = ["KENDO GRID (synthesized):"]
            for it in kendo_items[:20]:
                ktxt_lines.append(f"- {it.get('text','')} | {it.get('context','')} | {it.get('href','')}")
            page_text = ("\n".join(ktxt_lines) + "\n\n" + page_text)[:max_text]
    except Exception:
        logger.exception("Kendo augmentation failed")

    try:
        iframe_srcs = _find_iframe_srcs(soup, listing_url)
        for isrc in iframe_srcs[:2]:
            try:
                if_soup = fetch_page_with_session(session, isrc)
                iframe_links = gather_links(if_soup, isrc, max_links=80, page_url=isrc)
                if iframe_links:
                    links.extend(iframe_links)
            except Exception:
                logger.exception(f"Failed to fetch iframe content: {isrc}")
        seen_hrefs = set()
        deduped: List[Dict[str, str]] = []
        for l in links:
            h = l.get("href")
            if not h or h in seen_hrefs:
                continue
            seen_hrefs.add(h)
            deduped.append(l)
        links = deduped[:max_links]
    except Exception:
        logger.exception("Iframe augmentation failed")

    try:
        sample = "\n".join(f"- [{i}] {l.get('text','')} -> {l.get('href','')} | ctx: {l.get('context','')[:120]}" for i, l in enumerate(links[:20]))
        logger.info(f"Top links sample ({min(20, len(links))}/{len(links)}):\n{sample}")
    except Exception:
        pass
    existing = load_existing(engine, domain, limit=200)
    prompt = llm_utils.build_prompt(page_text, links, existing, page_url=listing_url)
    system_prompt = None if no_system_prompt else llm_utils.SCRAPE_SYSTEM_PROMPT
    chosen_model = (model_id or os.getenv("BEDROCK_MODEL_ID") or llm_utils.DEFAULT_MODEL_ID).strip()
    chosen_region = (region or os.getenv("BEDROCK_REGION") or llm_utils.DEFAULT_REGION).strip()
    chosen_endpoint = (endpoint or os.getenv("BEDROCK_ENDPOINT") or llm_utils.build_bedrock_endpoint(chosen_model, chosen_region)).strip()
    logger.info(f"Using Bedrock model={chosen_model} region={chosen_region} for listing {listing_url}")
    try:
        raw = llm_utils.call_bedrock(
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
        parsed = llm_utils.extract_json(raw)
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