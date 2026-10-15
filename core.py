"""The screenshot -> model -> action loop."""
import json, os, re, time, datetime, yaml
import sys
import screen
import browser_dom
import intents
from actions import NeedsVision
IS_MAC = sys.platform == "darwin"
OS_NAME = "macOS" if IS_MAC else "Windows"
MOD = "cmd" if IS_MAC else "ctrl"
from actions import parse_action, Executor, is_risky, ActionError
from llm import OllamaClient
from safety import KillSwitch, console_confirm
import safety, policy

SYSTEM = """You are a computer-use agent controlling a {os} computer with mouse and keyboard.
Each turn you get a screenshot with a red/blue coordinate grid (numbers are pixel coordinates in THIS image),
the task, a plan, and your recent actions WITH THEIR RESULTS.
Reply with EXACTLY ONE JSON object and nothing else:
{"thought": "<max 20 words: what the screen shows now>", "action": "<name>", ...params at top level, "reason": "<max 10 words>"}
Actions (PREFER the high-level ones at the top):
 open_app: "app" (e.g. "Safari", "Notes") - launches/focuses an application
 open_url: "url", optional "browser" (e.g. "Safari", "Google Chrome") - opens a website directly
 web_search: "query", optional "browser" - opens DuckDuckGo results for the query
 click_element: "id" - click an element from the CLICKABLE ELEMENTS / ELEMENTS list (web page or app window, when a list is given)
 type_element: "id", "text", optional "press_enter" - type into a text field from the app ELEMENTS list
 click/double_click/right_click/move: "x", "y" (pixel coordinates in the screenshot)
 type: "text", "press_enter": true/false, "sensitive": true if it is a password/secret
 hotkey: "keys": ["{mod}","l"]  (the main shortcut modifier on this OS is {mod})
 scroll: "amount" (negative = down, positive = up), optional "x","y"
 wait: "seconds"
 look: take a screenshot next step (use when the element list is not enough)
 done: "summary" of the result
Rules:
- To open an app use open_app, NOT Spotlight/Start menu. To visit a website use open_url, NOT typing in a search box.
- Typing into a search box, Spotlight or the URL bar does nothing until Enter: set "press_enter": true.
- NEVER repeat the same action if it did not work. If the screen did not change, try something DIFFERENT.
- Look at the screenshot to verify the previous step worked before moving on.
- If a CLICKABLE ELEMENTS list is given, prefer click_element over coordinates.
- Click the CENTER of elements. Click a text field before typing.
- When the task is complete, use done. Never guess passwords."""

SYSTEM = SYSTEM.replace("{os}", OS_NAME).replace("{mod}", MOD)

PLANNER = """Break the user's computer task into 2-6 short, concrete steps for a {os} computer agent.
Prefer: open_app to launch apps, open_url to visit sites, web_search to search. One step per line, numbered. No extra text."""

NORM_SYSTEM = (SYSTEM
    .replace("with a red/blue coordinate grid (numbers are pixel coordinates in THIS image)",
             "(coordinates are NORMALIZED 0-1000: x=0 left edge, x=1000 right edge, y=0 top, y=1000 bottom)")
    .replace('"x", "y" (pixel coordinates in the screenshot)', '"x", "y" (normalized 0-1000)'))

def uses_norm_coords(cfg):
    """qwen3-vl (and similar) natively output 0-1000 normalized coordinates."""
    mode = cfg.get("agent", {}).get("coord_mode", "auto")
    if mode == "auto":
        return "qwen3-vl" in cfg.get("ollama", {}).get("model", "").lower()
    return mode == "norm1000"

def denormalize(act, w, h):
    """Convert 0-1000 coords to image pixels (in place copy)."""
    a = dict(act)
    if "x" in a and "y" in a:
        a["x"] = int(round(float(a["x"]) * w / 1000.0)); a["y"] = int(round(float(a["y"]) * h / 1000.0))
    return a

def to_points(nx, ny, w, h, scale, ratio):
    """0-1000 -> screenshot image px (w,h) -> real screen px (*scale) -> points (*ratio)."""
    return int(round(nx * w / 1000.0 * scale * ratio)), int(round(ny * h / 1000.0 * scale * ratio))

