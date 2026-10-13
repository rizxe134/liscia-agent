import os, sys, json, unittest
from unittest import mock
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from actions import parse_action, ActionError, Executor, is_risky, search_url
import screen
from core import Agent
import actions as _actions, core as _core, intents as _intents
# Tests must never touch the real browser/OS: run them as "not macOS" unless a test patches it on purpose.
_actions.IS_MAC = False; _core.IS_MAC = False
_REAL_FRONT, _REAL_RECENT = _intents.browser_dom.frontmost_app, _intents.browser_dom.recent_browser
_intents.browser_dom.frontmost_app = lambda *a, **k: None
_intents.browser_dom.recent_browser = lambda *a, **k: None

class Parse(unittest.TestCase):
    def test_click_in_noise(self):
        a = parse_action('Sure! ```json\n{"action":"click","x":"10.6","y":20}\n```')
        self.assertEqual((a["action"], a["x"], a["y"]), ("click", 11, 20))
    def test_hotkey_string(self):
        self.assertEqual(parse_action('{"action":"hotkey","keys":"Ctrl+L"}')["keys"], ["ctrl", "l"])
    def test_errors(self):
        for bad in ["no json", '{"action":"fly"}', '{"action":"click","x":1}', '{"action":"type"}',
                    '{"action":"open_url"}', '{"action":"web_search"}', '{"action":"hotkey","keys":[]}']:
            with self.assertRaises(ActionError, msg=bad): parse_action(bad)
    def test_wait_clamped(self):
        self.assertEqual(parse_action('{"action":"wait","seconds":999}')["seconds"], 30.0)

class Execute(unittest.TestCase):
    def setUp(self):
        p = mock.patch("actions.IS_MAC", False); p.start(); self.addCleanup(p.stop)
        self.g, self.b = mock.MagicMock(), mock.MagicMock()
        self.ex = Executor(self.g, scale=2.0, move_duration=0, browser=self.b, sleep=mock.MagicMock())
    def test_click_scaled(self):
        self.ex.execute(parse_action('{"action":"click","x":100,"y":50}'))
        self.g.click.assert_called_once_with(200, 100)
    def test_type_enter(self):
        self.ex.execute(parse_action('{"action":"type","text":"hi","press_enter":true}'))
        self.g.write.assert_called_once(); self.g.press.assert_called_once_with("enter")
    def test_hotkey_scroll(self):
        self.ex.execute(parse_action('{"action":"hotkey","keys":["ctrl","t"]}')); self.g.hotkey.assert_called_with("ctrl", "t")
        self.ex.execute(parse_action('{"action":"scroll","amount":-3}')); self.g.scroll.assert_called_with(-300)
    def test_browser(self):
        self.ex.execute(parse_action('{"action":"open_url","url":"example.com"}'))
        self.b.open.assert_called_with("https://example.com")
        self.ex.execute(parse_action('{"action":"web_search","query":"ollama vision"}'))
        self.b.open.assert_called_with(search_url("ollama vision"))
    def test_done(self):
        self.assertTrue(self.ex.execute(parse_action('{"action":"done"}')))

class Risk(unittest.TestCase):
    W = ["buy", "send", "submit"]
    def test_cases(self):
        self.assertTrue(is_risky(parse_action('{"action":"click","x":1,"y":1,"reason":"click Buy now"}'), self.W))
        self.assertTrue(is_risky(parse_action('{"action":"type","text":"x","sensitive":true}'), self.W))
        self.assertFalse(is_risky(parse_action('{"action":"click","x":1,"y":1,"reason":"open search box"}'), self.W))

class Screen(unittest.TestCase):
    def test_prepare(self):
        img, s = screen.prepare(Image.new("RGB", (2560, 1440)), 1280, 100)
        self.assertEqual(img.size, (1280, 720)); self.assertEqual(s, 2.0)

