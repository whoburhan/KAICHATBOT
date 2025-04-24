# ───────────────────────────────────────────────────────────────
# KAI – Streamlit × Gemini × Firebase
# Last updated: 24-Apr-2025  ▸ fixes greeting-echo + image re-processing
# ───────────────────────────────────────────────────────────────
import streamlit as st
import os, base64, io, json, requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# ─────────────────── Firebase init ─────────────────────────────
def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        cert_dict = json.loads(os.getenv("FIREBASE_JSON"))
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# ─────────────────── Gemini config + system prompt ─────────────
SYSTEM_INSTRUCTION = """
You are KAI, a specialized assistant for international students, scholars, and expatriates.
<… same content you pasted …>
"""
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    "gemini-1.5-flash",
    system_instruction=SYSTEM_INSTRUCTION
)

# ─────────────────── OAuth helpers ─────────────────────────────
BASE_URL = "https://yourkai.streamlit.app"

def get_google_auth_url():
    return (
        "https://accounts.google.com/o/oauth2/auth?"
        f"client_id={os.getenv('GOOGLE_CLIENT_ID')}&"
        f"redirect_uri={BASE_URL}&"
        "scope=email%20profile%20openid&"
        "response_type=code"
    )

def handle_oauth_callback():
    try:
        code = st.query_params["code"]
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": BASE_URL,
            "grant_type": "authorization_code",
        }
        token_data = requests.post(token_url, data=data).json()
        id_token = token_data.get("id_token")
        if not id_token:
            st.error("Could not retrieve ID token."); return
        user_info = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        ).json()
        st.session_state.user = {
            "uid": user_info.get("sub", ""),
            "name": user_info.get("name", "User").split()[0],
            "email": user_info.get("email", ""),
            "picture": user_info.get("picture", ""),
        }
        st.query_params.clear(); st.rerun()
    except Exception as e:
        st.error("OAuth login failed."); st.exception(e)

# ─────────────────── UI helpers ────────────────────────────────
def display_logo():      st.image("Logo_1.png", use_container_width=True)

