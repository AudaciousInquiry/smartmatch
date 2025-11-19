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
    _link_flags,
    gather_links,
    is_pdf,
    normalize_url,
    find_kendo_read_urls,
    extract_request_verification_token,
    fetch_json,
    _extract_items_from_kendo_json,
    _find_iframe_srcs,
)

DEFAULT_REGION = llm_utils.DEFAULT_REGION
DEFAULT_MODEL_ID = llm_utils.DEFAULT_MODEL_ID
DEFAULT_ENDPOINT = os.getenv("BEDROCK_ENDPOINT", llm_utils.build_bedrock_endpoint(DEFAULT_MODEL_ID, DEFAULT_REGION))

 

MAX_DETAIL_TEXT_CHARS = int(os.getenv("MAX_DETAIL_TEXT_CHARS", "400000"))

def sanitize_text(val: Optional[str]) -> Optional[str]:
    # Replace control characters that can upset the db
    if val is None:
        return None
    return re.sub(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]", " ", val)

 

def load_existing(engine, domain: str, limit: int = 200) -> List[Dict[str, str]]:
    # Return previously processed items to pass to the LLM to skip existing and pre-excluded RFPs
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

 

def find_kendo_read_urls(soup: BeautifulSoup, base_url: str) -> List[str]:
    # Attempt extraction of Kendo Grid transport.read URLs from iFrame, 
    # this is neccessary to resolve the CSTE extraction issue
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

def extract_request_verification_token(soup: BeautifulSoup) -> Optional[str]:
    # Find ASP.NET RequestVerificationToken if present for POST fallbacks.
    # This is used with the Kendo Grid JSON endpoints for CSTE extraction
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

def fetch_json(url: str, referer: Optional[str] = None, timeout: float = 20.0, session: Optional[requests.Session] = None, token: Optional[str] = None) -> Optional[Any]:
    # Fetch JSON from Kendo endpoints using GET, then POST if needed.
    # Many Kendo widgets require POST with a verification token. This helper tries
    # GET first for simple cases, else POSTs a standard body using the token acquired earlier.
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
    # Normalize common Kendo dataset shapes into pseudo-link items for the LLM.
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
    # Collect iframe src URLs to optionally augment link discovery.
    srcs: List[str] = []
    try:
        for f in soup.find_all("iframe"):
            src = (f.get("src") or "").strip()
            if src:
                srcs.append(urljoin(base_url, src))
    except Exception:
        pass
    return list(dict.fromkeys(srcs))

def init_processed_table(engine):
    # Ensure the processed_rfps table exists and has expected columns.
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

def init_exclusions_table(engine):
    # Ensure the rfp_exclusions table exists for persistent skip reasons.
    metadata = MetaData(schema='public')
    excluded = Table(
        'rfp_exclusions', metadata,
        Column('hash', String, primary_key=True),
        Column('title', String),
        Column('site', String),
        Column('listing_url', String),
        Column('detail_url', String),
        Column('reason', String),  # out_of_scope | expired | unknown
        Column('decided_at', String),
    )
    metadata.create_all(engine)
    return excluded

def is_excluded(conn, excluded_table, h: str) -> bool:
    # Used to check if an exclusion with the given hash already exists so we waste resources processing them again
    try:
        row = conn.execute(select(excluded_table.c.hash).where(excluded_table.c.hash == h)).first()
        return row is not None
    except Exception:
        return False

