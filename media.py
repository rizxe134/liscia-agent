"""2.0.1: play a specific song/video on YouTube and PROVE it. Always searches (never presses play on whatever page is open,
unless the current video already matches), ranks every result by the query's significant tokens (title + artist),
prefers plain videos over Mix/radio/playlists, verifies the playing title, tries up to 3 candidates, and reports honestly."""
import json, re, time, urllib.parse
import intents, extlink

GOOD = 0.99   # every significant token matched
OK = 0.5      # half the tokens (e.g. the title without the artist): "closest match"

_CH = re.compile(r"youtube\.com/(@|channel/|c/|user/)")

VARIANT = re.compile(r"\b(slowed|sped ?up|reverb|nightcore|8d|bass ?boosted|1 hour|loop|edit|remix|cover|karaoke|instrumental|extended|full album)\b", re.I)
JUNK = re.compile(r"^(true|false|now playing|mix|\d+ videos|play all|\d+:\d+(:\d+)?( now playing)?|live|new|\d+ (seconds?|minutes?|hours?).*)$", re.I)

def vid(href):
    return (urllib.parse.parse_qs(urllib.parse.urlparse(href or "").query).get("v") or [""])[0]

def clean(href):
    """A /watch link without the radio/playlist tail, so the plain video plays (not 'Mix - ...')."""
    v = vid(href)
    return f"https://www.youtube.com/watch?v={v}" if v else href

def rank(query, results):
    """Best first. Score = token match (title + channel) minus penalties for Mix/playlist/shorts."""
    out = []
    for i, r in enumerate(results):
        title, ch = r.get("title") or r.get("label") or "", r.get("channel") or ""
        s = max(intents.title_match(query, title), intents.title_match(query, f"{title} {ch}"))
        h = r.get("href") or ""
        # YouTube adds &list=RD..&start_radio=1 to many plain videos; only the title/a /playlist link says it's a mix
        kind = r.get("kind") or ("mix" if intents.MIX_RE.search(title) else "playlist" if "/playlist" in h else
                                 "short" if "/shorts/" in h else "video")
        pen = {"mix": 0.35, "playlist": 0.3, "short": 0.15}.get(kind, 0.0)
        extra = max(0, len(re.findall(r"[\w']+", re.sub(r"\d+ (?:hours?|minutes?|seconds?)", "", title))) - len(intents.query_tokens(query)) - 2)
        pen += min(0.12, 0.012 * extra) + (0.05 if "#" in title else 0)
        import unicodedata
        var = VARIANT.findall(unicodedata.normalize("NFKC", title))
        if var and not VARIANT.search(query): pen += 0.12  # the original beats "(slowed)" / "sped up" / nightcore edits  # the plain track beats "Little cute video ... #tags"
        out.append((round(s - pen - i * 0.002, 4), s, dict(r, kind=kind)))
    out.sort(key=lambda x: x[0], reverse=True)
    return out

def results(link):
    got = []
    try:
        got = (link.call("video_results", timeout=15, limit=25) or {}).get("results") or []
        # 2.0.1-2.1.0 extensions read the thumbnail link ("2:05 Now playing" / "true") instead of the title: use the page's
        # title links from the snapshot then, keeping the extension's channel names
        if got and sum(1 for r in got if JUNK.match((r.get("title") or "").strip())) <= len(got) // 3: return got
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
    snap_res = _snapshot_results(link)
    chans = {vid(r.get("href")): r.get("channel") for r in got if r.get("channel")}
    for r in snap_res:
        if not r.get("channel") and chans.get(vid(r.get("href"))): r["channel"] = chans[vid(r["href"])]
    return snap_res or got

def _snapshot_results(link):
    if True:
        snap = link.call("snapshot", max=300)  # older extension: fall back to the page's /watch links
        res, seen = [], {}
        els = snap.get("elements") or []
        for i, e in enumerate(els):
            h = e.get("href") or ""; v = vid(h)
            if "/watch" not in h or not v: continue
            ch = ""
            for x in els[i + 1:i + 15]:  # the channel link follows the title, before the next video
                xv = vid(x.get("href"))
                if xv and xv != v: break
                if _CH.search(x.get("href") or "") and (x.get("label") or "").strip(): ch = x["label"].strip(); break
            lab = (e.get("label") or "").strip()
            if v in seen:  # same video via thumbnail/title/duration links: keep the best label, add the channel
                r = seen[v]
                if ch and not r["channel"]: r["channel"] = ch
                if lab and not JUNK.match(lab) and (JUNK.match(r["title"]) or len(lab) > len(r["title"])): r["title"] = lab; r["id"] = e["id"]
                continue
            if len(lab) > 3 or (lab and not JUNK.match(lab)):
                seen[v] = {"id": e["id"], "title": e["label"], "href": h, "channel": ch}; res.append(seen[v])
        return res

