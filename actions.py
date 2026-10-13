"""Parse strict-JSON actions from the model and execute them."""
import json, re, sys, time, webbrowser, urllib.parse

IS_MAC = sys.platform == "darwin"

def norm_key(k, mac=None):
    """Map OS-specific modifier names: cmd->command on macOS, cmd/win->ctrl on Windows."""
    mac = IS_MAC if mac is None else mac
    k = k.lower().strip()
    if k in ("cmd", "command", "meta", "super", "⌘"):
        return "command" if mac else "ctrl"
    if k in ("option", "opt"):
        return "option" if mac else "alt"
    return k

VALID = {"move", "click", "double_click", "right_click", "type", "hotkey", "scroll",
         "open_url", "web_search", "open_app", "click_element", "look", "first_video", "wait", "done"}
NEEDS_XY = {"move", "click", "double_click", "right_click"}

class ActionError(ValueError):
    pass

def parse_action(text):
    """Extract and validate one JSON action. Raises ActionError."""
    if isinstance(text, dict):
        a = text
    else:
        text = text or ""
        start = text.find("{")
        if start < 0:
            raise ActionError("no JSON object in model output")
        try:  # first complete JSON object; ignores any trailing text/extra objects
            a, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            try:
                a = json.loads(m.group(0))
            except Exception as e:
                raise ActionError(f"bad JSON: {e}")
    if "action" not in a and isinstance(a.get("next_action"), dict):
        a = a["next_action"]
    for k in ("params", "parameters", "args", "arguments"):  # flatten {"action":..,"params":{..}}
        if isinstance(a.get(k), dict):
            a = {**a.pop(k), **a}
        elif isinstance(a.get(k), (str, int, float)):  # {"action":"open_app","params":"Chrome"}
            main = {"open_app": "app", "open_url": "url", "web_search": "query", "type": "text",
                    "click_element": "id", "wait": "seconds"}.get(str(a.get("action", "")).lower())
            v = a.pop(k)
            if main and main not in a: a[main] = v
    act = str(a.get("action", "")).lower().strip()
    if act in ("press_enter", "enter", "press", "key", "keypress", "press_key", "submit"):
        key = a.get("key") or a.get("keys") or "enter"
        a["action"] = act = "hotkey"; a.setdefault("keys", key)
    if act not in VALID:
        raise ActionError(f"unknown action {act!r}")
    a["action"] = act
    if act in NEEDS_XY or (act == "scroll" and "x" in a):
        try:
            a["x"], a["y"] = int(round(float(a["x"]))), int(round(float(a["y"])))
        except (KeyError, TypeError, ValueError):
            raise ActionError(f"{act} needs numeric x and y")
    if act == "type" and not isinstance(a.get("text"), str):
        raise ActionError("type needs text")
    if act == "hotkey":
        keys = a.get("keys")
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split("+") if k.strip()]
        if not keys:
            raise ActionError("hotkey needs keys")
        a["keys"] = [norm_key(k) for k in keys]
    if act == "scroll":
        try:
            a["amount"] = int(a.get("amount", -5))
        except (TypeError, ValueError):
            raise ActionError("scroll amount must be int")
    if act == "open_url" and not a.get("url"):
        raise ActionError("open_url needs url")
    if act == "click_element":
        try:
            a["id"] = int(a.get("id", a.get("element")))
        except (TypeError, ValueError):
            raise ActionError("click_element needs a numeric id FROM THE CLICKABLE ELEMENTS LIST; if there is no list, "
                              "use click with x,y on the screenshot instead")
    if act == "open_app" and not str(a.get("app") or a.get("name") or "").strip():
        raise ActionError("open_app needs app")
    if act == "open_app":
        a["app"] = str(a.get("app") or a.get("name")).strip()
    if "press_enter" in a:
        a["press_enter"] = a["press_enter"] in (True, "true", "True", 1, "yes")
    if act == "web_search" and not a.get("query"):
        raise ActionError("web_search needs query")
    if act == "wait":
        a["seconds"] = max(0.0, min(float(a.get("seconds", 2)), 30.0))
    return a

def is_risky(a, words):
    """Heuristic: password typing or clicking buy/send/submit-like things."""
    blob = " ".join(str(a.get(k, "")) for k in ("reason", "target", "text", "thought")).lower()
    if a["action"] == "type" and (a.get("sensitive") or "password" in blob):
        return True
    if a["action"] in ("click", "double_click", "hotkey") or (a["action"] == "type" and a.get("press_enter")):
        return any(re.search(rf"\b{re.escape(w)}", blob) for w in words)
    return False

def search_url(q):
    return "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(q)

def _default_runner(cmd):
    import subprocess
    subprocess.run(cmd, check=True, timeout=20, capture_output=True)

