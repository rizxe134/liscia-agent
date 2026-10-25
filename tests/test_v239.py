import unittest, webagent

def test_truncated_snippets_cut():
    c = webagent.clean_headline
    assert c("India's RBI governor reiterates listing requirement for top NBFCs as focus intensifies on Ta", "Reuters").endswith("intensifies")
    assert c("India news: Neha Bora refuses to sign peace bond, cites right to democratic dissent Neha Bora", "DW").endswith("dissent")
    assert c("Indian physicist wins Oskar Klein medal, one of the top prizes in physics Known f", "Indian Express").endswith("physics")
    o = webagent.outlet_of("https://irishgolfer.ie/x")
    assert o == "Irish Golfer" and c("Irish Golfer Magazine Byrne slips back but still has a top 10 in her sights in India Sara Byrne's ch", o).startswith("Byrne slips")


class _Wrapped(unittest.TestCase):
    pass

def _mk(fn):
    def t(self):
        import inspect, pathlib, tempfile
        if "tmp_path" in inspect.signature(fn).parameters:
            with tempfile.TemporaryDirectory() as d: fn(pathlib.Path(d))
        else: fn()
    return t

for _n, _f in list(globals().items()):
    if _n.startswith("test_") and callable(_f): setattr(_Wrapped, _n, _mk(_f)); del globals()[_n]
