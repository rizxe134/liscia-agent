"""Installed-app discovery (1.4.0): a cached index of the apps on this computer with fuzzy name matching,
so open_app 'spotify' / 'photoshop' / 'notepad' launches the real shortcut / exe / AUMID / .app instead of guessing.
Windows: Start Menu .lnk files (ProgramData + AppData), App Paths registry (read-only), UWP/Store apps via Get-StartApps.
macOS: /Applications, ~/Applications, /System/Applications (+ Utilities)."""
import difflib, json, os, re, subprocess, sys, time
import policy

IS_WIN, IS_MAC = sys.platform.startswith("win"), sys.platform == "darwin"
TTL = 6 * 3600

ALIASES = {"chrome": "google chrome", "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
           "word": "microsoft word", "excel": "microsoft excel", "powerpoint": "microsoft powerpoint", "outlook": "microsoft outlook",
           "onenote": "microsoft onenote", "teams": "microsoft teams", "edge": "microsoft edge", "calc": "calculator",
           "explorer": "file explorer", "files": "file explorer", "photoshop": "adobe photoshop", "acrobat": "adobe acrobat",
           "illustrator": "adobe illustrator", "premiere": "adobe premiere pro", "lightroom": "adobe lightroom",
           "paint": "paint", "mspaint": "paint", "store": "microsoft store", "whatsapp": "whatsapp", "zoom": "zoom",
           "firefox": "mozilla firefox", "notes": "notes", "music": "music", "itunes": "music", "messages": "messages",
           "snipping tool": "snipping tool", "camera": "camera", "photos": "photos", "clock": "clock", "steam": "steam", "discord": "discord"}
JUNK = re.compile(r"\b(uninstall|uninstaller|readme|read me|help|manual|documentation|website|release notes|license|support|"
                  r"repair|setup|installer|update(r)?|changelog|faq)\b", re.I)

PS_SCRIPT = r"""
$ErrorActionPreference='SilentlyContinue'
$out = New-Object System.Collections.ArrayList
$sh = New-Object -ComObject WScript.Shell
$dirs = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
foreach ($d in $dirs) { Get-ChildItem $d -Recurse -Include *.lnk,*.url | ForEach-Object {
  $t = ''; if ($_.Extension -eq '.lnk') { try { $t = $sh.CreateShortcut($_.FullName).TargetPath } catch {} }
  [void]$out.Add(@{name=$_.BaseName; path=$_.FullName; target=$t; kind='lnk'}) } }
foreach ($k in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths')) {
  Get-ChildItem $k | ForEach-Object { $p = (Get-ItemProperty $_.PSPath).'(default)'
    if ($p) { [void]$out.Add(@{name=($_.PSChildName -replace '\.exe$',''); path=$p.Trim('"'); target=$p.Trim('"'); kind='apppath'}) } } }
try { Get-StartApps | ForEach-Object { [void]$out.Add(@{name=$_.Name; path=''; target=$_.AppID; kind='aumid'}) } } catch {}
$out | ConvertTo-Json -Compress -Depth 3
"""

