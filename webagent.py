"""Browser loop driven by the Chrome extension: snapshot -> text model picks an element id -> extension acts -> verify."""
import json, re, time
from actions import ActionError, NeedsVision
import extlink

WEB_SYSTEM = """You control the user's Chrome browser through an extension. Each turn you get the TASK, the current page
(URL, title, dialogs, a short text summary) and a numbered list of interactive ELEMENTS: [id] role "label" (value/href).
NEVER invent or type emails, usernames, passwords or codes: if the page asks to sign in or sign up, reply done with "needs sign-in".
If you could not do the task, say so plainly in done (never claim it was completed elsewhere).
Reply with EXACTLY ONE JSON object: {"thought": "<max 20 words>", "action": "<name>", ...params}
Actions:
  {"action":"click","id":"<id>"}                         click an element from the list
  {"action":"type","id":"<id>","text":"...","press_enter":true}  type into a textbox/searchbox (replaces its text)
  {"action":"press","key":"Enter|Escape|Tab|ArrowDown"}  key on the focused element
  {"action":"select","id":"<id>","value":"<option>"}     choose in a <select>
  {"action":"scroll","direction":"down|up"}              reveal more elements
  {"action":"hover","id":"<id>"}
  {"action":"navigate","url":"https://..."}              open a URL in this tab (use for known sites / search URLs)
  {"action":"new_tab","url":"https://..."}  {"action":"switch_tab","match":"<title words>"}  {"action":"close_tab"}  {"action":"back"}
  {"action":"find","text":"<words of the thing you want>"}   search the WHOLE page (scrolling down, loading more results) and scroll it into view
  {"action":"wait_for","text":"<text that should appear>"}
  {"action":"read_page"}                                 read the page's main text (to answer questions)
  {"action":"answer","text":"<final answer for the user>"}  answer the user's question from text you have read; ends the task
  {"action":"done","summary":"<what was achieved / the answer>"}
  {"action":"vision","reason":"..."}                     ONLY if the page can't be handled from the element list (canvas, games)
Rules: use ids ONLY from the list. Pick by reading the label. Never repeat an action that did not change the page.
If the task is already achieved, reply done. For YouTube/Google searches prefer navigate to the results URL.
Elements marked (below) are further down the page: you can click them directly (the page scrolls to them).
If what you want is not in the list, use find or scroll down - NEVER reply done with "not found" before scrolling."""

ACTS = {"answer", "read_page", "find", "type", "press", "select", "scroll", "hover", "navigate", "new_tab", "switch_tab", "close_tab", "back",
        "wait_for", "extract_text", "done", "vision", "click"}

def give_up_message(task, history, snap):
    """Plain words instead of 'max steps reached': what it tried, where it stopped, what to try next."""
    tried = [h.split(": ", 1)[-1] for h in history[-4:] if h.startswith("web")]
    where = (snap or {}).get("title") or (snap or {}).get("url") or "the page"
    return ("stopped: I tried for a while but couldn't finish this in Chrome. I stopped on \"" + str(where)[:80] + "\"" +
            (" after: " + "; ".join(t[:60] for t in tried) if tried else "") +
            ". You can rephrase it (e.g. name the site or what to click), or ask me a question about that page.")

def parse(raw):
    s = raw[raw.index("{"): raw.rindex("}") + 1] if "{" in (raw or "") else ""
    try: a = json.loads(s)
    except ValueError as e: raise ActionError(f"bad JSON: {e}")
    for k in ("params", "args", "arguments"):
        if isinstance(a.get(k), dict): a = {**a.pop(k), **a}
    act = str(a.get("action", "")).lower().strip()
    act = {"click_element": "click", "open_url": "navigate", "goto": "navigate", "press_enter": "press", "enter": "press",
           "input": "type", "fill": "type", "finish": "done",
           "extract": "read_page", "extract_text": "read_page", "read": "read_page", "get_text": "read_page", "reply": "answer", "respond": "answer"}.get(act, act)
    if act not in ACTS: raise ActionError(f"unknown action {act!r}")
    a["action"] = act
    if act == "press": a.setdefault("key", "Enter")
    if act in ("click", "type", "select", "hover"):
        if a.get("id") in (None, ""): raise ActionError(f"{act} needs an element id from the list")
        a["id"] = str(a["id"]).strip("[] ")
    if act == "type" and not isinstance(a.get("text"), str): raise ActionError("type needs text")
    if act in ("navigate", "new_tab") and not a.get("url"): raise ActionError(f"{act} needs url")
    if act == "find" and not str(a.get("text") or a.get("query") or "").strip(): raise ActionError("find needs text")
    if act == "find": a["text"] = str(a.get("text") or a.get("query"))
    if act == "answer":
        a["text"] = str(a.get("text") or a.get("answer") or a.get("summary") or "").strip()
        if not a["text"]: raise ActionError("answer needs text")
    if "press_enter" in a: a["press_enter"] = a["press_enter"] in (True, "true", 1, "yes")
    return a

