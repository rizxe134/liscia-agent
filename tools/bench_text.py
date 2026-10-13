"""Benchmark the non-vision fast path (page element list -> text model). usage: python tools/bench_text.py model..."""
import sys, os, time, json, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core, browser_dom
from actions import parse_action, ActionError
els = [{"id": i, "tag": t, "type": "", "text": x, "x": 0, "y": 0} for i, (t, x) in enumerate(
    [("a", "YouTube Home"), ("input", "Search"), ("button", "Search"), ("a", "Shorts"), ("a", "Subscriptions")] +
    [("a", f"Video {n}: lofi hip hop radio - beats to relax/study to") for n in range(1, 30)] + [("button", "Sign in")])]
snap = {"app": "Safari", "url": "https://www.youtube.com/", "title": "YouTube", "elements": els}
task = "open Safari, search for youtube.com, and click on the first video"
hist = '1: {"action": "open_url", "url": "https://youtube.com", "browser": "Safari"} -> screen changed'
for m in sys.argv[1:]:
    lat, ok, out = [], 0, ""
    for i in range(4):
        prompt = browser_dom.format_elements(snap) + f"\n\nTASK: {task}\nStep {i+2}. (No screenshot this step: use the element list.)\nRecent actions and results (oldest first):\n{hist}\nrun {i} {time.time()}\nWhat is the single next action? JSON only."
        body = {"model": m, "stream": False, "format": "json", "keep_alive": "30m", "think": False,
                "messages": [{"role": "system", "content": core.SYSTEM}, {"role": "user", "content": prompt}],
                "options": {"temperature": 0.1, "num_predict": 200}}
        t = time.time(); r = requests.post("http://localhost:11434/api/chat", json=body, timeout=300).json(); dt = time.time() - t
        txt = r.get("message", {}).get("content", str(r))
        if i == 0: continue
        lat.append(dt); out = txt
        try: a = parse_action(txt); ok += a["action"] == "click_element" and a["id"] == 5
        except ActionError: pass
    print(json.dumps({"model": m, "warm_avg_s": round(sum(lat)/len(lat), 2), "correct_click_first_video": f"{ok}/3", "sample": out[:110]}), flush=True)
