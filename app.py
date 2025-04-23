import streamlit as st
import os
import base64
from dotenv import load_dotenv
import io
import requests
from PIL import Image
import time

# Load environment variables
load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# -----------------------------------
# Firebase Initialization
# -----------------------------------
def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        # Grab the JSON dict you stored under FIREBASE_JSON in your Streamlit secrets
        cred_dict = st.secrets["FIREBASE_JSON"]
        # Initialize with that dict rather than a file
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()



# -----------------------------------
# Gemini Initialization
# -----------------------------------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

# -----------------------------------
# Google Auth URL
# -----------------------------------
BASE_URL = "https://yourkai.streamlit.app/"

def get_google_auth_url():
    return (
        f"https://accounts.google.com/o/oauth2/auth?"
        f"client_id={os.getenv('GOOGLE_CLIENT_ID')}&"
        f"redirect_uri={BASE_URL}&"
        f"scope=email%20profile%20openid&"
        f"response_type=code"
    )

# -----------------------------------
# OAuth Callback
# -----------------------------------
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
            st.error("❌ Could not retrieve ID token.")
            return

        user_info = requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        ).json()

        st.session_state.user = {
            "uid": user_info.get("sub", ""),
            "name": user_info.get("name", "User"),
            "email": user_info.get("email", ""),
            "picture": user_info.get("picture", "")
        }
        st.query_params.clear()
        st.rerun()

    except Exception as e:
        st.error("OAuth login failed.")
        st.exception(e)


# -----------------------------------
# Logo
# -----------------------------------
def display_logo():
    st.image("Logo_1.png", use_column_width=True, output_format="PNG")


# -----------------------------------
# Auth UI Logic
# -----------------------------------
def handle_authentication():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        display_logo()
        st.markdown(
            "<p style='text-align: center;'>Please sign in or continue as guest to use the chatbot.</p>",
            unsafe_allow_html=True,
        )
        if st.button("Sign in with Google", key="google_sign_in"):
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">',
                unsafe_allow_html=True,
            )
            st.stop()

        st.markdown("<div style='text-align: center;'>Or</div>", unsafe_allow_html=True)
        if st.button("Continue as Guest", key="continue_as_guest"):
            st.session_state.user = {
                "uid": "guest",
                "name": "Guest",
                "email": "",
                "picture": ""
            }
            st.rerun()


# -----------------------------------
# Chat UI
# -----------------------------------
def display_message(role, content, current_time=None):
    if role == "user":
        st.markdown(
            f"<div style='text-align: right; font-weight: bold;'>You</div>",
            unsafe_allow_html=True
        )
    st.chat_message(role).write(content)
    if current_time:
        align = "right" if role == "user" else "left"
        st.markdown(
            f"<div style='font-size: smaller; color: grey; text-align: {align}'>{current_time}</div>",
            unsafe_allow_html=True
        )


def chat_interface():
    header_container = st.container()
    with header_container:
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            display_logo()
        with col2:
            st.markdown("<h2 style='margin-top: 0; text-align: left;'>KAI</h2>",
                        unsafe_allow_html=True)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            ("assistant", "👋 Hello! I'm KAI. How can I help you today?")
        ]

    for role, content in st.session_state.chat_history:
        display_message(role, content)

    message_input()


def message_input():
    if prompt := st.chat_input("Ask about your rights or type 'clear' to reset"):
        st.session_state.chat_history.append(("user", prompt))


# -----------------------------------
# Gemini Chat Logic
# -----------------------------------
def process_user_input(prompt):
    st.session_state.chat_history.append(("user", prompt))
    with st.spinner("KAI is thinking..."):
        parts = [prompt]
        image = st.session_state.get("uploaded_file", None)
        if image:
            img = Image.open(image)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(buf.getvalue()).decode()
                }
            })
            # clear image so it’s sent only once
            del st.session_state["uploaded_file"]

        if prompt.lower() == "clear":
            st.session_state.chat_history = [
                ("assistant", "👋 Hello! I'm KAI. How can I help you today?")
            ]
        else:
            res = model.generate_content({"role": "user", "parts": parts})
            reply = res.text or "Sorry, I couldn't find the answer."
            st.session_state.chat_history.append(("assistant", reply))


# -----------------------------------
# Main App
# -----------------------------------
def main():
    db = setup_firebase()

    # handle OAuth return
    if "code" in st.query_params and "user" not in st.session_state:
        handle_oauth_callback()

    if "user" not in st.session_state:
        handle_authentication()
        return

    # image uploader in sidebar
    st.sidebar.markdown(f"#### 👋 Hello, {st.session_state.user['name']}")
    st.sidebar.file_uploader("Upload an image", type=["jpg", "jpeg", "png"],
                             key="uploaded_file")

    chat_interface()
    # whenever the user just appended a new chat entry, immediately call the model
    last = st.session_state.chat_history[-1]
    if last[0] == "user":
        process_user_input(last[1])
        # re-render with the assistant reply
        chat_interface()


if __name__ == "__main__":
    main()
