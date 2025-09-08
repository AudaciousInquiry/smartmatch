import re
import os
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin

from loguru import logger
import requests
from bs4 import BeautifulSoup
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    separators=["\n\n", "\n", " ", ""],
)

MAX_PDF_TEXT_CHARS = int(os.getenv("MAX_PDF_TEXT_CHARS", "400000"))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

def extract_pdf_text(pdf_bytes, splitter=DEFAULT_SPLITTER) -> str:
    with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = tmp.name
    try:
        loader = PyPDFLoader(tmp_path)
        docs = loader.load_and_split(splitter)
        text = "\n\n".join(d.page_content for d in docs)
        if len(text) > MAX_PDF_TEXT_CHARS:
            logger.debug(f"Trimming PDF text from {len(text)} to {MAX_PDF_TEXT_CHARS} chars")
            text = text[:MAX_PDF_TEXT_CHARS]
        return text
    except Exception as e:
        logger.warning(f"PDF parsing failed: {e}")
        return ""
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

def _headers(referer: str | None, accept: str = "*/*") -> dict:
    h = {
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        h["Referer"] = referer
    return h

def _get(session: requests.Session | None, url: str, headers: dict, timeout: int):
    if session is not None:
        return session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    return requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)

def extract_detail(url: str, timeout: int = 15, session: requests.Session | None = None, referer: str | None = None) -> tuple[str, str | None]:
    logger.info(f"Extracting detail content from {url}")
    try:
        resp = _get(session, url, _headers(referer), timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch detail URL {url}: {e}")
        return "", None

    final_url = resp.url
    content_type = resp.headers.get("Content-Type", "").lower()

    if "application/pdf" in content_type or final_url.lower().endswith(".pdf"):
        logger.debug(f"Detected PDF at {final_url}")
        return extract_pdf_text(resp.content), final_url

    soup = BeautifulSoup(resp.text, "html.parser")

    pdf_link = soup.find("a", href=re.compile(r"\.pdf($|\?)", re.I))
    if pdf_link and pdf_link.get("href"):
        pdf_url = urljoin(final_url, pdf_link["href"])
        logger.debug(f"Found linked PDF: {pdf_url}")
        try:
            pdf_resp = _get(session, pdf_url, _headers(referer or final_url, accept="application/pdf,*/*;q=0.9"), timeout)
            pdf_resp.raise_for_status()
            return extract_pdf_text(pdf_resp.content), pdf_url
        except Exception as e:
            logger.warning(f"Failed to fetch linked PDF {pdf_url}: {e}")

    iframe = soup.find(["iframe", "embed"], src=re.compile(r"\.pdf($|\?)", re.I))
    if iframe and iframe.get("src"):
        embedded_pdf_url = urljoin(final_url, iframe["src"])
        logger.debug(f"Found embedded PDF: {embedded_pdf_url}")
        try:
            pdf_resp = _get(session, embedded_pdf_url, _headers(referer or final_url, accept="application/pdf,*/*;q=0.9"), timeout)
            pdf_resp.raise_for_status()
            return extract_pdf_text(pdf_resp.content), embedded_pdf_url
        except Exception as e:
            logger.warning(f"Failed to fetch embedded PDF {embedded_pdf_url}: {e}")

    visible_text = soup.get_text(separator="\n", strip=True)
    logger.debug(f"Falling back to HTML text extraction for {final_url}")
    return (visible_text or ""), None

def extract_detail_content(url: str, timeout: int = 15, session: requests.Session | None = None, referer: str | None = None) -> str:
    text, _ = extract_detail(url, timeout=timeout, session=session, referer=referer)
    return text
