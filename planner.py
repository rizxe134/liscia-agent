"""Task planner: one fast call to the local text model turns ANY request into a structured plan, then code validates it.
Regex fast paths (intents.py) are used as hints and as the fallback when the model's answer is unusable."""
import datetime, json, re
import intents

INTENTS = ("web_answer", "open_site", "media_play", "web_research_to_files", "web_interact", "desktop_app")
FILE_KINDS = ("docx", "xlsx", "pptx", "txt")

SCHEMA = {"type": "object", "properties": {
    "intent": {"type": "string", "enum": list(INTENTS)},
    "query": {"type": "string"}, "site": {"type": "string"},
    "outputs": {"type": "array", "items": {"type": "string", "enum": list(FILE_KINDS)}},
    "columns": {"type": "array", "items": {"type": "string"}},
    "count": {"type": "integer"}, "title": {"type": "string"}, "app": {"type": "string"}},
    "required": ["intent", "query", "outputs"]}

PROMPT = """You route requests for a computer assistant. Today is {today}. Reply with JSON only.
intent:
 web_answer = a question answered by searching the web (facts, news, prices, "who/what/how many").
 open_site = just open a website.
 media_play = search/play a video or song (YouTube).
 web_research_to_files = find information online AND save it to a file: Word/document -> "docx", Excel/sheet/spreadsheet/table -> "xlsx", PowerPoint/slides/presentation/deck -> "pptx", Notepad/text file/notes -> "txt" (several allowed).
 web_interact = do something on a website (click, log in, fill a form, scroll, add to cart).
 desktop = operate a local app with no web content (calculator, settings, files, music player).
query = the search words (no filler; add {year} if the request says recent/latest/current/now). site = website name if one is named, else "".
columns = table columns the user asked for; count = how many items ("top 10" -> 10), else 0; title = short document title.
Examples:
"open youtube and play lofi" -> {{"intent":"media_play","query":"lofi","outputs":[]}}
"who won the last world cup" -> {{"intent":"web_answer","query":"who won the last world cup","outputs":[]}}
"go to netflix" -> {{"intent":"open_site","query":"","site":"netflix","outputs":[]}}
"make a word doc and a spreadsheet of the 5 biggest companies" -> {{"intent":"web_research_to_files","query":"5 biggest companies {year}","outputs":["docx","xlsx"],"count":5,"title":"5 Biggest Companies"}}
"open calculator and add 2+2" -> {{"intent":"desktop_app","app":"Calculator","query":"","outputs":[]}}
"launch photoshop" -> {{"intent":"desktop_app","app":"Photoshop","query":"","outputs":[]}}
"go on the page and look for jazz albums" -> {{"intent":"web_interact","query":"jazz albums","outputs":[]}}
(No Word/Excel/document/sheet/text file mentioned -> never web_research_to_files.)"""

WORD_RE = re.compile(r"\b(word(?!\s+(?:for|by|of)\b)|docx|document|doc|google docs|pages)\b", re.I)
XLSX_RE = re.compile(r"\b(excel|spread ?sheets?|sheets?|xlsx|csv|workbook|google sheets|numbers app)\b", re.I)
PPTX_RE = re.compile(r"\b(powerpoint|pptx?|slides?|slide ?deck|deck|presentation|keynote|google slides)\b", re.I)
TXT_RE = re.compile(r"\b(notepad|text ?file|txt|notes? file|textedit)\b", re.I)
DESKTOP_APP_RE = re.compile(r"\b(calculator|calc|settings|control panel|file explorer|explorer|finder|paint|photos|camera|clock|alarm|"
                            r"spotify app|music app|terminal|task manager|volume|brightness|bluetooth|wi-?fi|screenshot|recycle bin|trash|desktop)\b", re.I)
WEBBY_RE = re.compile(r"\b(google|search|web|online|internet|website|site|browser|chrome|youtube|look up|find out|research|"
                      r"reports?|rankings?|sources?|news|latest|recent|current|top \d+|most|best|richest|biggest|largest|who|what|which|how many)\b", re.I)
RECENT_RE = re.compile(r"\b(recent|latest|current|currently|now|today|this year|up[- ]to[- ]date|newest)\b", re.I)

def today():
    return datetime.date.today()

def file_outputs(task):
    t = intents.fix_typos(task or "")
    out = []
    if WORD_RE.search(t): out.append("docx")
    if XLSX_RE.search(t): out.append("xlsx")
    if PPTX_RE.search(t): out.append("pptx")
    if TXT_RE.search(t): out.append("txt")
    return out

