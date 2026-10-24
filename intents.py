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
SITES = {"forbes": "https://www.forbes.com", "bloomberg": "https://www.bloomberg.com", "cnn": "https://www.cnn.com",
         "bbc": "https://www.bbc.com", "espn": "https://www.espn.com", "imdb": "https://www.imdb.com", "nytimes": "https://www.nytimes.com",
         "youtube": "https://www.youtube.com", "hulu": "https://www.hulu.com", "disney+": "https://www.disneyplus.com",
         "disney plus": "https://www.disneyplus.com", "twitch": "https://www.twitch.tv", "tiktok": "https://www.tiktok.com",
         "pinterest": "https://www.pinterest.com", "ebay": "https://www.ebay.com", "bing": "https://www.bing.com",
         "outlook": "https://outlook.live.com", "drive": "https://drive.google.com", "maps": "https://maps.google.com", "google": "https://www.google.com", "gmail": "https://mail.google.com",
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

GUESS_CHECK = True  # tests turn the network check off

def site_alive(url, timeout=4.0):
    import urllib.request
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status < 500
    except Exception as e:
        code = getattr(e, "code", None)
        return code is not None and code < 500  # 403/405 from bot protection still means the site exists

import functools
@functools.lru_cache(maxsize=64)
def guess_site(name):
    """Unknown site name -> https://www.<name>.com if it answers, else Google's first result for the name."""
    import urllib.parse
    url = f"https://www.{name}.com"
    if not GUESS_CHECK or site_alive(url): return url
    return "https://www.google.com/search?btnI=1&q=" + urllib.parse.quote_plus(name)

def is_plain_open(task):
    """'open hulu in the browser' - a task that is finished as soon as the site is open."""
    acts, rest = plan(task)
    return not rest and len(acts) == 1 and acts[0]["action"] == "open_url" and "/search" not in acts[0]["url"] and "/results" not in acts[0]["url"]

def match(part):
    """Return a list of actions for one clause, or None."""
    p = _clean(part)
    m = re.match(r"^(?:open|launch|start|switch to)\s+(?:the\s+)?(?:app\s+)?(.+?)(?:\s+app)?$", p)
    if m and m.group(1) in APP_NAMES:
        return [{"action": "open_app", "app": APP_NAMES[m.group(1)]}]
    m = re.match(r"^(?:open(?: up)?|go to|visit|navigate to|load|bring up|search for|show me|take me to|go on)\s+(?:the\s+)?(?:website\s+)?"
                 r"([a-z0-9.\-]+?)(?:\s+(?:website|site|homepage|home page|page|\.com))?(?:\s+(?:in|on|using|with)\s+(?:the\s+|my\s+|a\s+)?(?:web\s+)?([a-z ]+?))?$", p)
    if m:
        name, br = m.group(1), m.group(2)
        browser = BROWSER_NAMES.get(br.strip()) if br else None
        webby = bool(br and (browser or br.strip() in ("browser", "internet", "web"))) or bool(re.match(r"^(?:go to|visit|navigate to|take me to|go on)\b", p)) \
            or bool(re.search(r"\b(?:website|site|homepage|home page)\b", p))
        url = SITES.get(name.replace(".com", "")) or (("https://" + name) if re.match(r"^[a-z0-9\-]+\.[a-z.]{2,}$", name) else None)
        if not url and webby and name not in APP_NAMES and re.match(r"^[a-z0-9\-]{2,40}$", name):
            url = guess_site(name)  # "open hulu in the browser" -> https://www.hulu.com (verified) or a lucky Google hit
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
    t = fix_typos(task or "")
    return bool(WEB_RE.search(t)) or (output_request(t) is not None and bool(RESEARCH_RE.search(t)))

OUTPUT_RE = re.compile(r"(?:,?\s*(?:and|then)\s+)?(?:(?:summari[sz]e|sumarize|summrize|summerize)\s+(?:it|them|that|this)?\s*(?:and\s+)?)?"
                       r"(?:put|save|write|make|create|export|turn|place|store|add|type)\s+(?:it|them|that|this|the (?:results?|list|data|info(?:rmation)?)|everything|a)?\s*"
                       r"(?:in|into|to|as|on)?\s*(?:a|an|the|my|new)?\s*"
                       r"(word\s*(?:doc(?:ument)?|file)?|docx|document|doc|excel(?:\s+(?:file|sheet|spreadsheet))?|spreadsheet|sheet|xlsx|csv|"
                       r"text\s*file|txt|notes?\s*(?:file)?|notepad)\b(?:\s+(?:called|named)\s+['\"]?([\w \-]+?)['\"]?)?\s*[.!]*$", re.I)
RESEARCH_RE = re.compile(r"\b(look(?:s|ing)? (?:for|up)|find|search|research|get|top \d+|list|richest|best|latest|news|prices?|open(?: up)?|go to|from)\b", re.I)

def output_request(task):
    """'... and summarize and put it in a word document' -> {"kind": "docx", "name": None, "research": "<the rest>", "summary": True}."""
    t = fix_typos(task or "").strip()
    first = _output_first(t)
    if first: return first
    m = OUTPUT_RE.search(t)
    if not m: return None
    word = m.group(1).lower()
    kind = "docx" if re.match(r"word|docx|document|doc$", word) else "xlsx" if re.match(r"excel|spreadsheet|sheet|xlsx|csv", word) else "txt"
    research = t[:m.start()].strip(" ,.")
    research = re.sub(r"(?:,?\s*(?:and|then)\s+)?(?:summari[sz]e|summrize|summerize|sumarize)(?:\s+(?:it|them|that|this))?\s*$", "", research, flags=re.I).strip(" ,.")
    if not research: return None
    if re.match(_LEAD + r"(?:open|launch|start|use)\s+(?:up\s+)?(?:microsoft\s+)?[\w ]{1,20}$", research, re.I) and not FACTS_RE.search(research):
        return None  # "open excel and create a new sheet": nothing to research
    return {"kind": kind, "name": (m.group(2) or "").strip() or None, "research": research,
            "summary": bool(re.search(r"summ?[ae]?r", t[m.start() - 30 if m.start() > 30 else 0:], re.I)) or True}

FACTS_RE = re.compile(r"\b(top \d+|richest|poorest|latest|newest|news|best|worst|tallest|biggest|largest|smallest|fastest|most|price|prices|"
                      r"cost|weather|population|statistics|stats|ranking|rankings|current|today|this year|20\d\d|who|what|when|where|"
                      r"summary of|information|info|facts|data|list of|history of|reviews?|specs|schedule|scores?|results)\b", re.I)

APP_KIND = [(r"powerpoint|pptx?|slides|keynote|presentation|deck", "pptx"),
            (r"excel|google sheets|sheets|numbers|spreadsheet|xlsx|csv", "xlsx"),
            (r"word|google docs|docs|pages|document|docx|doc", "docx"),
            (r"notepad|textedit|text ?edit|text file|notes?|txt", "txt")]
_VERIFY = re.compile(r"[.,;]?\s*(?:and\s+)?(?:please\s+)?(?:verify|double[- ]check|check|confirm|make sure)\b.*$", re.I)
_LEAD = r"^(?:(?:hey|ok|okay|please|can you|could you|would you|will you|pls)\s+)*"

def _kind(word):
    w = word.lower()
    return next(k for pat, k in APP_KIND if re.search(pat, w))

def _output_first(t):
    """'Open Excel, create a new sheet, and list the top 20 richest people ... Verify ...' /
    'make an excel spreadsheet of the top 10 laptops' -> output request."""
    s = _VERIFY.sub("", t).strip(" .")
    m = re.match(_LEAD + r"(?:open|launch|start|use|go to|go into)\s+(?:up\s+)?(?:microsoft\s+|ms\s+)?"
                 r"(excel|word|powerpoint|notepad|google sheets|sheets|google docs|google slides|keynote|numbers|pages|textedit|text ?edit)\b\s*[,.]?\s*(?:and\s+|then\s+)?(.*)$", s, re.I)
    if m:
        kind, rest = _kind(m.group(1)), m.group(2)
        rest = re.sub(r"^(?:(?:and|then)\s+)?(?:create|make|start|open|add)\s+(?:a\s+|an\s+)?(?:new\s+|blank\s+|empty\s+)?"
                      r"(?:sheet|spreadsheet|workbook|document|doc|file|page|note|table|list)\b\s*[,.]?\s*(?:and\s+|then\s+)?", "", rest.strip(), flags=re.I)
        rest = re.sub(r"^(?:in it|there|in there)\s*[,.]?\s*(?:and\s+)?", "", rest, flags=re.I).strip(" ,.")
        if rest and FACTS_RE.search(rest):  # content needs facts from the web (not dictation like "type hello")
            return {"kind": kind, "name": None, "research": rest, "summary": True}
        return None
    m = re.match(_LEAD + r"(?:create|make|build|write|prepare|give me)\s+(?:me\s+)?(?:a|an)\s+(?:new\s+)?"
                 r"((?:excel|word|google)?\s*(?:spreadsheet|sheet|workbook|document|doc|text file|notes? file|table))\s+"
                 r"(?:of|with|listing|that lists|about|containing|on|for)\s+(.+)$", s, re.I)
    if m and FACTS_RE.search(m.group(2)):
        word = m.group(1)
        kind = "xlsx" if re.search(r"excel|spreadsheet|sheet|workbook|table", word, re.I) else _kind(word)
        return {"kind": kind, "name": None, "research": m.group(2).strip(" ."), "summary": True}
    return None

def research_query(text):
    """'can you open up forbes and looks for the top 20 richest people' -> ('forbes', 'forbes top 20 richest people')."""
    t = re.sub(r"^(?:(?:hey|ok|okay|please|can you|could you|would you|will you|pls)\s+)+", "", fix_typos(text).strip(), flags=re.I)
    site = None
    m = re.match(r"^(?:open(?: up)?|go (?:to|on)|visit|use|check)\s+(?:the\s+)?([a-z0-9.\-]+?)(?:\.com)?(?:\s+(?:website|site))?\s*(?:,|and|then)\s*(.+)$", t, re.I)
    if m and (m.group(1).lower() in SITES or "." in m.group(1)):
        site, t = m.group(1).lower(), m.group(2)
    t = re.sub(r"^(?:(?:please|can you|could you)\s+)?(?:look(?:s|ing)?\s+(?:for|up)|search(?:\s+for)?|find|get|research|check|list|make|write|show|put|type|add)\s+(?:out\s+)?(?:the\s+)?", "", t, flags=re.I)
    q = (site + " " if site else "") + t.strip(" .?")
    return site, q

WORDNUM = {"three": 3, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25, "thirty": 30, "fifty": 50, "hundred": 100}

def requested_count(text):
    w = re.search(r"\b(?:top|the)\s+(twenty five|three|five|ten|fifteen|twenty|thirty|fifty|hundred)\b", text or "", re.I)
    if w: return WORDNUM[w.group(1).lower()]
    m = re.search(r"\btop\s+(\d{1,3})\b|\b(\d{1,3})\s+(?:richest|best|biggest|largest|top)\b", text or "", re.I)
    return int(m.group(1) or m.group(2)) if m else None

TYPOS = {"linkden": "linkedin", "linkdin": "linkedin", "linkedn": "linkedin", "linkeden": "linkedin", "instagarm": "instagram", "instgram": "instagram", "insta": "instagram", "agian": "again", "artcile": "article", "amry": "army", "musiuc": "music", "musci": "music", "muisc": "music", "msuic": "music", "musik": "music", "spotfy": "spotify", "sptify": "spotify", "spoitfy": "spotify", "claick": "click", "clcik": "click", "clik": "click", "cilck": "click", "clikc": "click", "cick": "click", "clck": "click",
         "serach": "search", "seach": "search", "saerch": "search", "searh": "search", "sreach": "search", "serch": "search",
         "youtueb": "youtube", "yotube": "youtube", "youtub": "youtube", "yt": "youtube", "youube": "youtube", "you tube": "youtube",
         "plya": "play", "paly": "play", "pley": "play", "opne": "open", "oepn": "open", "vidoe": "video", "vedio": "video",
         "exacel": "excel", "exel": "excel", "excell": "excel", "exccel": "excel", "ecxel": "excel", "excle": "excel", "exce": "excel",
         "hseet": "sheet", "sheeet": "sheet", "shet": "sheet", "sheat": "sheet", "spreadshet": "spreadsheet", "spredsheet": "spreadsheet",
         "wrod": "word", "wrd": "word", "wordd": "word", "docuemnt": "document", "documnet": "document", "dcoument": "document",
         "pwerpoint": "powerpoint", "powerpiont": "powerpoint", "powerpont": "powerpoint", "power point": "powerpoint", "power-point": "powerpoint",
         "powepoint": "powerpoint", "ppoint": "powerpoint", "presentaion": "presentation", "presntation": "presentation", "addtion": "addition",
         "make make": "make", "reprot": "report", "raport": "report"}

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
        q = strip_filler(m.group(1).strip()) or m.group(1).strip(); return (q, True) if q and q.lower() not in ("youtube", "it") else None
    q = strip_filler(m.group(1).strip(" '\"")) or m.group(1).strip(" '\"")
    if not q or q.lower() in ("youtube", "it", "something"): return None
    after = t[m.end():]
    return q, bool(_PLAY.search(after) or re.search(r"\b(?:play|listen to|watch)\b", t[:m.start()], re.I))

QUESTION = re.compile(r"\b(who|what|whats|when|where|which|why|how (?:many|much|old|tall|long|far|big|do|does|to)|is it|are there|"
                      r"top \d+|richest|tallest|biggest|largest|best|price of|cost of|weather|population|capital of|score|news)\b|\?\s*$", re.I)

def is_question(task):
    return bool(QUESTION.search(task or ""))

def google_request(task):
    """'can you go to google and search for X' / 'google X' / 'search the web for X' -> X (the user's own words), else None."""
    t = fix_typos(task or "").strip()
    if re.search(r"\byoutube\b", t, re.I): return None
    t = re.sub(r"^(?:(?:hey|ok|okay|please|can you|could you|would you|will you|now|just|pls)\s+)+", "", t, flags=re.I)
    t = re.sub(r"\s+(?:in|on|using)\s+(?:google\s+)?chrome\s*$", "", t, flags=re.I)
    pats = [r"^(?:go to|open(?: up)?|visit|use)\s+google(?:\.com)?\s*(?:,|and|then|and then)\s*(?:(?:please|can you|could you)\s+)?(?:search|look up|find|google)\s+(?:up\s+)?(?:for\s+)?(.+)$",
            r"^(?:search|look up|find)\s+(?:on\s+)?(?:google|the web|the internet|online)\s+(?:for\s+)?(.+)$",
            r"^(?:search|look up)\s+(?:for\s+)?(.+?)\s+(?:on|in|using)\s+(?:google|the web|the internet)$",
            r"^google\s+(?:for\s+)?(.+)$"]
    for p in pats:
        m = re.match(p, t, re.I)
        if m:
            q = m.group(1).strip(" .'\"?!")
            q = re.sub(r"\s+(?:on|in|using)\s+google$", "", q, flags=re.I)
            return q or None
    return None

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
    gq = google_request(task)
    if gq:  # deterministic Google search; questions are then answered from the results page
        import urllib.parse
        a = {"action": "open_url", "url": "https://www.google.com/search?q=" + urllib.parse.quote_plus(gq)}
        return [a] + ([{"action": "answer_from_page", "question": task}] if is_question(task) else []), ""
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

def media_target(task):
    """The thing a play/watch/listen task names ('' for 'play the first video' / 'play it')."""
    t = fix_typos(task or "")
    if re.search(r"\b(first|1st|top)\b\s+(?:video|result|one|song)", t, re.I): return ""
    m = re.search(r"\b(?:play|watch|listen to|put on|find|search(?: for)?|look up)\b(.*)$", t, re.I)
    return strip_filler(m.group(1)) if m else ""

def goal_reached(task, url, title=None):
    """Cheap check that a browser goal is met (used to stop early). A named song/video must match the page title."""
    t, u = (task or "").lower(), url or ""
    if re.search(r"\b(first|1st|top)\b.*\b(video|result)\b|\bplay\b", t) and "youtube.com/watch" in u:
        want = media_target(task)
        if not want or title is None: return not want
        return title_match(want, title) >= 0.99
    return False

def goal_check(task, snap):
    """(ok, why) before accepting 'done': a play/watch task must be on a video whose title matches what was asked."""
    t = (task or "").lower()
    if not re.search(r"\b(play|watch|listen)\b", t): return True, ""
    want = media_target(task); url, title = (snap or {}).get("url") or "", (snap or {}).get("title") or ""
    if not re.search(r"youtube\.com/watch|open\.spotify\.com/(track|album|playlist)|/watch|/video", url):
        return False, "nothing is playing yet: open the matching video/song first"
    if want and title_match(want, title) < 0.99:
        return False, f"the page title \"{title[:80]}\" doesn't match \"{want}\": find the right one (search, then pick the result whose title has every word)"
    return True, ""


SEARCH_HOSTS = re.compile(r"(^|\.)(google\.[a-z.]+|youtube\.com|bing\.com|duckduckgo\.com)$")

def safe_url(url, known=()):
    """Never open invented deep links: homepages, search URLs and links seen on the page are fine;
    anything else becomes a Google site search."""
    import urllib.parse
    u = urllib.parse.urlparse(url if re.match(r"^[a-z]+://", url or "", re.I) else "https://" + (url or ""))
    host = u.netloc.lower()
    if not host: return url
    path = (u.path or "/").rstrip("/")
    if not path or SEARCH_HOSTS.search(host.split(":")[0]) and (path in ("/search", "/results") or path == ""): return url
    if SEARCH_HOSTS.search(host): return url
    norm = lambda x: re.sub(r"^https?://(www\.)?", "", (x or "").split("#")[0]).rstrip("/").lower()
    if any(norm(k) == norm(url) or (norm(k) and norm(url).startswith(norm(k)) and len(norm(k).split("/")) > 1) for k in known if k):
        return url
    words = " ".join(w for w in re.split(r"[/\-_.?=&]+", path + " " + (u.query or "")) if w and not w.isdigit())
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"site:{re.sub(r'^www[.]', '', host)} {words}".strip())

