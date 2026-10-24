"""2.1.0 safety: the agent never invents or types credentials, and stops on sign-in / sign-up pages.
Enforced in code for both the extension (web) loop and the screenshot (vision) loop, not just in the prompt."""
import re

FIELD = re.compile(r"e-?mail|user\s*name|username|login|log in|sign[\s-]?in|pass(word|code|phrase)?|\bpin\b|one[\s-]time|\botp\b|2fa|"
                   r"two[\s-]factor|verification|security code|auth(entication)? code|\bcode\b|account|credential|phone", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
FAKE = re.compile(r"\b(test|demo|example|sample|dummy|fake|user|admin|guest)(user|name|pass(word)?|123|@)?\b|password|passw0rd|p@ss|123456|qwerty", re.I)
AUTH_URL = re.compile(r"/(login|log-in|signin|sign-in|sign_in|signup|sign-up|sign_up|join|register|session|sessions|auth|oauth|"
                      r"accounts/(login|signin)|ServiceLogin|identifier|password_reset|two-factor|2fa|verify)(\b|/|\?|$)", re.I)
AUTH_HOST = re.compile(r"^(accounts\.google\.com|login\.|signin\.|auth\.|id\.|account\.)", re.I)
AUTH_TITLE = re.compile(r"\b(sign in|log in|login|sign up|create (your|an) account|join github|verify your|two-factor)\b", re.I)

def _from_user(text, task):
    t = (text or "").strip().lower()
    return bool(t) and t in (task or "").lower()

def auth_page(snap):
    """True when the page is a sign-in / sign-up / verification page."""
    url = str((snap or {}).get("url") or ""); title = str((snap or {}).get("title") or "")
    host = re.sub(r"^https?://", "", url).split("/")[0]
    if AUTH_URL.search(url) or AUTH_HOST.search(host): return True
    els = (snap or {}).get("elements") or []
    pw = any(e.get("itype") == "password" or (e.get("tag") == "input" and re.search(r"\bpassword\b", e.get("label") or "", re.I)) for e in els)
    return bool(pw or AUTH_TITLE.search(title) and any(e.get("tag") == "input" for e in els))

def check_type(text, task, el=None):
    """Return a reason string if typing `text` must be blocked, else None.
    Blocks: anything into an email/username/password/code field, and anything that looks like an email or a made-up
    credential anywhere - unless that exact text came from the user's own message."""
    if _from_user(text, task): return None
    el = el or {}
    desc = " ".join(str(el.get(k) or "") for k in ("label", "itype", "name", "autocomplete", "placeholder", "id_attr"))
    if el.get("itype") in ("password", "email", "tel") or FIELD.search(desc):
        return f"won't type into the \"{(el.get('label') or el.get('itype') or 'credential')[:40]}\" field: I never enter emails, usernames, passwords or codes you didn't give me"
    if EMAIL.search(text or ""): return "won't type an email address you didn't give me"
    if FAKE.fullmatch((text or "").strip()) or re.fullmatch(r"(test|demo|fake|dummy)\w*", (text or "").strip(), re.I):
        return "won't type a made-up username/password"
    return None

def sign_in_message(snap):
    host = re.sub(r"^https?://(www\.)?", "", str((snap or {}).get("url") or "")).split("/")[0] or "this site"
    return (f"stopped: {host} is asking you to sign in. I don't type emails, usernames or passwords for you - please sign in "
            f"to {host} in Chrome yourself, then ask me again. (If you're already signed in, tell me and I'll carry on.)")
