import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import creds, themes, accounts, webagent

class Themes(unittest.TestCase):
    def test_all_readable(self):
        for k, t in themes.THEMES.items():
            for c in ("fg", "dim", "step", "user", "warn"):
                with self.subTest(theme=k, c=c): self.assertGreaterEqual(themes.contrast(t["bg"], t[c]), 4.5)
            self.assertEqual(len({t[x].lower() for x in themes.KEYS}), len(themes.KEYS))  # unique -> live recolour is unambiguous
    def test_persist_and_clamp(self):
        import settings
        cfg = {"ollama": {"host": "x", "model": "m"}}
        self.assertEqual(themes.get(cfg), ("terminal", 13))
        themes.set_theme(cfg, "light", 40); self.assertEqual(themes.get(cfg), ("light", 22))
        self.assertRaises(ValueError, themes.set_theme, cfg, "neon")
        p = os.path.join(tempfile.mkdtemp(), "c.yaml"); settings.save(cfg, p)
        import yaml; self.assertEqual(yaml.safe_load(open(p))["ui"], {"theme": "light", "font_size": 22})

@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class UiLive(unittest.TestCase):
    def test_collapse_and_live_theme(self):
        import tkinter as tk, ui, chats
        cfg = {"ollama": {"host": "x", "model": "m"}, "setup_check": False, "panel": {"enabled": False}}
        r = tk.Tk(); r.withdraw()
        with mock.patch.object(ui.ChatApp, "_preload", lambda self: None):
            app = ui.ChatApp(cfg, root=r, store=chats.ChatStore(tempfile.mkdtemp()))
        app.write("user", "do x"); app.write("step", "[plan] a"); app.write("step", "[web1] b"); app.write("agent", "Done.")
        txt = app.log.get("1.0", "end")
        self.assertIn("\u25b8 2 steps", txt); self.assertTrue(int(app.log.tag_cget("grp1", "elide")))
        app.toggle_steps("grp1"); self.assertIn("\u25be 2 steps", app.log.get("1.0", "end")); self.assertFalse(int(app.log.tag_cget("grp1", "elide")))
        app.apply_theme("light", 16)
        self.assertEqual(str(app.log.cget("bg")).lower(), "#fafafa"); self.assertEqual(app.log.tag_cget("agent", "foreground"), "#1d1d1f")
        self.assertEqual(int(r.tk.splitlist(app.log.cget("font"))[1]), 16); self.assertEqual(cfg["ui"]["theme"], "light")
        app.apply_theme("dracula", 13); self.assertEqual(str(app.entry.cget("bg")).lower(), "#282a36")
        sw = ui.SettingsWindow(app); self.assertEqual(len(sw.nb.tabs()), 2); sw.win.destroy(); r.destroy()

class Credentials(unittest.TestCase):
    BAD = [("testuser@example.com", {"label": "Email"}), ("testuser", {"label": "Username or email address"}),
           ("testpassword", {"label": "Password", "itype": "password"}), ("hunter2", {"itype": "password"}),
           ("123456", {"label": "Verification code"}), ("me@gmail.com", {"label": "Search"}), ("testpassword", {"label": ""}),
           ("rizxe134", {"name": "login", "label": ""})]
    def test_blocks_invented(self):
        for text, el in self.BAD:
            with self.subTest(text=text): self.assertIsNotNone(creds.check_type(text, "open up my github and give me a summary", el))
    def test_allows_user_text_and_searches(self):
        self.assertIsNone(creds.check_type("lofi music", "search youtube for lofi music", {"label": "Search"}))
        self.assertIsNone(creds.check_type("me@site.com", "sign up for the newsletter with me@site.com", {"label": "Email"}))
        self.assertIsNone(creds.check_type("weather in paris", "weather in paris", {"label": "Search Google"}))
    def test_auth_pages(self):
        for u in ("https://github.com/login", "https://github.com/signup?source=x", "https://accounts.google.com/v3/signin/identifier",
                  "https://x.com/i/flow/login", "https://github.com/session", "https://www.reddit.com/register/"):
            with self.subTest(u=u): self.assertTrue(creds.auth_page({"url": u}))
        for u in ("https://github.com/", "https://www.youtube.com/watch?v=1", "https://github.com/rizxe134?tab=repositories"):
            with self.subTest(u=u): self.assertFalse(creds.auth_page({"url": u, "title": "x"}))
        self.assertTrue(creds.auth_page({"url": "https://a.com/x", "elements": [{"tag": "input", "itype": "password"}]}))

class FakeAgent:
    def __init__(self, replies):
        self.cfg = {"safety": {"confirm_risky": False}, "agent": {}}; self.logs = []
        self.client = mock.Mock(); self.client.text_chat.side_effect = list(replies)
        self.kill = mock.Mock(killed=False); self.confirm = lambda m: True
    def log(self, m): self.logs.append(m)

