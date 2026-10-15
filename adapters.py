"""App adapters (1.4.2) for Electron apps whose UI Automation trees are thin or slow (Spotify, Discord, VS Code, Slack).
An adapter can launch through the app's own URI (spotify:search:<query>) and finish the job through a few reliable,
verified steps, scoped to the bound app window. Everything else falls back to the generic element/vision loop."""
import difflib, os, re, subprocess, sys, time, urllib.parse

IS_WIN, IS_MAC = sys.platform.startswith("win"), sys.platform == "darwin"

# keyboard-first hints for thin-tree apps (shown to the model)
SEARCH_KEYS = {"spotify": "Ctrl+K (search)", "discord": "Ctrl+K (quick switcher: find a server, channel or person)",
               "visual studio code": "Ctrl+P (open file), Ctrl+Shift+P (commands)", "code": "Ctrl+P (open file), Ctrl+Shift+P (commands)",
               "slack": "Ctrl+K (jump to a channel or person)", "microsoft teams": "Ctrl+E (search)", "teams": "Ctrl+E (search)",
               "notion": "Ctrl+P (search)", "obsidian": "Ctrl+O (open note)", "steam": "Ctrl+F not available - use the Library search box"}

def hints_table():
    """Built-in app_hints.json, extended/overridden by <data dir>/app_hints.json (user-editable)."""
    import json, os, sys
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    t = {}
    paths_ = [os.path.join(base, "app_hints.json")]
    try:
        import paths; paths_.append(os.path.join(paths.data_dir(), "app_hints.json"))
    except Exception: pass
    for p in paths_:
        try:
            for k, v in json.load(open(p, encoding="utf-8")).items():
                if not k.startswith("_") and isinstance(v, dict): t.setdefault(k.lower(), {}).update(v)
        except Exception: pass
    return t

def hint(app):
    a = str(app or "").lower()
    if not a: return ""
    tbl = hints_table()
    keys = sorted((k for k in tbl if k == a or k in a or (len(a) >= 4 and a in k)), key=len, reverse=True)
    if keys and tbl[keys[0]]:
        shown = ", ".join(f"{v.replace('ctrl', 'Ctrl').replace('shift', 'Shift').replace('cmd', 'Cmd')} ({k.replace('_', ' ')})" for k, v in tbl[keys[0]].items())
        return f"Keyboard shortcuts in {app}: {shown}. Prefer keyboard shortcuts in this app."
    for k, v in SEARCH_KEYS.items():
        if k in a: return f"Keyboard shortcut in {app}: {v}. Prefer keyboard shortcuts in this app."
    return ""

def verbatim_target(task, verbs=r"play|put on|listen to|search(?: for)?|find|queue"):
    """The user's own words for the thing to play/search - never spell-corrected ('gettin money' stays 'gettin money')."""
    t = (task or "").strip()
    m = re.search(r"\b(?:" + verbs + r")\s+(?:me\s+)?(?:the\s+)?(?:song|track|album|playlist|artist|podcast)?\s*(.+?)\s*"
                  r"(?:\b(?:on|in|using|with|from)\s+(?:the\s+)?spotify(?:\s+app)?\b.*)?[.!?]*$", t, re.I)
    if not m: return ""
    q = m.group(1).strip(" \"'.,!?")
    q = re.sub(r"^(?:(?:a|an|some)\s+)?(?:song|track)\s+(?:called|named)\s+", "", q, flags=re.I)
    q = re.sub(r"\s+(?:for me|please|now)$", "", q, flags=re.I)
    return q

def open_uri(uri, run=None):
    if IS_WIN and run is None: os.startfile(uri); return
    (run or (lambda c: subprocess.run(c, timeout=15, capture_output=True)))(["open", uri] if IS_MAC else ["xdg-open", uri])

def _n(s):
    return re.sub(r"[^a-z0-9 ]+", "", str(s or "").lower().replace("'", "")).strip()

def best_row(rows, query):
    """rows: [(name, play_fn)] in on-screen order. Prefer the first row whose title matches the query; else the first row."""
    q = _n(query)
    scored = [(difflib.SequenceMatcher(None, q, _n(name)).ratio() + (0.3 if q and q in _n(name) else 0), -i, name, fn)
              for i, (name, fn) in enumerate(rows) if fn]
    if not scored: return None
    good = [s for s in scored if s[0] >= 0.75]
    pick = max(good) if good else max(scored, key=lambda s: s[1])  # nothing matches: top of the list
    return pick[2], pick[3]

