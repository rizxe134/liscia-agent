import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import intents, followups, media, planner, chats

class Filler(unittest.TestCase):
    CASES = {
        "can you go on youtube and find me a song by the name of Frog": "Frog",
        "me a song by the name of Frog": "Frog",
        "the song of frog by ptasinski": "frog by ptasinski",
        "can you play me the song of frog by ptasinski": "frog by ptasinski",
        "play me a video called Never Gonna Give You Up": "Never Gonna Give You Up",
        "please play some lofi beats for me": "lofi beats",
        "find me the track Blinding Lights by The Weeknd": "Blinding Lights by The Weeknd",
        "could you please search for cat videos": "cat videos",
        "i want to listen to the song Pursuit by isq": "Pursuit by isq",
        "put on a song named Gettin Money": "Gettin Money",
        "something called Hello by Adele": "Hello by Adele",
        "hey can you look up a clip titled funny cats": "funny cats",
        "play gettin money": "gettin money",
        "play frog by ptasinski on youtube": "frog by ptasinski",
        "search for the video about how to tie a tie please": "how to tie a tie",
        "open youtube and play the music video for Bohemian Rhapsody": "for Bohemian Rhapsody",
    }
    def test_phrasings(self):
        for t, want in self.CASES.items():
            with self.subTest(t=t): self.assertEqual(intents.strip_filler(t), want)
    def test_references_are_empty(self):
        for t in ("the song", "play it", "that one", "play me the song", "the video"):
            with self.subTest(t=t): self.assertEqual(intents.strip_filler(t), "")
    def test_youtube_request_and_planner(self):
        self.assertEqual(intents.youtube_request("can you go on youtube and find me a song by the name of Frog")[0], "Frog")
        p = planner.plan(None, "can you go on youtube and find me a song by the name of Frog", use_model=False)
        self.assertEqual(p["query"], "Frog")
        p = planner.validate({"intent": "media_play", "query": "me a song by the name of Frog", "outputs": []}, "find me a song by the name of Frog on youtube")
        self.assertEqual(p["query"], "Frog")

class Followups(unittest.TestCase):
    CTX = {"last": {"task": "can you go on youtube and find me a song by the name of Frog", "intent": "media_play", "query": "Frog", "site": "youtube"}}
    def test_reference_uses_previous_query(self):
        for t in ("can you play me the song", "play it", "play that one", "ok play it", "now play the song"):
            with self.subTest(t=t): self.assertEqual(followups.resolve(t, self.CTX)[0], "play Frog on youtube")
    def test_corrections_redo_with_new_target(self):
        for t, want in (("no I meant can you play me the song of frog by ptasinski", "play frog by ptasinski on youtube"),
                        ("actually frog by ptasinski", "play frog by ptasinski on youtube"),
                        ("no, the one by ptasinski", "play Frog by ptasinski on youtube"),
                        ("I mean the song Frog by Ptasinski", "play Frog by Ptasinski on youtube")):
            with self.subTest(t=t): self.assertEqual(followups.resolve(t, self.CTX)[0], want)
    def test_unrelated_or_no_context(self):
        self.assertEqual(followups.resolve("what's the weather", self.CTX), ("what's the weather", None))
        self.assertEqual(followups.resolve("play it", {}), ("play it", None))
        self.assertEqual(followups.resolve("play gettin money", self.CTX)[1], None)
    def test_planner_gets_chat_context(self):
        client = mock.Mock(); client.text_chat.return_value = '{"intent":"media_play","query":"frog","outputs":[]}'
        planner.plan(client, "find that frog song again please", context={"turns": [{"role": "user", "content": "x"}], "last": self.CTX["last"]})
        sent = client.text_chat.call_args.args[0][-1]["content"]
        self.assertIn("previous task", sent); self.assertIn("'Frog'", sent); self.assertIn("NEW TASK", sent)
    def test_store_context(self):
        st = chats.ChatStore(tempfile.mkdtemp()); c = st.new()
        st.add(c["id"], "user", "find frog"); st.add(c["id"], "assistant", "Playing x", meta=self.CTX["last"])
        ctx = st.context(c["id"]); self.assertEqual(ctx["last"]["query"], "Frog"); self.assertEqual(len(ctx["turns"]), 2)

