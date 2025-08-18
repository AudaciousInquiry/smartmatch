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
            {"role": "user", "content": f"Please summarize this RFP provided, seperate the details into the following sections\nSummary - A very brief summary of the work:\nScope of work - A summary of the work to be done, as well as key competancies relevant to completing the work\nSelection Criteria - Anything relevant to being selected, usually a section for this, but might be relevant info elsewhere too\nApplication requirements - Copy this section exactly if found, if not found, just mention that it couldn't be found\nTimeline - Focus on the application deadline and project period, as well as any other relevant time related constraints\nFunding - All info related to the funding of the project, like the award amount and hourly pay\n\nHere is the provided RFP, if there is nothing below this line, or it is definitely not an entire RFP (website homepage, etc), just mention that the RFP was not provided:\n\n{rfp_text} "}
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