def handle_authentication():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        display_logo()
        st.markdown("<p style='text-align:center'>Sign in or continue as guest.</p>",
                    unsafe_allow_html=True)
        if st.button("Sign in with Google", key="google_sign_in"):
            st.markdown(f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">', unsafe_allow_html=True)
            st.stop()
        if st.button("Continue as Guest"):
            st.session_state.user = {"uid": "guest", "name": None, "email": "", "picture": ""}
            st.session_state.chat_history = [("assistant", "👋 Hey there! I'm KAI. What should I call you?")]
            st.session_state.awaiting_name  = True
            st.session_state.image_processed = False
            st.rerun()

def enforce_boundaries(prompt:str)->bool:
    core_topics = ["visa","immigration","legal","culture","tradition","education",
                   "university","admission","housing","healthcare","transport","safety",
                   "financial","cost of living","abroad","international","relocation","moving"]
    pl = prompt.lower()
    return any(t in pl for t in core_topics)

def show_sidebar():
    with st.sidebar:
        if st.session_state.user.get("picture"): st.image(st.session_state.user["picture"], width=100)
        else: display_logo()
        if st.session_state.user.get("name"): st.write(f"Welcome, {st.session_state.user['name']}!")

        if st.button("Sign Out"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

        if st.button("Clear Conversation"):
            if st.session_state.user["uid"]=="guest" and st.session_state.user.get("name"):
                st.session_state.chat_history=[("assistant",f"Conversation cleared. How can I help you today, {st.session_state.user['name']}?")]
            else:
                st.session_state.chat_history=[("assistant","Conversation cleared. How can I help you today?")]
            st.rerun()

        uploaded_file = st.file_uploader("Upload an image", type=["jpg","jpeg","png"])
        if uploaded_file:
            st.session_state.uploaded_file_data = uploaded_file
            st.session_state.image_processed   = False

def chat_interface():
    display_logo()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history=[("assistant","Hey there! I'm KAI. How can I help you today?")]
    for role, txt in st.session_state.chat_history:
        with st.chat_message(role): st.write(txt)
    message_input()

def message_input():
    prompt = st.chat_input("Ask about visas, culture, housing …")
    if prompt:
        if (st.session_state.user["uid"]=="guest" 
            and st.session_state.user.get("name") is None 
            and st.session_state.awaiting_name):
            handle_guest_name(prompt)
        else:
            st.session_state.chat_history.append(("user", prompt))
            process_user_input(prompt)

def handle_guest_name(prompt:str):
    st.session_state.chat_history.append(("user", prompt))
    name=None
    if any(k in prompt.lower() for k in ["my name is","i am","call me"]):
        words=prompt.replace(",","").split()
        for i,w in enumerate(words):
            if w.lower() in ["is","am"] and i+1<len(words):
                name=words[i+1].capitalize(); break
    if name:
        st.session_state.user["name"]=name
        st.session_state.awaiting_name=False
        st.session_state.chat_history.append(("assistant",f"Nice to meet you, {name}! How can I help you with your international plans?"))
    else:
        st.session_state.chat_history.append(("assistant","Got it! May I know what name I should call you?"))
    st.rerun()

# ─────────────────── pronoun fixer ─────────────────────────────
def fix_pronouns(text:str, name:str)->str:
    if not name: return text
    repl = {
        f"{name} is":"you are",   f"{name}'s":"your",   f"{name} has":"you have",
        f"{name} should":"you should", f"{name} can":"you can", f"{name} will":"you will",
        f"{name} was":"you were", f"{name} were":"you were", f"{name} needs":"you need",
        f"{name} wants":"you want"
    }
    for wrong, right in repl.items():
        text = text.replace(wrong.lower(), right)
    return text

# ─────────────────── NEW: role-map helper ──────────────────────
def map_role(role:str)->str:
    return "user" if role=="user" else "model"   # gemini calls assistant "model"

# ─────────────────── main inference routine ───────────────────
def process_user_input(prompt:str):
    try:
        # ---- build structured Gemini message list (no echo of greetings) ----
        messages=[]
        for role, content in st.session_state.chat_history[-6:]:
            messages.append({"role": map_role(role), "parts":[content]})
        messages.append({"role":"user","parts":[prompt]})

        # ---- one-time image processing -------------------------------------
        if st.session_state.get("uploaded_file_data") and not st.session_state.get("image_processed"):
            img = Image.open(st.session_state.uploaded_file_data)
            buf = io.BytesIO(); img.save(buf, format="JPEG")
            image_part = {"inline_data":{"mime_type":"image/jpeg","data":base64.b64encode(buf.getvalue()).decode()}}
            messages.append({"role":"user","parts":[
                "User just uploaded this image. Analyse it only once and relate it to the current query; do not refer back unless explicitly asked. And Identify in which language is user asking the question and reply in that language only."
            ]})
            messages.append({"role":"user","parts":[image_part]})
            st.session_state.image_processed=True

        # ---- Gemini call ----------------------------------------------------
        with st.spinner("KAI is thinking…"):
            res   = model.generate_content(messages)
            reply = res.text or "Sorry, I didn't quite get that. Could you rephrase?"

        # ---- enforce second-person style ------------------------------------
        if (n:=st.session_state.user.get("name")): reply = fix_pronouns(reply, n)

        st.session_state.chat_history.append(("assistant", reply))

        # ---- persist for logged-in users ------------------------------------
        if st.session_state.user["uid"]!="guest":
            db=setup_firebase()
            db.collection("users").document(st.session_state.user["uid"]).set(
                {"chat_history":[{"role":r,"content":c} for r,c in st.session_state.chat_history]},
                merge=True
            )
        st.rerun()

    except Exception as e:
        st.session_state.chat_history.append(("assistant","Sorry, I encountered an error. Please try again."))
        st.rerun()

# ─────────────────── Streamlit page bootstrap ─────────────────
def main():
    st.set_page_config(page_title="KAI – Your International Assistant", page_icon="🌍")
    setup_firebase()

    if "code" in st.query_params and "user" not in st.session_state:
        handle_oauth_callback()

    if "user" not in st.session_state:
        handle_authentication(); return

    # load chat history for signed-in users
    if st.session_state.user["uid"]!="guest" and "chat_history" not in st.session_state:
        db = setup_firebase()
        doc = db.collection("users").document(st.session_state.user["uid"]).get()
        if doc.exists:
            st.session_state.chat_history=[(m["role"], m["content"]) for m in doc.to_dict().get("chat_history",[])]

    if "chat_history" not in st.session_state:
        if st.session_state.user.get("name"):
            st.session_state.chat_history=[("assistant",f"Welcome back, {st.session_state.user['name']}! How can I help today?")]
        else:
            st.session_state.chat_history=[("assistant","Hey there! How can I assist you with your international plans?")]

    show_sidebar()
    chat_interface()

if __name__ == "__main__":
    main()
