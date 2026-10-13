"""Kill switch (global hotkeys) and confirmation prompts."""
import threading, time

class KillSwitch:
    def __init__(self, keys=("esc", "f12")):
        self.event = threading.Event(); self.keys = {k.lower() for k in keys}; self._l = None; self._run = False

    def start(self):
        import sys
        if sys.platform == "darwin":
            return self._start_mac()
        try:
            from pynput import keyboard
        except Exception as e:
            print(f"[safety] pynput unavailable ({e}); kill hotkey disabled, FAILSAFE still active"); return
        def on_press(key):
            name = getattr(key, "name", None) or getattr(key, "char", None)
            if name and name.lower() in self.keys:
                print(f"\n[safety] {name} pressed - stopping agent"); self.event.set()
        self._l = keyboard.Listener(on_press=on_press); self._l.daemon = True; self._l.start()

    def _start_mac(self):
        """pynput's listener crashes on recent macOS (it calls HIToolbox/TSM off the main
        thread -> SIGTRAP). Instead poll CGEventSourceKeyState, which is thread-safe."""
        codes = {"esc": 53, "escape": 53, "f12": 111}
        keys = [codes[k] for k in self.keys if k in codes]
        try:
            import ctypes, ctypes.util
            cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
            cg.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]
            cg.CGEventSourceKeyState.restype = ctypes.c_bool
        except Exception as e:
            print(f"[safety] kill hotkey unavailable ({e}); use STOP button / mouse-corner FAILSAFE"); return
        self._run = True
        def poll():
            while self._run and not self.event.is_set():
                if any(cg.CGEventSourceKeyState(1, k) for k in keys):  # 1 = HID system state
                    print("\n[safety] kill key pressed - stopping agent"); self.event.set()
                time.sleep(0.05)
        threading.Thread(target=poll, daemon=True).start()

    def stop(self):
        self._run = False
        if self._l: self._l.stop()

    @property
    def killed(self): return self.event.is_set()

def console_confirm(msg):
    return input(f"\n[CONFIRM] {msg}\nAllow? [y/N]: ").strip().lower() in ("y", "yes")


# ---- v1.3.0: vision safety blocklist -------------------------------------------------
import re as _re
_SYS = [  # (pattern matched against what the action opens/types, words that must be in the task to allow it)
    (r"\bservices\.msc\b|\bservices\b", r"\bservices?\b"),
    (r"\bregedit\b|registry", r"\bregedit|registry\b"),
    (r"\bcmd(\.exe)?\b|command prompt", r"\bcmd\b|command prompt|terminal"),
    (r"\bpowershell\b|\bpwsh\b", r"powershell|terminal"),
    (r"\btaskmgr\b|task manager", r"task manager|taskmgr"),
    (r"\bmsconfig\b|\bgpedit\b|control panel|\bms-settings\b|^settings$|system settings|system preferences|\bterminal\b",
     r"settings|preferences|control panel|msconfig|gpedit|terminal"),
    (r"^run$|run dialog", r"\brun dialog|\bwin\s*\+\s*r\b|\brun box\b"),
    (r"\b(microsoft )?(word|excel|winword)\b", r"(?!x)x"),  # never vision-drive Word/Excel: docmaker writes files
]

def vision_block(act, task):
    """Return a reason string if this vision action must not run for this task, else None."""
    t = (task or "").lower()
    a = act.get("action")
    if a == "hotkey":
        keys = act.get("keys"); keys = keys if isinstance(keys, list) else str(keys or "").split("+")
        ks = {str(k).strip().lower() for k in keys}
        if ks & {"win", "winleft", "super", "cmd", "command"} and "r" in ks and not _re.search(r"\bwin\s*\+\s*r\b|\brun dialog|\brun box\b", t):
            return "Win+R (Run dialog) is not allowed unless the task asks for it"
        if {"ctrl", "shift", "esc"} <= ks and "task manager" not in t:
            return "Task Manager is not allowed unless the task asks for it"
        return None
    if a in ("open_app", "type"):
        target = str(act.get("app") if a == "open_app" else act.get("text") or "").strip().lower()
        if not target: return None
        for pat, allow in _SYS:
            if _re.search(pat, target) and not _re.search(allow, t):
                if a == "type" and pat.startswith(r"\b(microsoft"):  # typing the word "excel" into a search box is fine
                    continue
                if a == "type" and pat.startswith(r"\bservices.msc") and "services.msc" not in target:
                    continue
                return f"opening '{target}' is not allowed for this task" + (" (documents/spreadsheets are written directly, never by driving Word/Excel)" if "word" in pat else "")
    return None
