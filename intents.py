"""Deterministic handling of common commands - no model needed, instant and reliable.
Also tracks the 'current browser' so URLs open in the app the user/agent is working in."""
import re, time
import browser_dom

STATE = {"browser": None, "app": None, "named": None}  # named = browser the user named in the current task  # persists across tasks/messages in this process

BROWSER_NAMES = {"safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome",
                 "firefox": "Firefox", "brave": "Brave Browser", "edge": "Microsoft Edge", "arc": "Arc"}
APP_NAMES = {**BROWSER_NAMES, "notes": "Notes", "mail": "Mail", "messages": "Messages", "finder": "Finder",
             "music": "Music", "calendar": "Calendar", "terminal": "Terminal", "settings": "System Settings",
             "system settings": "System Settings", "spotify": "Spotify", "slack": "Slack", "vs code": "Visual Studio Code",
             "vscode": "Visual Studio Code", "photos": "Photos", "maps": "Maps", "app store": "App Store"}
SITES = {"youtube": "https://www.youtube.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
         "github": "https://github.com", "reddit": "https://www.reddit.com", "twitter": "https://x.com", "x": "https://x.com",
         "netflix": "https://www.netflix.com", "amazon": "https://www.amazon.com", "wikipedia": "https://www.wikipedia.org",
         "chatgpt": "https://chatgpt.com", "linkedin": "https://www.linkedin.com", "instagram": "https://www.instagram.com",
         "facebook": "https://www.facebook.com", "spotify web": "https://open.spotify.com"}
BROWSERS_SET = set(BROWSER_NAMES.values())

def note_app(app):
    if app:
        STATE["app"] = app
        if app in BROWSERS_SET: STATE["browser"] = app

def current_browser(frontmost=None):
    """Frontmost app if it's a browser, else the last browser we used/opened, else None (= system default)."""
    if STATE.get("named"):
        return STATE["named"]  # the user named a browser for this task
    try:
        import extlink
        if extlink.LINK.connected(): return "Google Chrome"  # extension live -> Chrome is the web browser
    except Exception: pass
    try: front = (frontmost or browser_dom.frontmost_app)()
    except Exception: front = None
    if front in BROWSERS_SET:
        STATE["browser"] = front; return front
    if STATE["browser"]:
        return STATE["browser"]
    if STATE.get("preferred"):
        return STATE["preferred"]
    try: recent = browser_dom.recent_browser()
    except Exception: recent = None
    if recent: STATE["browser"] = recent
    return recent

_FILLER = r"(?:please |can you |could you |now |then |and |also |just )*"
_SPLIT = re.compile(r"\s*(?:,\s*(?:and\s+)?then\s+|,\s*and\s+|\s+and\s+then\s+|\s+then\s+|\s+and\s+|;\s*|,\s*)", re.I)

def _clean(s):
    s = re.sub(r"^" + _FILLER, "", s.strip().lower()); return s.strip(" .!?")