# ---------------- 2.0.1: filler-free queries for every intent ----------------
_KIND = r"(?:songs?|videos?|music videos?|tracks?|tunes?|clips?|music|album|playlist|podcast|episode|movie|trailer)"
_FILLER_LEAD = [
    r"(?:hey|hi|ok|okay|so|um|uh|yo|please|pls|plz|kindly|just|now)\b[\s,]*",
    r"(?:can|could|would|will) (?:you|u)\b(?:\s+please)?\s*",
    r"(?:i (?:want|wanna|would like|'d like|need) (?:you )?to|i want|i wanna|i'd like|let me|let's|lets)\s+",
    r"(?:go|head)\s+(?:on|to|onto)\s+(?:youtube|spotify|the web)\s+(?:and\s+)?",
    r"(?:open(?: up)?|use)\s+(?:youtube|spotify)\s+(?:and\s+)?",
    r"(?:search|look|find|play|put on|listen to|watch|queue|look up|search up|pull up|bring up|show)(?:\s+(?:up|for))?\s+",
    r"(?:me|us|for me)\s+",
    r"(?:a|an|the|some|something|that|this)\s+",
    _KIND + r"\s+",
    r"(?:by the name of|named|called|titled|with the (?:name|title)|of|about|that goes|which is|that is)\s+",
]
_TRAIL = [r"[\s,]+(?:on|in|from|using|via)\s+(?:youtube|spotify|google|chrome|the web)\b.*$", r"[\s,]+(?:for me|please|pls|thanks|thank you|now|right now|again)\s*$",
          r"[\s,]+(?:and|then)\s+(?:play|click|watch|open|start)\b.*$"]

