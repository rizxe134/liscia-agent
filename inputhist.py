"""2.3.8: terminal-style input history for the chat box (Up/Down like bash, Ctrl+R search, Tab completes slash commands).
Per-chat + global lists, persisted to input_history.json next to the chats folder, capped at 500 each."""
import json, os, threading

CAP = 500
SLASH = ["/new", "/newchat", "/clear", "/settings", "/models", "/model", "/token", "/help", "/commands", "/do", "/chat"]

class History:
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        try: d = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError): d = {}
        self.glob = [str(x) for x in d.get("global", [])][-CAP:]
        self.chats = {k: [str(x) for x in v][-CAP:] for k, v in (d.get("chats") or {}).items()}
        self.reset()

    def add(self, text, chat_id=None):
        t = (text or "").rstrip("\n")
        if not t.strip(): return
        for lst in [self.glob] + ([self.chats.setdefault(chat_id, [])] if chat_id else []):
            if not lst or lst[-1] != t: lst.append(t)
            del lst[:-CAP]
        self.save(); self.reset()

    def save(self):
        with self.lock:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f: json.dump({"global": self.glob, "chats": self.chats}, f, ensure_ascii=False)
                os.replace(tmp, self.path)
            except OSError: pass

    def items(self, chat_id=None):
        """Oldest -> newest: this chat's messages, preceded by older global ones not already in it."""
        mine = self.chats.get(chat_id, []) if chat_id else []
        seen = set(mine)
        rest = []
        for t in self.glob:
            if t not in seen: rest.append(t); seen.add(t)
        return rest + mine

    # ---- navigation (bash-like: the unsent draft is kept at the end) ----
    def reset(self): self.pos, self.draft, self.search_from = None, "", None

    def up(self, current, chat_id=None):
        it = self.items(chat_id)
        if not it: return None
        if self.pos is None: self.draft, self.pos = current, len(it)
        if self.pos == 0: return it[0]
        self.pos -= 1; return it[self.pos]

    def down(self, current, chat_id=None):
        it = self.items(chat_id)
        if self.pos is None: return None
        self.pos += 1
        if self.pos >= len(it): d = self.draft; self.reset(); return d
        return it[self.pos]

    def search(self, query, chat_id=None, older=False):
        """Ctrl+R: newest item containing query (again = older match). Returns text or None."""
        it = self.items(chat_id); q = (query or "").lower()
        start = (self.search_from if older and self.search_from is not None else len(it)) - 1
        for i in range(start, -1, -1):
            if q in it[i].lower(): self.search_from = i; return it[i]
        return None

def complete(text):
    """Tab: complete a slash command ('/to' -> '/token '); returns (new_text, candidates)."""
    if not text.startswith("/") or " " in text: return text, []
    c = [s for s in SLASH if s.startswith(text.lower())]
    if len(c) == 1: return c[0] + " ", c
    if c:
        pre = os.path.commonprefix(c); return (pre if len(pre) > len(text) else text), c
    return text, []
