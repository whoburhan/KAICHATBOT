import streamlit as st
import os
import base64
from dotenv import load_dotenv
import io
import requests
from PIL import Image
import json
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Initialize Firebase
def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_json = os.getenv("FIREBASE_JSON")
        cert_dict = json.loads(firebase_json)
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

BASE_URL = "https://yourkai.streamlit.app"

# OAuth helpers

def get_google_auth_url():
    return (
        f"https://accounts.google.com/o/oauth2/auth?"
        f"client_id={os.getenv('GOOGLE_CLIENT_ID')}&"
        f"redirect_uri={BASE_URL}&"
        f"scope=email%20profile%20openid&"
        f"response_type=code"
    )

def handle_oauth_callback():
    try:
        params = st.experimental_get_query_params()
        if "code" in params:
            code = params["code"][0]
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "code": code,
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "redirect_uri": BASE_URL,
                "grant_type": "authorization_code"
            }
            res = requests.post(token_url, data=data)
            token_data = res.json()
            id_token = token_data.get("id_token")
            if id_token:
                user_info = requests.get(
                    f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
                ).json()
                name = user_info.get("name", "User").split()[0]
                st.session_state.user = {
                    "uid": user_info.get("sub",""),
                    "name": name,
                    "email": user_info.get("email",""),
                    "picture": user_info.get("picture","")
                }
            st.experimental_set_query_params()
    except Exception:
        pass

# UI components

def display_logo():
    st.image("Logo_1.png", use_column_width=True)

# Authentication screen

def show_login():
    st.markdown("<style>body {background-color: #090c10;}</style>", unsafe_allow_html=True)
    display_logo()
    st.write("# Welcome to KAI")
    st.write("Please sign in or continue as guest to start chatting.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Sign in with Google"):
            st.markdown(f"<meta http-equiv='refresh' content='0; url={get_google_auth_url()}'>",
                        unsafe_allow_html=True)
    with col2:
        if st.button("Continue as Guest"):
            st.session_state.user = {"uid":"guest","name":None,"email":"","picture":""}
            st.session_state.chat_history = [("assistant","👋 Hi! I'm KAI. What should I call you?")]
            st.session_state.awaiting_name = True

# Sidebar

def show_sidebar():
    with st.sidebar:
        if st.session_state.user.get("picture"):
            st.markdown(
                f"<img src='{st.session_state.user['picture']}' style='width:80px;height:80px;border-radius:50%;'>",
                unsafe_allow_html=True
            )
        else:
            st.image("Logo_1.png", width=80)
        if st.session_state.user.get("name"):
            st.write(f"Hello, {st.session_state.user['name']}!")
        if st.button("Sign Out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.experimental_rerun()
        uploaded = st.file_uploader("Upload an image", type=["jpg","jpeg","png"])
        if uploaded:
            st.session_state.uploaded_image = uploaded
            st.session_state.image_processed = False

# Main chat interface

def chat_interface():
    st.markdown("<h1 style='text-align:center;'>KAI - Your Rights Assistant</h1>", unsafe_allow_html=True)
    display_logo()
    st.markdown("<style>[data-testid='stChatMessageContent'] p{font-size:1.1rem;}</style>", unsafe_allow_html=True)

    # Initialize history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [("assistant","👋 Hi! I'm KAI. How can I help you today?")]

    # Display messages
    for role, msg in st.session_state.chat_history:
        st.chat_message(role).write(msg)

    # Input
    prompt = st.chat_input("Type your message...")
    if prompt:
        # First-time guest naming
        if st.session_state.user["uid"] == "guest" and st.session_state.user.get("name") is None:
            name = prompt.split()[0].capitalize()
            st.session_state.user["name"] = name
            st.session_state.chat_history.append(("user",prompt))
            st.session_state.chat_history.append(("assistant",f"Nice to meet you, {name}! How can I assist your study abroad plans?"))
        else:
            # Append user
            st.session_state.chat_history.append(("user",prompt))
            # Build parts
            parts = [prompt]
            img = st.session_state.get("uploaded_image")
            if img and not st.session_state.image_processed:
                buffer = io.BytesIO()
                Image.open(img).save(buffer,format="JPEG")
                parts.append({
                    "inline_data":{
                        "mime_type":"image/jpeg",
                        "data":base64.b64encode(buffer.getvalue()).decode()
                    }
                })
                st.session_state.image_processed = True
            # Prepare full context
            convo = []
            for r,m in st.session_state.chat_history:
                role_tag = "user" if r=="user" else "model"
                convo.append({"role":role_tag,"parts":[m]})
            # Last user message overrides
            convo.append({"role":"user","parts":parts})
            # Call Gemini
            with st.spinner("KAI is thinking..."):
                try:
                    res = model.generate_content(convo)
                    reply = res.text or "Sorry, I didn't get that. Could you rephrase?"
                except Exception as e:
                    reply = f"Oops, something went wrong: {e}"
            # Personalize
            if st.session_state.user.get("name"):
                reply = reply.replace("you", st.session_state.user['name'])
            st.session_state.chat_history.append(("assistant",reply))
            # Persist
            if st.session_state.user["uid"]!="guest":
                db = setup_firebase()
                db.collection("users").document(st.session_state.user["uid"]).set({
                    "chat_history":[{"role":r,"content":m} for r,m in st.session_state.chat_history]
                },merge=True)

# App entry

def main():
    setup_firebase()
    handle_oauth_callback()
    if "user" not in st.session_state:
        show_login()
        return
    show_sidebar()
    chat_interface()

if __name__ == "__main__":
    main()