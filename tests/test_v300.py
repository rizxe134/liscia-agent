import json, os, tempfile, time, unittest
from unittest import mock
import bots, chats, toolhub, connections, mcphub, keystore, robot

class FakeKR:
    def __init__(self): self.d = {}
    def get_password(self, s, k): return self.d.get((s, k))
    def set_password(self, s, k, v): self.d[(s, k)] = v
    def delete_password(self, s, k): self.d.pop((s, k), None)

class Migration(unittest.TestCase):
    def test_old_chat_becomes_bot_and_backup(self):
        d = tempfile.mkdtemp(); cd = os.path.join(d, "chats"); os.makedirs(cd)
        old = {"id": "20261024-234027-698135", "title": "Search and tell me the news", "created": 1, "updated": 2,
               "messages": [{"role": "user", "content": "hi", "t": 1}, {"role": "assistant", "content": "yo", "t": 2}], "runs": []}
        json.dump(old, open(os.path.join(cd, old["id"] + ".json"), "w"))
        s = chats.ChatStore(cd); n = s.migrate_bots()
        self.assertEqual(n, 1)
        c = s.get(old["id"]); self.assertEqual(c["bot"]["name"], "Search and tell me the news"); self.assertEqual(len(c["messages"]), 2)
        self.assertEqual(c["bot"]["connections"], ["*"])
        bk = os.listdir(os.path.join(d, "backups")); self.assertEqual(len(bk), 1)
        self.assertTrue(os.path.exists(os.path.join(d, "backups", bk[0], old["id"] + ".json")))
        self.assertEqual(s.migrate_bots(), 0)  # once
        self.assertEqual(len(os.listdir(os.path.join(d, "backups"))), 1)

    def test_trash_restore_and_expiry(self):
        cd = tempfile.mkdtemp(); now = [1000.0]; s = chats.ChatStore(cd, clock=lambda: now[0])
        c = s.new(bot=bots.default_bot("Music", "Music")); s.add(c["id"], "user", "play x")
        s.delete(c["id"]); self.assertIsNone(s.get(c["id"])); self.assertEqual([t["name"] for t in s.trash()], ["Music"])
        s.restore(c["id"]); self.assertEqual(s.get(c["id"])["messages"][0]["content"], "play x")
        s.delete(c["id"]); now[0] += 31 * 86400; self.assertEqual(s.trash(), [])

    def test_bot_fields(self):
        s = chats.ChatStore(tempfile.mkdtemp())
        c = s.new(bot=dict(bots.default_bot("Cal", "Calendar"), memory=[]))
        self.assertEqual(c["title"], "Cal"); s.add(c["id"], "user", "what's on tomorrow"); self.assertEqual(s.get(c["id"])["title"], "Cal")
        s.remember(c["id"], "my dentist is Dr. Rao"); s.update_bot(c["id"], name="Calendar bot", provider="gemini", model="gemini-3.5-flash")
        b = s.get(c["id"])["bot"]; self.assertIn("Dr. Rao", bots.persona(b)); self.assertEqual(s.get(c["id"])["title"], "Calendar bot")
        cfg = {"provider": {"name": "ollama", "gemini": {"text_model": "x"}}, "ollama": {}}
        self.assertEqual(bots.bot_cfg(cfg, b)["provider"]["gemini"]["text_model"], "gemini-3.5-flash")
        self.assertEqual(cfg["provider"]["name"], "ollama")  # global untouched
        self.assertIsNone(bots.allowed({"mcp": ["*"]}, "mcp")); self.assertEqual(bots.allowed({"mcp": ["a"]}, "mcp"), ["a"])

