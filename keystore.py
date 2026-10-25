"""API keys live ONLY in the OS keychain (macOS Keychain / Windows Credential Manager) via `keyring`.
Never in config.yaml, logs, run folders or the repo."""
SERVICE = "Liscia Agent"
PROVIDERS = ("openai", "anthropic", "gemini")
_backend = None  # tests inject a fake {get_password,set_password,delete_password}

def _kr():
    if _backend is not None: return _backend
    import keyring; return keyring

_cache = {}  # 2.3.6: read each key from the OS keychain ONCE per launch (every read can show a macOS Keychain prompt)

def get(provider):
    if provider in _cache: return _cache[provider]
    try: v = _kr().get_password(SERVICE, f"{provider}_api_key") or ""
    except Exception: return ""  # not cached: a denied/failed read can be retried later
    _cache[provider] = v; return v

def set(provider, key):
    key = (key or "").strip()
    if not key: return delete(provider)
    _kr().set_password(SERVICE, f"{provider}_api_key", key); _cache[provider] = key; return True

def delete(provider):
    try: _kr().delete_password(SERVICE, f"{provider}_api_key")
    except Exception: pass
    _cache[provider] = ""
    return True

def clear_cache(): _cache.clear()

def has(provider): return bool(get(provider))

def mask(key):
    key = key or ""
    return "" if not key else (key[:3] + "…" + key[-4:] if len(key) > 10 else "••••")
