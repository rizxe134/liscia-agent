"""1.4.2: window binding, never acting on a non-target window, Spotify adapter, verbatim queries, desktop action set."""
import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import adapters, appui, planner, winbind

WINDOWS = [
    {"hwnd": 11, "title": "Gettin money - Google Chrome", "proc": "chrome.exe", "exe": r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "w": 1600, "h": 1000},
    {"hwnd": 22, "title": "New Tab - Chromium", "proc": "Spotify.exe", "exe": r"C:\\Users\\u\\AppData\\Roaming\\Spotify\\Spotify.exe", "w": 1200, "h": 800},
    {"hwnd": 33, "title": "Spotify Premium", "proc": "Spotify.exe", "exe": r"C:\\Users\\u\\AppData\\Roaming\\Spotify\\Spotify.exe", "w": 1400, "h": 900},
    {"hwnd": 44, "title": "", "proc": "Spotify.exe", "exe": "", "w": 1400, "h": 900},
    {"hwnd": 55, "title": "Untitled - Notepad", "proc": "Notepad.exe", "exe": r"C:\\Program Files\\WindowsApps\\Microsoft.WindowsNotepad_11\\Notepad\\Notepad.exe", "w": 900, "h": 700},
    {"hwnd": 66, "title": "Calculator", "proc": "ApplicationFrameHost.exe", "exe": r"C:\\Windows\\System32\\ApplicationFrameHost.exe", "w": 400, "h": 600},
    {"hwnd": 77, "title": "tiny", "proc": "Spotify.exe", "exe": "", "w": 50, "h": 20},
]

class Binding(unittest.TestCase):
    def test_pick_main_window_not_helper_or_chrome(self):
        w = winbind.pick(WINDOWS, winbind.exe_hints("Spotify", {"name": "Spotify", "target": r"C:\\x\\Spotify.exe"}), "Spotify")
        self.assertEqual(w["hwnd"], 33)
    def test_pick_aumid_and_uwp_host(self):
        e = {"name": "Notepad", "target": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "kind": "aumid"}
        self.assertEqual(winbind.pick(WINDOWS, winbind.exe_hints("notepad", e), "notepad")["hwnd"], 55)
        c = {"name": "Calculator", "target": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", "kind": "aumid"}
        self.assertEqual(winbind.pick(WINDOWS, winbind.exe_hints("calculator", c), "calculator")["hwnd"], 66)
    def test_no_window_none(self):
        self.assertIsNone(winbind.pick(WINDOWS, winbind.exe_hints("discord"), "discord"))
    def _b(self, fg, focus_ok=True):
        state = {"fg": fg}
        def focus(h):
            if focus_ok: state["fg"] = h
            return focus_ok
        b = winbind.WindowBinding("Spotify", None, lister=lambda: WINDOWS, fg=lambda: state["fg"], focus=focus,
                                  rect=lambda h: [100, 50, 1500, 950], title=lambda h: "Spotify Premium", alive=lambda h: True)
        b.bind(timeout=0, sleep=lambda s: None); return b, state
    def test_ensure_refocuses(self):
        b, st = self._b(fg=11)
        self.assertTrue(b.ensure(sleep=lambda s: None)); self.assertEqual(st["fg"], 33)
    def test_ensure_fails_when_focus_stolen(self):
        b, st = self._b(fg=11, focus_ok=False)
        self.assertFalse(b.ensure(sleep=lambda s: None))
    def test_bind_waits_for_window(self):
        calls = {"n": 0}
        def lister():
            calls["n"] += 1
            return WINDOWS[:2] if calls["n"] < 3 else WINDOWS
        b = winbind.WindowBinding("Spotify", None, lister=lister, fg=lambda: 0, focus=lambda h: True)
        w = b.bind(timeout=5, sleep=lambda s: None); self.assertEqual(w["hwnd"], 33); self.assertGreaterEqual(calls["n"], 3)

class NeverWrongWindow(unittest.TestCase):
    def test_appui_refuses_when_not_foreground(self):
        b = mock.Mock(); b.ensure.return_value = False; b.app = "Spotify"
        ui = appui.AppUI(gui=mock.Mock(), raw_fn=lambda: ("chrome.exe", "Chrome", []), binding=b)
        with self.assertRaises(appui.WrongWindow): ui.snapshot()
    def test_click_refused_after_focus_lost(self):
        b = mock.Mock(); b.ensure.side_effect = [True, False]; b.app = "Spotify"
        g = mock.Mock()
        ui = appui.AppUI(gui=g, raw_fn=lambda: ("Spotify.exe", "Spotify Premium", [{"role": "ButtonControl", "name": "Play", "rect": [0, 0, 20, 20]}]), binding=b)
        ui.snapshot()
        with self.assertRaises(appui.WrongWindow): ui.click(1)
        g.click.assert_not_called()
    def test_agent_stops_instead_of_acting_elsewhere(self):
        from PIL import Image
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False,
                                                                 "chrome_extension": False, "app_start_wait_s": 0, "app_ui": False}, "safety": {}}
        client = mock.MagicMock(); client.chat.return_value = '{"action":"click","x":5,"y":5}'
        ex = mock.Mock(last_info="launched Discord")
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex)
        b = mock.Mock(app="Discord"); b.bind.return_value = {"hwnd": 9, "title": "Discord", "proc": "Discord.exe", "pid": 1}
        b.ensure.side_effect = [True, False]; b.window_rect.return_value = [0, 0, 800, 600]
        a.binding_factory = lambda app: b
        r = a.run("open discord and click the general channel")
        self.assertIn("couldn't be brought back", r); client.chat.assert_not_called()
        self.assertEqual([c.args[0]["action"] for c in ex.execute.call_args_list], ["open_app"])

