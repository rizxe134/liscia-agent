"""2.3.0: log-review fixes (complete lists, article mode, compound tasks, ordinal videos), model downloads, livelier cursor."""
import os, sys, json, unittest, threading
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import core, media, modelhub, appfirst, webagent
from test_v220 import _chrome, CONTENT, STUB, PAGE

class Answers(unittest.TestCase):
    def test_list_string_becomes_lines(self):
        self.assertEqual(core.tidy_answer("['1. Koenigsegg', '2. Yangwang U9']"), "1. Koenigsegg\n2. Yangwang U9")
        self.assertEqual(core.tidy_answer(["1. A", "2. B"]), "1. A\n2. B")
    def test_split_followon(self):
        a, b = core.split_followon("can you search up the top 10 fastest cars then can you open up github on a new tab then in a new tab open up xbox")
        self.assertEqual(a, "can you search up the top 10 fastest cars"); self.assertTrue(b.startswith("can you open up github"))
        self.assertEqual(core.split_followon("what is the capital of france")[1], "")
        self.assertTrue(appfirst.explicit_web("open up github on a new tab"))
    def _agent(self, answers):
        a = core.Agent.__new__(core.Agent); a.cfg = {"agent": {}}; a.logs = []; a.log = a.logs.append
        a._answer_from = mock.Mock(side_effect=answers); return a
    def _link(self, pages):
        L = mock.Mock(); L.url = [pages[0][0]]; L.navs = []
        RES = {"url": "https://www.google.com/search?q=armies", "title": "Google", "elements": [
            {"id": "1", "role": "link", "label": "Global Firepower home", "href": "https://www.globalfirepower.com/"},
            {"id": "2", "role": "link", "label": "2026 Military Strength Ranking", "href": "https://www.globalfirepower.com/countries-listing.php"}]}
        def call(cmd, **k):
            if cmd == "snapshot": return RES if "google" in L.url[0] else {"url": L.url[0], "title": "GFP 2026", "elements": []}
            if cmd == "extract_text": return {"text": dict(pages).get(L.url[0], "")}
            if cmd == "navigate": L.url[0] = k["url"]; L.navs.append(k["url"]); return {}
            return {}
        L.call.side_effect = call; return L
    def test_short_list_reads_the_article_and_keeps_the_longest(self):
        L = self._link([("https://www.google.com/search?q=armies", "snippet"), ("https://www.globalfirepower.com/countries-listing.php", "full list")])
        ten = "\n".join(f"{i}. C{i}" for i in range(1, 11))
        a = self._agent(["1. US\n2. Russia\n3. China\n4. India\n5. South Korea", ten])
        with mock.patch("time.sleep"): r = a.answer_question(L, "top 10 most powerful armies", open(os.devnull, "w"), count=10)
        self.assertEqual(r, ten); self.assertEqual(L.navs, ["https://www.globalfirepower.com/countries-listing.php"])  # article beats home page
    def test_article_mode_skips_results_page_and_cites_source(self):
        L = self._link([("https://www.google.com/search?q=armies", "snippet"), ("https://www.globalfirepower.com/countries-listing.php", "full list")])
        a = self._agent(["1. US"])
        with mock.patch("time.sleep"): r = a.answer_question(L, "top armies", open(os.devnull, "w"), article=True)
        self.assertEqual(a._answer_from.call_count, 1); self.assertIn("Source: GFP 2026", r)
        self.assertTrue(core.ARTICLE_RE.search("you didnt go to an article"))