class Loop(unittest.TestCase):
    def test_run(self, tmp="/tmp/pcagent-test"):
        cfg = {"ollama": {"host": "x", "model": "m"},
               "agent": {"max_steps": 5, "runs_dir": tmp, "plan": False, "step_delay_s": 0, "move_duration_s": 0},
               "safety": {"confirm_risky": True, "risky_words": ["send"], "kill_keys": []}}
        client = mock.MagicMock(); client.chat.side_effect = [
            "garbage", '{"action":"click","x":5,"y":5,"reason":"press Send"}',
            '{"action":"web_search","query":"q"}', '{"action":"done","summary":"ok"}']
        g = mock.MagicMock(); g.size.return_value = (800, 600); confirm = mock.MagicMock(return_value=False)
        with mock.patch("actions.webbrowser") as wb, mock.patch("actions.IS_MAC", False):
            agent = Agent(cfg, confirm=confirm, log=lambda m: None, gui=g,
                          capture=lambda: Image.new("RGB", (800, 600)), client=client)
            agent.kill.start = lambda: None
            self.assertEqual(agent.run("t"), "ok")
            wb.open.assert_called_once()
        confirm.assert_called_once(); g.click.assert_not_called()

if __name__ == "__main__":
    unittest.main()

class Route(unittest.TestCase):
    def test_route(self):
        from core import route
        c = mock.MagicMock()
        self.assertEqual(route(c, "/do open gmail"), ("task", "open gmail")); c.text_chat.assert_not_called()
        c.text_chat.return_value = '{"type":"chat","reply":"Hi!"}'
        self.assertEqual(route(c, "hello"), ("chat", "Hi!"))
        c.text_chat.return_value = '{"type":"task","task":"search weather"}'
        self.assertEqual(route(c, "check weather"), ("task", "search weather"))
        c.text_chat.return_value = "plain text"
        self.assertEqual(route(c, "hey"), ("chat", "plain text"))
        c.text_chat.return_value = "sure"
        self.assertEqual(route(c, "/chat hi"), ("chat", "sure"))

class MacSupport(unittest.TestCase):
    def test_keys(self):
        from actions import norm_key
        self.assertEqual(norm_key("cmd", mac=True), "command"); self.assertEqual(norm_key("cmd", mac=False), "ctrl")
        self.assertEqual(norm_key("ctrl", mac=True), "ctrl"); self.assertEqual(norm_key("option", mac=False), "alt")
    def test_retina_ratio(self):
        g = mock.MagicMock(); g.size.return_value = (1512, 982)
        self.assertAlmostEqual(screen.point_ratio(g, 3024), 0.5)
        g.size.return_value = (1920, 1080); self.assertEqual(screen.point_ratio(g, 1920), 1.0)
    def test_retina_click(self):
        # 3024px retina screenshot -> 1280 image (scale 2.3625) -> points (x0.5)
        img, s = screen.prepare(Image.new("RGB", (3024, 1964)), 1280, 0)
        g = mock.MagicMock(); g.size.return_value = (1512, 982)
        ex = Executor(g, scale=s * screen.point_ratio(g, 3024), move_duration=0)
        ex.execute(parse_action('{"action":"click","x":640,"y":400}'))
        g.click.assert_called_once_with(756, 472)

class KillSwitchTest(unittest.TestCase):
    def test_no_pynput_on_mac(self):
        from safety import KillSwitch
        k = KillSwitch()
        with mock.patch("sys.platform", "darwin"), mock.patch.object(KillSwitch, "_start_mac") as m:
            k.start(); m.assert_called_once()
        k.event.set(); self.assertTrue(k.killed); k.stop()

