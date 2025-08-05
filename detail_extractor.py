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


def extract_pdf_text(pdf_bytes, splitter=DEFAULT_SPLITTER) -> str:
    with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        tmp_path = tmp.name
    try:
        loader = PyPDFLoader(tmp_path)
        docs = loader.load_and_split(splitter)
        return "\n\n".join(d.page_content for d in docs)
    except Exception as e:
        logger.warning(f"PDF parsing failed: {e}")
        return ""
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def extract_detail_content(url: str, timeout: int = 15) -> str:
    logger.info(f"Extracting detail content from {url}")
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch detail URL {url}: {e}")
        return ""

    final_url = resp.url
    content_type = resp.headers.get("Content-Type", "").lower()

    if "application/pdf" in content_type or final_url.lower().endswith(".pdf"):
        logger.debug(f"Detected PDF at {final_url}")
        return extract_pdf_text(resp.content)

    soup = BeautifulSoup(resp.text, "html.parser")

    pdf_link = soup.find("a", href=re.compile(r"\.pdf($|\?)", re.I))
    if pdf_link and pdf_link.get("href"):
        pdf_url = urljoin(final_url, pdf_link["href"])
        logger.debug(f"Found linked PDF: {pdf_url}")
        try:
            pdf_resp = requests.get(pdf_url, timeout=timeout)
            pdf_resp.raise_for_status()
            return extract_pdf_text(pdf_resp.content)
        except Exception as e:
            logger.warning(f"Failed to fetch linked PDF {pdf_url}: {e}")
    iframe = soup.find(["iframe", "embed"], src=re.compile(r"\.pdf($|\?)", re.I))
    if iframe and iframe.get("src"):
        embedded_pdf_url = urljoin(final_url, iframe["src"])
        logger.debug(f"Found embedded PDF: {embedded_pdf_url}")
        try:
            pdf_resp = requests.get(embedded_pdf_url, timeout=timeout)
            pdf_resp.raise_for_status()
            return extract_pdf_text(pdf_resp.content)
        except Exception as e:
            logger.warning(f"Failed to fetch embedded PDF {embedded_pdf_url}: {e}")

    visible_text = soup.get_text(separator="\n", strip=True)
    logger.debug(f"Falling back to HTML text extraction for {final_url}")
    return visible_text or ""
