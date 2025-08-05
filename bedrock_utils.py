from langchain_aws import ChatBedrock

def summarize_rfp(text: str) -> str:
    """Call Bedrock to get a concise summary of this RFP."""
    model = ChatBedrock(
        model_id="us.meta.llama3-3-70b-instruct-v1:0",
        temperature=0.0,
        max_tokens=512,
    )
    prompt = f"""
You are an expert grants administrator. Please read this Request for Proposals in full, then produce a 3–4 sentence summary that:
- Clearly states the scope of work
- Highlights any dollar amounts or contract value
- Mentions key deliverables or deadlines

RFP TEXT:
\"\"\"
{text}
\"\"\""""

    resp = model.invoke(prompt)
    return resp["answer"].strip()