class SpotifyAdapter(unittest.TestCase):
    def test_flow_plays_matching_row_and_verifies_title(self):
        pressed = []; titles = iter(["Spotify Premium", "Spotify Premium", "Vive - Gettin Money"])
        rows = [("The Cayo Perico Heist", lambda: pressed.append("cayo")), ("Gettin Money", lambda: pressed.append("gm")),
                ("Gettin Money - Slowed Version", lambda: pressed.append("slow"))]
        sp = adapters.SpotifyPlay("gettin money", rows_fn=lambda: rows, title_fn=lambda: next(titles, "Vive - Gettin Money"), sleep=lambda s: None)
        self.assertEqual(sp.launch_uri, "spotify:search:gettin%20money")
        agent = mock.Mock(); agent.app_binding.ensure.return_value = True
        r = sp.run(agent)
        self.assertEqual(pressed, ["gm"]); self.assertIn("Vive - Gettin Money", r)
    def test_waits_for_results_and_refuses_wrong_window(self):
        agent = mock.Mock(); agent.app_binding.ensure.return_value = False
        sp = adapters.SpotifyPlay("x", rows_fn=lambda: [("x", lambda: None)], title_fn=lambda: "", sleep=lambda s: None)
        with self.assertRaises(RuntimeError): sp.run(agent)
    def test_unverified_returns_none(self):
        agent = mock.Mock(); agent.app_binding.ensure.return_value = True
        sp = adapters.SpotifyPlay("abc", rows_fn=lambda: [("abc", lambda: None)], title_fn=lambda: "Spotify Premium", sleep=lambda s: None)
        self.assertIsNone(sp.run(agent))
    def test_for_app_and_verbatim(self):
        a = adapters.for_app("spotify", "can you open spotify then play gettin money")
        self.assertEqual(a.query, "gettin money")
        for t, q in [("open spotify and play Pursuit by isq", "Pursuit by isq"), ("open spotify and play gettin money on spotify", "gettin money"),
                     ("launch spotify then play the song blinding lights please", "blinding lights")]:
            self.assertEqual(adapters.verbatim_target(t), q, t)
        self.assertIsNone(adapters.for_app("spotify", "open spotify"))
        self.assertIsNone(adapters.for_app("discord", "open discord and play x"))
    def test_agent_uses_uri_and_adapter(self):
        from PIL import Image
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 2, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False,
                                                                 "chrome_extension": False, "app_start_wait_s": 0, "app_ui": False}, "safety": {}}
        client = mock.MagicMock(); ex = mock.Mock()
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex)
        b = mock.Mock(app="spotify"); b.bind.return_value = {"hwnd": 33, "title": "Spotify Premium", "proc": "Spotify.exe", "pid": 1}; b.ensure.return_value = True
        a.binding_factory = lambda app: b
        with mock.patch("adapters.open_uri") as ou, mock.patch("adapters.SpotifyPlay.run", return_value='Playing "Vive - Gettin Money" in Spotify'):
            r = a.run("can you open spotify then play gettin money")
        ou.assert_called_once_with("spotify:search:gettin%20money"); self.assertIn("Gettin Money", r)
        ex.execute.assert_not_called(); client.chat.assert_not_called()

class Verbatim(unittest.TestCase):
    def test_model_spellfix_reverted(self):
        c = mock.Mock(); c.text_chat.return_value = '{"intent":"desktop_app","app":"Spotify","query":"getting money","outputs":[]}'
        p = planner.plan(c, "can you open spotify then play gettin money")
        self.assertEqual(p["intent"], "desktop_app"); self.assertEqual(p["query"], "gettin money")
        c.text_chat.return_value = '{"intent":"media_play","query":"Pursuit by Isaac","outputs":[]}'
        self.assertNotIn("Isaac", planner.plan(c, "play pursuit by isq on youtube")["query"])
    def test_plan_for_sentence(self):
        p = planner.plan(None, "can you open spotify then play gettin money", use_model=False)
        self.assertEqual((p["intent"], p["app"].lower()), ("desktop_app", "spotify"))

class DesktopActionSet(unittest.TestCase):
    def test_web_actions_blocked_and_hidden(self):
        from PIL import Image
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 4, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False,
                                                                 "chrome_extension": False, "app_start_wait_s": 0, "app_ui": False, "plan": False}, "safety": {}}
        client = mock.MagicMock()
        client.chat.side_effect = ['{"action":"web_search","query":"gettin money"}', '{"action":"open_url","url":"https://open.spotify.com"}',
                                   '{"action":"hotkey","keys":["ctrl","t"]}', '{"action":"done","summary":"x"}']
        ex = mock.Mock(last_info="")
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex)
        b = mock.Mock(app="Discord"); b.bind.return_value = {"hwnd": 9, "title": "Discord", "proc": "Discord.exe", "pid": 1}
        b.ensure.return_value = True; b.window_rect.return_value = [100, 100, 700, 500]
        a.binding_factory = lambda app: b
        a.run("open discord and find the music channel")
        acts = [c.args[0]["action"] for c in ex.execute.call_args_list]
        self.assertEqual(acts, ["open_app"])  # none of the web actions ran
        sys_prompt = client.chat.call_args_list[0].args[0]
        self.assertNotIn("web_search:", sys_prompt); self.assertNotIn("open_url:", sys_prompt)
    def test_crop_offset_applied(self):
        from actions import Executor
        e = Executor(gui=mock.Mock(), scale=1.0); e.offset = (100, 50)
        e.execute({"action": "click", "x": 10, "y": 20}); e.gui.click.assert_called_with(110, 70)

if __name__ == "__main__": unittest.main()