def with_year(q, task):
    y = str(today().year)
    if q and RECENT_RE.search(task or "") and not re.search(r"\b20\d\d\b", q): return f"{q} {y}"
    return q

def needs_facts(task):
    return bool(intents.FACTS_RE.search(task or "")) or bool(WEBBY_RE.search(task or ""))

def clean_query(task):
    """Fallback search words from free text."""
    t = intents.fix_typos(task or "")
    t = re.sub(intents._LEAD, "", t.strip(), flags=re.I)
    t = re.sub(r"\b(?:create|make|build|write|prepare|open|generate|produce)\s+(?:me\s+)?(?:a|an|the)?\s*(?:new\s+)?(?:microsoft\s+)?"
               r"(?:word|excel|notepad)?\s*(?:documents?|docs?|sheets?|spreadsheets?|workbooks?|files?|notes?|tables?)?\b", " ", t, flags=re.I)
    t = re.sub(r"\b(?:and|&)\s+(?:a|an)\s+(?:excel|word)?\s*(?:sheet|spreadsheet|document|doc|file)\b", " ", t, flags=re.I)
    t = re.sub(r"\b(?:put|save|export|store)\s+(?:it|them|that|this|everything)\s+(?:in|into|to|as)\s+.*$", " ", t, flags=re.I)
    t = re.sub(r"[.,;]?\s*(?:and\s+)?(?:please\s+)?(?:verify|double[- ]check|make sure|confirm)\b.*$", " ", t, flags=re.I)
    t = re.sub(r"\s*,?\s*(?:based on|according to|using|from)\s+(?:the\s+)?(?:most\s+)?(?:recent|latest|current|reliable|official|up[- ]to[- ]date)?\s*"
               r"(?:rankings?|reports?|sources?|data|lists?|statistics)\b(?:\s+(?:or|and)\s+\w+)?.*$", " ", t, flags=re.I)
    t = re.sub(r"\b(?:listing|list(?:ing)? of|that lists?|list|with|containing|about|of|for|summari[sz]e|summary of|showing|based on)\b\s*", " ", t, count=0, flags=re.I) \
        if re.match(r"^\s*(?:listing|list|with|containing|about|of|for|showing)\b", t.strip(), re.I) else t
    t = re.sub(r"^\s*(?:listing|list|with|containing|about|of|for|showing|and|the)\s+", "", t.strip(), flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .,?!")
    return t

INSTR_RE = re.compile(
    r"\b(?:(?:then|and|also|as well as|plus|with)\s+)*(?:(?:can|could|would|will)\s+you\s+|please\s+)?"
    r"(?:open|launch|start|use|look up|lookup|search(?: for)?|find(?: out)?|google|make|create|build|write|prepare|generate|produce|put|save|export|add|do|give me)\s+"
    r"(?:me\s+|up\s+|it\s+|them\s+|that\s+|this\s+)?(?:a\s+|an\s+|the\s+|my\s+|some\s+)?(?:new\s+|blank\s+|small\s+|short\s+|full\s+|fuller\s+|quick\s+)*"
    r"(?:(?:microsoft|ms|google)\s+)?(?:excel|word|powerpoint|notepad|sheets?|spreadsheets?|workbooks?|documents?|docs?|reports?|lists?|tables?|files?|"
    r"presentations?|decks?|slides?|summary|summaries)?\b"
    r"|\b(?:in|into|on|to|as|of)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+|small\s+)?(?:(?:microsoft|ms)\s+)?(?:excel|word|powerpoint|notepad)\s*(?:sheets?|spreadsheets?|documents?|docs?|files?|presentations?|decks?|slides?)?\b"
    r"|\b(?:excel|word|powerpoint)\s+(?:sheets?|spreadsheets?|documents?|docs?|files?|presentations?|decks?)\b"
    r"|\b(?:with\s+)?(?:an?\s+)?addition\s+of\b|\bas well as\b|\b(?:a\s+)?(?:report|list|presentation)\s+(?:on|of|about)\b"
    r"|\b(?:(?:a|an)\s+)?(?:small\s+|short\s+|quick\s+)?(?:excel|word|powerpoint|notepad|pptx?|docx|xlsx)\b(?:\s+(?:of|about|on)\s+(?:it|them|that|this))?"
    r"|\bwhat\s+(?:the\s+)?(?=(?:top|best|most|\d))|\b(?:are|is)\s+then\b|\bthen\b", re.I)

def strip_instructions(q):
    """'can you look up what the top 10 fastest cars are then make a list on excel sheet ...' -> 'top 10 fastest cars'."""
    q = intents.fix_typos(q or "")
    q = re.sub(r"\s*,?\s*(?:based on|according to)\s+(?:the\s+)?(?:most\s+)?(?:recent|latest|current|reliable|official)?\s*(?:rankings?|reports?|sources?|data|lists?)\b(?:\s+(?:or|and)\s+\w+)?", " ", q, flags=re.I)
    q = re.sub(_LEAD_RE, "", q.strip())
    prev = None
    while prev != q:
        prev = q; q = INSTR_RE.sub(" ", q)
    q = re.sub(r"\s*[.,;]+\s*", " ", q)
    q = re.sub(r"\b(?:are|is)\s*$", "", re.sub(r"\s+", " ", q).strip(" .,;?!"), flags=re.I)
    q = re.sub(r"^(?:(?:and|of|the|about|listing|list|on|a|an|it|them)\s+)+", "", q, flags=re.I)
    q = re.sub(r"\s+(?:and|of|on|a|an|it|them|with|in|to|plus)$", "", q, flags=re.I)
    q = re.sub(r"\s*[.,;]+\s*", " ", q)
    q = re.sub(r"\s+(?:and|of|on|a|an|it|them|with|in|to|plus)$", "", q.strip(), flags=re.I)
    return re.sub(r"\s+", " ", q).strip(" .,;?!")

_LEAD_RE = re.compile(r"^(?:(?:hey|hi|ok|okay|please|so|can you|could you|would you|will you|pls|i need you to|i want you to)\s+)+", re.I)

def verbatim(task, q):
    """Return the span of the ORIGINAL task text that the (possibly spell-corrected) query refers to.
    'play gettin money' + model query 'getting money' -> 'gettin money'."""
    import difflib
    q = str(q or "").strip(); raw = task or ""
    if not q or q.lower() in raw.lower(): return q
    words = re.findall(r"\S+", raw); n = len(q.split())
    best, bs = q, 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(0, len(words) - size) + 1):
            cand = " ".join(words[i:i + size]).strip(" .,!?\"'")
            r = difflib.SequenceMatcher(None, cand.lower(), q.lower()).ratio()
            if r > bs: best, bs = cand, r
    return best if bs >= 0.75 else q

