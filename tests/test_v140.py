"""1.4.0: installed-app discovery, core-app denylist, desktop_app routing, app UI snapshot parsing (all mocked)."""
import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import appindex, appui, planner, policy

WIN_SCAN = [
    {"name": "Notepad", "path": "", "target": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "kind": "aumid"},
    {"name": "Spotify", "path": r"C:\\Users\\u\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Spotify.lnk", "target": r"C:\\Users\\u\\AppData\\Roaming\\Spotify\\Spotify.exe", "kind": "lnk"},
    {"name": "Adobe Photoshop 2025", "path": r"C:\\ProgramData\\...\\Adobe Photoshop 2025.lnk", "target": r"C:\\Program Files\\Adobe\\Photoshop.exe", "kind": "lnk"},
    {"name": "Uninstall Spotify", "path": "x.lnk", "target": "u.exe", "kind": "lnk"},
    {"name": "Spotify Website", "path": "w.url", "target": "", "kind": "lnk"},
    {"name": "VLC media player", "path": "vlc.lnk", "target": r"C:\\Program Files\\VideoLAN\\VLC\\vlc.exe", "kind": "lnk"},
    {"name": "Google Chrome", "path": "chrome.lnk", "target": r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "kind": "lnk"},
    {"name": "Visual Studio Code", "path": "code.lnk", "target": r"C:\\code\\Code.exe", "kind": "lnk"},
    {"name": "Calculator", "path": "", "target": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", "kind": "aumid"},
    {"name": "Control Panel", "path": "", "target": "Microsoft.Windows.ControlPanel", "kind": "aumid"},
    {"name": "Settings", "path": "", "target": "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel", "kind": "aumid"},
    {"name": "Registry Editor", "path": "regedit.lnk", "target": r"C:\\Windows\\regedit.exe", "kind": "lnk"},
    {"name": "Windows PowerShell", "path": "ps.lnk", "target": r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "kind": "lnk"},
    {"name": "Task Manager", "path": "tm.lnk", "target": r"C:\\Windows\\system32\\Taskmgr.exe", "kind": "lnk"},
    {"name": "Microsoft Word", "path": "", "target": "Microsoft.Office.WINWORD.EXE.15", "kind": "aumid"},
    {"name": "Discord", "path": "d.lnk", "target": r"C:\\Users\\u\\AppData\\Local\\Discord\\Update.exe", "kind": "lnk"},
]
IDX = appindex.build(WIN_SCAN)

class Discovery(unittest.TestCase):
    def test_fuzzy_matching(self):
        for q, want in [("spotify", "Spotify"), ("Spotify app", "Spotify"), ("photoshop", "Adobe Photoshop 2025"), ("notepad", "Notepad"),
                        ("notpad", "Notepad"), ("vlc", "VLC media player"), ("chrome", "Google Chrome"), ("vs code", "Visual Studio Code"),
                        ("calculator", "Calculator"), ("calc", "Calculator"), ("word", "Microsoft Word"), ("discord", "Discord")]:
            e = appindex.find(q, IDX); self.assertIsNotNone(e, q); self.assertEqual(e["name"], want, q)
    def test_no_match(self):
        self.assertIsNone(appindex.find("blender", IDX)); self.assertIsNone(appindex.find("", IDX))
    def test_junk_dropped(self):
        names = [e["name"] for e in IDX]
        self.assertNotIn("Uninstall Spotify", names); self.assertNotIn("Spotify Website", names)
    def test_core_tagged(self):
        core = {e["name"]: e["core"] for e in IDX}
        for n in ["Control Panel", "Settings", "Registry Editor", "Windows PowerShell", "Task Manager"]: self.assertTrue(core[n], n)
        for n in ["Spotify", "Notepad", "Microsoft Word", "Calculator"]: self.assertFalse(core[n], n)
    def test_launch_uses_real_target(self):
        calls = []
        with mock.patch.object(appindex, "IS_WIN", True), mock.patch.object(appindex, "IS_MAC", False):
            e, blocked = appindex.launch("notepad", run=calls.append, idx=IDX)
            self.assertIsNone(blocked); self.assertEqual(calls[-1], ["explorer.exe", "shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"])
            e, blocked = appindex.launch("spotify", run=calls.append, idx=IDX)
            self.assertIn("Spotify.lnk", calls[-1][-1])
    def test_launch_refuses_core(self):
        calls = []
        for q in ["control panel", "settings", "regedit", "registry editor", "powershell", "task manager"]:
            e, blocked = appindex.launch(q, run=calls.append, idx=IDX)
            self.assertTrue(blocked, q)
        self.assertEqual(calls, [])
    def test_mac_scan(self):
        import tempfile
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "Spotify.app")); os.makedirs(os.path.join(d, "System Settings.app"))
        idx = appindex.build(appindex.scan_mac([d]))
        self.assertEqual(appindex.find("spotify", idx)["path"], os.path.join(d, "Spotify.app"))
        self.assertTrue(appindex.find("system settings", idx)["core"])
    def test_lookup_error(self):
        with self.assertRaises(LookupError): appindex.launch("zzzunknownapp", run=lambda c: None, idx=IDX)