class SignupReplay(unittest.TestCase):
    """The 20261023-204707 run: GitHub's sign-up form; the model typed testuser@example.com / testpassword."""
    def link(self, url="https://github.com/", els=None):
        L = mock.Mock(); L.typed = []
        els = els or [{"id": "13", "role": "link", "label": "Sign up", "href": "https://github.com/signup"}, {"id": "14", "role": "textbox", "label": "Email", "tag": "input", "itype": "email"}]
        def call(cmd, **a):
            if cmd == "type": L.typed.append(a.get("text"))
            return {"url": url, "title": "GitHub", "elements": els} if cmd == "snapshot" else {}
        L.call.side_effect = call; return L
    def test_never_types_and_asks_user(self):
        L = self.link(); ag = FakeAgent(['{"action":"type","id":"14","text":"testuser@example.com","press_enter":true}'] * 3)
        with mock.patch("time.sleep"):
            r = webagent.run_web(ag, "try github on the chrome", [], open(os.devnull, "w"), link=L, sleep=lambda s: None)
        self.assertEqual(L.typed, []); self.assertIn("sign in", r); self.assertTrue(r.startswith("stopped"))
    def test_stops_on_login_page(self):
        L = self.link("https://github.com/login"); ag = FakeAgent([])
        r = webagent.run_web(ag, "open github", [], open(os.devnull, "w"), link=L, sleep=lambda s: None)
        self.assertTrue(r.startswith("stopped: github.com is asking you to sign in")); ag.client.text_chat.assert_not_called()
    def test_not_found_done_is_failure(self):
        L = self.link(els=[{"id": "1", "role": "link", "label": "Repos", "href": "https://github.com/x"}])
        ag = FakeAgent(['{"action":"done","summary":"Password field not found; task likely completed elsewhere."}'] * 3)
        with mock.patch.object(webagent, "MIN_SCROLLS", 0):
            r = webagent.run_web(ag, "open github", [], open(os.devnull, "w"), link=L, sleep=lambda s: None)
        self.assertTrue(r.startswith("stopped:"), r)

class GitHubSummary(unittest.TestCase):
    DASH = {"url": "https://github.com/", "title": "GitHub", "elements": [
        {"id": "1", "label": "Dashboard", "href": "https://github.com/dashboard"}, {"id": "2", "label": "rizxe134/liscia-agent", "href": "https://github.com/rizxe134/liscia-agent"},
        {"id": "3", "label": "rizxe134/notes", "href": "https://github.com/rizxe134/notes"}, {"id": "4", "label": "torvalds/linux", "href": "https://github.com/torvalds/linux"},
        {"id": "5", "label": "Explore", "href": "https://github.com/explore"}]}
    OUT = {"url": "https://github.com/", "title": "GitHub", "elements": [{"id": "1", "label": "Sign in", "href": "https://github.com/login"}, {"id": "2", "label": "Sign up", "href": "https://github.com/signup"}]}
    def test_intent(self):
        self.assertTrue(accounts.wants_summary("can you open up my github and give me a summary of the things i hvae"))
        self.assertFalse(accounts.wants_summary("open github desktop")); self.assertFalse(accounts.wants_summary("open github"))
    def run_it(self, dash):
        L = mock.Mock(); navs = []
        L.call.side_effect = lambda cmd, **a: dash if cmd == "snapshot" else {}
        ag = mock.Mock(); ag._answer_from.return_value = "2 repositories: liscia-agent (Python, private), notes."
        with mock.patch.object(webagent, "nav", lambda l, u, log=None, new_tab=False: navs.append(u)), \
             mock.patch.object(webagent, "main_text", lambda l, n=0: "liscia-agent Private Python Updated today\nnotes"):
            return accounts.github_summary(ag, L, "summarize my github", open(os.devnull, "w"), sleep=lambda s: None), navs
    def test_signed_in(self):
        r, navs = self.run_it(self.DASH)
        self.assertEqual(navs[-1], "https://github.com/rizxe134?tab=repositories"); self.assertIn("Your GitHub (rizxe134)", r)
    def test_signed_out_asks(self):
        r, navs = self.run_it(self.OUT); self.assertIn("sign in", r); self.assertEqual(len(navs), 1)
    def test_core_routes_not_to_desktop_app(self):
        import core
        from PIL import Image
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "planner": False}, "safety": {}}
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=mock.MagicMock(), capture=lambda: Image.new("RGB", (8, 8)), executor=lambda s: mock.Mock(), dom=False)
        a.link = lambda: mock.Mock(connected=lambda: True); a.focus_chrome = lambda: None; a.app_index = [{"name": "GitHub Desktop"}]
        with mock.patch.object(accounts, "github_summary", return_value="Your GitHub (x): ok") as g:
            r = a.run("can you open up my github and give me a summary of the things i hvae")
        self.assertEqual(r, "Your GitHub (x): ok"); g.assert_called_once()

if __name__ == "__main__": unittest.main()
