"""3.0.0 UI pieces: bot list with robots, bot editor, trash, Settings > CONNECTIONS and Settings > MCP."""
import json, shlex, threading, tkinter as tk
import bots, robot

def U():
    import ui; return ui

def scrollable(parent):
    """A vertically scrollable frame (canvas + inner frame). Returns (outer, inner)."""
    u = U()
    outer = tk.Frame(parent, bg=u.BG)
    cv = tk.Canvas(outer, bg=u.BG, highlightthickness=0, bd=0)
    sb = tk.Scrollbar(outer, orient="vertical", command=cv.yview, width=10, troughcolor=u.BG, bg=u.LINE, highlightthickness=0, bd=0)
    inner = tk.Frame(cv, bg=u.BG)
    win = cv.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
    cv.configure(yscrollcommand=sb.set); cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
    def wheel(e):
        d = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1
        cv.yview_scroll(d, "units")
    for w in (cv, inner):
        w.bind("<Enter>", lambda e: (cv.bind_all("<MouseWheel>", wheel), cv.bind_all("<Button-4>", wheel), cv.bind_all("<Button-5>", wheel)))
        w.bind("<Leave>", lambda e: (cv.unbind_all("<MouseWheel>"), cv.unbind_all("<Button-4>"), cv.unbind_all("<Button-5>")))
    outer.canvas = cv
    return outer, inner