class Denylist(unittest.TestCase):
    ALIASES = ["Control Panel", "control", "control.exe", "regedit", "regedit.exe", "Registry Editor", "Settings", "Windows Settings",
               "System Settings", "System Preferences", "ms-settings:", "com.apple.systempreferences", "SystemSettings.exe",
               "services.msc", "services", "gpedit.msc", "Group Policy Editor", "cmd", "cmd.exe", "Command Prompt", "PowerShell",
               "Windows PowerShell", "pwsh", "Terminal", "Windows Terminal", "wt.exe", "com.apple.Terminal", "Task Manager", "taskmgr",
               "Taskmgr.exe", "Activity Monitor", "com.apple.ActivityMonitor", "Disk Management", "diskmgmt.msc", "Disk Utility",
               "Windows Security", "Windows Defender Firewall", "wf.msc", "firewall.cpl", "User Accounts", "netplwiz", "lusrmgr.msc",
               "msconfig", "System Configuration", "Device Manager", "devmgmt.msc", "Event Viewer", "Run",
               r"C:\\Windows\\System32\\cmd.exe", r"C:\\Windows\\regedit.exe", "/System/Applications/System Settings.app"]
    def test_aliases_blocked(self):
        for a in self.ALIASES:
            self.assertTrue(policy.core_app(a), a); self.assertTrue(policy.check({"action": "open_app", "app": a}), a)
    def test_ok_apps(self):
        for a in ["Notepad", "Spotify", "Calculator", "Microsoft Excel", "PowerPoint", "Photos", "Paint", "Steam", "Slack", "Zoom",
                  "Adobe Photoshop 2025", "Visual Studio Code", "Notes", "Music", "Discord", "Obsidian", "Settings Sync Helper Docs"]:
            self.assertIsNone(policy.core_app(a), a)
    def test_hotkeys(self):
        for k in [["win", "r"], ["winleft", "r"], ["win", "i"], ["win", "x"], ["ctrl", "shift", "esc"], ["ctrl", "alt", "delete"]]:
            self.assertTrue(policy.check({"action": "hotkey", "keys": k}), k)
        for k in [["ctrl", "s"], ["ctrl", "c"], ["win", "d"], ["alt", "tab"], ["enter"]]:
            self.assertIsNone(policy.check({"action": "hotkey", "keys": k}), k)
    def test_typed_launch_commands(self):
        for t in ["regedit", "control", "control panel", "ms-settings:display", "cmd", "powershell", "taskmgr", "services.msc", "gpedit.msc", "start regedit"]:
            self.assertTrue(policy.check({"action": "type", "text": t}), t)
        for t in ["hello world", "how to change settings in the game", "the control group"]:
            self.assertIsNone(policy.check({"action": "type", "text": t}), t)
    def test_settings_urls(self):
        self.assertTrue(policy.check({"action": "open_url", "url": "ms-settings:privacy"}))
        self.assertIsNone(policy.check({"action": "open_url", "url": "https://example.com/settings"}))
    def test_risky_in_app(self):
        self.assertTrue(policy.risky({"action": "click_element", "id": 3}, "Delete"))
        self.assertTrue(policy.risky({"action": "click_element", "id": 3}, "Send"))
        self.assertTrue(policy.risky({"action": "click", "x": 1, "y": 1, "target": "Install now"}))
        self.assertTrue(policy.risky({"action": "click_element", "id": 4}, "Don't Save"))
        self.assertTrue(policy.risky({"action": "hotkey", "keys": ["alt", "f4"]}))
        self.assertFalse(policy.risky({"action": "click_element", "id": 4}, "Bold"))
        self.assertFalse(policy.risky({"action": "type", "text": "hello"}))