class LoopDetection(unittest.TestCase):
    def test_guard_levels(self):
        from core import LoopGuard
        g = LoopGuard(2, 3, 5); a = parse_action('{"action":"type","text":"youtube.com"}')
        self.assertEqual([g.check(a) for _ in range(5)], [0, 1, 2, 2, 3])
        self.assertEqual(g.check(parse_action('{"action":"open_app","app":"Safari"}')), 0)
    def test_nearby_clicks_same(self):
        from core import action_signature
        a = parse_action('{"action":"click","x":101,"y":201}'); b = parse_action('{"action":"click","x":105,"y":205}')
        self.assertEqual(action_signature(a), action_signature(b))

    def _cfg(self, tmp):
        return {"ollama": {"host": "x", "model": "m"},
                "agent": {"max_steps": 10, "runs_dir": tmp, "step_delay_s": 0, "plan": True},
                "safety": {"confirm_risky": False, "kill_keys": []}}

    def test_repeating_model_is_stopped_and_warned(self):
        client = mock.MagicMock(); client.text_chat.return_value = "1. open Safari"
        client.chat.return_value = '{"action":"type","text":"youtube.com"}'
        ex = mock.MagicMock(); g = mock.MagicMock(); g.size.return_value = (800, 600)
        agent = Agent(self._cfg("/tmp/pcagent-test"), log=lambda m: None, gui=g, client=client,
                      capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex)
        agent.kill.start = lambda: None
        res = agent.run("t")
        self.assertIn("stuck repeating", res)
        self.assertEqual(ex.execute.call_count, 2)          # repeats 3 and 4 were blocked
        prompts = [c.args[1] for c in client.chat.call_args_list]
        self.assertIn("PLAN:", prompts[0])
        self.assertIn("NO VISIBLE CHANGE", prompts[1])       # static screen detected
        self.assertIn("WARNING", prompts[2]); self.assertIn("NOT working", prompts[3])

    def test_screen_change_detected(self):
        frames = iter([Image.new("RGB", (800, 600)), Image.new("RGB", (800, 600), "white"), Image.new("RGB", (800, 600), "white")])
        client = mock.MagicMock(); client.chat.side_effect = ['{"action":"open_app","app":"Safari"}', '{"action":"done"}']
        g = mock.MagicMock(); g.size.return_value = (800, 600)
        cfg = self._cfg("/tmp/pcagent-test"); cfg["agent"]["plan"] = False
        agent = Agent(cfg, log=lambda m: None, gui=g, client=client, capture=lambda: next(frames), executor=lambda s: mock.MagicMock())
        agent.kill.start = lambda: None; agent.run("t")
        self.assertIn("screen changed", client.chat.call_args_list[1].args[1])

class HighLevelActions(unittest.TestCase):
    def test_open_app_and_browser(self):
        from actions import app_command
        self.assertEqual(app_command("Safari", "https://youtube.com", mac=True), ["open", "-a", "Safari", "https://youtube.com"])
        self.assertEqual(app_command("chrome", mac=False, windows=True), ["cmd", "/c", "start", "", "chrome"])
        run = mock.MagicMock(); b = mock.MagicMock()
        mock.patch("actions.IS_MAC", True).start(); self.addCleanup(mock.patch.stopall)
        ex = Executor(mock.MagicMock(), browser=b, runner=run, sleep=lambda s: None)
        ex.execute(parse_action('{"action":"open_app","app":"Safari"}')); self.assertEqual(run.call_args.args[0][-1], "Safari")
        ex.execute(parse_action('{"action":"open_url","url":"youtube.com","browser":"Safari"}'))
        self.assertEqual(run.call_args.args[0][-2:], ["Safari", "https://youtube.com"]); b.open.assert_not_called()
        with self.assertRaises(ActionError): parse_action('{"action":"open_app"}')
        self.assertTrue(parse_action('{"action":"type","text":"a","press_enter":"true"}')["press_enter"])

