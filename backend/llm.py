import os
import google.generativeai as genai
import openai

# ───────── env ─────────
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

# ───────── init ────────
if PROVIDER == "gemini":
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    gemini_model = genai.GenerativeModel(
        os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        system_instruction=os.getenv("SYSTEM_PROMPT", "")
    )

elif PROVIDER == "gpt":
    openai.api_key = os.getenv("GPT_API_KEY")

else:
    raise ValueError(f"Unsupported LLM_PROVIDER '{PROVIDER}'")

# ───────── unified chat ────────
def chat(messages: list[dict]) -> str:
    """
    Input  (Gemini style):
        [{"role":"user","parts":[text]}, …]
    Output: assistant string
    """
    if PROVIDER == "gemini":
        resp = gemini_model.generate_content(messages)
        return resp.text

    # -- GPT path : convert message schema --
    oai_msgs = []
    for m in messages:
        role = "assistant" if m["role"] in ("assistant", "model") else "user"
        oai_msgs.append({"role": role, "content": "\n".join(m["parts"])})

    resp = openai.ChatCompletion.create(
        model=os.getenv("GPT_MODEL", "gpt-4o-mini"),
        messages=oai_msgs,
        temperature=0.7,
    )
    return resp.choices[0].message.content
