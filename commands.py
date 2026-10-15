"""Universal app controls (1.4.4): common verbs for ANY app, executed without a model call.
 - media: play / pause / resume / next / previous / stop / volume up|down / mute
     Windows: System Media Transport Controls (the session whose source app matches the target), verified by its
     playback status; fallback: virtual media keys. macOS: AppleScript for Spotify / Music, else media keys.
 - window: focus / minimize / maximize / restore / close (close asks first)
 - app actions: new / save / find / undo / redo / new tab / close tab / next tab / previous tab / select all / refresh (standard shortcuts)
"""
import json, os, re, subprocess, sys, time

IS_WIN, IS_MAC = sys.platform.startswith("win"), sys.platform == "darwin"

MEDIA = [  # (verb, regex)
    ("pause", r"\b(pause|stop playing|hold)\b"),
    ("play", r"\b(resume|unpause|un-pause|continue playing|keep playing|play (?:it |the music |the song |again|music)?\s*(?:again|back)?$|start (?:the )?(?:music|song|playback))\b"),
    ("next", r"\b(next|skip)(?:\s+(?:song|track|one|video|episode|it|this))?\b"),
    ("previous", r"\b(previous|prev|last|go back to the (?:last|previous)|back)\s+(?:song|track|one|video|episode)\b|\bplay (?:the )?previous\b|\brewind\b"),
    ("stop", r"\bstop\b(?!\s+playing)"),
    ("volume_up", r"\b(volume up|turn (?:it |the volume |the music )?up|louder|increase (?:the )?volume|raise (?:the )?volume)\b"),
    ("volume_down", r"\b(volume down|turn (?:it |the volume |the music )?down|quieter|softer|lower (?:the )?volume|decrease (?:the )?volume)\b"),
    ("mute", r"\b(mute|unmute|silence)\b"),
]
WINDOW = [("minimize", r"\bminimi[sz]e\b|\bhide\b"), ("maximize", r"\bmaximi[sz]e\b|\bfull ?screen\b"), ("restore", r"\brestore\b"),
          ("close", r"\b(close|quit|exit)\b(?!\s+(?:the\s+)?tab\b)"), ("focus", r"\b(focus|switch to|bring up|go to|show)\b")]
ACTIONS = [("new_tab", r"\bnew tab\b", "t"), ("close_tab", r"\bclose (?:the |this )?tab\b", "w"), ("next_tab", r"\bnext tab\b", "tab"),
           ("previous_tab", r"\bprevious tab\b", "shift+tab"), ("save", r"\bsave\b(?! as)", "s"), ("new", r"\bnew (?:document|file|window|note|doc)\b|\bnew\b$", "n"),
           ("find", r"^(?:open )?find(?: bar| box| dialog)?(?: in .+)?$|\b(?:find|search) (?:in|inside|on) (?:the|this) (?:document|page|file|note)\b", "f"), ("undo", r"\bundo\b", "z"), ("redo", r"\bredo\b", "y"),
           ("select_all", r"\bselect all\b", "a"), ("refresh", r"\brefresh|reload\b", "r")]
MEDIA_CONTEXT = re.compile(r"\b(music|song|track|video|podcast|episode|playback|spotify|vlc|music app|apple music|itunes|media|audio|playing|player|it|this)\b", re.I)