class Tools(unittest.TestCase):
    def setUp(self): keystore._backend = FakeKR(); keystore.clear_cache()
    def tearDown(self): keystore._backend = None; keystore.clear_cache()

    def tool(self, write):
        calls = []
        return {"name": "calendar_create_event", "description": "d", "write": write, "source": "google",
                "schema": {"type": "object", "properties": {"title": {"type": "string"}, "start": {"type": "string"}}, "required": ["title", "start"]},
                "run": lambda a: calls.append(a) or "created"}, calls

    def test_write_needs_approval(self):
        t, calls = self.tool(True)
        ok, res = toolhub.run(t, {"title": "x", "start": "2026-10-26T15:00"}, confirm=lambda m: False, log=lambda m: 0)
        self.assertFalse(ok); self.assertIn("Cancelled", res); self.assertEqual(calls, [])
        ok, res = toolhub.run(t, {"title": "x", "start": "2026-10-26T15:00"}, confirm=lambda m: True, log=lambda m: 0)
        self.assertTrue(ok); self.assertEqual(len(calls), 1)

    def test_schema_validation(self):
        t, calls = self.tool(False)
        ok, res = toolhub.run(t, {"title": 5}, confirm=lambda m: True, log=lambda m: 0)
        self.assertFalse(ok); self.assertEqual(calls, [])

    def test_pick_and_gate(self):
        t, _ = self.tool(True)
        cl = mock.Mock(); cl.text_chat.return_value = '{"tool": "calendar_create_event", "args": {"title": "Meeting", "start": "2026-10-26T15:00"}}'
        self.assertTrue(toolhub.relevant("add a meeting tomorrow at 3 to my calendar", [t]))
        self.assertFalse(toolhub.relevant("play a hindi song on youtube", [t]))
        tool, args = toolhub.pick(cl, "add a meeting tomorrow at 3", [t]); self.assertEqual(args["title"], "Meeting")
        cl.text_chat.return_value = '{"tool": "made_up"}'; self.assertIsNone(toolhub.pick(cl, "x", [t]))

    def test_connections_tools_only_when_connected(self):
        cfg = {}
        self.assertEqual(connections.tools_for(cfg), [])
        cfg["connections"] = {"google": {"connected": True}}
        names = [t["name"] for t in connections.tools_for(cfg)]
        self.assertIn("calendar_create_event", names); self.assertIn("gmail_draft", names)
        self.assertTrue(all(t["write"] for t in connections.tools_for(cfg) if t["name"] in ("gmail_draft", "calendar_create_event", "calendar_delete_event")))
        self.assertEqual(connections.tools_for(cfg, ["github"]), [])

    def test_pkce_and_auth_url(self):
        v, ch = connections.pkce_pair(); import hashlib, base64
        self.assertEqual(ch, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode())
        connections.save_client("google", "abc.apps.googleusercontent.com", "s3cret")
        u = connections.auth_url("google", "http://127.0.0.1:5000/", ch, "st")
        self.assertIn("code_challenge_method=S256", u); self.assertIn("client_id=abc.apps", u); self.assertNotIn("s3cret", u)
        self.assertIn("calendar.events", u)

    def test_exchange_and_refresh_keychain_only(self):
        connections.save_client("google", "cid", "sec")
        post = mock.Mock(); post.return_value.json.return_value = {"access_token": "ya29.AAA", "refresh_token": "r1", "expires_in": 3600}
        tok = connections.exchange("google", "code", "http://127.0.0.1:1/", "ver", post=post)
        self.assertEqual(post.call_args[1]["data"]["code_verifier"], "ver"); connections.save_tokens("google", tok)
        self.assertEqual(connections.access_token("google"), "ya29.AAA")
        t = connections.tokens("google"); t["expires_at"] = 0; connections.save_tokens("google", t)
        post.return_value.json.return_value = {"access_token": "ya29.BBB", "expires_in": 3600}
        self.assertEqual(connections.access_token("google", post=post), "ya29.BBB")
        self.assertTrue(all(k[1].startswith("conn:") for k in keystore._backend.d))

    def test_oauth_loopback_roundtrip(self):
        import urllib.request, urllib.parse
        connections.save_client("google", "cid", "sec"); cfg = {}; done = []
        opened = []
        with mock.patch.object(connections, "exchange", return_value={"access_token": "ya29.X", "expires_at": time.time() + 999}), \
             mock.patch.object(connections, "account_name", return_value="me@example.com"), mock.patch("settings.save"):
            url = connections.start_oauth(cfg, "google", open_browser=opened.append, timeout=20, done=lambda ok, m: done.append((ok, m)))
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            urllib.request.urlopen(q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "c", "state": q["state"]}), timeout=10).read()
            for _ in range(50):
                if done: break
                time.sleep(0.1)
        self.assertEqual(done[0][0], True); self.assertTrue(cfg["connections"]["google"]["connected"])
        self.assertEqual(opened, [url])

