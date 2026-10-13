"""Benchmark vision models on one static screenshot (no computer control).
usage: python tools/bench.py IMAGE model1 [model2 ...] [--runs 3] [--width 1024] [--predict 160] [--old]"""
import sys, os, time, json, argparse, base64, io, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image
import screen, core
from actions import parse_action, ActionError

p = argparse.ArgumentParser(); p.add_argument("image"); p.add_argument("models", nargs="+")
p.add_argument("--runs", type=int, default=3); p.add_argument("--width", type=int, default=1024)
p.add_argument("--predict", type=int, default=160); p.add_argument("--old", action="store_true", help="old settings: 1280px, no keep_alive/num_predict")
p.add_argument("--task", default="open Safari, search for youtube.com, and click on the first video")
a = p.parse_args()
H = "http://localhost:11434"
raw = Image.open(a.image).convert("RGB")
import random
from PIL import ImageDraw
def make_img(i, grid=100):
    """Slightly different image each run so Ollama can't reuse its cache (like real steps)."""
    im = raw.copy(); d = ImageDraw.Draw(im)
    x, y = random.randint(0, im.width - 400), random.randint(0, im.height - 120)
    d.rectangle([x, y, x + 400, y + 120], fill=(random.randint(0, 255),) * 3); d.text((x + 10, y + 10), f"run {i} {time.time()}", fill=(255, 0, 0))
    out, _ = screen.prepare(im, 1280 if a.old else a.width, grid)
    buf = io.BytesIO(); out.save(buf, "PNG"); return out, base64.b64encode(buf.getvalue()).decode()
img, _ = make_img(0)
prompt = f"TASK: {a.task}\nStep 1. Image size {img.width}x{img.height}.\nRecent actions and results:\n(none yet)\nWhat is the single next action? JSON only."
for m in a.models:
    lat, ok, outs = [], 0, []
    tok = []; errs = []; outs_full = []
    for i in range(a.runs + 1):  # first run = cold/warm-up
        _, b64 = make_img(i, 0 if "qwen3-vl" in m else 100)
        body = {"model": m, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": (core.NORM_SYSTEM if "qwen3-vl" in m else core.SYSTEM)}, {"role": "user", "content": prompt, "images": [b64]}],
                "options": {"temperature": 0.1}}
        if not a.old: body["keep_alive"] = "30m"; body["options"]["num_predict"] = a.predict; body["think"] = False
        t = time.time()
        try:
            r = requests.post(H + "/api/chat", json=body, timeout=600).json(); txt = r["message"]["content"]
            if i: tok.append((round(r.get("prompt_eval_duration", 0) / 1e9, 1), round(r.get("eval_duration", 0) / 1e9, 1), r.get("eval_count")))
        except Exception as e:
            txt = f"ERR {e}"
        dt = time.time() - t
        if i == 0: cold = dt; continue
        lat.append(dt); outs.append(txt[:120]); outs_full.append(txt)
        try: parse_action(txt); ok += 1
        except ActionError as e: errs.append(str(e)[:80])
    print(json.dumps({"model": m, "cold_s": round(cold, 1), "warm_avg_s": round(sum(lat) / len(lat), 1),
                      "warm_min_s": round(min(lat), 1), "valid_json": f"{ok}/{a.runs}", "prefill_s,gen_s,tokens": tok, "sample": outs[0], "errors": errs, "all": outs_full}), flush=True)
