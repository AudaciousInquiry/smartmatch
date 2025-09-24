import os
import re
import time
import json
import random
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from requests import ReadTimeout, ConnectTimeout
from loguru import logger

DEFAULT_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
DEFAULT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
DEFAULT_ENDPOINT = os.getenv("BEDROCK_ENDPOINT", f"https://bedrock-runtime.{DEFAULT_REGION}.amazonaws.com/model/{DEFAULT_MODEL_ID}/invoke")

MAX_DETAIL_TEXT_CHARS = int(os.getenv("MAX_DETAIL_TEXT_CHARS", "400000"))

def build_bedrock_endpoint(model_id: str, region: str) -> str:
    # Construct the Bedrock invoke endpoint URL for a given model/region.
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/invoke"

def _post_with_retries(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: tuple[float, float], retries: int) -> requests.Response:
    # POST with exponential backoff and jitter; retries on 429/5xx or exceptions.
    attempt = 0
    last_exc: Optional[Exception] = None
    while attempt <= retries:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            # Retry on throttling or server errors
            if resp.status_code in (429,) or resp.status_code >= 500:
                raise RuntimeError(f"Bedrock HTTP {resp.status_code}")
            return resp
        except Exception as e:
            last_exc = e
            if attempt >= retries:
                break
            backoff = min(2 ** attempt, 8) + random.random()
            logger.warning(f"Bedrock request failed (attempt {attempt+1}/{retries+1}): {e}; retrying in {backoff:.1f}s")
            time.sleep(backoff)
            attempt += 1
    assert last_exc is not None
    raise last_exc

def call_bedrock(prompt: str, *, max_tokens: int = 8000, timeout_read: float = 60.0, timeout_connect: float = 10.0, retries: int = 2, log_raw: bool = False, log_raw_chars: int = 2000, system: Optional[str] = None, temperature: Optional[float] = 0.0, bedrock_url: Optional[str] = None) -> str:
    # Invoke Bedrock Claude and return the raw text portion of the response.
    api_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not api_key:
        raise RuntimeError("Set AWS_BEARER_TOKEN_BEDROCK")
    payload: Dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [ {"role": "user", "content": prompt} ],
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
    # Parse JSON from an LLM response
    # Raises ValueError if no reasonable JSON can be parsed.
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
                            out.append(ch); esc = False; continue
                        if ch == '\\':
                            out.append(ch); esc = True; continue
                        if ch in ('"', "'"):
                            if not in_str:
                                in_str = True; q = ch
                            elif q == ch:
                                in_str = False
                            out.append(ch); continue
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

SCRAPE_SYSTEM_PROMPT = (
    "You are a careful web analysis assistant. When returning detail_source_url: "
    "- It MUST be chosen from the list under \"Top links\" or be a direct .pdf link. "
    "- Do NOT use the page URL unless it is clearly a single-item detail page (rare for listing pages). "
    "- Prefer links whose local context mentions the item title or contains descriptive details (e.g., Learn more, Apply, Details, PDF). "
    "- Prefer deeper, specific paths over general section pages. "
    "- If you cannot find a suitable detail link for an item, OMIT that item. "
    "Prefer links that: "
    "- are marked is_learn_more=true, "
    "- or have a nearest heading matching the item title, "
    "- or are is_pdf=true and clearly about the item, "
    "and avoid links where is_generic_listing=true. "
    "Scope filter: ONLY include items that are clearly Healthcare IT / public health informatics / health data systems. "
    "Examples to INCLUDE: data modernization, surveillance systems, registries, LIMS, HIE, EHR/EMR, HL7/FHIR, interoperability, data platforms/warehouses (Snowflake/Azure/AWS/GCP), ETL/ELT, APIs/integration, dashboards/BI/analytics, cloud engineering, cybersecurity for health data. "
    "Examples to EXCLUDE: construction/facilities, architectural, legal, HR/staffing jobs, direct clinical services, supplies/equipment, travel, printing, events, general marketing/comms, non-IT training not about data systems. "
    "If topic is ambiguous or not enough information is shown on this page, OMIT it at the listing stage. "
    "Return strict JSON only, no comments or markdown. IMPORTANT: Only include an item if the date you rely on is clearly a submission / application / proposal deadline (NOT a posted/published/announcement date). If the only visible date is a posted/publish date and there is no explicit deadline language (e.g., Due/Deadline/Closing), omit the item. Your answer will be evaluated primarily by whether detail_link_index correctly references a link in \"Top links\" that provides specific details for the item."
)