def rule_plan(task):
    """Plan from code only (fast path, and fallback if the model fails). 'sure' = unambiguous, no model call needed."""
    p = _rule_plan(task); return p

APP_OPEN_RE = re.compile(r"^(?:(?:hey|ok|okay|please|so|can you|could you|would you|will you|pls|i want to|i need to)\s+)*"
                         r"(?:open|launch|start|run|use|switch to|bring up|fire up|load)\s+(?:up\s+)?(?:the\s+|my\s+)?(?:app\s+|application\s+|program\s+)?"
                         r"([\w.+#'&-]+(?:\s+(?!and\b|then\b|to\b|on\b|in\b|app\b|application\b|program\b|for\b|with\b)[\w.+#'&-]+){0,3}?)"
                         r"(?:\s+(?:app|application|program))?\s*(?:$|[,.;]|\s+(?:and|then|to|on|in|for|with)\b)", re.I)

def target_app(task):
    """'open notepad and type hello' -> 'notepad'; None for websites/browsers/files."""
    t = intents.fix_typos(task or "").strip()
    m = APP_OPEN_RE.match(t)
    if not m: return None
    name = m.group(1).strip(" .,'")
    low = name.lower()
    if re.search(r"\.(com|org|net|io|tv|co|gov|edu)\b|https?:|www\.", low): return None
    if low in ("it", "that", "this", "them", "a", "an", "new", "google", "youtube", "a new tab", "tab", "website", "site") or low.startswith(("a ", "the web")): return None
    if low in intents.SITES and low not in ("spotify", "slack", "discord", "zoom", "teams", "whatsapp", "notion", "steam"): return None
    if intents.named_browser(low) or low in ("browser", "chrome", "safari", "firefox", "edge", "google chrome"): return None
    return name

