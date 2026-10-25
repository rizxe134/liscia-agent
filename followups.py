"""2.0.1: follow-ups use the chat context.
  "can you play me the song" / "play it" / "that one"  -> the previous task's query
  "no I meant X" / "actually X" / "I mean X"           -> a correction: redo the previous task with X
ctx = {"last": {"task", "intent", "query", "site", "result"}, "turns": [{"role","content"}...]}"""
import re
import intents

CORRECTION = re.compile(r"^\W*(?:no+|nope|nah|wrong|not that(?: one)?|that's not it|thats not it|wait)?[\s,.!]*(?:i meant|i mean|i said|actually|rather|instead)\b[\s,:]*|"
                        r"^\W*(?:no+|nope|nah|not that(?: one)?|wrong one)[\s,.!]+(?=\S)", re.I)
REF = re.compile(r"^(?:it|that|this|that one|this one|the song|the video|the track|the one|same|the same one|again|it again)$", re.I)
RETRY = re.compile(r"\b(wrong (song|video|one|track|thing)|not (that|the right|the correct) (one|song|video|track)|that'?s not (it|the one|right)|"
                   r"try (it )?again|again please|another (one|version)|different (one|song|version|video)|search (it|for it)( up)?|look (it|for it) up|"
                   r"find (it|the right one))\b", re.I)

BROWSERS = r"(?:google\s+)?chrome|safari|(?:microsoft\s+)?edge|firefox|brave|opera|arc|(?:the\s+|a\s+|my\s+)?(?:web\s+)?browser|the web"
BROWSER_REDO = re.compile(r"^\W*(?:(?:can|could|would|will) you\s+|please\s+|ok(?:ay)?\s+|now\s+|then\s+)*(?:do|try|open|run)\s+(?:it|that|this|them|those|that one)?\s*"
                          r"(?:again\s+)?(?:on|in|with|using|through|via)\s+(" + BROWSERS + r")(?:\s+(?:instead|again|please))?\W*$", re.I)

def browser_redo(task, ctx):
    """'do it on google chrome' -> redo the most recent task in that browser (a browser is never a site or a query)."""
    last = (ctx or {}).get("last") or {}
    m = BROWSER_REDO.match(task or "")
    if not m or not last.get("task"): return None
    b = re.sub(r"^(the|a|my)\s+", "", m.group(1).strip().lower())
    b = "Google Chrome" if "chrome" in b or "browser" in b or "web" in b else b.title()
    prev = re.sub(r"\s+(?:on|in|with|using)\s+(?:" + BROWSERS + r")\s*$", "", last["task"].strip(), flags=re.I)
    return f"{prev} in {b}", f"\"{task.strip()}\" = redo \"{last['task']}\" in {b}"

REST_RE = re.compile(r"\b(?:(?:did\s*n'?t|didnt|did not|never|forgot to|haven'?t|havent)\s+(?:do|did|finish|complete|get to)\s+(?:the\s+)?"
                     r"(?:rest|other (?:things|parts|steps|stuff)|second (?:part|thing)|next (?:part|thing)|everything|all of it)|"
                     r"(?:do|finish|complete|continue with)\s+the\s+(?:rest|other (?:things|parts|steps))|what about the rest)\b", re.I)
FAILED_RE = re.compile(r"^\s*(?:stopped|i searched but|couldn'?t|i couldn'?t|i stopped)", re.I)

def rest_of(task, ctx):
    """'you didn't do the rest' -> the unfinished parts of the previous multi-step request (None if not that kind of message)."""
    last = (ctx or {}).get("last") or {}
    if not REST_RE.search(intents.fix_typos(task or "")) or not last.get("task"): return None
    parts = last.get("parts") or intents.split_steps(last["task"])
    if len(parts) < 2: return None
    done = last.get("done")
    if done is None: done = [] if FAILED_RE.match(str(last.get("result") or "")) else [0]
    todo = [p for k, p in enumerate(parts) if k not in done]
    return " then ".join(todo) if todo else None

