"""Retro green-on-black chat app (Tkinter, no extra deps)."""
import threading, queue, tkinter as tk
from core import Agent, route

BG, FG, DIM, USER, WARN = "#000000", "#00ff66", "#00994d", "#b3ffcc", "#ffcc00"
FONT = ("Consolas", 11)

def pick_font(root):
    """Use the first installed monospace font (Consolas on Windows)."""
    global FONT
    from tkinter import font as tkfont
    fams = set(tkfont.families(root))
    for f in ("SF Mono", "Menlo", "Monaco", "Consolas", "Cascadia Mono", "Lucida Console", "IBM Plex Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New"):
        if f in fams:
            FONT = (f, 11); return
    FONT = ("TkFixedFont", 11)
SPIN = ["[=     ]", "[ =    ]", "[  =   ]", "[   =  ]", "[    = ]", "[     =]", "[    = ]", "[   =  ]", "[  =   ]", "[ =    ]"]

def retro_confirm(root, msg):
    """Modal yes/no dialog styled like the terminal. Returns bool."""
    win = tk.Toplevel(root, bg=BG, highlightbackground=FG, highlightthickness=2)
    win.title("CONFIRM"); win.attributes("-topmost", True); win.transient(root)
    tk.Label(win, text="!! CONFIRM ACTION !!", fg=WARN, bg=BG, font=FONT + ("bold",)).pack(padx=12, pady=(10, 4))
    tk.Label(win, text=msg, fg=FG, bg=BG, font=FONT, wraplength=460, justify="left").pack(padx=12, pady=4)
    res = {"ok": False}
    def done(v): res["ok"] = v; win.destroy()
    bar = tk.Frame(win, bg=BG); bar.pack(pady=10)
    for txt, v in (("[ Y ] ALLOW", True), ("[ N ] DENY", False)):
        tk.Button(bar, text=txt, command=lambda v=v: done(v), fg=FG, bg=BG, activebackground=FG,
                  activeforeground=BG, font=FONT, relief="flat", highlightbackground=FG,
                  highlightthickness=1).pack(side="left", padx=8)
    win.bind("y", lambda e: done(True)); win.bind("n", lambda e: done(False)); win.bind("<Escape>", lambda e: done(False))
    win.grab_set(); win.focus_force(); root.wait_window(win)
    return res["ok"]