JUNK = re.compile(r"^(privacy|privacy (policy|statement|notice)|terms|terms (of (use|service))?|cookies?( (policy|settings|preferences))?|"
                  r"jobs|careers|advertis\w*|business|about( us)?|help|send feedback|feedback|legal|imprint|accessibility|sitemap|"
                  r"how search works|settings|report inappropriate predictions|your data in search|do not sell.*|contact( us)?|press|investors)$", re.I)

def is_junk(el, task=""):
    """Footer / legal / corporate links that never help a task (unless the task mentions them)."""
    lab = (el.get("label") or "").strip()
    return bool(lab) and bool(JUNK.match(lab)) and lab.lower() not in (task or "").lower()

def today():
    import datetime
    return datetime.date.today().strftime("%A %B %d, %Y")

def is_404(snap):
    """Only a real HTTP 404 (status reported by the extension) or an unmistakable 404 title - never page body text."""
    st = snap.get("status") or snap.get("http_status")
    if st is not None:
        try: return int(st) == 404
        except (TypeError, ValueError): pass
    t = (snap.get("title") or "").strip().lower()
    return bool(re.search(r"(^|[\s|:\-])404([\s|:\-]|$)", t)) or t in ("not found", "page not found", "404 not found", "error 404")

RISKY_WEB = re.compile(r"\b(sign ?up|register|create (?:an |your )?account|subscribe|subscription|start (?:your )?(?:free )?trial|free trial|"
                       r"billing|payment|pay|purchase|buy|checkout|check out|order|upgrade|get (?:started|premium|plus)|join now|choose (?:a |your )?plan|"
                       r"select (?:a |your )?plan|add to cart|place order|donate)\b", re.I)

def money_click(act, el, task):
    """Sign-up / billing / purchase / subscribe clicks need the user's OK unless the task asks for them."""
    if act.get("action") not in ("click", "press") or not el: return False
    lab = " ".join(str(el.get(k) or "") for k in ("label", "href"))
    m = RISKY_WEB.search(lab)
    return bool(m) and not RISKY_WEB.search(task or "")

def main_text(link, max_chars=3500):
    """The page's main text, whitespace-collapsed and trimmed."""
    res = link.call("extract_text", timeout=20, max=max_chars * 2) or {}
    return " ".join((res.get("text") or "").split())[:max_chars]

def nav(link, url, log=print, new_tab=False):
    """Navigate; if Chrome has no window/active tab, open a new tab, else launch Chrome with the URL."""
    try:
        return link.call("new_tab" if new_tab else "navigate", timeout=25, url=url) or {}
    except extlink.ExtError as e:
        msg = str(e).lower()
        if "not connected" in msg: raise
        if not any(k in msg for k in ("no active tab", "no current window", "no window", "no tab")): raise
        log(f"[web] Chrome has no open window - opening one for {url[:60]}")
        try:
            return link.call("new_tab", timeout=25, url=url) or {}
        except extlink.ExtError:
            launch_chrome(url); time.sleep(4.0)
            return {"url": url, "launched": True}

def launch_chrome(url):
    import subprocess, sys
    if sys.platform.startswith("win"): subprocess.Popen(["cmd", "/c", "start", "", "chrome", url], shell=False)
    elif sys.platform == "darwin": subprocess.Popen(["open", "-a", "Google Chrome", url])
    else: subprocess.Popen(["google-chrome", url])

def host(u):
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", u or "").split("/")[0].lower())

def site_matches(url, want):
    """Same site (ignoring www and paths like /welcome), or any non-Google page after a 'lucky' redirect."""
    if "btnI=1" in (want or ""): return bool(url) and "google." not in host(url)
    a, b = host(url), host(want)
    return bool(a) and (a == b or a.endswith("." + b) or b.endswith("." + a))