class Routing(unittest.TestCase):
    def test_desktop_app_intents(self):
        for t, app in [("open spotify", "spotify"), ("open notepad and type hello world", "notepad"), ("launch photoshop", "photoshop"),
                       ("open vlc and play my movie", "vlc"), ("can you open discord", "discord"), ("start the calculator app", "calculator"),
                       ("open control panel", "control panel"), ("open regedit", "regedit"), ("open paint and draw a circle", "paint")]:
            p = planner.plan(None, t, use_model=False)
            self.assertEqual(p["intent"], "desktop_app", t); self.assertEqual(p["app"].lower(), app, t)
    def test_model_wrong_desktop_corrected(self):
        p = planner.plan(mock.Mock(text_chat=mock.Mock(return_value='{"intent":"web_interact","query":"","outputs":[]}')), "open vlc and play my movie")
        self.assertEqual(p["intent"], "desktop_app"); self.assertEqual(p["app"], "vlc")
    def test_web_stays_web(self):
        for t, i in [("open hulu", "open_site"), ("open youtube and play lofi", "media_play"), ("open chrome and go to reddit", None),
                     ("Open Excel and make a sheet of the top 20 richest people in the world", "web_research_to_files")]:
            p = planner.plan(None, t, use_model=False)
            if i: self.assertEqual(p["intent"], i, t)
            else: self.assertNotEqual(p["intent"], "desktop_app", t)

UIA_RAW = [
    {"role": "WindowControl", "name": "Untitled - Notepad", "rect": [0, 0, 800, 600]},
    {"role": "MenuItemControl", "name": "File", "rect": [10, 30, 50, 50]},
    {"role": "MenuItemControl", "name": "Edit", "rect": [55, 30, 95, 50]},
    {"role": "DocumentControl", "name": "Text editor", "value": "", "rect": [0, 60, 800, 580]},
    {"role": "ButtonControl", "name": "Close", "rect": [760, 0, 800, 25]},
    {"role": "ButtonControl", "name": "Hidden", "rect": [0, 0, 10, 10], "offscreen": True},
    {"role": "ButtonControl", "name": "Disabled", "rect": [0, 0, 30, 30], "enabled": False},
    {"role": "TextControl", "name": "Ln 1, Col 1", "rect": [0, 580, 100, 600]},
    {"role": "ButtonControl", "name": "", "rect": [1, 1, 20, 20]},
    {"role": "EditControl", "name": "", "value": "abc", "rect": [100, 100, 300, 120]},
]
AX_RAW = [{"role": "AXButton", "name": "Play", "rect": [100, 100, 130, 130]}, {"role": "AXTextField", "name": "Search", "value": "", "rect": {"x": 10, "y": 10, "w": 200, "h": 22}},
          {"role": "AXMenuItem", "name": "Quit Spotify", "rect": [0, 0, 100, 20]}, {"role": "AXStaticText", "name": "Now playing", "rect": [0, 0, 50, 50]}]

class AppSnapshot(unittest.TestCase):
    def test_parse_uia(self):
        els = appui.parse_elements(UIA_RAW)
        self.assertEqual([e["text"] for e in els], ["File", "Edit", "Text editor", "Close", "(edit)"])
        self.assertEqual([e["id"] for e in els], [1, 2, 3, 4, 5])
        self.assertEqual((els[0]["x"], els[0]["y"]), (30, 40)); self.assertTrue(els[2]["typable"]); self.assertEqual(els[4]["value"], "abc")
    def test_parse_ax(self):
        els = appui.parse_elements(AX_RAW)
        self.assertEqual([(e["tag"], e["text"]) for e in els], [("button", "Play"), ("textfield", "Search"), ("menuitem", "Quit Spotify")])
        self.assertEqual((els[1]["x"], els[1]["y"]), (110, 21))
    def test_limit_and_format(self):
        raw = [{"role": "ButtonControl", "name": f"B{i}", "rect": [i * 10, 0, i * 10 + 8, 8]} for i in range(200)]
        self.assertEqual(len(appui.parse_elements(raw, limit=60)), 60)
        ui = appui.AppUI(gui=mock.Mock(), raw_fn=lambda: ("notepad.exe", "Untitled - Notepad", UIA_RAW))
        snap = ui.snapshot(); txt = appui.format_elements(snap)
        self.assertIn("APP: notepad.exe", txt); self.assertIn('[3] document "Text editor"', txt)
    def test_click_and_type(self):
        g = mock.Mock(); ui = appui.AppUI(gui=g, raw_fn=lambda: ("notepad.exe", "Untitled - Notepad", UIA_RAW)); ui.snapshot()
        ui.type_into(3, "hello world")
        g.click.assert_called_with(400, 320); g.write.assert_called_with("hello world", interval=0.02)
        with self.assertRaises(RuntimeError): ui.click(99)
    def test_core_window_hidden(self):
        ui = appui.AppUI(gui=mock.Mock(), raw_fn=lambda: ("regedit.exe", "Registry Editor", UIA_RAW))
        snap = ui.snapshot(); self.assertEqual(snap["elements"], []); self.assertTrue(snap["blocked"])