class Ranking(unittest.TestCase):
    RES = [{"id": "1", "title": "Mix - Ptasinski", "kind": "mix", "href": "https://www.youtube.com/watch?v=m&list=RD&start_radio=1"},
           {"id": "2", "title": "Funny Song #9: The Name of my Frog", "kind": "video", "href": "https://www.youtube.com/watch?v=f"},
           {"id": "3", "title": "frog", "channel": "Ptasinski", "kind": "video", "href": "https://www.youtube.com/watch?v=p"},
           {"id": "4", "title": "Ptasinski - Frog (1 hour loop)", "kind": "video", "href": "https://www.youtube.com/watch?v=l"}]
    def test_title_and_artist_win_over_mix_and_loops(self):
        self.assertEqual(media.rank("frog by ptasinski", self.RES)[0][2]["id"], "3")
    def test_live_case_plain_track_beats_tagged_clip(self):
        res = [{"title": "Little cute video. Frog: Song by RJ Pasin and ptasinski #jada4ev #rjpasin #ptasinski 1 minute, 33 seconds", "href": "https://www.youtube.com/watch?v=c&list=RDc&start_radio=1"},
               {"title": "Frog Rj Pasin", "href": "https://www.youtube.com/watch?v=r&list=PL"},
               {"title": "frog 1 minute, 31 seconds", "channel": "ptasinski", "href": "https://www.youtube.com/watch?v=p&list=RDp&start_radio=1"}]
        self.assertEqual(media.rank("frog by ptasinski", res)[0][2]["href"], "https://www.youtube.com/watch?v=p&list=RDp&start_radio=1")
    def test_snapshot_fallback_reads_channel(self):
        link = mock.Mock()
        def call(cmd, **a):
            if cmd == "video_results": raise __import__("extlink").ExtError("unknown command video_results")
            return {"elements": [{"id": "1", "label": "frog", "href": "https://www.youtube.com/watch?v=p"}, {"id": "2", "label": "ptasinski", "href": "https://www.youtube.com/@ptasinski"}]}
        link.call.side_effect = call
        self.assertEqual(media.results(link)[0]["channel"], "ptasinski")
    def test_radio_link_plain_video_not_mix_and_clean_url(self):
        h = "https://www.youtube.com/watch?v=RTDUbi0P0B8&list=RDRTDUbi0P0B8&start_radio=1"
        r = media.rank("frog by ptasinski", [{"title": "Mix - frog", "href": h}, {"title": "frog", "channel": "ptasinski", "href": h}])
        self.assertEqual(r[0][2]["kind"], "video"); self.assertGreaterEqual(r[0][1], media.GOOD)
        self.assertEqual(media.clean(h), "https://www.youtube.com/watch?v=RTDUbi0P0B8")
    def test_snapshot_dedupes_and_finds_far_channel(self):
        link = mock.Mock(); h = "https://www.youtube.com/watch?v=A1&list=RDA1&start_radio=1"
        els = [{"id": "1", "label": "frog 1 minute, 31 seconds", "href": h}, {"id": "2", "label": "frog", "href": h}] + \
              [{"id": str(i), "label": "x", "href": ""} for i in range(3, 10)] + [{"id": "10", "label": "ptasinski", "href": "https://www.youtube.com/@ptasinski"}]
        link.call.side_effect = lambda cmd, **a: {} if cmd == "video_results" else {"elements": els}
        got = media.results(link); self.assertEqual(len(got), 1); self.assertEqual(got[0]["channel"], "ptasinski")
    def test_title_match_fuzzy(self):
        self.assertEqual(intents.title_match("frog by ptasinski", "Ptasiński – Frog"), 1.0)
        self.assertEqual(intents.title_match("frog by ptasinski", "Funny Song #9: The Name of my Frog"), 0.5)

class FakeLink:
    """YouTube in a box: results pages, watch pages with titles; 'Play (k)' never counts."""
    def __init__(self, videos, start="https://www.youtube.com/watch?v=6YbFNApKc2k", start_title="Ptasinski Radio Mix"):
        self.videos, self.url, self.calls = videos, start, []
        self.titles = {start: start_title}
        for v in videos: self.titles[v["href"]] = v["title"]
    def call(self, cmd, timeout=None, **a):
        self.calls.append((cmd, a))
        if cmd == "navigate": self.url = a["url"]; return {"title": self.titles.get(self.url, "YouTube")}
        if cmd == "video_results": return {"results": [dict(v, id=str(i)) for i, v in enumerate(self.videos)] if "results" in self.url else []}
        if cmd == "media_state": return {"url": self.url, "title": self.titles.get(self.url, ""), "channel": next((v.get("channel", "") for v in self.videos if v["href"] == self.url), ""), "paused": False}
        if cmd == "media_control": return {"paused": False}
        if cmd == "scroll": return {"moved": 0}
        if cmd == "snapshot": return {"url": self.url, "title": self.titles.get(self.url, "YouTube"), "elements": []}
        if cmd in ("ad_watch", "ad_state"):  # like a pre-2.1.1 extension
            import extlink; raise extlink.ExtError(f"unknown command {cmd}")
        raise AssertionError(cmd)

def agent():
    a = mock.Mock(); a.log = lambda m: None; return a

