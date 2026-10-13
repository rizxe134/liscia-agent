"""Local bridge for the Chrome side panel: token-authenticated HTTP + Server-Sent Events on 127.0.0.1 only.
  GET  /events?token=T        -> SSE stream: log / step / token / chat / confirm / status / highlight events
  POST /chat     {text}        -> route like the chat app (chat reply or computer task)
  POST /stop                   -> stop current task;  POST /takeover -> stop + hand control to the user
  POST /confirm  {id, ok}      -> answer a confirmation prompt shown in the panel
Every request needs header  X-PCA-Token: T  (or ?token=T for EventSource). The token lives in ~/.pc-agent/token."""
import json, os, queue, re, secrets, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ALLOWED_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")

def load_token(path=None):
    if path is None:
        import paths; path = paths.token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path) as f: t = f.read().strip()
        if len(t) >= 32: return t
    t = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: f.write(t)
    return t

class Hub:
    """Fan-out of events to every connected panel + pending confirmations."""
    def __init__(self):
        self.subs, self.lock, self.pending = [], threading.Lock(), {}
    def emit(self, kind, **data):
        msg = json.dumps({"type": kind, "t": time.time(), **data})
        with self.lock:
            for q in list(self.subs): q.put(msg)
    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock: self.subs.append(q)
        return q
    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs: self.subs.remove(q)
    def confirm(self, msg, timeout=90):
        """Block the agent thread until the panel answers. No panel / timeout -> deny."""
        if not self.subs: return False
        cid, ev = secrets.token_hex(6), threading.Event()
        self.pending[cid] = [ev, False]
        self.emit("confirm", id=cid, message=msg)
        ev.wait(timeout); ok = self.pending.pop(cid, [None, False])[1]
        self.emit("confirm_done", id=cid, ok=ok); return ok
    def answer(self, cid, ok):
        p = self.pending.get(cid)
        if not p: return False
        p[1] = bool(ok); p[0].set(); return True

BRIDGE = None  # the running bridge (so the chat app can mirror its narration to the panel)

STEP_RE = re.compile(r"^\[(\d+|fast)\]\s+(\w+)\s*(.*)$")

class Bridge:
    def __init__(self, cfg, token=None, agent_factory=None, router=None):
        self.cfg, self.hub, self.token = cfg, Hub(), token or load_token()
        self.history, self.busy, self.agent = [], False, None
        self.agent_factory, self.router = agent_factory, router
        self.lock = threading.Lock()
        import extlink
        self.link = extlink.LINK
        global BRIDGE; BRIDGE = self

    def log(self, line):
        line = str(line); m = STEP_RE.match(line)
        if m:
            self.hub.emit("step", n=m.group(1), action=m.group(2), detail=m.group(3)[:300])
            hl = re.search(r'"x":\s*(-?\d+),\s*"y":\s*(-?\d+)', m.group(3))
            if hl and m.group(2) in ("click", "double_click", "right_click", "move"):
                self.hub.emit("highlight", note="vision click (model coords)")
        else:
            self.hub.emit("log", text=line[:2000])

    def _get_agent(self):
        if self.agent is None:
            if self.agent_factory: self.agent = self.agent_factory(self)
            else:
                from core import Agent
                self.agent = Agent(self.cfg, confirm=self.hub.confirm, log=self.log)
                self.agent.on_highlight = lambda **k: self.hub.emit("highlight", **k)
        return self.agent

    def chat(self, text):
        with self.lock:
            if self.busy: return False
            self.busy = True
        threading.Thread(target=self._chat, args=(text,), daemon=True).start(); return True

    def _chat(self, text):
        import slash
        if slash.is_local(text):  # slash commands never reach the model; the key is only shown in the app itself
            cmd = text.strip().split()[0].lower()
            self.hub.emit("chat", text=slash.HELP if cmd in ("/help", "/?", "/commands")
                          else "For safety the key is only shown in the Liscia Agent app: type /token there.")
            self.hub.emit("status", state="idle"); return
        try:
            self.hub.emit("status", state="thinking")
            ag = self._get_agent()
            route = self.router or __import__("core").route
            kind, out = route(ag.client, text, self.history, on_token=lambda p: self.hub.emit("token", text=p))
            self.history += [{"role": "user", "content": text}]
            if kind == "chat":
                self.history.append({"role": "assistant", "content": out}); self.hub.emit("chat", text=out)
            else:
                self.hub.emit("task", text=out); self.hub.emit("status", state="working")
                ag.kill.event.clear()
                res = ag.run(out)
                self.history.append({"role": "assistant", "content": f"(computer task) {res}"})
                self.hub.emit("result", text=res)
        except Exception as e:
            self.hub.emit("error", text=f"{type(e).__name__}: {e}")
        finally:
            self.busy = False; self.history = self.history[-20:]; self.hub.emit("status", state="ready")

    def stop(self, takeover=False):
        if self.agent: self.agent.kill.event.set()
        for cid in list(self.hub.pending): self.hub.answer(cid, False)
        self.hub.emit("takeover" if takeover else "stopped",
                      text="You're in control. Send a message when you want me to continue." if takeover else "Stop requested.")

