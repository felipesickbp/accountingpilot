import os, time, base64
import streamlit as st
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

# --------- LOAD .env ----------
load_dotenv(override=True)

def _getenv(name: str, required=True, default=None):
    v = os.getenv(name, default)
    if required and (v is None or v.strip() == ""):
        st.error(f"Missing required env: {name}")
        st.stop()
    return v

BEXIO_CLIENT_ID     = _getenv("BEXIO_CLIENT_ID")
BEXIO_CLIENT_SECRET = _getenv("BEXIO_CLIENT_SECRET")
BEXIO_REDIRECT_URI  = _getenv("BEXIO_REDIRECT_URI")

# OIDC (new IdP)
AUTH_URL   = "https://auth.bexio.com/realms/bexio/protocol/openid-connect/auth"
TOKEN_URL  = "https://auth.bexio.com/realms/bexio/protocol/openid-connect/token"
USERINFO_URL = "https://auth.bexio.com/realms/bexio/protocol/openid-connect/userinfo"

# bexio APIs
API_V2      = "https://api.bexio.com/2.0"
API_V3      = "https://api.bexio.com/3.0"
ACCOUNTS_V2 = f"{API_V2}/account"  # to resolve account number -> id
MANUAL_ENTRIES_V3 = f"{API_V3}/accounting/manual_entries"
NEXT_REF_V3       = f"{API_V3}/accounting/manual_entries/next_ref_nr"

SCOPES = "openid profile email offline_access company_profile"

st.set_page_config(page_title="bexio Manual Entry Poster", page_icon="📘")

if "oauth" not in st.session_state:
    st.session_state.oauth = {}
if "accounts_map" not in st.session_state:
    st.session_state.accounts_map = {}  # {"1020": 77, ...}

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

def ensure_accounts_loaded():
    """Load chart of accounts (v2) and map account number -> id."""
    if st.session_state.accounts_map:
        return
    r = requests.get(ACCOUNTS_V2, headers=auth_header(st.session_state.oauth["access_token"]), timeout=30)
    r.raise_for_status()
    accounts = r.json()
    # v2 /account has fields like: { "id": 77, "no": "1020", "name": "...", ... }
    st.session_state.accounts_map = {str(a.get("no")).strip(): int(a.get("id")) for a in accounts if a.get("no")}

def resolve_account_id(user_input: str):
    """Accepts '1020' (account no) or a raw integer ID; returns an int ID or raises."""
    s = str(user_input).strip()
    # try by account number
    if s in st.session_state.accounts_map:
        return st.session_state.accounts_map[s]
    # try as integer ID
    try:
        return int(s)
    except:
        raise ValueError(f"Konto '{user_input}' konnte nicht aufgelöst werden (Nummer oder ID).")

# ---------- UI ----------
with st.expander("Config diagnostics"):
    st.write("BEXIO_REDIRECT_URI:", repr(BEXIO_REDIRECT_URI))
    dbg = {
        "client_id": BEXIO_CLIENT_ID[:3] + "…",
        "redirect_uri": BEXIO_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": "diag",
    }
    st.code(f"{AUTH_URL}?{urlencode(dbg)}")

st.title("📘 bexio Manual Entry Poster (API v3)")

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

# 4) Load accounts once (to resolve 1020/3200 -> IDs)
try:
    ensure_accounts_loaded()
except Exception as e:
    st.warning(f"Konten konnten nicht geladen werden: {e}")

# 5) Form for manual entry (single line)
with st.form("post_entry"):
    col1, col2 = st.columns(2)
    date = col1.date_input("Datum (YYYY-MM-DD)")
    beschreibung = col2.text_input("Beschreibung / Text")

    col3, col4 = st.columns(2)
    amount = col3.number_input("Betrag", min_value=0.00, step=0.05, format="%.2f", value=0.00)
    waehrung = col4.text_input("Währung (optional, z. B. CHF/EUR/USD)", value="CHF")

    col5, col6 = st.columns(2)
    waehrungskurs = col5.number_input("Währungskurs (currency_factor, optional)", min_value=0.0, step=0.0001, format="%.6f", value=1.0)
    debit_kto = col6.text_input("Debit-Konto (z. B. 1020 oder ID)")

    credit_kto = st.text_input("Credit-Konto (z. B. 3200 oder ID)")

    use_next_ref = st.checkbox("Automatisch Referenznummer von bexio beziehen", value=True)
    reference_nr = st.text_input("Referenznummer (optional, überschreibt Auto)", value="")

    submitted = st.form_submit_button("Manuelle Buchung erstellen")

if submitted:
    try:
        debit_id = resolve_account_id(debit_kto)
        credit_id = resolve_account_id(credit_kto)

        # Optionally fetch next reference number
        ref_nr = reference_nr.strip()
        if use_next_ref and not ref_nr:
            rr = requests.get(NEXT_REF_V3, headers=auth_header(st.session_state.oauth["access_token"]), timeout=15)
            rr.raise_for_status()
            ref_nr = rr.json().get("next_ref_nr") or ""

        # Build v3 payload
        entry = {
            "debit_account_id": debit_id,
            "credit_account_id": credit_id,
            "amount": float(amount),
            "description": beschreibung or ""
        }
        # Only include currency fields if they differ from base or are meaningful
        if waehrung:
            entry["currency"] = waehrung
        if waehrungskurs and float(waehrungskurs) != 1.0:
            entry["currency_factor"] = float(waehrungskurs)

        payload = {
            "type": "manual_single_entry",         # or manual_compound_entry / manual_group_entry
            "date": str(date),
            "entries": [entry],
        }
        if ref_nr:
            payload["reference_nr"] = ref_nr

        r = requests.post(
            MANUAL_ENTRIES_V3,
            headers={**auth_header(st.session_state.oauth["access_token"]), "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )

        # Token could have expired right at POST
        if r.status_code == 401:
            refresh_access_token()
            r = requests.post(
                MANUAL_ENTRIES_V3,
                headers={**auth_header(st.session_state.oauth["access_token"]), "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )

        if r.status_code == 429:
            st.error("Rate limit (429). Bitte später erneut versuchen.")
            st.stop()

        r.raise_for_status()
        st.success("Manuelle Buchung erfolgreich erstellt.")
        st.json(r.json())

    except requests.HTTPError as e:
        st.error(f"HTTP error: {e.response.status_code} – {e.response.text}")
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Unexpected error: {e}")

# Helper: quick peek at loaded accounts (optional)
with st.expander("Geladene Konten-Vorschau (Nr → ID)"):
    try:
        preview = list(st.session_state.accounts_map.items())[:20]
        st.write(dict(preview))
    except Exception:
        st.write("Keine Konten geladen.")

