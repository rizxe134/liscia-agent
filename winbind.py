"""Bind a desktop run to ONE app window (1.4.2).
After open_app we resolve the launched app's process (exe / AUMID package, incl. child processes of Electron/UWP apps),
wait for its real main window, bring it to the foreground reliably, and from then on every snapshot and action is scoped
to that window handle. Before each step the agent calls ensure(): if the foreground window isn't the target, refocus;
if that fails, the run stops. Windows: Win32 + UI Automation. macOS: NSRunningApplication + AX on that pid."""
import os, re, sys, time

IS_WIN, IS_MAC = sys.platform.startswith("win"), sys.platform == "darwin"
# helper / hidden windows that belong to the app's process but are not the app UI
HELPER_TITLES = re.compile(r"^(new tab - chromium|chrome legacy window|msctfime ui|default ime|gdi\+ window.*|hidden window|"
                           r"\.net-broadcasteventwindow.*|task host window|crashpad.*|)$", re.I)

def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())

def exe_hints(app, entry=None):
    """Names the target process may have: 'spotify' -> {'spotify'}; index target C:\\...\\Code.exe -> {'code', 'visualstudiocode'}."""
    hints = {_norm(app)}
    base = re.sub(r"^(microsoft|adobe|google|mozilla)\s+", "", str(app or ""), flags=re.I)
    hints.add(_norm(base)); hints.add(_norm(base.split()[0]) if base.split() else "")
    if entry:
        t = str(entry.get("target") or "")
        if t.lower().endswith(".exe"): hints.add(_norm(os.path.splitext(os.path.basename(t))[0]))
        if "!" in t:  # AUMID: Microsoft.WindowsNotepad_8wekyb3d8bbwe!App -> 'windowsnotepad', 'notepad'
            pkg = t.split("_")[0].split("!")[0]
            for part in pkg.split("."): hints.add(_norm(part))
            hints.add(_norm(pkg.split(".")[-1].replace("Windows", "")))
        hints.add(_norm(entry.get("name")))
    KNOWN = {"vscode": "code", "visualstudiocode": "code", "word": "winword", "powerpoint": "powerpnt", "calculator": "calculatorapp",
             "fileexplorer": "explorer", "photos": "photosapp", "paint": "mspaint", "teams": "mstteams"}
    for h in list(hints):
        if h in KNOWN: hints.add(KNOWN[h])
    return {h for h in hints if len(h) >= 3 and h not in ("microsoft", "windows", "app", "the")}

def pick(windows, hints, app_name=""):
    """windows: [{'hwnd','title','proc','exe','pid','visible','w','h','cls'}] -> best main window of the target app, or None."""
    cands = []
    for w in windows:
        if not w.get("visible", True) or w.get("w", 1) < 120 or w.get("h", 1) < 80: continue
        if HELPER_TITLES.match((w.get("title") or "").strip()): continue
        if w.get("cls") == "#32770": continue  # message boxes / "not responding" dialogs are not the app window
        proc, exe = _norm(w.get("proc")), _norm(os.path.basename(str(w.get("exe") or "")))
        title = _norm(w.get("title"))
        score = 0
        if any(h and (h == proc or proc.startswith(h) or h in exe) for h in hints): score += 3
        if w.get("proc", "").lower() == "applicationframehost.exe" and any(h and h in title for h in hints): score += 3  # UWP host
        if app_name and _norm(app_name) in title: score += 1
        if score >= 3:
            cands.append((score, w.get("w", 0) * w.get("h", 0), w))
    if not cands: return None
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return cands[0][2]

# ---------------- Windows ----------------
def list_windows():
    import ctypes, ctypes.wintypes as wt, psutil
    u = ctypes.windll.user32; out = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if not u.IsWindowVisible(h) or u.GetWindow(h, 4):  # skip invisible and owned popups (GW_OWNER)
            return True
        n = u.GetWindowTextLengthW(h); buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
        cls = ctypes.create_unicode_buffer(256); u.GetClassNameW(h, cls, 256)
        pid = wt.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        try: p = psutil.Process(pid.value); proc, exe = p.name(), p.exe()
        except Exception: proc, exe = "", ""
        out.append({"hwnd": int(h), "title": buf.value, "cls": cls.value, "pid": pid.value, "proc": proc, "exe": exe, "visible": True,
                    "w": r.right - r.left, "h": r.bottom - r.top, "rect": [r.left, r.top, r.right, r.bottom],
                    "iconic": bool(u.IsIconic(h))})
        return True
    u.EnumWindows(cb, 0)
    return out