def make_handler(bridge):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def _cors(self):
            o = self.headers.get("Origin", "")
            if ALLOWED_ORIGIN.match(o):
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Access-Control-Allow-Headers", "X-PCA-Token, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        def _ok_origin(self):
            o = self.headers.get("Origin")
            return o is None or bool(ALLOWED_ORIGIN.match(o))  # block ordinary web pages
        def _authed(self, qs=None):
            t = self.headers.get("X-PCA-Token") or ((qs or {}).get("token") or [""])[0]
            return self._ok_origin() and secrets.compare_digest(t, bridge.token)
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code); self._cors()
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_OPTIONS(self):
            self.send_response(204 if self._ok_origin() else 403); self._cors()
            self.send_header("Content-Length", "0"); self.end_headers()
        def do_GET(self):
            u = urlparse(self.path); qs = parse_qs(u.query)
            if not self._authed(qs): return self._send(401, {"error": "bad token"})
            if u.path == "/health":
                return self._send(200, {"ok": True, "busy": bridge.busy, "extension_connected": bridge.link.connected(),
                                        "panel_clients": len(bridge.hub.subs)})
            if u.path == "/status":
                return self._send(200, {"ok": True, "busy": bridge.busy, "panel_clients": len(bridge.hub.subs),
                                        "extension": bridge.link.status()})
            if u.path == "/ext/poll":
                info = {k: v[0] for k, v in qs.items() if k in ("version", "ua", "client")}
                hold = min(float((qs.get("hold") or ["20"])[0]), 25.0)
                return self._send(200, {"commands": bridge.link.poll(info, hold=hold)})
            if u.path != "/events": return self._send(404, {"error": "not found"})
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = bridge.hub.subscribe()
            try:
                self.wfile.write(b"data: " + json.dumps({"type": "hello", "busy": bridge.busy}).encode() + b"\n\n"); self.wfile.flush()
                while True:
                    try: msg = q.get(timeout=15)
                    except queue.Empty: self.wfile.write(b": ping\n\n"); self.wfile.flush(); continue
                    self.wfile.write(b"data: " + msg.encode() + b"\n\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                bridge.hub.unsubscribe(q)
        def do_POST(self):
            if not self._authed(): return self._send(401, {"error": "bad token"})
            n = min(int(self.headers.get("Content-Length") or 0), 100_000)
            try: data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError: return self._send(400, {"error": "bad json"})
            p = urlparse(self.path).path
            if p == "/chat":
                text = str(data.get("text", "")).strip()
                if not text: return self._send(400, {"error": "empty"})
                return self._send(200, {"accepted": bridge.chat(text), "busy": bridge.busy})
            if p == "/ext/result": return self._send(200, {"ok": bridge.link.result(data)})
            if p == "/ext/event":
                bridge.link.event(data); return self._send(200, {"ok": True})
            if p == "/stop": bridge.stop(); return self._send(200, {"ok": True})
            if p == "/takeover": bridge.stop(takeover=True); return self._send(200, {"ok": True})
            if p == "/confirm": return self._send(200, {"ok": bridge.hub.answer(str(data.get("id")), data.get("ok") is True)})
            return self._send(404, {"error": "not found"})
    return H

def serve(cfg, port=None, bridge=None, background=True):
    port = port or cfg.get("panel", {}).get("port", 8765)
    bridge = bridge or Bridge(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(bridge)); srv.daemon_threads = True
    if background: threading.Thread(target=srv.serve_forever, daemon=True).start()
    else: srv.serve_forever()
    return srv, bridge
