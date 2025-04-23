import streamlit as st
import os, io, json, base64, requests
from PIL import Image
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# ─── CONFIG ────────────────────────────────────────────────────────────────────
load_dotenv()
BASE_URL = "https://yourkai.streamlit.app"  # change to your URL
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        cred_dict = json.loads(os.getenv("FIREBASE_JSON"))
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# ─── OAUTH HELPERS ─────────────────────────────────────────────────────────────
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
    # exchange code
    token = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": BASE_URL,
            "grant_type": "authorization_code"
        },
    ).json()
    id_token = token.get("id_token")
    if not id_token:
        st.error("❌ Couldn't fetch ID token")
        return
    info = requests.get(
        f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    ).json()
    first_name = info.get("name", "User").split()[0]
    st.session_state.user = {
        "uid": info["sub"], "name": first_name,
        "email": info.get("email"), "picture": info.get("picture")
    }
    st.experimental_set_query_params({})

# ─── LOGIN SCREEN ──────────────────────────────────────────────────────────────
def login_screen():
    st.markdown("<style>body{background:#090c10;}</style>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.image("Logo_1.png", use_column_width=True)
        st.markdown("<p style='text-align:center;color:white;'>Sign in or continue as guest.</p>", unsafe_allow_html=True)
        if st.button("Sign in with Google"):
            st.markdown(f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">', unsafe_allow_html=True)
            st.stop()
        st.markdown("<div style='text-align:center;color:white;'>— OR —</div>", unsafe_allow_html=True)
        if st.button("Continue as Guest"):
            st.session_state.user = {"uid":"guest","name":None,"picture":None}
            st.session_state.awaiting_name = True
            st.session_state.chat_history = [
                ("assistant", "👋 Hey there! I'm KAI. What's your name?")
            ]

# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
def show_sidebar():
    with st.sidebar:
        pic = st.session_state.user.get("picture")
        if pic:
            st.markdown(f"<img src='{pic}' style='border-radius:50%;width:80px;height:80px;'>", unsafe_allow_html=True)
        else:
            st.image("Logo_1.png", width=80)
        name = st.session_state.user.get("name")
        if name:
            st.write(f"Welcome, **{name}**")
        if st.button("Sign Out"):
            st.session_state.clear()
            return
        up = st.file_uploader("Upload an image", type=["jpg","jpeg","png"])
        if up:
            st.session_state.uploaded_image = up
            st.session_state.image_processed = False

# ─── CHAT UI ──────────────────────────────────────────────────────────────────
def chat_interface():
    st.image("Logo_1.png", width=100)
    st.markdown("## KAI")
    st.markdown("<style>[data-testid='stChatMessageContent'] > p{font-size:1.1rem;}</style>", unsafe_allow_html=True)

    # init history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            ("assistant", "👋 Hello! I'm KAI, your rights guide. How can I help?")
        ]

    # display
    for role, text in st.session_state.chat_history:
        st.chat_message(role).write(text)

    # user input
    msg = st.chat_input("Type your message…")
    if not msg:
        return

    # if guest needs naming
    if st.session_state.user["uid"]=="guest" and st.session_state.user.get("name") is None:
        nm = msg.split()[0].capitalize()
        st.session_state.user["name"] = nm
        st.session_state.chat_history.append(("user", msg))
        st.session_state.chat_history.append(("assistant", f"Nice to meet you, {nm}! What can I do for you today?"))
        return

    # normal flow
    st.session_state.chat_history.append(("user", msg))
    parts = [msg]
    img = st.session_state.get("uploaded_image")
    if img and not st.session_state.get("image_processed"):
        buf = io.BytesIO()
        Image.open(img).save(buf, format="JPEG")
        parts.append({
            "inline_data":{
                "mime_type":"image/jpeg",
                "data":base64.b64encode(buf.getvalue()).decode()
            }
        })
        st.session_state.image_processed = True

    with st.spinner("KAI is thinking…"):
        resp = model.generate_content({"role":"user","parts":parts})
        reply = resp.text or "Sorry, I didn’t catch that."
        nm = st.session_state.user.get("name")
        if nm:
            reply = reply.replace("you", nm)
        st.session_state.chat_history.append(("assistant", reply))

    # persist signed-in
    if st.session_state.user["uid"]!="guest":
        db = setup_firebase()
        db.collection("users")\
          .document(st.session_state.user["uid"])\
          .set({
            "chat_history":[{"role":r,"content":c}
                            for r,c in st.session_state.chat_history]
          }, merge=True)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    setup_firebase()

    # handle OAuth return
    if "code" in st.query_params and "user" not in st.session_state:
        handle_oauth_callback()

    # not logged in?
    if "user" not in st.session_state:
        login_screen()
        return

    # load existing history
    if st.session_state.user["uid"]!="guest":
        db = setup_firebase()
        doc = db.collection("users")\
                .document(st.session_state.user["uid"])\
                .get()
        if doc.exists:
            hist = doc.to_dict().get("chat_history",[])
            st.session_state.chat_history = [(m["role"],m["content"]) for m in hist]

    # UI
    show_sidebar()
    chat_interface()

if __name__=="__main__":
    main()