def app_command(app, url=None, mac=None, windows=None):
    """Shell command (argv list) to open an app (optionally with a URL)."""
    mac = IS_MAC if mac is None else mac
    windows = (sys.platform.startswith("win")) if windows is None else windows
    if mac:
        return ["open", "-a", app] + ([url] if url else [])
    if windows:
        return ["cmd", "/c", "start", "", app] + ([url] if url else [])
    return [app.lower().replace(" ", "-")] + ([url] if url else [])

class NeedsVision(RuntimeError):
    """Deterministic action couldn't run (e.g. page JS not allowed) - let the vision loop handle it."""

class Executor:
    def __init__(self, gui=None, scale=1.0, move_duration=0.25, browser=None, sleep=time.sleep, runner=None, dom=None):
        if gui is None:
            import pyautogui as gui
        self.gui, self.scale, self.dur = gui, scale, move_duration
        self.browser, self.sleep = browser or webbrowser, sleep
        self.run_cmd = runner or _default_runner
        self.dom = dom
        self.run_dom = None; self.last_info = ""
        self.on_click = None  # optional hook(x_points, y_points) - side panel draws a highlight

    def _open(self, url, browser=None):
        import intents, extlink
        if not browser and IS_MAC:
            browser = intents.current_browser()  # the app we're working in, not the system default
        if browser == "Google Chrome" and extlink.LINK.connected():
            intents.note_app(browser)
            try: self.run_cmd(app_command(browser))  # bring Chrome to the front
            except Exception: pass
            res = extlink.LINK.call("navigate", timeout=25, url=url) or {}
            self.last_info = (res.get("title") or "")[:60]; return
        if browser:
            intents.note_app(browser)
            self.run_cmd(app_command(browser, url))
        else:
            self.browser.open(url)

    def first_video(self, timeout=12.0):
        """Click the first (non-ad) video on a YouTube page via the browser's JavaScript."""
        import intents, browser_dom, extlink
        app = intents.current_browser() if IS_MAC else None
        if app == "Google Chrome" and extlink.LINK.connected():
            try:
                res = extlink.LINK.call("first_video", timeout=20) or {}
                self.last_info = (res.get("clicked") or "")[:80]; return
            except extlink.ExtError as e:
                raise NeedsVision(f"extension couldn't click the first video ({e})")
        if not app:
            raise NeedsVision("no scriptable browser in front")
        deadline = time.time() + timeout
        while True:
            try:
                res = browser_dom.run_js(app, intents.FIRST_VIDEO_JS, self.run_dom or __import__("subprocess").run) or ""
            except Exception as e:
                raise NeedsVision(f"can't run JavaScript in {app} ({str(e)[:120]})")
            if res.startswith("ok"):
                self.last_info = res[3:]; return
            if time.time() > deadline:
                raise NeedsVision("no video link found on the page")
            self.sleep(0.8)  # page still loading

    def _xy(self, a):
        return int(a["x"] * self.scale), int(a["y"] * self.scale)

    def execute(self, a):
        g, act = self.gui, a["action"]
        if act in NEEDS_XY:
            x, y = self._xy(a)
            if self.on_click:
                try: self.on_click(x, y)
                except Exception: pass
            g.moveTo(x, y, duration=self.dur)
            if act == "click": g.click(x, y)
            elif act == "double_click": g.doubleClick(x, y)
            elif act == "right_click": g.rightClick(x, y)
        elif act == "type":
            text = a["text"]
            if text.isascii():
                g.write(text, interval=0.02)
            else:  # pyautogui can't type unicode; paste instead
                import pyperclip; pyperclip.copy(text); g.hotkey("command" if IS_MAC else "ctrl", "v")
            if a.get("press_enter"): g.press("enter")
        elif act == "hotkey":
            g.hotkey(*a["keys"])
        elif act == "scroll":
            if "x" in a:
                g.moveTo(*self._xy(a), duration=self.dur)
            g.scroll(a["amount"] * 100)
        elif act == "open_url":
            url = a["url"] if "://" in a["url"] else "https://" + a["url"]
            self._open(url, a.get("browser"))
        elif act == "web_search":
            self._open(search_url(a["query"]), a.get("browser"))
        elif act == "click_element":
            if not self.dom:
                raise RuntimeError("no page element list available - use click with x,y")
            self.dom.click(a["id"])
        elif act == "look":
            pass  # handled by the loop: next step uses a screenshot
        elif act == "open_app":
            import intents
            name = intents.APP_NAMES.get(a["app"].lower().strip(), a["app"])  # "Chrome" -> "Google Chrome"
            self.run_cmd(app_command(name))
            intents.note_app(name)
            self.sleep(1.5)
        elif act == "first_video":
            self.first_video()
        elif act == "wait":
            self.sleep(a["seconds"])
        return act == "done"