def parse(task, app=""):
    """'can you pause the music on spotify' -> {'kind':'media','verb':'pause'}. None when the task is more than a simple command."""
    t = (task or "").lower().strip(" .!?")
    t = re.sub(r"^(?:(?:hey|ok|okay|please|so|can you|could you|would you|will you|pls|liscia)\s+)+", "", t)
    if len(t.split()) > 12: return None
    if re.search(r"\b(and then|then|after that)\b.*\b(play|open|search|type|find)\b", t): return None
    if re.match(r"^(open|launch|start|run|go to|use)\b.*\b(and|then)\b", t): return None  # multi-step task, not a single command
    for verb, rx, _k in ACTIONS:  # keyboard-shortcut actions first ("close tab" must not become "close")
        if re.search(rx, t): return {"kind": "action", "verb": verb}
    for verb, rx in MEDIA:
        if re.search(rx, t):
            if verb == "play" and re.search(r"\bplay\s+(?!it\b|again\b|back\b|music\b|the music\b|the song\b)\S", t) and "resume" not in t:
                return None  # "play <something>" is a search/play request, not resume
            if verb in ("stop", "next", "previous") and not (MEDIA_CONTEXT.search(t) or app):
                continue
            return {"kind": "media", "verb": verb}
    for verb, rx in WINDOW:
        if re.search(rx, t) and (app or re.search(r"\bwindow\b", t)):
            if verb == "focus" and not re.fullmatch(r"(?:focus|switch to|bring up|go to|show)\s+(?:the\s+)?[\w .'+-]{1,40}?(?:\s+(?:app|window))?", t):
                continue
            return {"kind": "window", "verb": verb}
    return None

# ---------------- Windows SMTC ----------------
SMTC_PS = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "smtc.ps1")

def smtc(action="list", match="", run=None):
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout)
    out = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", SMTC_PS, "-Action", action, "-Match", match or ""])
    try: return json.loads((out or "").strip().splitlines()[-1])
    except Exception: return {"ok": False, "error": "no reply from media controls", "sessions": []}

def session_key(app):
    """Which SMTC source-app id belongs to the app: 'Spotify' -> 'spotify', 'VLC media player' -> 'vlc', 'Google Chrome' -> 'chrome'."""
    a = re.sub(r"^(google|microsoft|mozilla|apple)\s+", "", str(app or "").lower()).strip()
    special = {"music": "music", "apple music": "music", "itunes": "music", "media player": "zunemusic", "windows media player": "zunemusic",
               "groove": "zunemusic", "edge": "msedge", "firefox": "firefox", "brave": "brave", "vlc": "vlc", "vlc media player": "vlc"}
    if a in special: return special[a]
    return (a.split() or [""])[0]

VK = {"play": 0xB3, "pause": 0xB3, "toggle": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}

def media_key(verb, presses=1):
    if IS_WIN:
        import ctypes
        for _ in range(presses):
            ctypes.windll.user32.keybd_event(VK[verb], 0, 0, 0); ctypes.windll.user32.keybd_event(VK[verb], 0, 2, 0); time.sleep(0.05)
        return True
    try:
        import pyautogui
        key = {"play": "playpause", "pause": "playpause", "toggle": "playpause", "next": "nexttrack", "previous": "prevtrack", "stop": "stop",
               "volume_up": "volumeup", "volume_down": "volumedown", "mute": "volumemute"}[verb]
        for _ in range(presses): pyautogui.press(key)
        return True
    except Exception:
        return False

MAC_SCRIPTABLE = {"spotify": "Spotify", "music": "Music", "itunes": "Music", "apple music": "Music"}

def mac_media(app, verb, run=None):
    name = MAC_SCRIPTABLE.get(str(app or "").lower())
    if not name: return None
    cmd = {"pause": "pause", "play": "play", "next": "next track", "previous": "previous track", "stop": "pause",
           "volume_up": "set sound volume to (sound volume + 15)", "volume_down": "set sound volume to (sound volume - 15)",
           "mute": "set sound volume to 0"}[verb]
    run = run or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout)
    run(["osascript", "-e", f'tell application "{name}" to {cmd}'])
    state = (run(["osascript", "-e", f'tell application "{name}" to player state as string']) or "").strip()
    return state