SCRAPE_PROMPT_TEMPLATE = """You are analyzing a single web page for RFP/Opportunity items.
You are given:
1) A plain-text snapshot of the page (truncated).
2) A list of anchor links (text + href).
3) A list of existing items already in the database (title + url).
 4) Today's date (YYYY-MM-DD): {today}

Scope:
- ONLY include items clearly related to Healthcare IT / public health informatics / health data systems.
- Include: data modernization, certification, registries, LIMS, HIE, EHR/EMR, HL7/FHIR, interoperability, APIs, data platforms/warehouses, ETL/ELT, dashboards/BI/analytics, cloud engineering, cybersecurity for health data.
- Exclude: construction/facilities, architectural, legal, HR/staffing jobs, direct clinical services, supplies/equipment, travel, printing, events, general marketing/comms, non-IT training.
- If uncertain or ambiguous from this page, omit; a later navigation step cannot fix topic mismatch.

Task:
- Identify any new RFP/Opportunity items not already in the database.
- Include consulting/contractor solicitations, RFQs, and RFPs as valid opportunities. Exclude only full-time/part-time employment job postings from HR/careers pages.
- Prefer concrete detail pages or direct PDF links if available.
- detail_source_url must be selected from the provided Top links (anchor list) or be a direct .pdf link on the same site. Do not repeat the page URL unless the page is itself a single-item detail page.
- If the page clearly indicates an opportunity is closed/expired/no-longer accepting applications (e.g., "Closed", "Deadline has passed", "No longer accepting applications", "Application window closed", "Archived", "Award made", "This opportunity is closed"), EXCLUDE the item.
- If a clear deadline is shown on this page, prefer items with a future deadline and ignore those clearly in the past. If a clear deadline is not shown here, you may still include the item if the link appears to lead to a detailed RFP/solicitation page or PDF; a later step will validate deadline/recency.
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
- Do not treat posted/published/announcement dates as deadlines unless there is explicit deadline language adjacent to them. Terms like "Expiration Date" do count as deadlines when present.
 - When a date appears without a year (e.g., "June 3"), assume the current year (TODAY) for comparison; if that makes it clearly in the past, consider the item expired on this page.

Existing DB items (title,url):
{existing}

Page text (truncated):
\"\"\"
{text}
\"\"\"

Top links (indexed, with metadata):
{links}
"""

