import os, time, base64, re
import streamlit as st
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
from datetime import date as dt_date

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

AUTH_URL = "https://auth.bexio.com/realms/bexio/protocol/openid-connect/auth"
TOKEN_URL = "https://auth.bexio.com/realms/bexio/protocol/openid-connect/token"

API_V3 = "https://api.bexio.com/3.0"
MANUAL_ENTRIES_V3 = f"{API_V3}/accounting/manual_entries"
NEXT_REF_V3       = f"{API_V3}/accounting/manual_entries/next_ref_nr"

SCOPES = "openid profile email offline_access company_profile"

st.set_page_config(page_title="bexio Manual Entry Poster (v3)", page_icon="📘")

if "oauth" not in st.session_state:
    st.session_state.oauth = {}
if "acct_map" not in st.session_state:
    st.session_state.acct_map = {}   # {"1020": "77", "3200": "139"}
if "curr_map" not in st.session_state:
    st.session_state.curr_map = {}   # {"CHF": "1", "EUR": "2", "USD": "3"}

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

# ---------- mapping & validation helpers ----------

_SPLIT_RE = re.compile(r"\s*[:=,;\s]\s*")

def _parse_mapping(text: str, upper_keys=False):
    mapping, bad = {}, []
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        parts = [p for p in _SPLIT_RE.split(s) if p != ""]
        if len(parts) != 2:
            bad.append((i, line)); continue
        k, v = parts[0].strip(), parts[1].strip()
        if upper_keys:
            k = k.upper()
        if not k or not v:
            bad.append((i, line)); continue
        mapping[k] = v
    return mapping, bad

def resolve_account_id(user_value: str) -> int:
    s = str(user_value).strip()
    # if user typed an account number (e.g., "1020") and it's in mapping
    if s in st.session_state.acct_map:
        return int(st.session_state.acct_map[s])
    # otherwise treat as raw id
    val = int(s)
    if val <= 0:
        raise ValueError("Account-ID muss > 0 sein.")
    return val

def resolve_currency_id(user_value: str) -> int:
    s = str(user_value).strip().upper()
    if s in st.session_state.curr_map:
        return int(st.session_state.curr_map[s])
    val = int(s)
    if val <= 0:
        raise ValueError("currency_id muss > 0 sein.")
    return val

def normalize_iso_date(d):
    if isinstance(d, dt_date):
        return d.isoformat()
    s = str(d).strip().replace("/", "-").replace(".", "-")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise ValueError(f"Ungültiges Datum '{d}'. Erwartet: YYYY-MM-DD.")
    return s

# ---------- UI ----------

with st.expander("Config diagnostics"):
    dbg = {
        "client_id": BEXIO_CLIENT_ID[:3] + "…",
        "redirect_uri": BEXIO_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": "diag",
    }
    st.code(f"{AUTH_URL}?{urlencode(dbg)}")

st.title("📘 bexio Manual Entry Poster (API v3)")

# OAuth
handle_callback()
if need_login():
    st.info("Verbinde dein bexio Konto, um Buchungen zu posten.")
    login_link()
    st.stop()

if time.time() > st.session_state.oauth.get("expires_at", 0):
    with st.spinner("Session wird erneuert …"):
        refresh_access_token()

# Mapping helpers (flexible parsers)
with st.expander("Optional: Konto-Nr → ID Mapping (eine pro Zeile; erlaubt: = : , ; oder Leerzeichen)"):
    mapping_text = st.text_area(
        "Konten-Mapping",
        value="",
        height=140,
        placeholder="Beispiele:\n1020=77\n3200:139\n1000,55\n2400    88\n# Kommentare erlaubt",
    )
    if st.button("Konten-Mapping übernehmen"):
        new_map, bad = _parse_mapping(mapping_text, upper_keys=False)
        st.session_state.acct_map.update(new_map)
        st.success(f"{len(new_map)} Konten übernommen.")
        if bad:
            st.warning("Konnte nicht lesen:\n" + "\n".join([f"Zeile {ln}: {txt}" for ln, txt in bad[:5]]) + ("…" if len(bad)>5 else ""))
    if st.session_state.acct_map:
        st.caption("Aktuelles Konten-Mapping (erste 20):")
        st.json(dict(list(st.session_state.acct_map.items())[:20]))