class Mcp(unittest.TestCase):
    def test_demo_server_tools_and_call(self):
        cfg = {"mcp": {"servers": [mcphub.demo_server()]}}
        with mock.patch.object(mcphub, "log_path", return_value=os.path.join(tempfile.mkdtemp(), "l.log")):
            tools = mcphub.list_tools(cfg, "liscia-demo")
            self.assertIn("list_folder", [t["name"] for t in tools]); self.assertTrue(all(t["read_only"] for t in tools))
            self.assertEqual(float(mcphub.call_tool(cfg, "liscia-demo", "add", {"a": 2, "b": 3})), 5.0)
            bt = toolhub.bot_tools(cfg, {"mcp": ["*"], "connections": []})
            t = next(x for x in bt if x["name"] == "liscia-demo__add"); self.assertFalse(t["write"])
            self.assertEqual(toolhub.bot_tools(cfg, {"mcp": [], "connections": []}), [])

    def test_missing_npx_is_friendly(self):
        cfg = {"mcp": {"servers": [{"name": "fs", "transport": "stdio", "command": "npx-not-here", "args": []}]}}
        with mock.patch.object(mcphub, "log_path", return_value=os.path.join(tempfile.mkdtemp(), "l.log")):
            with self.assertRaises(FileNotFoundError): mcphub.list_tools(cfg, "fs")
        self.assertIn("Node.js", mcphub.missing_hint("npx"))

    def test_unknown_tool_needs_confirm_unless_always_allow(self):
        cfg = {"mcp": {"servers": [{"name": "s", "enabled": True, "cached": [{"name": "write_file", "description": "", "schema": {"type": "object"}, "read_only": False}],
                                    "tools": {"write_file": {"enabled": True, "always_allow": False}}}]}}
        self.assertTrue(toolhub.bot_tools(cfg, None)[0]["write"])
        cfg["mcp"]["servers"][0]["tools"]["write_file"]["always_allow"] = True
        self.assertFalse(toolhub.bot_tools(cfg, None)[0]["write"])
        cfg["mcp"]["servers"][0]["tools"]["write_file"]["enabled"] = False
        self.assertEqual(toolhub.bot_tools(cfg, None), [])

    def test_redact(self):
        self.assertNotIn("abcdef123456", mcphub.redact("Authorization: Bearer abcdef123456"))
        self.assertNotIn("ghp_", mcphub.redact("token ghp_" + "a" * 30))

class Robot(unittest.TestCase):
    def test_frames(self):
        f = robot.frame("classic"); self.assertEqual(len(f), 9); self.assertTrue(all(len(r) == 9 for r in f))
        self.assertNotIn("E", "".join(robot.frame("classic", blink=True)))
        self.assertIn("O", "".join(robot.frame("visor", talk=2)))
        self.assertEqual(robot.px_for(10), 2); self.assertEqual(robot.px_for(22), 4)

