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

# Configure Gemini with enhanced system instruction
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_INSTRUCTION = """
You are KAI, a specialized assistant for international students, scholars, and expatriates. Your expertise is strictly limited to:

CORE DOMAINS:
1. Visa regulations and immigration procedures
2. Cultural norms and social integration
3. Education systems and admissions
4. Housing, healthcare, transportation, safety
5. Financial planning for relocation

COMMUNICATION RULES:
- ALWAYS use second-person (you/your)
- NEVER use third-person references
- Use the user's name sparingly (1-2 times per response max)
- No repetitive greetings in ongoing conversations
- Never say "as mentioned before" or similar phrases

RESPONSE GUIDELINES:
- Be concise (2-3 paragraphs max)
- Use bullet points for complex information
- Provide authoritative sources when possible
- For off-topic queries:
  * Playful questions → matching witty response
  * Serious questions → polite redirection
"""

model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_INSTRUCTION)

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
    st.image("Logo_1.png", use_column_width=True)

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
                ("assistant", "👋 Hi there! I'm KAI. What should I call you?")
            ]
            st.session_state.awaiting_name = True
            st.session_state.image_processed = False
            st.session_state.conversation_active = False
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
        
        if st.button("Clear Conversation"):
            if st.session_state.user.get("name"):
                st.session_state.chat_history = [
                    ("assistant", f"How can I help you, {st.session_state.user['name']}?")
                ]
            else:
                st.session_state.chat_history = [
                    ("assistant", "How can I help you today?")
                ]
            st.rerun()
        
        uploaded_file = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png"])
        if uploaded_file:
            st.session_state.uploaded_file_data = uploaded_file
            st.session_state.image_processed = False

def chat_interface():
    display_logo()
    
    for role, content in st.session_state.chat_history:
        with st.chat_message(role):
            st.write(content)
    
    message_input()

def message_input():
    prompt = st.chat_input("Ask about visas, culture, housing, or other international topics...")
    if prompt:
        if not st.session_state.get("conversation_active"):
            st.session_state.conversation_active = True
            
        if st.session_state.user["uid"] == "guest" and st.session_state.user.get("name") is None and st.session_state.awaiting_name:
            handle_guest_name(prompt)
        else:
            st.session_state.chat_history.append(("user", prompt))
            process_user_input(prompt)

def handle_guest_name(prompt):
    st.session_state.chat_history.append(("user", prompt))
    
    name = None
    if any(x.lower() in prompt.lower() for x in ["my name is", "i am", "call me"]):
        words = prompt.replace(",", "").split()
        for i, word in enumerate(words):
            if word.lower() in ["is", "am"] and i + 1 < len(words):
                name = words[i + 1].capitalize()
                break
    
    if name:
        st.session_state.user["name"] = name
        st.session_state.awaiting_name = False
        st.session_state.chat_history.append(("assistant", f"Got it, {name}! How can I assist you with your international plans?"))
    else:
        st.session_state.chat_history.append(("assistant", "May I know what name I should call you?"))
    
    st.rerun()

def fix_pronouns(text, name=None):
    if not name:
        return text
    
    replacements = {
        f"{name} is": "you are",
        f"{name}'s": "your",
        f"{name} has": "you have",
        f"{name} should": "you should",
        f"{name} can": "you can",
        f"{name} needs": "you need"
    }
    
    for wrong, correct in replacements.items():
        text = text.replace(wrong.lower(), correct)
    
    return text

def clean_response(text, skip_greeting):
    if skip_greeting:
        unwanted = [
            "welcome back",
            "hello again",
            "as we discussed",
            "as I mentioned",
            "let me reintroduce myself"
        ]
        for phrase in unwanted:
            if phrase in text.lower():
                text = text.lower().replace(phrase, "").capitalize()
    
    # Ensure no empty responses
    if not text.strip():
        return "How can I assist you with this?"
    
    return text.strip()

def process_user_input(prompt):
    try:
        skip_greeting = st.session_state.get("conversation_active", False)
        
        context = "\n".join([f"{role}: {content}" for role, content in st.session_state.chat_history[-4:]])
        
        full_prompt = f"""
        USER QUERY: {prompt}
        
        CONTEXT:
        {context}
        
        RESPONSE RULES:
        1. {"NO GREETINGS" if skip_greeting else "Brief welcome if first interaction"}
        2. Always use second-person
        3. Be concise and helpful
        4. Never repeat previous responses
        """
        
        parts = [full_prompt]
        
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
            reply = res.text or "Could you please rephrase that?"
            
            reply = clean_response(reply, skip_greeting)
            
            name = st.session_state.user.get("name")
            if name:
                reply = fix_pronouns(reply, name)
            
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
        st.session_state.chat_history.append(("assistant", "Apologies, I encountered an error. Please try again."))
        st.rerun()

def main():
    st.set_page_config(page_title="KAI - Your International Assistant", page_icon="🌍")
    
    setup_firebase()
    
    if "code" in st.query_params and "user" not in st.session_state:
        handle_oauth_callback()
    
    if "user" not in st.session_state:
        handle_authentication()
        return
    
    if "conversation_active" not in st.session_state:
        st.session_state.conversation_active = False
    
    if st.session_state.user["uid"] != "guest":
        db = setup_firebase()
        doc = db.collection("users").document(st.session_state.user["uid"]).get()
        if doc.exists:
            st.session_state.chat_history = [
                (msg["role"], msg["content"]) for msg in doc.to_dict().get("chat_history", [])
            ]
            st.session_state.conversation_active = True
    
    if "chat_history" not in st.session_state:
        if st.session_state.user.get("name"):
            greeting = f"Hi {st.session_state.user['name']}! How can I help you today?"
        else:
            greeting = "Hello! How can I assist you with your international plans?"
        
        st.session_state.chat_history = [("assistant", greeting)]
    
    show_sidebar()
    chat_interface()

if __name__ == "__main__":
    main()