def match(part):
    """Return a list of actions for one clause, or None."""
    p = _clean(part)
    m = re.match(r"^(?:open|launch|start|switch to)\s+(?:the\s+)?(?:app\s+)?(.+?)(?:\s+app)?$", p)
    if m and m.group(1) in APP_NAMES:
        return [{"action": "open_app", "app": APP_NAMES[m.group(1)]}]
    m = re.match(r"^(?:open|go to|visit|navigate to|load|bring up|search for|show me|take me to)\s+(?:the\s+)?(?:website\s+)?"
                 r"([a-z0-9.\-]+?)(?:\s+(?:website|site|homepage|page|\.com))?(?:\s+(?:in|on|using)\s+([a-z ]+))?$", p)
    if m:
        name, br = m.group(1), m.group(2)
        browser = BROWSER_NAMES.get(br.strip()) if br else None
        url = SITES.get(name.replace(".com", "")) or (("https://" + name) if re.match(r"^[a-z0-9\-]+\.[a-z.]{2,}$", name) else None)
        if url:
            a = {"action": "open_url", "url": url}
            if browser: a["browser"] = browser
            return [a]
    p = re.sub(r"\s+(?:in|on|using|with)\s+(?:google chrome|chrome|safari|firefox|brave|edge|arc)$", "", p)
    m = re.match(r"^(?:search|look up|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)$", p) or \
        re.match(r"^youtube\s+search\s+(?:for\s+)?(.+)$", p)
    if m:
        import urllib.parse
        return [{"action": "open_url", "url": "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(m.group(1).strip(" '\""))}]
    m = re.match(r"^(?:search|google|look up)\s+(?:for\s+)?(.+?)(?:\s+on\s+(youtube|google))?$", p)
    if m and m.group(2) == "youtube":
        import urllib.parse
        return [{"action": "open_url", "url": "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(m.group(1))}]
    m = re.match(r"^(?:play|watch|put on|find)\s+(?!the\s+(?:first|1st|top)\b)(.+?)\s+(?:on|in|from)\s+youtube$", p)
    if m:  # "play pursuit of jade ost on youtube" -> results page, then the video whose title matches
        return [{"action": "open_url", "url": _yt(m.group(1))}, {"action": "first_video", "match": m.group(1).strip(" '\"")}]
    if re.match(r"^(?:click|open|play|watch|tap)\s+(?:on\s+)?(?:the\s+)?(?:very\s+)?(?:first|1st|top)\s+(?:youtube\s+)?(?:video|result|one)(?:\s+.*)?$", p):
        return [{"action": "first_video"}]
    return None

_BROWSER_RE = re.compile(r"\b(google chrome|chrome|safari|firefox|brave|microsoft edge|edge|arc)\b", re.I)
WEB_RE = re.compile(r"\b(browser|website|web ?site|web|url|link|tab|page|search|google|youtube|video|chrome|online|"
                    r"click|claick|clik|play|watch|song|music|serach|seach|yt|"
                    r"https?://|www\.|" + "|".join(re.escape(k) for k in SITES) + r")\b|\.(com|org|net|io)\b", re.I)

def named_browser(task):
    """Browser the user explicitly named in the task ("... in safari"), else None."""
    m = _BROWSER_RE.search(task or "")
    return BROWSER_NAMES.get(m.group(1).lower()) if m else None

def is_web_task(task):
    return bool(WEB_RE.search(fix_typos(task or "")))

TYPOS = {"claick": "click", "clcik": "click", "clik": "click", "cilck": "click", "clikc": "click", "cick": "click", "clck": "click",
         "serach": "search", "seach": "search", "saerch": "search", "searh": "search", "sreach": "search", "serch": "search",
         "youtueb": "youtube", "yotube": "youtube", "youtub": "youtube", "yt": "youtube", "youube": "youtube", "you tube": "youtube",
         "plya": "play", "paly": "play", "pley": "play", "opne": "open", "oepn": "open", "vidoe": "video", "vedio": "video"}

def fix_typos(text):
    t = text
    for bad, good in TYPOS.items():
        t = re.sub(r"\b" + re.escape(bad) + r"\b", good, t, flags=re.I)
    return t

_STOP_END = r"(?=\s*(?:,|\.|;|\band\b|\bthen\b|\b(?:on|in)\s+youtube\b|\b(?:in|on|using)\s+(?:google\s+)?chrome\b|$))"
_PLAY = re.compile(r"\b(?:play|click|watch|open (?:it|that|the (?:first |top )?(?:video|song|result))|put (?:it )?on|listen)\b", re.I)

def youtube_request(task):
    """Tolerant parse of 'can you open up youtube and on youtube can you search for the song X by Y and claick on to play the song'.
    Returns (query, wants_play) or None."""
    t = fix_typos(task or "")
    if not re.search(r"\byoutube\b", t, re.I): return None
    pat = (r"\b(?:search|look|find|type)(?:\s+(?:up|it\s+up))?(?:\s+(?:for|up))?(?:\s+(?:on\s+)?youtube)?(?:\s+for)?\s+"
           r"(?:the\s+|a\s+)?(?:(?:song|video|music video|track|music|clip)\s+(?:called\s+|named\s+)?)?['\"]?(.+?)['\"]?" + _STOP_END)
    m = re.search(pat, t, re.I)
    if not m:  # "play X on youtube"
        m = re.search(r"\b(?:play|watch|put on)\s+(?!(?:the\s+)?(?:very\s+)?(?:first|1st|top|it|that|this)\b)(?:the\s+)?(?:(?:song|video|track)\s+)?['\"]?(.+?)['\"]?" + _STOP_END, t, re.I)
        if not m: return None
        q = m.group(1).strip(); return (q, True) if q and q.lower() not in ("youtube", "it") else None
    q = m.group(1).strip(" '\"")
    if not q or q.lower() in ("youtube", "it", "something"): return None
    after = t[m.end():]
    return q, bool(_PLAY.search(after) or re.search(r"\b(?:play|listen to|watch)\b", t[:m.start()], re.I))

def match_words(q):
    """Words to look for in result titles (drops filler like 'by', 'the', 'song')."""
    stop = {"by", "the", "a", "an", "song", "video", "official", "music", "ft", "feat"}
    w = [x for x in re.findall(r"[\w']+", q.lower()) if x not in stop]
    return " ".join(w) or q

def _yt(q):
    import urllib.parse
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q.strip(" '\""))

def plan(task):
    """Split a task into clauses. Returns (deterministic_actions, remaining_text or '')."""
    yt = youtube_request(task)
    if yt:  # whole-sentence YouTube search (+ play) - tolerant of filler and typos
        q, play = yt; nb = named_browser(task)
        a = {"action": "open_url", "url": _yt(q)}
        if nb: a["browser"] = nb
        if not play: return [a], ""
        ft = fix_typos(task); first = re.search(r"\b(?:first|1st|top)\b", ft[ft.lower().find(q.lower()) + len(q):], re.I)
        rest = ft[ft.lower().find(q.lower()) + len(q):]
        tm = re.search(r"\b(?:click|play|watch)\s+(?:on\s+)?(?:the\s+)?(?!(?:it|that|this|to|on|the|first|1st|top|song|video|one)\b)(.+?)" + _STOP_END, rest, re.I)
        target = tm.group(1).strip(" '\"") if tm else q
        return [a, {"action": "first_video"} if first else {"action": "first_video", "match": match_words(target)}], ""
    parts = [x for x in _SPLIT.split(task.strip()) if x and x.strip()]
    acts = []
    for i, part in enumerate(parts):
        got = match(part)
        if got is None and acts and acts[-1].get("url", "").startswith("https://www.youtube.com"):
            # "open youtube ... and search lofi"  -> search on YouTube
            m = re.match(r"^(?:search|look up|find|type)\s+(?:up\s+)?(?:for\s+)?(.+?)(?:\s+(?:on|in)\s+(?:youtube|it|there))?$",
                         re.sub(r"\s+(?:in|on|using)\s+(?:google chrome|chrome)$", "", _clean(part)))
            if m: got = [dict(acts[-1], url=_yt(m.group(1)))]
            else:  # "... and play/click <title>" after a YouTube search
                m = re.match(r"^(?:click|play|open|watch|tap)\s+(?:on\s+)?(?:the\s+)?(?!(?:very\s+)?(?:first|1st|top)\b)(.+?)(?:\s+(?:video|song|one))?$", _clean(part))
                if m and m.group(1) not in ("it", "that", "video", "one"): got = [{"action": "first_video", "match": m.group(1).strip(" '\"")}]
        if got is None:
            return acts, " and ".join(parts[i:])
        acts += got
    return acts, ""

FIRST_VIDEO_JS = r"""(function(){
 var sels=['ytd-rich-item-renderer a#video-title-link','ytd-video-renderer a#video-title','a#video-title-link','a#video-title',
           'ytd-rich-item-renderer a#thumbnail','ytd-video-renderer a#thumbnail','a[href^="/watch"]'];
 for(var i=0;i<sels.length;i++){var els=document.querySelectorAll(sels[i]);
  for(var j=0;j<els.length;j++){var e=els[j],r=e.getBoundingClientRect();
   if(r.width>0&&r.height>0&&e.href&&e.href.indexOf('/watch')>=0&&!e.closest('ytd-ad-slot-renderer')){
     var t=(e.getAttribute('title')||e.innerText||'').trim().slice(0,80); e.scrollIntoView({block:'center'});e.style.outline='3px solid #00ff66';e.style.outlineOffset='2px';e.style.boxShadow='0 0 18px #00ff66';var h=e.href;setTimeout(function(){window.location.href=h;},700); return 'ok|'+t;}}}
 return 'none';})()"""

PAGE_JS = "location.href+'\\n'+document.title"

def page_info(app=None, run=None):
    """(url, title) of the browser's front tab via AppleScript, or (None, None)."""
    import subprocess
    app = app or current_browser()
    if not app: return None, None
    try:
        out = browser_dom.run_js(app, PAGE_JS, run or subprocess.run) or ""
        url, _, title = out.partition("\n"); return url or None, title
    except Exception:
        return None, None

def goal_reached(task, url):
    """Cheap check that a browser goal is met (used to stop early)."""
    t, u = (task or "").lower(), url or ""
    if re.search(r"\b(first|1st|top)\b.*\b(video|result)\b|\bplay\b", t) and "youtube.com/watch" in u:
        return True
    return False