def state(link):
    try:
        st = link.call("media_state", timeout=10) or {}
        if st.get("url"): return st
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
    if True:
        s = link.call("snapshot")
        ch = next(((x.get("label") or "").strip() for x in (s.get("elements") or [])
                   if _CH.search(x.get("href") or "") and (x.get("label") or "").strip()), "") if "/watch" in (s.get("url") or "") else ""
        return {"url": s.get("url"), "title": re.sub(r"^\(\d+\)\s*", "", (s.get("title") or "").replace(" - YouTube", "")), "channel": ch, "paused": None}

def youtube_play(agent, link, query, logf, sleep=time.sleep, nav=None, max_tries=3, exclude=None):
    """Returns a plain-words result: 'Playing "<title>" on YouTube.' or an honest closest/failure message."""
    import webagent
    nav = nav or (lambda url: webagent.nav(link, url, agent.log))
    q = intents.strip_filler(query) or query
    excl = {vid(u) for u in (exclude or []) if vid(u)}
    agent.last_played = None
    # already playing the right thing? keep it (not on a retry: the user just said it wasn't right)
    try:
        if exclude is not None: raise extlink.ExtError("retry: always search again")
        cur = state(link)
        if "youtube.com/watch" in (cur.get("url") or "") and vid(cur.get("url")) not in excl and intents.title_match(q, cur.get("title", "") + " " + cur.get("channel", "")) >= GOOD:
            if cur.get("paused"):
                try: link.call("media_control", timeout=10, op="play")
                except extlink.ExtError: pass
            logf.write(json.dumps({"media": "already_playing", "title": cur.get("title")}) + "\n")
            agent.last_played = {"url": cur.get("url"), "title": cur.get("title")}
            return f"Playing \"{cur.get('title')}\"" + (f" by {cur['channel']}" if cur.get("channel") else "") + " on YouTube (it was already open)."
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
    res = [r for r in res if vid(r.get("href")) not in excl and not JUNK.match((r.get("title") or "").strip())] or res
    ranked = rank(q, res)
    for _ in range(3):  # lazy-loaded results: look further down before settling for a weak match
        if ranked and ranked[0][1] >= GOOD: break
        try: link.call("scroll", timeout=12, direction="down", wait_lazy=True)
        except extlink.ExtError: break
        sleep(0.8); more = results(link)
        if len(more) <= len(res) and not [x for x in more if x not in res]: continue
        res = [r for r in more if vid(r.get("href")) not in excl and not JUNK.match((r.get("title") or "").strip())] or more; ranked = rank(q, res)
    logf.write(json.dumps({"media_candidates": [{"score": s, "title": r.get("title"), "kind": r.get("kind")} for s, _, r in ranked[:6]]}) + "\n")
    tried, best_played = [], None; skipped_ads = [0]
    adnote = lambda: f" (skipped {skipped_ads[0]} ad{'s' if skipped_ads[0] > 1 else ''})" if skipped_ads[0] else ""
    for score, match, r in ranked[:max_tries]:
        if tried and match < OK: break  # don't wander off into unrelated videos
        tried.append(r.get("title"))
        agent.log(f"[media] trying \"{(r.get('title') or '')[:70]}\" (match {match:.0%}, {r.get('kind')})")
        if r.get("href"): nav(clean(r["href"]) if r.get("kind") == "video" else r["href"])
        else: link.call("click", timeout=25, id=r["id"])
        try:  # ads: skip as soon as possible / wait out unskippable ones before judging the video
            import ads
            ad = ads.handle(link, getattr(agent, "cfg", None) if isinstance(getattr(agent, "cfg", None), dict) else {}, logf, agent.log, sleep)
            if ad.get("skipped"): skipped_ads[0] += ad["skipped"]
        except extlink.ExtError as e:
            if "not connected" in str(e): raise
        st = {}
        for _ in range(10):
            sleep(1.0)
            try: st = state(link)
            except extlink.ExtError: continue
            if "youtube.com/watch" in (st.get("url") or "") and st.get("title"): break
        got = intents.title_match(q, (st.get("title") or "") + " " + (st.get("channel") or ""))
        if vid(st.get("url")) and vid(st.get("url")) == vid(r.get("href")) and r.get("channel") and not st.get("channel"):
            st["channel"] = r["channel"]; got = max(got, intents.title_match(q, f"{st.get('title') or ''} {r['channel']}"))
        if st.get("paused"):
            try: link.call("media_control", timeout=10, op="play"); st["paused"] = False
            except extlink.ExtError: pass
        logf.write(json.dumps({"media_verify": {"title": st.get("title"), "channel": st.get("channel"), "match": got, "paused": st.get("paused")}}) + "\n")
        if got >= GOOD:
            agent.last_played = {"url": st.get("url") or r.get("href"), "title": st.get("title")}
            return f"Playing \"{st.get('title')}\"" + (f" by {st['channel']}" if st.get("channel") else "") + " on YouTube." + adnote()
        if best_played is None or got > best_played[0]: best_played = (got, st.get("title"), st.get("url") or r.get("href"))
    if best_played and best_played[0] >= OK:
        if tried and best_played[1] != st.get("title") and best_played[2]: nav(best_played[2]); sleep(1.0)
        agent.last_played = {"url": best_played[2], "title": best_played[1]}
        return f"Couldn't find an exact match for \"{q}\"; playing the closest: \"{best_played[1]}\"."
    return f"stopped: couldn't find \"{q}\" on YouTube (tried: " + "; ".join(t or "?" for t in tried) + ")."