def _rule_plan(task):
    t = intents.fix_typos(task or "")
    outs = file_outputs(t)
    o = intents.output_request(t)
    if o and o["kind"] not in outs: outs.append(o["kind"])
    count = intents.requested_count(t) or 0
    if outs and needs_facts(t):
        q = intents.research_query(o["research"])[1] if o else clean_query(t)
        site = (intents.research_query(o["research"])[0] if o else None) or ""
        return {"intent": "web_research_to_files", "query": with_year(q, t), "site": site, "outputs": outs, "count": count, "columns": [], "title": "", "sure": bool(o)}
    yt = intents.youtube_request(t)
    if not yt:
        m = re.match(r"^\s*(?:on\s+)?youtube\s+(?!and\b|then\b)(.+)$", t, re.I) or re.match(r"^\s*(?:put on|listen to)\s+(?:some\s+)?(.+?)\s+on\s+youtube\s*$", t, re.I)
        if m: yt = (m.group(1).strip(" .?!"),)
    if yt: return {"intent": "media_play", "query": yt[0], "site": "youtube", "outputs": [], "count": 0, "sure": True}
    acts, rest = intents.plan(t)
    if acts and not rest and all(a["action"] in ("open_url", "first_video", "answer_from_page") for a in acts):
        if any(a["action"] == "first_video" for a in acts) or "youtube.com/results" in acts[0].get("url", ""):
            return {"intent": "media_play", "query": "", "site": "youtube", "outputs": [], "count": 0, "sure": True}
        if "/search" in acts[0]["url"]:
            return {"intent": "web_answer" if intents.is_question(t) or any(a["action"] == "answer_from_page" for a in acts) or re.search(r"\b(google|search)\b", t, re.I) else "web_interact", "query": intents.google_request(t) or "", "site": "", "outputs": [], "count": count, "sure": True}
        return {"intent": "open_site", "query": "", "site": acts[0]["url"], "outputs": [], "count": 0, "sure": True}
    if acts and not rest:  # fully deterministic (e.g. "open safari and open youtube and click the first video")
        browser = any(a["action"] == "open_app" and a["app"] in intents.BROWSERS_SET for a in acts) or any(a["action"] != "open_app" for a in acts)
        apps = [a["app"] for a in acts if a["action"] == "open_app" and a["app"] not in intents.BROWSERS_SET]
        return {"intent": "web_interact" if browser else "desktop_app", "app": apps[0] if apps and not browser else "", "query": "", "site": "", "outputs": [], "count": 0, "sure": True}
    app = target_app(t)
    if app and not re.search(r"\byoutube\b", t, re.I):
        sure = bool(re.match(r"^\W*(?:\w+\W+){0,2}" + re.escape(app) + r"(\s+app)?\W*$", re.sub(_LEAD_RE, "", t), re.I))  # just "open X"
        return {"intent": "desktop_app", "app": app, "query": "", "site": "", "outputs": [], "count": 0, "sure": sure}
    if acts and acts[0]["action"] == "open_app" and acts[0]["app"] not in intents.BROWSERS_SET and not WEBBY_RE.search(rest or ""):
        return {"intent": "desktop_app", "app": acts[0]["app"], "query": "", "site": "", "outputs": [], "count": 0}
    if DESKTOP_APP_RE.search(t) and not WEBBY_RE.search(t) and not intents.is_web_task(t):
        return {"intent": "desktop_app", "query": "", "site": "", "outputs": [], "count": 0}
    if intents.is_question(t):
        return {"intent": "web_answer", "query": with_year(intents.google_request(t) or clean_query(t), t), "site": "", "outputs": [], "count": count}
    if intents.is_web_task(t) or WEBBY_RE.search(t):
        return {"intent": "web_interact", "query": "", "site": "", "outputs": [], "count": count}
    return {"intent": "desktop_app", "query": "", "site": "", "outputs": [], "count": 0}