SCRAPE_NAV_SYSTEM = (
    "You are navigating toward the actual full RFP page or PDF. "
    "At every hop you are given the current page text and its links. "
    "Decide if CURRENT page is the final RFP (full opportunity details including scope, deadlines, funding, how to apply). "
    "If yes, return status='final' and no next_link_index. If not, select the single most promising link index to continue navigation. "
    "If you see clear language that the opportunity is closed/expired/no longer accepting applications, or the expiration date listed is clearly in the past relative to TODAY shown in the prompt, return status='expired' immediately and stop. "
    "When a date is shown without a year, assume the year is the current year (TODAY) for comparisons. If that makes it in the past, treat it as expired. "
    "Apply the same Healthcare IT scope filter as the listing step: if the CURRENT page clearly indicates the opportunity is not Healthcare IT / public health informatics / health data systems, return status='give_up'. "
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
    "status": "final" | "continue" | "give_up" | "expired",
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
- status=expired if the page clearly indicates the opportunity is closed/expired/no longer accepting applications, or the expiration date listed is clearly in the past relative to today's date, which is {today}.
 - When a date appears without a year (e.g., "June 3"), assume the current year ({current_year}). If that date is before TODAY, treat as expired.
- Do not treat posted/published/announcement dates as deadlines.
- If status=expired, include the exact sentence or line containing the deadline/closing text in the "reason" for auditability.
- No markdown, comments, or extra keys.
"""

SYSTEM_PROMPT = SCRAPE_SYSTEM_PROMPT
NAV_SYSTEM = SCRAPE_NAV_SYSTEM

FINAL_SYSTEM = (
    "You are validating a final RFP/Opportunity page or PDF. "
    "Return JSON only. Determine if it should be stored as ACTIVE or skipped as EXPIRED. "
    "ACTIVE only if there is a clear submission/application/proposal deadline that is in the FUTURE relative to TODAY. "
    "Do not treat posted/published/announcement dates as deadlines. If a date appears without a year, assume the current year (TODAY). "
    "Do NOT roll month/day forward to next year. If the month/day is earlier than TODAY in the current year, it is in the past."
)

FINAL_PROMPT_TEMPLATE = """TODAY: {today}
PAGE URL: {page_url}

Page content (truncated):
<<<CONTENT_START>>>
{content}
<<<CONTENT_END>>>

Return ONLY strict JSON with this schema:
{{
    "status": "active" | "expired" | "unknown",
    "reason": "short explanation",
    "matched_text": "the exact sentence/line containing the deadline/closing language if present, else empty",
    "deadline_iso": "YYYY-MM-DD or null (normalize your interpreted deadline)"
}}

Rules:
- status=active only if there is explicit deadline wording (Due/Deadline/Applications Due/Closing) and the deadline date is in the future relative to TODAY.
- status=expired if the deadline date is clearly in the past or the page states closed/no longer accepting applications.
- When a date appears without a year, assume the current year ({current_year}).
- Do not treat posted/published/announcement dates as deadlines.
- If uncertain, return status="unknown".
 - Always provide deadline_iso when status is active or expired. Use the format YYYY-MM-DD. Compare it to TODAY to decide status. Do NOT roll to next year.
"""

def today_str() -> str:
    # Return YYYY-MM-DD using override envs if provided for deterministic tests.
    t = (os.getenv("TODAY_OVERRIDE") or os.getenv("SM_TODAY") or os.getenv("RFP_TODAY") or "").strip()
    if t:
        return t[:10]
    return time.strftime("%Y-%m-%d", time.gmtime())

def build_prompt(page_text: str, links: List[Dict[str, str]], existing: List[Dict[str, str]], page_url: str) -> str:
    # Compose the listing-stage prompt with page text, anchors, and prior items.
    existing_lines = "\n".join(f"- {e.get('title','').strip()} | {e.get('url','').strip()}" for e in existing[:100])
    def fmt(l: Dict[str, Any], i: int) -> str:
        return (
            f"- [{i}] {l.get('text','')} -> {l.get('href','')}"
            f" | heading: {l.get('heading','')}"
            f" | context: {l.get('context','')}"
            f" | flags: learn_more={l.get('is_learn_more', False)}, apply={l.get('is_apply', False)}, pdf={l.get('is_pdf', False)}, generic_listing={l.get('is_generic_listing', False)}, depth={l.get('depth', 0)}"
        )
    link_lines = "\n".join(fmt(l, i) for i, l in enumerate(links))
    today = today_str()
    return SCRAPE_PROMPT_TEMPLATE.format(
        existing=existing_lines or "(none)",
        text=page_text,
        links=link_lines,
        page_url=page_url,
        today=today,
    )

def build_nav_prompt(page_text: str, links: List[Dict[str, str]], existing: List[Dict[str, str]], page_url: str, hop: int, max_hops: int) -> str:
    # Compose the navigation prompt for a single hop decision.
    existing_titles = ", ".join(e.get('title','').strip() for e in existing[:40] if e.get('title')) or "(none)"
    def fmt(l: Dict[str, Any], i: int) -> str:
        return (
            f"- [{i}] {l.get('text','')} -> {l.get('href','')}"
            f" | heading: {l.get('heading','')}"
            f" | flags: learn_more={l.get('is_learn_more', False)}, apply={l.get('is_apply', False)}, pdf={l.get('is_pdf', False)}, depth={l.get('depth',0)}"
        )
    link_lines = "\n".join(fmt(l, i) for i, l in enumerate(links))
    today = today_str()
    current_year = today.split("-")[0]
    return NAV_PROMPT_TEMPLATE.format(
        page_url=page_url,
        hop=hop,
        max_hops=max_hops,
        today=today,
        current_year=current_year,
        existing_titles=existing_titles,
        page_text=page_text,
        links=link_lines,
    )

def build_final_prompt(page_text: str, page_url: str) -> str:
    # Compose the final validation prompt for deadline and scope classification.
    today = today_str()
    current_year = today.split("-")[0]
    return FINAL_PROMPT_TEMPLATE.format(
        today=today,
        current_year=current_year,
        page_url=page_url,
        content=page_text[:MAX_DETAIL_TEXT_CHARS]
    )

def classify_final_page(page_text: str, page_url: str) -> Dict[str, Any]:
    # Call FINAL prompt and normalize status and deadline_iso for downstream use.
    prompt = build_final_prompt(page_text, page_url)
    try:
        raw = call_bedrock(prompt, system=FINAL_SYSTEM, temperature=0.0, max_tokens=800)
        decision = extract_json(raw)
        status = (decision.get("status") or "").lower()
        reason = decision.get("reason") or ""
        deadline_iso = decision.get("deadline_iso") or None
        if isinstance(deadline_iso, str):
            deadline_iso = deadline_iso.strip() or None
            if deadline_iso and len(deadline_iso) >= 10:
                deadline_iso = deadline_iso[:10]
        try:
            logger.info(f"FINAL-CHECK: status={status} deadline_iso={deadline_iso} reason={reason[:180]} url={page_url}")
        except Exception:
            pass
        return {"status": status, "reason": reason, "deadline_iso": deadline_iso}
    except Exception:
        logger.exception("Final page classification failed")
        return {"status": "unknown", "reason": "classification error", "deadline_iso": None}

def summarize_rfp(rfp_text: str) -> str:
    # Summarize a final RFP text into structured sections for storage/display.
    api_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not api_key:
        raise RuntimeError("Set your Bedrock API key in AWS_BEARER_TOKEN_BEDROCK")
    region = os.getenv("BEDROCK_REGION", "us-east-1").strip()
    model_id = os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID).strip()
    url = os.getenv("BEDROCK_ENDPOINT", build_bedrock_endpoint(model_id, region)).strip()
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [
            {"role": "user", "content": (
                "Please summarize this RFP provided, seperate the details into the following sections\n"
                "Summary - A very brief summary of the work:\n"
                "Scope of work - A summary of the work to be done, as well as key competancies relevant to completing the work\n"
                "Selection Criteria - Anything relevant to being selected, usually a section for this, but might be relevant info elsewhere too\n"
                "Application requirements - Copy this section exactly if found, if not found, just mention that it couldn't be found\n"
                "Timeline - Focus on the application deadline and project period, as well as any other relevant time related constraints\n"
                "Funding - All info related to the funding of the project, like the award amount and hourly pay\n\n"
                "Here is the provided RFP, if there is nothing below this line, or it is definitely not an entire RFP (website homepage, etc), just mention that the RFP was not provided:\n\n"
                f"{rfp_text} "
            )}
        ],
    }
    logger.info(f"Using Bedrock model={model_id} region={region}")
    logger.debug(f"BEDROCK REQUEST PAYLOAD size: messages.user.len={len(rfp_text)} max_tokens=1000")
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json=payload
    )
    logger.info(f"→ Bedrock HTTP {resp.status_code}")
    try:
        resp.raise_for_status()
    except Exception:
        logger.error(f"BEDROCK RESPONSE ERROR: {resp.status_code} / {resp.text[:500]!r}")
        raise
    data = resp.json()
    snippet = data.get("content", [{}])[0].get("text", "")[:2000]
    logger.debug(f"BEDROCK RESPONSE:\n{snippet!r}")
    return data["content"][0]["text"].strip()