def strip_filler(q):
    """'can you go on youtube and find me a song by the name of Frog' -> 'Frog'; 'the song of frog by ptasinski' -> 'frog by ptasinski'.
    Keeps the user's own words (and casing) for the title/artist; never returns empty."""
    orig = s = re.sub(r"\s+", " ", (q or "").strip(" .!?'\""))
    for _ in range(12):
        before = s
        for p in _FILLER_LEAD: s = re.sub(r"^" + p, "", s, flags=re.I)
        for p in _TRAIL: s = re.sub(p, "", s, flags=re.I)
        s = s.strip(" ,.!?'\"")
        if s == before: break
    if not s or re.fullmatch(_KIND + r"|it|that|this|that one|this one|one", s, re.I): return "" if re.fullmatch(r"(?:" + _KIND + r"|it|that|this|that one|this one|one)?", s, re.I) else orig
    return s

def query_tokens(q):
    """Significant tokens of a media query (title + artist): 'frog by ptasinski' -> ['frog', 'ptasinski']."""
    stop = {"by", "the", "a", "an", "of", "and", "ft", "feat", "featuring", "official", "song", "video", "music", "audio", "lyrics", "with", "to", "in", "on"}
    return [w for w in re.findall(r"[\w']+", (q or "").lower()) if w not in stop]

def title_match(query, title):
    """Share of the query's significant tokens found in a title (fuzzy per token: 'ptasinski' ~ 'ptasiński')."""
    import difflib, unicodedata
    def fold(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    toks = query_tokens(fold(query)); words = re.findall(r"[\w']+", fold(title))
    if not toks: return 0.0
    hit = sum(1 for t in toks if t in words or any(difflib.SequenceMatcher(None, t, w).ratio() >= 0.85 for w in words if abs(len(w) - len(t)) <= 2))
    return hit / len(toks)

MIX_RE = re.compile(r"\b(mix|radio|playlist|full album|compilation|1 hour|10 hours|hours? loop|nonstop)\b|^Mix\s*-", re.I)