def load_config(path=None):
    if path is None:
        import paths; path = paths.config_path()
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def action_signature(a):
    """Identity of an action for loop detection (coords bucketed to 20px)."""
    keep = {k: v for k, v in a.items() if k in ("action", "text", "keys", "url", "query", "app", "amount", "press_enter")}
    if "x" in a:
        keep["xy"] = (int(a["x"]) // 20, int(a["y"]) // 20)
    return json.dumps(keep, sort_keys=True, default=str)

class LoopGuard:
    """Counts consecutive identical actions. level: 0 ok, 1 warn, 2 block (skip & force new strategy), 3 stop."""
    def __init__(self, warn=2, block=3, stop=5):
        self.warn, self.block, self.stop = warn, block, stop
        self.last, self.count = None, 0

    def check(self, act):
        sig = action_signature(act)
        if act.get("action") == "type":  # retyping the same text is a repeat even if the screen changed
            self.typed = getattr(self, "typed", {}); k = act.get("text", "").strip().lower()
            self.typed[k] = self.typed.get(k, 0) + 1
            if self.typed[k] > 1:
                self.count = max(self.count + 1 if sig == self.last else 1, self.typed[k]); self.last = sig
                return 3 if self.count >= self.stop else 2 if self.count >= self.block else 1
        self.count = self.count + 1 if sig == self.last else 1
        self.last = sig
        if self.count >= self.stop: return 3
        if self.count >= self.block: return 2
        if self.count >= self.warn: return 1
        return 0

class Agent:
    def __init__(self, cfg, confirm=console_confirm, log=print, gui=None, capture=None, client=None, executor=None, dom=None):
        self.cfg, self.confirm, self.log = cfg, confirm, log
        self.media_runner = None
        o, s = cfg["ollama"], cfg["safety"]
        self.client = client or OllamaClient(o["host"], o["model"], o.get("fallback_model", ""),
                                             o.get("temperature", 0.1), o.get("timeout_s", 180),
                                             text_model=o.get("text_model", ""), keep_alive=o.get("keep_alive", "30m"),
                                             num_predict=o.get("num_predict", 200), num_ctx=o.get("num_ctx"))
        self.on_token = None  # UI sets this to stream model output
        use_dom = cfg["agent"].get("browser_dom", True) and IS_MAC
        self.dom = dom if dom is not None else (browser_dom.BrowserDOM(cfg["agent"].get("max_elements", 60), log=log) if use_dom else None)
        if gui is None:
            import pyautogui as gui
            gui.FAILSAFE = s.get("failsafe", True); gui.PAUSE = 0.05
        self.gui, self.capture = gui, capture or screen.capture
        self.on_highlight = None  # side panel hook: on_highlight(x=..., y=..., space="screen_points")
        self._injected_exec = executor is not None
        self._mk = executor or (lambda scale: Executor(self.gui, scale, cfg["agent"].get("move_duration_s", 0.25), dom=self.dom))
        self.make_executor = self._executor
        self.kill = KillSwitch(s.get("kill_keys", ["esc", "f12"]))
        self._page = (None, None)
        self.ext = None  # tests can inject an ExtensionLink
        intents.STATE["preferred"] = cfg["agent"].get("preferred_browser") or None

    def _executor(self, scale):
        ex = self._mk(scale)
        if self.on_highlight and hasattr(ex, "on_click") and not isinstance(getattr(type(ex), "on_click", None), property):
            try: ex.on_click = lambda x, y: (self.on_highlight(x=x, y=y, space="screen_points"), time.sleep(0.35))
            except Exception: pass
        return ex

    def link(self):
        import extlink
        return self.ext or extlink.LINK

    def use_extension(self, task=None):
        """Route to the extension when it's connected and the task is a web task in Chrome
        (the user didn't name another browser)."""
        if not self.cfg["agent"].get("chrome_extension", True): return False
        if not self.link().connected(): return False
        named = intents.named_browser(task) if task is not None else intents.STATE.get("named")
        if named and named != "Google Chrome": return False
        return True if task is None else intents.is_web_task(task)

    def live_tab(self):
        """(url, title) of Chrome's active tab as reported by the extension, or None."""
        try:
            tabs = self.link().call("tabs", timeout=5) or []
            t = next((t for t in tabs if t.get("active")), tabs[0] if tabs else None)
            return (t.get("url", ""), t.get("title", "")) if t else None
        except Exception:
            return None

    def focus_chrome(self):
        if not IS_MAC: return
        try:
            import subprocess; subprocess.run(["open", "-a", "Google Chrome"], timeout=5, capture_output=True)
        except Exception: pass

    def fix_browser(self, act):
        """Never switch to another browser unless the user named it: default web browser = Google Chrome."""
        allowed = intents.STATE.get("named") or "Google Chrome"
        a = dict(act)
        if a.get("action") == "open_app":
            app = intents.APP_NAMES.get(str(a.get("app", "")).lower().strip(), a.get("app"))
            if app in intents.BROWSERS_SET and app != allowed: a["app"] = allowed
        if a.get("action") in ("open_url", "web_search") and a.get("browser"):
            b = intents.BROWSER_NAMES.get(str(a["browser"]).lower().strip(), a["browser"])
            if b != allowed: a["browser"] = allowed
            else: a["browser"] = b
        return a

    ANSWER_SYSTEM = ("You answer the user's question using ONLY the web page text given. Today is {today}; 'now'/'current' means today, "
                     "never an older year from your memory. Reply with ONE JSON object: "
                     '{{"answer": "<clear, complete answer, use a short numbered list when asked for a list; mention the source/date if the text gives one>"}} '
                     'or, if the text does not contain the answer, {{"answer": "", "need_more": true}}.')

    def _answer_from(self, question, text, url):
        import webagent
        sys_p = self.ANSWER_SYSTEM.format(today=webagent.today())
        raw = self.client.text_chat([{"role": "system", "content": sys_p},
                                     {"role": "user", "content": f"QUESTION: {question}\nPAGE ({url[:100]}):\n{text}"}],
                                    json_mode=True, num_predict=self.cfg["agent"].get("answer_tokens", 350))
        try:
            obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except ValueError:
            return (raw or "").strip() if raw and "{" not in raw else ""
        ans = str(obj.get("answer") or "").strip()
        return "" if obj.get("need_more") and not ans else ans

    def answer_question(self, link, question, logf, max_pages=2):
        """Read the results page; answer. If it isn't enough, open the top real result and answer from that."""
        import webagent
        t0 = time.time(); time.sleep(1.0)
        limit = self.cfg["agent"].get("answer_chars", 2500)
        for page in range(max_pages):
            text = webagent.main_text(link, limit); url = ""
            try: snap = link.call("snapshot", max=60); url = snap.get("url", "")
            except Exception: snap = {}
            self.log(f"[web] reading {url[:80]} ({len(text)} chars)")
            ans = self._answer_from(question, text, url) if text else ""
            logf.write(json.dumps({"answer_try": page + 1, "url": url, "chars": len(text), "answer": ans[:500], "secs": round(time.time() - t0, 1)}) + "\n")
            if ans: return ans
            if page + 1 >= max_pages: break
            top = webagent.top_result(snap)
            if not top: break
            self.log(f"[web] not enough on the results page - opening \"{top['label'][:60]}\"")
            webagent.nav(link, top["href"], self.log); time.sleep(1.5)
        return "I searched but couldn't find a clear answer on the page."

    EXTRACT_SYSTEM = ("You turn web page text into a document. Today is {today}. Use ONLY facts in the text. Reply with ONE JSON object: "
                      '{{"title": "<short title>", "summary": "<3-6 sentence summary answering the request>", '
                      '"columns": ["Rank", "Name", ...], "rows": [["1", "...", ...], ...]}}. '
                      "Include up to {n} rows if the text has them, in the page's order. No rows if the request isn't a list.")

    def extract_data(self, request, text, url, n):
        import webagent
        sys_p = self.EXTRACT_SYSTEM.format(today=webagent.today(), n=n or 25)
        raw = self.client.text_chat([{"role": "system", "content": sys_p},
                                     {"role": "user", "content": f"REQUEST: {request}\nPAGE ({url[:120]}):\n{text}"}],
                                    json_mode=True, num_predict=self.cfg["agent"].get("extract_tokens", 1400))
        try:
            obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except ValueError:
            return {"title": request, "summary": (raw or "").strip()[:2000], "columns": [], "rows": []}
        rows = [r if isinstance(r, list) else list(r.values()) if isinstance(r, dict) else [r] for r in (obj.get("rows") or [])]
        cols = obj.get("columns") or []
        if not cols and rows and isinstance((obj.get("rows") or [None])[0], dict): cols = list(obj["rows"][0].keys())
        return {"title": str(obj.get("title") or request), "summary": str(obj.get("summary") or ""), "columns": [str(c) for c in cols],
                "rows": rows[: n or len(rows)]}

    REPORT_SYSTEM = ("You write a short factual report from a data table. Use ONLY the table and summary given. Reply with ONE JSON object: "
                     '{"intro": "<3-5 sentence introduction>", "items": [{"name": "<item name>", "text": "<2-3 sentences about it using its row>"}], '
                     '"conclusion": "<1-2 sentences>"}. One item per table row, same order.')

    def write_report(self, request, data):
        """One model call: intro + a short paragraph per row + conclusion, for the Word report."""
        table = " | ".join(data["columns"]) + "\n" + "\n".join(" | ".join(r) for r in data["rows"])
        try:
            raw = self.client.text_chat([{"role": "system", "content": self.REPORT_SYSTEM},
                                         {"role": "user", "content": f"REQUEST: {request}\nSUMMARY: {data['summary']}\nTABLE:\n{table}"}],
                                        json_mode=True, num_predict=self.cfg["agent"].get("report_tokens", 1800))
            obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            items = [i for i in (obj.get("items") or []) if isinstance(i, dict)]
            return {"intro": str(obj.get("intro") or data["summary"]), "items": items, "conclusion": str(obj.get("conclusion") or "")}
        except Exception as e:
            self.log(f"[doc] report text unavailable ({type(e).__name__}); using the summary")
            return None

    def make_binding(self, app):
        """WindowBinding for the launched app (None where unsupported, e.g. tests with an injected executor)."""
        if getattr(self, "binding_factory", None): return self.binding_factory(app)
        if not (sys.platform.startswith("win") or IS_MAC) or getattr(self, "_injected_exec", False): return None
        import winbind, appindex
        try: entry = appindex.find(app)
        except Exception: entry = None
        return winbind.WindowBinding(app, entry, log=self.log)

    def research_to_document(self, task, out, logf):
        """Web research through the extension, then a local .docx/.xlsx/.txt with the results (opened in the default app)."""
        import webagent, docmaker, urllib.parse
        link = self.link(); intents.note_app("Google Chrome"); self.focus_chrome()
        if out.get("query"):
            q, site, n = out["query"], (out.get("site") or "").lower() or None, out.get("count") or intents.requested_count(task)
            if site and site.startswith("http"): site = webagent.host(site).split(".")[0]
        else:
            site, q = intents.research_query(out["research"]); n = intents.requested_count(task)
        t0 = time.time()
        search = "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)
        webagent.nav(link, search, self.log); time.sleep(1.5)
        logf.write(json.dumps({"web_fast": {"action": "open_url", "url": search}}) + "\n")
        snap = link.call("snapshot", max=80)
        results_text = webagent.main_text(link, 3000)
        pick = None
        for e in snap.get("elements") or []:
            h = e.get("href") or ""
            if site and e.get("role") == "link" and h.startswith("http") and site in webagent.host(h) and len((e.get("label") or "").split()) >= 2:
                pick = e; break
        if not pick:  # prefer well-known reliable sources among the results
            trusted = re.compile(r"(^|\.)(globalfirepower\.com|forbes\.com|bloomberg\.com|reuters\.com|wikipedia\.org|apnews\.com|bbc\.(com|co\.uk)|\w+\.gov|"
                                 r"britannica\.com|statista\.com|who\.int|worldbank\.org|cnbc\.com|nytimes\.com)$")
            for e in snap.get("elements") or []:
                h = e.get("href") or ""
                if e.get("role") == "link" and h.startswith("http") and trusted.search(webagent.host(h)) and len((e.get("label") or "").split()) >= 2 \
                        and not webagent.is_junk(e):
                    pick = e; break
        pick = pick or webagent.top_result(snap)
        text, url = results_text, snap.get("url", search)
        if pick:
            self.log(f"[web] opening \"{pick['label'][:70]}\"")
            webagent.nav(link, pick["href"], self.log); time.sleep(3.0)
            try:
                link.call("scroll", timeout=12, direction="down", wait_lazy=True); link.call("scroll", timeout=12, direction="up", amount=-100000)
            except Exception: pass
            try:
                page = webagent.main_text(link, self.cfg["agent"].get("doc_chars", 9000))
                if len(page) > 400: text, url = page, link.call("snapshot", max=5).get("url", pick["href"])
            except Exception as e:
                self.log(f"[web] couldn't read {pick['href'][:60]}: {e}")
        logf.write(json.dumps({"read": url, "chars": len(text)}) + "\n")
        self.log(f"[web] extracting data from {url[:80]} ({len(text)} chars)")
        request = out.get("research") or q
        if out.get("columns"): request += " (columns: " + ", ".join(out["columns"]) + ")"
        data = self.extract_data(request, text, url, n)
        if n and len(data["rows"]) < min(n, 5) and text is not results_text:
            data2 = self.extract_data(request, results_text, search, n)
            if len(data2["rows"]) > len(data["rows"]): data, url = data2, search
        saved = []; kinds = out.get("kinds") or [out["kind"]]
        report = self.write_report(task, data) if "docx" in kinds and data["rows"] and re.search(r"\breport|essay|write[- ]?up|explain|describe|detail", task, re.I) else None
        if report: logf.write(json.dumps({"report": {"items": len(report.get("items") or []), "secs": round(time.time() - t0, 1)}}) + "\n")
        for kind in kinds:  # several outputs from the same extracted data
            path = docmaker.make(kind, out.get("name") or out.get("title") or data["title"], data["summary"], data["columns"], data["rows"], source=url,
                                 report=report if kind == "docx" else None)
            opened = docmaker.open_file(path); saved.append((path, opened))
            logf.write(json.dumps({"document": path, "rows": len(data["rows"]), "opened": opened, "secs": round(time.time() - t0, 1)}) + "\n")
        names = ", ".join(str(r[1] if len(r) > 1 else r[0]) for r in data["rows"][:5])
        return ("\n".join(f"Saved {len(data['rows'])} rows to {p}" + (" (opened)" if o else "") for p, o in saved) + "\n\n" + data["summary"] +
                (f"\n\nFirst entries: {names}" if names else ""))

    def run_via_extension(self, task, history, logf):
        """Deterministic steps through the extension (navigate / YouTube search / first video), then webagent."""
        import webagent
        link = self.link(); intents.note_app("Google Chrome"); self.focus_chrome()
        fixed, rest = intents.plan(task) if self.cfg["agent"].get("intents", True) else ([], task)
        done = []
        for act in fixed:
            if self.kill.killed: return "stopped by user"
            if act["action"] == "open_app":
                if act["app"] in intents.BROWSERS_SET: done.append("open Google Chrome (done)"); continue
                rest = " and ".join([f"open {act['app']}"] + ([rest] if rest else [])); raise NeedsVision("non-browser app in task")
            if act["action"] == "open_url":
                res = webagent.nav(link, act["url"], self.log)
                self.log(f"[web] navigate {act['url']} -> {(res.get('title') or '')[:60]}")
            elif act["action"] == "answer_from_page":
                logf.write(json.dumps({"web_fast": act}) + "\n")
                return self.answer_question(link, act.get("question") or task, logf)
            elif act["action"] == "first_video":
                time.sleep(1.0); res = None
                if act.get("match"):  # a specific title: search the whole results list, scrolling for lazy-loaded items
                    found = webagent.scroll_find(link, act["match"], self.log, max_scrolls=self.cfg["agent"].get("max_scrolls", 8))
                    if found:
                        res = link.call("click", timeout=25, id=found["id"]) or {}
                        self.log(f"[web] clicked \"{(found.get('label') or '')[:60]}\"")
                if res is None:
                    res = link.call("first_video", timeout=20) or {}
                    self.log(f"[web] first video -> {(res.get('clicked') or '')[:60]}")
            logf.write(json.dumps({"web_fast": act}) + "\n"); done.append(f"{act['action']} {act.get('url','')}".strip() + " (done)")
        if fixed and not rest:
            return "done: " + "; ".join(done)
        history += [f"(already done) {d}" for d in done]
        return webagent.run_web(self, rest or task, history, logf, link=link, max_steps=self.cfg["agent"].get("max_steps", 40))

    def wait_page_change(self, act, timeout=8.0):
        """Mark a sub-step done when the front tab's URL/title changes (AppleScript); else fixed wait."""
        before = self._page
        if act["action"] == "open_app" or not IS_MAC:
            time.sleep(self.cfg["agent"].get("page_wait_s", 2.0)); return
        t0 = time.time()
        while time.time() - t0 < timeout:
            url, title = intents.page_info()
            if url is None: time.sleep(self.cfg["agent"].get("page_wait_s", 2.0)); return
            if (url, title) != before and "about:blank" not in url and title is not None:
                self._page = (url, title); self.log(f"   page: {title[:60]} | {url[:90]}"); time.sleep(0.8); return
            time.sleep(0.4)

    def locate_and_click_first_video(self, run_dir):
        """Vision fallback: ask ONLY where the first video thumbnail is, convert 0-1000 -> image px -> points, click."""
        try:
            raw_img = self.capture()
            img, scale = screen.prepare(raw_img, self.cfg["agent"].get("screenshot_width", 1280), 0)
            ratio = screen.point_ratio(self.gui, raw_img.width)
            img.save(os.path.join(run_dir, "first_video_locate.png"))
            raw = self.client.chat("You locate things on screenshots. Reply JSON only: {\"x\": <0-1000>, \"y\": <0-1000>}.",
                                   "Where is the center of the FIRST video thumbnail in the list of video results "
                                   "(skip ads/shorts/sponsored)? Coordinates normalized 0-1000 relative to the image.", img)
            obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            nx, ny = float(obj["x"]), float(obj["y"])
            if not (0 <= nx <= 1000 and 0 <= ny <= 1000): raise ValueError(f"out of range {nx},{ny}")
            px, py = to_points(nx, ny, img.width, img.height, scale, ratio)
            self.log(f"[fast] first video via vision: norm=({nx:.0f},{ny:.0f}) image={img.width}x{img.height} "
                     f"-> img_px=({nx*img.width/1000:.0f},{ny*img.height/1000:.0f}) screen_px=({px/ratio:.0f},{py/ratio:.0f}) "
                     f"-> points=({px},{py}) [scale={scale:.3f}, pt_ratio={ratio:.3f}]")
            if IS_MAC: self._page = intents.page_info()
            if self.on_highlight: self.on_highlight(x=px, y=py, space="screen_points"); time.sleep(0.35)
            self.gui.moveTo(px, py, duration=0.2); self.gui.click(px, py)
            self.wait_page_change({"action": "first_video"})
            return True
        except Exception as e:
            self.log(f"[fast] vision locate failed ({e})"); return False

    def make_plan(self, task):
        try:
            msgs = [{"role": "system", "content": PLANNER.replace("{os}", OS_NAME)}, {"role": "user", "content": task}]
            plan = self.client.text_chat(msgs, num_predict=150).strip()
            return "\n".join(plan.splitlines()[:8])
        except Exception as e:
            self.log(f"(planning skipped: {e})"); return ""

    def run(self, task):
        a_cfg, s_cfg = self.cfg["agent"], self.cfg["safety"]
        import paths
        run_dir = os.path.join(paths.runs_dir(a_cfg.get("runs_dir", "runs")), datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        logf = open(os.path.join(run_dir, "log.jsonl"), "a", encoding="utf-8")
        logf.write(json.dumps({"task": task}) + "\n")
        history, result, notes = [], "max steps reached", []
        guard = LoopGuard(a_cfg.get("loop_warn", 2), a_cfg.get("loop_block", 3), a_cfg.get("loop_stop", 5))
        prev_hash, last_idx, force_look = None, None, False
        bad_streak, last_bad = 0, None
        opens = {}; same_clicks, last_click = 0, None; blocked_opens = 0
        norm = uses_norm_coords(self.cfg)
        system = NORM_SYSTEM if norm else SYSTEM
        orig_task = task
        self.kill.start(); self.log(f"Task: {task}\nRun folder: {run_dir}\nAbort: Esc/F12, STOP, or slam mouse into a screen corner.")
        intents.STATE["named"] = intents.named_browser(task)
        # PLAN: one fast model call (validated by code) decides what kind of task this is
        import planner
        ext_ok = self.cfg["agent"].get("chrome_extension", True) and self.link().connected()
        t_plan = time.time()
        pl = planner.plan(self.client, task, use_model=a_cfg.get("planner", True), log=self.log)
        # APP-FIRST (1.4.4): a task that names an installed/running app is about that app, never its website
        try:
            import appfirst, commands
            if a_cfg.get("app_first", True):
                pl, why = appfirst.override(pl, task, idx=getattr(self, "app_index", None), running=getattr(self, "running_apps", None),
                                            is_command=bool(commands.parse(task, "x")))
                if why: self.log(f"[plan] {why}"); logf.write(json.dumps({"app_first": why}) + "\n")
        except Exception as e:
            self.log(f"[plan] app-first check skipped ({type(e).__name__})")
        self.plan_info = pl
        logf.write(json.dumps({"plan": pl, "secs": round(time.time() - t_plan, 1)}) + "\n")
        self.log(f"[plan] {pl['intent']}" + (f" -> {', '.join(pl['outputs'])}" if pl["outputs"] else "") + (f" | {pl['query']}" if pl.get("query") else "") +
                 f" ({time.time() - t_plan:.1f}s, {pl.get('source')})")
        def finish(result):
            self.kill.stop(); logf.close(); self.log(f"Result: {result}"); return result
        if pl["intent"] == "web_research_to_files":
            if not ext_ok:
                return finish("stopped: this needs the Chrome extension to read the web. Open Chrome, open the Liscia Agent panel "
                              "(it should say 'page control ON'), then ask again.")
            try:
                return finish(self.research_to_document(task, {"kinds": pl["outputs"], "query": pl["query"], "site": pl.get("site"),
                                                              "count": pl.get("count"), "columns": pl.get("columns"), "title": pl.get("title")}, logf))
            except Exception as e:
                logf.write(json.dumps({"doc_error": str(e)}) + "\n")
                return finish(f"stopped: couldn't finish the research/document task ({type(e).__name__}: {e})")
        if pl["intent"] == "web_answer" and ext_ok:
            try:
                import webagent, urllib.parse
                intents.note_app("Google Chrome"); self.focus_chrome()
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(pl["query"] or task)
                webagent.nav(self.link(), url, self.log); logf.write(json.dumps({"web_fast": {"action": "open_url", "url": url}}) + "\n")
                return finish(self.answer_question(self.link(), task, logf))
            except Exception as e:
                logf.write(json.dumps({"web_error": str(e)}) + "\n")
                return finish(f"stopped: the Chrome extension step failed ({type(e).__name__}: {e})")
        try:  # "pause the music" / "next song" with no app named: the system's current media session
            import commands, appfirst
            c0 = commands.parse(task, "")
            if c0 and c0["kind"] == "media" and not (pl["intent"] == "desktop_app" and pl.get("app")) and not appfirst.explicit_web(task):
                logf.write(json.dumps({"command": c0, "app": ""}) + "\n")
                res = (self.media_runner or commands.run_media)(c0["verb"], "")
                logf.write(json.dumps({"command_result": res}) + "\n"); return finish(res)
        except Exception as e:
            self.log(f"[app] media command check failed ({type(e).__name__})")
        self.desktop_only = pl["intent"] == "desktop_app"
        self.app_binding = None
        self.desktop_app_name = pl.get("app", "") if self.desktop_only else ""
        skip_fast = False
        if pl["intent"] == "desktop_app":
            import policy
            app = pl.get("app") or ""
            lbl = policy.core_app(app) or policy.core_app(*re.findall(r"control panel|regedit|registry editor|task manager|services\.msc|gpedit|"
                                                                      r"command prompt|powershell|windows terminal|activity monitor|system settings|system preferences", task, re.I))
            if not lbl and re.search(r"\b(open|launch|start|go to|use)\s+(?:the\s+|my\s+)?(?:windows\s+|system\s+)?settings\b", task, re.I): lbl = "Settings"
            if lbl:
                logf.write(json.dumps({"blocked": lbl}) + "\n")
                return finish(policy.message(lbl))
            if app:
                import adapters, winbind, commands, appfirst
                t0 = time.time()
                # UNIVERSAL CONTROLS (1.4.4): media / window / standard app actions for any app, no model call
                cmd = commands.parse(task, app)
                if cmd:
                    logf.write(json.dumps({"command": cmd, "app": app}) + "\n")
                    self.log(f"[app] {cmd['kind']} command '{cmd['verb']}' for {app}")
                    if cmd["kind"] == "media":
                        res = (self.media_runner or commands.run_media)(cmd["verb"], app)
                        logf.write(json.dumps({"command_result": res}) + "\n")
                        return finish(res)
                    binding = self.make_binding(app)
                    if binding is None or not binding.bind(timeout=3):
                        return finish(f"stopped: {app} isn't open, so there's no window to {cmd['verb'].replace('_', ' ')}.")
                    self.app_binding = binding
                    logf.write(json.dumps({"bound_window": {k: binding.info.get(k) for k in ("hwnd", "title", "proc", "pid")}}) + "\n")
                    res = commands.run_window(cmd["verb"], binding, confirm=self.confirm) if cmd["kind"] == "window" else \
                        commands.run_action(cmd["verb"], binding, gui=self.gui, confirm=self.confirm)
                    logf.write(json.dumps({"command_result": res}) + "\n")
                    return finish(res)
                adapter = adapters.for_app(app, task)
                # RUNNING APP (1.4.4): bind to its existing main window instead of relaunching
                pre, pre_w = None, None
                if not (adapter and adapter.launch_uri):
                    pre = self.make_binding(app)
                    pre_w = pre.bind(timeout=0.5) if pre is not None else None
                    if not pre_w: pre = None
                try:
                    if pre is not None:
                        info = f"{app} is already running; using its window"
                        self.log(f"[app] {info}"); logf.write(json.dumps({"app_running": app}) + "\n")
                    elif adapter and adapter.launch_uri:
                        adapters.open_uri(adapter.launch_uri); info = f"opened {adapter.launch_uri}"
                    else:
                        ex = self.make_executor(1.0); ex.execute({"action": "open_app", "app": app})
                        info = getattr(ex, "last_info", "") if isinstance(getattr(ex, "last_info", ""), str) else ""
                    self.log(f"[app] {info or 'opened ' + app} ({time.time() - t0:.1f}s)"); logf.write(json.dumps({"app_open": app, "info": info}) + "\n")
                except PermissionError as e:
                    return finish(str(e))
                except Exception as e:
                    return finish(f"stopped: couldn't open {app} ({type(e).__name__}: {e}). Is it installed?")
                just_open = planner.rule_plan(task).get("sure") or re.match(r"^\W*(?:\w+\W+){0,3}?(open|launch|start|run)\s+(the\s+)?" + re.escape(app) + r"(\s+app)?\W*$", task, re.I)
                if just_open and not adapter:
                    if pre is not None:
                        pre.ensure(); return finish(f"{app} was already open; brought its window to the front.")
                    return finish(f"Opened {app}.")
                skip_fast = True
                # BIND the run to the launched app's own window; every later step is scoped to it
                binding = pre or self.make_binding(app)
                if binding is not None:
                    w = pre_w if pre is not None else binding.bind(timeout=a_cfg.get("app_window_timeout_s", 15))
                    if not w:
                        return finish(f"stopped: {app} was launched but its window didn't appear, so I didn't act on any other window.")
                    if not binding.ensure():
                        return finish(f"stopped: couldn't bring {app} to the front, so I didn't act on any other window.")
                    self.app_binding = binding
                    logf.write(json.dumps({"bound_window": {k: w.get(k) for k in ("hwnd", "title", "proc", "pid")}}) + "\n")
                    self.log(f"[app] bound to {w.get('proc') or app} window \"{(w.get('title') or '')[:60]}\"")
                try:
                    import appui
                    if a_cfg.get("app_ui", True) and self.dom is None and not getattr(self, "_injected_dom", False):
                        self.dom = appui.AppUI(gui=self.gui, limit=a_cfg.get("max_elements", 60), log=self.log, binding=self.app_binding)
                except Exception as e:
                    self.log(f"[app] structured view unavailable ({type(e).__name__}); using screenshots")
                if adapter:
                    try:
                        res = adapter.run(self, logf)
                        if res: return finish(res)
                        why = "the result didn't start playing"
                    except Exception as e:
                        why = f"{type(e).__name__}: {e}"
                        logf.write(json.dumps({"adapter_error": str(e)}) + "\n")
                    if not a_cfg.get("adapter_fallback_loop", False):
                        return finish(f"stopped: I opened {app} and searched for \"{adapter.query}\", but couldn't confirm playback ({why}). "
                                      "The results are on screen - press Play on the one you want.")
                history.append(f"1: open_app {app} (done) - it is open and focused; now do the rest of the task inside it")
                hk = __import__("adapters").hint(app)
                if hk: history.append("(note) " + hk)
                # fast path: "open X and type Y" -> type into the app's text area directly, verify, done
                m_t = re.search(r"\b(?:type|write|enter)\s+(?:in\s+|out\s+)?[\"']?(.+?)[\"']?\s*$", task, re.I)
                if m_t and hasattr(self.dom, "first_typable") and not re.search(r"\b(and|then)\b.*\b(save|send|click|press)\b", m_t.group(1), re.I):
                    try:
                        self.dom.snapshot(); el = self.dom.first_typable()
                        if el and el.get("value"):  # the app opened on existing content: use a new blank document, never append to it
                            self.dom.new_document(); el = self.dom.first_typable()
                            if el and el.get("value"):
                                return finish(f"Opened {app}, but its text area already has content, so I didn't type into it. Open a blank document and ask again.")
                        if el:
                            text = m_t.group(1).strip()
                            self.dom.type_into(el["id"], text); time.sleep(0.4)
                            after = self.dom.snapshot(); val = next((e.get("value", "") for e in after.get("elements", []) if e.get("typable")), "")
                            logf.write(json.dumps({"app_type": text, "element": el["text"], "readback": val[:80]}) + "\n")
                            if text.lower() in (val or "").lower() or not val:
                                return finish(f"Opened {app} and typed \"{text}\"." + ("" if val else " (couldn't read it back to double-check)"))
                    except Exception as e:
                        self.log(f"[app] direct typing failed ({type(e).__name__}: {e}); continuing step by step")
        # 0) web task + Chrome extension connected: do it all through the extension (no screenshots)
        if ext_ok and pl["intent"] != "desktop_app" or self.use_extension(task) and pl["intent"] != "desktop_app":
            try:
                result = self.run_via_extension(task, history, logf)
                self.kill.stop(); logf.close(); self.log(f"Result: {result}"); return result
            except NeedsVision as e:
                logf.write(json.dumps({"web_handover": str(e)}) + "\n")
                if pl["intent"] != "desktop_app" and not self.cfg["agent"].get("web_vision_fallback", False):
                    return finish(f"stopped: I couldn't finish this in Chrome ({e}). Try rephrasing or doing the last step yourself.")
                self.log(f"[web] handing over to screenshots: {e}")
            except Exception as e:  # don't fall into a blind screenshot loop for a web task - report the problem
                result = f"stopped: the Chrome extension step failed ({type(e).__name__}: {e})"
                logf.write(json.dumps({"web_error": str(e)}) + "\n")
                self.kill.stop(); logf.close(); self.log(f"Result: {result}"); return result
            history.append("(note) The Chrome extension is connected: Google Chrome IS open. Do not open another browser.")
        # 1) deterministic fast handling of common commands (open app / site, first video ...)
        if a_cfg.get("intents", True) and not skip_fast:
            fixed, rest = intents.plan(task)
            done_steps = []
            for act in fixed:
                if self.kill.killed: break
                desc = act["action"] + (" " + (act.get("app") or act.get("url") or "")).rstrip()
                try:
                    t0 = time.time()
                    if IS_MAC and act["action"] in ("open_url", "first_video"):
                        self._page = intents.page_info()  # baseline, so 'changed' means THIS step changed the page
                    ex = self.make_executor(1.0); ex.execute(act)
                    info = getattr(ex, "last_info", "") if isinstance(getattr(ex, "last_info", ""), str) else ""
                    self.log(f"[fast] {desc}" + (f" -> {info}" if info else "") + f" ({time.time()-t0:.1f}s)")
                    done_steps.append(desc + " (done)"); logf.write(json.dumps({"fast": act}) + "\n")
                    if act["action"] in ("open_url", "open_app", "first_video"): self.wait_page_change(act)
                except NeedsVision as e:
                    if act["action"] == "first_video" and self.locate_and_click_first_video(run_dir):
                        done_steps.append("first_video (done, vision)"); continue
                    self.log(f"[fast] {desc} could not run directly ({e}); using vision")
                    idx = fixed.index(act)
                    left = ["click the first video on the page" if x["action"] == "first_video" else
                            f"{x['action'].replace('_', ' ')} {x.get('app') or x.get('url') or ''}".strip() for x in fixed[idx:]]
                    rest = " and ".join(left + ([rest] if rest else [])); break
                except Exception as e:
                    self.log(f"[fast] {desc} could not run directly ({e}); using vision")
                    idx = fixed.index(act)
                    left = ["click the first video on the page" if x["action"] == "first_video" else
                            f"{x['action'].replace('_', ' ')} {x.get('app') or x.get('url') or ''}".strip() for x in fixed[idx:]]
                    rest = " and ".join(left + ([rest] if rest else [])); break
            if not rest and not self.kill.killed and fixed:
                self.kill.stop(); logf.close()
                result = "done: " + "; ".join(done_steps); self.log(f"Result: {result}"); return result
            if fixed:
                history += [f"(already done) {d}" for d in done_steps]
                task = rest
        if self.desktop_only and self.desktop_app_name:  # desktop app runs get no web actions at all
            system = "\n".join(l for l in system.splitlines() if not re.match(r"\s*(open_url|web_search|first_video)\s*:", l)
                                 and "To visit a website use open_url" not in l)
            if self.app_binding is not None:
                system += (f"\nYou are operating ONLY the app '{self.app_binding.app}'. The screenshot shows only its window. "
                           "Never use a browser or web actions. If you can't finish inside this app, use done and say why.")
        plan = self.make_plan(task) if a_cfg.get("plan", True) else ""
        if plan: self.log("Plan:\n" + plan)
        try:
            for step in range(1, a_cfg.get("max_steps", 40) + 1):
                if self.kill.killed: result = "stopped by user"; break
                if getattr(self, "app_binding", None) is not None and not self.app_binding.ensure():
                    result = (f"stopped: {self.app_binding.app} is no longer in front and couldn't be brought back, "
                              "so I stopped instead of acting on another window."); self.log(f"!! {result}"); break
                if IS_MAC and step > 1:
                    url, _t = intents.page_info()
                    if intents.goal_reached(orig_task, url):
                        result = f"done: goal reached ({url})"; break
                raw_img = self.capture(); full_w = raw_img.width; crop_off = (0, 0)
                if getattr(self, "app_binding", None) is not None:  # look ONLY at the bound app's window
                    r = self.app_binding.window_rect()
                    if r:
                        l, t, rr, b = max(0, int(r[0])), max(0, int(r[1])), min(raw_img.width, int(r[2])), min(raw_img.height, int(r[3]))
                        if rr - l > 50 and b - t > 50: raw_img = raw_img.crop((l, t, rr, b)); crop_off = (l, t)
                if a_cfg.get("blank_check", IS_MAC) and screen.is_blank(raw_img):
                    result = ("stopped: the screenshots are blank, so Liscia Agent can't see the screen. Open System Settings > "
                              "Privacy & Security > Screen Recording, turn Liscia Agent OFF and ON again (or remove it with - and add it back), "
                              "then quit and reopen Liscia Agent.")
                    self.log(f"!! {result}"); logf.write(json.dumps({"step": step, "blank_screenshot": True}) + "\n"); break
                h = screen.image_hash(raw_img)
                if last_idx is not None:  # annotate the previous action with its result
                    changed = screen.hash_diff(prev_hash, h) > a_cfg.get("change_threshold", 0.01)
                    history[last_idx] += " -> screen changed" if changed else " -> NO VISIBLE CHANGE (it probably did not work)"
                    last_idx = None
                prev_hash = h
                img, scale = screen.prepare(raw_img, a_cfg.get("screenshot_width", 1280), 0 if norm else a_cfg.get("grid_spacing", 100))
                pr = screen.point_ratio(self.gui, full_w); scale *= pr  # Retina: pixels -> points
                step_offset = (crop_off[0] * pr, crop_off[1] * pr)
                img.save(os.path.join(run_dir, f"step{step:03d}.png"))
                hist = "\n".join(history[-a_cfg.get("max_history", 8):]) or "(none yet)"
                prompt = (f"TASK: {task}\n" + (f"PLAN:\n{plan}\n" if plan else "") +
                          f"Step {step}. " + ("Coordinates: normalized 0-1000." if norm else f"Image size {img.width}x{img.height}.") + "\n"
                          f"Recent actions and results (oldest first):\n{hist}\n" +
                          ("".join(f"WARNING: {n}\n" for n in notes)) +
                          "Do not repeat an action that did not work; if the screen did not change, try something different.\n"
                          "What is the single next action? JSON only.")
                notes = []
                ext_live = self.link().connected() and self.cfg["agent"].get("chrome_extension", True)
                if ext_live:
                    tab = self.live_tab()
                    if tab:
                        prompt = (f"FACT: Google Chrome IS open and running (extension reports the active tab: {tab[1][:60]} | {tab[0][:100]}). "
                                  "Do NOT say Chrome is not open; do NOT use open_app for a browser.\n") + prompt
                snap = None
                if self.dom and not force_look:
                    try: snap = self.dom.snapshot()
                    except Exception: snap = None
                force_look = False
                t0 = time.time()
                if snap and snap.get("elements") and a_cfg.get("text_fast_path", True):
                    # FAST PATH: no image, the page structure as text on the fast text model
                    tprompt = prompt.replace(f"Image size {img.width}x{img.height}." if not norm else "Coordinates: normalized 0-1000.", "(No screenshot this step: use the element list. Use look if you need to see the screen.)")
                    tprompt = (__import__("appui").format_elements(snap) if snap.get("kind") == "app" else browser_dom.format_elements(snap)) + "\n\n" + tprompt
                    raw = self.client.text_chat([{"role": "system", "content": system}, {"role": "user", "content": tprompt}],
                                                json_mode=True, on_token=self.on_token, num_predict=self.client.num_predict)
                    mode = "dom"
                else:
                    if snap and snap.get("elements"):
                        prompt = (__import__("appui").format_elements(snap) if snap.get("kind") == "app" else browser_dom.format_elements(snap)) + "\n\n" + prompt
                        vsys = system
                    else:  # no element list -> don't offer click_element (the model invents ids otherwise)
                        vsys = "\n".join(l for l in system.splitlines() if "click_element" not in l and "type_element" not in l)
                        prompt += "\nThere is NO element list this step: to click, use click with x,y on the screenshot."
                    raw = self.client.chat(vsys, prompt, img, on_token=self.on_token)
                    mode = "vision"
                entry = {"step": step, "secs": round(time.time() - t0, 1), "raw": raw, "mode": mode}
                if self.kill.killed: result = "stopped by user"; break
                try:
                    act = parse_action(raw)
                except ActionError as e:
                    self.log(f"[{step}] invalid output: {e}"); history.append(f"{step}: INVALID OUTPUT ({e}) - reply with valid JSON")
                    bad_streak = bad_streak + 1 if str(e) == last_bad else 1; last_bad = str(e)
                    notes.append(f"Your last reply was rejected: {e}. Do something different.")
                    if bad_streak >= a_cfg.get("loop_stop", 5):
                        result = f"stopped: the model kept giving an invalid action ({e})"; self.log(f"!! {result}")
                        entry["error"] = str(e); logf.write(json.dumps(entry) + "\n"); break
                    entry["error"] = str(e); logf.write(json.dumps(entry) + "\n"); continue
                entry["action"] = act
                self.log(f"[{step}] {act['action']} {json.dumps({k: v for k, v in act.items() if k not in ('action','thought')})} ({entry['secs']}s, {mode})")
                if act["action"] == "look":
                    force_look = True; history.append(f"{step}: look (screenshot next)"); logf.write(json.dumps(entry) + "\n"); continue
                if act["action"] == "done":
                    result = act.get("summary", "done"); logf.write(json.dumps(entry) + "\n"); break
                act = self.fix_browser(act)
                import policy
                why = policy.check(act, task)
                if not why and getattr(self, "app_binding", None) is not None:
                    el_name = ""
                    if act["action"] in ("click_element", "type_element") and isinstance(getattr(self.dom, "last", None), dict):
                        el_name = next((str(e.get("text", "")) for e in self.dom.last.get("elements", []) if str(e.get("id")) == str(act.get("id"))), "")
                    if re.fullmatch(r"\s*(close|minimi[sz]e|maximi[sz]e|restore|exit|quit)\s*", el_name, re.I) or \
                            (act["action"] == "hotkey" and {k.lower() for k in act.get("keys", [])} in ({"alt", "f4"}, {"ctrl", "w"}, {"command", "q"}, {"command", "w"})):
                        why = f"closing or minimizing {self.app_binding.app} isn't part of this task"
                if not why and self.desktop_only and getattr(self, "desktop_app_name", "") and not getattr(self, "desktop_web_ok", False):
                    if act["action"] in DESKTOP_FORBIDDEN or (act["action"] == "open_app" and act.get("app") and intents.named_browser(str(act.get("app")))) or \
                            (act["action"] == "hotkey" and {k.lower() for k in act.get("keys", [])} in ({"ctrl", "t"}, {"command", "t"})):
                        why = f"{act['action']} is a web/browser action; this is a desktop task inside {getattr(self.app_binding, 'app', 'the app')} - work in that app's window"
                if why:
                    blocked_opens += 1
                    self.log(f"!! blocked: {why}"); entry["blocked"] = why; logf.write(json.dumps(entry) + "\n")
                    if blocked_opens >= 3:
                        result = f"stopped: {why} (3 blocked attempts). I can't do this on the desktop - try rephrasing."; break
                    history.append(f"{step}: {act['action']} -> BLOCKED: {why}"); notes.append(f"BLOCKED: {why}. Do something else or use done."); continue
                if act["action"] in ("click", "double_click", "right_click") and "x" in act:
                    xy = (round(float(act["x"])), round(float(act["y"])))
                    same_clicks = same_clicks + 1 if xy == last_click else 1; last_click = xy
                    if same_clicks >= 3:
                        result = (f"stopped: clicked the same spot ({xy[0]},{xy[1]}) 3 times without progress. "
                                  "I can't do this by clicking on the screen - try rephrasing, or ask me to make a document/spreadsheet instead.")
                        self.log(f"!! {result}"); entry["loop"] = "same_click"; logf.write(json.dumps(entry) + "\n"); break
                else:
                    same_clicks, last_click = 0, None
                if act["action"] == "open_url" and act.get("url"):
                    act["url"] = intents.safe_url(act["url"])
                logged = {k: ("***" if k == "text" and act.get("sensitive") else v) for k, v in act.items() if k not in ("thought", "reason")}
                if act["action"] in ("open_app", "open_url"):
                    key = act["action"] + ":" + str(act.get("app") or act.get("url") or "").rstrip("/").lower()
                    opens[key] = opens.get(key, 0) + 1
                    if ext_live and act["action"] == "open_app" and act.get("app") == "Google Chrome" and opens[key] > 1:
                        history.append(f"{step}: open_app Google Chrome -> SKIPPED: Chrome is already open")
                        notes.append("Chrome is already open. Do something on the page instead."); logf.write(json.dumps(entry) + "\n"); continue
                    if opens[key] > 2:
                        result = f"stopped: kept re-opening {key.split(':',1)[1]} without progress"
                        self.log(f"!! {result}"); entry["loop"] = 3; logf.write(json.dumps(entry) + "\n"); break
                level = guard.check(act)
                if level == 3:
                    result = f"stopped: stuck repeating the same action ({act['action']}) {guard.count} times"
                    self.log(f"!! {result}"); entry["loop"] = 3; logf.write(json.dumps(entry) + "\n"); break
                if level == 2:
                    self.log(f"!! loop detected - skipped repeat #{guard.count} of {act['action']}")
                    history.append(f"{step}: {json.dumps(logged)} -> BLOCKED: repeated {guard.count} times without success")
                    notes.append(f"You have proposed {json.dumps(logged)} {guard.count} times in a row. It is NOT working. "
                                 "You MUST choose a completely different action (e.g. open_app / open_url / press Enter / click elsewhere) or use done if finished.")
                    entry["loop"] = 2; logf.write(json.dumps(entry) + "\n"); continue
                if level == 1:
                    notes.append(f"You just repeated the same action ({act['action']}). Check the screenshot: if it did not help, do something different.")
                el_text = ""
                if act["action"] in ("click_element", "type_element") and snap:
                    el_text = next((e.get("text", "") for e in snap.get("elements", []) if str(e.get("id")) == str(act.get("id"))), "")
                if s_cfg.get("confirm_risky", True) and (is_risky(act, s_cfg.get("risky_words", [])) or policy.risky(act, el_text)):
                    shown = dict(act); shown["text"] = "***" if act.get("sensitive") else act.get("text")
                    if not self.confirm(f"Agent wants to: {json.dumps(shown)}"):
                        history.append(f"{step}: {act['action']} DENIED by user - choose another approach or finish")
                        entry["denied"] = True; logf.write(json.dumps(entry) + "\n"); continue
                try:
                    ex = self.make_executor(scale); ex.offset = step_offset
                    ex.execute(denormalize(act, img.width, img.height) if norm else act)
                    history.append(f"{step}: {json.dumps(logged)}"); last_idx = len(history) - 1
                except Exception as e:
                    if type(e).__name__ == "FailSafeException": raise
                    history.append(f"{step}: {json.dumps(logged)} -> FAILED: {e}"); self.log(f"   action failed: {e}")
                logf.write(json.dumps(entry) + "\n"); logf.flush()
                time.sleep(a_cfg.get("step_delay_s", 1.0))
        except Exception as e:
            if type(e).__name__ == "FailSafeException": result = "aborted by FAILSAFE (mouse in corner)"
            else: raise
        finally:
            self.kill.stop(); logf.close()
        self.log(f"Result: {result}")
        return result

DESKTOP_FORBIDDEN = {"open_url", "web_search", "first_video"}

ROUTER = """You are the router for a local assistant that can also control the user's computer.
Decide whether the user's latest message needs the computer (opening sites/apps, clicking, typing, searching
the web in the browser, looking things up, making Word/Excel/PowerPoint/text files) or is just conversation/questions that can be answered directly.
If the user asks you to DO something (look up, make, create, open, write, save) it is a task, even if it has typos. When in doubt, it is a task.
Reply with ONE JSON object only: {"type": "chat"}  or  {"type": "task", "task": "<clear instruction for the computer agent>"}"""

import re as _re
IMPERATIVE = _re.compile(r"^\s*(?:please\s+|now\s+|then\s+|ok\s+|okay\s+|and\s+|can you\s+|could you\s+)*"
    r"(?:open|launch|start|go to|visit|navigate|click|tap|press|type|search|play|watch|scroll|close|quit|"
    r"switch to|find|download|log ?in|sign ?in|fill|select|choose|pause|mute|bring up|show me)\b", _re.I)

CHAT_SYSTEM = ("You are Liscia, a friendly, concise, smart local assistant running on the user's own computer. "
               "You CAN act on this computer: open apps and websites, search the web, and create Word, Excel, PowerPoint and text files. "
               "Never say you can't create files or use the computer. If the user asks for something you can do, don't give how-to steps: "
               "tell them to just ask you to do it (it will run as a task).")

ACTION_RE = _re.compile(r"\b(look ?up|search|google|find|open|launch|go to|visit|play|watch|make|create|write|build|generate|prepare|draft|"
                        r"put|save|export|add|list|download|type|click|fill|send|book|order|compile|gather|collect|research)\b", _re.I)
SMALLTALK_RE = _re.compile(r"^\s*(hi|hello|hey|yo|thanks|thank you|thx|good (morning|night|evening)|how are you|what'?s up|bye|ok|okay|cool|nice|lol)\b", _re.I)

def needs_task(message):
    """Code-side chat-vs-task decision (runs before the model): planner rules + action verbs + file words."""
    import planner
    m = intents.fix_typos(message or "")
    if _re.match(r"^\s*(how (do|can|would|should) (i|you|we)|how to|what is|what are|explain)\b", m, _re.I) and not _re.search(r"\b(for me|look ?up|search)\b", m, _re.I):
        return False  # a question about how something works stays chat
    if planner.file_outputs(m) and (ACTION_RE.search(m) or planner.needs_facts(m)): return True
    if intents.output_request(m): return True
    if SMALLTALK_RE.match(m) and not ACTION_RE.search(m): return False
    if ACTION_RE.search(m) and not _re.match(r"^\s*(what|who|why|how|when|where|which|is|are|do|does|can|should)\b(?!.*\b(look ?up|search|google|open|make|create|play)\b)", m, _re.I):
        return True
    rp = planner.rule_plan(m)
    return bool(rp.get("sure")) and rp["intent"] != "desktop_app"

def route(client, message, history=(), on_token=None):
    """Return ("chat", reply) or ("task", task). '/do ...' forces a task, '/chat ...' forces chat.
    Chat replies are generated with streaming via on_token(piece) when given."""
    m = message.strip()
    if m.lower().startswith("/do "): return "task", m[4:].strip()
    hist = list(history)[-10:]
    if intents.plan(m)[0] or IMPERATIVE.match(m) or needs_task(m):
        return "task", m
    force_chat = m.lower().startswith("/chat ")
    if force_chat:
        m = m[6:].strip()
    else:
        raw = client.text_chat([{"role": "system", "content": ROUTER}] + hist + [{"role": "user", "content": m}],
                               json_mode=True, num_predict=80)
        try:
            obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        except ValueError:
            obj = {}
        if obj.get("type") == "task" and obj.get("task"):
            # keep the user's own words for anything self-contained; the rewrite only resolves "do that again"-style references
            return "task", (str(obj["task"]) if _re.search(r"\b(it|that|this|them|again|same)\b", m, _re.I) and len(m.split()) <= 8 else m)
        if obj.get("reply"):  # some models answer directly anyway
            return "chat", str(obj["reply"]).strip()
    msgs = [{"role": "system", "content": CHAT_SYSTEM}] + hist + [{"role": "user", "content": m}]
    return "chat", client.text_chat(msgs, on_token=on_token).strip()