def insert_exclusion(conn, excluded_table, *, h: str, title: str, site: str, listing_url: str, detail_url: Optional[str], reason: str):
    # Insert a new exclusion record; ignore duplicates gracefully.
    try:
        conn.execute(
            excluded_table.insert().values(
                hash=h,
                title=title,
                site=site,
                listing_url=listing_url,
                detail_url=detail_url or None,
                reason=reason,
                decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        )
    except Exception:
        # Ignore duplicate insert errors
        pass

 

def normalize_url(u: str) -> str:
    # Normalize a URL by dropping fragments/query and lowercasing path.
    # This doesn't happen often, but is used to catch cases where the model
    # tries to point back to the same listing page.
    try:
        p = urlparse(u)
        path = (p.path or "").rstrip("/").lower()
        return f"{p.scheme}://{p.netloc}{path}"
    except Exception:
        return u

def upsert_new_items(engine, processed_table, site_name: str, items: List[Dict[str, Any]], page_url: str, links: List[Dict[str, str]], max_hops: int, per_page_max_text: int) -> List[Dict[str, Any]]:
    # Navigate candidates to final pages, validate, summarize, and insert.
    # For each item proposed by the LLM on the listing page:
    # - Validate detail_link_index and avoid selecting the listing page itself.
    # - Skip if it was previously excluded (by title+listing URL early check).
    # - Navigate to the final detail/PDF, extracting robust text if PDF.
    # - Run deadline classification first; persist expired/unknown as exclusions.
    # - Run LLM-only scope gating on the final content.
    # - De-dup by final URL, then summarize and insert into processed_rfps.
    new_rows = []
    content_cache: Dict[str, Tuple[str, Optional[bytes]]] = {}
    summary_cache: Dict[str, str] = {}
    excluded_table = init_exclusions_table(engine)
    with engine.begin() as conn:
        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            idx = item.get("detail_link_index")
            if not title or not url:
                continue
            # Capture authoritative listing title from the page's anchor text when available
            listing_title = title
            if not isinstance(idx, int) or not (0 <= idx < len(links)):
                logger.warning(f"Skipping item '{title}': missing or invalid detail_link_index={idx}")
                continue
            detail_src = links[idx].get("href") or ""
            if not detail_src:
                continue
            if normalize_url(detail_src) == normalize_url(page_url):
                logger.warning(f"Skipping item '{title}': model selected listing URL as detail link")
                continue
            try:
                anchor_text = (links[idx].get("text") or "").strip()
                if anchor_text and not _is_generic_title(anchor_text):
                    listing_title = anchor_text
            except Exception:
                pass

            # Precompute a hash for early exclusion checks (title+listing URL)
            h = hashlib.sha256((title + url).encode("utf-8")).hexdigest()
            if is_excluded(conn, excluded_table, h):
                logger.info(f"Skipping previously-excluded: {title}")
                continue

            # Seed navigation with the item's title and anchor text so direct PDFs won't be titled "(PDF)"
            final_url, final_title, final_text = navigate_to_final(
                detail_src,
                existing=[],
                max_hops=max_hops,
                per_page_max_text=per_page_max_text,
                initial_title=listing_title,
                initial_link_text=(links[idx].get("text") if isinstance(idx, int) and 0 <= idx < len(links) else None),
            )
            if not final_url or not final_text:
                logger.info(f"Navigation failed to resolve final RFP for '{title}' (transient, not excluded)")
                continue
            # Prefer non-generic listing title if nav title is generic or missing
            if (not final_title or _is_generic_title(final_title)) and not _is_generic_title(listing_title):
                final_title = listing_title
            # Always extract PDF text if final URL is a PDF (even if some text exists)
            try:
                if is_pdf(final_url):
                    parsed_text, detected_pdf_url = extract_detail(final_url, referer=page_url)
                    if parsed_text:
                        final_text = parsed_text
                    if detected_pdf_url:
                        final_url = detected_pdf_url
            except Exception:
                logger.exception(f"Failed to extract PDF text for final URL {final_url} (transient, not excluded)")
                # Treat as transient: do NOT persist exclusion; allow future retry
                continue

            # Classify deadline first
            final_check = llm_utils.classify_final_page(final_text or "", final_url)
            status_lower = (final_check.get("status") or "").lower()
            enforce = os.getenv("FINAL_DATE_ENFORCE", "true").strip().lower() in ("true")
            if enforce:
                today = llm_utils.today_str()
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
                        f"(overridden: orig_status={orig_status}, deadline_iso={dline} <= today={llm_utils.today_str()}) reason={reason}"
                    )
                else:
                    if dline:
                        logger.info(f"Skipping '{title}' due to final page status={status_lower} deadline_iso={dline} reason={reason}")
                    else:
                        logger.info(f"Skipping '{title}' due to final page status={status_lower} reason={reason}")
                # Exclusion keyed on final_url for stability across runs
                h_excl = hashlib.sha256((title + final_url).encode("utf-8")).hexdigest()
                insert_exclusion(conn, excluded_table, h=h_excl, title=title, site=site_name, listing_url=page_url, detail_url=final_url, reason="expired" if status_lower=="expired" else "unknown")
                continue

            # Scope decision on final content (LLM-only)
            llm_ok = True
            try:
                # LLM scope check with a compact JSON prompt 
                # TODO: use with_structured_output
                scope_system = (
                    "Classify ONLY if this opportunity is clearly Healthcare IT / public health informatics / health data systems. "
                    "Require explicit health-related context (e.g., public health, EHR/EMR, HIE, HL7/FHIR, HIPAA/PHI, Medicaid, disease surveillance, immunization). "
                    "Do NOT infer based on possible presence of health fields in otherwise non-health systems. "
                    "Explicitly EXCLUDE education/SIS, justice/law-enforcement, traffic/public safety, and other non-health government IT. "
                    "Return JSON only: {\"in_scope\": true|false, \"reason\": \"...\"}."
                )
                scope_prompt = (
                    f"TITLE: {(final_title or title)[:300]}\nURL: {final_url}\n\nCONTENT (truncated):\n<<<\n{(final_text or '')[:12000]}\n>>>\n"
                )
                raw_scope = llm_utils.call_bedrock(scope_prompt, system=scope_system, temperature=0.0, max_tokens=300)
                sc = llm_utils.extract_json(raw_scope)
                llm_ok = bool(sc.get("in_scope", False))
                try:
                    logger.info(f"SCOPE LLM: in_scope={llm_ok} reason={(sc.get('reason') or '')[:1800]}")
                except Exception:
                    pass
            except Exception:
                logger.exception("LLM scope classification failed")
                llm_ok = False
            accept = llm_ok
            logger.info(f"SCOPE DECISION: llm={llm_ok} accept={accept} title='{title}'")
            if not accept:
                logger.info(f"Skipping '{title}' as out-of-scope after final-page checks")
                h_excl = hashlib.sha256((title + final_url).encode("utf-8")).hexdigest()
                insert_exclusion(conn, excluded_table, h=h_excl, title=title, site=site_name, listing_url=page_url, detail_url=final_url, reason="out_of_scope")
                continue

            # Prefer the final page's title when available
            chosen_title = final_title.strip() if final_title else listing_title

            pdf_bytes = None
            try:
                parsed_text, detected_pdf_url = extract_detail(final_url, referer=page_url)
                if detected_pdf_url:
                    headers = dict(UA_BASE)
                    headers["Referer"] = url
                    rpdf = requests.get(detected_pdf_url, headers=headers, timeout=30, allow_redirects=True)
                    if rpdf.status_code == 200 and rpdf.content and (rpdf.headers.get('Content-Type','').lower().find('application/pdf') != -1 or rpdf.content[:5] == b"%PDF-"):
                        pdf_bytes = rpdf.content
                    if parsed_text:
                        final_text = parsed_text
                        final_url = detected_pdf_url
            except Exception:
                logger.exception(f"Failed robust PDF confirm/fetch for {final_url}")

            # Dedup by final URL prior to expensive summarization/insert
            existing_by_url = conn.execute(select(processed_table.c.hash).where(processed_table.c.url == final_url)).first()
            if existing_by_url:
                logger.info(f"Skipping existing by URL: {chosen_title} -> {final_url}")
                continue

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

            # (Removed legacy summary heading override that caused prompt-echo titles)

            # Summary override only if both chosen & listing are generic
            if ai_summary and _is_generic_title(chosen_title):
                if not _is_generic_title(listing_title):
                    chosen_title = listing_title
                else:
                    cand = _extract_title_from_summary(ai_summary)
                    if cand and not _is_generic_title(cand):
                        chosen_title = cand
            # Final fallback: if still generic & listing non-generic
            if _is_generic_title(chosen_title) and not _is_generic_title(listing_title):
                chosen_title = listing_title

            detail_content = sanitize_text(detail_content) or None
            if ai_summary:
                ai_summary = sanitize_text(ai_summary)

            # Hash based on final URL
            h_final = hashlib.sha256(final_url.encode('utf-8')).hexdigest()

            # Final insert into processed_rfps for all determined values
            conn.execute(
                processed_table.insert().values(
                    hash=h_final,
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
                "hash": h_final,
                "has_detail": bool(detail_content),
                "ai_summary": ai_summary,
            })
            logger.info(f"Inserted (final): {chosen_title} -> {final_url}")
    return new_rows

