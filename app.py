import streamlit as st
import os
import base64
from dotenv import load_dotenv
import io
import requests
from PIL import Image
import json

load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

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

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

BASE_URL = "https://yourkai.streamlit.app"

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
        code = st.query_params["code"]
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
        if not id_token:
            st.error("Could not retrieve ID token.")
            return
        user_info = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}").json()
        name = user_info.get("name", "User").split(" ")[0]
        st.session_state.user = {
            "uid": user_info.get("sub", ""),
            "name": name,
            "email": user_info.get("email", ""),
            "picture": user_info.get("picture", "")
        }
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error("OAuth login failed.")
        st.exception(e)

def display_logo():
    st.image("Logo_1.png", use_container_width=True)

def handle_authentication():
    st.markdown("<style>body {background-color: #090c10;}</style>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        display_logo()
        st.markdown("<p style='text-align: center;'>Please sign in or continue as guest to use the chatbot.</p>", unsafe_allow_html=True)
        if st.button("Sign in with Google", key="google_sign_in"):
            st.markdown(f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">', unsafe_allow_html=True)
            st.stop()
        st.markdown("<div style='text-align: center;'>Or</div>", unsafe_allow_html=True)
        if st.button("Continue as Guest"):
            st.session_state.user = {"uid": "guest", "name": None, "email": "", "picture": ""}
            st.session_state.chat_history = [("assistant", "👋 Hey there! I'm KAI. What should I call you?")]
            st.session_state.awaiting_name = True
            st.rerun()

def show_sidebar():
    with st.sidebar:
        if st.session_state.user.get("picture"):
            st.markdown(f"<img src='{st.session_state.user['picture']}' style='width:100px; height:100px; border-radius:50%;'>", unsafe_allow_html=True)
        else:
            st.image("Logo_1.png", width=100)
        if st.session_state.user.get("name"):
            st.write(f"Welcome, {st.session_state.user['name']}!")
        if st.button("Sign Out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        uploaded_file = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png"])
        if uploaded_file:
            st.session_state.uploaded_file_data = uploaded_file
            st.session_state.image_processed = False

def chat_interface():
    display_logo()
    st.markdown("<h2 style='margin-top: 0;'>KAI</h2>", unsafe_allow_html=True)
    st.markdown("<style>[data-testid='stChatMessageContent'] > p {font-size: 1.1rem;}</style>", unsafe_allow_html=True)
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [("assistant", "Hey there! I'm KAI.")]
    for role, content in st.session_state.chat_history:
        st.chat_message(role).write(content)
    message_input()

def message_input():
    prompt = st.chat_input("Say Hello or anything you want")
    if prompt:
        if st.session_state.user["uid"] == "guest" and st.session_state.user.get("name") is None and st.session_state.awaiting_name:
            lowered = prompt.lower()
            name = None

            if "my name is" in lowered:
                name = lowered.split("my name is")[-1].strip().split()[0].capitalize()
            elif "i am" in lowered or "i'm" in lowered:
                name = lowered.split("i am" if "i am" in lowered else "i'm")[-1].strip().split()[0].capitalize()

            if name:
                st.session_state.user["name"] = name
                st.session_state.awaiting_name = False
                st.session_state.chat_history.append(("user", prompt))
                st.session_state.chat_history.append(("assistant", f"Nice to meet you, {name}! How can I help you today?"))
            else:
                st.session_state.chat_history.append(("user", prompt))
                st.session_state.chat_history.append(("assistant", "I'd love to know what to call you! Could you tell me your name?"))
            st.rerun()
        else:
            st.session_state.chat_history.append(("user", prompt))
            process_user_input(prompt)

def process_user_input(prompt):
    try:
        image = st.session_state.get("uploaded_file_data", None)
        parts = [prompt]
        if image and not st.session_state.get("image_processed"):
            img = Image.open(image)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            image_data = {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(buf.getvalue()).decode(),
                }
            }
            parts.append(image_data)
            st.session_state.image_processed = True
        with st.spinner("KAI is thinking..."):
            res = model.generate_content({"role": "user", "parts": parts})
            reply = res.text or "Sorry, I didn’t quite get that — wanna rephrase?"
            name = st.session_state.user.get("name")
            if name:
                reply = reply.replace("you", name)
            st.session_state.chat_history.append(("assistant", reply))
        if st.session_state.user["uid"] != "guest":
            db = setup_firebase()
            db.collection("users").document(st.session_state.user["uid"]).set({
                "chat_history": [{"role": r, "content": c} for r, c in st.session_state.chat_history]
            }, merge=True)
        st.rerun()
    except Exception as e:
        st.session_state.chat_history.append(("assistant", f"Oops, that hit a wall: {e}"))
        st.rerun()

def main():
    setup_firebase()
    if "code" in st.query_params and "user" not in st.session_state:
        handle_oauth_callback()
    if "user" not in st.session_state:
        handle_authentication()
        return
    if st.session_state.user["uid"] != "guest":
        db = setup_firebase()
        doc = db.collection("users").document(st.session_state.user["uid"]).get()
        if doc.exists:
            st.session_state.chat_history = [(msg["role"], msg["content"]) for msg in doc.to_dict().get("chat_history", [])]
    show_sidebar()
    chat_interface()

if __name__ == "__main__":
    main()
