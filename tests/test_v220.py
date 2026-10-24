"""2.2.0: agent cursor + active-tab banner in a real Chrome page (skipped without playwright/Chrome)."""
import os, sys, unittest, shutil, tempfile
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = open(os.path.join(HERE, "..", "chrome-extension", "content.js"), encoding="utf-8").read()
STUB = "window.__msgs=[];window.chrome={runtime:{sendMessage:(m)=>window.__msgs.push(m),onMessage:{addListener(){}}}};"
PAGE = """<html><body style='margin:0;font:16px sans-serif'>
<div style='height:50px;background:#eee;display:flex;align-items:center;justify-content:center'>
<input id=q placeholder='Search' style='width:420px;height:30px'><button id=go onclick="window.__clicked=(window.__clicked||0)+1">Search</button></div>
<a id=v href='#v' onclick="window.__link=1" style='display:block;margin:40px'>Shirobon - Pursuit</a></body></html>"""

def _chrome():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError: return None
    return sync_playwright if shutil.which("google-chrome") or shutil.which("chromium") else None

@unittest.skipUnless(_chrome(), "needs playwright + Chrome")
class OverlayInPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = _chrome()().start()
        cls.b = cls.pw.chromium.launch(channel="chrome" if shutil.which("google-chrome") else None, args=["--no-sandbox"])
    @classmethod
    def tearDownClass(cls): cls.b.close(); cls.pw.stop()
    def page(self):
        p = self.b.new_page(viewport={"width": 1000, "height": 600}); p.set_content(PAGE)
        p.evaluate(STUB); p.evaluate("(()=>{" + CONTENT + "})()"); return p
    def ids(self, p):
        s = p.evaluate("window.__liscia.snapshot({})")
        ids = {e["label"]: e["id"] for e in s["elements"]}
        ids["Box"] = next(e["id"] for e in s["elements"] if e["role"] == "textbox"); ids["Search"] = next(e["id"] for e in s["elements"] if e["role"] == "button")
        return s, ids
    def test_overlay_invisible_to_snapshot_and_clicks(self):
        p = self.page(); p.evaluate("window.__liscia.viz({on:true,cursor:true,banner:true})")
        s, ids = self.ids(p)
        self.assertNotIn("Stop", ids); self.assertNotIn("Liscia Agent is using this tab", s.get("summary", "") + str(s))
        self.assertEqual(p.evaluate("document.querySelectorAll('#liscia-agent-overlay-host').length"), 1)
        # elementFromPoint ignores the pointer-events:none overlay; the click lands and isn't "covered"
        self.assertEqual(p.evaluate("document.elementFromPoint(500,300).tagName"), "BODY")
        p.evaluate(f"window.__liscia.prepare('{ids['Search']}','clicking')"); r = p.evaluate(f"window.__liscia.click('{ids['Search']}')")
        self.assertFalse(r["covered"]); self.assertEqual(p.evaluate("window.__clicked"), 1)
        p.evaluate(f"window.__liscia.prepare('{ids['Box']}','typing in')")
        p.evaluate(f"window.__liscia.type('{ids['Box']}', 'pursuit', {{}})"); self.assertEqual(p.evaluate("q.value"), "pursuit")
    def test_banner_hides_over_target_and_stop_sends_message(self):
        p = self.page(); p.evaluate("window.__liscia.viz({on:true})"); _, ids = self.ids(p)
        # the search box sits under the banner: the banner fades out while the cursor is on it
        p.evaluate(f"window.__liscia.prepare('{ids['Box']}','typing in')"); p.wait_for_timeout(1000)  # fades back after
        for x in range(500, 760, 8):  # the Stop pill lives in a closed shadow root: press along the banner until it fires
            p.mouse.click(x, 18)
            if any(m.get("type") == "agent_stop" for m in p.evaluate("window.__msgs")): break
        self.assertTrue(any(m.get("type") == "agent_stop" for m in p.evaluate("window.__msgs")))
        self.assertEqual(p.evaluate("document.querySelectorAll('#liscia-agent-overlay-host').length"), 0)  # removed on Stop
    def test_off_removes_everything(self):
        p = self.page(); p.evaluate("window.__liscia.viz({on:true})"); p.evaluate("window.__liscia.viz({on:false})")
        self.assertEqual(p.evaluate("document.querySelectorAll('#liscia-agent-overlay-host').length"), 0)
    def test_cursor_off_banner_only(self):
        p = self.page(); p.evaluate("window.__liscia.viz({on:true,cursor:false,banner:true})"); _, ids = self.ids(p)
        p.evaluate(f"window.__liscia.prepare('{ids['Search']}','clicking')")  # no cursor glide, still works
        self.assertEqual(p.evaluate("document.querySelectorAll('#liscia-agent-overlay-host').length"), 1)

class SessionLifecycle(unittest.TestCase):
    def agent(self, cfg_ui=None):
        import core
        from PIL import Image
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 1, "runs_dir": "/tmp/pcagent-test", "planner": False}, "safety": {}, "ui": cfg_ui or {}}
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=mock.MagicMock(), capture=lambda: Image.new("RGB", (8, 8)), dom=False)
        calls = []; L = mock.Mock(connected=lambda: True); L.call.side_effect = lambda cmd, **k: calls.append((cmd, k)) or {}
        a.link = lambda: L; return a, calls
    def test_on_then_off_even_on_error(self):
        a, calls = self.agent()
        with mock.patch.object(a, "_run", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError): a.run("x")
        sess = [k["on"] for c, k in calls if c == "agent_session"]
        self.assertEqual(sess, [True, False])
    def test_toggles_off_means_no_session(self):
        a, calls = self.agent({"show_cursor": False, "show_banner": False})
        with mock.patch.object(a, "_run", return_value="done"): a.run("x")
        self.assertFalse([c for c, k in calls if c == "agent_session"])
    def test_stop_from_banner_kills_current(self):
        import core
        a, _ = self.agent(); core.CURRENT = a
        try:
            self.assertTrue(core.stop_current()); self.assertTrue(a.kill.event.is_set())
        finally: core.CURRENT = None

class DesktopRing(unittest.TestCase):
    def test_executor_hook_calls_overlay(self):
        import core, overlay
        a, _ = SessionLifecycle.agent(self)
        a._mk = lambda scale: core.Executor(mock.Mock(), scale, 0, dom=None)
        got = []; overlay.HOOK = lambda x, y: got.append((x, y))
        try:
            ex = a._executor(1.0)
            with mock.patch("time.sleep"): ex.execute({"action": "click", "x": 10, "y": 20})
        finally: overlay.HOOK = None
        self.assertEqual(got, [(10, 20)])
    @unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
    def test_ring_window(self):
        import tkinter as tk, overlay
        r = tk.Tk(); w = overlay.ring(r, 100, 100, ms=50); r.update(); self.assertTrue(w.winfo_exists()); r.after(120, r.quit); r.mainloop(); r.destroy()

if __name__ == "__main__": unittest.main()
