"""2.3.0: curated local (Ollama) models for Settings -> Download models: size, RAM need, role; pull with progress/cancel; delete."""
import json, threading
import requests

# name, download size (GB, Ollama default quantisation), RAM needed to run it comfortably (GB), role, short note
CATALOG = [
    ("llama3.2:1b",  1.3,  3, "text",          "tiny and fast; fine for testing, weak at planning"),
    ("qwen2.5:3b",   1.9,  4, "text",          "small, quick text/planner model"),
    ("llama3.2:3b",  2.0,  4, "text",          "small Meta model, good for chat"),
    ("phi4-mini",    2.5,  5, "text",          "small Microsoft model, good reasoning for its size"),
    ("qwen3:4b",     2.5,  6, "text",          "small, newer Qwen; strong for its size"),
    ("gemma3:4b",    3.3,  6, "text + vision", "Google model that can also read images"),
    ("qwen3-vl:4b",  3.3,  6, "vision",        "small vision model (Liscia's default for screenshots)"),
    ("mistral:7b",   4.1,  8, "text",          "solid general text model"),
    ("qwen2.5:7b",   4.7,  8, "text",          "recommended text/planner model (Liscia's default)"),
    ("llava:7b",     4.7,  8, "vision",        "older vision model, widely used"),
    ("llama3.1:8b",  4.9,  8, "text",          "Meta 8B, good all-rounder"),
    ("qwen3:8b",     5.2, 10, "text",          "newer Qwen 8B, better reasoning, slower"),
    ("qwen2.5vl:7b", 6.0, 10, "vision",        "strong vision model for screenshots"),
    ("qwen3-vl:8b",  6.1, 10, "vision",        "newer, sharper vision model"),
    ("gemma3:12b",   8.1, 16, "text + vision", "bigger Google model; needs lots of RAM"),
    ("qwen2.5:14b",  9.0, 16, "text",          "bigger, smarter planner; needs lots of RAM"),
]

def system_ram_gb():
    try:
        import psutil; return round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        return 0.0

def fit(ram_need, total=None):
    """'ok' | 'tight' (runs, but close other apps) | 'too big' for this computer's RAM."""
    total = system_ram_gb() if total is None else total
    if not total: return "ok"
    if ram_need > total * 0.8: return "too big"
    if ram_need > total * 0.55: return "tight"
    return "ok"

def label(entry, total=None):
    name, size, ram, role, note = entry
    f = fit(ram, total)
    tag = {"ok": "", "tight": "  [tight: close other apps]", "too big": "  [TOO BIG for this computer]"}[f]
    return f"{name:<14} {size:>4.1f} GB download  needs ~{ram} GB RAM  {role:<13}{tag}"

def name_from_label(text):
    return (text or "").strip().split()[0] if (text or "").strip() else ""

def installed(host):
    """[(name, size_gb)] of local models, or None if Ollama isn't running."""
    try:
        tags = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5).json().get("models", [])
    except Exception:
        return None
    return sorted((m.get("name") or m.get("model"), round((m.get("size") or 0) / 1e9, 1)) for m in tags)

def delete(host, name, req=None):
    req = req or requests.request
    r = req("DELETE", f"{host.rstrip('/')}/api/delete", json={"model": name}, timeout=30)
    if getattr(r, "status_code", 200) >= 400: raise RuntimeError(getattr(r, "text", "") or f"HTTP {r.status_code}")
    return True

class Cancelled(Exception): pass

def pull(host, name, on_progress=None, cancel=None, post=None):
    """Stream POST /api/pull. on_progress(status, done_bytes, total_bytes). cancel: threading.Event -> raises Cancelled."""
    post = post or requests.post
    cancel = cancel or threading.Event()
    with post(f"{host.rstrip('/')}/api/pull", json={"model": name, "stream": True}, stream=True, timeout=(10, 600)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if cancel.is_set(): r.close(); raise Cancelled(name)
            if not line: continue
            m = json.loads(line)
            if m.get("error"): raise RuntimeError(m["error"])
            if on_progress: on_progress(m.get("status", ""), m.get("completed") or 0, m.get("total") or 0)
            if m.get("status") == "success": return True
    if cancel.is_set(): raise Cancelled(name)
    return True

HOW_TO = """\
1. Pick a model from the list below, or type any Ollama model name in the custom box. Each line shows the download size, how much memory (RAM) it needs, and whether it reads text, images (vision), or both.

2. Click DOWNLOAD. The bar shows progress. CANCEL stops it; Ollama keeps the finished parts, so downloading again resumes.

3. When it says ready, open the MODELS tab and choose it as the TEXT / PLANNER model (text models) or the VISION model (vision models read screenshots). Click SAVE. New messages use it right away.

RAM guidance: a model needs about its RAM amount free while it runs. Models marked TOO BIG won't run well on this computer; "tight" ones work if you close other big apps. Bigger is smarter but slower. A 7-8B text model plus a 4B vision model is a good pair on 16 GB or more.

Manual way: open Terminal (Mac) or PowerShell (Windows) and run   ollama pull <name>   for example   ollama pull qwen2.5:7b . To remove one, run   ollama rm <name>   or use DELETE below."""
