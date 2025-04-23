import streamlit as st
import os
import base64
import io
import json
import requests
from PIL import Image
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# ------------------------------------------------------------------------------
# 1) CONFIG & INITIALIZATION
# ------------------------------------------------------------------------------

load_dotenv()

BASE_URL = "https://yourkai.streamlit.app"  # <-- your deployed URL

# GenAI
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

# Firebase
def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        # JSON stored in FIREBASE_JSON env var
        cert_dict = json.loads(os.getenv("FIREBASE_JSON"))
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# ------------------------------------------------------------------------------
# 2) OAUTH ROUTINES
# ------------------------------------------------------------------------------

def get_google_auth_url():
    return (
        "https://accounts.google.com/o/oauth2/auth?"
        f"client_id={os.getenv('GOOGLE_CLIENT_ID')}&"
        f"redirect_uri={BASE_URL}&"
        "scope=email%20profile%20openid&"
        "response_type=code"
    )

def handle_oauth_callback():
    code = st.query_params.get("code")
    if not code:
        return

    # Exchange code for tokens
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": BASE_URL,
        "grant_type": "authorization_code"
    }
    res = requests.post(token_url, data=data).json()
    id_token = res.get("id_token")
    if not id_token:
        st.error("❌ Couldn't get ID token.")
        return

    # Get user info
    user_info = requests.get(
        f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    ).json()

    # Store only first name
    first_name = user_info.get("name", "User").split(" ")[0]

    st.session_state.user = {
        "uid": user_info.get("sub"),
        "name": first_name,
        "email": user_info.get("email"),
        "picture": user_info.get("picture")
    }

    # clear the query params so we don't process this again
    st.experimental_set_query_params({})
    # and trigger a fresh render
    st.experimental_rerun()

# ------------------------------------------------------------------------------
# 3) AUTHENTICATION LAYER
# ------------------------------------------------------------------------------

def login_screen():
    st.markdown("<style>body {background-color: #090c10;}</style>", unsafe_allow_html=True)
    cols = st.columns([1,2,1])
    with cols[1]:
        st.image("Logo_1.png", use_column_width=True)
        st.markdown("<p style='text-align:center;color:white;'>Please sign in or continue as guest.</p>",
                    unsafe_allow_html=True)

        if st.button("Sign in with Google", use_container_width=True):
            st.experimental_set_query_params({})
            st.markdown(f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">',
                        unsafe_allow_html=True)
            st.stop()

        st.markdown("<div style='text-align:center;color:white;'>— OR —</div>",
                    unsafe_allow_html=True)

        if st.button("Continue as Guest", use_container_width=True):
            st.session_state.user = {"uid":"guest","name":None,"picture":None}
            st.session_state.chat_history = [
                ("assistant","👋 Hey there! I'm KAI. What's your name?")
            ]
            st.session_state.awaiting_name = True
            st.experimental_rerun()

# ------------------------------------------------------------------------------
# 4) SIDEBAR W/ PROFILE & UPLOAD
# ------------------------------------------------------------------------------

def show_sidebar():
    with st.sidebar:
        if st.session_state.user.get("picture"):
            st.markdown(
                f"<img src='{st.session_state.user['picture']}' "
                "style='width:80px;height:80px;border-radius:50%;'>",
                unsafe_allow_html=True
            )
        else:
            st.image("Logo_1.png", width=80)

        if st.session_state.user.get("name"):
            st.write(f"Welcome, **{st.session_state.user['name']}**")

        if st.button("Sign Out"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.experimental_rerun()

        uploaded = st.file_uploader(
            "Upload an image",
            type=["jpg","png","jpeg"]
        )
        if uploaded:
            st.session_state.uploaded_image = uploaded
            st.session_state.image_processed = False

# ------------------------------------------------------------------------------
# 5) CHAT INTERFACE & LOGIC
# ------------------------------------------------------------------------------

def chat_interface():
    st.image("Logo_1.png", width=100)
    st.markdown("## KAI", unsafe_allow_html=True)
    st.markdown(
        "<style>[data-testid='stChatMessageContent'] > p {font-size:1.1rem;}</style>",
        unsafe_allow_html=True
    )

    # initialize
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            ("assistant","👋 Hello! I'm KAI, your rights guide. How can I help?")
        ]

    # render
    for role, msg in st.session_state.chat_history:
        st.chat_message(role).write(msg)

    # input
    user_input = st.chat_input("Type a message…")
    if not user_input:
        return

    # if guest just told us their name
    if st.session_state.user["uid"]=="guest" and st.session_state.user.get("name") is None:
        name = user_input.split()[0].capitalize()
        st.session_state.user["name"] = name
        st.session_state.awaiting_name = False
        st.session_state.chat_history.append(("user",user_input))
        st.session_state.chat_history.append(
            ("assistant",f"Nice to meet you, {name}! What can I do for you today?")
        )
        return  # next run will show the new UI

    # otherwise: real question → process inline
    st.session_state.chat_history.append(("user",user_input))

    # prepare parts
    parts = [user_input]
    img = st.session_state.get("uploaded_image")
    if img and not st.session_state.get("image_processed"):
        buf = io.BytesIO()
        Image.open(img).save(buf, format="JPEG")
        parts.append({"inline_data":{
            "mime_type":"image/jpeg",
            "data":base64.b64encode(buf.getvalue()).decode()
        }})
        st.session_state.image_processed = True

    # call Gemini synchronously
    with st.spinner("KAI is thinking…"):
        resp = model.generate_content({"role":"user","parts":parts})
        reply = resp.text or "Hmm, I couldn't quite get that."
        # personalize
        name = st.session_state.user.get("name")
        if name:
            reply = reply.replace("you", name)
        st.session_state.chat_history.append(("assistant",reply))

    # persist for logged-in users
    if st.session_state.user["uid"]!="guest":
        db = setup_firebase()
        db.collection("users")\
          .document(st.session_state.user["uid"])\
          .set({
            "chat_history":[{"role":r,"content":c}
                            for r,c in st.session_state.chat_history]
          },merge=True)

# ------------------------------------------------------------------------------
# 6) APP ENTRYPOINT
# ------------------------------------------------------------------------------

def main():
    setup_firebase()

    # 1) OAuth callback?
    if "code" in st.query_params and "user" not in st.session_state:
        handle_oauth_callback()

    # 2) still no user? show login
    if "user" not in st.session_state:
        login_screen()
        return

    # 3) load history for signed-in
    if st.session_state.user["uid"]!="guest":
        db = setup_firebase()
        doc = db.collection("users")\
                .document(st.session_state.user["uid"])\
                .get()
        if doc.exists:
            hist = doc.to_dict().get("chat_history",[])
            st.session_state.chat_history = [
                (m["role"],m["content"]) for m in hist
            ]

    # 4) show chat + sidebar
    show_sidebar()
    chat_interface()

if __name__=="__main__":
    main()
