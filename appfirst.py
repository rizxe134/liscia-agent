"""App-first resolution (1.4.4). If a task names an app that is installed or running on this computer (fuzzy,
typo-tolerant), the task is about that DESKTOP app, never its website - unless the user explicitly asks for the
website/browser/web/online/.com version. Applied in code after the planner, for every app."""
import re, sys
import appindex, intents

EXPLICIT_WEB = re.compile(r"\b(website|web ?site|web ?page|webpage|web app|web player|web version|browser|online|(?:in|on|using|with) (?:google )?chrome|(?:in|on) (?:a |another |a new |new |separate )?(?:new |another |separate )?tab|"
                          r"in safari|in firefox|in edge|on the web|the web)\b|\.(com|org|net|io|tv|app|co)\b|https?://|www\.", re.I)
BROWSERS = {"google chrome", "chrome", "safari", "firefox", "mozilla firefox", "microsoft edge", "edge", "brave", "opera", "arc", "chromium"}
# common words never treated as app names on their own (an index can contain apps called "Music", "Clock", "Mail", ...)
COMMON = set("""a an the and or to of on in at for with from by my me i you it this that these those is are be can could would will
please pls hey ok okay so just now then up down out off next previous last back song songs track tracks music video videos
play pause resume stop skip mute volume louder quieter turn open launch start run close quit minimize maximize focus show switch go
new save find undo redo tab tabs window app application program some something what who how why when where search look
type write make create do get set put give tell help""".split())
AUDIO_APP_HINT = {"music app": "music", "apple music": "music", "itunes": "music", "groove": "media player", "windows media player": "media player",
                  "media player": "media player", "vs code": "visual studio code", "vscode": "visual studio code"}

SYSTEM_PROCS = set("""system idle svchost csrss wininit winlogon services lsass smss dwm explorer conhost fontdrvhost sihost ctfmon
runtimebroker searchhost searchindexer startmenuexperiencehost shellexperiencehost textinputhost dllhost taskhostw audiodg spoolsv
wmiprvse securityhealthservice msmpeng nissrv registry memory compression applicationframehost systemsettings lockapp
python py pythonw powershell pwsh cmd launchd kernel_task windowserver loginwindow mds mdworker coreaudiod""".split())

def explicit_web(task):
    return bool(EXPLICIT_WEB.search(task or ""))

def running_names(proc_iter=None):
    """Lower-case process base names of running apps (spotify, vlc, discord, ...)."""
    try:
        if proc_iter is None:
            import psutil; proc_iter = (p.info.get("name") or "" for p in psutil.process_iter(["name"]))
        return {re.sub(r"\.(exe|app)$", "", n.lower()) for n in proc_iter if n}
    except Exception:
        return set()

def _spans(t):
    w = re.findall(r"[a-z0-9+#.'&-]+", t.lower())
    # prefer the words after on/in/with/using/from ("pause the music on spotify")
    pref = []
    for i, x in enumerate(w):
        if x in ("on", "in", "with", "using", "from", "via"):
            pref += [" ".join(w[i + 1:i + 1 + n]) for n in (3, 2, 1) if i + n < len(w) + 1 and i + 1 + n <= len(w)]
    rest = [" ".join(w[i:i + n]) for n in (3, 2, 1) for i in range(len(w) - n + 1)]
    out, seen = [], set()
    for s in pref + rest:
        s = re.sub(r"^(the|my)\s+", "", s).strip(" .'")
        if s and s not in seen: seen.add(s); out.append(s)
    return out

VENDOR = re.compile(r"^(microsoft|google|adobe|mozilla|apple)\s+")

