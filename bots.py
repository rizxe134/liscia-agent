"""3.0.0: every chat is a bot. The bot lives inside its chat file (chats/<id>.json) under "bot", so a bot's history,
persona, model choice, tools and memory stay together and old chats migrate by just gaining a "bot" block.
Deleting moves the file to chats/_trash/ (kept 30 days, restorable); the first 3.0 launch backs up the chats folder."""
import json, os, shutil, time

COLORS = {"green": "#3dff8f", "cyan": "#3de8ff", "amber": "#ffc83d", "pink": "#ff6ad5", "violet": "#a98bff", "red": "#ff5f5f", "white": "#e8e8e8"}
STYLES = ("classic", "antenna", "visor")
TEMPLATES = {
    "General": {"color": "green", "style": "classic", "description": "Everyday help + computer control", "instructions": "You are a helpful general assistant that can also use this computer."},
    "Researcher": {"color": "cyan", "style": "visor", "description": "Searches the web, cites sources", "instructions": "You research on the web, compare sources, and answer with short cited summaries."},
    "Music": {"color": "pink", "style": "antenna", "description": "Finds and plays music & videos", "instructions": "You play and find music and videos (YouTube, Spotify) and keep replies short."},
    "Calendar": {"color": "amber", "style": "classic", "description": "Your calendar & email, asks first", "instructions": "You manage my calendar and email. Always confirm before creating, changing or sending anything.",
                 "connections": ["google"]},
}
TRASH_DAYS = 30

def default_bot(name="General", template=None):
    t = dict(TEMPLATES.get(template or "General", TEMPLATES["General"]))
    return {"name": name, "description": t.get("description", "") if template else "", "color": t.get("color", "green"), "style": t.get("style", "classic"), "instructions": t.get("instructions", ""),
            "provider": "", "model": "", "connections": list(t.get("connections", ["*"])), "mcp": list(t.get("mcp", ["*"])), "memory": []}

def ensure(chat):
    """Migrate in place: a pre-3.0 chat becomes a bot named after its title (nothing else changes). Returns True if changed."""
    if isinstance(chat.get("bot"), dict):
        b = chat["bot"]; d = default_bot(b.get("name") or chat.get("title") or "Bot"); changed = False
        for k, v in d.items():
            if k not in b: b[k] = v; changed = True
        return changed
    chat["bot"] = default_bot(chat.get("title") or "General"); chat["bot"]["instructions"] = ""
    return True

def allowed(bot, key):
    """None = every connected app / enabled MCP server ("*"), else the bot's list."""
    v = (bot or {}).get(key)
    if v is None or "*" in v: return None
    return list(v)

def color_hex(bot):
    c = (bot or {}).get("color") or "green"
    return COLORS.get(c, c if str(c).startswith("#") else COLORS["green"])

def persona(bot):
    """Extra system text for this bot: name, instructions, saved notes."""
    if not bot: return ""
    out = [f"Your name is {bot.get('name') or 'Liscia'}." + (f" Your role: {bot['description']}." if bot.get("description") else "")]
    if bot.get("instructions"): out.append("Instructions from the user for you: " + bot["instructions"].strip()[:2000])
    mem = [m for m in bot.get("memory") or [] if str(m).strip()][-30:]
    if mem: out.append("Things you saved to remember:\n- " + "\n- ".join(str(m)[:300] for m in mem))
    return "\n".join(out)

def bot_cfg(cfg, bot):
    """The global config with this bot's provider/model override (empty = global default)."""
    if not bot or not (bot.get("provider") or bot.get("model")): return cfg
    import copy
    c = copy.deepcopy(cfg); p = bot.get("provider") or c.get("provider", {}).get("name", "ollama")
    c.setdefault("provider", {})["name"] = p
    if bot.get("model"):
        if p == "ollama": c.setdefault("ollama", {})["text_model"] = bot["model"]
        else: c["provider"].setdefault(p, {})["text_model"] = bot["model"]
    return c

# ---------------- trash / backup ----------------
def trash_dir(chats_dir): return os.path.join(chats_dir, "_trash")

def to_trash(chats_dir, cid, clock=time.time):
    src = os.path.join(chats_dir, cid + ".json")
    os.makedirs(trash_dir(chats_dir), exist_ok=True)
    dst = os.path.join(trash_dir(chats_dir), f"{cid}.json")
    try:
        c = json.load(open(src, encoding="utf-8")); c["deleted_at"] = clock()
        with open(dst, "w", encoding="utf-8") as f: json.dump(c, f, ensure_ascii=False, indent=1)
        os.remove(src)
    except ValueError: shutil.move(src, dst)
    return dst

def list_trash(chats_dir, clock=time.time):
    out, d = [], trash_dir(chats_dir)
    if not os.path.isdir(d): return out
    for fn in os.listdir(d):
        if not fn.endswith(".json"): continue
        p = os.path.join(d, fn)
        try: c = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError): continue
        age = clock() - float(c.get("deleted_at") or os.path.getmtime(p))
        if age > TRASH_DAYS * 86400: os.remove(p); continue
        out.append({"id": fn[:-5], "name": (c.get("bot") or {}).get("name") or c.get("title"), "deleted_at": c.get("deleted_at"),
                    "days_left": max(0, int(TRASH_DAYS - age / 86400))})
    return sorted(out, key=lambda x: -(x["deleted_at"] or 0))

def restore(chats_dir, cid):
    src = os.path.join(trash_dir(chats_dir), cid + ".json"); dst = os.path.join(chats_dir, cid + ".json")
    c = json.load(open(src, encoding="utf-8")); c.pop("deleted_at", None)
    with open(dst, "w", encoding="utf-8") as f: json.dump(c, f, ensure_ascii=False, indent=1)
    os.remove(src); return c

def backup_once(chats_dir, tag="pre-3.0.0"):
    """Copy the whole chats folder to <data>/backups/chats-<tag>-<time> once (marker file)."""
    marker = os.path.join(chats_dir, f"_backup_{tag}.done")
    if os.path.exists(marker): return None
    dst = os.path.join(os.path.dirname(chats_dir), "backups", f"chats-{tag}-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copytree(chats_dir, dst, ignore=shutil.ignore_patterns("_trash"))
    open(marker, "w").write(dst); return dst

def mentions(text, items, exclude=None):
    """'@Music what should I play?' -> [(cid, bot)] for bots named in @mentions (longest names first, case-insensitive)."""
    import re
    out, low = [], " " + (text or "").lower()
    for c in sorted(items, key=lambda c: -len(((c.get("bot") or {}).get("name") or ""))):
        n = ((c.get("bot") or {}).get("name") or "").strip().lower()
        if not n or c["id"] == exclude: continue
        if re.search(r"(?<![\w@.])@" + re.escape(n) + r"(?![\w]|\.\w)", low):
            if all(c["id"] != x[0] for x in out): out.append((c["id"], c.get("bot") or {}))
    return out

def strip_mentions(text, names):
    import re
    for n in names: text = re.sub(r"@" + re.escape(n), n, text, flags=re.I)
    return text
