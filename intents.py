"""Deterministic handling of common commands - no model needed, instant and reliable.
Also tracks the 'current browser' so URLs open in the app the user/agent is working in."""
import re, time
import browser_dom

STATE = {"browser": None, "app": None}  # persists across tasks/messages in this process

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
    try: front = (frontmost or browser_dom.frontmost_app)()
    except Exception: front = None
    if front in BROWSERS_SET:
        STATE["browser"] = front; return front
    if STATE["browser"]:
        return STATE["browser"]
    try:
        import extlink
        if extlink.LINK.connected(): return "Google Chrome"  # the extension is live -> work in Chrome
    except Exception: pass
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
    m = re.match(r"^(?:search|look up|find)\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)$", p) or \
        re.match(r"^youtube\s+search\s+(?:for\s+)?(.+)$", p)
    if m:
        import urllib.parse
        return [{"action": "open_url", "url": "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(m.group(1).strip(" '\""))}]
    m = re.match(r"^(?:search|google|look up)\s+(?:for\s+)?(.+?)(?:\s+on\s+(youtube|google))?$", p)
    if m and m.group(2) == "youtube":
        import urllib.parse
        return [{"action": "open_url", "url": "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(m.group(1))}]
    if re.match(r"^(?:click|open|play|watch|tap)\s+(?:on\s+)?(?:the\s+)?(?:very\s+)?(?:first|1st|top)\s+(?:youtube\s+)?(?:video|result|one)(?:\s+.*)?$", p):
        return [{"action": "first_video"}]
    return None

def plan(task):
    """Split a task into clauses. Returns (deterministic_actions, remaining_text or '')."""
    parts = [x for x in _SPLIT.split(task.strip()) if x and x.strip()]
    acts = []
    for i, part in enumerate(parts):
        got = match(part)
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