def validate(p, task):
    """Code rules that override the model where the text is unambiguous."""
    t = intents.fix_typos(task or "")
    rule = rule_plan(t)
    if not isinstance(p, dict) or p.get("intent") not in INTENTS: return dict(rule, source="rules")
    p = dict(p)
    outs = [o for o in (p.get("outputs") or []) if o in FILE_KINDS]
    text_outs = file_outputs(t) or (rule["outputs"] if rule["intent"] == "web_research_to_files" else [])
    # files: only kinds the user actually mentioned; mentioned files + factual content => research_to_files
    outs = [o for o in outs if o in text_outs] or (text_outs if p["intent"] == "web_research_to_files" else [])
    if text_outs and needs_facts(t):
        p["intent"] = "web_research_to_files"; outs = list(dict.fromkeys(outs + text_outs))
    if p["intent"] == "web_research_to_files" and not outs:
        p["intent"] = rule["intent"] if rule["intent"] not in ("web_research_to_files", "desktop_app") else "web_answer"
    p["outputs"] = outs if p["intent"] == "web_research_to_files" else []
    # strong regex hints win for media / plain open / desktop-only
    if rule["intent"] in ("media_play", "open_site") and p["intent"] not in ("web_research_to_files",):
        p = dict(p, intent=rule["intent"], site=rule.get("site") or p.get("site", ""), query=rule.get("query") or p.get("query", ""))
    if p["intent"] == "desktop_app" and not rule.get("app") and (needs_facts(t) and WEBBY_RE.search(t) or intents.is_web_task(t)) and not DESKTOP_APP_RE.search(t):
        p["intent"] = rule["intent"] if rule["intent"] != "desktop_app" else "web_interact"
    if p["intent"] not in ("desktop_app", "web_research_to_files") and rule["intent"] == "desktop_app" and rule.get("app"):
        p["intent"] = "desktop_app"  # an explicitly named installed app wins
    if p["intent"] != "desktop_app" and rule["intent"] == "desktop_app" and DESKTOP_APP_RE.search(t) and not WEBBY_RE.search(t):
        p["intent"] = "desktop_app"
    if p["intent"] == "desktop_app":
        p["app"] = str(rule.get("app") or p.get("app") or "").strip()
    else:
        p.pop("app", None)
    cnt = intents.requested_count(t)
    try: p["count"] = cnt or int(p.get("count") or 0)
    except (TypeError, ValueError): p["count"] = cnt or 0
    q = str(p.get("query") or "").strip()
    if p["intent"] in ("web_research_to_files", "web_answer"):
        if not q or len(q) < 3: q = rule.get("query") or clean_query(t)
        if p["count"] and not re.search(rf"\b{p['count']}\b", q): q = f"top {p['count']} {q}" if not re.search(r"\btop\b", q, re.I) else q
        q = with_year(q, t)
    p["query"] = q
    p["site"] = str(p.get("site") or "")
    p["columns"] = [str(c) for c in (p.get("columns") or []) if str(c).strip()][:12]
    p["title"] = str(p.get("title") or "")
    # a year only belongs in the query when the task is time-sensitive (recent/now/top/rankings)
    if p.get("query") and not (RECENT_RE.search(t) or re.search(r"\b(top|most|best|richest|biggest|largest|rank\w*|20\d\d)\b", t, re.I)):
        p["query"] = re.sub(r"\s*\b20\d\d\b\s*$", "", p["query"]).strip()
    p["query"] = re.sub(r"^(?:of|the|about|listing)\s+(?=\w)", "", str(p.get("query") or "")).strip()
    if p["intent"] == "web_research_to_files" and p["query"]:
        cq = strip_instructions(p["query"])
        if len(cq.split()) >= 2: p["query"] = cq
    # names/titles stay verbatim: if the model "corrected" the user's words, take them back from the original text
    if p["intent"] in ("media_play", "desktop_app", "web_interact") and p.get("query"):
        p["query"] = verbatim(task, p["query"])
    if p["intent"] in ("media_play", "web_answer", "web_interact", "open_site") and p.get("query"):
        p["query"] = intents.strip_filler(p["query"]) or p["query"]  # never search for "me a song by the name of X"
    p["source"] = p.get("source", "model"); p.pop("sure", None)
    return p

def with_context(task, context):
    if not context: return task
    lines = []
    for m in (context.get("turns") or [])[-4:]:
        lines.append(f"{m['role']}: {str(m['content'])[:160]}")
    last = context.get("last") or {}
    if last.get("task"):
        lines.append(f"previous task: {last['task']} (intent {last.get('intent')}, query {last.get('query')!r}, result: {str(last.get('result'))[:120]})")
    if not lines: return task
    return "Earlier in this chat (for resolving 'it', 'that', corrections):\n" + "\n".join(lines) + "\n\nNEW TASK: " + task

def plan(client, task, use_model=True, log=None, context=None):
    """Return a validated plan dict. The model is skipped for unambiguous regex fast paths.
    context = {"last": {...previous task...}, "turns": [...]} from the chat this task came from."""
    rule = rule_plan(task)
    if not use_model or client is None or rule.get("sure"):
        return dict(validate(rule, task), source="rules")
    try:
        raw = client.text_chat([{"role": "system", "content": PROMPT.format(today=today().strftime("%B %d, %Y"), year=today().year)},
                                {"role": "user", "content": with_context(task, context)}], json_mode=True, schema=SCHEMA, num_predict=160, temperature=0.0)
        obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception as e:
        if log: log(f"[plan] model plan unusable ({type(e).__name__}); using rules")
        return dict(validate(rule, task), source="rules")
    return validate(obj, task)