def top_result(snap, skip=()):
    """First real search result link (not Google's own pages, not footer junk). Articles beat site home pages."""
    homes = []
    for e in snap.get("elements") or []:
        h = e.get("href") or ""
        if h in skip: continue
        if e.get("role") != "link" or not h.startswith("http") or is_junk(e): continue
        host = re.sub(r"^https?://", "", h).split("/")[0].lower()
        if re.search(r"(^|\.)google\.|gstatic\.|googleusercontent\.|youtube\.com$|webcache", host): continue
        if len((e.get("label") or "").split()) < 2: continue
        if re.sub(r"^https?://[^/]+", "", h).strip("/") == "": homes.append(e); continue  # a home page: only if nothing better
        return e
    return homes[0] if homes else None

def format_snapshot(s, max_els=70, task=""):
    lines = [f"URL: {s.get('url','')}", f"TITLE: {s.get('title','')}"]
    if s.get("dialogs"): lines.append("OPEN DIALOG(S): " + "; ".join(d.get("label", "") for d in s["dialogs"]) + "  <- deal with it first")
    sc = s.get("scroll") or [0, 0]
    lines.append(f"SCROLL: {sc[0]}/{sc[1]}px")
    lines.append("PAGE TEXT (start): " + " ".join((s.get("text") or "").split())[:600])
    lines.append("ELEMENTS:")
    for e in [e for e in (s.get("elements") or []) if not is_junk(e, task)][:max_els]:
        extra = ""
        if e.get("value"): extra += f" value={e['value']!r}"
        if e.get("href") and e["role"] == "link": extra += " -> " + e["href"].split("?")[0][-60:]
        if e.get("focused"): extra += " (focused)"
        if e.get("disabled"): extra += " (disabled)"
        if e.get("below"): extra += " (below)"
        lines.append(f"  [{e['id']}] {e['role']} \"{e['label']}\"{extra}")
    return "\n".join(lines)

def page_key(s):
    return (s.get("url"), s.get("title"), len(s.get("elements") or []), tuple(sorted(d.get("label", "") for d in s.get("dialogs") or [])),
            tuple((e.get("id"), e.get("value")) for e in (s.get("elements") or [])[:40]))

def risky_text(act, snap):
    el = next((e for e in snap.get("elements") or [] if str(e.get("id")) == str(act.get("id"))), {})
    return " ".join(str(x) for x in (act.get("thought", ""), el.get("label", ""), act.get("text", "") if act["action"] == "type" else ""))

GAVE_UP = re.compile(r"\blikely\b|elsewhere|\bfailed\b|gave up|\bmaybe\b|\bprobably\b|not (?:sure|confirmed)", re.I)
NOT_FOUND = re.compile(r"not (?:be )?found|n[o']t find|could ?n[o']t|cannot find|can't find|unable to|no (?:matching |such )?(?:result|video|item)s?|not (?:visible|available|on the page|listed)|doesn'?t (?:appear|exist)", re.I)
MIN_SCROLLS = 5

def scroll_find(link, text, log=print, max_scrolls=8, sleep=time.sleep):
    """Look for text on the whole page; scroll down (waiting for lazy-loaded results) and retry up to max_scrolls times.
    Returns the find_text result (with id, already scrolled into view) or None."""
    for i in range(max_scrolls + 1):
        try:
            res = link.call("find_text", timeout=10, text=text) or {}
        except extlink.ExtError as e:
            res = {}; log(f"   find failed: {e}")
        if res.get("found"):
            log(f"[web] found \"{(res.get('label') or '')[:60]}\"" + (f" after {i} scroll(s)" if i else "")); return res
        if i == max_scrolls: break
        try: sc = link.call("scroll", timeout=12, direction="down", wait_lazy=True) or {}
        except extlink.ExtError: sc = {}
        log(f"[web] '{text[:40]}' not visible yet - scrolled down ({i+1}/{max_scrolls})")
        if sc.get("at_bottom") and not sc.get("grew") and not sc.get("moved"): break
        sleep(0.4)
    return None