def foreground_hwnd():
    import ctypes
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)

def force_foreground(hwnd):
    """AllowSetForegroundWindow + AttachThreadInput + SetForegroundWindow (+ restore if minimized), then verify."""
    import ctypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    try:
        u.AllowSetForegroundWindow(-1)  # ASFW_ANY
        if u.IsIconic(hwnd): u.ShowWindow(hwnd, 9)  # SW_RESTORE
        fg = u.GetForegroundWindow()
        cur = k.GetCurrentThreadId(); fg_t = u.GetWindowThreadProcessId(fg, None); tgt_t = u.GetWindowThreadProcessId(hwnd, None)
        u.AttachThreadInput(cur, fg_t, True); u.AttachThreadInput(cur, tgt_t, True)
        # a tiny Alt tap lifts the foreground lock when another app holds it
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
        u.BringWindowToTop(hwnd); u.SetForegroundWindow(hwnd); u.SetFocus(hwnd)
        u.AttachThreadInput(cur, fg_t, False); u.AttachThreadInput(cur, tgt_t, False)
    except Exception:
        pass
    return foreground_hwnd() == int(hwnd)

def window_rect(hwnd):
    import ctypes, ctypes.wintypes as wt
    r = wt.RECT(); ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)); return [r.left, r.top, r.right, r.bottom]

def window_title(hwnd):
    import ctypes
    u = ctypes.windll.user32; n = u.GetWindowTextLengthW(hwnd); b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(hwnd, b, n + 1)
    return b.value

def is_window(hwnd):
    import ctypes
    return bool(ctypes.windll.user32.IsWindow(hwnd))

# ---------------- macOS ----------------
def mac_bind(app_name):
    try:
        from AppKit import NSWorkspace
        for a in NSWorkspace.sharedWorkspace().runningApplications():
            if _norm(a.localizedName()) == _norm(app_name) or _norm(app_name) in _norm(a.bundleIdentifier() or ""):
                return {"pid": int(a.processIdentifier()), "title": a.localizedName(), "bundle": a.bundleIdentifier(), "hwnd": int(a.processIdentifier())}
    except Exception: pass
    return None

def mac_activate(pid):
    try:
        from AppKit import NSRunningApplication
        a = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        a.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
        time.sleep(0.3)
        from AppKit import NSWorkspace
        return int(NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()) == int(pid)
    except Exception:
        return False

class WindowBinding:
    """The target app's window. All Win32/AX calls are injectable for tests."""
    def __init__(self, app, entry=None, lister=None, fg=None, focus=None, rect=None, title=None, alive=None, log=print):
        self.app, self.entry, self.log = app, entry, log
        self.hints = exe_hints(app, entry)
        self._mac = IS_MAC and lister is None
        if self._mac:
            self.lister = lambda: [w for w in [mac_bind(app)] if w]
            self.fg = lambda: self._mac_front(); self.focus = lambda h: mac_activate(h)
            self.rect = rect or (lambda h: None); self.title = title or (lambda h: self.app); self.alive = alive or (lambda h: True)
        else:
            self.lister = lister or list_windows; self.fg = fg or foreground_hwnd; self.focus = focus or force_foreground
            self.rect = rect or window_rect; self.title = title or window_title; self.alive = alive or is_window
        self.hwnd, self.info = None, None

    def _mac_front(self):
        try:
            from AppKit import NSWorkspace
            return int(NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier())
        except Exception: return 0

    def bind(self, timeout=15.0, sleep=time.sleep):
        end = time.time() + timeout
        while True:
            try:
                ws = self.lister(); w = (ws[0] if ws else None) if self._mac else pick(ws, self.hints, self.app)
            except Exception: w = None
            if w:
                self.hwnd, self.info = w["hwnd"], w; return w
            if time.time() >= end: return None
            sleep(0.5)

    def is_foreground(self):
        return bool(self.hwnd) and int(self.fg() or 0) == int(self.hwnd)

    def ensure(self, tries=3, sleep=time.sleep):
        """True when the target window is (now) in the foreground. Rebinds if the window was replaced."""
        if not self.hwnd or not self.alive(self.hwnd):
            if not self.bind(timeout=5, sleep=sleep): return False
        for _ in range(tries):
            if self.is_foreground(): return True
            self.focus(self.hwnd); sleep(0.3)
        return self.is_foreground()

    def window_rect(self):
        try: return self.rect(self.hwnd)
        except Exception: return None

    def window_title(self):
        try: return self.title(self.hwnd)
        except Exception: return ""
