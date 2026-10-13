"""Central app policy (1.4.0): the agent may open and operate any installed app EXCEPT core system apps.
The denylist is matched by display name, executable, launch command, AUMID and macOS bundle id, and is enforced on
open_app, launch hotkeys, typed launch commands and the vision loop. Core apps are always blocked."""
import os, re

# (label, regex over a normalized name/exe/command/bundle id)
CORE = [
    ("Control Panel", r"control panel|^control(\.exe)?$|\.cpl\b|microsoft\.windows\.controlpanel|shell:controlpanel"),
    ("Registry Editor", r"regedit|regedt32|registry( editor)?"),
    ("Settings", r"^(windows |pc |system |mac ?os |macos )?settings( app)?$|^ms-settings|immersivecontrolpanel|windows\.immersivecontrolpanel|"
                 r"system settings|system preferences|com\.apple\.systempreferences|com\.apple\.settings|systemsettings(\.exe)?|\.prefpane\b"),
    ("Services", r"services\.msc|^services( app)?$|^services\.exe$"),
    ("Group Policy Editor", r"gpedit|group policy|secpol|local security policy"),
    ("Command Prompt", r"^cmd(\.exe)?$|command prompt|windows command processor|conhost|\bprompt$|git bash|^bash$|^wsl(\.exe)?$|windows subsystem for linux|^ubuntu( \d.*)?$"),
    ("PowerShell", r"powershell|pwsh"),
    ("Terminal", r"^terminal( app)?$|windows terminal|^wt(\.exe)?$|com\.apple\.terminal|iterm|microsoft\.windowsterminal"),
    ("Task Manager", r"task ?manager|taskmgr|^task mgr$"),
    ("Activity Monitor", r"activity monitor|com\.apple\.activitymonitor"),
    ("Disk Management", r"disk ?management|diskmgmt|disk utility|com\.apple\.diskutility|diskpart|defragment|disk cleanup|cleanmgr|dfrgui"),
    ("Computer Management", r"computer management|compmgmt|device manager|devmgmt|event viewer|eventvwr|task scheduler|taskschd|mmc(\.exe)?$|\.msc\b"),
    ("Security / firewall", r"windows security|windows defender|defender|securityhealth|firewall|wf\.msc|windowsdefender:|"
                            r"security (center|& privacy|and privacy)|privacy & security"),
    ("User accounts", r"user accounts|netplwiz|lusrmgr|useraccountcontrol|user account control|users? & groups|control userpasswords"),
    ("System configuration", r"msconfig|system configuration|system properties|sysdm\.cpl|systempropertiesadvanced|recovery|reset this pc|"
                             r"bcdedit|keychain access|com\.apple\.keychainaccess|directory utility|boot camp|startup disk"),
    ("Run dialog", r"^run( dialog| box)?$"),
]
_CORE = [(lbl, re.compile(rx, re.I)) for lbl, rx in CORE]

# hotkeys that open core surfaces (lowercased key names; win/super/cmd treated alike)
_WIN = {"win", "winleft", "winright", "super", "windows", "meta"}
BLOCKED_HOTKEYS = [({"win", "r"}, "the Run dialog"), ({"win", "i"}, "Settings"), ({"win", "x"}, "the system (Win+X) menu"),
                   ({"ctrl", "shift", "esc"}, "Task Manager"), ({"ctrl", "alt", "delete"}, "the security screen"),
                   ({"ctrl", "alt", "del"}, "the security screen"), ({"win", "pause"}, "System properties"),
                   ({"cmd", "alt", "esc"}, "Force Quit"), ({"command", "option", "escape"}, "Force Quit")]

def norm(s):
    s = str(s or "").strip().strip('"').lower()
    s = s.replace("\\", "/")
    base = s.rsplit("/", 1)[-1] if "/" in s and not s.startswith(("ms-settings", "shell:")) else s
    base = re.sub(r"\.(lnk|app|url)$", "", base)
    return re.sub(r"\s+", " ", base).strip()

def core_app(*names):
    """Return the core-app label if any of the given names/exes/ids/commands is a core system app, else None."""
    for n in names:
        if not n: continue
        for cand in {norm(n), str(n).strip().lower()}:
            for lbl, rx in _CORE:
                if rx.search(cand): return lbl
    return None

def message(label):
    return (f"Blocked: {label} is a core system app, and Liscia Agent never opens or operates core system apps "
            "(Control Panel, Settings, Registry Editor, services, Group Policy, Command Prompt/PowerShell/Terminal, Task Manager/Activity Monitor, "
            "disk, security/firewall or user-account tools). You can open it yourself if you need it.")

def _keys(act):
    keys = act.get("keys"); keys = keys if isinstance(keys, list) else str(keys or "").split("+")
    ks = {str(k).strip().lower() for k in keys if str(k).strip()}
    if ks & _WIN: ks = (ks - _WIN) | {"win"}
    return ks

# a typed line that is just a launch command (Run box / search box / address bar style)
LAUNCH_TYPED = re.compile(r"^\s*(start\s+)?(regedit|regedt32|control(\s+\w+)?|ms-settings:\S*|cmd|cmd\.exe|powershell|pwsh|wt|taskmgr|"
                          r"\S+\.msc|\S+\.cpl|msconfig|netplwiz|gpedit|secpol|diskpart|bcdedit|terminal|activity monitor|"
                          r"control panel|registry editor|task manager|system settings|system preferences|settings)\s*$", re.I)

def check(act, task=""):
    """Return a block message for an action, or None. Core apps are blocked no matter what the task says."""
    a = (act or {}).get("action")
    if a == "open_app":
        lbl = core_app(act.get("app"), act.get("path"), act.get("target"))
        return message(lbl) if lbl else None
    if a == "hotkey":
        ks = _keys(act)
        for combo, what in BLOCKED_HOTKEYS:
            c = {"win" if k in _WIN else k for k in combo}
            if c <= ks: return f"Blocked: that shortcut opens {what}, a core system surface Liscia Agent never uses."
        return None
    if a == "type":
        text = str(act.get("text") or "")
        if LAUNCH_TYPED.match(text):
            lbl = core_app(text.strip().split()[-1] if text.strip().lower().startswith("start ") else text) or "a core system app"
            return message(lbl)
        return None
    if a == "open_url":
        u = str(act.get("url") or "").lower()
        if re.match(r"^(ms-settings:|shell:|control:|x-apple\.systempreferences:|windowsdefender:)", u):
            return message(core_app(u) or "a system settings page")
    return None

# ---- risky in-app actions: always ask first ----------------------------------------------------
RISKY_APP = re.compile(r"\b(delete|remove|erase|wipe|format|uninstall|install|send|post|publish|submit|buy|purchase|pay|checkout|order|"
                       r"subscribe|transfer|empty (the )?(trash|recycle bin)|permanently|don'?t save|discard|close without saving|reset|sign out|log ?out)\b", re.I)

def risky(act, element_text=""):
    """True if this action looks like delete / send / buy / install / discard-unsaved and needs the user's OK."""
    a = (act or {}).get("action")
    blob = " ".join(str(act.get(k, "")) for k in ("target", "reason", "thought", "label")) + " " + (element_text or "")
    if a in ("click", "double_click", "click_element", "type") and RISKY_APP.search(blob):
        return True
    if a == "hotkey":
        ks = _keys(act)
        if ks in ({"shift", "delete"}, {"shift", "del"}, {"alt", "f4"}, {"ctrl", "w"}, {"cmd", "q"}, {"command", "q"}, {"cmd", "w"}, {"command", "w"}):
            return True
    return False
