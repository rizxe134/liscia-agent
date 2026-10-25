import os, tkinter as tk, pytest
import inputhist, chats

def test_history_nav_keeps_draft(tmp_path):
    h = inputhist.History(str(tmp_path / "h.json"))
    for t in ["a", "b", "c"]: h.add(t, "x")
    assert h.up("draft", "x") == "c" and h.up("", "x") == "b" and h.up("", "x") == "a" and h.up("", "x") == "a"
    assert h.down("", "x") == "b" and h.down("", "x") == "c" and h.down("", "x") == "draft"
    assert h.down("", "x") is None

def test_history_per_chat_global_persist_cap(tmp_path):
    p = str(tmp_path / "h.json"); h = inputhist.History(p)
    h.add("g1", "a"); h.add("mine", "b"); h.add("mine", "b")
    assert h.chats["b"] == ["mine"]
    assert h.items("b") == ["g1", "mine"]
    for i in range(600): h.add(f"m{i}", "a")
    h2 = inputhist.History(p)
    assert len(h2.glob) == 500 and len(h2.chats["a"]) == 500 and h2.glob[-1] == "m599"

def test_reverse_search(tmp_path):
    h = inputhist.History(str(tmp_path / "h.json"))
    for t in ["open youtube", "news", "youtube song"]: h.add(t)
    assert h.search("tube") == "youtube song"
    assert h.search("tube", older=True) == "open youtube"
    assert h.search("tube", older=True) is None

def test_complete():
    assert inputhist.complete("/to") == ("/token ", ["/token"])
    assert inputhist.complete("/ne")[0] == "/new"
    assert inputhist.complete("hello")[1] == []

def test_new_chat_reuses_empty(tmp_path):
    s = chats.ChatStore(str(tmp_path))
    a = s.new_or_reuse(); b = s.new_or_reuse()
    assert a["id"] == b["id"] and len(s.list()) == 1

@pytest.mark.parametrize("size", [10, 16, 22])
def test_flatbutton_frame_border(size):
    import ui
    r = tk.Tk()
    try:
        hits = []
        b = ui.FlatButton(r, text="[ + NEW CHAT ]", command=lambda: hits.append(1), font=("Courier", size)); b.pack()
        assert isinstance(b, tk.Frame) and int(b.lbl.cget("highlightthickness")) == 0
        b.configure(text="X", state="disabled", fg="#123456", highlightbackground="#abcdef")
        assert b.cget("text") == "X" and b.cget("fg") == "#123456" and b.cget("highlightbackground") == "#abcdef"
        assert b.cget("bg") == "#abcdef"
        b.configure(state="normal"); b.invoke(); assert hits == [1]
    finally: r.destroy()

import webagent, core, planner

def test_headline_cleanup():
    o = webagent.outlet_of("https://time.com/x")
    assert webagent.clean_headline('Magazine The Fight Over Who Counts in India "Many Indians might', o) == "The Fight Over Who Counts in India"
    assert webagent.clean_headline("Ambani's Jio becomes most subscribed Indian IPO with $77 billion in bids Bids for x", "Reuters").endswith("in bids")
    assert webagent.clean_headline("Seattle council passes budget The Seattle Times", "Seattle Times") == "Seattle council passes budget"
    assert webagent.outlet_of("https://www.chicagotribune.com/a") == "Chicago Tribune"
    assert webagent.NOT_NEWS_RE.search("Today News Headlines for School Assembly, October 9")

def test_no_year_on_news():
    assert planner.with_year("top news in india", "what the top news in india is right now") == "top news in india"
    assert planner.with_year("best phones", "latest best phones").endswith(str(planner.today().year))

def test_summarize_targets_uses_previous_items():
    items = [{"headline": f"h{i}", "outlet": "X", "href": f"https://x.com/{i}"} for i in range(7)]
    ctx = {"last": {"task": "top news", "news_items": items, "result": "1. h0 (X)"}}
    assert len(core.summarize_targets("can you summerize the top 5 articles", ctx)) == 5
    assert len(core.summarize_targets("explain those", ctx)) == 7
    assert core.summarize_targets("search for new articles about cricket", ctx) is None
    assert core.summarize_targets("summarize the top 5 articles", {"last": {}}) is None
