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
