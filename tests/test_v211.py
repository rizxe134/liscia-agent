import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import followups, media, planner, chats, webagent, intents
from test_v201 import FakeLink

VIDS = [{"title": "Shirobon - Pursuit | Just Shapes & Beats", "channel": "ShirobonMusic", "href": "https://www.youtube.com/watch?v=a"},
        {"title": "Pursuit", "channel": "Shirobon - Topic", "href": "https://www.youtube.com/watch?v=b"},
        {"title": "Pursuit (Official Audio)", "channel": "isq", "href": "https://www.youtube.com/watch?v=c"},
        {"title": "Just Shapes & Beats - All Songs | Hardcore | S Rank", "channel": "x", "href": "https://www.youtube.com/watch?v=d"}]
MSGS = ["can you open up youtube and look for the song pursuit", "can you play it", "thats the wrong song", "can you try again and try to search it up"]
MODEL_PLANS = {"thats the wrong song": {"intent": "media_play", "query": "pursuit", "site": "", "outputs": [], "source": "model"},
               "can you try again and try to search it up": {"intent": "media_play", "query": "Shirobon Pursuit", "site": "", "outputs": [], "source": "model"}}

class ChatReplay(unittest.TestCase):
    """Chat 20261023-214231-02436a: the retry used to fall into the LLM web loop and drift to 'Just Shapes & Beats all songs'."""
    def run_chat(self, msgs=MSGS):
        import core
        from PIL import Image
        link = FakeLink(VIDS)
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": True}, "safety": {}}
        client = mock.MagicMock(); client.text_chat.side_effect = AssertionError("the LLM web loop must not run for media_play")
        real = planner.plan
        def fake_plan(c, task, use_model=True, log=None, context=None):
            return dict(MODEL_PLANS[task]) if task in MODEL_PLANS else real(None, task, use_model=False, log=log, context=context)
        st = chats.ChatStore(tempfile.mkdtemp()); cid = st.new()["id"]; out = []
        with mock.patch.object(webagent, "nav", lambda l, url, log=None, new_tab=False: link.call("navigate", url=url)), \
             mock.patch.object(planner, "plan", fake_plan), mock.patch("time.sleep"):
            for text in msgs:
                a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (8, 8)), executor=lambda s: mock.Mock(), dom=False)
                a.link = lambda: mock.Mock(connected=lambda: True, call=link.call); a.focus_chrome = lambda: None
                a.chat_ctx = st.context(cid); st.add(cid, "user", text)
                r = a.run(text); out.append((r, link.url)); st.add(cid, "assistant", r, meta=a.last_task_meta)
        return out, link
    def test_replay(self):
        out, link = self.run_chat()
        self.assertIn('Searched YouTube for "pursuit"', out[0][0])
        self.assertTrue(out[1][0].startswith("Playing"), out[1])
        self.assertTrue(out[2][0].startswith("Playing") and out[2][1] != out[1][1], out[2])  # "wrong song" -> a different one
        r, url = out[3]
        self.assertTrue(r.startswith("Playing"), r); self.assertIn("Shirobon", r); self.assertIn("Pursuit", r)
        self.assertIn(url, ("https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=b"))
        navs = [a["url"] for c, a in link.calls if c == "navigate"]
        self.assertIn("https://www.youtube.com/results?search_query=Shirobon+Pursuit", navs)
        self.assertNotIn("https://www.youtube.com/watch?v=d", navs); self.assertFalse([c for c, a in link.calls if c in ("type", "click")])

    def test_live_sequence_retry_skips_everything_already_played(self):
        global VIDS
        old = VIDS
        VIDS = [{"title": "Phoenix Wright Ace Attorney OST - Pressing Pursuit ~ Cornered", "channel": "Gyakuten", "href": "https://www.youtube.com/watch?v=p"},
                {"title": "ISQ - PURSUIT (VIZUALIZER)", "channel": "isq", "href": "https://www.youtube.com/watch?v=i"},
                {"title": "Shirobon - Pursuit | Just Shapes & Beats", "channel": "ShirobonMusic", "href": "https://www.youtube.com/watch?v=a"},
                {"title": "Mix", "href": "https://www.youtube.com/watch?v=m&list=RDm"}, {"title": "19 videos", "href": "https://www.youtube.com/watch?v=q&list=PL1"}]
        MODEL_PLANS["can you try again and try to search it up"]["query"] = "Pursuit"
        try:
            out, link = self.run_chat()
        finally:
            VIDS = old; MODEL_PLANS["can you try again and try to search it up"]["query"] = "Shirobon Pursuit"
        urls = [u for _, u in out[1:]]
        self.assertEqual(len(set(urls)), 3, out)  # every retry plays something new
        self.assertNotIn("https://www.youtube.com/watch?v=m&list=RDm", urls); self.assertNotIn("https://www.youtube.com/watch?v=q&list=PL1", urls)