def nothing_left(task, ctx):
    """'you didn't do the rest' when every step already ran: ('do', 'play X') to finish a search-only step, or ('say', honest summary)."""
    last = (ctx or {}).get("last") or {}
    if not REST_RE.search(intents.fix_typos(task or "")) or not last.get("task"): return None
    parts = last.get("parts") or intents.split_steps(last["task"])
    res = last.get("part_results") or ([str(last.get("result") or "")] if len(parts) == 1 else [])
    for p, r in zip(parts, res):
        m = re.match(r'^\s*Searched YouTube for "([^"]+)"', r)
        if m: return "do", f"play {m.group(1)} on youtube"
    if len(parts) < 2: return None
    short = lambda r: re.sub(r"\s+", " ", r)[:90]
    done = "; ".join(f"{k + 1}) {p} -> {short(r)}" for k, (p, r) in enumerate(zip(parts, res))) if res else "; ".join(parts)
    return "say", (f"All {len(parts)} steps of your last request already ran: {done}. "
                   "Tell me which part isn't right (or what to do next) and I'll redo it.")

def is_retry(task, ctx):
    """'thats the wrong song' / 'try again and search it up' right after a media task -> redo it (deterministically)."""
    last = (ctx or {}).get("last") or {}
    return bool(RETRY.search(task or "") and last.get("query") and (last.get("intent") == "media_play" or (ctx or {}).get("media_before")))

def retry_query(plan_query, ctx):
    """The single source of truth for a retry: the planner's query only if it is a refinement of the most recent requested
    item (e.g. 'pursuit' -> 'Shirobon Pursuit'); otherwise the most recent requested item itself (never an older one)."""
    last_q = ((ctx or {}).get("last") or {}).get("query") or ""
    pq = intents.strip_filler(plan_query or "") or ""
    lt, pt = set(intents.query_tokens(last_q)), set(intents.query_tokens(pq))
    return pq if pq and lt and lt <= pt and len(pt) <= len(lt) + 3 else last_q

SITE_WORDS = re.compile(r"\b(youtube|spotify|google|chrome|safari|website)\b", re.I)

def _site_hint(last):
    site = (last or {}).get("site") or ""
    if site: return site
    m = SITE_WORDS.search((last or {}).get("task") or "")
    return m.group(1).lower() if m else ""

def resolve(task, ctx):
    """Return (task_to_run, note or None). Unchanged when there's no usable context."""
    last = (ctx or {}).get("last") or {}
    if not last.get("task"): return task, None
    t = task.strip()
    br = browser_redo(t, ctx)
    if br: return br
    site = _site_hint(last)
    on_site = f" on {site}" if site in ("youtube", "spotify") and not SITE_WORDS.search(t) else ""
    m = CORRECTION.match(t)
    if m:
        rest = t[m.end():].strip(" ,.")
        if not rest: return task, None
        q = intents.strip_filler(rest)
        by = re.match(r"^(?:the\s+)?(?:one\s+|song\s+|video\s+|version\s+)?by\s+(.+)$", rest, re.I)
        if by and last.get("query"): q = f"{last['query']} by {by.group(1).strip()}"
        verb = "play" if last.get("intent") == "media_play" or re.search(r"\b(play|song|video|track|listen)\b", rest + " " + last["task"], re.I) else None
        if verb and q:
            return f"play {q}{on_site}", f"correction of \"{last['task']}\" -> play \"{q}\"{on_site}"
        if q: return f"{rest}{on_site}" if on_site else rest, f"correction of \"{last['task']}\""
        return task, None
    # "play me the song" / "play it" with nothing named -> the previous query
    body = re.sub(r"^(?:(?:hey|ok|okay|so|please|pls|now|can you|could you|would you|will you|just)\s+)+", "", t, flags=re.I).strip(" .!?")
    pm = re.match(r"^(?:play|put on|start|listen to|watch|open|click)(?:\s+(?:me|us|for me))?\s*(.*)$", body, re.I)
    if pm and last.get("query"):
        obj = pm.group(1).strip(" .!?")
        if not obj or REF.match(obj) or not intents.strip_filler(obj):
            return f"play {last['query']}{on_site}", f"\"{obj or 'it'}\" = \"{last['query']}\" from the previous task"
    return task, None
