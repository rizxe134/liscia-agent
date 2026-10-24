"""2.0.1: play a specific song/video on YouTube and PROVE it. Always searches (never presses play on whatever page is open,
unless the current video already matches), ranks every result by the query's significant tokens (title + artist),
prefers plain videos over Mix/radio/playlists, verifies the playing title, tries up to 3 candidates, and reports honestly."""
import json, time, urllib.parse
import intents, extlink

GOOD = 0.99   # every significant token matched
OK = 0.5      # half the tokens (e.g. the title without the artist): "closest match"

def rank(query, results):
    """Best first. Score = token match (title + channel) minus penalties for Mix/playlist/shorts."""
    out = []
    for i, r in enumerate(results):
        title, ch = r.get("title") or r.get("label") or "", r.get("channel") or ""
        s = max(intents.title_match(query, title), intents.title_match(query, f"{title} {ch}"))
        kind = r.get("kind") or ("mix" if intents.MIX_RE.search(title) or "start_radio=1" in (r.get("href") or "") else
                                 "playlist" if "list=" in (r.get("href") or "") else "video")
        pen = {"mix": 0.35, "playlist": 0.3, "short": 0.15}.get(kind, 0.0)
        if kind == "video" and intents.MIX_RE.search(title) and not intents.MIX_RE.search(query): pen += 0.2
        out.append((round(s - pen - i * 0.002, 4), s, dict(r, kind=kind)))
    out.sort(key=lambda x: x[0], reverse=True)
    return out

def results(link):
    try:
        got = (link.call("video_results", timeout=15, limit=25) or {}).get("results") or []
        if got: return got
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
    if True:
        snap = link.call("snapshot")  # older extension: fall back to the page's /watch links
        res, seen = [], set()
        for e in snap.get("elements") or []:
            h = e.get("href") or ""
            if "/watch" in h and h not in seen and len(e.get("label") or "") > 3:
                seen.add(h); res.append({"id": e["id"], "title": e["label"], "href": h})
        return res

def state(link):
    try:
        st = link.call("media_state", timeout=10) or {}
        if st.get("url"): return st
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
    if True:
        s = link.call("snapshot"); return {"url": s.get("url"), "title": (s.get("title") or "").replace(" - YouTube", ""), "paused": None}

def youtube_play(agent, link, query, logf, sleep=time.sleep, nav=None, max_tries=3):
    """Returns a plain-words result: 'Playing "<title>" on YouTube.' or an honest closest/failure message."""
    import webagent
    nav = nav or (lambda url: webagent.nav(link, url, agent.log))
    q = intents.strip_filler(query) or query
    # already playing the right thing? keep it
    try:
        cur = state(link)
        if "youtube.com/watch" in (cur.get("url") or "") and intents.title_match(q, cur.get("title", "") + " " + cur.get("channel", "")) >= GOOD:
            if cur.get("paused"):
                try: link.call("media_control", timeout=10, op="play")
                except extlink.ExtError: pass
            logf.write(json.dumps({"media": "already_playing", "title": cur.get("title")}) + "\n")
            return f"Playing \"{cur.get('title')}\" on YouTube (it was already open)."
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q)
    nav(url); logf.write(json.dumps({"web_fast": {"action": "open_url", "url": url}, "query": q}) + "\n")
    agent.log(f"[media] searching YouTube for \"{q}\"")
    res = []
    for _ in range(6):
        sleep(1.0); res = results(link)
        if res: break
    if not res: return f"stopped: YouTube showed no results for \"{q}\"."
    ranked = rank(q, res)
    for _ in range(3):  # lazy-loaded results: look further down before settling for a weak match
        if ranked and ranked[0][1] >= GOOD: break
        try: link.call("scroll", timeout=12, direction="down", wait_lazy=True)
        except extlink.ExtError: break
        sleep(0.8); more = results(link)
        if len(more) <= len(res) and not [x for x in more if x not in res]: continue
        res = more; ranked = rank(q, res)
    logf.write(json.dumps({"media_candidates": [{"score": s, "title": r.get("title"), "kind": r.get("kind")} for s, _, r in ranked[:6]]}) + "\n")
    tried, best_played = [], None
    for score, match, r in ranked[:max_tries]:
        if tried and match < OK: break  # don't wander off into unrelated videos
        tried.append(r.get("title"))
        agent.log(f"[media] trying \"{(r.get('title') or '')[:70]}\" (match {match:.0%}, {r.get('kind')})")
        if r.get("href"): nav(r["href"])
        else: link.call("click", timeout=25, id=r["id"])
        st = {}
        for _ in range(10):
            sleep(1.0)
            try: st = state(link)
            except extlink.ExtError: continue
            if "youtube.com/watch" in (st.get("url") or "") and st.get("title"): break
        got = intents.title_match(q, (st.get("title") or "") + " " + (st.get("channel") or ""))
        if st.get("paused"):
            try: link.call("media_control", timeout=10, op="play"); st["paused"] = False
            except extlink.ExtError: pass
        logf.write(json.dumps({"media_verify": {"title": st.get("title"), "channel": st.get("channel"), "match": got, "paused": st.get("paused")}}) + "\n")
        if got >= GOOD:
            return f"Playing \"{st.get('title')}\"" + (f" by {st['channel']}" if st.get("channel") else "") + " on YouTube."
        if best_played is None or got > best_played[0]: best_played = (got, st.get("title"), st.get("url") or r.get("href"))
    if best_played and best_played[0] >= OK:
        if tried and best_played[1] != st.get("title") and best_played[2]: nav(best_played[2]); sleep(1.0)
        return f"Couldn't find an exact match for \"{q}\"; playing the closest: \"{best_played[1]}\"."
    return f"stopped: couldn't find \"{q}\" on YouTube (tried: " + "; ".join(t or "?" for t in tried) + ")."
