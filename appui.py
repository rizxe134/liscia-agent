"""Structured, read-only view of the focused desktop app (1.4.0), like the web snapshot.
Windows: UI Automation (uiautomation package). macOS: Accessibility API through System Events (JXA).
The model gets a numbered element list (role, name, value); click_element clicks the element's centre, type_element
clicks it and types. Vision (screenshots) stays the fallback when the tree is empty."""
import json, re, subprocess, sys, time

IS_WIN, IS_MAC = sys.platform.startswith("win"), sys.platform == "darwin"
ROLES = {"button", "menuitem", "menu item", "edit", "document", "text field", "text area", "textfield", "textarea", "combobox", "combo box",
         "checkbox", "check box", "radiobutton", "radio button", "listitem", "list item", "treeitem", "tree item", "tabitem", "tab item", "tab",
         "hyperlink", "link", "menubaritem", "menu bar item", "splitbutton", "split button", "slider", "spinner", "row", "cell", "dataitem",
         "pop up button", "popupbutton", "menu button", "menubutton", "search field", "incrementor", "disclosure triangle", "image"}
TYPABLE = {"edit", "document", "text field", "text area", "textfield", "textarea", "combobox", "combo box", "search field"}

def _role(r):
    r = str(r or "").lower().replace("control", "").replace("ax", "", 1 if str(r or "").startswith("AX") else 0).strip()
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", r).lower()