IDLE_TITLES = re.compile(r"^(spotify( premium| free)?|spotify)$", re.I)

class SpotifyPlay:
    """'open spotify and play <X>': spotify:search:<X> -> wait for 'Search results' -> press Play on the best row
    (the top result card's Play button or the track row's 'Play <title>') -> verify the window title became 'Artist - Song'."""
    def __init__(self, query, rows_fn=None, title_fn=None, sleep=time.sleep, timeout=25.0, playing_fn=None, main_play_fn=None):
        self.query = query
        self.playing_fn, self.main_play_fn = playing_fn, main_play_fn
        self.launch_uri = "spotify:search:" + urllib.parse.quote(query)
        self.rows_fn, self.title_fn, self.sleep, self.timeout = rows_fn, title_fn, sleep, timeout

    def _rows_uia(self, hwnd):
        import uiautomation as auto
        w = auto.ControlFromHandle(int(hwnd))
        grid = w.DataGridControl(searchDepth=40, Name="Search results")
        if not grid.Exists(0.5): return []
        rows = []
        for row in grid.GetChildren():
            name = (row.Name or "").strip()
            if not name: continue
            btn = None
            for c, d in auto.WalkControl(row, maxDepth=6):
                if c.ControlTypeName == "ButtonControl" and (c.Name == "Play" or (c.Name or "").startswith("Play ")):
                    btn = c; break
            def press(b=btn):
                try:
                    ip = b.GetInvokePattern()
                    if ip: ip.Invoke(); return True
                except Exception: pass
                b.Click(simulateMove=False); return True
            rows.append((name, press if btn is not None else None))
        return rows

    def _playing_uia(self, hwnd):
        """Spotify shows a 'Pause' button in the player bar while something plays."""
        import uiautomation as auto
        return auto.ControlFromHandle(int(hwnd)).ButtonControl(searchDepth=40, Name="Pause").Exists(0.3)

    def _main_play_uia(self, hwnd):
        import uiautomation as auto
        b = auto.ControlFromHandle(int(hwnd)).ButtonControl(searchDepth=40, Name="Play")
        if b.Exists(0.5):
            try: b.GetInvokePattern().Invoke()
            except Exception: b.Click(simulateMove=False)
            return True
        return False

    def _verify(self, title_fn, playing_fn, name, before, polls=10):
        for _ in range(polls):
            self.sleep(0.5)
            title = (title_fn() or "").strip()
            playing = False
            try: playing = bool(playing_fn())
            except Exception: pass
            if playing and title and not IDLE_TITLES.match(title) and " - " in title:
                return title
            if playing and _n(name) and _n(name) in _n(title):
                return title
        return None

    def run(self, agent, logf=None):
        b = getattr(agent, "app_binding", None)
        if b is None: return None
        rows_fn = self.rows_fn or (lambda: self._rows_uia(b.hwnd))
        title_fn = self.title_fn or b.window_title
        start = time.time(); rows = []
        while time.time() - start < self.timeout:
            if not b.ensure(): raise RuntimeError("Spotify isn't in front")
            rows = rows_fn()
            if rows: break
            self.sleep(0.7)
        if not rows: return None
        pick = best_row(rows, self.query)
        if not pick: return None
        name, press = pick
        if not b.ensure(): raise RuntimeError("Spotify isn't in front")
        playing_fn = self.playing_fn or (lambda: self._playing_uia(b.hwnd))
        main_play = self.main_play_fn or (lambda: self._main_play_uia(b.hwnd))
        before = title_fn() or ""
        press()
        if logf: logf.write('{"spotify_play": %s}\n' % __import__("json").dumps(name))
        title = self._verify(title_fn, playing_fn, name, before)
        if not title:  # the row's Play can toggle (track already loaded but paused): use the player's main Play once
            if not b.ensure(): raise RuntimeError("Spotify isn't in front")
            try: playing = bool(playing_fn())
            except Exception: playing = False
            if not playing and main_play():
                title = self._verify(title_fn, playing_fn, name, before, polls=8)
        if title:
            return f"Playing \"{title}\" in Spotify (searched for \"{self.query}\")."
        return None

def for_app(app, task):
    a = str(app or "").lower()
    if "spotify" in a:
        q = verbatim_target(task)
        if q and q.lower() not in ("spotify", "music", "it"):
            return SpotifyPlay(q)
    return None
