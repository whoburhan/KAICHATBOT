# KAICHABOT/backend/firebase_util.py
import os, json, base64, google.auth.credentials, firebase_admin
from firebase_admin import credentials, firestore

_app = None

def _init():
    global _app
    if _app:
        return _app

    # ---------- LOCAL EMULATOR ----------
    if os.getenv("FIRESTORE_EMULATOR_HOST"):
        cred = google.auth.credentials.AnonymousCredentials()
        _app = firebase_admin.initialize_app(
            credential=cred,
            options={"projectId": os.getenv("FIREBASE_PROJECT_ID", "kai-local")},
        )
    # ---------- PRODUCTION -------------
    else:
        key_json = (
            os.getenv("FIREBASE_JSON")
            or os.getenv("FIREBASE_JSON_B64")
            and base64.b64decode(os.getenv("FIREBASE_JSON_B64")).decode()
        )
        if not key_json:
            raise RuntimeError("Firebase creds missing")
        cred = credentials.Certificate(json.loads(key_json))
        _app = firebase_admin.initialize_app(cred)
    return _app

def get_firestore():
    _init()
    return firestore.client()

def save_chat_history(db, user_id: str, messages: list[dict]):
    db.collection("users").document(user_id).set(
        {"chat_history": messages}, merge=True
    )
