import os, time, json, base64
import streamlit as st
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

BEXIO_CLIENT_ID = os.getenv("BEXIO_CLIENT_ID")
BEXIO_CLIENT_SECRET = os.getenv("BEXIO_CLIENT_SECRET")
BEXIO_REDIRECT_URI = os.getenv("BEXIO_REDIRECT_URI")

AUTH_URL  = "https://idp.bexio.com/authorize"
TOKEN_URL = "https://idp.bexio.com/token"
API_BASE  = "https://api.bexio.com/2.0"
JOURNAL_URL = f"{API_BASE}/journal"  # adjust if your tenant uses a different path

SCOPES = "openid profile email offline_access company_profile"

if "oauth" not in st.session_state:
    st.session_state.oauth = {}

def auth_header(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def save_tokens(tokens):
    # tokens = {access_token, refresh_token, expires_in, token_type, ...}
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600)) - 30
    st.session_state.oauth = tokens

def need_login():
    return not st.session_state.oauth or time.time() > st.session_state.oauth.get("expires_at", 0)

def refresh_access_token():
    if not st.session_state.oauth.get("refresh_token"):
        return
    data = {
        "grant_type": "refresh_token",
        "refresh_token": st.session_state.oauth["refresh_token"],
        "client_id": BEXIO_CLIENT_ID,
        "client_secret": BEXIO_CLIENT_SECRET,
        "redirect_uri": BEXIO_REDIRECT_URI,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    save_tokens(r.json())

def ensure_token():
    if need_login():
        st.stop()

def login_link():
    params = {
        "client_id": BEXIO_CLIENT_ID,
        "redirect_uri": BEXIO_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": "anti-csrf-" + base64.urlsafe_b64encode(os.urandom(12)).decode("utf-8"),
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    st.markdown(f"[Sign in with bexio]({url})")

def handle_callback():
    code = st.query_params.get("code")
    if not code:
        return
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": BEXIO_REDIRECT_URI,
        "client_id": BEXIO_CLIENT_ID,
        "client_secret": BEXIO_CLIENT_SECRET,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    save_tokens(r.json())
    # Clean query params so refreshes don’t re-run callback
    st.query_params.clear()

st.title("bexio Journal Poster")

# 1) Handle OAuth callback if present
handle_callback()

# 2) If not logged in, show login
if need_login():
    st.info("Connect your bexio account to continue.")
    login_link()
    st.stop()

# 3) Refresh token if needed
if time.time() > st.session_state.oauth.get("expires_at", 0):
    with st.spinner("Refreshing bexio session…"):
        refresh_access_token()

# 4) Build the posting form
with st.form("post_entry"):
    col1, col2 = st.columns(2)
    date = col1.date_input("Datum (YYYY-MM-DD)")
    beschreibung = col2.text_input("Beschreibung")

    col3, col4 = st.columns(2)
    amount = col3.number_input("Betrag", min_value=0.00, step=0.05, format="%.2f")
    waehrung = col4.text_input("Währung (z.B. CHF, EUR, USD)", value="CHF")

    col5, col6 = st.columns(2)
    waehrungskurs = col5.number_input("Währungskurs (currency_factor)", min_value=0.0, step=0.0001, format="%.6f", value=1.0)
    debit_kto = col6.text_input("Debit-Konto (z.B. 1020)")

    credit_kto = st.text_input("Credit-Konto (z.B. 3200)")

    submitted = st.form_s_
