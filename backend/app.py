# KAICHABOT/backend/app.py
import os, base64
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from llm import chat as llm_chat
from firebase_util import get_firestore, save_chat_history

load_dotenv()

api = FastAPI(title="KAI-API", version="1.0.0")
api.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:5173",
        "https://yourkai.com",
    ],
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

Role = Literal["user", "assistant"]

class Message(BaseModel):
    role: Role
    content: str

class ChatRequest(BaseModel):
    user_id: str = Field(..., example="guest")
    messages: List[Message]
    image_b64: Optional[str] = Field(
        default=None, description="Base64 JPEG from client"
    )

class ChatResponse(BaseModel):
    reply: str

def image_part(img_b64: str) -> dict:
    return {
        "inline_data": {"mime_type": "image/jpeg", "data": img_b64}
    }

@api.post("/chat", response_model=ChatResponse)
def chat_endpoint(body: ChatRequest):
    try:
        g_msgs = [
            {"role": m.role if m.role != "assistant" else "model", "parts": [m.content]}
            for m in body.messages
        ]

        if body.image_b64:
            g_msgs.append(
                {"role":"user","parts":[
                    "User uploaded this image. Relate it to current query."
                ]}
            )
            g_msgs.append({"role":"user","parts":[image_part(body.image_b64)]})

        assistant = llm_chat(g_msgs)

        # persist
        try:
            db = get_firestore()
            save_chat_history(
                db,
                body.user_id,
                [m.dict() for m in body.messages] + [{"role":"assistant","content":assistant}],
            )
        except Exception as e:
            print("Firestore save failed:", e)

        return ChatResponse(reply=assistant)

    except Exception as e:
        raise HTTPException(500, str(e))
