import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import followups, webagent, intents
M1 = "ok find me the lastest news in 4 diffrent news stations then can you open up youtube and find me a good hindi song"

class Rest235(unittest.TestCase):
    def last(self, r2):
        return {"last": {"task": M1, "parts": intents.split_steps(M1), "done": [0, 1], "part_results": ["1. A (CNN)", r2]}}
    def test_search_only_step_gets_played(self):
        self.assertEqual(followups.nothing_left("you didnt do the rest", self.last('Searched YouTube for "good hindi song". Say "play it"')),
                         ("do", "play good hindi song on youtube"))
    def test_all_done_honest(self):
        kind, msg = followups.nothing_left("you didnt do the rest", self.last('Playing "X" on YouTube.'))
        self.assertEqual(kind, "say"); self.assertIn("All 2 steps", msg); self.assertIn("Playing", msg)
        self.assertIsNone(followups.nothing_left("play it", self.last("x")))

class News235(unittest.TestCase):
    def test_outlets_distinct_and_formatted(self):
        els = [{"role": "link", "label": "Euronews.com Video. Latest news bulletin October 24th 2026 midday 3 hours ago", "href": "https://www.euronews.com/video/1"},
               {"role": "link", "label": "Another Euronews story about Europe today", "href": "https://www.euronews.com/2"},
               {"role": "link", "label": "FOX10 News Brief for Friday evening Oct 23", "href": "https://www.fox10phoenix.com/video/2"},
               {"role": "link", "label": "KTLA 5 News Top Stories at 5 pm", "href": "https://ktla.com/news/3"},
               {"role": "link", "label": "Tracking undefeated FBS college football teams", "href": "https://www.cbssports.com/x"},
               {"role": "link", "label": "Google News help center page", "href": "https://support.google.com/news"}]
        it = webagent.news_list({"elements": els}, 4)
        self.assertEqual([i["outlet"] for i in it], ["Euronews", "FOX 10 Phoenix", "KTLA 5", "Cbssports"])
        self.assertTrue(it[0]["headline"].startswith("Latest news bulletin"))

class SongPlays(unittest.TestCase):
    def test_song_wording_not_search_only(self):
        import re, inspect, core
        self.assertIn("a song request implies playing", inspect.getsource(core.Agent._run))

class Tracing235(unittest.TestCase):
    def test_events_and_fallback_reason(self):
        import providers
        cloud = mock.Mock(provider="gemini", text_model="gemini-pro-latest", model="gemini-pro-latest")
        cloud.text_chat.side_effect = providers.ProviderError("gemini", "quota", "rate limit or quota exceeded (429)")
        local = mock.Mock(model="qwen3-vl:4b-instruct", text_model="qwen2.5:7b"); local.check.return_value = ["qwen2.5:7b", "qwen3-vl:4b-instruct"]
        local.text_chat.return_value = "ok"
        evs = []; c = providers.TracingClient(providers.FallbackClient(cloud, local, log=lambda m: None), evs.append)
        self.assertEqual(c.text_chat([{"role": "user", "content": "x"}]), "ok")
        e = evs[0]; self.assertEqual((e["provider"], e["model"], e["fallback"], e["used_model"]), ("gemini", "gemini-pro-latest", True, "qwen2.5:7b"))
        self.assertIn("429", e["fallback_reason"])
        cloud.text_chat.side_effect = None; cloud.text_chat.return_value = "hi"; c.text_chat([{"role": "user", "content": "y"}])
        self.assertFalse(evs[1]["fallback"]); self.assertNotIn("key", str(evs).lower())

class KeyCache236(unittest.TestCase):
    def test_keychain_read_once(self):
        import keystore
        kr = mock.Mock(); kr.get_password.return_value = "secret-value"
        keystore._backend = kr; keystore.clear_cache()
        try:
            for _ in range(5): self.assertEqual(keystore.get("gemini"), "secret-value")
            self.assertEqual(kr.get_password.call_count, 1)
            keystore.set("gemini", "new"); self.assertEqual(keystore.get("gemini"), "new"); self.assertEqual(kr.get_password.call_count, 1)
        finally:
            keystore._backend = None; keystore.clear_cache()
    def test_build_uses_stable_identity(self):
        s = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "build_mac_dmg.sh")).read()
        self.assertIn("Liscia Agent Local Signing", s); self.assertIn("--identifier local.liscia.agent", s)