def run_media(verb, app="", run=None, sleep=time.sleep, mac_run=None):
    """Returns a result string (verified when possible)."""
    label = app or "the current player"
    if IS_MAC and not run:
        state = mac_media(app, verb, run=mac_run)
        if state is not None:
            return f"{verb.replace('_', ' ')}: {label} is now {state}."
        media_key(verb); return f"Sent the {verb.replace('_', ' ')} media key."
    if verb in ("volume_up", "volume_down", "mute"):  # SMTC has no volume: system volume keys
        media_key(verb, presses=5 if verb != "mute" else 1)
        return {"volume_up": "Turned the volume up.", "volume_down": "Turned the volume down.", "mute": "Toggled mute."}[verb]
    key = session_key(app) if app else ""
    res = smtc(verb, key, run=run)
    if res.get("ok") and res.get("after"):
        a = res["after"]; status = a.get("status", "")
        want = {"pause": "Paused", "play": "Playing", "stop": "Stopped"}.get(verb)
        song = " - ".join(x for x in (a.get("artist"), a.get("title")) if x)
        if want and status != want and verb != "stop":
            # some players report late: re-check once
            sleep(0.8); again = smtc("list", run=run)
            for s in again.get("sessions", []):
                if key and key in str(s.get("app", "")).lower(): status = s.get("status", status)
        if want and status != want and not (verb == "stop" and status in ("Paused", "Stopped")):
            return f"stopped: sent {verb} to {label}, but it still reports {status or 'unknown'}."
        return f"{verb.replace('_', ' ').capitalize()}: {label} is {status}" + (f" ({song})." if song else ".")
    # no matching session: fall back to the media key (affects the system's current player)
    sessions = res.get("sessions") or []
    if app and not any(key in str(s.get("app", "")).lower() for s in sessions):
        return f"stopped: {label} has no active media session (is it playing anything?)."
    media_key(verb)
    return f"Sent the {verb} media key."

# ---------------- window + app actions on the bound window ----------------
def run_window(verb, binding, confirm=None):
    if not binding or not binding.hwnd: return "stopped: the app window isn't available."
    if IS_WIN:
        import ctypes
        u = ctypes.windll.user32
        if verb == "minimize": u.ShowWindow(binding.hwnd, 6); return f"Minimized {binding.app}."
        if verb == "maximize": binding.ensure(); u.ShowWindow(binding.hwnd, 3); return f"Maximized {binding.app}."
        if verb == "restore": u.ShowWindow(binding.hwnd, 9); binding.ensure(); return f"Restored {binding.app}."
        if verb == "focus": return f"{binding.app} is in front." if binding.ensure() else f"stopped: couldn't bring {binding.app} to the front."
        if verb == "close":
            if confirm and not confirm(f"Close {binding.app}? (it will ask to save if anything is unsaved)"): return "Not closed."
            u.PostMessageW(binding.hwnd, 0x0010, 0, 0); return f"Asked {binding.app} to close (it will prompt if anything is unsaved)."
    if IS_MAC:
        name = binding.app
        if verb == "focus": return f"{name} is in front." if binding.ensure() else f"stopped: couldn't bring {name} to the front."
        if verb == "close":
            if confirm and not confirm(f"Quit {name}?"): return "Not closed."
            subprocess.run(["osascript", "-e", f'tell application "{name}" to quit'], capture_output=True, timeout=10); return f"Asked {name} to quit."
        if verb == "minimize":
            subprocess.run(["osascript", "-e", f'tell application "System Events" to set visible of process "{name}" to false'], capture_output=True, timeout=10)
            return f"Hid {name}."
    return f"stopped: '{verb}' isn't supported here."

def run_action(verb, binding, gui=None, confirm=None):
    keys = next(k for v, _, k in ACTIONS if v == verb)
    if not binding or not binding.ensure(): return f"stopped: {getattr(binding, 'app', 'the app')} isn't in front, so I didn't press anything."
    if verb == "close_tab" and confirm and not confirm(f"Close the current tab in {binding.app}?"): return "Not closed."
    mod = "command" if IS_MAC else "ctrl"
    combo = [mod] + keys.split("+") if keys not in ("tab", "shift+tab") else ([mod, "tab"] if keys == "tab" else [mod, "shift", "tab"])
    g = gui or __import__("pyautogui"); g.hotkey(*combo)
    return f"Pressed {'+'.join(combo)} in {binding.app} ({verb.replace('_', ' ')})."
