import os, time, base64
import streamlit as st
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

# --------- LOAD .env LOCALLY OR IN REPO ----------
# Note: On some hosted environments, .env may be ignored for security.
# If you deploy and it fails to load, set real OS env vars instead.
load_dotenv()

def _getenv(name: str, required=True, default=None):
    v = os.getenv(name, default)
    if required and (v is None or v.strip() == ""):
        st.stop()  # immediately stop with a clear message on the page
    return v

BEXIO_CLIENT_ID     = _getenv("BEXIO_CLIENT_ID")
BEXIO_CLIENT_SECRET = _getenv("BEXIO_CLIENT_SECRET")
BEXIO_REDIRECT_URI  = _getenv("BEXIO_REDIRECT_URI")

AUTH_URL  = "https://idp.bexio.com/authorize"
TOKEN_URL = "https://idp.bexio.com/token"
API_BASE  = "https://api.bexio.com/2.0"
JOURNAL_URL = f"{API_BASE}/journal"  # adjust if your tenant uses a different path

SCOPES = "openid profile email offline_access company_profile"

st.set_page_config(page_title="bexio Journal Poster", page_icon="📘")

if "oauth" not in st.session_state:
    st.session_state.oauth = {}

def auth_header(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def save_tokens(tokens):
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

def login_link():
    state = "anti-csrf-" + base64.urlsafe_b64encode(os.urandom(12)).decode("utf-8")
    params = {
        "client_id": BEXIO_CLIENT_ID,
        "redirect_uri": BEXIO_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
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
    st.query_params.clear()

st.title("📘 bexio Journal Poster")

# 1) OAuth callback
handle_callback()

# 2) If not logged in, show login
if need_login():
    st.info("Verbinde dein bexio Konto, um Buchungen zu posten.")
    login_link()
    st.stop()

# 3) Refresh if needed
if time.time() > st.session_state.oauth.get("expires_at", 0):
    with st.spinner("Session wird erneuert …"):
        refresh_access_token()

# 4) Form
with st.form("post_entry"):
    col1, col2 = st.columns(2)
    date = col1.date_input("Datum (YYYY-MM-DD)")
    beschreibung = col2.text_input("Beschreibung")

    col3, col4 = st.columns(2)
    amount = col3.number_input("Betrag", min_value=0.00, step=0.05, format="%.2f")
    waehrung = col4.text_input("Währung (CHF/EUR/USD …)", value="CHF")

    col5, col6 = st.columns(2)
    waehrungskurs = col5.number_input("Währungskurs (currency_factor)", min_value=0.0, step=0.0001, format="%.6f", value=1.0)
    debit_kto = col6.text_input("Debit-Konto (z. B. 1020)")

    credit_kto = st.text_input("Credit-Konto (z. B. 3200)")
    submitted = st.form_submit_button("Buchen")

if submitted:
    payload = {
        "date": str(date),
        "text": beschreibung,
        "amount": float(amount),
        "currency": waehrung,
        "currency_factor": float(waehrungskurs),
        "debit_account": str(debit_kto),
        "credit_account": str(credit_kto),
    }
    try:
        r = requests.post(JOURNAL_URL, headers=auth_header(st.session_state.oauth["access_token"]),
                          json=payload, timeout=30)
        if r.status_code == 401:
            refresh_access_token()
            r = requests.post(JOURNAL_URL, headers=auth_header(st.session_state.oauth["access_token"]),
                              json=payload, timeout=30)
        if r.status_code == 429:
            st.error("Rate limit (429). Bitte später erneut versuchen.")
        r.raise_for_status()
        st.success("Buchung erfolgreich erfasst.")
        st.json(r.json())
    except requests.HTTPError as e:
        st.error(f"HTTP error: {e.response.status_code} – {e.response.text}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")

