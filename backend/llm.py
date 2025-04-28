# KAICHABOT/backend/llm.py
import os, openai

openai.api_key = os.getenv("GPT_API_KEY")
GPT_MODEL   = os.getenv("GPT_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("GPT_TEMPERATURE", "0.7"))  # 0-1

def chat(messages: list[dict]) -> str:
    """
    messages in Gemini-style:
      {"role":"user"|"assistant","parts":[text]}
    returns assistant reply string.
    """
    # Convert to OpenAI schema
    oai_msgs = [
        {
            "role": "assistant" if m["role"] in ("assistant", "model") else "user",
            "content": "\n".join(m["parts"]),
        }
        for m in messages
    ]

    resp = openai.ChatCompletion.create(
        model=GPT_MODEL,
        messages=oai_msgs,
        temperature=TEMPERATURE,
    )
    return resp.choices[0].message.content.strip()