class Resolver(unittest.TestCase):
    CTX = {"last": {"task": "thats the wrong song", "intent": "media_play", "query": "pursuit", "site": ""}, "media_before": True,
           "played": {"url": "https://www.youtube.com/watch?v=a"}}
    def test_retry_detection(self):
        for t in ("thats the wrong song", "can you try again and try to search it up", "not that one", "try again", "search it up"):
            with self.subTest(t=t): self.assertTrue(followups.is_retry(t, self.CTX))
        self.assertFalse(followups.is_retry("try again", {"last": {}}))
    def test_most_recent_item_wins(self):
        self.assertEqual(followups.retry_query("Shirobon Pursuit", self.CTX), "Shirobon Pursuit")  # refinement of the latest item
        self.assertEqual(followups.retry_query("Just Shapes & Beats all songs", self.CTX), "pursuit")  # stale/unrelated -> latest item
        self.assertEqual(followups.retry_query("", self.CTX), "pursuit")
    def test_context_carries_latest_query_and_played(self):
        st = chats.ChatStore(tempfile.mkdtemp()); cid = st.new()["id"]
        st.add(cid, "assistant", "x", meta={"task": "play frog", "intent": "media_play", "query": "frog", "played": {"url": "u1"}})
        st.add(cid, "assistant", "y", meta={"task": "play pursuit", "intent": "media_play", "query": "pursuit", "played": {"url": "u2"}})
        st.add(cid, "assistant", "z", meta={"task": "thats wrong", "intent": "chat", "query": ""})
        c = st.context(cid); self.assertEqual(c["last"]["query"], "pursuit"); self.assertEqual(c["played"]["url"], "u2")

class WebLoopAntiDrift(unittest.TestCase):
    def agent(self, replies, query="Shirobon Pursuit"):
        a = mock.Mock(); a.cfg = {"safety": {"confirm_risky": False}, "agent": {}}; a.logs = []; a.log = a.logs.append
        a.client.text_chat.side_effect = list(replies); a.kill = mock.Mock(killed=False); a.confirm = lambda m: True
        a.plan_info = {"query": query, "site": "youtube"}; a.user_text = "can you try again and try to search it up"; return a
    def link(self):
        L = mock.Mock(); L.typed = []; L.navs = []
        els = [{"id": "4", "role": "searchbox", "label": "Search", "tag": "input", "itype": "text"}, {"id": "9", "role": "link", "label": "Bing Wallpaper", "href": "https://x"}]
        def call(cmd, **a):
            if cmd == "type": L.typed.append(a.get("text"))
            return {"url": "https://www.youtube.com/", "title": "YouTube", "elements": els} if cmd == "snapshot" else {}
        L.call.side_effect = call; return L
    def go(self, replies):
        L = self.link(); ag = self.agent(replies)
        with mock.patch.object(webagent, "nav", lambda l, u, log=None, new_tab=False: L.navs.append(u) or {}):
            r = webagent.run_web(ag, "play Shirobon Pursuit", [], open(os.devnull, "w"), link=L, max_steps=20, sleep=lambda s: None)
        return r, L, ag
    def test_off_goal_text_blocked(self):
        r, L, ag = self.go(['{"action":"type","id":"4","text":"Just Shapes & Beats all songs","press_enter":true}',
                             '{"action":"type","id":"4","text":"lively wallpaper setup","press_enter":true}',
                             '{"action":"type","id":"4","text":"Shirobon Pursuit","press_enter":true}', '{"action":"done","summary":"searched"}'] + ['{"action":"done","summary":"x"}'] * 4)
        self.assertEqual(L.typed, ["Shirobon Pursuit"])
        self.assertIn("GOAL QUERY (type exactly this when searching): Shirobon Pursuit", ag.client.text_chat.call_args_list[0][0][0][1]["content"])
    def test_repeat_blocks_replan_then_stop(self):
        r, L, ag = self.go(['{"action":"click","id":"9"}'] * 20)
        self.assertIn("https://www.youtube.com/results?search_query=Shirobon+Pursuit", L.navs)
        self.assertTrue(r.startswith("stopped: I kept repeating"), r); self.assertLess(ag.client.text_chat.call_count, 20)

class JunkLabels(unittest.TestCase):
    def test_snapshot_titles_not_true_or_now_playing(self):
        L = mock.Mock(); h = "https://www.youtube.com/watch?v=a"
        els = [{"id": "1", "label": "true", "href": h}, {"id": "2", "label": "2:05 Now playing", "href": h},
               {"id": "3", "label": "Shirobon - Pursuit | Just Shapes & Beats", "href": h}]
        L.call.side_effect = lambda cmd, **a: {} if cmd == "video_results" else {"elements": els}
        got = media.results(L); self.assertEqual(got[0]["title"], "Shirobon - Pursuit | Just Shapes & Beats")

if __name__ == "__main__": unittest.main()
