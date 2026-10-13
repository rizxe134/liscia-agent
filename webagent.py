"""Browser loop driven by the Chrome extension: snapshot -> text model picks an element id -> extension acts -> verify."""
import json, time
from actions import ActionError, NeedsVision
import extlink

WEB_SYSTEM = """You control the user's Chrome browser through an extension. Each turn you get the TASK, the current page
(URL, title, dialogs, a short text summary) and a numbered list of interactive ELEMENTS: [id] role "label" (value/href).
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
  {"action":"wait_for","text":"<text that should appear>"}
  {"action":"extract_text"}                              read the page text (to answer questions)
  {"action":"done","summary":"<what was achieved / the answer>"}
  {"action":"vision","reason":"..."}                     ONLY if the page can't be handled from the element list (canvas, games)
Rules: use ids ONLY from the list. Pick by reading the label. Never repeat an action that did not change the page.
If the task is already achieved, reply done. For YouTube/Google searches prefer navigate to the results URL."""

ACTS = {"click", "type", "press", "select", "scroll", "hover", "navigate", "new_tab", "switch_tab", "close_tab", "back",
        "wait_for", "extract_text", "done", "vision"}

def parse(raw):
    s = raw[raw.index("{"): raw.rindex("}") + 1] if "{" in (raw or "") else ""
    try: a = json.loads(s)
    except ValueError as e: raise ActionError(f"bad JSON: {e}")
    for k in ("params", "args", "arguments"):
        if isinstance(a.get(k), dict): a = {**a.pop(k), **a}
    act = str(a.get("action", "")).lower().strip()
    act = {"click_element": "click", "open_url": "navigate", "goto": "navigate", "press_enter": "press", "enter": "press",
           "input": "type", "fill": "type", "finish": "done"}.get(act, act)
    if act not in ACTS: raise ActionError(f"unknown action {act!r}")
    a["action"] = act
    if act == "press": a.setdefault("key", "Enter")
    if act in ("click", "type", "select", "hover"):
        if a.get("id") in (None, ""): raise ActionError(f"{act} needs an element id from the list")
        a["id"] = str(a["id"]).strip("[] ")
    if act == "type" and not isinstance(a.get("text"), str): raise ActionError("type needs text")
    if act in ("navigate", "new_tab") and not a.get("url"): raise ActionError(f"{act} needs url")
    if "press_enter" in a: a["press_enter"] = a["press_enter"] in (True, "true", 1, "yes")
    return a

def format_snapshot(s, max_els=70):
    lines = [f"URL: {s.get('url','')}", f"TITLE: {s.get('title','')}"]
    if s.get("dialogs"): lines.append("OPEN DIALOG(S): " + "; ".join(d.get("label", "") for d in s["dialogs"]) + "  <- deal with it first")
    sc = s.get("scroll") or [0, 0]
    lines.append(f"SCROLL: {sc[0]}/{sc[1]}px")
    lines.append("PAGE TEXT (start): " + " ".join((s.get("text") or "").split())[:600])
    lines.append("ELEMENTS:")
    for e in (s.get("elements") or [])[:max_els]:
        extra = ""
        if e.get("value"): extra += f" value={e['value']!r}"
        if e.get("href") and e["role"] == "link": extra += " -> " + e["href"].split("?")[0][-60:]
        if e.get("focused"): extra += " (focused)"
        if e.get("disabled"): extra += " (disabled)"
        lines.append(f"  [{e['id']}] {e['role']} \"{e['label']}\"{extra}")
    return "\n".join(lines)

def page_key(s):
    return (s.get("url"), s.get("title"), len(s.get("elements") or []), tuple(sorted(d.get("label", "") for d in s.get("dialogs") or [])),
            tuple((e.get("id"), e.get("value")) for e in (s.get("elements") or [])[:40]))

def risky_text(act, snap):
    el = next((e for e in snap.get("elements") or [] if str(e.get("id")) == str(act.get("id"))), {})
    return " ".join(str(x) for x in (act.get("thought", ""), el.get("label", ""), act.get("text", "") if act["action"] == "type" else ""))

def run_web(agent, task, history, logf, link=None, max_steps=30, sleep=time.sleep):
    """Returns a result string. Raises NeedsVision to hand over to the screenshot loop."""
    from actions import is_risky
    link = link or extlink.LINK
    s_cfg = agent.cfg["safety"]; words = s_cfg.get("risky_words", [])
    snap = link.call("snapshot")
    agent.log(f"[web] page: {snap.get('title','')[:60]} | {snap.get('url','')[:90]} ({len(snap.get('elements') or [])} elements)")
    from core import LoopGuard
    guard = LoopGuard(2, 3, 5); bad = 0; notes = []
    for step in range(1, max_steps + 1):
        if agent.kill.killed: return "stopped by user"
        prompt = (f"TASK: {task}\n\nCURRENT PAGE:\n{format_snapshot(snap)}\n\nRecent actions (oldest first):\n" +
                  ("\n".join(history[-8:]) or "(none)") + "\n" + "".join(f"WARNING: {n}\n" for n in notes) + "Next action? JSON only.")
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
        agent.log(f"[web{step}] {act['action']}{target} {json.dumps(shown)} ({entry['secs']}s)")
        if act["action"] == "done":
            logf.write(json.dumps(entry) + "\n"); return act.get("summary", "done")
        if act["action"] == "vision":
            logf.write(json.dumps(entry) + "\n"); raise NeedsVision(act.get("reason", "model asked for vision"))
        level = guard.check({"action": act["action"], "text": act.get("text"), "url": act.get("url"), "app": act.get("id"), "keys": act.get("key")})
        if level >= 3: raise NeedsVision("stuck repeating the same browser action")
        if level == 2:
            history.append(f"web{step}: {json.dumps(shown)} -> BLOCKED (repeated, page did not change)")
            notes.append("That action was repeated without effect. Choose a DIFFERENT element or action."); continue
        if s_cfg.get("confirm_risky", True):
            probe = {"action": "click" if act["action"] in ("click", "press") else act["action"], "text": act.get("text", ""),
                     "reason": risky_text(act, snap), "press_enter": act.get("press_enter")}
            if is_risky(probe, words) and not agent.confirm(f"Agent wants to {act['action']}{target} on {snap.get('url','')[:80]}"):
                history.append(f"web{step}: {act['action']}{target} DENIED by user - choose another approach or finish"); continue
        before = page_key(snap)
        try:
            args = {k: v for k, v in act.items() if k not in ("action", "thought", "reason")}
            res = link.call(act["action"], timeout=25, **args)
            entry["result"] = res
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
        if act["action"] != "extract_text":
            history.append(f"web{step}: {json.dumps(shown)}{target} -> " + ("page changed" if changed else "NO CHANGE on the page"))
        if changed: guard.last = None
        logf.write(json.dumps(entry) + "\n"); logf.flush()
        import intents
        if intents.goal_reached(task, snap.get("url")):
            return f"done: goal reached ({snap.get('url')})"
    return "max steps reached"
