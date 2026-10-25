import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import chats, keystore, providers, settings, yaml
from PIL import Image

class FakeKR(dict):
    def get_password(s, a, b): return dict.get(s, (a, b))
    def set_password(s, a, b, c): s[(a, b)] = c
    def delete_password(s, a, b): s.pop((a, b), None)

class ChatStoreCRUD(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.t = [1000.0]
        self.s = chats.ChatStore(self.d, clock=lambda: self.t[0])
    def tick(self): self.t[0] += 1
    def test_crud_titles_history_and_runs(self):
        a = self.s.new(); self.tick()
        self.s.add(a["id"], "user", "can you open notepad and type hello world for me please"); self.tick()
        self.s.add(a["id"], "assistant", "(did task) ok", run="20261023-190000")
        c = self.s.get(a["id"])
        self.assertTrue(c["title"].startswith("Open notepad and type hello")); self.assertLessEqual(len(c["title"]), 40)
        self.assertEqual(c["runs"], ["20261023-190000"]); self.assertEqual(c["messages"][1]["run"], "20261023-190000")
        self.tick(); b = self.s.new(); self.s.add(b["id"], "user", "hi")
        self.assertEqual([x["id"] for x in self.s.list()], [b["id"], a["id"]])
        self.assertEqual(self.s.history(a["id"])[0]["role"], "user"); self.assertEqual(len(self.s.history(b["id"])), 1)  # separate contexts
        self.s.rename(a["id"], "My notepad chat"); self.s.add(a["id"], "user", "second")
        self.assertEqual(self.s.get(a["id"])["title"], "My notepad chat")  # a manual rename sticks
        self.s.select(a["id"]); self.assertEqual(self.s.current()["id"], a["id"])
        self.s.delete(a["id"]); self.assertIsNone(self.s.get(a["id"])); self.assertEqual(self.s.current()["id"], b["id"])
    def test_persists_across_restart(self):
        a = self.s.new(); self.s.add(a["id"], "user", "remember me")
        s2 = chats.ChatStore(self.d)
        self.assertEqual(s2.current()["id"], a["id"]); self.assertEqual(s2.current()["messages"][0]["content"], "remember me")
    def test_bad_ids_rejected(self):
        with self.assertRaises(ValueError): self.s.get("../../etc/passwd") or self.s._path("../x")
    def test_migration(self):
        old = [{"role": "user", "content": "top 10 cars in excel"}, {"role": "assistant", "content": "done"}]
        json.dump(old, open(os.path.join(self.d, "history.json"), "w"))
        store = chats.ChatStore(os.path.join(self.d, "chats"))
        c = chats.migrate_legacy(store, self.d)
        self.assertEqual(c["title"], "Top 10 cars in excel"); self.assertEqual(len(c["messages"]), 2)
        self.assertFalse(os.path.exists(os.path.join(self.d, "history.json")))
        self.assertIsNone(store.migrate(old))  # only once
    def test_empty_store_gets_a_chat(self):
        self.assertEqual(len(self.s.list()), 0); c = self.s.current(); self.assertEqual(c["title"], "New chat")

class SettingsKeys(unittest.TestCase):
    def setUp(self):
        keystore._backend = FakeKR()
        self.cfg = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.yaml")))
    def tearDown(self): keystore._backend = None
    def test_save_load_and_keys_never_on_disk(self):
        key = "sk-test-SECRET-1234567890abcdef"
        settings.apply(self.cfg, {"provider": "openai", "text_model": "gpt-4.1-mini", "vision_model": "gpt-4.1", "keys": {"openai": key}})
        self.cfg["provider"]["openai"]["api_key"] = key  # even if something put it in cfg by mistake...
        p = os.path.join(tempfile.mkdtemp(), "config.yaml")
        settings.save(self.cfg, p)
        text = open(p).read()
        self.assertNotIn(key, text); self.assertNotIn("api_key", text)
        back = yaml.safe_load(text)
        self.assertEqual(back["provider"]["name"], "openai"); self.assertEqual(back["provider"]["openai"]["vision_model"], "gpt-4.1")
        self.assertEqual(keystore.get("openai"), key)
        self.assertEqual(keystore.mask(key), "sk-…cdef")
    def test_refuses_key_in_any_field(self):
        keystore.set("gemini", "AIzaLEAKEDKEY123456")
        self.cfg["agent"]["note"] = "AIzaLEAKEDKEY123456"
        with self.assertRaises(RuntimeError): settings.save(self.cfg, os.path.join(tempfile.mkdtemp(), "c.yaml"))
    def test_ollama_role_models(self):
        settings.apply(self.cfg, {"provider": "ollama", "text_model": "llama3.2:3b", "vision_model": "qwen2.5vl:7b"})
        self.assertEqual((self.cfg["ollama"]["text_model"], self.cfg["ollama"]["model"]), ("llama3.2:3b", "qwen2.5vl:7b"))
    def test_bad_provider(self):
        with self.assertRaises(ValueError): settings.apply(self.cfg, {"provider": "evilcorp"})
    def test_takes_effect_without_restart(self):
        import core
        settings.apply(self.cfg, {"provider": "anthropic"})
        if True:
            a = core.Agent(self.cfg, log=lambda m: None, gui=mock.Mock(), capture=lambda: None)
        self.assertIsInstance(a.client.inner, providers.FallbackClient); self.assertEqual(a.client.primary.provider, "anthropic")
        self.assertFalse(core.uses_norm_coords(self.cfg))
        settings.apply(self.cfg, {"provider": "gemini"}); self.assertTrue(core.uses_norm_coords(self.cfg))
        settings.apply(self.cfg, {"provider": "ollama"}); self.assertTrue(core.uses_norm_coords(self.cfg))  # qwen3-vl

class Resp:
    def __init__(self, code, data): self.status_code, self._d, self.text = code, data, json.dumps(data)
    def json(self): return self._d

class ProviderFormat(unittest.TestCase):
    IMG = Image.new("RGB", (8, 8))
    def client(self, prov, reply):
        sent = []
        def post(url, json=None, headers=None, timeout=None): sent.append((url, json, headers)); return Resp(200, reply)
        return providers.CloudClient(prov, "tm", "vm", key="KEY", post=post, sleep=lambda s: None), sent
    def test_openai(self):
        c, sent = self.client("openai", {"choices": [{"message": {"content": "```json\n{\"action\":\"done\"}\n```"}}]})
        self.assertEqual(c.chat("SYS", "do it", self.IMG), '{"action":"done"}')
        url, body, h = sent[0]
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions"); self.assertEqual(h["Authorization"], "Bearer KEY")
        self.assertEqual(body["model"], "vm"); self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][0]["role"], "system")
        parts = body["messages"][1]["content"]; self.assertEqual(parts[1]["type"], "image_url")
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        c.text_chat([{"role": "user", "content": "hi"}]); self.assertEqual(sent[1][1]["model"], "tm"); self.assertNotIn("response_format", sent[1][1])
    def test_anthropic(self):
        c, sent = self.client("anthropic", {"content": [{"type": "text", "text": "{\"a\":1}"}]})
        self.assertEqual(c.chat("SYS", "go", self.IMG), '{"a":1}')
        url, body, h = sent[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages"); self.assertEqual(h["x-api-key"], "KEY"); self.assertIn("anthropic-version", h)
        self.assertIn("SYS", body["system"]); self.assertIn("JSON", body["system"]); self.assertIn("max_tokens", body)
        blk = body["messages"][0]["content"]; self.assertEqual(blk[0]["type"], "image"); self.assertEqual(blk[0]["source"]["media_type"], "image/png")
    def test_gemini(self):
        c, sent = self.client("gemini", {"candidates": [{"content": {"parts": [{"text": "{\"b\":2}"}]}}]})
        schema = {"type": "object", "properties": {"intent": {"type": "string"}}}
        self.assertEqual(c.text_chat([{"role": "system", "content": "S"}, {"role": "user", "content": "u"}, {"role": "assistant", "content": "a"},
                                      {"role": "user", "content": "u2"}], schema=schema), '{"b":2}')
        url, body, h = sent[0]
        self.assertEqual(url, "https://generativelanguage.googleapis.com/v1beta/models/tm:generateContent"); self.assertEqual(h["x-goog-api-key"], "KEY")
        self.assertEqual([x["role"] for x in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json"); self.assertIn("intent", body["systemInstruction"]["parts"][0]["text"])
        c.chat("S", "p", self.IMG); self.assertIn("inline_data", sent[1][1]["contents"][0]["parts"][1])
    def test_ollama_unchanged(self):
        import llm
        with mock.patch("requests.post") as p:
            p.return_value.status_code = 200; p.return_value.json.return_value = {"message": {"content": "{}"}}
            llm.OllamaClient("http://h:1", "qwen3-vl:4b").chat("S", "P", self.IMG)
        body = p.call_args.kwargs["json"]; self.assertEqual(body["format"], "json"); self.assertTrue(body["messages"][1]["images"])
    def test_errors_are_clear(self):
        for code, kind, words in ((401, "auth", "key was rejected"), (429, "quota", "quota"), (404, "model", "model not found"), (400, "bad_request", "rejected")):
            c = providers.CloudClient("openai", "t", "v", key="K", post=lambda *a, **k: Resp(code, {"error": {"message": "nope"}}), sleep=lambda s: None)
            with self.subTest(code=code):
                with self.assertRaises(providers.ProviderError) as cm: c.text_chat([{"role": "user", "content": "x"}])
                self.assertEqual(cm.exception.kind, kind); self.assertIn(words, str(cm.exception))
    def test_no_key_and_network(self):
        import requests
        c = providers.CloudClient("anthropic", "t", "v", key="")
        with self.assertRaises(providers.ProviderError) as cm: c.text_chat([{"role": "user", "content": "x"}])
        self.assertEqual(cm.exception.kind, "no_key"); self.assertIn("no API key set", str(cm.exception)); self.assertIn("Settings", str(cm.exception))
        calls = []
        def boom(*a, **k): calls.append(1); raise requests.exceptions.ConnectionError("x")
        c = providers.CloudClient("gemini", "t", "v", key="K", post=boom, retries=2, sleep=lambda s: None)
        with self.assertRaises(providers.ProviderError) as cm: c.text_chat([{"role": "user", "content": "x"}])
        self.assertEqual((cm.exception.kind, len(calls)), ("network", 3))
    def test_retry_then_success(self):
        rs = iter([Resp(503, {}), Resp(200, {"choices": [{"message": {"content": "ok"}}]})])
        c = providers.CloudClient("openai", "t", "v", key="K", post=lambda *a, **k: next(rs), sleep=lambda s: None)
        self.assertEqual(c.text_chat([{"role": "user", "content": "x"}]), "ok")
    def test_list_models(self):
        g = lambda url, headers=None, timeout=None: Resp(200, {"data": [{"id": "gpt-4.1"}, {"id": "whisper-1"}, {"id": "gpt-4o-mini-tts"}, {"id": "text-embedding-3"}]})
        m = providers.list_models("openai", "K", get=g); self.assertEqual(m["text"], ["gpt-4.1"])
        g = lambda url, headers=None, timeout=None: Resp(200, {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                                                                         {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})
        self.assertEqual(providers.list_models("gemini", "K", get=g)["vision"], ["gemini-2.5-flash"])
        ok, msg = providers.test_connection("openai", key=""); self.assertFalse(ok); self.assertIn("No API key", msg)

class Fallback(unittest.TestCase):
    def test_falls_back_to_local_when_cloud_fails(self):
        cloud = mock.Mock(); cloud.text_chat.side_effect = providers.ProviderError("openai", "quota", "rate limit")
        local = mock.Mock(model="qwen3-vl:4b-instruct", text_model="qwen2.5:7b"); local.check.return_value = ["qwen2.5:7b", "qwen3-vl:4b-instruct"]
        local.text_chat.return_value = "local answer"; logs = []
        fb = providers.FallbackClient(cloud, local, log=logs.append)
        self.assertEqual(fb.text_chat([{"role": "user", "content": "x"}], model="gpt-4.1"), "local answer")
        self.assertNotIn("model", local.text_chat.call_args.kwargs); self.assertTrue(any("local model" in l for l in logs))
    def test_no_local_model_reraises(self):
        cloud = mock.Mock(); cloud.chat.side_effect = providers.ProviderError("gemini", "auth", "bad key")
        local = mock.Mock(model="m", text_model="t"); local.check.return_value = None
        with self.assertRaises(providers.ProviderError): providers.FallbackClient(cloud, local).chat("s", "p", None)
    def test_make_client(self):
        cfg = {"ollama": {"host": "h", "model": "m"}, "provider": {"name": "openai", "fallback_local": False, "openai": {"text_model": "a", "vision_model": "b"}}}
        c = providers.make_client(cfg, key="K", local_factory=lambda c: mock.Mock())
        self.assertIsInstance(c, providers.CloudClient); self.assertEqual((c.text_model, c.model), ("a", "b"))
        cfg["provider"]["name"] = "ollama"; lf = mock.Mock(); self.assertIs(providers.make_client(cfg, local_factory=lambda c: lf), lf)

class BridgeChats(unittest.TestCase):
    def test_panel_messages_go_to_the_current_chat(self):
        import server
        st = chats.ChatStore(tempfile.mkdtemp()); a = st.new()
        router = mock.Mock(return_value=("chat", "hello back"))
        ag = mock.Mock(); br = server.Bridge({}, token="t" * 40, router=router, store=st, agent_factory=lambda b: ag)
        br.hub.emit = lambda *x, **k: None
        br._chat("hi there"); self.assertEqual([m["content"] for m in st.get(a["id"])["messages"]], ["hi there", "hello back"])
        b = st.new(); br._chat("second chat msg")
        self.assertEqual(router.call_args.args[2], [])  # the new chat has its own (empty) context
        self.assertEqual(len(st.get(b["id"])["messages"]), 2)
        info = br.chats_info(); self.assertEqual(info["current"]["id"], b["id"]); self.assertEqual(len(info["chats"]), 2)
        br._chat("/new"); self.assertEqual(len(st.list()), 3)

class SmallFixes(unittest.TestCase):
    def test_transient_ui_error(self):
        import core
        self.assertTrue(core.transient_ui_error(Exception(-2147220991, "An event was unable to invoke any of the subscribers", (None,))))
        self.assertFalse(core.transient_ui_error(ValueError("bad row")))
    def test_media_command_skips_planner_model(self):
        sys.path.insert(0, os.path.dirname(__file__)); from test_v144 import IDX
        import core
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0,
                                                                 "chrome_extension": False, "app_start_wait_s": 0, "app_ui": False}, "safety": {}}
        client = mock.MagicMock()
        a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: None, executor=lambda s: mock.Mock())
        a.app_index, a.running_apps = IDX, {"spotify"}; a.media_runner = lambda v, app: f"{v} {app}"
        self.assertEqual(a.run("pause spotify"), "pause Spotify"); client.text_chat.assert_not_called()
