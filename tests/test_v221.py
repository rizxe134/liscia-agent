import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import followups, planner, intents, appfirst, webagent

LINK_TASK = "can you open up linkden then can you open up instagram on another tab"
CTX = {"last": {"task": LINK_TASK, "intent": "desktop_app", "query": ""}}

class ChatReplay221(unittest.TestCase):
    """Chat 20261024-001452: '... open up linkden then ... instagram on another tab' then 'do it on google chrome' -> max steps reached."""
    def test_browser_redo_redoes_previous_task(self):
        t, note = followups.resolve("do it on google chrome", CTX)
        self.assertEqual(t, LINK_TASK + " in Google Chrome"); self.assertTrue(note)
        self.assertTrue(appfirst.explicit_web(t))
        fixed, rest = intents.plan(intents.fix_typos(t))
        self.assertEqual([a["url"] for a in fixed], ["https://www.linkedin.com", "https://www.instagram.com"])
    def test_variants(self):
        for s in ["try it in chrome", "do it on the browser", "can you do that in chrome instead"]:
            self.assertTrue(followups.resolve(s, CTX)[0].endswith("in Google Chrome"), s)
        self.assertEqual(followups.resolve("do it on google chrome", {"last": {}})[0], "do it on google chrome")
    def test_browser_never_site_and_lists_are_answers(self):
        p = planner.validate({"intent": "open_site", "site": "google chrome", "query": "top 10 most powerful armies on chrome", "outputs": []}, "do it on google chrome")
        self.assertEqual(p["site"], ""); self.assertEqual(p["intent"], "web_answer"); self.assertEqual(p["query"], "top 10 most powerful armies")
    def test_typos(self):
        self.assertEqual(intents.fix_typos("open linkden and instagarm"), "open linkedin and instagram")

class InventedIds(unittest.TestCase):
    def test_rejected_and_friendly_cap(self):
        L = mock.Mock(); L.clicks = []
        els = [{"id": "3", "role": "link", "label": "Global Firepower 2026", "href": "https://www.globalfirepower.com/"}]
        def call(cmd, **a):
            if cmd == "click": L.clicks.append(a)
            return {"url": "https://www.google.com/search?q=x", "title": "Google", "elements": els} if cmd == "snapshot" else {}
        L.call.side_effect = call
        a = mock.Mock(); a.cfg = {"safety": {"confirm_risky": False}, "agent": {}}; a.logs = []; a.log = a.logs.append
        a.client.text_chat.side_effect = ['{"action":"click","id":"search_result_1"}'] * 12; a.kill = mock.Mock(killed=False); a.confirm = lambda m: True
        a.plan_info = {"intent": "open_site", "query": "", "site": ""}; a.answer_question = mock.Mock(return_value="I searched but found nothing")
        r = webagent.run_web(a, "open the first result", [], open(os.devnull, "w"), link=L, max_steps=8, sleep=lambda s: None)
        self.assertEqual(L.clicks, []); self.assertNotEqual(r, "max steps reached"); self.assertTrue(r.startswith("stopped"), r)
        self.assertIn("[3] Global Firepower", str(a.client.text_chat.call_args_list[1]))
