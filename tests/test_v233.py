"""2.3.3: chat 20261024-032110-b1ac0b - 'news' opened the macOS News app, 'you didn't do the rest' replayed one step, '4 different news'."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import appfirst, intents, followups, core

M1 = "ok find me the lastest news in 4 diffrent news stations then can you open up youtube and find me a good hindi song"
M3 = "on google can you find me the 4 diffrent news and tell me"
IDX = [{"key": "news", "name": "News"}, {"key": "spotify", "name": "Spotify"}, {"key": "discord", "name": "Discord"}, {"key": "music", "name": "Music"}]

class AppFirstGeneric(unittest.TestCase):
    def ov(self, t, intent="web_answer", running=()):
        return appfirst.override({"intent": intent, "query": "x"}, t, idx=IDX, running=set(running))[1]
    def test_news_topic_never_news_app(self):
        self.assertIsNone(self.ov(M3, running={"news"}))
        self.assertIsNone(self.ov(M1, "media_play", running={"news"}))
        self.assertIsNone(self.ov("what's the latest news", running={"news"}))
        self.assertIsNone(self.ov("search the music charts", "web_answer"))
    def test_named_apps_still_win(self):
        self.assertTrue(self.ov("open the news app", "open_site")); self.assertTrue(self.ov("open news", "open_site"))
        self.assertTrue(self.ov("play lofi on spotify", "media_play")); self.assertTrue(self.ov("message bob on discord", "web_interact"))
        self.assertTrue(self.ov("play my playlist in the music app", "media_play"))
    def test_site_named_stays_web(self):
        self.assertIsNone(self.ov("search spotify wrapped on google", "web_answer"))

class Steps(unittest.TestCase):
    def test_split_and_counts(self):
        self.assertEqual(intents.split_steps(M1), ["ok find me the lastest news in 4 diffrent news stations", "can you open up youtube and find me a good hindi song"])
        self.assertEqual(intents.split_steps("what happened then"), ["what happened then"])
        self.assertEqual(intents.requested_count(M3), 4); self.assertEqual(intents.requested_count(M1), 4)
    def test_rest_runs_unfinished_steps(self):
        parts = intents.split_steps(M1)
        self.assertEqual(followups.rest_of("you didnt do the rest", {"last": {"task": M1, "parts": parts, "done": [1]}}), parts[0])
        self.assertEqual(followups.rest_of("you didnt do the rest", {"last": {"task": M1, "result": "done"}}), parts[1])
        self.assertEqual(followups.rest_of("you didnt do the rest", {"last": {"task": M1, "result": "stopped: x"}}), " then ".join(parts))
        self.assertIsNone(followups.rest_of("play it again", {"last": {"task": M1}}))
    def test_multi_runs_each_step_and_tracks_done(self):
        a = core.Agent.__new__(core.Agent); a.log = lambda m: None; a.kill = mock.Mock(killed=False)
        seen = []
        def fake(t):
            seen.append(t); a.last_task_meta = {"task": t}; return "stopped: nope" if len(seen) == 1 else "Playing X"
        a._run = fake
        r = a._run_multi(M1, intents.split_steps(M1))
        self.assertEqual(len(seen), 2); self.assertEqual(a.last_task_meta["done"], [1]); self.assertEqual(a.last_task_meta["task"], M1)
        self.assertIn("1) stopped", r); self.assertIn("2) Playing X", r)

class Live234(unittest.TestCase):
    def test_youtube_search_of_whole_sentence_is_not_an_open(self):
        self.assertFalse(core.Agent._all_opens(M1))
        self.assertTrue(core.Agent._all_opens("open linkedin then open instagram in another tab"))
