import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import appfirst, commands, planner, winbind

def E(name, target="", kind="lnk"): return {"name": name, "key": __import__("appindex").norm(name), "path": "", "target": target, "kind": kind}
IDX = [E("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "aumid"), E("VLC media player", r"C:\Program Files\VideoLAN\VLC\vlc.exe"),
       E("Discord", r"C:\Users\x\AppData\Local\Discord\Update.exe"), E("Steam", r"C:\Program Files (x86)\Steam\steam.exe"),
       E("Visual Studio Code", r"C:\x\Code.exe"), E("Notepad", "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "aumid"),
       E("Microsoft Word", r"C:\x\WINWORD.EXE"), E("Google Chrome", r"C:\x\chrome.exe"), E("Media Player", "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "aumid"),
       E("Music", "/System/Applications/Music.app", "app")]

class AppFirst(unittest.TestCase):
    def ov(self, task, intent="web_interact", running=()):
        return appfirst.override({"intent": intent, "query": "", "site": "", "outputs": []}, task, idx=IDX, running=set(running),
                                 is_command=bool(commands.parse(task, "x")))[0]
    def test_named_apps_override_web(self):
        cases = {"can you pause the musiuc on spotify": "Spotify", "pause spotfy": "Spotify", "go to my friends list in discord": "Discord",
                 "check my library in steam": "Steam", "open a new file in vs code": "Visual Studio Code", "write a note in notepad": "Notepad",
                 "make the text bold in word": "Microsoft Word", "next song on spotify": "Spotify", "skip the track in vlc": "VLC media player",
                 "play the next video in vlc": "VLC media player", "search for lofi on sptify": "Spotify", "open discrod": "Discord"}
        for t, app in cases.items():
            for it in ("web_interact", "open_site", "media_play"):
                with self.subTest(t=t, it=it):
                    p = self.ov(t, it); self.assertEqual((p["intent"], p.get("app")), ("desktop_app", app))
    def test_explicit_web_exception(self):
        for t in ("open spotify website", "open spotify.com", "play lofi on spotify in the browser", "open the discord web app", "steam online store"):
            with self.subTest(t=t): self.assertEqual(self.ov(t)["intent"], "web_interact")
    def test_questions_and_browsers_stay_web(self):
        self.assertEqual(self.ov("who founded spotify", "web_answer")["intent"], "web_answer")
        self.assertEqual(self.ov("search cats in chrome")["intent"], "web_interact")
        self.assertEqual(self.ov("pause the video in chrome")["app"], "Google Chrome")  # media command on a browser -> its session
    def test_running_only_app(self):
        p = appfirst.override({"intent": "web_interact"}, "pause the song on tidal", idx=IDX, running={"tidal"}, is_command=True)[0]
        self.assertEqual(p["intent"], "desktop_app"); self.assertEqual(p["app"].lower(), "tidal")
    def test_research_untouched(self):
        p = {"intent": "web_research_to_files", "outputs": ["xlsx"]}
        self.assertIs(appfirst.override(p, "top 10 spotify songs in excel", idx=IDX, running=set())[0], p)

class Parse(unittest.TestCase):
    def test_media(self):
        for t, v in {"can you pause the musiuc on spotify": "pause", "resume spotify": "play", "next song on spotify": "next", "skip this song": "next",
                     "previous track in vlc": "previous", "turn the volume up on spotify": "volume_up", "volume down": "volume_down",
                     "mute spotify": "mute", "pause the video in chrome": "pause", "pause the music app": "pause", "resume itunes": "play",
                     "pause apple music": "pause", "unpause vlc": "play"}.items():
            with self.subTest(t=t): self.assertEqual(commands.parse(t, "x"), {"kind": "media", "verb": v})
    def test_not_commands(self):
        for t in ("play gettin money on spotify", "open discord and find the music channel", "open spotify", "who sang pause"):
            with self.subTest(t=t): self.assertNotEqual((commands.parse(t, "x") or {}).get("kind"), "media" if "who" not in t else "x")
    def test_window_and_actions(self):
        self.assertEqual(commands.parse("minimize notepad", "Notepad"), {"kind": "window", "verb": "minimize"})
        self.assertEqual(commands.parse("close vlc", "VLC"), {"kind": "window", "verb": "close"})
        self.assertEqual(commands.parse("close the tab in chrome", "Chrome"), {"kind": "action", "verb": "close_tab"})
        self.assertEqual(commands.parse("save the document in word", "Word"), {"kind": "action", "verb": "save"})
        self.assertEqual(commands.parse("undo in notepad", "Notepad"), {"kind": "action", "verb": "undo"})

class SMTC(unittest.TestCase):
    def fake(self, status_after, app="SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", sent=None):
        calls = []
        def run(argv):
            calls.append(argv); act, match = argv[argv.index("-Action") + 1], argv[argv.index("-Match") + 1]
            sess = [{"app": app, "status": status_after, "title": "true story", "artist": "ptasinski"}]
            if act == "list": return json.dumps({"ok": True, "action": "list", "sessions": sess})
            hit = match.lower() in app.lower()
            return json.dumps({"ok": hit, "action": act, "sessions": sess, "sent": hit, "after": sess[0] if hit else None})
        return run, calls
    def test_pause_resume_next_by_app(self):
        for app, sid in (("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"), ("VLC media player", "vlc.exe"), ("Google Chrome", "chrome.exe"),
                         ("music app", "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"), ("Media Player", "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic")):
            for verb, st in (("pause", "Paused"), ("play", "Playing"), ("next", "Playing")):
                with self.subTest(app=app, verb=verb):
                    run, calls = self.fake(st, sid)
                    with mock.patch.object(commands, "IS_MAC", False):
                        r = commands.run_media(verb, "music app" if app == "music app" else app, run=run, sleep=lambda s: None)
                    self.assertIn(st, r); self.assertNotIn("stopped", r)
    def test_unverified_is_reported(self):
        run, _ = self.fake("Playing")
        with mock.patch.object(commands, "IS_MAC", False):
            self.assertIn("stopped", commands.run_media("pause", "Spotify", run=run, sleep=lambda s: None))
    def test_no_session_for_app(self):
        run, _ = self.fake("Playing", "chrome.exe")
        with mock.patch.object(commands, "IS_MAC", False):
            self.assertIn("no active media session", commands.run_media("pause", "Spotify", run=run, sleep=lambda s: None))
    def test_volume_uses_keys(self):
        with mock.patch.object(commands, "media_key", return_value=True) as k:
            commands.run_media("volume_up", "Spotify", run=lambda a: "")
        k.assert_called_with("volume_up", presses=5)

class MacMedia(unittest.TestCase):
    def test_spotify_music_itunes_applescript(self):
        for app, name in (("Spotify", "Spotify"), ("itunes", "Music"), ("apple music", "Music"), ("Music", "Music")):
            for verb, cmd, st in (("pause", "pause", "paused"), ("play", "play", "playing"), ("next", "next track", "playing")):
                with self.subTest(app=app, verb=verb):
                    sent = []
                    def run(argv): sent.append(argv[-1]); return st if "player state" in argv[-1] else ""
                    with mock.patch.object(commands, "IS_MAC", True):
                        r = commands.run_media(verb, app, mac_run=run)
                    self.assertEqual(sent[0], f'tell application "{name}" to {cmd}'); self.assertIn(st, r)

class AgentFlow(unittest.TestCase):
    def agent(self):
        from PIL import Image
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False,
                                                                 "chrome_extension": False, "app_start_wait_s": 0, "app_ui": False}, "safety": {}}
        client = mock.MagicMock(); ex = mock.Mock(last_info="")
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (800, 600)), executor=lambda s: ex)
        a.app_index, a.running_apps = IDX, {"spotify"}
        return a, client, ex
    def test_pause_spotify_no_model_no_browser(self):
        a, client, ex = self.agent(); got = []
        a.media_runner = lambda verb, app: got.append((verb, app)) or "Pause: Spotify is Paused."
        r = a.run("can you pause the musiuc on spotify")
        self.assertEqual(got, [("pause", "Spotify")]); self.assertIn("Paused", r)
        client.chat.assert_not_called(); ex.execute.assert_not_called()
    def test_resume_next(self):
        for t, v in (("resume spotify", "play"), ("next song on spotify", "next"), ("pause the song", "pause")):
            a, client, ex = self.agent(); got = []
            a.media_runner = lambda verb, app: got.append(verb) or "ok"
            a.run(t); self.assertEqual(got, [v], t); ex.execute.assert_not_called()
    def test_binds_running_app_without_relaunch(self):
        a, client, ex = self.agent()
        client.chat.return_value = '{"action":"done","result":"ok"}'
        b = mock.Mock(app="Notepad"); b.bind.return_value = {"hwnd": 5, "title": "Untitled - Notepad", "proc": "Notepad.exe", "pid": 3}
        b.ensure.return_value = True; b.window_rect.return_value = [0, 0, 800, 600]
        a.binding_factory = lambda app: b
        r = a.run("open notepad")
        self.assertIn("already open", r); ex.execute.assert_not_called()
    def test_minimize_bound_window(self):
        a, client, ex = self.agent()
        b = mock.Mock(app="Notepad", hwnd=5); b.bind.return_value = {"hwnd": 5, "title": "x", "proc": "Notepad.exe", "pid": 3}
        b.info = b.bind.return_value; a.binding_factory = lambda app: b
        with mock.patch.object(commands, "run_window", return_value="Minimized Notepad.") as rw:
            r = a.run("minimize notepad")
        self.assertEqual(r, "Minimized Notepad."); self.assertEqual(rw.call_args.args[0], "minimize"); ex.execute.assert_not_called()

class HintsTable(unittest.TestCase):
    def test_table_and_user_override(self):
        import adapters, tempfile
        self.assertIn("Ctrl+k (search)", adapters.hint("Spotify"))
        d = tempfile.mkdtemp(); json.dump({"myapp": {"go": "ctrl+g"}}, open(os.path.join(d, "app_hints.json"), "w"))
        with mock.patch("paths.data_dir", return_value=d):
            self.assertIn("Ctrl+g (go)", adapters.hint("MyApp"))
