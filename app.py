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
model = genai.GenerativeModel("gemini-1.5-flash", system_instruction="""
You are KAI, a warm, intelligent, and helpful assistant for international students, scholars, and individuals moving abroad. Your mission is to help users understand:
- Legal rights and visa regulations in different countries
- Cultural norms, traditions, and integration tips
- Educational pathways, admissions processes, and trending courses
- Safety information, housing options, healthcare systems, and transportation
- Financial planning, cost of living, and budgeting for international moves

Stay within these boundaries. If asked about topics outside your scope:
- For casual questions: respond with light wit or sarcasm matching the user's tone
- For serious but unrelated topics: politely redirect to your area of expertise

Maintain conversation context throughout the session. Remember user preferences, previous questions, and personal details they've shared to provide coherent assistance.

For image analysis:
- Process uploaded images once with your response
- Don't reprocess or mention the same image again unless specifically requested
- Focus on relevant information in images like documents, locations, or items related to international travel

Be conversational and natural - avoid stilted responses. Match your tone to the user's style, using humor when appropriate. Address users by name when available, and use second-person (you/your) over third-person references.
""")

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
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        display_logo()
        st.markdown("<p style='text-align: center;'>Sign in or continue as guest.</p>", unsafe_allow_html=True)
        if st.button("Sign in with Google", key="google_sign_in"):
            st.markdown(f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">', unsafe_allow_html=True)
            st.stop()
        if st.button("Continue as Guest"):
            st.session_state.user = {"uid": "guest", "name": None, "email": "", "picture": ""}
            st.session_state.chat_history = [
                ("assistant", "👋 Hey there! I'm KAI. What should I call you?")
            ]
            st.session_state.awaiting_name = True
            st.session_state.image_processed = False
            st.rerun()

def show_sidebar():
    with st.sidebar:
        if st.session_state.user.get("picture"):
            st.image(st.session_state.user['picture'], width=100)
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
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [("assistant", "Hey there! I'm KAI.")]
    for role, content in st.session_state.chat_history:
        st.chat_message(role).write(content)
    message_input()

def message_input():
    prompt = st.chat_input("Say Hello or ask something...")
    if prompt:
        if st.session_state.user["uid"] == "guest" and st.session_state.user.get("name") is None and st.session_state.awaiting_name:
            # Smart name extraction
            if any(x.lower() in prompt.lower() for x in ["my name is", "i am", "call me"]):
                words = prompt.replace(",", "").split()
                for i, word in enumerate(words):
                    if word.lower() in ["is", "am"] and i + 1 < len(words):
                        st.session_state.user["name"] = words[i + 1].capitalize()
                        st.session_state.awaiting_name = False
                        break
            st.session_state.chat_history.append(("user", prompt))
            if st.session_state.user.get("name"):
                st.session_state.chat_history.append(("assistant", f"Nice to meet you, {st.session_state.user['name']}! How can I help you today?"))
            else:
                st.session_state.chat_history.append(("assistant", "Got it! May I know your name so I can address you better?"))
            st.rerun()
        else:
            st.session_state.chat_history.append(("user", prompt))
            process_user_input(prompt)

def process_user_input(prompt):
    try:
        parts = [prompt]
        if st.session_state.get("uploaded_file_data") and not st.session_state.get("image_processed"):
            img = Image.open(st.session_state.uploaded_file_data)
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
            reply = res.text or "Sorry, I didn't quite get that. Mind rephrasing?"
            name = st.session_state.user.get("name")
            if name:
                reply = reply.replace("you", name).replace(f"{name}r", name)  # fix third-person
            st.session_state.chat_history.append(("assistant", reply))
        if st.session_state.user["uid"] != "guest":
            db = setup_firebase()
            db.collection("users").document(st.session_state.user["uid"]).set({
                "chat_history": [
                    {"role": role, "content": content}
                    for role, content in st.session_state.chat_history
                ]
            }, merge=True)
        st.rerun()
    except Exception as e:
        st.session_state.chat_history.append(("assistant", f"Yikes, something broke: {e}"))
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
            st.session_state.chat_history = [
                (msg["role"], msg["content"]) for msg in doc.to_dict().get("chat_history", [])
            ]
    show_sidebar()
    chat_interface()

if __name__ == "__main__":
    main()