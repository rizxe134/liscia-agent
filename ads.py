"""2.1.1: auto ad-skip while playing media. Extension 2.1.1+: an in-page watcher clicks Skip / closes overlays / mutes
unskippable ads. Older extensions: the agent finds the Skip button in the page snapshot and clicks it."""
import json, re, time
import extlink

SKIP = re.compile(r"^\s*skip(\s+ads?)?\s*[>›»]?\s*$", re.I)
AD_MARK = re.compile(r"^(ad|sponsored)\s*[·•]|\bvisit advertiser\b|^ad \d+ of \d+|^skip ad", re.I)

def shown(x):
    b = x.get("bbox") or [0, 0, 1, 1]
    return len(b) < 4 or (b[2] > 0 and b[3] > 0)
CLOSE = re.compile(r"^(close( ad)?|dismiss|no thanks)$", re.I)

def settings(cfg):
    m = (cfg or {}).get("media") or {}
    return m.get("auto_skip_ads", True), m.get("mute_ads", True)

def handle(link, cfg, logf=None, log=print, sleep=time.sleep, max_wait=60):
    """Wait out / skip ads on the current video page. Returns {"ad": bool, "skipped": n, "waited": s, "via": "..."}."""
    on, mute = settings(cfg)
    rep = {"ad": False, "skipped": 0, "closed": 0, "waited": 0.0, "via": "off" if not on else ""}
    if not on: return rep
    t0 = time.time()
    try:
        link.call("ad_watch", timeout=10, mute=mute); rep["via"] = "extension"
        while time.time() - t0 < max_wait:
            st = link.call("ad_state", timeout=10) or {}
            rep["skipped"], rep["closed"] = st.get("skipped", 0), st.get("closed", 0)
            if st.get("ad"): rep["ad"] = True; sleep(0.8); continue
            break
    except extlink.ExtError as e:
        if "not connected" in str(e): raise
        rep["via"] = "snapshot"  # older extension: no in-page watcher
        stale = 0
        while time.time() - t0 < max_wait:
            try: snap = link.call("snapshot", max=150)
            except extlink.ExtError: break
            els = snap.get("elements") or []
            skip = next((x for x in els if SKIP.match(x.get("label") or "") and shown(x) and not x.get("below")), None)
            ad = skip is not None or any(AD_MARK.search(x.get("label") or "") and shown(x) for x in els)
            for x in els:
                if CLOSE.match(x.get("label") or "") and re.search(r"ad|overlay|promo", json.dumps(x), re.I):
                    try: link.call("click", timeout=10, id=x["id"]); rep["closed"] += 1
                    except extlink.ExtError: pass
            if skip:
                if stale >= 2: break  # the same "Skip" keeps showing after clicks: not an ad button
                try:
                    link.call("click", timeout=10, id=skip["id"]); sleep(0.8)
                    after = link.call("snapshot", max=150).get("elements") or []
                    if any(SKIP.match(x.get("label") or "") and shown(x) and not x.get("below") for x in after): stale += 1
                    else: rep["skipped"] += 1; stale = 0; log("[media] skipped an ad")
                except extlink.ExtError: pass
            if not ad: break
            rep["ad"] = True; sleep(1.0)
    rep["waited"] = round(time.time() - t0, 1)
    if logf: logf.write(json.dumps({"ads": rep}) + "\n")
    return rep