def parse_elements(raw, limit=80, screen=None):
    """raw: [{'role','name','value','rect':[l,t,r,b] or {'x','y','w','h'},'enabled'}] -> numbered, filtered elements."""
    out, seen = [], set()
    for e in raw or []:
        role = _role(e.get("role"))
        if role not in ROLES: continue
        if e.get("enabled") is False or e.get("offscreen"): continue
        name = re.sub(r"\s+", " ", str(e.get("name") or "")).strip()[:80]
        value = re.sub(r"\s+", " ", str(e.get("value") or "")).strip()[:60]
        if not name and role not in TYPABLE: continue
        r = e.get("rect")
        if isinstance(r, dict): r = [r.get("x", 0), r.get("y", 0), r.get("x", 0) + r.get("w", 0), r.get("y", 0) + r.get("h", 0)]
        if not r or len(r) != 4: continue
        l, t, rr, b = [int(v) for v in r]
        if rr - l < 2 or b - t < 2: continue
        if screen and (rr < 0 or b < 0 or l > screen[0] or t > screen[1]): continue
        key = (role, name, l // 4, t // 4)
        if key in seen: continue
        seen.add(key)
        el = {"id": len(out) + 1, "tag": role, "type": "", "text": name or ("(" + role + ")"), "value": value,
              "x": (l + rr) // 2, "y": (t + b) // 2, "typable": role in TYPABLE}
        if e.get("ctrl") is not None: el["_ctrl"] = e["ctrl"]
        out.append(el)
        if len(out) >= limit: break
    return out

def format_elements(snap):
    lines = [f"APP: {snap.get('app','')} | window: {snap.get('title','')[:80]}",
             "ELEMENTS in the app window (id, role, name[, current value]). Use click_element with an id to click one, or",
             "type_element with an id and text to type into a field. Use look if you need a screenshot."]
    for e in snap.get("elements", []):
        v = f" = \"{e['value']}\"" if e.get("value") else ""
        lines.append(f"  [{e['id']}] {e['tag']} \"{e['text']}\"{v}")
    return "\n".join(lines)

# ---------------- Windows (UI Automation) ----------------
def win_raw(max_depth=12, max_nodes=600, hwnd=None):
    """Element tree of ONE window: the bound app window (hwnd) - never 'whatever is in front'."""
    import uiautomation as auto
    if hwnd:
        top = auto.ControlFromHandle(int(hwnd))
    else:
        win = auto.GetForegroundControl()
        top = win.GetTopLevelControl() if hasattr(win, "GetTopLevelControl") else win
    title, app = top.Name, ""
    try:
        import psutil; app = psutil.Process(top.ProcessId).name()
    except Exception: app = title
    raw, n = [], 0
    for ctrl, depth in auto.WalkControl(top, includeTop=False, maxDepth=max_depth):
        n += 1
        if n > max_nodes: break
        try:
            r = ctrl.BoundingRectangle; val = ""
            try:
                vp = ctrl.GetValuePattern(); val = vp.Value if vp else ""
            except Exception: pass
            if not val and ctrl.ControlTypeName in ("DocumentControl", "EditControl"):
                try:
                    tp = ctrl.GetTextPattern(); val = tp.DocumentRange.GetText(200) if tp else ""
                except Exception: pass
            raw.append({"role": ctrl.ControlTypeName, "name": ctrl.Name, "value": val, "rect": [r.left, r.top, r.right, r.bottom],
                        "enabled": bool(ctrl.IsEnabled), "offscreen": bool(ctrl.IsOffscreen), "ctrl": ctrl})
        except Exception: continue
    return app, title, raw

# ---------------- macOS (Accessibility via System Events) ----------------
JXA = r"""
const se = Application('System Events'); const PID = parseInt('__PID__');
const p = PID > 0 ? se.processes.whose({unixId: PID})[0] : se.processes.whose({frontmost: true})[0];
const out = []; let n = 0;
function walk(el, d) { if (d > 9 || n > 500) return; let kids = [];
  try { kids = el.uiElements(); } catch (e) { return; }
  for (const k of kids) { n++; try { const pos = k.position(), sz = k.size();
      out.push({role: k.role(), name: (k.name() || k.description() || k.title() || ''), value: String(k.value() || '').slice(0, 60),
                rect: [pos[0], pos[1], pos[0] + sz[0], pos[1] + sz[1]], enabled: k.enabled()}); } catch (e) {}
    walk(k, d + 1); } }
let title = ''; try { const w = p.windows[0]; title = w.name(); walk(w, 0); } catch (e) {}
try { walk(p.menuBars[0], 7); } catch (e) {}
JSON.stringify({app: p.name(), title: title, raw: out});
"""

def mac_raw(run=subprocess.run, pid=0):
    r = run(["osascript", "-l", "JavaScript", "-e", JXA.replace("__PID__", str(int(pid or 0)))], capture_output=True, text=True, timeout=25)
    d = json.loads(r.stdout or "{}")
    return d.get("app", ""), d.get("title", ""), d.get("raw", [])

class WrongWindow(RuntimeError):
    """The bound app window isn't in the foreground (and refocusing failed): never act on another window."""

class AppUI:
    """Adapter used by the agent like browser_dom.BrowserDOM: snapshot() and click(id), plus type_into(id, text)."""
    def __init__(self, gui=None, limit=80, raw_fn=None, log=print, binding=None):
        """binding: winbind.WindowBinding - when given, every snapshot reads ONLY that window, and refuses to run if it isn't in front."""
        self.gui, self.limit, self.log, self.binding = gui, limit, log, binding
        if raw_fn is None and binding is not None:
            raw_fn = (lambda: win_raw(hwnd=binding.hwnd)) if IS_WIN else (lambda: mac_raw(pid=binding.hwnd)) if IS_MAC else None
        self.raw_fn = raw_fn or (win_raw if IS_WIN else mac_raw if IS_MAC else None)
        self.last = {"elements": []}

    def snapshot(self):
        if not self.raw_fn: return {"elements": []}
        if getattr(self, "binding", None) is not None and not self.binding.ensure():
            raise WrongWindow(f"{self.binding.app} is not in front and couldn't be focused")
        app, title, raw = self.raw_fn()
        import policy
        if policy.core_app(app, title):  # never expose/operate a core app
            self.last = {"kind": "app", "app": app, "title": title, "elements": [], "blocked": policy.core_app(app, title)}
            return self.last
        self.last = {"kind": "app", "app": app, "title": title, "elements": parse_elements(raw, self.limit)}
        return self.last

    def _el(self, element_id):
        for e in self.last.get("elements", []):
            if str(e["id"]) == str(element_id): return e
        raise RuntimeError(f"no element {element_id} in the app element list")

    def click(self, element_id):
        """Windows: act through UI Automation on the element itself (Invoke / focus / its own DPI-correct Click),
        never raw screen coordinates (UIA rects are physical pixels; the mouse may be in logical pixels)."""
        e = self._el(element_id); c = e.get("_ctrl")
        if getattr(self, "binding", None) is not None and not self.binding.ensure():
            raise WrongWindow(f"{self.binding.app} is not in front - not clicking")
        if c is not None:
            if e["tag"] in TYPABLE:
                c.SetFocus(); return e
            try:
                ip = c.GetInvokePattern()
                if ip: ip.Invoke(); return e
            except Exception: pass
            try: c.Click(simulateMove=False); return e
            except Exception: pass
        g = self.gui or __import__("pyautogui")
        g.moveTo(e["x"], e["y"], duration=0.15); g.click(e["x"], e["y"])
        return e

    def new_document(self):
        """Ctrl+N in the focused app (new blank document / tab)."""
        el = self.first_typable() or (self.last.get("elements") or [None])[0]
        c = el.get("_ctrl") if el else None
        if c is not None and IS_WIN: c.SendKeys("{Ctrl}n", waitTime=0.8)
        else:
            g = self.gui or __import__("pyautogui"); g.hotkey("command" if IS_MAC else "ctrl", "n"); time.sleep(0.8)
        return self.snapshot()

    def first_typable(self):
        for e in self.last.get("elements", []):
            if e.get("typable"): return e
        return None

    def type_into(self, element_id, text, press_enter=False, allow_existing=False):
        e = self._el(element_id)
        if e.get("value") and not allow_existing:  # never type into someone's existing text (e.g. a restored Notepad tab)
            raise RuntimeError(f"element {element_id} already contains text that isn't from this task - open a new blank document/field first")
        e = self.click(element_id); time.sleep(0.2)
        c = e.get("_ctrl")
        if c is not None and hasattr(c, "SendKeys") and not isinstance(c, type(None)) and IS_WIN:
            import uiautomation as auto  # paste through the clipboard (exact text, any language), then restore the clipboard
            try: old = auto.GetClipboardText()
            except Exception: old = None
            auto.SetClipboardText(text); time.sleep(0.05)
            c.SendKeys("{Ctrl}v" + ("{Enter}" if press_enter else ""), waitTime=0.2)
            time.sleep(0.2)
            if old is not None:
                try: auto.SetClipboardText(old)
                except Exception: pass
            return e
        g = self.gui or __import__("pyautogui")
        if text.isascii(): g.write(text, interval=0.02)
        else:
            import pyperclip; pyperclip.copy(text); g.hotkey("command" if IS_MAC else "ctrl", "v")
        if press_enter: g.press("enter")
        return e

def focus_window(name, timeout=8.0):
    """Bring the launched app's window to the front (best effort)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if IS_WIN:
                import uiautomation as auto
                q = name.lower()
                for w in auto.GetRootControl().GetChildren():
                    if q in (w.Name or "").lower():
                        w.SetActive(); w.SetFocus(); return True
            elif IS_MAC:
                subprocess.run(["osascript", "-e", f'tell application "{name}" to activate'], timeout=5, capture_output=True); return True
        except Exception: pass
        time.sleep(0.5)
    return False