class BrowserDomTest(unittest.TestCase):
    def _runner(self, js_out):
        calls = []
        def run(cmd, **kw):
            calls.append(cmd); r = mock.MagicMock(returncode=0, stderr="")
            if cmd[:2] == ["lsappinfo", "front"]: r.stdout = "ASN:0x0-0x1234:"
            elif cmd[0] == "lsappinfo": r.stdout = '"LSDisplayName"="Safari"'
            else: r.stdout = js_out
            return r
        return run, calls
    def test_snapshot_and_click(self):
        import browser_dom
        snap = {"url": "https://youtube.com", "title": "YouTube", "elements": [{"id": 0, "tag": "a", "type": "", "text": "Lofi video", "x": 1, "y": 2}]}
        run, calls = self._runner(json.dumps(snap))
        with mock.patch("browser_dom.sys.platform", "darwin"), mock.patch.object(browser_dom, "frontmost_app", _REAL_FRONT):
            d = browser_dom.BrowserDOM(run=run, log=lambda m: None); s = d.snapshot()
        self.assertEqual(s["app"], "Safari"); self.assertIn('[0] a "Lofi video"', browser_dom.format_elements(s))
        self.assertIn("do JavaScript", calls[-1][4])
        run2, calls2 = self._runner("ok"); d.run = run2; d.click(0); self.assertIn("__pca", calls2[-1][-1])
        ex = Executor(mock.MagicMock(), dom=d); ex.execute(parse_action('{"action":"click_element","id":"0"}'))
    def test_not_browser(self):
        import browser_dom
        run, _ = self._runner("")
        def run_finder(cmd, **kw):
            r = run(cmd, **kw)
            if cmd[0] == "lsappinfo" and cmd[1] == "info": r.stdout = '"LSDisplayName"="Finder"'
            return r
        with mock.patch("browser_dom.sys.platform", "darwin"), mock.patch.object(browser_dom, "frontmost_app", _REAL_FRONT):
            self.assertIsNone(browser_dom.BrowserDOM(run=run_finder, log=lambda m: None).snapshot())

class FastPathTest(unittest.TestCase):
    def test_dom_text_path_used(self):
        dom = mock.MagicMock(); dom.snapshot.return_value = {"app": "Safari", "url": "u", "title": "t",
            "elements": [{"id": 3, "tag": "a", "type": "", "text": "First video", "x": 1, "y": 1}]}
        client = mock.MagicMock(); client.num_predict = 200
        client.text_chat.side_effect = ['{"action":"click_element","id":3}', '{"action":"done","summary":"ok"}']
        ex = mock.MagicMock(); g = mock.MagicMock(); g.size.return_value = (800, 600)
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 5, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "plan": False},
               "safety": {"confirm_risky": False, "kill_keys": []}}
        agent = Agent(cfg, log=lambda m: None, gui=g, client=client, capture=lambda: Image.new("RGB", (800, 600)),
                      executor=lambda s: ex, dom=dom)
        agent.kill.start = lambda: None
        self.assertEqual(agent.run("pick the cat clip from the list"), "ok")
        client.chat.assert_not_called()   # no vision call needed
        self.assertIn('[3] a "First video"', client.text_chat.call_args_list[0].args[0][1]["content"])
        self.assertEqual(ex.execute.call_args.args[0]["id"], 3)

class StreamingTest(unittest.TestCase):
    def test_stream_tokens(self):
        from llm import OllamaClient
        lines = [json.dumps({"message": {"content": p}, "done": False}).encode() for p in ("Hel", "lo")] + [json.dumps({"done": True}).encode()]
        resp = mock.MagicMock(status_code=200); resp.iter_lines.return_value = lines
        resp.__enter__ = lambda s: resp; resp.__exit__ = lambda *a: False
        got = []
        with mock.patch("llm.requests.post", return_value=resp) as post:
            out = OllamaClient("http://h", "m", text_model="t").text_chat([{"role": "user", "content": "hi"}], on_token=got.append)
        self.assertEqual((out, got), ("Hello", ["Hel", "lo"]))
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["model"], body["keep_alive"], body["stream"], body["think"]), ("t", "30m", True, False))
    def test_route_streams_chat(self):
        from core import route
        c = mock.MagicMock(); c.text_chat.side_effect = ['{"type":"chat"}', "Hi there"]
        self.assertEqual(route(c, "hello", on_token=lambda p: None), ("chat", "Hi there"))
        self.assertIsNotNone(c.text_chat.call_args.kwargs["on_token"])