def run_web(agent, task, history, logf, link=None, max_steps=30, sleep=time.sleep, info=None):
    """Returns a result string. Raises NeedsVision to hand over to the screenshot loop."""
    from actions import is_risky
    link = link or extlink.LINK
    s_cfg = agent.cfg["safety"]; words = s_cfg.get("risky_words", [])
    try:
        snap = link.call("snapshot")
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
        # active tab is chrome://, a new tab page, the extensions page ... -> open a real page first
        import intents
        site = next((u for k, u in intents.SITES.items() if re.search(r"\b" + re.escape(k) + r"\b", (task or "").lower())), "https://www.google.com")
        agent.log(f"[web] can't read this tab ({str(e)[:60]}); opening {site}")
        nav(link, site, agent.log); sleep(1.0); snap = link.call("snapshot")
    agent.log(f"[web] page: {snap.get('title','')[:60]} | {snap.get('url','')[:90]} ({len(snap.get('elements') or [])} elements)")
    from core import LoopGuard
    guard = LoopGuard(2, 3, 5); bad = 0; notes = []; scrolls = 0; no_change = 0
    import intents
    if info is None:
        _p = getattr(agent, "plan_info", None)
        info = intents.is_question(task) or (isinstance(_p, dict) and _p.get("intent") == "web_answer")
    if info: max_steps = min(max_steps, agent.cfg.get("agent", {}).get("info_max_steps", 8))
    seen = {}; dead_urls = set(); read = ""; rejected_done = 0
    # 2.1.1: the resolved query is the single source of truth for the goal (never an older query or text from the page)
    _pi = getattr(agent, "plan_info", None); _pi = _pi if isinstance(_pi, dict) else {}
    _ut = getattr(agent, "user_text", ""); _ut = _ut if isinstance(_ut, str) else ""
    goal_q = str(_pi.get("query") or "").strip()
    _stop = {"can", "you", "the", "and", "for", "try", "again", "search", "find", "play", "look", "please", "me", "it", "up", "on", "to", "a", "of",
             "song", "songs", "video", "videos", "all", "some", "this", "that", "with", "from", "open", "go", "youtube", "google", "chrome"}
    _words = lambda s: {t for t in intents.query_tokens(s) if t not in _stop and len(t) > 1}
    user_words = _words(_ut + " " + task + " " + goal_q)
    repeat_blocks = 0; replans = 0
    def direct_url():
        import urllib.parse
        site = str(_pi.get("site") or "")
        if goal_q and ("youtube" in site or "youtube." in str(snap.get("url") or "")):
            return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(goal_q)
        return "https://www.google.com/search?q=" + urllib.parse.quote_plus(goal_q or task)
    plain_open = None
    if intents.is_plain_open(task): plain_open = intents.plan(task)[0][0]["url"]
    max_els = 40 if info else 70
    import creds
    for step in range(1, max_steps + 1):
        if agent.kill.killed: return "stopped by user"
        if creds.auth_page(snap):  # 2.1.0: never fill in sign-in / sign-up forms; the user signs in themselves
            logf.write(json.dumps({"step": step, "stopped": "auth_page", "url": snap.get("url")}) + "\n")
            agent.log(f"[web] sign-in page ({str(snap.get('url'))[:70]}) - asking you to sign in yourself"); return creds.sign_in_message(snap)
        prompt = (f"TODAY: {today()}\nTASK: {task}\n" + (f"GOAL QUERY (type exactly this when searching): {goal_q}\n" if goal_q else "") + "\nCURRENT PAGE:\n{format_snapshot(snap, max_els, task)}\n" +
                  (f"\nTEXT YOU READ:\n{read[:1800]}\n" if read else "") + "\nRecent actions (oldest first):\n" +
                  ("\n".join(history[-6:]) or "(none)") + "\n" + "".join(f"WARNING: {n}\n" for n in notes) +
                  ("This is a QUESTION: read_page, then answer from the text (use the current year, not an old one).\n" if info else "") +
                  "Next action? JSON only.")
        notes = []
        t0 = time.time()
        raw = agent.client.text_chat([{"role": "system", "content": WEB_SYSTEM}, {"role": "user", "content": prompt}],
                                     json_mode=True, num_predict=160)
        entry = {"step": step, "mode": "web", "secs": round(time.time() - t0, 1), "raw": raw}
        try:
            act = parse(raw)
        except ActionError as e:
            bad += 1; history.append(f"web{step}: INVALID ({e})"); notes.append(f"Your reply was rejected: {e}")
            entry["error"] = str(e); logf.write(json.dumps(entry) + "\n")
            if bad >= 4: raise NeedsVision(f"text model kept giving invalid actions ({e})")
            continue
        entry["action"] = act
        shown = {k: v for k, v in act.items() if k not in ("action", "thought")}
        el = next((e for e in snap.get("elements") or [] if str(e.get("id")) == str(act.get("id"))), None)
        target = f" \"{el['label'][:50]}\"" if el else ""
        if act["action"] in ("click", "type", "select", "hover") and el is None:  # 2.2.1: invented ids ("search_result_1") never run
            valid = ", ".join(f"[{e.get('id')}] {str(e.get('label') or '')[:30]}" for e in (snap.get("elements") or [])[:25])
            bad += 1; entry["error"] = f"unknown id {act.get('id')!r}"; logf.write(json.dumps(entry) + "\n")
            history.append(f"web{step}: {act['action']} id={act.get('id')!r} -> REJECTED: that id is not on the page")
            notes.append(f"id {act.get('id')!r} does not exist. Use ONLY these ids from CURRENT PAGE: {valid}")
            agent.log(f"[web{step}] rejected made-up id {act.get('id')!r}")
            if bad >= 6: break
            continue
        agent.log(f"[web{step}] {act['action']}{target} {json.dumps(shown)} ({entry['secs']}s)")
        if act["action"] == "done" and scrolls < MIN_SCROLLS and NOT_FOUND.search(str(act.get("summary", "")) + " " + str(act.get("thought", ""))) \
                and not (snap.get("scroll") or [0, 1])[1] <= (snap.get("scroll") or [0, 0])[0]:
            # never give up with "not found" before looking further down the page
            act = {"action": "scroll", "direction": "down", "auto": True}; entry["action"] = act
            notes.append("You said it was not found, but you have not scrolled yet. I scrolled down: check the new elements.")
            agent.log(f"[web{step}] not found yet -> scrolling down instead of giving up")
        if act["action"] == "done":
            ok, why = intents.goal_check(task, snap)
            if not ok and rejected_done < 2:
                rejected_done += 1; history.append(f"web{step}: done -> REJECTED: {why}"); notes.append(f"Not done yet: {why}.")
                logf.write(json.dumps(dict(entry, rejected=why)) + "\n"); agent.log(f"[web{step}] not done: {why}"); continue
            logf.write(json.dumps(dict(entry, goal_check="ok" if ok else why)) + "\n")
            summ = act.get("summary", "done")
            if ok and (NOT_FOUND.search(summ) or GAVE_UP.search(summ)):  # "done: X not found / likely completed elsewhere" is a failure
                return f"stopped: {summ}"
            return summ if ok else f"stopped: couldn't confirm the goal ({why}). Last page: {snap.get('title') or snap.get('url')}"
        if act["action"] == "answer":
            logf.write(json.dumps(entry) + "\n"); return act["text"]
        if act["action"] == "read_page":
            try: read = main_text(link)
            except extlink.ExtError as e: read = ""; history.append(f"web{step}: read_page FAILED: {e}")
            history.append(f"web{step}: read_page -> {len(read)} chars (shown under TEXT YOU READ)")
            notes.append("Now reply with answer, using TEXT YOU READ." if info else "")
            logf.write(json.dumps(dict(entry, chars=len(read))) + "\n"); continue
        sig = json.dumps({k: act.get(k) for k in ("action", "id", "text", "url", "key", "direction")}, sort_keys=True)
        if act["action"] != "scroll": seen[sig] = seen.get(sig, 0) + 1
        if seen.get(sig, 0) > 2 and act["action"] != "scroll":
            repeat_blocks += 1
            if repeat_blocks >= 3:  # 2.1.1 anti-drift: stop clicking around; start over from the direct search page
                logf.write(json.dumps(dict(entry, blocked="repeat", replan=replans + 1)) + "\n")
                if replans >= 1: return "stopped: I kept repeating the same actions without reaching the goal" + (f" (\"{goal_q}\")" if goal_q else "") + "."
                replans += 1; repeat_blocks = 0; seen.clear(); history.append(f"web{step}: stuck -> restarted from the search page for {goal_q or task!r}")
                agent.log(f"[web] stuck - restarting from the search page"); nav(link, direct_url(), agent.log); sleep(1.0)
                snap = link.call("snapshot"); continue
            history.append(f"web{step}: {json.dumps(shown)} -> BLOCKED: you already did exactly this twice")
            notes.append("Do NOT repeat that action again. Choose something different" + (", or read_page and answer." if info else "."))
            logf.write(json.dumps(dict(entry, blocked="repeat")) + "\n"); continue
        if act["action"] in ("navigate", "new_tab"):
            known = [snap.get("url")] + [e.get("href") for e in snap.get("elements") or [] if e.get("href")]
            fixed = intents.safe_url(act["url"], known)
            if fixed != act["url"]:
                history.append(f"web{step}: {act['url']} is not a link on the page (made-up URL) -> searching Google instead")
                agent.log(f"[web] not opening made-up URL {act['url'][:80]} - using {fixed[:80]}"); act["url"] = fixed
        if act["action"] in ("navigate", "new_tab") and act["url"].rstrip("/") in dead_urls:
            history.append(f"web{step}: navigate {act['url']} -> BLOCKED: that URL returned 404 before; don't invent URLs, use search results")
            logf.write(json.dumps(dict(entry, blocked="404")) + "\n"); continue
        if act["action"] == "type":
            why = creds.check_type(act.get("text"), _ut or task, el)
            tw = _words(act.get("text") or "")
            if not why and tw and user_words and not (tw & user_words):  # text lifted from the page / an older task
                why = f"\"{str(act.get('text'))[:40]}\" isn't what you asked for" + (f" - search for \"{goal_q}\"" if goal_q else "")
                logf.write(json.dumps(dict(entry, blocked="off_goal_text")) + "\n"); agent.log(f"[web{step}] BLOCKED: {why}")
                history.append(f"web{step}: type {act.get('text')!r} -> BLOCKED: {why}")
                notes.append(f"Only type the goal query{(' ' + repr(goal_q)) if goal_q else ''} or words from the user's message."); continue
            if why:
                logf.write(json.dumps(dict(entry, blocked="credentials")) + "\n"); agent.log(f"[web{step}] BLOCKED: {why}")
                if el and (el.get("itype") in ("password", "email") or creds.FIELD.search(el.get("label") or "")):
                    return creds.sign_in_message(snap)
                history.append(f"web{step}: type {act.get('text')!r} -> BLOCKED: {why}")
                notes.append("NEVER invent emails, usernames, passwords or codes. Only type text from the user's message."); continue
        if money_click(act, el, task):
            if not agent.confirm(f"Agent wants to click \"{el.get('label','')[:60]}\" (sign-up / billing) on {snap.get('url','')[:80]}. Allow?"):
                history.append(f"web{step}: click \"{el.get('label','')[:50]}\" -> DENIED: sign-up/billing pages are off-limits for this task")
                notes.append("Don't click sign-up, subscribe or billing buttons. If the task is done, reply done.")
                logf.write(json.dumps(dict(entry, blocked="money")) + "\n"); continue
        if act["action"] == "click" and el and is_junk(el, task):
            history.append(f"web{step}: click \"{el['label']}\" -> BLOCKED: footer/legal link, not useful")
            logf.write(json.dumps(dict(entry, blocked="junk")) + "\n"); continue
        if act["action"] == "find" and len(act["text"].split()) > 6:  # a whole question is not text on the page
            act = {"action": "read_page"}; read = main_text(link)
            history.append(f"web{step}: find with a whole sentence -> read the page instead ({len(read)} chars)"); continue
        if act["action"] == "find":
            res = scroll_find(link, act["text"], agent.log, sleep=sleep); scrolls += 1
            snap = link.call("snapshot")
            if res:
                history.append(f"web{step}: find {act['text']!r} -> FOUND [{res['id']}] \"{(res.get('label') or '')[:60]}\" (now in view) - click it")
            else:
                history.append(f"web{step}: find {act['text']!r} -> not on the page even after scrolling")
            logf.write(json.dumps(dict(entry, result=res)) + "\n"); continue
        if act["action"] == "vision":
            logf.write(json.dumps(entry) + "\n"); raise NeedsVision(act.get("reason", "model asked for vision"))
        level = guard.check({"action": act["action"], "text": act.get("text"), "url": act.get("url"), "app": act.get("id"), "keys": act.get("key")})
        if level >= 3 and scrolls < MIN_SCROLLS:
            level = 2
        if level >= 3 and info: break
        if level >= 3: raise NeedsVision("stuck repeating the same browser action")
        if level == 2:
            history.append(f"web{step}: {json.dumps(shown)} -> BLOCKED (repeated, page did not change)")
            notes.append("That action was repeated without effect. I scrolled down to reveal more: choose a DIFFERENT element.")
            act = {"action": "scroll", "direction": "down", "auto": True}
        if s_cfg.get("confirm_risky", True):
            probe = {"action": "click" if act["action"] in ("click", "press") else act["action"], "text": act.get("text", ""),
                     "reason": risky_text(act, snap), "press_enter": act.get("press_enter")}
            if is_risky(probe, words) and not agent.confirm(f"Agent wants to {act['action']}{target} on {snap.get('url','')[:80]}"):
                history.append(f"web{step}: {act['action']}{target} DENIED by user - choose another approach or finish"); continue
        before = page_key(snap)
        try:
            args = {k: v for k, v in act.items() if k not in ("action", "thought", "reason", "auto")}
            if act["action"] == "scroll": scrolls += 1; args.setdefault("wait_lazy", True)
            res = nav(link, args["url"], agent.log, new_tab=act["action"] == "new_tab") if act["action"] in ("navigate", "new_tab") \
                else link.call(act["action"], timeout=25, **args)
            entry["result"] = res
            if res is None and act["action"] in ("click", "type", "select"):  # 2.2.1: no result = it didn't happen
                raise extlink.ExtError("the page did not respond to this action")
        except extlink.ExtError as e:
            history.append(f"web{step}: {json.dumps(shown)}{target} -> FAILED: {e}")
            agent.log(f"   failed: {e}"); logf.write(json.dumps(entry) + "\n")
            if "not connected" in str(e): raise NeedsVision(str(e))
            snap = link.call("snapshot"); continue
        if act["action"] == "extract_text":
            text = (res or {}).get("text", "")[:1500]
            history.append(f"web{step}: extract_text -> {text[:400]!r}")
        sleep(0.6 if act["action"] in ("click", "type", "press", "select") else 0.2)
        try: snap = link.call("snapshot")
        except extlink.ExtError as e:  # page navigating
            sleep(1.0); snap = link.call("snapshot")
        changed = page_key(snap) != before
        if act["action"] in ("navigate", "new_tab", "click") and is_404(snap):
            dead_urls.add(str(snap.get("url", "")).rstrip("/")); dead_urls.add(str(act.get("url", "")).rstrip("/"))
            history.append(f"web{step}: that page is a 404 (not found) - go back and use real links from search results")
        if act["action"] != "extract_text":
            history.append(f"web{step}: {json.dumps(shown)}{target} -> " + ("page changed" if changed else "NO CHANGE on the page"))
        if changed: guard.last = None; no_change = 0
        else:
            no_change += 1
            if no_change >= 3 and act["action"] != "scroll":  # stuck on the visible part of the page -> look further down
                link.call("scroll", timeout=12, direction="down", wait_lazy=True); scrolls += 1; no_change = 0
                snap = link.call("snapshot"); notes.append("Nothing changed 3 times; I scrolled down to show more of the page.")
        logf.write(json.dumps(entry) + "\n"); logf.flush()
        if act["action"] in ("navigate", "new_tab") and plain_open and site_matches(snap.get("url"), plain_open) and not is_404(snap):
            logf.write(json.dumps({"done": "site open"}) + "\n")
            return f"done: opened {snap.get('title') or snap.get('url')}"
        if intents.goal_reached(task, snap.get("url"), snap.get("title")):
            t = (snap.get("title") or "").replace(" - YouTube", "")
            return f"Playing \"{t}\" on YouTube." if "youtube.com/watch" in (snap.get("url") or "") and t else f"done: {t or snap.get('url')}"
    if info:  # out of steps on a question: answer from whatever page we're on instead of nothing
        try:
            ans = agent.answer_question(link, task, logf, max_pages=1)
            if isinstance(ans, str) and ans: return ans
        except Exception as e:
            agent.log(f"[web] final answer failed: {e}")
        return "I couldn't find a clear answer in time."
    try:  # 2.2.1: out of steps - answer from what's on the page if the task is a question/list, else explain plainly
        if intents.is_question(task) or re.search(r"\btop\s+\d+|\blist\b|\bmost\b|\bbest\b", task, re.I):
            ans = agent.answer_question(link, task, logf, max_pages=1)
            if isinstance(ans, str) and ans and not ans.startswith("I searched but"): return ans
    except Exception: pass
    return give_up_message(task, history, snap)
