"""The screenshot -> model -> action loop."""
import json, os, time, datetime, yaml
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

SYSTEM = """You are a computer-use agent controlling a {os} computer with mouse and keyboard.
Each turn you get a screenshot with a red/blue coordinate grid (numbers are pixel coordinates in THIS image),
the task, a plan, and your recent actions WITH THEIR RESULTS.
Reply with EXACTLY ONE JSON object and nothing else:
{"thought": "<max 20 words: what the screen shows now>", "action": "<name>", ...params at top level, "reason": "<max 10 words>"}
Actions (PREFER the high-level ones at the top):
 open_app: "app" (e.g. "Safari", "Notes") - launches/focuses an application
 open_url: "url", optional "browser" (e.g. "Safari", "Google Chrome") - opens a website directly
 web_search: "query", optional "browser" - opens DuckDuckGo results for the query
 click_element: "id" - click a page element from the CLICKABLE ELEMENTS list (best for web pages, when a list is given)
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

def load_config(path="config.yaml"):
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
        self._mk = executor or (lambda scale: Executor(self.gui, scale, cfg["agent"].get("move_duration_s", 0.25), dom=self.dom))
        self.make_executor = self._executor
        self.kill = KillSwitch(s.get("kill_keys", ["esc", "f12"]))
        self._page = (None, None)
        intents.STATE["preferred"] = cfg["agent"].get("preferred_browser") or None

    def _executor(self, scale):
        ex = self._mk(scale)
        if self.on_highlight and hasattr(ex, "on_click") and not isinstance(getattr(type(ex), "on_click", None), property):
            try: ex.on_click = lambda x, y: (self.on_highlight(x=x, y=y, space="screen_points"), time.sleep(0.35))
            except Exception: pass
        return ex

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
        run_dir = os.path.join(a_cfg.get("runs_dir", "runs"), datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        logf = open(os.path.join(run_dir, "log.jsonl"), "a", encoding="utf-8")
        history, result, notes = [], "max steps reached", []
        guard = LoopGuard(a_cfg.get("loop_warn", 2), a_cfg.get("loop_block", 3), a_cfg.get("loop_stop", 5))
        prev_hash, last_idx, force_look = None, None, False
        bad_streak, last_bad = 0, None
        norm = uses_norm_coords(self.cfg)
        system = NORM_SYSTEM if norm else SYSTEM
        orig_task = task
        self.kill.start(); self.log(f"Task: {task}\nRun folder: {run_dir}\nAbort: Esc/F12, STOP, or slam mouse into a screen corner.")
        # 1) deterministic fast handling of common commands (open app / site, first video ...)
        if a_cfg.get("intents", True):
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
        plan = self.make_plan(task) if a_cfg.get("plan", True) else ""
        if plan: self.log("Plan:\n" + plan)
        try:
            for step in range(1, a_cfg.get("max_steps", 40) + 1):
                if self.kill.killed: result = "stopped by user"; break
                if IS_MAC and step > 1:
                    url, _t = intents.page_info()
                    if intents.goal_reached(orig_task, url):
                        result = f"done: goal reached ({url})"; break
                raw_img = self.capture()
                h = screen.image_hash(raw_img)
                if last_idx is not None:  # annotate the previous action with its result
                    changed = screen.hash_diff(prev_hash, h) > a_cfg.get("change_threshold", 0.01)
                    history[last_idx] += " -> screen changed" if changed else " -> NO VISIBLE CHANGE (it probably did not work)"
                    last_idx = None
                prev_hash = h
                img, scale = screen.prepare(raw_img, a_cfg.get("screenshot_width", 1280), 0 if norm else a_cfg.get("grid_spacing", 100))
                scale *= screen.point_ratio(self.gui, raw_img.width)  # Retina: pixels -> points
                img.save(os.path.join(run_dir, f"step{step:03d}.png"))
                hist = "\n".join(history[-a_cfg.get("max_history", 8):]) or "(none yet)"
                prompt = (f"TASK: {task}\n" + (f"PLAN:\n{plan}\n" if plan else "") +
                          f"Step {step}. " + ("Coordinates: normalized 0-1000." if norm else f"Image size {img.width}x{img.height}.") + "\n"
                          f"Recent actions and results (oldest first):\n{hist}\n" +
                          ("".join(f"WARNING: {n}\n" for n in notes)) +
                          "Do not repeat an action that did not work; if the screen did not change, try something different.\n"
                          "What is the single next action? JSON only.")
                notes = []
                snap = None
                if self.dom and not force_look:
                    try: snap = self.dom.snapshot()
                    except Exception: snap = None
                force_look = False
                t0 = time.time()
                if snap and snap.get("elements") and a_cfg.get("text_fast_path", True):
                    # FAST PATH: no image, the page structure as text on the fast text model
                    tprompt = prompt.replace(f"Image size {img.width}x{img.height}." if not norm else "Coordinates: normalized 0-1000.", "(No screenshot this step: use the element list. Use look if you need to see the screen.)")
                    tprompt = browser_dom.format_elements(snap) + "\n\n" + tprompt
                    raw = self.client.text_chat([{"role": "system", "content": system}, {"role": "user", "content": tprompt}],
                                                json_mode=True, on_token=self.on_token, num_predict=self.client.num_predict)
                    mode = "dom"
                else:
                    if snap and snap.get("elements"):
                        prompt = browser_dom.format_elements(snap) + "\n\n" + prompt
                        vsys = system
                    else:  # no element list -> don't offer click_element (the model invents ids otherwise)
                        vsys = "\n".join(l for l in system.splitlines() if "click_element" not in l)
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
                logged = {k: ("***" if k == "text" and act.get("sensitive") else v) for k, v in act.items() if k not in ("thought", "reason")}
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
                if s_cfg.get("confirm_risky", True) and is_risky(act, s_cfg.get("risky_words", [])):
                    shown = dict(act); shown["text"] = "***" if act.get("sensitive") else act.get("text")
                    if not self.confirm(f"Agent wants to: {json.dumps(shown)}"):
                        history.append(f"{step}: {act['action']} DENIED by user - choose another approach or finish")
                        entry["denied"] = True; logf.write(json.dumps(entry) + "\n"); continue
                try:
                    self.make_executor(scale).execute(denormalize(act, img.width, img.height) if norm else act)
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

ROUTER = """You are the router for a local assistant that can also control the user's computer.
Decide whether the user's latest message needs the computer (opening sites/apps, clicking, typing, searching
the web in the browser) or is just conversation/questions that can be answered directly.
Reply with ONE JSON object only: {"type": "chat"}  or  {"type": "task", "task": "<clear instruction for the computer agent>"}"""

import re as _re
IMPERATIVE = _re.compile(r"^\s*(?:please\s+|now\s+|then\s+|ok\s+|okay\s+|and\s+|can you\s+|could you\s+)*"
    r"(?:open|launch|start|go to|visit|navigate|click|tap|press|type|search|play|watch|scroll|close|quit|"
    r"switch to|find|download|log ?in|sign ?in|fill|select|choose|pause|mute|bring up|show me)\b", _re.I)

CHAT_SYSTEM = "You are a friendly, concise, smart local assistant running on the user's own computer."

def route(client, message, history=(), on_token=None):
    """Return ("chat", reply) or ("task", task). '/do ...' forces a task, '/chat ...' forces chat.
    Chat replies are generated with streaming via on_token(piece) when given."""
    m = message.strip()
    if m.lower().startswith("/do "): return "task", m[4:].strip()
    hist = list(history)[-10:]
    if intents.plan(m)[0] or IMPERATIVE.match(m):
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
            return "task", str(obj["task"])
        if obj.get("reply"):  # some models answer directly anyway
            return "chat", str(obj["reply"]).strip()
    msgs = [{"role": "system", "content": CHAT_SYSTEM}] + hist + [{"role": "user", "content": m}]
    return "chat", client.text_chat(msgs, on_token=on_token).strip()