@unittest.skipUnless(os.environ.get("DISPLAY"), "needs a display")
class UiBots(unittest.TestCase):
    def test_sidebar_avatars_card(self):
        import tkinter as tk, ui, threading
        cfg = {"ollama": {"host": "x", "model": "m"}, "setup_check": False, "panel": {"enabled": False}}
        r = tk.Tk(); r.withdraw()
        st = chats.ChatStore(tempfile.mkdtemp())
        with mock.patch.object(ui.ChatApp, "_preload", lambda self: None):
            app = ui.ChatApp(cfg, root=r, store=st)
        c = st.new(bot=bots.default_bot("Music", "Music")); app.refresh_chats(); app.show_chat(c)
        self.assertEqual(len(app.bot_list.icons), 2)
        app.write("user", "hi"); app.write("agent", "hello")
        self.assertIn("Music > hello", app.log.get("1.0", "end")); self.assertIn("you > hi", app.log.get("1.0", "end"))
        self.assertTrue(any(isinstance(r.nametowidget(w), robot.RobotIcon) for w in app.log.window_names()))
        box = {}; ev = threading.Event(); app._show_card("create event", ev, box)
        r.update(); self.assertFalse(ev.is_set())
        app.typing_start(); r.update(); self.assertIn("is thinking", app.log.get("1.0", "end"))
        app.write("step", "[x] y"); app.write("agent", "done"); self.assertNotIn("is thinking", app.log.get("1.0", "end"))
        self.assertIn("[x] y", app.log.get("1.0", "end"))
        app.write("agent", ({"name": "Calendar", "color": "amber"}, "from cal")); self.assertIn("Calendar > from cal", app.log.get("1.0", "end"))
        other = st.new(bot=bots.default_bot("Cal", "Calendar"), select=False); app.refresh_chats()
        app.bot_list.mark_unread(other["id"]); self.assertIn(other["id"], app.bot_list.unread)
        import botui; pp = botui.ProfilePane(app, c["id"]); r.update(); pp.win.destroy()
        app.apply_theme("light", 20); app.apply_theme("terminal", 13)
        with mock.patch("settings.save"):
            sw = ui.SettingsWindow(app); r.update(); sw.mcp.add_demo(); self.assertEqual(cfg["mcp"]["servers"][0]["name"], "liscia-demo"); sw.win.destroy()
        r.destroy()

class Mentions(unittest.TestCase):
    def test_mentions(self):
        items = [{"id": "a", "bot": {"name": "Music"}}, {"id": "b", "bot": {"name": "Calendar bot"}}, {"id": "c", "bot": {"name": "General"}}]
        self.assertEqual([x[0] for x in bots.mentions("@music what should I play?", items, exclude="c")], ["a"])
        self.assertEqual([x[0] for x in bots.mentions("ask @Calendar bot about friday", items)], ["b"])
        self.assertEqual(bots.mentions("email me@music.com", items), [])
        self.assertEqual(bots.mentions("@General hi", items, exclude="c"), [])
        self.assertEqual(bots.strip_mentions("@Music play", ["Music"]), "Music play")

    def test_robot_states(self):
        self.assertNotEqual(robot.frame("classic", look=1), robot.frame("classic"))

class BridgeTools(unittest.TestCase):
    def test_panel_chat_uses_bot_mcp_tool(self):
        import server
        cfg = {"mcp": {"servers": [dict(mcphub.demo_server(), cached=[{"name": "add", "description": "Add two numbers.", "schema": {"type": "object",
               "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}, "read_only": True}])]}}
        st = chats.ChatStore(tempfile.mkdtemp()); c = st.new(bot=bots.default_bot("Math"))
        b = server.Bridge.__new__(server.Bridge); b.cfg = cfg; b._store = st; b.router = lambda *a, **k: ("chat", "router")
        b.hub = mock.Mock(); b.busy = True
        ag = mock.Mock(); ag.client.text_chat.side_effect = ['{"tool": "liscia-demo__add", "args": {"a": 2, "b": 3}}', "2 + 3 = 5"]
        b._get_agent = lambda: ag
        with mock.patch.object(mcphub, "log_path", return_value=os.path.join(tempfile.mkdtemp(), "l.log")):
            b._chat("use the mcp add tool for 2 and 3", c["id"])
        self.assertEqual(st.get(c["id"])["messages"][-1]["content"], "2 + 3 = 5")
