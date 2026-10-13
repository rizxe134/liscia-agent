"""Bidirectional control channel to the Chrome extension (long-poll over the localhost bridge).
The extension's service worker calls  GET /ext/poll  (held up to ~20 s) to receive commands,
POST /ext/result  with {id, ok, result|error}, and  POST /ext/event  for page-change events."""
import itertools, queue, threading, time

POLL_HOLD_S = 20.0
CONNECTED_WINDOW_S = 45.0  # a client that polled within this window counts as connected

class ExtError(RuntimeError):
    pass

class ExtensionLink:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.cmds = queue.Queue()
        self.pending = {}            # id -> [Event, response]
        self.ids = itertools.count(1)
        self.last_poll = 0.0
        self.info = {}               # version, user agent ... sent by the extension
        self.events = []             # recent page events (bounded)
        self.lock = threading.Lock()
        self.on_event = None

    # ---- agent side ----
    def connected(self):
        return self.clock() - self.last_poll < CONNECTED_WINDOW_S

    def call(self, cmd, timeout=20.0, **args):
        """Send one command and wait for the extension's result. Raises ExtError."""
        if not self.connected():
            raise ExtError("Chrome extension not connected")
        cid = next(self.ids); ev = threading.Event()
        self.pending[cid] = [ev, None]
        self.cmds.put({"id": cid, "cmd": cmd, "args": args})
        if not ev.wait(timeout):
            self.pending.pop(cid, None)
            raise ExtError(f"extension did not answer '{cmd}' within {timeout:.0f}s")
        res = self.pending.pop(cid)[1] or {}
        if not res.get("ok"):
            raise ExtError(str(res.get("error") or f"{cmd} failed"))
        return res.get("result")

    # ---- HTTP side ----
    def poll(self, info=None, hold=POLL_HOLD_S):
        """Return a list of commands (possibly empty after `hold` seconds)."""
        self.last_poll = self.clock()
        if info: self.info.update(info)
        out = []
        try:
            out.append(self.cmds.get(timeout=hold))
            while True: out.append(self.cmds.get_nowait())
        except queue.Empty:
            pass
        self.last_poll = self.clock()
        return out

    def result(self, data):
        p = self.pending.get(int(data.get("id", -1)))
        if not p: return False
        p[1] = data; p[0].set(); return True

    def event(self, data):
        with self.lock:
            self.events = (self.events + [dict(data, t=self.clock())])[-50:]
        if self.on_event:
            try: self.on_event(data)
            except Exception: pass

    def status(self):
        return {"connected": self.connected(),
                "last_poll_s_ago": round(self.clock() - self.last_poll, 1) if self.last_poll else None,
                "extension": self.info, "queued": self.cmds.qsize(), "pending": len(self.pending),
                "last_event": self.events[-1] if self.events else None}

LINK = ExtensionLink()  # one per process: shared by the chat app's agent and the panel's agent