def names_of(e):
    """Whole-name forms a user would say: 'vlc media player' -> {'vlc media player', 'vlc'}; 'microsoft word' -> {'microsoft word', 'word'}."""
    k = e["key"]; out = {k, VENDOR.sub("", k)}
    first = k.split()[0] if k.split() else ""
    if len(k.split()) > 1 and len(first) >= 3 and first not in COMMON and not VENDOR.match(k) and first not in ("windows", "add", "check", "click", "logi"):
        if re.search(r"\b(player|media|desktop|client|launcher|app)\b", k): out.add(first)
    return {n for n in out if n}

def lookup(q, idx):
    """Exact whole-name (or alias) match first, then a one-word typo. Never a prefix/partial ('page' is not 'Pageant')."""
    import difflib
    qa = appindex.norm(appindex.ALIASES.get(q, q))
    for e in idx:
        if q in names_of(e) or qa in names_of(e): return e
    if " " in q or len(q) < 5 or q in COMMON: return None
    for e in idx:
        for k in names_of(e):
            if " " in k or len(k) < 5 or k[0] != q[0] or abs(len(k) - len(q)) > 1: continue
            if sorted(k) == sorted(q) or difflib.SequenceMatcher(None, q, k).ratio() >= 0.83: return e
    return None

def mention(task, idx=None, running=None):
    """The installed/running app a task names, e.g. 'can you pause the musiuc on spotify' -> ('Spotify', entry, running?)."""
    t = intents.fix_typos(task or "")
    idx = appindex.index() if idx is None else idx
    running = running_names() if running is None else running
    best = None
    for s in _spans(t):
        words = s.split()
        if all(x in COMMON for x in words) and s not in AUDIO_APP_HINT: continue
        if (words[0] in COMMON or words[-1] in COMMON) and s not in AUDIO_APP_HINT: continue
        q = appindex.norm(AUDIO_APP_HINT.get(s, s))
        if len(q.replace(" ", "")) < 3: continue
        e = lookup(q, idx)
        run = next((r for r in running if r not in SYSTEM_PROCS and len(r) >= 4 and (q == appindex.norm(r) or (e and appindex.norm(r) in exe_names(e)))), None)
        if e or run:
            sc = len(words)
            if not best or sc > best[0]:
                best = (sc, (e["name"] if e else run.title()), e, bool(run))
    return best[1:] if best else None

def swapped(q, idx):
    """Two-letter swaps / one-letter slips in a single word: 'discrod' -> Discord, 'spotfy' -> Spotify."""
    import difflib
    if " " in q or len(q) < 5: return None
    for e in idx:
        for k in [e["key"]] + e["key"].split():
            if len(k) < 5 or k[0] != q[0]: continue
            if (sorted(k) == sorted(q) and len(k) == len(q)) or difflib.SequenceMatcher(None, q, k).ratio() >= 0.83:
                return e
    return None

def exe_names(e):
    try:
        import winbind; return winbind.exe_hints(e.get("name"), e)
    except Exception:
        return set()

def is_browser(name):
    return appindex.norm(name) in BROWSERS or bool(intents.named_browser(appindex.norm(name)))

def override(plan, task, idx=None, running=None, is_command=None):
    """Return (plan, note). Turns web intents into desktop_app when the task names an installed/running app."""
    if plan.get("intent") == "web_research_to_files": return plan, None
    if plan.get("intent") == "desktop_app" and plan.get("app"): return plan, None
    m = mention(task, idx, running)
    if not m: return plan, None
    name, entry, running_now = m
    if explicit_web(task) and not (is_browser(name) and is_command): return plan, None
    if is_browser(name) and not is_command: return plan, None  # browsers stay web tasks, except media/window commands
    if plan.get("intent") == "web_answer" and not is_command and not running_now and not re.match(r"^\W*(?:\w+\W+){0,3}?(open|launch|start|use)\b", task or "", re.I):
        return plan, None  # "who founded spotify" is a question, not an app task
    p = dict(plan, intent="desktop_app", app=name, site="")
    return p, f"app-first: {name} is {'running' if running_now else 'installed'} -> desktop app (was {plan.get('intent')})"
