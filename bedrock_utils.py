import os
import requests
from loguru import logger

def summarize_rfp(rfp_text: str) -> str:
    api_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not api_key:
        raise RuntimeError("Set your Bedrock API key in AWS_BEARER_TOKEN_BEDROCK")

    url = (
        "https://bedrock-runtime.us-east-1.amazonaws.com/"
        "model/us.anthropic.claude-3-7-sonnet-20250219-v1:0/invoke"
    )
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "messages": [
            {"role": "user", "content": f"Please summarize this RFP:\n\n{rfp_text}"}
        ],
    }

    logger.debug(f"BEDROCK REQUEST PAYLOAD:\n{payload!r}")
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