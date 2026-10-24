"""Multiple chats (2.0.0). Each chat is one JSON file in <data dir>/chats/<id>.json:
  {"id", "title", "created", "updated", "messages": [{"role", "content", "t", "run"?}], "runs": [run folder names]}
Each chat keeps its own history/context; task runs are linked to the chat they came from."""
import json, os, re, secrets, threading, time

def plain_result(result):
    """Task results in plain words for the chat ('stopped: x' -> 'I stopped: x', 'done: y' -> 'Done: y')."""
    r = str(result or "").strip()
    if r.lower().startswith("stopped:"): return "I stopped: " + r[8:].strip()
    if r.lower().startswith("done:"): return "Done: " + r[5:].strip()
    return r or "Done."

def default_dir():
    import paths; return os.path.join(paths.data_dir(), "chats")

def auto_title(text, n=40):
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^(?:(?:hey|hi|ok|okay|please|pls|so|can you|could you|would you)[\s,]+)+", "", t, flags=re.I)
    t = t[:1].upper() + t[1:] if t else "New chat"
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"

class ChatStore:
    def __init__(self, folder=None, clock=time.time):
        self.dir = folder or default_dir(); self.clock = clock; self.lock = threading.RLock()
        os.makedirs(self.dir, exist_ok=True)
        self.current_id = None; self.listeners = []
        st = self._state()
        if st.get("current") and os.path.exists(self._path(st["current"])): self.current_id = st["current"]

    def _path(self, cid):
        if not re.fullmatch(r"[a-z0-9-]{6,40}", cid or ""): raise ValueError("bad chat id")
        return os.path.join(self.dir, cid + ".json")
    def _state(self):
        try: return json.load(open(os.path.join(self.dir, "_state.json"), encoding="utf-8"))
        except Exception: return {}
    def _notify(self, what, cid=None):
        for f in list(self.listeners):
            try: f(what, cid)
            except Exception: pass
    def _save_state(self):
        self._notify("current", self.current_id)
        self._atomic(os.path.join(self.dir, "_state.json"), {"current": self.current_id})
    def _atomic(self, path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def new(self, title=None, select=True):
        with self.lock:
            now = self.clock()
            cid = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)).lower() + "-" + secrets.token_hex(3)
            c = {"id": cid, "title": title or "New chat", "auto_title": title is None, "created": now, "updated": now, "messages": [], "runs": []}
            self.save(c)
            if select: self.current_id = cid; self._save_state()
            return c

    def get(self, cid):
        with self.lock:
            try: return json.load(open(self._path(cid), encoding="utf-8"))
            except (OSError, ValueError): return None

    def save(self, c):
        with self.lock: self._atomic(self._path(c["id"]), c)

    def list(self):
        """Newest first: [{'id','title','updated','count'}]."""
        out = []
        for fn in os.listdir(self.dir):
            if fn.endswith(".json") and not fn.startswith("_"):
                c = self.get(fn[:-5])
                if c: out.append({"id": c["id"], "title": c["title"], "updated": c["updated"], "count": len(c["messages"])})
        return sorted(out, key=lambda c: c["updated"], reverse=True)

    def current(self):
        with self.lock:
            c = self.get(self.current_id) if self.current_id else None
            if c is None:
                lst = self.list()
                c = self.get(lst[0]["id"]) if lst else self.new()
                self.current_id = c["id"]; self._save_state()
            return c

    def select(self, cid):
        with self.lock:
            c = self.get(cid)
            if c is None: raise KeyError(cid)
            self.current_id = cid; self._save_state(); return c

    def rename(self, cid, title):
        with self.lock:
            c = self.get(cid)
            if c is None: raise KeyError(cid)
            c["title"] = (title or "").strip()[:80] or c["title"]; c["auto_title"] = False; self.save(c); self._notify("list", cid); return c

    def delete(self, cid):
        with self.lock:
            os.remove(self._path(cid))
            if self.current_id == cid:
                self.current_id = None; self._save_state()
            self._notify("list", cid); return True

    def add(self, cid, role, content, run=None, meta=None):
        with self.lock:
            c = self.get(cid)
            if c is None: raise KeyError(cid)
            m = {"role": role, "content": content, "t": self.clock()}
            if run: m["run"] = run; c.setdefault("runs", []).append(run)
            if meta: m["task"] = meta
            c["messages"].append(m); c["updated"] = m["t"]
            if role == "user" and c.get("auto_title", True) and sum(1 for x in c["messages"] if x["role"] == "user") == 1:
                c["title"] = auto_title(content)
            self.save(c); self._notify("message", cid); return c

    def history(self, cid, n=20):
        """Model context for this chat only (role/content pairs)."""
        c = self.get(cid) or {"messages": []}
        return [{"role": m["role"], "content": m["content"]} for m in c["messages"] if m["role"] in ("user", "assistant")][-n:]

    def context(self, cid, n=6):
        """What a follow-up needs: the last few turns and the last task (its query/site/result)."""
        c = self.get(cid) or {"messages": []}
        metas = [m["task"] for m in reversed(c["messages"]) if m.get("task")]
        last = metas[0] if metas else None
        if last and not last.get("query"):  # 2.1.1: the most recent task that actually named something
            q = next((x for x in metas if x.get("query")), None)
            if q: last = dict(last, query=q["query"], site=last.get("site") or q.get("site", ""))
        played = next((x.get("played") for x in metas if x.get("played")), None)
        chain = []  # everything played for the current request (consecutive media tasks about the same thing)
        lq = set(re.findall(r"\w+", ((last or {}).get("query") or "").lower()))
        for x in metas:
            if x.get("intent") != "media_play" or (lq and not (lq & set(re.findall(r"\w+", (x.get("query") or "").lower())))): break
            if x.get("played", {}).get("url"): chain.append(x["played"]["url"])
        return {"turns": self.history(cid, n), "last": last, "played": played, "played_chain": chain,
                "media_before": any(x.get("intent") == "media_play" for x in metas)}

    def migrate(self, old_messages):
        """Move a pre-2.0 single conversation into the first chat (once)."""
        with self.lock:
            if self.list() or not old_messages: return None
            c = self.new(select=True)
            for m in old_messages:
                if m.get("role") in ("user", "assistant") and m.get("content"): self.add(c["id"], m["role"], m["content"])
            return self.get(c["id"])

def migrate_legacy(store, data_dir):
    """Pre-2.0 builds kept the conversation only in memory (and the panel's in bridge memory); a saved
    history.json from older dev builds is migrated if present. Always guarantees at least one chat."""
    p = os.path.join(data_dir, "history.json")
    if os.path.exists(p):
        try:
            store.migrate(json.load(open(p, encoding="utf-8")))
            os.replace(p, p + ".migrated")
        except Exception: pass
    return store.current()

STORE = None
def store():
    """The app-wide chat store (shared by the chat window and the Chrome panel bridge)."""
    global STORE
    if STORE is None:
        import paths
        STORE = ChatStore(); migrate_legacy(STORE, paths.data_dir())
    return STORE
