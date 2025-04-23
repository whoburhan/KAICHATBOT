import streamlit as st
import os, io, json, base64, requests
from PIL import Image
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# ―― CONFIG ――
load_dotenv()
BASE_URL = "https://yourkai.streamlit.app"
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def setup_firebase():
    try:
        firebase_admin.get_app()
    except ValueError:
        cert_dict = json.loads(os.getenv("FIREBASE_JSON"))
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# ―― OAUTH HELPERS ――
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
    tok = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": BASE_URL,
            "grant_type": "authorization_code",
        },
    ).json()
    id_token = tok.get("id_token")
    if not id_token:
        st.error("❌ Couldn't get ID token")
        return
    info = requests.get(
        f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    ).json()
    first = info.get("name", "User").split()[0]
    st.session_state.user = {
        "uid": info["sub"],
        "name": first,
        "email": info.get("email", ""),
        "picture": info.get("picture", ""),
    }
    st.experimental_set_query_params({})

# ―― UI BLOCKS ――
def login_screen():
    st.markdown("<style>body{background:#090c10;}</style>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.image("Logo_1.png", use_column_width=True)
        st.markdown("<p style='color:white;text-align:center;'>Sign in or continue as guest</p>", unsafe_allow_html=True)
        if st.button("Sign in with Google"):
            st.markdown(f'<meta http-equiv="refresh" content="0; url={get_google_auth_url()}">', unsafe_allow_html=True)
            st.stop()
        st.markdown("<div style='color:white;text-align:center;'>— OR —</div>", unsafe_allow_html=True)
        if st.button("Continue as Guest"):
            st.session_state.user = {"uid": "guest", "name": None, "picture": None}
            st.session_state.awaiting_name = True
            st.session_state.chat_history = [
                ("assistant", "👋 Hey there! I'm KAI. What's your name?")
            ]

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
            st.experimental_rerun()
        up = st.file_uploader("Upload image", type=["jpg","jpeg","png"])
        if up:
            st.session_state.uploaded_image = up
            st.session_state.image_processed = False

# ―― CHAT FLOW ――
def process_user_input(msg):
    st.session_state.chat_history.append(("user", msg))
    parts = [msg]
    img = st.session_state.get("uploaded_image")
    if img and not st.session_state.get("image_processed"):
        buf = io.BytesIO()
        Image.open(img).save(buf, format="JPEG")
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(buf.getvalue()).decode(),
            }
        })
        st.session_state.image_processed = True

    with st.spinner("KAI is thinking…"):
        resp = model.generate_content({"role": "user", "parts": parts})
        text = resp.text or "Sorry, I didn’t catch that."
        nm = st.session_state.user.get("name")
        if nm:
            text = text.replace("you", nm)
        st.session_state.chat_history.append(("assistant", text))

    if st.session_state.user["uid"] != "guest":
        db = setup_firebase()
        db.collection("users")\
          .document(st.session_state.user["uid"])\
          .set({
              "chat_history": [
                  {"role":r,"content":c}
                  for r,c in st.session_state.chat_history
              ]
          }, merge=True)

# ―― MAIN ――
def main():
    # … auth & sidebar code …

    # 1) load or init history  
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            ("assistant", "👋 Hello! I'm KAI. What can I call you?")
        ]

    # 2) **capture** new user input first (no lag)  
    new_msg = st.chat_input("Your message…")
    if new_msg:
        # handle first-time guest naming
        if st.session_state.user["uid"] == "guest" and st.session_state.user["name"] is None:
            name = new_msg.split()[0].capitalize()
            st.session_state.user["name"] = name
            st.session_state.chat_history.append(("user", new_msg))
            st.session_state.chat_history.append(
                ("assistant", f"Nice to meet you, {name}! What can I do for you today?")
            )
        else:
            # queue it for the model
            st.session_state.chat_history.append(("user", new_msg))
            # inline generate
            with st.spinner("KAI is thinking…"):
                resp = model.generate_content({"role":"user","parts":[new_msg]})
                text = resp.text or "Sorry, can you rephrase?"
                st.session_state.chat_history.append(("assistant", text))

        # persist for logged-in users here (no rerun)

    # 3) now render everything
    for role, txt in st.session_state.chat_history:
        st.chat_message(role).write(txt)


if __name__ == "__main__":
    main()
