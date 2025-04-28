# backend/llm.py  – GPT-only, SDK ≥ 1.0
import os
from openai import OpenAI, OpenAIError

GPT_MODEL   = os.getenv("GPT_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("GPT_TEMPERATURE", "0.7"))

client = OpenAI(api_key=os.getenv("GPT_API_KEY"))

def chat(messages: list[dict]) -> str:
    """
    Args:
        messages (list): [{"role":"user"|"assistant","parts":[text]}, …]
    Returns:
        str: assistant reply
    """
    # convert Gemini-style schema ➜ OpenAI
    oai_msgs = [
        {
            "role": "assistant" if m["role"] in ("assistant", "model") else "user",
            "content": "\n".join(m["parts"]),
        }
        for m in messages
    ]

    try:
        resp = client.chat.completions.create(
            model=GPT_MODEL,
            messages=oai_msgs,
            temperature=TEMPERATURE,
        )
        return resp.choices[0].message.content.strip()
    except OpenAIError as e:
        # bubble up – FastAPI will wrap into HTTP 500
        raise RuntimeError(str(e)) from e