class YouTubePlay(unittest.TestCase):
    def run_play(self, link, q):
        import webagent
        with mock.patch.object(webagent, "nav", lambda l, url, log=None, new_tab=False: link.call("navigate", url=url)):
            return media.youtube_play(agent(), link, q, open(os.devnull, "w"), sleep=lambda s: None)
    def test_always_searches_and_verifies(self):
        link = FakeLink(Ranking.RES)
        r = self.run_play(link, "frog by ptasinski")
        self.assertTrue(any(c == "navigate" and "results?search_query=frog+by+ptasinski" in a["url"] for c, a in link.calls))
        self.assertEqual(link.url, "https://www.youtube.com/watch?v=p"); self.assertIn('Playing "frog" by Ptasinski on YouTube.', r)
    def test_current_video_kept_only_if_it_matches(self):
        link = FakeLink(Ranking.RES, start="https://www.youtube.com/watch?v=p", start_title="frog")
        link.videos[2]["channel"] = "Ptasinski"
        r = self.run_play(link, "frog by ptasinski"); self.assertIn("already open", r)
        self.assertFalse(any(c == "navigate" for c, _ in link.calls))
    def test_next_candidate_then_honest_closest(self):
        vids = [{"title": "Frog Song", "href": "https://www.youtube.com/watch?v=a"}, {"title": "Frog (cover)", "href": "https://www.youtube.com/watch?v=b"}]
        link = FakeLink(vids)
        r = self.run_play(link, "frog by ptasinski")
        self.assertIn("Couldn't find an exact match", r); self.assertIn("playing the closest", r)
    def test_nothing_relevant_fails_honestly(self):
        link = FakeLink([{"title": "Cats compilation", "href": "https://www.youtube.com/watch?v=c"}])
        self.assertTrue(self.run_play(link, "frog by ptasinski").startswith("stopped: couldn't find"))

class GoalCheck(unittest.TestCase):
    def test_play_button_on_wrong_video_is_not_done(self):
        ok, why = intents.goal_check("play me the song of frog by ptasinski", {"url": "https://www.youtube.com/watch?v=6YbFNApKc2k", "title": "Mix - Radio - YouTube"})
        self.assertFalse(ok); self.assertIn("doesn't match", why)
        self.assertTrue(intents.goal_check("play frog by ptasinski", {"url": "https://www.youtube.com/watch?v=p", "title": "Ptasinski - Frog - YouTube"})[0])
        self.assertFalse(intents.goal_reached("play frog by ptasinski", "https://www.youtube.com/watch?v=x", "Some Radio Mix"))
        self.assertTrue(intents.goal_reached("play the first video", "https://www.youtube.com/watch?v=x", "anything"))
    def test_webagent_rejects_unverified_done(self):
        import webagent
        link = mock.Mock(); snap = {"url": "https://www.youtube.com/watch?v=6Y", "title": "Radio Mix - YouTube", "elements": [{"id": "84", "label": "Play (k)", "role": "button"}]}
        link.call.return_value = snap
        client = mock.Mock(); client.text_chat.side_effect = ['{"action":"done","summary":"goal reached"}'] * 3
        ag = mock.Mock(); ag.client = client; ag.kill.killed = False; ag.cfg = {"safety": {"confirm_risky": False}}; ag.log = lambda m: None
        r = webagent.run_web(ag, "play me the song of frog by ptasinski", [], open(os.devnull, "w"), link=link, sleep=lambda s: None, max_steps=5)
        self.assertTrue(r.startswith("stopped: couldn't confirm"), r)

class EndToEnd(unittest.TestCase):
    """The failing chat: search -> 'play me the song' -> correction. No model calls; every play verified."""
    def test_chat_sequence(self):
        import core
        from PIL import Image
        vids = [{"title": "Mix - Ptasinski", "kind": "mix", "href": "https://www.youtube.com/watch?v=m&list=RD&start_radio=1"},
                {"title": "Funny Song #9: The Name of my Frog", "href": "https://www.youtube.com/watch?v=f"},
                {"title": "frog", "channel": "Ptasinski", "href": "https://www.youtube.com/watch?v=p"}]
        link = FakeLink(vids)
        cfg = {"ollama": {"host": "x", "model": "m"}, "agent": {"max_steps": 3, "runs_dir": "/tmp/pcagent-test", "step_delay_s": 0, "planner": False}, "safety": {}}
        client = mock.MagicMock()
        st = chats.ChatStore(tempfile.mkdtemp()); cid = st.new()["id"]
        import webagent
        out = []
        with mock.patch.object(webagent, "nav", lambda l, url, log=None, new_tab=False: link.call("navigate", url=url)), mock.patch("time.sleep"):
            for text in ("can you go on youtube and find me a song by the name of Frog", "can you play me the song",
                         "no I meant can you play me the song of frog by ptasinski"):
                a = core.Agent(cfg, log=lambda m: None, gui=mock.Mock(), client=client, capture=lambda: Image.new("RGB", (8, 8)), executor=lambda s: mock.Mock(), dom=False)
                a.link = lambda: mock.Mock(connected=lambda: True, call=link.call); a.focus_chrome = lambda: None
                a.chat_ctx = st.context(cid); st.add(cid, "user", text)
                r = a.run(text); out.append(r); st.add(cid, "assistant", r, meta=a.last_task_meta)
        self.assertIn("search_query=Frog", [a["url"] for c, a in link.calls if c == "navigate"][0])
        self.assertIn('Playing', out[0]); self.assertIn("frog", out[1].lower())  # "the song" = the previous query, searched and verified
        self.assertIn('Playing "frog" by Ptasinski', out[2]); self.assertEqual(link.url, "https://www.youtube.com/watch?v=p")
        client.chat.assert_not_called()