def _fetch_links_and_text(url: str, max_text: int = 20000, max_links: int = 120) -> Tuple[str, List[Dict[str,str]]]:
    # Fetch a page and return its readable text and discovered links.
    soup = fetch_page(url)
    txt = soup_text(soup, max_chars=max_text)
    lnks = gather_links(soup, url, max_links=max_links, page_url=url)
    return txt, lnks

def navigate_to_final(start_url: str, existing: List[Dict[str,str]], max_hops: int, per_page_max_text: int = 16000, *, initial_title: Optional[str] = None, initial_link_text: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    # Iteratively navigate to the final RFP page or PDF.
    # Uses the NAV prompt to either stop on a final page, continue to a single
    # best next link, or give up/expire. Returns:
    # - (final_url, final_title, final_page_text) on success
    # - (None, None, None) if navigation fails or gives up
    # PDFs are parsed via detail_extractor to provide normalized text.
    visited = set()
    current_url = start_url
    # Prefer initial link text or provided title as a seed for PDFs
    final_title = (initial_link_text or initial_title) or None
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
                    return pdf_url, (final_title or "(PDF)"), text
            except Exception:
                logger.exception(f"Failed to extract PDF at {current_url}")
            return current_url, (final_title or "(PDF)"), page_text

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
            try:
                text, pdf_url = extract_detail(fu, referer=current_url)
                if text and pdf_url:
                    return pdf_url, final_title, text
                if text:
                    return fu, final_title, text
            except Exception:
                logger.exception(f"Failed to extract declared final URL {fu}")
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

# --- Generic title handling helpers ---
GENERIC_TITLE_SET = {
    'rfp','rfa','rfi','request for applications','request for application',
    'request for proposals','request for proposal','request for information','pdf','(pdf)',
    'untitled rfp','opportunity','solicitation'
}
GENERIC_PREFIXES = (
    'summary of rfp','rfp summary','i will summarize','i\'ll summarize','this rfp','the rfp','summary:'
)

def _is_generic_title(t: Optional[str]) -> bool:
    if not t:
        return True
    s = t.strip().lower()
    if not s:
        return True
    # remove surrounding quotes & parenthetical pdf marker
    s = s.strip('"\'')
    s = s.replace('(pdf)','').strip()
    if s in GENERIC_TITLE_SET:
        return True
    if len(s) < 4:
        return True
    # overly boilerplate patterns
    for p in GENERIC_PREFIXES:
        if s.startswith(p):
            return True
    # reject if mostly non-alpha
    if sum(c.isalpha() for c in s) < 6:
        return True
    return False

def _extract_title_from_summary(summary: str) -> Optional[str]:
    try:
        lines = [l.strip() for l in summary.splitlines() if l.strip()][:8]
        for l in lines:
            raw = l.lstrip('#').strip()
            # skip boilerplate lines
            low = raw.lower()
            if any(low.startswith(p) for p in GENERIC_PREFIXES):
                continue
            # handle colon pattern
            if ':' in raw:
                left,right = raw.split(':',1)
                cand = right.strip()
                if cand and not _is_generic_title(cand) and 6 <= len(cand) <= 200:
                    return cand[:200]
            if not _is_generic_title(raw) and 6 <= len(raw) <= 200:
                return raw[:200]
    except Exception:
        pass
    return None

def main():
    # CLI entrypoint for probing a single listing URL.
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
    # End-to-end processing of a single listing page URL.
    # - Fetch page and extract text/links
    # - Ask LLM to propose concrete items with a detail_link_index.
    # - Forward the items to upsert_new_items for navigation and insertion.
    domain = urlparse(listing_url).netloc
    site = site_name or domain
    created_engine = False
    if engine is None:
        engine = create_engine(ConfigurationValues.get_pgvector_connection())
        created_engine = True
    processed = init_processed_table(engine)
    excluded_table = init_exclusions_table(engine)
    session = requests.Session()
    try:
        soup = fetch_page_with_session(session, listing_url)
    except Exception:
        logger.exception(f"Failed to fetch listing URL; skipping: {listing_url}")
        if created_engine:
            engine.dispose()
        return []

    page_text = soup_text(soup, max_chars=max_text)
    links = gather_links(soup, listing_url, max_links=max_links, page_url=listing_url)

    try:
        kendo_urls = find_kendo_read_urls(soup, listing_url)
        token = extract_request_verification_token(soup)
        kendo_items: List[Dict[str, str]] = []
        for ku in kendo_urls[:3]: 
            data = fetch_json(ku, referer=listing_url, session=session, token=token)
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
    # Inform the model about excluded items by using title+listing URL with exclusion reason
    # TODO: increase limit if needed in future
    try:
        with engine.connect() as conn:
            ex_rows = conn.execute(text("""
                SELECT title, listing_url as url
                FROM public.rfp_exclusions
                WHERE site = :site
                  AND reason IN ('out_of_scope','expired')
                ORDER BY decided_at DESC
                LIMIT 500
            """), {"site": site}).mappings().all()
            if ex_rows:
                existing.extend([dict(r) for r in ex_rows])
    except Exception:
        logger.exception("Failed to load exclusions to seed existing list")
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