class Ordinal(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(media.ordinal_pick("ok scarcth that can you take me to youtube and take me to wacth the 5th video you see"), (5, ""))
        self.assertEqual(media.ordinal_pick("play the third video for lofi beats"), (3, "lofi beats"))
        for t in ["play maroon 5", "play top 10 songs", "play embrace it", "play the 1975 somebody else"]: self.assertIsNone(media.ordinal_pick(t), t)
    def test_plays_nth(self):
        res = [{"id": str(i), "title": f"Video {i}", "href": f"https://www.youtube.com/watch?v=abcdefghij{i}"} for i in range(1, 8)]
        L = mock.Mock(); navs = []
        ag = mock.Mock(); ag.cfg = {}; ag.log = lambda m: None
        with mock.patch.object(media, "results", return_value=res), mock.patch.object(media, "state", return_value={"title": "Video 5", "url": res[4]["href"]}):
            r = media.youtube_nth(ag, L, 5, "", open(os.devnull, "w"), sleep=lambda s: None, nav=navs.append)
        self.assertEqual(navs, ["https://www.youtube.com/", "https://www.youtube.com/watch?v=abcdefghij5"]); self.assertIn("Video 5", r)

class ModelHub(unittest.TestCase):
    def test_catalog_and_fit(self):
        names = [e[0] for e in modelhub.CATALOG]
        for n in ["qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b", "qwen3:4b", "qwen3:8b", "llama3.2:3b", "llama3.1:8b", "gemma3:4b", "gemma3:12b",
                  "mistral:7b", "phi4-mini", "qwen2.5vl:7b", "qwen3-vl:4b", "qwen3-vl:8b", "llava:7b"]: self.assertIn(n, names)
        e14 = next(e for e in modelhub.CATALOG if e[0] == "qwen2.5:14b")
        self.assertEqual(modelhub.fit(e14[2], 14.0), "too big"); self.assertEqual(modelhub.fit(e14[2], 32.0), "ok")
        self.assertIn("TOO BIG", modelhub.label(e14, 14.0)); self.assertEqual(modelhub.name_from_label(modelhub.label(e14, 14.0)), "qwen2.5:14b")
        self.assertIn("ollama pull", modelhub.HOW_TO)
    def _resp(self, lines):
        r = mock.MagicMock(); r.__enter__.return_value = r; r.iter_lines.return_value = [json.dumps(x).encode() for x in lines]; return r
    def test_pull_progress_and_cancel(self):
        seen = []; post = mock.Mock(return_value=self._resp([{"status": "pulling", "completed": 5, "total": 10}, {"status": "success"}]))
        self.assertTrue(modelhub.pull("http://h", "llama3.2:1b", lambda s, d, t: seen.append((d, t)), post=post))
        self.assertEqual(seen[0], (5, 10)); self.assertEqual(post.call_args[1]["json"], {"model": "llama3.2:1b", "stream": True})
        ev = threading.Event(); ev.set()
        with self.assertRaises(modelhub.Cancelled): modelhub.pull("http://h", "x", cancel=ev, post=mock.Mock(return_value=self._resp([{"status": "pulling"}])))
    def test_delete(self):
        req = mock.Mock(return_value=mock.Mock(status_code=200)); modelhub.delete("http://h", "llama3.2:1b", req=req)
        self.assertEqual(req.call_args[0][:2], ("DELETE", "http://h/api/delete"))

@unittest.skipUnless(_chrome(), "needs playwright + Chrome")
class LivelyCursor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        cls.pw = _chrome()().start(); cls.b = cls.pw.chromium.launch(channel="chrome" if shutil.which("google-chrome") else None, args=["--no-sandbox"])
    @classmethod
    def tearDownClass(cls): cls.b.close(); cls.pw.stop()
    def test_moves_while_idle_scroll_and_type(self):
        p = self.b.new_page(viewport={"width": 1000, "height": 600}); p.set_content(PAGE.replace("</body>", "<p style='height:2000px'>" + "text " * 400 + "</p></body>"))
        p.evaluate(STUB); p.evaluate("(()=>{" + CONTENT + "})()"); p.evaluate("window.__liscia.viz({on:true})")
        p.evaluate("window.__liscia.extract_text({})")
        pos = set()
        for _ in range(5): p.wait_for_timeout(800); d = p.evaluate("window.__liscia.viz_pos()"); pos.add((d["x"], d["y"]))
        self.assertGreaterEqual(len(pos), 3, pos)  # it drifts over the page while 'thinking'
        a = p.evaluate("window.__liscia.viz_pos()"); p.evaluate("window.__liscia.scroll({direction:'down',wait_lazy:false})"); b = p.evaluate("window.__liscia.viz_pos()")
        self.assertNotEqual((a["x"], a["y"]), (b["x"], b["y"]))
        s = p.evaluate("window.__liscia.snapshot({})"); box = next(e["id"] for e in s["elements"] if e["role"] == "textbox")
        p.evaluate(f"window.__liscia.type('{box}', 'pursuit', {{}})"); self.assertEqual(p.evaluate("q.value"), "pursuit")
        self.assertEqual(p.evaluate("document.elementFromPoint(500,300).closest('#liscia-agent-overlay-host')"), None)
        self.assertNotIn("reading", json.dumps(s)); self.assertNotIn("thinking", json.dumps(s))

class ExtReload(unittest.TestCase):
    def test_older_22x_reloads_once(self):
        import extlink
        self.assertTrue(extlink.needs_reload("2.2.2", "2.3.0")); self.assertFalse(extlink.needs_reload("2.0.1", "2.3.0")); self.assertFalse(extlink.needs_reload("2.3.0", "2.3.0"))
        L = extlink.ExtLink() if hasattr(extlink, "ExtLink") else extlink.LINK.__class__()
        out = L.poll({"version": "2.2.2"}, hold=0.01); self.assertEqual([c["cmd"] for c in out], ["reload_extension"])
        self.assertEqual(L.poll({"version": "2.2.2"}, hold=0.01), [])

class LiveFixes231(unittest.TestCase):
    def test_new_tab_clause_opens_unknown_site(self):
        import intents
        with mock.patch.object(intents, "GUESS_CHECK", False):
            fixed, rest = intents.plan("can you open up github on a new tab then in a new tab open up xbox")
        self.assertEqual(rest, ""); self.assertEqual([a["url"] for a in fixed], ["https://github.com", "https://www.xbox.com"])

class ArticleFallback232(unittest.TestCase):
    def test_article_words_stripped_and_results_fallback(self):
        a = core.Agent.__new__(core.Agent); a.cfg = {"agent": {}}; a.log = lambda m: None
        a._answer_from = mock.Mock(side_effect=["", "1. US"])
        L = mock.Mock(); url = ["https://www.google.com/search?q=x"]
        RES = {"url": "https://www.google.com/search?q=x", "elements": [{"id": "1", "role": "link", "label": "Military ranking 2026", "href": "https://a.com/rank"}]}
        def call(cmd, **k):
            if cmd == "snapshot": return RES if "google" in url[0] else {"url": url[0], "elements": []}
            if cmd == "extract_text": return {"text": "page"}
            if cmd == "navigate": url[0] = k["url"]
            return {}
        L.call.side_effect = call
        with mock.patch("time.sleep"): r = a.answer_question(L, "top armies 2026 article", open(os.devnull, "w"), article=True, max_pages=1)
        self.assertNotIn("article", a._answer_from.call_args_list[0][0][0]); self.assertTrue(r.startswith("1. US"), r)
