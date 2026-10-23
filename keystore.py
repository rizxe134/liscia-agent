"""API keys live ONLY in the OS keychain (macOS Keychain / Windows Credential Manager) via `keyring`.
Never in config.yaml, logs, run folders or the repo."""
SERVICE = "Liscia Agent"
PROVIDERS = ("openai", "anthropic", "gemini")
_backend = None  # tests inject a fake {get_password,set_password,delete_password}

def _kr():
    if _backend is not None: return _backend
    import keyring; return keyring

def get(provider):
    try: return _kr().get_password(SERVICE, f"{provider}_api_key") or ""
    except Exception: return ""

def set(provider, key):
    key = (key or "").strip()
    if not key: return delete(provider)
    _kr().set_password(SERVICE, f"{provider}_api_key", key); return True

def delete(provider):
    try: _kr().delete_password(SERVICE, f"{provider}_api_key")
    except Exception: pass
    return True

def has(provider): return bool(get(provider))

def mask(key):
    key = key or ""
    return "" if not key else (key[:3] + "…" + key[-4:] if len(key) > 10 else "••••")