class NestedParams(unittest.TestCase):
    def test_flatten(self):
        a = parse_action('{"action":"open_app","params":{"app":"Safari"}}')
        self.assertEqual(a["app"], "Safari")

class TrailingJunk(unittest.TestCase):
    def test_two_objects(self):
        self.assertEqual(parse_action('{"action":"wait","seconds":1}\n{"action":"done"}')["action"], "wait")

class NormCoords(unittest.TestCase):
    def test_qwen3_norm(self):
        from core import uses_norm_coords, denormalize, NORM_SYSTEM
        self.assertTrue(uses_norm_coords({"ollama": {"model": "qwen3-vl:4b-instruct"}, "agent": {}}))
        self.assertFalse(uses_norm_coords({"ollama": {"model": "qwen2.5vl:7b"}, "agent": {}}))
        self.assertEqual(denormalize({"action": "click", "x": 138, "y": 960}, 1024, 665)["x"], 141)
        self.assertIn("NORMALIZED 0-1000", NORM_SYSTEM)
    def test_loop_denormalizes(self):
        client = mock.MagicMock(); client.chat.side_effect = ['{"action":"click","x":500,"y":500}', '{"action":"done"}']
        ex = mock.MagicMock(); g = mock.MagicMock(); g.size.return_value = (800, 600)
        cfg = {"ollama": {"host": "x", "model": "qwen3-vl:4b-instruct"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "plan": False},
               "safety": {"confirm_risky": False, "kill_keys": []}}
        agent = Agent(cfg, log=lambda m: None, gui=g, client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex, dom=False)
        agent.kill.start = lambda: None; agent.run("t")
        a = ex.execute.call_args.args[0]; self.assertEqual((a["x"], a["y"]), (400, 300))
        self.assertIn("NORMALIZED", client.chat.call_args_list[0].args[0])

