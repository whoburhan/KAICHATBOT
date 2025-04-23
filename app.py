import streamlit as st
import os
import base64
from dotenv import load_dotenv
import io
import requests
from PIL import Image
import json

# Load environment
load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# Firebase initialization
def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_json = os.getenv("FIREBASE_JSON")
        cert_dict = json.loads(firebase_json)
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Configure Gemini API
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
    params = st.experimental_get_query_params()
    if "code" in params and "user" not in st.session_state:
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
            info = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}").json()
            name = info.get("name", "User").split()[0]
            st.session_state.user = {"uid": info.get("sub"), "name": name, "email": info.get("email"), "picture": info.get("picture")}
        st.experimental_set_query_params({})

# UI components
def display_logo():
    st.image("Logo_1.png", width=150)

def show_login():
    st.markdown("<style>body{background:#090c10;color:#fff;}</style>", unsafe_allow_html=True)
    display_logo()
    st.header("Welcome to KAI - Your Rights Assistant")
    if st.button("Sign in with Google"):
        st.markdown(f"<meta http-equiv='refresh' content='0; url={get_google_auth_url()}'>", unsafe_allow_html=True)
    st.write("--- Or ---")
    if st.button("Continue as Guest"):
        st.session_state.user = {"uid":"guest","name":None,"email":"","picture":""}
        st.session_state.chat_history = [("assistant","👋 Hi! I'm KAI. What should I call you?")]

def show_sidebar():
    with st.sidebar:
        if st.session_state.user.get("picture"):
            st.image(st.session_state.user['picture'], width=80, clamp=True)
        else:
            st.image("Logo_1.png", width=80)
        if st.session_state.user.get("name"):
            st.write(f"Hello, {st.session_state.user['name']}!")
        if st.button("Sign Out"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.experimental_rerun()
        uploaded_file = st.file_uploader("Upload an image", type=["jpg","jpeg","png"])
        if uploaded_file:
            st.session_state.uploaded_image = uploaded_file
            st.session_state.image_processed = False

def chat_interface():
    st.header("🤖 KAI Chat")
    # Initialize history if missing
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [("assistant","👋 Hello! I'm KAI. How can I help you?")]
    # Display all messages
    for role, msg in st.session_state.chat_history:
        st.chat_message(role).write(msg)
    # Input prompt and immediate response
    prompt = st.chat_input("Your message...")
    if prompt:
        # Guest naming
        if st.session_state.user['uid']=='guest' and not st.session_state.user.get('name'):
            name = prompt.split()[0].capitalize()
            st.session_state.user['name']=name
            st.session_state.chat_history.append(("user",prompt))
            st.session_state.chat_history.append(("assistant",f"Nice to meet you, {name}!"))
        else:
            # Append user
            st.session_state.chat_history.append(("user",prompt))
            # Prepare parts
            parts=[prompt]
            img = st.session_state.get('uploaded_image')
            if img and not st.session_state.get('image_processed'):
                buf=io.BytesIO()
                Image.open(img).save(buf,format='JPEG')
                parts.append({'inline_data':{'mime_type':'image/jpeg','data':base64.b64encode(buf.getvalue()).decode()}})
                st.session_state.image_processed=True
            # Build context
            context=[]
            for r,m in st.session_state.chat_history:
                role_tag='user' if r=='user' else 'model'
                context.append({'role':role_tag,'parts':[m]})
            # Call Gemini
            with st.spinner("KAI is thinking..."):
                try:
                    res=model.generate_content(context)
                    reply=res.text or "Sorry, try rephrasing."
                except Exception as e:
                    reply=f"Error: {e}"
            # Personalize
            name=st.session_state.user.get('name')
            if name:
                reply=reply.replace('you',name)
            # Append assistant
            st.session_state.chat_history.append(("assistant",reply))
            # Persist for logged-in
            if st.session_state.user['uid']!='guest':
                db=setup_firebase()
                db.collection('users').document(st.session_state.user['uid']).set({'chat_history':[{'role':r,'content':m} for r,m in st.session_state.chat_history]},merge=True)

def main():
    setup_firebase()
    handle_oauth_callback()
    if 'user' not in st.session_state:
        show_login()
        return
    show_sidebar()
    chat_interface()

if __name__=='__main__':
    main()