# 2.3.0: "the 5th video you see" is a position on the page, not a title
_ORDW = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "last": -1}
ORDINAL_RE = re.compile(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b|\b(?:the\s+)?(" + "|".join(_ORDW) + r")\b", re.I)

def ordinal_pick(task):
    """(n, topic) for '... the 5th video (you see|on the page|for X)'; None when the task names a title."""
    t = task or ""
    if not re.search(r"\b(video|result|one|clip|song|thing|item|link)s?\b", t, re.I): return None
    m = ORDINAL_RE.search(t)
    if not m or not re.search(ORDINAL_RE.pattern + r"\s+(?:\w+\s+)?(?:video|result|one|clip|song|thing|item|link)", t, re.I): return None
    n = int(m.group(1)) if m.group(1) else _ORDW[m.group(2).lower()]
    topic = ""
    tm = re.search(r"\b(?:video|result|one|clip|song)s?\s+(?:for|about|of|on)\s+(?!youtube\b|the (?:page|screen|home ?page)\b)(.+?)(?:\s+on youtube)?\s*[.?!]*$", t, re.I)
    if tm: topic = tm.group(1).strip()
    return n, topic

def youtube_nth(agent, link, n, topic, logf, sleep=time.sleep, nav=None):
    import webagent
    nav = nav or (lambda url: webagent.nav(link, url, agent.log))
    url = ("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(topic)) if topic else "https://www.youtube.com/"
    nav(url); logf.write(json.dumps({"web_fast": {"action": "open_url", "url": url}, "nth": n}) + "\n")
    res = []
    for i in range(8):
        sleep(1.0)
        res = [r for r in results(link) if not JUNK.match((r.get("title") or "").strip()) and "/shorts/" not in (r.get("href") or "")]
        if n == -1 and res or len(res) >= n: break
        if i >= 2:
            try: link.call("scroll", timeout=12, direction="down", wait_lazy=True)
            except extlink.ExtError: pass
    if not res or (n > 0 and len(res) < n): return f"stopped: I could only see {len(res)} videos on that YouTube page, not {n}."
    r = res[n - 1] if n > 0 else res[-1]
    agent.log(f"[media] video #{n}: \"{(r.get('title') or '')[:70]}\"")
    nav(clean(r["href"]) if r.get("href") else url)
    if not r.get("href"): link.call("click", timeout=25, id=r["id"])
    try:
        import ads; ads.handle(link, getattr(agent, "cfg", None) if isinstance(getattr(agent, "cfg", None), dict) else {}, logf, agent.log, sleep)
    except Exception: pass
    st = {}
    for _ in range(8):
        sleep(1.0)
        try: st = state(link)
        except extlink.ExtError: continue
        if st.get("title"): break
    if st.get("paused"):
        try: link.call("media_control", timeout=10, op="play")
        except extlink.ExtError: pass
    title = st.get("title") or r.get("title"); agent.last_played = {"url": st.get("url") or r.get("href"), "title": title}
    where = f"the results for \"{topic}\"" if topic else "the YouTube home page"
    return f"Playing video #{n if n > 0 else len(res)} from {where}: \"{title}\"" + (f" by {st['channel']}" if st.get("channel") else "") + "."