class AgentDesktopApp(unittest.TestCase):
    def agent(self, ex):
        from PIL import Image
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 2, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False,
                                                                 "chrome_extension": False, "app_start_wait_s": 0, "app_ui": False}, "safety": {}}
        client = mock.MagicMock(); client.chat.return_value = '{"action":"done","summary":"ok"}'
        client.text_chat.return_value = '{"action":"done","summary":"ok"}'
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (800, 600)),
                       executor=lambda scale: ex, confirm=lambda m: False)
        return a, client
    def test_blocked_core_apps_never_launch(self):
        for t in ["open control panel", "open settings", "open regedit", "open the settings app and turn on dark mode", "launch task manager", "open powershell"]:
            ex = mock.Mock(); a, client = self.agent(ex)
            r = a.run(t)
            self.assertIn("Blocked", r, t); ex.execute.assert_not_called(); client.chat.assert_not_called()
    def test_plain_open_launches_and_stops(self):
        ex = mock.Mock(last_info="launched Spotify"); a, client = self.agent(ex)
        r = a.run("open spotify")
        ex.execute.assert_called_once_with({"action": "open_app", "app": "Spotify"}); self.assertIn("Opened", r); client.chat.assert_not_called()

if __name__ == "__main__": unittest.main()


class V141(unittest.TestCase):
    def test_uia_ctrl_used_not_coords(self):
        ctrl = mock.Mock(); g = mock.Mock()
        raw = [dict(UIA_RAW[3], ctrl=ctrl), dict(UIA_RAW[4], ctrl=mock.Mock())]
        ui = appui.AppUI(gui=g, raw_fn=lambda: ("Notepad.exe", "Untitled - Notepad", raw)); ui.snapshot()
        self.assertEqual(ui.first_typable()["text"], "Text editor")
        ui.type_into(1, "hello world")
        ctrl.SetFocus.assert_called_once(); g.click.assert_not_called(); g.write.assert_called_with("hello world", interval=0.02)
        ui.click(2); raw[1]["ctrl"].GetInvokePattern.return_value.Invoke.assert_called_once()
    def test_open_and_type_fast_path(self):
        from PIL import Image
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 2, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False,
                                                                 "chrome_extension": False, "app_start_wait_s": 0}, "safety": {}}
        client = mock.MagicMock(); g = mock.Mock(); ex = mock.Mock(last_info="launched Notepad")
        state = {"v": ""}
        def raw_fn():
            return ("Notepad.exe", "Untitled - Notepad", [dict(UIA_RAW[3], value=state["v"], ctrl=mock.Mock())])
        g.write.side_effect = lambda t, interval=0: state.update(v=t)
        a = core.Agent(cfg, log=lambda m: None, gui=g, client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex)
        with mock.patch("appui.focus_window", return_value=True), mock.patch("appui.AppUI.__init__", lambda self, **k: (setattr(self, "gui", g), setattr(self, "raw_fn", raw_fn), setattr(self, "limit", 60), setattr(self, "last", {"elements": []}))[0]):
            r = a.run("open notepad and type hello world")
        self.assertIn('typed "hello world"', r); client.chat.assert_not_called(); client.text_chat.assert_not_called()

class V141NoClobber(unittest.TestCase):
    def test_refuses_existing_text(self):
        raw = [dict(UIA_RAW[3], value="Dear Professor...", ctrl=mock.Mock())]
        ui = appui.AppUI(gui=mock.Mock(), raw_fn=lambda: ("Notepad.exe", "Letter - Notepad", raw)); ui.snapshot()
        with self.assertRaises(RuntimeError): ui.type_into(1, "hello world")
        raw[0]["ctrl"].SetFocus.assert_not_called()