def norm(s):
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"\.(exe|app|lnk|url)$", "", s.strip())
    s = re.sub(r"[^a-z0-9+#]+", " ", s)
    s = re.sub(r"\b(the|app|application|program)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def cache_path():
    try:
        import paths; d = paths.data_dir()
    except Exception:
        d = os.path.join(os.path.expanduser("~"), ".pc-agent")
    os.makedirs(d, exist_ok=True); return os.path.join(d, "app_index.json")

def scan_windows(run=subprocess.run):
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
            capture_output=True, text=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    raw = (r.stdout or "").strip()
    data = json.loads(raw) if raw else []
    return data if isinstance(data, list) else [data]

def scan_mac(roots=None):
    roots = roots or ["/Applications", os.path.expanduser("~/Applications"), "/System/Applications",
                      "/System/Applications/Utilities", "/Applications/Utilities"]
    out = []
    for root in roots:
        try: names = os.listdir(root)
        except OSError: continue
        for n in names:
            p = os.path.join(root, n)
            if n.endswith(".app"):
                out.append({"name": n[:-4], "path": p, "target": p, "kind": "app"})
            elif os.path.isdir(p) and not n.startswith(".") and root == "/Applications":  # vendor folders: /Applications/Adobe Photoshop 2025/...
                try:
                    out += [{"name": m[:-4], "path": os.path.join(p, m), "target": os.path.join(p, m), "kind": "app"} for m in os.listdir(p) if m.endswith(".app")]
                except OSError: pass
    return out

def build(entries):
    """Deduplicate, drop uninstallers/readmes, tag core apps (they stay in the index but are never launched)."""
    seen, idx = set(), []
    pri = {"aumid": 0, "lnk": 1, "app": 1, "apppath": 2}
    for e in sorted(entries or [], key=lambda e: pri.get(e.get("kind"), 3)):
        name = str(e.get("name") or "").strip()
        if not name or JUNK.search(name): continue
        tgt = str(e.get("target") or "")
        if e.get("kind") == "lnk" and tgt and not re.search(r"\.(exe|bat|cmd|msc|cpl)$", tgt, re.I) and not tgt.lower().startswith("shell:") and os.path.splitext(tgt)[1]:
            continue  # shortcuts to documents / web pages
        key = norm(name)
        if not key or key in seen: continue
        seen.add(key)
        idx.append({"name": name, "key": key, "path": e.get("path") or "", "target": tgt, "kind": e.get("kind") or "",
                    "core": policy.core_app(name, tgt, e.get("path"))})
    return idx

_MEM = {"t": 0, "idx": None}

def index(refresh=False, scanner=None):
    if _MEM["idx"] is not None and not refresh and time.time() - _MEM["t"] < TTL: return _MEM["idx"]
    p = cache_path()
    if not refresh and scanner is None and os.path.exists(p) and time.time() - os.path.getmtime(p) < TTL:
        try:
            _MEM.update(t=time.time(), idx=json.load(open(p, encoding="utf-8"))); return _MEM["idx"]
        except Exception: pass
    try:
        entries = scanner() if scanner else scan_windows() if IS_WIN else scan_mac() if IS_MAC else []
    except Exception:
        entries = []
    idx = build(entries)
    try: json.dump(idx, open(p, "w", encoding="utf-8"))
    except Exception: pass
    _MEM.update(t=time.time(), idx=idx); return idx

def score(q, key):
    if q == key: return 1.0
    qt, kt = q.split(), key.split()
    if key.startswith(q + " ") or (len(q) >= 3 and key.startswith(q)): return 0.93 - 0.01 * (len(kt) - len(qt))
    if all(t in kt for t in qt): return 0.88 - 0.01 * (len(kt) - len(qt))
    if any(t == q for t in kt) and len(q) >= 4: return 0.84 - 0.01 * len(kt)
    r = difflib.SequenceMatcher(None, q, key).ratio()
    return r * 0.9 if r >= 0.86 else r * 0.7  # typos only ("notpad"), not different apps ("photoshop" != "photos")

def find(name, idx=None, cutoff=0.75):
    """Best index entry for a spoken app name, or None."""
    idx = index() if idx is None else idx
    q = norm(name)
    if not q: return None
    cands = [q] + ([norm(ALIASES[q])] if q in ALIASES else [])
    best, bs = None, 0.0
    for c in cands:
        for e in idx:
            s = score(c, e["key"])
            if s > bs: best, bs = e, s
    return best if bs >= cutoff else None

def launch_argv(e):
    """Command to launch an index entry (never a core app)."""
    if IS_MAC or e.get("kind") == "app":
        return ["open", "-a", e["path"]]
    if e.get("kind") == "aumid":
        return ["explorer.exe", "shell:AppsFolder\\" + e["target"]]
    return ["cmd", "/c", "start", "", e["path"] or e["target"]]

def launch(name, run=None, idx=None):
    """Resolve and launch. Returns (entry_or_None, blocked_message_or_None). Raises LookupError when nothing matches."""
    lbl = policy.core_app(name)
    if lbl: return None, policy.message(lbl)
    e = find(name, idx)
    if not e: raise LookupError(name)
    lbl = e.get("core") or policy.core_app(e["name"], e.get("target"), e.get("path"))
    if lbl: return e, policy.message(lbl)
    if IS_WIN and run is None and e.get("kind") in ("lnk", "apppath"):
        os.startfile(e["path"] or e["target"])
    else:
        (run or (lambda c: subprocess.run(c, timeout=20, capture_output=True)))(launch_argv(e))
    return e, None