class IntentsTest(unittest.TestCase):
    def setUp(self):
        import intents; intents.STATE.update(browser=None, app=None)
    def test_plan(self):
        import intents
        acts, rest = intents.plan("open safari, search for youtube.com, and click on the first video")
        self.assertEqual([a["action"] for a in acts], ["open_app", "open_url", "first_video"])
        self.assertEqual((acts[0]["app"], acts[1]["url"], rest), ("Safari", "https://www.youtube.com", ""))
        self.assertEqual(intents.plan("open youtube")[0][0]["url"], "https://www.youtube.com")
        self.assertEqual(intents.plan("go to youtube.com in chrome")[0][0]["browser"], "Google Chrome")
        self.assertEqual(intents.plan("write an email to bob"), ([], "write an email to bob"))
        acts, rest = intents.plan("open safari and write a poem in notes")
        self.assertEqual((len(acts), rest), (1, "write a poem in notes"))
    def test_router_imperative(self):
        from core import route
        c = mock.MagicMock()
        self.assertEqual(route(c, "open youtube"), ("task", "open youtube"))
        self.assertEqual(route(c, "now click the first video"), ("task", "now click the first video"))
        c.text_chat.assert_not_called()
    def test_open_url_uses_current_browser(self):
        import intents
        run = mock.MagicMock(); b = mock.MagicMock()
        with mock.patch("actions.IS_MAC", True), mock.patch("intents.browser_dom.frontmost_app", return_value="PC Agent"):
            ex = Executor(mock.MagicMock(), browser=b, runner=run, sleep=lambda s: None)
            ex.execute(parse_action('{"action":"open_app","app":"Safari"}'))
            ex.execute(parse_action('{"action":"open_url","url":"https://www.youtube.com"}'))
        self.assertEqual(run.call_args.args[0], ["open", "-a", "Safari", "https://www.youtube.com"]); b.open.assert_not_called()
        self.assertEqual(intents.STATE["browser"], "Safari")
    def test_frontmost_browser_wins(self):
        import intents
        intents.STATE["browser"] = "Safari"
        with mock.patch("intents.browser_dom.frontmost_app", return_value="Google Chrome"):
            self.assertEqual(intents.current_browser(), "Google Chrome")
    def test_first_video_js_and_fallback(self):
        import intents
        from actions import NeedsVision
        intents.STATE["browser"] = "Safari"
        with mock.patch("actions.IS_MAC", True), mock.patch("intents.browser_dom.frontmost_app", return_value="Safari"):
            with mock.patch("browser_dom.run_js", return_value="ok|Lofi radio") as js:
                ex = Executor(mock.MagicMock(), sleep=lambda s: None); ex.execute({"action": "first_video"})
                self.assertEqual(ex.last_info, "Lofi radio"); self.assertIn("video-title-link", js.call_args.args[1])
            with mock.patch("browser_dom.run_js", side_effect=RuntimeError("JavaScript from Apple Events is turned off")):
                with self.assertRaises(NeedsVision): Executor(mock.MagicMock(), sleep=lambda s: None).execute({"action": "first_video"})

    def _agent(self, client, ex):
        g = mock.MagicMock(); g.size.return_value = (800, 600)
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 4, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "plan": False, "page_wait_s": 0},
               "safety": {"confirm_risky": False, "kill_keys": []}}
        a = Agent(cfg, log=lambda m: None, gui=g, client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex, dom=False)
        a.kill.start = lambda: None; return a
    def test_full_flow_no_model(self):
        client = mock.MagicMock(); ex = mock.MagicMock()
        res = self._agent(client, ex).run("open safari and open youtube and click the first video")
        self.assertTrue(res.startswith("done"))
        self.assertEqual([c.args[0]["action"] for c in ex.execute.call_args_list], ["open_app", "open_url", "first_video"])
        client.chat.assert_not_called(); client.text_chat.assert_not_called()
    def test_first_video_falls_back_to_vision(self):
        from actions import NeedsVision
        client = mock.MagicMock(); client.chat.side_effect = ['not sure', '{"action":"click","x":100,"y":100}', '{"action":"done","summary":"clicked"}']
        ex = mock.MagicMock()
        def execute(a):
            if a["action"] == "first_video": raise NeedsVision("js off")
        ex.execute.side_effect = execute
        self.assertEqual(self._agent(client, ex).run("open youtube and click the first video"), "clicked")
        self.assertIn("click the first video", client.chat.call_args_list[1].args[1])
        self.assertIn("(already done) open_url", client.chat.call_args_list[1].args[1])
    def test_first_video_vision_locate_clicks_points(self):
        from actions import NeedsVision
        client = mock.MagicMock(); client.chat.return_value = '{"x": 250, "y": 500}'
        ex = mock.MagicMock()
        def execute(a):
            if a["action"] == "first_video": raise NeedsVision("js off")
        ex.execute.side_effect = execute
        a = self._agent(client, ex)
        a.capture = lambda: Image.new("RGB", (1600, 1200))  # Retina-like: 2x the 800x600 points
        res = a.run("open youtube and click the first video")
        self.assertTrue(res.startswith("done"), res)
        a.gui.click.assert_called_with(200, 300)  # 250/1000*1280*1.25*0.5 = 200 ; 500/1000*960*1.25*0.5 = 300

class RecentBrowser(unittest.TestCase):
    def test_parse(self):
        import browser_dom
        r = mock.MagicMock(stdout='ASN:0x0-0x1: "PC_Agent", ASN:0x0-0x2: "Finder", ASN:0x0-0x3: "Safari", ASN:0x0-0x4: "Google_Chrome"')
        with mock.patch("browser_dom.sys.platform", "darwin"):
            self.assertEqual(_REAL_RECENT(run=lambda *a, **k: r), "Safari")