class ChatApp:
    def __init__(self, cfg, root=None):
        self.cfg = cfg; self.q = queue.Queue(); self.busy = False; self.agent = None
        self.history = []; self.spin_i = 0; self.status_text = "READY"; self.live = ""
        r = self.root = root or tk.Tk()
        pick_font(r)
        r.title("LISCIA AGENT"); r.configure(bg=BG); r.geometry("760x520")
        top = tk.Frame(r, bg=BG); top.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(top, text=f"> LISCIA AGENT // {cfg['ollama']['model']}", fg=FG, bg=BG, font=FONT + ("bold",)).pack(side="left")
        self.stop_btn = tk.Button(top, text="[ STOP ]", command=self.stop, fg=WARN, bg=BG, font=FONT,
                                  relief="flat", activebackground=WARN, activeforeground=BG, state="disabled")
        self.stop_btn.pack(side="right")
        self.log = tk.Text(r, bg=BG, fg=FG, font=FONT, wrap="word", relief="flat", insertbackground=FG,
                           highlightthickness=1, highlightbackground=DIM, padx=8, pady=6, height=10)
        for tag, col in (("user", USER), ("agent", FG), ("step", DIM), ("warn", WARN), ("sys", DIM)):
            self.log.tag_config(tag, foreground=col)
        self.log.config(state="disabled")
        self.status = tk.Label(r, text="", fg=DIM, bg=BG, font=FONT, anchor="w"); self.status.pack(fill="x", padx=8)
        bottom = tk.Frame(r, bg=BG); bottom.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(bottom, text="$>", fg=FG, bg=BG, font=FONT + ("bold",)).pack(side="left")
        self.entry = tk.Entry(bottom, bg=BG, fg=FG, font=FONT, relief="flat", insertbackground=FG,
                              insertwidth=9, insertontime=500, insertofftime=500,  # blinking block cursor
                              highlightthickness=1, highlightbackground=DIM, highlightcolor=FG)
        self.entry.pack(side="left", fill="x", expand=True, padx=6, ipady=4)
        self.entry.bind("<Return>", lambda e: self.send()); self.entry.focus_set()
        self.log.pack(fill="both", expand=True, padx=8, pady=6, before=self.status)  # packed last so input row always shows
        r.bind("<F12>", lambda e: self.stop()); r.bind("<Command-period>", lambda e: self.stop())
        self.write("sys", "SYSTEM READY. Chat normally, or ask me to do something on your PC.\n"
                          "Tips: '/do <task>' forces computer control, '/chat <msg>' forces plain chat.\n"
                          "Abort a task: STOP button, Esc/F12, or slam the mouse into a screen corner.\n")
        self._tick()
        threading.Thread(target=self._preload, daemon=True).start()

    def _ask(self, msg):
        ev, box = threading.Event(), {}
        self.q.put(("confirm", (msg, ev, box))); ev.wait(); return box.get("ok", False)

    def setup_models(self, ask=None, sleep=None):
        """First-launch check: Ollama running? models pulled? Offer to pull with progress in the chat. Returns True if ready."""
        import llm, time as _t
        ask, sleep = ask or self._ask, sleep or _t.sleep
        o = self.cfg["ollama"]; client = llm.OllamaClient(o["host"], o["model"])
        installed = client.check()
        if installed is None:
            self.q.put(("sys", "Ollama isn't running - trying to start it..."))
            if llm.start_ollama():
                for _ in range(20):
                    sleep(1); installed = client.check()
                    if installed is not None: break
        if installed is None:
            self.q.put(("warn", "Ollama not found. Install it from https://ollama.com/download, open it, then restart Liscia Agent."))
            return False
        need = llm.missing_models(installed, [o.get("model"), o.get("text_model")])
        if not need: return True
        if not ask("Liscia Agent needs these local models (a few GB, one-time download):\n  " + "\n  ".join(need) + "\n\nDownload them now?"):
            self.q.put(("warn", "Models missing: " + ", ".join(need) + ". Run `ollama pull <name>` or restart Liscia Agent to be asked again."))
            return False
        for name in need:
            self.q.put(("sys", f"downloading {name} ...")); self.q.put(("busy", True)); last = [-10]
            def prog(status, done, total, name=name):
                if total:
                    pct = int(done * 100 / total)
                    self.q.put(("status", f"pulling {name} {pct:3d}% {done/1e9:.1f}/{total/1e9:.1f} GB"))
                    if pct >= last[0] + 10: last[0] = pct - pct % 10; self.q.put(("step", f"{name}: {last[0]}%"))
                else:
                    self.q.put(("status", f"pulling {name}: {status}"))
            try:
                llm.pull_model(o["host"], name, prog); self.q.put(("sys", f"{name} ready."))
            except Exception as e:
                self.q.put(("warn", f"download of {name} failed: {e}")); self.q.put(("end", None)); return False
        self.q.put(("end", None)); return True

    def _preload(self):
        """Warm up the models in the background so the first message is fast."""
        if self.cfg.get("setup_check", True):
            try:
                if not self.setup_models(): return
            except Exception as e:
                self.q.put(("warn", f"setup check failed: {e}"))
        try:
            from llm import OllamaClient
            o = self.cfg["ollama"]
            OllamaClient(o["host"], o["model"], text_model=o.get("text_model", ""), keep_alive=o.get("keep_alive", "30m"), num_ctx=o.get("num_ctx")).preload()
            self.q.put(("sys", "(models loaded and warm)"))
        except Exception as e:
            self.q.put(("warn", f"could not preload models: {e}"))

    def write(self, tag, text):
        prefix = {"user": "YOU   > ", "agent": "AGENT > ", "step": "   ::  ", "warn": "  !!   ", "sys": ""}[tag]
        self.log.config(state="normal"); self.log.insert("end", prefix + text + "\n", tag)
        self.log.see("end"); self.log.config(state="disabled")

    def _tick(self):
        while not self.q.empty():
            kind, val = self.q.get()
            if kind == "confirm":
                msg, ev, box = val; box["ok"] = retro_confirm(self.root, msg); ev.set()
            elif kind == "status": self.status_text = val; self.live = ""
            elif kind == "live": self.live = (self.live + val)[-90:]
            elif kind == "stream_start":
                self.log.config(state="normal"); self.log.insert("end", "AGENT > ", "agent"); self.log.config(state="disabled")
            elif kind == "stream":
                self.log.config(state="normal"); self.log.insert("end", val, "agent"); self.log.see("end"); self.log.config(state="disabled")
            elif kind == "stream_end":
                self.log.config(state="normal"); self.log.insert("end", "\n"); self.log.config(state="disabled")
            elif kind == "end": self._set_busy(False)
            elif kind == "busy": self._set_busy(True)
            else: self.write(kind, val)
        if self.busy:
            self.spin_i += 1
            dots = "." * (self.spin_i // 3 % 4)
            live = " ".join(self.live.split())
            self.status.config(text=f"{SPIN[self.spin_i % len(SPIN)]} {self.status_text}{dots}" + (f"  {live[-60:]}" if live else ""), fg=FG)
        else:
            self.status.config(text="READY _" if self.spin_i // 5 % 2 == 0 else "READY", fg=DIM); self.spin_i += 1
        self.root.after(100, self._tick)

    def _set_busy(self, b):
        self.busy = b
        self.stop_btn.config(state="normal" if b else "disabled")
        self.entry.config(state="disabled" if b else "normal")
        if not b: self.entry.focus_set()

    def _log(self, msg):
        tag = "step" if msg.startswith("[") else ("warn" if "stop" in msg.lower() else "step")
        self.q.put((tag, msg))
    def _confirm(self, msg):
        ev, box = threading.Event(), {}
        self.q.put(("confirm", (msg, ev, box))); ev.wait(); return box.get("ok", False)

    def send(self):
        text = self.entry.get().strip()
        if not text or self.busy: return
        self.entry.delete(0, "end"); self.write("user", text); self._set_busy(True)
        self.q.put(("status", "thinking"))
        threading.Thread(target=self._work, args=(text,), daemon=True).start()

    def _work(self, text):
        try:
            self.agent = Agent(self.cfg, confirm=self._confirm, log=self._log)
            self.agent.on_token = lambda p: self.q.put(("live", p))
            started = []
            def stream(p):
                if not started: started.append(1); self.q.put(("stream_start", None))
                self.q.put(("stream", p))
            kind, out = route(self.agent.client, text, self.history, on_token=stream)
            self.history.append({"role": "user", "content": text})
            if kind == "chat":
                if started: self.q.put(("stream_end", None))
                else: self.q.put(("agent", out))
                self.history.append({"role": "assistant", "content": out})
            else:
                self.q.put(("agent", f"On it -> {out}")); self.q.put(("status", "working on your PC"))
                result = self.agent.run(out)
                self.q.put(("agent", f"Task finished: {result}"))
                self.history.append({"role": "assistant", "content": f"(did task: {out}; result: {result})"})
        except Exception as e:
            self.q.put(("warn", f"Error: {e}  (is Ollama running? `ollama serve`)"))
        self.q.put(("end", None))

    def stop(self):
        if self.agent: self.agent.kill.event.set(); self.q.put(("warn", "Stop requested."))

def launch(cfg):
    if cfg.get("panel", {}).get("enabled", True):
        try:
            import server; server.serve(cfg)
            print(f"[panel] side-panel bridge on http://127.0.0.1:{cfg.get('panel', {}).get('port', 8765)} (token: {__import__('paths').token_path()})")
        except Exception as e:
            print(f"[panel] bridge not started: {e}")
    ChatApp(cfg).root.mainloop()