class BotList:
    """Sidebar list: one row per bot = animated robot + name. on_pick(cid), on_edit(cid)."""
    def __init__(self, parent, on_pick, on_edit):
        u = U()
        self.outer, self.inner = scrollable(parent)
        self.on_pick, self.on_edit = on_pick, on_edit
        self.rows, self.icons, self.ids, self.sel = {}, {}, [], None

    def pack(self, **kw): self.outer.pack(**kw)

    def set(self, items, current, working=None, unread=()):
        u = U()
        for w in self.inner.winfo_children(): w.destroy()
        self.rows, self.icons, self.ids, self.subs, self.descs = {}, {}, [c["id"] for c in items], {}, {}
        self.working_id, self.unread = working, set(unread)
        size = u.FONT[1]; small = (u.FONT[0], max(8, size - 3))
        for c in items:
            b = c.get("bot") or {}
            row = tk.Frame(self.inner, bg=u.BG, cursor="hand2"); row.pack(fill="x", pady=1)
            ic = robot.RobotIcon(row, color=bots.color_hex(b), style=b.get("style", "classic"), size=size, bg=u.BG)
            ic.pack(side="left", padx=(2, 6), pady=2)
            txt = tk.Frame(row, bg=u.BG); txt.pack(side="left", fill="x", expand=True)
            top = tk.Frame(txt, bg=u.BG); top.pack(fill="x")
            lb = tk.Label(top, text=(b.get("name") or c["title"])[:24], fg=u.FG, bg=u.BG, font=u.FONT, anchor="w"); lb.pack(side="left")
            dot = tk.Label(top, text=" \u25cf" if c["id"] in self.unread else "", fg=u.WARN, bg=u.BG, font=small); dot.pack(side="left")
            desc = (b.get("description") or "").strip() or f"{c.get('count', 0)} messages"
            sub = tk.Label(txt, text=desc[:30], fg=u.DIM, bg=u.BG, font=small, anchor="w"); sub.pack(fill="x")
            for w in (row, ic, txt, top, lb, dot, sub):
                w.bind("<Button-1>", lambda e, i=c["id"]: self.on_pick(i))
                w.bind("<Double-Button-1>", lambda e, i=c["id"]: self.on_edit(i))
            self.rows[c["id"]] = (row, [txt, top, lb, dot, sub]); self.icons[c["id"]] = ic; self.subs[c["id"]] = sub; self.descs[c["id"]] = desc[:30]
            if working and c["id"] == working: ic.set_working(True)
        self.select(current)

    def select(self, cid):
        u = U(); self.sel = cid
        self.unread.discard(cid)
        for i, (row, ws) in self.rows.items():
            on = i == cid
            row.configure(bg=u.FG if on else u.BG)
            for w in ws:
                w.configure(bg=u.FG if on else u.BG)
            ws[2].configure(fg=u.BG if on else u.FG); ws[4].configure(fg=u.BG if on else u.DIM)
            if i == cid: ws[3].configure(text="")
            self.icons[i].configure(bg=u.FG if on else u.BG); self.icons[i].draw()

    def working(self, cid, on):
        self.working_id = cid if on else None
        if cid in self.icons:
            try:
                self.icons[cid].set_working(on)
                if not on: self.subs[cid].configure(text=self.descs.get(cid, ""))
            except tk.TclError: pass

    def talking(self, cid, on):
        if cid in self.icons:
            try: self.icons[cid].set_talking(on)
            except tk.TclError: pass

    def tick(self, n):
        """Animated 'working...' status line for the bot that's running."""
        cid = self.working_id
        if cid in self.subs:
            try: self.subs[cid].configure(text="working" + "." * (n // 3 % 4))
            except tk.TclError: pass

    def mark_unread(self, cid):
        if cid == self.sel or cid not in self.rows: return
        self.unread.add(cid)
        try: self.rows[cid][1][3].configure(text=" \u25cf")
        except tk.TclError: pass

class BotDialog:
    """Create or edit a bot. result = dict of bot fields (or None if cancelled)."""
    def __init__(self, app, bot=None, new=False):
        import providers, connections, mcphub
        u = U(); from tkinter import ttk
        self.app, self.result = app, None
        b = dict(bot or bots.default_bot("My bot"))
        top = self.win = tk.Toplevel(app.root, bg=u.BG, highlightbackground=u.FG, highlightthickness=2)
        top.title("NEW BOT" if new else "EDIT BOT"); top.geometry("620x700"); top.transient(app.root)
        outer, w = scrollable(top); outer.pack(fill="both", expand=True, padx=6, pady=6)
        L = lambda t, fg=None: tk.Label(w, text=t, fg=fg or u.FG, bg=u.BG, font=u.FONT, anchor="w", justify="left", wraplength=560)
        L("> NEW BOT" if new else "> EDIT BOT").pack(fill="x", padx=10, pady=(8, 4))
        if new:
            L("START FROM A TEMPLATE").pack(fill="x", padx=10)
            tr = tk.Frame(w, bg=u.BG); tr.pack(fill="x", padx=10, pady=(0, 6))
            for name in bots.TEMPLATES:
                u.btn(tr, f"[ {name} ]", lambda n=name: self.template(n)).pack(side="left", padx=(0, 4))
        L("NAME").pack(fill="x", padx=10)
        self.name = tk.Entry(w, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", highlightthickness=1, highlightbackground=u.LINE)
        self.name.insert(0, b.get("name", "")); self.name.pack(fill="x", padx=10, pady=(0, 6))
        L("SHORT DESCRIPTION  (shown under the name)").pack(fill="x", padx=10)
        self.desc = tk.Entry(w, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", highlightthickness=1, highlightbackground=u.LINE)
        self.desc.insert(0, b.get("description", "")); self.desc.pack(fill="x", padx=10, pady=(0, 6))
        L("ROBOT").pack(fill="x", padx=10)
        pr = tk.Frame(w, bg=u.BG); pr.pack(fill="x", padx=10)
        self.preview = robot.RobotIcon(pr, color=bots.color_hex(b), style=b.get("style", "classic"), size=max(20, u.FONT[1] * 2), bg=u.BG)
        self.preview.pack(side="left", padx=(0, 10))
        right = tk.Frame(pr, bg=u.BG); right.pack(side="left", fill="x")
        self.color = tk.StringVar(value=b.get("color", "green")); self.style = tk.StringVar(value=b.get("style", "classic"))
        cr = tk.Frame(right, bg=u.BG); cr.pack(anchor="w")
        for cname, hexv in bots.COLORS.items():
            sw = tk.Radiobutton(cr, text="\u25a0", value=cname, variable=self.color, command=self.repaint, fg=hexv, bg=u.BG, selectcolor=u.BG,
                                activebackground=u.BG, activeforeground=hexv, font=u.FONT, highlightthickness=0, indicatoron=True)
            sw.pack(side="left"); sw._fixed = True
        sr = tk.Frame(right, bg=u.BG); sr.pack(anchor="w")
        for st in bots.STYLES:
            tk.Radiobutton(sr, text=st, value=st, variable=self.style, command=self.repaint, fg=u.FG, bg=u.BG, selectcolor=u.BG,
                           activebackground=u.BG, activeforeground=u.FG, font=u.FONT, highlightthickness=0).pack(side="left", padx=(0, 6))
        L("INSTRUCTIONS / PERSONA  (how this bot should behave)").pack(fill="x", padx=10, pady=(8, 0))
        self.instr = tk.Text(w, height=5, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", wrap="word",
                             highlightthickness=1, highlightbackground=u.LINE)
        self.instr.insert("1.0", b.get("instructions", "")); self.instr.pack(fill="x", padx=10)
        L("MODEL  (empty = the global one from Settings)").pack(fill="x", padx=10, pady=(8, 0))
        mr = tk.Frame(w, bg=u.BG); mr.pack(fill="x", padx=10)
        self.prov = ttk.Combobox(mr, values=["(global)"] + list(providers.NAMES), state="readonly", style="R.TCombobox", font=u.FONT, width=14)
        self.prov.set(b.get("provider") or "(global)"); self.prov.pack(side="left")
        self.model = tk.Entry(mr, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", highlightthickness=1, highlightbackground=u.LINE)
        self.model.insert(0, b.get("model", "")); self.model.pack(side="left", fill="x", expand=True, padx=6)
        L("APP CONNECTIONS this bot may use").pack(fill="x", padx=10, pady=(8, 0))
        conns = b.get("connections") or []
        self.conn_all = tk.BooleanVar(value="*" in conns); self.conn_vars = {}
        cb = lambda parent, text, var: tk.Checkbutton(parent, text=text, variable=var, fg=u.FG, bg=u.BG, selectcolor=u.BG, activebackground=u.BG,
                                                     activeforeground=u.FG, font=u.FONT, highlightthickness=0, anchor="w")
        cb(w, "all connected apps", self.conn_all).pack(fill="x", padx=10)
        for pid, p in connections.PROVIDERS.items():
            st = connections.status(app.cfg, pid)
            v = tk.BooleanVar(value=pid in conns); self.conn_vars[pid] = v
            cb(w, f"   {p['name']}" + ("" if st["connected"] else "   (not connected)"), v).pack(fill="x", padx=10)
        L("MCP SERVERS this bot may use").pack(fill="x", padx=10, pady=(8, 0))
        mcps = b.get("mcp") or []
        self.mcp_all = tk.BooleanVar(value="*" in mcps); self.mcp_vars = {}
        cb(w, "all enabled MCP servers", self.mcp_all).pack(fill="x", padx=10)
        for s in mcphub.servers(app.cfg):
            v = tk.BooleanVar(value=s["name"] in mcps); self.mcp_vars[s["name"]] = v
            cb(w, f"   {s['name']}  ({len(s.get('cached') or [])} tools)", v).pack(fill="x", padx=10)
        L("MEMORY  (one note per line; the bot can also save notes itself: 'remember that ...')").pack(fill="x", padx=10, pady=(8, 0))
        self.mem = tk.Text(w, height=4, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", wrap="word",
                           highlightthickness=1, highlightbackground=u.LINE)
        self.mem.insert("1.0", "\n".join(b.get("memory") or [])); self.mem.pack(fill="x", padx=10)
        bar = tk.Frame(top, bg=u.BG); bar.pack(pady=8)
        u.btn(bar, "[ CREATE BOT ]" if new else "[ SAVE ]", self.ok).pack(side="left", padx=6)
        u.btn(bar, "[ CANCEL ]", top.destroy).pack(side="left", padx=6)
        top.bind("<Escape>", lambda e: top.destroy())
        self.name.focus_set(); self.name.select_range(0, "end")

    def template(self, n):
        t = bots.default_bot(n, n)
        self.name.delete(0, "end"); self.name.insert(0, n); self.desc.delete(0, "end"); self.desc.insert(0, t.get("description", "")); self.color.set(t["color"]); self.style.set(t["style"])
        self.instr.delete("1.0", "end"); self.instr.insert("1.0", t["instructions"])
        self.conn_all.set("*" in t["connections"])
        for pid, v in self.conn_vars.items(): v.set(pid in t["connections"])
        self.repaint()

    def repaint(self):
        self.preview.color = bots.COLORS.get(self.color.get(), "#3dff8f"); self.preview.style = self.style.get(); self.preview.draw()

    def ok(self):
        name = self.name.get().strip()[:40]
        if not name: self.name.configure(highlightbackground=U().WARN); return
        conns = ["*"] if self.conn_all.get() else [k for k, v in self.conn_vars.items() if v.get()]
        mcps = ["*"] if self.mcp_all.get() else [k for k, v in self.mcp_vars.items() if v.get()]
        prov = self.prov.get(); prov = "" if prov == "(global)" else prov
        self.result = {"name": name, "description": self.desc.get().strip()[:60], "color": self.color.get(), "style": self.style.get(), "instructions": self.instr.get("1.0", "end").strip(),
                       "provider": prov, "model": self.model.get().strip(), "connections": conns, "mcp": mcps,
                       "memory": [x.strip() for x in self.mem.get("1.0", "end").splitlines() if x.strip()]}
        self.win.destroy()

def trash_dialog(app):
    u = U(); items = app.store.trash()
    top = tk.Toplevel(app.root, bg=u.BG, highlightbackground=u.FG, highlightthickness=2); top.title("TRASH"); top.transient(app.root)
    tk.Label(top, text="> DELETED BOTS  (kept 30 days)", fg=u.FG, bg=u.BG, font=u.FONT).pack(fill="x", padx=12, pady=(10, 4))
    if not items: tk.Label(top, text="Trash is empty.", fg=u.DIM, bg=u.BG, font=u.FONT).pack(padx=12, pady=8)
    for it in items:
        row = tk.Frame(top, bg=u.BG); row.pack(fill="x", padx=12, pady=2)
        tk.Label(row, text=f"{it['name'][:30]:<30}  {it['days_left']}d left", fg=u.FG, bg=u.BG, font=u.FONT).pack(side="left")
        def rest(i=it["id"]):
            app.store.restore(i); top.destroy(); app.refresh_chats(); app.write("sys", "Bot restored.")
        u.btn(row, "[ RESTORE ]", rest).pack(side="right")
    u.btn(top, "[ CLOSE ]", top.destroy).pack(pady=10)

def howto(parent, title, text):
    """A '▸ How to ...' dropdown: click to show/hide the steps."""
    u = U()
    box = tk.Frame(parent, bg=u.BG); hdr = tk.Label(box, text="\u25b8 " + title, fg=u.DIM, bg=u.BG, font=u.FONT, anchor="w", cursor="hand2")
    body = tk.Label(box, text=text, fg=u.STEP, bg=u.BG, font=u.FONT, anchor="w", justify="left", wraplength=600)
    hdr.pack(fill="x")
    def tog(e=None):
        if body.winfo_ismapped(): body.pack_forget(); hdr.config(text="\u25b8 " + title)
        else: body.pack(fill="x", padx=12); hdr.config(text="\u25be " + title)
    hdr.bind("<Button-1>", tog); box.toggle = tog; return box

class ConnectionsTab:
    def __init__(self, sw, parent):
        import connections
        u = U(); self.sw, self.cfg = sw, sw.cfg
        outer, w = scrollable(parent); outer.pack(fill="both", expand=True)
        tk.Label(w, text="> CONNECTIONS  - let bots use your apps. Tokens stay in the OS keychain. Anything that creates, changes or "
                         "sends asks you first (emails are only drafted).", fg=u.FG, bg=u.BG, font=u.FONT, anchor="w", justify="left",
                 wraplength=640).pack(fill="x", padx=12, pady=(10, 6))
        self.state = {}
        for pid, p in connections.PROVIDERS.items():
            fr = tk.Frame(w, bg=u.BG, highlightthickness=1, highlightbackground=u.LINE); fr.pack(fill="x", padx=12, pady=4)
            top = tk.Frame(fr, bg=u.BG); top.pack(fill="x", padx=6, pady=(4, 2))
            tk.Label(top, text=p["name"], fg=u.FG, bg=u.BG, font=u.FONT + ("bold",), anchor="w").pack(side="left")
            stl = tk.Label(top, text="", fg=u.DIM, bg=u.BG, font=u.FONT); stl.pack(side="right"); self.state[pid] = stl
            row = tk.Frame(fr, bg=u.BG); row.pack(fill="x", padx=6, pady=2)
            E = lambda width=22, show=None: tk.Entry(row, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", width=width, show=show,
                                                     highlightthickness=1, highlightbackground=u.LINE)
            if p["kind"] == "oauth":
                tk.Label(row, text="client id", fg=u.DIM, bg=u.BG, font=u.FONT).pack(side="left")
                cid = E(); cid.pack(side="left", padx=4); sec = None
                if p.get("secret"):
                    tk.Label(row, text="secret", fg=u.DIM, bg=u.BG, font=u.FONT).pack(side="left"); sec = E(12, "\u2022"); sec.pack(side="left", padx=4)
                r2 = tk.Frame(fr, bg=u.BG); r2.pack(fill="x", padx=6, pady=2)
                u.btn(r2, "[ SAVE CLIENT ]", lambda pid=pid, cid=cid, sec=sec: self.save_client(pid, cid, sec)).pack(side="left")
                u.btn(r2, "[ CONNECT ]", lambda pid=pid: self.connect(pid)).pack(side="left", padx=4)
                u.btn(r2, "[ DISCONNECT ]", lambda pid=pid: self.disconnect(pid), fg=u.WARN).pack(side="left")
            else:
                tk.Label(row, text="token", fg=u.DIM, bg=u.BG, font=u.FONT).pack(side="left")
                tok = E(30, "\u2022"); tok.pack(side="left", padx=4)
                r2 = tk.Frame(fr, bg=u.BG); r2.pack(fill="x", padx=6, pady=2)
                u.btn(r2, "[ SAVE TOKEN ]", lambda pid=pid, tok=tok: self.save_token(pid, tok)).pack(side="left")
                u.btn(r2, "[ DISCONNECT ]", lambda pid=pid: self.disconnect(pid), fg=u.WARN).pack(side="left", padx=4)
            howto(fr, "How to set up", connections.HOWTO[pid]).pack(fill="x", padx=6, pady=(0, 4))
        self.msg = tk.Label(w, text="", fg=u.DIM, bg=u.BG, font=u.FONT, anchor="w", justify="left", wraplength=640); self.msg.pack(fill="x", padx=12, pady=6)
        self.refresh()

    def refresh(self):
        import connections
        u = U()
        for pid, lbl in self.state.items():
            st = connections.status(self.cfg, pid)
            lbl.config(text=("\u25cf connected" + (f" ({st['account']})" if st["account"] else "")) if st["connected"]
                       else ("client saved - press CONNECT" if st["has_client"] else "not connected"), fg=u.FG if st["connected"] else u.DIM)

    def say(self, t, warn=False): self.msg.config(text=t, fg=U().WARN if warn else U().FG)

    def save_client(self, pid, cid, sec):
        import connections
        v = cid.get().strip()
        if not v: self.say("Paste the client ID first (see How to set up).", True); return
        try:
            connections.save_client(pid, v, sec.get() if sec else ""); connections.mark(self.cfg, pid, has_client=True)
            cid.delete(0, "end"); sec and sec.delete(0, "end"); self.say("Client saved in the keychain. Now press CONNECT.")
        except Exception as e: self.say(f"couldn't save: {e}", True)
        self.refresh()

    def connect(self, pid):
        import connections
        def done(ok, m): self.sw.ui(lambda: (self.say(m, not ok), self.refresh()))
        try:
            connections.start_oauth(self.cfg, pid, done=done)
            self.say("Your browser opened the sign-in page. Approve access there; this updates when it's done (5 min limit).")
        except Exception as e: self.say(str(e), True)

    def save_token(self, pid, tok):
        import connections
        v = tok.get().strip()
        if not v: self.say("Paste the token first.", True); return
        tok.delete(0, "end"); self.say("checking the token...")
        def work():
            try: acct = connections.save_token(self.cfg, pid, v); self.sw.ui(lambda: (self.say(f"Connected as {acct}."), self.refresh()))
            except Exception as e: self.sw.ui(lambda: (self.say(str(e), True), self.refresh()))
        threading.Thread(target=work, daemon=True).start()

    def disconnect(self, pid):
        import connections
        connections.disconnect(self.cfg, pid); self.say("Disconnected (token removed from the keychain)."); self.refresh()

MCP_HOWTO = """MCP (Model Context Protocol) servers give bots extra tools.
- Try it now: press [ + DEMO SERVER ] then [ TEST ]. It's built in (time, list a folder, system info) and needs nothing else.
- Filesystem example (needs Node.js from nodejs.org): press [ + FILESYSTEM EXAMPLE ]. That fills in
    command: npx    args: -y @modelcontextprotocol/server-filesystem ~/Documents
  Change the folder at the end of args to the one you want to share, SAVE, then TEST.
- Remote servers: transport http (Streamable HTTP) or sse, paste the URL, and put a token in AUTH (stored in the keychain;
  "Bearer xyz" or "Header-Name: value").
- After TEST, tick which tools are allowed. Tools that change things (not marked read-only by the server) ask before running,
  unless you tick "always allow" for that tool. Then just ask a bot, e.g. "use the demo tool to list my Downloads folder"."""

class McpTab:
    def __init__(self, sw, parent):
        import mcphub
        u = U(); from tkinter import ttk
        self.sw, self.cfg = sw, sw.cfg
        outer, w = scrollable(parent); outer.pack(fill="both", expand=True)
        tk.Label(w, text="> MCP SERVERS", fg=u.FG, bg=u.BG, font=u.FONT + ("bold",), anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        howto(w, "How to use MCP (example)", MCP_HOWTO).pack(fill="x", padx=12, pady=(0, 6))
        top = tk.Frame(w, bg=u.BG); top.pack(fill="x", padx=12)
        self.lst = tk.Listbox(top, height=4, bg=u.BG, fg=u.FG, font=u.FONT, relief="flat", highlightthickness=1, highlightbackground=u.LINE,
                              selectbackground=u.FG, selectforeground=u.BG, exportselection=False)
        self.lst.pack(side="left", fill="x", expand=True); self.lst.bind("<<ListboxSelect>>", lambda e: self.load())
        bb = tk.Frame(top, bg=u.BG); bb.pack(side="left", padx=6)
        for t, f in (("[ + NEW ]", self.add_new), ("[ + DEMO SERVER ]", self.add_demo), ("[ + FILESYSTEM EXAMPLE ]", self.add_fs)):
            u.btn(bb, t, f).pack(fill="x", pady=1)
        u.btn(bb, "[ REMOVE ]", self.remove, fg=u.WARN).pack(fill="x", pady=1)
        form = tk.Frame(w, bg=u.BG); form.pack(fill="x", padx=12, pady=6)
        self.f = {}
        def row(label, widget):
            r = tk.Frame(form, bg=u.BG); r.pack(fill="x", pady=1)
            tk.Label(r, text=f"{label:<10}", fg=u.DIM, bg=u.BG, font=u.FONT).pack(side="left"); widget(r).pack(side="left", fill="x", expand=True)
        E = lambda show=None: (lambda r: tk.Entry(r, bg=u.BG, fg=u.FG, font=u.FONT, insertbackground=u.FG, relief="flat", show=show,
                                                  highlightthickness=1, highlightbackground=u.LINE))
        for k in ("name", "command", "args", "env", "url"):
            def mk(r, k=k):
                e = E()(r); self.f[k] = e; return e
            row(k, mk)
        def mkt(r):
            c = ttk.Combobox(r, values=["stdio", "http", "sse"], state="readonly", style="R.TCombobox", font=u.FONT, width=8); self.f["transport"] = c; return c
        row("transport", mkt)
        def mka(r):
            e = E("\u2022")(r); self.f["auth"] = e; return e
        row("auth", mka)
        tk.Label(form, text="env = KEY=value pairs separated by spaces (secret values: put them in auth or leave env empty)", fg=u.DIM, bg=u.BG,
                 font=u.FONT, anchor="w", wraplength=620, justify="left").pack(fill="x")
        self.enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(form, text="enabled", variable=self.enabled, fg=u.FG, bg=u.BG, selectcolor=u.BG, activebackground=u.BG,
                       activeforeground=u.FG, font=u.FONT, highlightthickness=0).pack(anchor="w")
        br = tk.Frame(w, bg=u.BG); br.pack(fill="x", padx=12)
        u.btn(br, "[ SAVE ]", self.save).pack(side="left"); u.btn(br, "[ TEST + LIST TOOLS ]", self.test).pack(side="left", padx=4)
        u.btn(br, "[ VIEW LOG ]", self.view_log).pack(side="left")
        self.msg = tk.Label(w, text="", fg=u.DIM, bg=u.BG, font=u.FONT, anchor="w", justify="left", wraplength=640); self.msg.pack(fill="x", padx=12, pady=4)
        tk.Label(w, text="TOOLS  (enabled / always allow without asking)", fg=u.FG, bg=u.BG, font=u.FONT, anchor="w").pack(fill="x", padx=12)
        self.tools = tk.Frame(w, bg=u.BG); self.tools.pack(fill="x", padx=12, pady=(0, 10))
        self.refresh_list()

    def say(self, t, warn=False): self.msg.config(text=t, fg=U().WARN if warn else U().FG)

    def refresh_list(self, select=None):
        import mcphub
        self.lst.delete(0, "end")
        for s in mcphub.servers(self.cfg):
            dot = "\u25cf" if s.get("enabled", True) else "\u25cb"
            self.lst.insert("end", f" {dot} {s['name']}  [{s.get('transport', 'stdio')}]  {len(s.get('cached') or [])} tools")
        names = [s["name"] for s in mcphub.servers(self.cfg)]
        if names:
            i = names.index(select) if select in names else 0
            self.lst.selection_clear(0, "end"); self.lst.selection_set(i); self.load()
        else: self.clear_form()

    def current(self):
        import mcphub
        sel = self.lst.curselection(); lst = mcphub.servers(self.cfg)
        return lst[sel[0]] if sel and sel[0] < len(lst) else None

    def clear_form(self):
        for k, e in self.f.items():
            if k == "transport": e.set("stdio")
            else: e.delete(0, "end")
        for x in self.tools.winfo_children(): x.destroy()

    def load(self):
        s = self.current()
        if not s: return
        self.clear_form()
        self.f["name"].insert(0, s["name"]); self.f["transport"].set(s.get("transport", "stdio"))
        self.f["command"].insert(0, s.get("command", "")); self.f["args"].insert(0, " ".join(shlex.quote(str(a)) for a in s.get("args") or []))
        self.f["env"].insert(0, " ".join(f"{k}={v}" for k, v in (s.get("env") or {}).items())); self.f["url"].insert(0, s.get("url", ""))
        self.enabled.set(s.get("enabled", True)); self.show_tools(s)

    def show_tools(self, s):
        u = U()
        for x in self.tools.winfo_children(): x.destroy()
        if not s.get("cached"):
            tk.Label(self.tools, text="(press TEST + LIST TOOLS)", fg=u.DIM, bg=u.BG, font=u.FONT).pack(anchor="w"); return
        for t in s["cached"]:
            st = s.setdefault("tools", {}).setdefault(t["name"], {"enabled": True, "always_allow": False})
            r = tk.Frame(self.tools, bg=u.BG); r.pack(fill="x")
            ev, av = tk.BooleanVar(value=st.get("enabled", True)), tk.BooleanVar(value=st.get("always_allow", False))
            def upd(st=st, ev=ev, av=av): st["enabled"], st["always_allow"] = bool(ev.get()), bool(av.get()); self.persist()
            for var, txt in ((ev, ""), (av, "")):
                tk.Checkbutton(r, variable=var, command=upd, fg=u.FG, bg=u.BG, selectcolor=u.BG, activebackground=u.BG, highlightthickness=0).pack(side="left")
            tag = "read-only" if t.get("read_only") else "asks first"
            tk.Label(r, text=f"{t['name']}  ({tag})  {t['description'][:70]}", fg=u.FG if t.get("read_only") else u.WARN, bg=u.BG, font=u.FONT,
                     anchor="w").pack(side="left", fill="x")

    def persist(self):
        try:
            import settings; settings.save(self.cfg)
        except Exception as e: self.say(f"couldn't save: {e}", True)

    def add(self, entry):
        import mcphub
        lst = mcphub.servers(self.cfg); base, n = entry["name"], 2
        while any(s["name"] == entry["name"] for s in lst): entry["name"] = f"{base}-{n}"; n += 1
        lst.append(entry); self.persist(); self.refresh_list(entry["name"])

    def add_new(self): self.add({"name": "my-server", "transport": "stdio", "command": "", "args": [], "env": {}, "enabled": True, "tools": {}})
    def add_demo(self): import mcphub; self.add(mcphub.demo_server()); self.say("Demo server added. Press TEST + LIST TOOLS.")
    def add_fs(self):
        import mcphub, copy
        self.add(copy.deepcopy(mcphub.FS_EXAMPLE)); ok, _ = mcphub.resolve_command("npx")
        self.say("Filesystem example added. Edit the folder at the end of args, SAVE, then TEST." if ok else mcphub.missing_hint("npx"), not ok)

    def remove(self):
        import mcphub
        s = self.current()
        if not s or not U().retro_confirm(self.sw.win, f"Remove the MCP server '{s['name']}'?"): return
        mcphub.servers(self.cfg).remove(s); self.persist(); self.refresh_list()

    def save(self):
        import mcphub, keystore
        s = self.current()
        if not s: self.say("Add a server first.", True); return
        old = s["name"]; s["name"] = mcphub.safe_name(self.f["name"].get()) or old
        s["transport"] = self.f["transport"].get() or "stdio"; s["command"] = self.f["command"].get().strip()
        try: s["args"] = shlex.split(self.f["args"].get())
        except ValueError as e: self.say(f"args: {e}", True); return
        env = {}
        for part in shlex.split(self.f["env"].get() or ""):
            if "=" in part: k, v = part.split("=", 1); env[k] = v
        s["env"] = env; s["url"] = self.f["url"].get().strip(); s["enabled"] = bool(self.enabled.get())
        if self.f["auth"].get().strip():
            keystore.set_secret(f"mcp:{mcphub.safe_name(s['name'])}:auth", self.f["auth"].get().strip()); self.f["auth"].delete(0, "end")
        self.persist(); self.refresh_list(s["name"]); self.say("Saved.")

    def test(self):
        import mcphub
        self.save(); s = self.current()
        if not s: return
        self.say(f"connecting to {s['name']} ...")
        def work():
            try:
                tools = mcphub.list_tools(self.cfg, s["name"])
                self.sw.ui(lambda: (self.persist(), self.refresh_list(s["name"]),
                                    self.say(f"OK - {len(tools)} tools: " + ", ".join(t['name'] for t in tools)[:300])))
            except Exception as e:
                m = f"{type(e).__name__}: {e}"
                self.sw.ui(lambda: self.say("Couldn't connect: " + m[:400] + "   (VIEW LOG for details)", True))
        threading.Thread(target=work, daemon=True).start()

    def view_log(self):
        import mcphub
        u = U(); s = self.current()
        if not s: return
        top = tk.Toplevel(self.sw.win, bg=u.BG); top.title(f"MCP LOG - {s['name']}")
        t = tk.Text(top, bg=u.BG, fg=u.FG, font=u.FONT, width=90, height=25, relief="flat"); t.pack(fill="both", expand=True)
        t.insert("1.0", mcphub.read_log(s["name"])); t.see("end"); t.config(state="disabled")

class ProfilePane:
    """Bot profile: big robot, name, description, instructions, model, tools, memory (delete notes), EDIT."""
    def __init__(self, app, cid):
        import toolhub
        u = U(); self.app, self.cid = app, cid
        c = app.store.get(cid); b = c["bot"]
        top = self.win = tk.Toplevel(app.root, bg=u.BG, highlightbackground=u.FG, highlightthickness=2)
        top.title(f"BOT - {b.get('name')}"); top.geometry("560x620"); top.transient(app.root)
        outer, w = scrollable(top); outer.pack(fill="both", expand=True, padx=6, pady=6)
        hd = tk.Frame(w, bg=u.BG); hd.pack(fill="x", padx=10, pady=8)
        self.big = robot.RobotIcon(hd, color=bots.color_hex(b), style=b.get("style", "classic"), size=max(30, u.FONT[1] * 3), bg=u.BG)
        self.big.pack(side="left", padx=(0, 12)); self.big.happy()
        nm = tk.Frame(hd, bg=u.BG); nm.pack(side="left", fill="x")
        tk.Label(nm, text=b.get("name"), fg=u.FG, bg=u.BG, font=u.FONT + ("bold",), anchor="w").pack(fill="x")
        tk.Label(nm, text=b.get("description") or "(no description)", fg=u.DIM, bg=u.BG, font=u.FONT, anchor="w").pack(fill="x")
        tk.Label(nm, text=f"{len(c['messages'])} messages", fg=u.DIM, bg=u.BG, font=u.FONT, anchor="w").pack(fill="x")
        def sec(t, body, fg=None):
            tk.Label(w, text=t, fg=u.FG, bg=u.BG, font=u.FONT + ("bold",), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
            tk.Label(w, text=body, fg=fg or u.STEP, bg=u.BG, font=u.FONT, anchor="w", justify="left", wraplength=500).pack(fill="x", padx=18)
        sec("INSTRUCTIONS", b.get("instructions") or "(none - uses the default assistant behaviour)")
        sec("MODEL", (b.get("provider") or "global") + (f" · {b['model']}" if b.get("model") else " (same as Settings)"))
        try: tools = toolhub.bot_tools(app.cfg, b)
        except Exception: tools = []
        names = [t["name"] + (" (asks first)" if t.get("write") else "") for t in tools]
        sec("TOOLS", "\n".join(names) or "(none yet - connect apps or MCP servers in Settings)")
        tk.Label(w, text="MEMORY", fg=u.FG, bg=u.BG, font=u.FONT + ("bold",), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        self.memf = tk.Frame(w, bg=u.BG); self.memf.pack(fill="x", padx=18); self.fill_mem()
        bar = tk.Frame(top, bg=u.BG); bar.pack(pady=8)
        u.btn(bar, "[ EDIT BOT ]", self.edit).pack(side="left", padx=6); u.btn(bar, "[ CLOSE ]", top.destroy).pack(side="left", padx=6)
        top.bind("<Escape>", lambda e: top.destroy())

    def fill_mem(self):
        u = U()
        for x in self.memf.winfo_children(): x.destroy()
        mem = self.app.store.get(self.cid)["bot"].get("memory") or []
        if not mem: tk.Label(self.memf, text="(nothing saved - say 'remember that ...' or /remember)", fg=u.DIM, bg=u.BG, font=u.FONT, anchor="w").pack(fill="x")
        for i, m in enumerate(mem):
            r = tk.Frame(self.memf, bg=u.BG); r.pack(fill="x", pady=1)
            u.btn(r, "x", lambda i=i: self.forget(i), fg=u.WARN).pack(side="left", padx=(0, 6))
            tk.Label(r, text=m, fg=u.STEP, bg=u.BG, font=u.FONT, anchor="w", justify="left", wraplength=440).pack(side="left", fill="x")

    def forget(self, i):
        mem = list(self.app.store.get(self.cid)["bot"].get("memory") or [])
        if 0 <= i < len(mem): mem.pop(i); self.app.store.update_bot(self.cid, memory=mem)
        self.fill_mem()

    def edit(self):
        self.win.destroy(); self.app.edit_bot(self.cid)