class RealRunRegressions(unittest.TestCase):
    def test_string_params(self):
        self.assertEqual(parse_action('{"action":"open_app","params":"Chrome"}')["app"], "Chrome")
    def test_invented_ids_stop_and_no_click_element_offered(self):
        client = mock.MagicMock(); client.chat.return_value = '{"action":"click_element","params":{"id":"video_0"}}'
        g = mock.MagicMock(); g.size.return_value = (800, 600)
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 25, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "plan": False},
               "safety": {"confirm_risky": False, "kill_keys": []}}
        a = Agent(cfg, log=lambda m: None, gui=g, client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: mock.MagicMock(), dom=False)
        a.kill.start = lambda: None
        self.assertIn("invalid action", a.run("do the thing"))
        self.assertEqual(client.chat.call_count, 5)
        self.assertNotIn("click_element", client.chat.call_args_list[0].args[0])
        self.assertIn("rejected", client.chat.call_args_list[1].args[1])
    def test_preferred_browser(self):
        import intents
        intents.STATE.update(browser=None, preferred="Safari")
        with mock.patch("intents.browser_dom.frontmost_app", return_value="PC Agent"):
            self.assertEqual(intents.current_browser(), "Safari")
        intents.STATE["preferred"] = None

class BrowserTargeting(unittest.TestCase):
    def setUp(self):
        _intents.STATE.update(browser=None, app=None, preferred=None)
    def test_open_url_uses_last_opened_browser(self):
        cmds = []
        with mock.patch("actions.IS_MAC", True):
            ex = Executor(gui=mock.Mock(), runner=cmds.append, sleep=lambda s: None)
            ex.execute({"action": "open_app", "app": "Safari"})
            ex.execute({"action": "open_url", "url": "youtube.com"})
            ex.execute({"action": "web_search", "query": "cats"})
        self.assertEqual(cmds[1], ["open", "-a", "Safari", "https://youtube.com"])
        self.assertEqual(cmds[2][:3], ["open", "-a", "Safari"])
    def test_frontmost_browser_wins(self):
        _intents.STATE["browser"] = "Safari"
        self.assertEqual(_intents.current_browser(lambda: "Google Chrome"), "Google Chrome")
        self.assertEqual(_intents.current_browser(lambda: "Finder"), "Google Chrome")  # persists across messages
    def test_open_youtube_deterministic(self):
        self.assertEqual(_intents.plan("open youtube")[0], [{"action": "open_url", "url": "https://www.youtube.com"}])
        acts, rest = _intents.plan("open safari and go to youtube then click the first video")
        self.assertEqual([a["action"] for a in acts], ["open_app", "open_url", "first_video"]); self.assertEqual(rest, "")
    def test_first_video_via_js_and_fallback(self):
        with mock.patch("actions.IS_MAC", True), mock.patch("intents.current_browser", return_value="Safari"):
            ex = Executor(gui=mock.Mock(), runner=lambda c: None, sleep=lambda s: None)
            with mock.patch("browser_dom.run_js", return_value="ok|Some video"):
                ex.execute({"action": "first_video"}); self.assertEqual(ex.last_info, "Some video")
            with mock.patch("browser_dom.run_js", side_effect=RuntimeError("not allowed")):
                with self.assertRaises(_actions.NeedsVision): ex.execute({"action": "first_video"})
    def test_imperative_followups_are_tasks(self):
        from core import route
        c = mock.Mock()
        for m in ["click on the first video", "now play the first one", "pause it", "scroll down"]:
            self.assertEqual(route(c, m)[0], "task", m)
        c.text_chat.assert_not_called()