with st.expander("Optional: Währungscode → currency_id (eine pro Zeile; z. B. CHF=1)"):
    curr_text = st.text_area(
        "Währungs-Mapping",
        value="",
        height=120,
        placeholder="CHF=1\nEUR:2\nUSD,3\n# Kommentare erlaubt",
    )
    if st.button("Währungs-Mapping übernehmen"):
        new_map, bad = _parse_mapping(curr_text, upper_keys=True)
        st.session_state.curr_map.update(new_map)
        st.success(f"{len(new_map)} Währungen übernommen.")
        if bad:
            st.warning("Konnte nicht lesen:\n" + "\n".join([f"Zeile {ln}: {txt}" for ln, txt in bad[:5]]) + ("…" if len(bad)>5 else ""))
    if st.session_state.curr_map:
        st.caption("Aktuelles Währungs-Mapping:")
        st.json(st.session_state.curr_map)

# Form
with st.form("post_entry"):
    col1, col2 = st.columns(2)
    date_val = col1.date_input("Datum (YYYY-MM-DD)")
    beschreibung = col2.text_input("Beschreibung / Text")

    col3, col4 = st.columns(2)
    amount = col3.number_input("Betrag", min_value=0.00, step=0.05, format="%.2f", value=0.00)
    waehrung = col4.text_input("Währung (Code oder ID)", value="CHF")

    col5, col6 = st.columns(2)
    waehrungskurs = col5.number_input("Währungskurs (currency_factor)", min_value=0.0, step=0.0001,
                                      format="%.6f", value=1.0)
    debit_kto = col6.text_input("Debit-Konto (Nr oder ID, z. B. 1020 oder 77)")
    credit_kto = st.text_input("Credit-Konto (Nr oder ID, z. B. 3200 oder 139)")

    use_next_ref = st.checkbox("Referenznummer automatisch beziehen", value=True)
    reference_nr = st.text_input("Referenznummer (optional)", value="")

    submitted = st.form_submit_button("Manuelle Buchung erstellen")

if submitted:
    try:
        post_date   = normalize_iso_date(date_val)
        debit_id    = resolve_account_id(debit_kto)
        credit_id   = resolve_account_id(credit_kto)
        currency_id = resolve_currency_id(waehrung)

        ref_nr = reference_nr.strip()
        if use_next_ref and not ref_nr:
            rr = requests.get(NEXT_REF_V3, headers=auth_header(st.session_state.oauth["access_token"]), timeout=15)
            rr.raise_for_status()
            ref_nr = (rr.json() or {}).get("next_ref_nr") or ""

        entry = {
            "debit_account_id": debit_id,
            "credit_account_id": credit_id,
            "amount": float(amount),
            "description": beschreibung or "",
            "currency_id": int(currency_id),
            "currency_factor": float(waehrungskurs),
        }

        payload = {
            "type": "manual_single_entry",
            "date": post_date,
            "entries": [entry],
        }
        if ref_nr:
            payload["reference_nr"] = ref_nr

        r = requests.post(
            MANUAL_ENTRIES_V3,
            headers={**auth_header(st.session_state.oauth["access_token"]), "Content-Type": "application/json"},
            json=payload, timeout=30
        )
        if r.status_code == 401:
            refresh_access_token()
            r = requests.post(
                MANUAL_ENTRIES_V3,
                headers={**auth_header(st.session_state.oauth["access_token"]), "Content-Type": "application/json"},
                json=payload, timeout=30
            )
        if r.status_code == 429:
            st.error("Rate limit (429). Bitte später erneut versuchen.")
            st.stop()

        r.raise_for_status()
        st.success("✅ Manuelle Buchung erfolgreich erstellt.")
        st.json(r.json())

    except requests.HTTPError as e:
        st.error(f"HTTP error: {e.response.status_code} – {e.response.text}")
    except ValueError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Unexpected error: {e}")