class Round2(unittest.TestCase):
    def test_press_enter_alias(self):
        for raw in ['{"action":"press_enter"}', '{"action":"enter"}', '{"action":"key","key":"enter"}']:
            a = parse_action(raw); self.assertEqual((a["action"], a["keys"]), ("hotkey", ["enter"]))
    def test_search_youtube_deterministic(self):
        acts, rest = _intents.plan("search youtube for 'embrace it' and play the first video")
        self.assertEqual(rest, "")
        self.assertEqual(acts, [{"action": "open_url", "url": "https://www.youtube.com/results?search_query=embrace+it"},
                                {"action": "first_video"}])
        self.assertEqual(_intents.plan("search for embrace it on youtube")[0][0]["url"][-10:], "embrace+it")
    def test_to_points(self):
        from core import to_points
        self.assertEqual(to_points(500, 500, 1280, 831, 3024/1280, 1512/3024), (756, 491))
    def test_retype_is_repeat(self):
        from core import LoopGuard
        g = LoopGuard()
        self.assertEqual(g.check({"action": "type", "text": "embrace it"}), 0)
        g.check({"action": "wait", "seconds": 2})
        self.assertGreaterEqual(g.check({"action": "type", "text": "Embrace it"}), 1)
        self.assertGreaterEqual(g.check({"action": "type", "text": "embrace it"}), 2)
    def test_goal_reached(self):
        self.assertTrue(_intents.goal_reached("play the first video", "https://www.youtube.com/watch?v=x"))
        self.assertFalse(_intents.goal_reached("play the first video", "https://www.youtube.com/results?q"))

class PanelBridge(unittest.TestCase):
    def setUp(self):
        import server, threading, urllib.request
        self.server, self.ur = server, urllib.request
        class FakeAgent:
            def __init__(s, br): s.client = None; s.kill = mock.Mock(); s.kill.event = threading.Event(); s.br = br
            def run(s, task):
                ok = s.br.hub.confirm("click Buy?", timeout=5)
                s.br.log('[1] click {"x": 10, "y": 20}'); return f"ran {task} ok={ok}"
        def router(client, text, hist, on_token=None):
            return ("task", text) if text.startswith("do") else ("chat", "hi " + text)
        br = server.Bridge({}, token="t" * 40, agent_factory=FakeAgent, router=router)
        self.srv, self.br = server.serve({}, port=0, bridge=br) if False else (None, br)
        from http.server import ThreadingHTTPServer
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(br)); self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.addCleanup(self.srv.shutdown)
    def req(self, path, body=None, token="t" * 40, origin=None):
        import json as j
        h = {"Content-Type": "application/json"}
        if token: h["X-PCA-Token"] = token
        if origin: h["Origin"] = origin
        r = self.ur.Request(self.base + path, data=j.dumps(body).encode() if body is not None else None, headers=h)
        try:
            with self.ur.urlopen(r, timeout=5) as resp: return resp.status, j.loads(resp.read())
        except self.ur.HTTPError as e: return e.code, None
    def test_auth(self):
        self.assertEqual(self.req("/health", token=None)[0], 401)
        self.assertEqual(self.req("/health", token="wrong")[0], 401)
        self.assertEqual(self.req("/health", origin="https://evil.example")[0], 401)  # web pages can't drive it
        self.assertEqual(self.req("/health", origin="chrome-extension://" + "a" * 32)[0], 200)
    def test_task_with_confirm_and_steps(self):
        import time as t
        q = self.br.hub.subscribe()
        self.assertTrue(self.req("/chat", {"text": "do buy it"})[1]["accepted"])
        got, cid = [], None
        end = t.time() + 5
        while t.time() < end:
            m = json.loads(q.get(timeout=5)); got.append(m["type"])
            if m["type"] == "confirm": cid = m["id"]; self.req("/confirm", {"id": cid, "ok": True})
            if m["type"] == "result": self.assertEqual(m["text"], "ran do buy it ok=True"); break
        self.assertIn("step", got); self.assertIn("confirm_done", got); self.assertIsNotNone(cid)
    def test_chat_and_stop(self):
        import time as t
        q = self.br.hub.subscribe(); self.req("/chat", {"text": "hello"})
        while True:
            m = json.loads(q.get(timeout=5))
            if m["type"] == "chat": self.assertEqual(m["text"], "hi hello"); break
        self.assertEqual(self.req("/takeover", {})[0], 200)
    def test_token_file_private(self):
        import tempfile, stat
        p = os.path.join(tempfile.mkdtemp(), "tok")
        t1 = self.server.load_token(p); self.assertGreaterEqual(len(t1), 32); self.assertEqual(self.server.load_token(p), t1)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
