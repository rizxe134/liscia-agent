"""Retro green-on-black chat app (Tkinter, no extra deps)."""
import os, threading, queue, tkinter as tk
from core import Agent, route

import themes
BG, FG, DIM, USER, WARN = "#000000", "#3dff8f", "#9fe8c0", "#ffffff", "#ffd23f"
STEP, LINE = "#c2f5d8", "#2e7d55"
FONT = ("Consolas", themes.DEFAULT_SIZE)
PAL = dict(themes.THEMES[themes.DEFAULT])

def set_palette(p):
    """Module colours used when widgets are created (2.1.0 themes)."""
    global BG, FG, DIM, USER, WARN, STEP, LINE, PAL
    BG, FG, DIM, USER, WARN, STEP, LINE = (p[k] for k in themes.KEYS[:1] + ("fg", "dim", "user", "warn", "step", "line"))
    PAL = dict(p)

COLOR_OPTS = ("bg", "fg", "highlightbackground", "highlightcolor", "activebackground", "activeforeground", "selectbackground",
              "selectforeground", "insertbackground", "selectcolor", "disabledforeground", "troughcolor")

def recolor(widget, old, new, size):
    """Live theme switch: map every colour of the old palette to the new one, resize fonts, recursively."""
    cmap = {}
    for k in themes.KEYS:
        if old.get(k): cmap.setdefault(old[k].lower(), new[k])
    stack = [widget]
    while stack:
        w = stack.pop(); stack.extend(w.winfo_children())
        for opt in (() if getattr(w, "_fixed", False) else COLOR_OPTS):
            try:
                v = str(w.cget(opt)).lower()
                if v in cmap: w.configure(**{opt: cmap[v]})
            except tk.TclError: pass
        try:
            f = w.tk.splitlist(w.cget("font"))
            if len(f) >= 2: w.configure(font=(f[0], size) + tuple(f[2:]))
        except tk.TclError: pass
        if isinstance(w, tk.Text):
            for t in w.tag_names():
                for opt in ("foreground", "background"):
                    v = str(w.tag_cget(t, opt)).lower()
                    if v in cmap: w.tag_config(t, **{opt: cmap[v]})
                tf = w.tag_cget(t, "font")
                if tf:
                    f = w.tk.splitlist(tf)
                    if len(f) >= 2: w.tag_config(t, font=(f[0], size) + tuple(f[2:]))

def pick_font(root):
    """Use the first installed monospace font (Consolas on Windows)."""
    global FONT
    from tkinter import font as tkfont
    fams = set(tkfont.families(root))
    for f in ("SF Mono", "Menlo", "Monaco", "Consolas", "Cascadia Mono", "Lucida Console", "IBM Plex Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New"):
        if f in fams:
            FONT = (f, FONT[1]); return
    FONT = ("TkFixedFont", FONT[1])
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
        FlatButton(bar, text=txt, command=lambda v=v: done(v), highlightbackground=FG).pack(side="left", padx=8)
    win.bind("y", lambda e: done(True)); win.bind("n", lambda e: done(False)); win.bind("<Escape>", lambda e: done(False))
    win.grab_set(); win.focus_force(); root.wait_window(win)
    return res["ok"]

from chats import plain_result

def style_tabs(st):
    st.configure("R.TNotebook", background=BG, borderwidth=0)
    st.configure("R.TNotebook.Tab", background=BG, foreground=DIM, font=FONT, padding=(10, 4), bordercolor=LINE)
    st.map("R.TNotebook.Tab", background=[("selected", FG)], foreground=[("selected", BG)])

class FlatButton(tk.Frame):
    """A themable button. 2.3.8: the border is a 1px Frame around a plain Label. Tk on macOS draws a Label's own highlight
    ring offset from its text (cut corners, label below the box, worse at bigger fonts), so Labels get no highlight at all.
    Same API as before: command=, state=, text=, fg=, configure/cget, invoke()."""
    _LABEL_KEYS = {"text", "state", "fg", "foreground", "font", "cursor", "disabledforeground", "anchor", "padx", "pady", "width", "textvariable"}
    def __init__(self, parent, text="", command=None, fg=None, bg=None, font=None, state="normal", activebackground=None,
                 activeforeground=None, highlightbackground=None, highlightthickness=1, **_):
        self._line = highlightbackground or LINE; self._bw = max(0, int(highlightthickness))
        super().__init__(parent, bg=self._line if self._bw else (bg or BG), highlightthickness=0, bd=0)
        self.lbl = tk.Label(self, text=text, fg=fg or FG, bg=bg or BG, font=font or FONT, cursor="hand2", padx=8, pady=3,
                            highlightthickness=0, bd=0, disabledforeground=LINE, state=state)
        self.lbl.pack(fill="both", expand=True, padx=self._bw, pady=self._bw)
        self._cmd = command
        for w in (self, self.lbl):
            w.bind("<Button-1>", lambda e: self._cmd() if self._cmd and str(self.lbl.cget("state")) != "disabled" else None)
            w.bind("<Enter>", lambda e: str(self.lbl.cget("state")) != "disabled" and tk.Frame.configure(self, bg=self.lbl.cget("fg")))
            w.bind("<Leave>", lambda e: tk.Frame.configure(self, bg=self._line))
    def configure(self, cnf=None, **kw):
        if cnf: kw.update(cnf)
        lk = {k: v for k, v in kw.items() if k in self._LABEL_KEYS}
        if "highlightbackground" in kw: self._line = kw.pop("highlightbackground"); kw["bg"] = self._line
        fk = {k: v for k, v in kw.items() if k not in self._LABEL_KEYS and k not in ("activebackground", "activeforeground", "highlightthickness")}
        if "bg" in fk and fk["bg"] != self._line and not ("highlightbackground" in kw):
            self.lbl.configure(bg=fk.pop("bg"))  # a plain bg= colours the face, not the border
        if "background" in fk: self.lbl.configure(bg=fk.pop("background"))
        if lk: self.lbl.configure(**lk)
        if fk: tk.Frame.configure(self, **fk)
    config = configure
    def cget(self, key):
        if key in self._LABEL_KEYS: return self.lbl.cget(key)
        if key == "highlightbackground": return self._line
        return tk.Frame.cget(self, key)
    def invoke(self):
        if self._cmd: self._cmd()

def btn(parent, text, cmd, fg=None):
    return FlatButton(parent, text=text, command=cmd, fg=fg)

def retro_prompt(root, title, initial=""):
    win = tk.Toplevel(root, bg=BG, highlightbackground=FG, highlightthickness=2); win.title(title); win.transient(root)
    tk.Label(win, text=title, fg=FG, bg=BG, font=FONT + ("bold",)).pack(padx=12, pady=(10, 4))
    e = tk.Entry(win, bg=BG, fg=FG, font=FONT, insertbackground=FG, width=40, relief="flat", highlightthickness=1, highlightbackground=FG)
    e.insert(0, initial); e.pack(padx=12, pady=4); e.select_range(0, "end")
    res = {"v": None}
    def done(v): res["v"] = v; win.destroy()
    bar = tk.Frame(win, bg=BG); bar.pack(pady=10)
    btn(bar, "[ OK ]", lambda: done(e.get())).pack(side="left", padx=6); btn(bar, "[ CANCEL ]", lambda: done(None)).pack(side="left", padx=6)
    e.bind("<Return>", lambda ev: done(e.get())); win.bind("<Escape>", lambda ev: done(None))
    win.grab_set(); e.focus_force(); root.wait_window(win); return res["v"]

class SettingsWindow:
    """Provider, per-role models, API keys (OS keychain), Ollama pulls, privacy notice."""
    def __init__(self, app):
        import providers, keystore, settings
        from tkinter import ttk
        self.app, self.cfg = app, app.cfg; settings.defaults(self.cfg)
        top = self.win = tk.Toplevel(app.root, bg=BG, highlightbackground=FG, highlightthickness=2); top.title("SETTINGS"); top.geometry("760x720")
        st = ttk.Style(top)
        try: st.theme_use("clam")
        except Exception: pass
        st.configure("R.TCombobox", fieldbackground=BG, background=BG, foreground=FG, arrowcolor=FG, bordercolor=DIM)
        st.map("R.TCombobox", fieldbackground=[("readonly", BG)], foreground=[("readonly", FG)])
        style_tabs(st)
        nb = self.nb = ttk.Notebook(top, style="R.TNotebook"); nb.pack(fill="both", expand=True, padx=6, pady=6)
        w = tk.Frame(nb, bg=BG); nb.add(w, text=" MODELS ")
        self.dl_tab = tk.Frame(nb, bg=BG); nb.add(self.dl_tab, text=" DOWNLOAD ")
        self.theme_tab = tk.Frame(nb, bg=BG); nb.add(self.theme_tab, text=" THEMES ")
        self.build_themes(self.theme_tab)
        import botui  # 3.0.0
        self.conn_tab = tk.Frame(nb, bg=BG); nb.add(self.conn_tab, text=" CONNECTIONS ")
        self.mcp_tab = tk.Frame(nb, bg=BG); nb.add(self.mcp_tab, text=" MCP ")
        self.conns = botui.ConnectionsTab(self, self.conn_tab); self.mcp = botui.McpTab(self, self.mcp_tab)
        top.option_add("*TCombobox*Listbox.background", BG); top.option_add("*TCombobox*Listbox.foreground", FG)
        top.option_add("*TCombobox*Listbox.selectBackground", FG); top.option_add("*TCombobox*Listbox.selectForeground", BG)
        L = lambda t, fg=FG, bold=False, **k: tk.Label(w, text=t, fg=fg, bg=BG, font=FONT + (("bold",) if bold else ()), anchor="w", justify="left", **k)
        L("> SETTINGS", bold=True).pack(fill="x", padx=12, pady=(10, 6))
        L("PROVIDER").pack(fill="x", padx=12)
        self.prov = tk.StringVar(value=self.cfg["provider"]["name"])
        pr = tk.Frame(w, bg=BG); pr.pack(fill="x", padx=12, pady=(0, 6))
        for k, name in providers.NAMES.items():
            tk.Radiobutton(pr, text=name, value=k, variable=self.prov, command=self.on_provider, fg=FG, bg=BG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG, font=FONT, highlightthickness=0).pack(side="left", padx=(0, 10))
        self.priv = L("", fg=WARN, wraplength=640); self.priv.pack(fill="x", padx=12, pady=(0, 6))
        # key row
        self.key_frame = tk.Frame(w, bg=BG); self.key_frame.pack(fill="x", padx=12, pady=4)
        self.key_lbl = tk.Label(self.key_frame, text="API KEY", fg=FG, bg=BG, font=FONT); self.key_lbl.pack(side="left")
        self.key = tk.Entry(self.key_frame, show="\u2022", bg=BG, fg=FG, font=FONT, insertbackground=FG, width=30, relief="flat",
                            highlightthickness=1, highlightbackground=LINE)
        self.key.pack(side="left", padx=6)
        btn(self.key_frame, "[ SAVE KEY ]", self.save_key).pack(side="left", padx=2)
        btn(self.key_frame, "[ REMOVE ]", self.remove_key, fg=WARN).pack(side="left", padx=2)
        tr = tk.Frame(w, bg=BG); tr.pack(fill="x", padx=12, pady=2)
        btn(tr, "[ TEST CONNECTION ]", self.test).pack(side="left"); btn(tr, "[ REFRESH MODELS ]", self.load_models).pack(side="left", padx=6)
        self.key_state = tk.Label(tr, text="", fg=DIM, bg=BG, font=FONT); self.key_state.pack(side="left", padx=6)
        # models
        L("TEXT / PLANNER MODEL  (chat, routing, planning, page text)").pack(fill="x", padx=12, pady=(10, 0))
        self.tm = ttk.Combobox(w, style="R.TCombobox", font=FONT); self.tm.pack(fill="x", padx=12)
        L("VISION MODEL  (reads screenshots; must accept images)").pack(fill="x", padx=12, pady=(8, 0))
        self.vm = ttk.Combobox(w, style="R.TCombobox", font=FONT); self.vm.pack(fill="x", padx=12)
        self.vm_hint = L("Pick from the list or type any model name.", fg=DIM); self.vm_hint.pack(fill="x", padx=12)
        # ollama pull
        self.pull_frame = tk.Frame(w, bg=BG); self.pull_frame.pack(fill="x", padx=12, pady=(10, 0))
        btn(self.pull_frame, "[ DOWNLOAD MORE LOCAL MODELS \u2192 ]", lambda: self.nb.select(self.dl_tab)).pack(side="left")
        self.pull_state = L("", fg=DIM); self.pull_state.pack(fill="x", padx=12)
        self.fb = tk.BooleanVar(value=self.cfg["provider"].get("fallback_local", True))
        tk.Checkbutton(w, text="If the cloud provider fails, fall back to the local Ollama model", variable=self.fb, fg=FG, bg=BG, selectcolor=BG,
                       activebackground=BG, activeforeground=FG, font=FONT, highlightthickness=0).pack(fill="x", padx=12, pady=(8, 0))
        md = self.cfg.setdefault("media", {})
        self.skip_ads = tk.BooleanVar(value=md.get("auto_skip_ads", True)); self.mute_ads = tk.BooleanVar(value=md.get("mute_ads", True))
        for txt, var in (("Auto-skip ads (click 'Skip', close ad banners) while playing videos", self.skip_ads),
                         ("Mute ads that can't be skipped, unmute after", self.mute_ads)):
            tk.Checkbutton(w, text=txt, variable=var, fg=FG, bg=BG, selectcolor=BG, activebackground=BG, activeforeground=FG,
                           font=FONT, highlightthickness=0).pack(fill="x", padx=12, pady=(4, 0))
        self.msg = L("", fg=DIM, wraplength=640); self.msg.pack(fill="x", padx=12, pady=4)
        bar = tk.Frame(w, bg=BG); bar.pack(side="bottom", pady=10)
        btn(bar, "[ SAVE ]", self.save).pack(side="left", padx=6); btn(bar, "[ CLOSE ]", top.destroy).pack(side="left", padx=6)
        top.bind("<Escape>", lambda e: top.destroy())
        self.build_downloads(self.dl_tab)
        self.on_provider()

    def ui(self, f): self.app.root.after(0, f)

    def build_themes(self, w):
        name, size = themes.get(self.app.cfg)
        tk.Label(w, text="> THEME", fg=FG, bg=BG, font=FONT + ("bold",), anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        self.theme = tk.StringVar(value=name)
        for k, t in themes.THEMES.items():
            row = tk.Frame(w, bg=BG); row.pack(fill="x", padx=12, pady=2)
            tk.Radiobutton(row, text=t["name"], value=k, variable=self.theme, command=self.on_theme, fg=FG, bg=BG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG, font=FONT, highlightthickness=0, width=16, anchor="w").pack(side="left")
            sw = tk.Label(row, text=" AGENT > reply   :: step ", bg=t["bg"], fg=t["fg"], font=FONT, padx=6)  # fixed preview swatch
            sw.pack(side="left"); sw._fixed = True
        tk.Label(w, text="> FONT SIZE", fg=FG, bg=BG, font=FONT + ("bold",), anchor="w").pack(fill="x", padx=12, pady=(14, 0))
        self.size = tk.Scale(w, from_=themes.SIZES[0], to=themes.SIZES[1], orient="horizontal", command=lambda v: self.on_theme(),
                             fg=FG, bg=BG, troughcolor=LINE, highlightthickness=0, font=FONT, length=360, activebackground=FG)
        self.size.set(size); self.size.pack(anchor="w", padx=12)
        tk.Label(w, text="> WHILE THE AGENT WORKS", fg=FG, bg=BG, font=FONT + ("bold",), anchor="w").pack(fill="x", padx=12, pady=(14, 0))
        ui_cfg = self.app.cfg.setdefault("ui", {})
        self.show_cursor = tk.BooleanVar(value=ui_cfg.get("show_cursor", True)); self.show_banner = tk.BooleanVar(value=ui_cfg.get("show_banner", True))
        for txt, var, key in (("Show agent cursor (glides to what it clicks; ring on desktop clicks)", self.show_cursor, "show_cursor"),
                              ("Show active-tab banner (\u25cf Liscia Agent is using this tab \u00b7 Stop) + tab group", self.show_banner, "show_banner")):
            tk.Checkbutton(w, text=txt, variable=var, command=lambda v=var, k=key: self.on_toggle(k, v), fg=FG, bg=BG, selectcolor=BG,
                           activebackground=BG, activeforeground=FG, font=FONT, highlightthickness=0, anchor="w").pack(fill="x", padx=12)
        self.theme_msg = tk.Label(w, text="Changes apply right away and are saved to config.yaml.", fg=DIM, bg=BG, font=FONT, anchor="w")
        self.theme_msg.pack(fill="x", padx=12, pady=8)

    def on_toggle(self, key, var):
        self.app.cfg.setdefault("ui", {})[key] = bool(var.get())
        try:
            import settings; settings.save(self.app.cfg)
        except Exception as e:
            self.theme_msg.config(text=f"couldn't save: {e}", fg=WARN)

    def on_theme(self):
        name, size = self.theme.get(), int(self.size.get())
        if (name, size) == themes.get(self.app.cfg): return
        self.app.apply_theme(name, size)
        try:
            import settings; settings.save(self.app.cfg)
        except Exception as e:
            self.theme_msg.config(text=f"couldn't save: {e}", fg=WARN)

    def on_provider(self):
        import providers, keystore
        p = self.prov.get(); cloud = p != "ollama"
        self.priv.config(text=("!! PRIVACY: " + providers.PRIVACY) if cloud else
                         "Local (Ollama): everything stays on this computer. Nothing is sent to any company.", fg=WARN if cloud else FG)
        for wdg in (self.key_frame,):
            if cloud: wdg.pack(fill="x", padx=12, pady=4, after=self.priv)
            else: wdg.pack_forget()
        if cloud:
            self.key.delete(0, "end"); k = keystore.get(p)
            self.key_lbl.config(text=f"{providers.NAMES[p].upper()} API KEY")
            self.key_state.config(text=("stored in the OS keychain: " + keystore.mask(k)) if k else "no key set", fg=DIM if k else WARN)
            self.pull_frame.pack_forget(); self.pull_state.pack_forget()
        else:
            self.key_state.config(text="", fg=DIM)
            self.pull_frame.pack(fill="x", padx=12, pady=(10, 0), after=self.vm_hint)
            self.pull_state.pack(fill="x", padx=12, after=self.pull_frame)
        if p == "ollama": cur = (self.cfg["ollama"].get("text_model"), self.cfg["ollama"].get("model"))
        else: cur = (self.cfg["provider"][p]["text_model"], self.cfg["provider"][p]["vision_model"])
        self.tm.set(cur[0] or ""); self.vm.set(cur[1] or "")
        self.load_models()

    def load_models(self):
        import providers, keystore
        p = self.prov.get(); self.msg.config(text="loading model list...", fg=DIM)
        def work():
            try:
                if p == "ollama":
                    import llm
                    names = llm.OllamaClient(self.cfg["ollama"]["host"], "").check()
                    if names is None: res = ([], [], "Ollama isn't running. Open the Ollama app, then REFRESH MODELS.", WARN)
                    else: res = (sorted(names), sorted(names), f"{len(names)} local model(s) installed.", DIM)
                else:
                    key = keystore.get(p); st = providers.STATIC_MODELS[p]
                    if not key: res = (st["text"], st["vision"], f"No {providers.NAMES[p]} key set - showing the default model list.", WARN)
                    else:
                        try:
                            m = providers.list_models(p, key); res = (m["text"], m["vision"], f"{len(m['text'])} models from {providers.NAMES[p]}.", DIM)
                        except Exception as e:
                            res = (st["text"], st["vision"], f"{e} - showing the default list.", WARN)
            except Exception as e:
                res = ([], [], f"couldn't list models: {e}", WARN)
            def show():
                if self.prov.get() != p or not self.win.winfo_exists(): return
                self.tm["values"], self.vm["values"] = res[0], res[1]; self.msg.config(text=res[2], fg=res[3])
            self.ui(show)
        threading.Thread(target=work, daemon=True).start()

    def save_key(self):
        import keystore
        p = self.prov.get(); k = self.key.get().strip()
        if not k: self.key_state.config(text="paste a key first", fg=WARN); return
        try: keystore.set(p, k)
        except Exception as e: self.key_state.config(text=f"couldn't store the key in the OS keychain: {e}", fg=WARN); return
        self.key.delete(0, "end"); self.key_state.config(text="stored in the OS keychain: " + keystore.mask(k), fg=DIM); self.load_models()

    def remove_key(self):
        import keystore
        p = self.prov.get()
        if retro_confirm(self.win, f"Remove the stored {p} API key from the OS keychain?"):
            keystore.delete(p); self.key_state.config(text="no key set", fg=WARN)

    def test(self):
        import providers
        p = self.prov.get(); typed = self.key.get().strip() or None; self.key_state.config(text="testing...", fg=DIM)
        def work():
            ok, msg = providers.test_connection(p, key=typed, host=self.cfg["ollama"]["host"])
            self.ui(lambda: self.key_state.config(text=("OK: " if ok else "FAILED: ") + msg, fg=FG if ok else WARN))
        threading.Thread(target=work, daemon=True).start()

    def build_downloads(self, w):
        """2.3.0: curated Ollama models with size / RAM / role, download with progress + cancel, installed list with delete."""
        import modelhub
        from tkinter import ttk
        self.ram = modelhub.system_ram_gb()
        L = lambda t, fg=FG, bold=False, **k: tk.Label(w, text=t, fg=fg, bg=BG, font=FONT + (("bold",) if bold else ()), anchor="w", justify="left", **k)
        L("> DOWNLOAD MORE LOCAL MODELS", bold=True).pack(fill="x", padx=12, pady=(10, 2))
        L(f"This computer has {self.ram:g} GB of RAM. Models marked TOO BIG won't run well here." if self.ram else
          "Couldn't read this computer's RAM.", fg=DIM).pack(fill="x", padx=12)
        self.how_open = False
        self.how_btn = btn(w, "\u25b8 HOW TO (step by step)", self.toggle_howto); self.how_btn.pack(anchor="w", padx=12, pady=(6, 0))
        self.how_lbl = tk.Text(w, fg=FG, bg=BG, font=FONT, wrap="word", height=9, relief="flat", highlightthickness=1, highlightbackground=LINE,
                               padx=8, pady=6, cursor="arrow")
        self.how_lbl.insert("1.0", modelhub.HOW_TO); self.how_lbl.config(state="disabled")
        self.how_anchor = tk.Frame(w, bg=BG, height=1); self.how_anchor.pack(fill="x")
        L("MODEL  (size \u00b7 RAM needed \u00b7 role)").pack(fill="x", padx=12, pady=(8, 0))
        self.dl_pick = ttk.Combobox(w, style="R.TCombobox", font=FONT, state="readonly", values=[modelhub.label(e, self.ram) for e in modelhub.CATALOG])
        self.dl_pick.pack(fill="x", padx=12)
        rec = next((i for i, e in enumerate(modelhub.CATALOG) if e[0] == "qwen2.5:7b"), 0); self.dl_pick.current(rec)
        self.dl_pick.bind("<<ComboboxSelected>>", lambda e: self.dl_note())
        self.dl_info = L("", fg=DIM, wraplength=660); self.dl_info.pack(fill="x", padx=12)
        cr = tk.Frame(w, bg=BG); cr.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(cr, text="OR CUSTOM NAME", fg=FG, bg=BG, font=FONT).pack(side="left")
        self.pull_name = tk.Entry(cr, bg=BG, fg=FG, font=FONT, insertbackground=FG, width=24, relief="flat", highlightthickness=1, highlightbackground=LINE)
        self.pull_name.pack(side="left", padx=6)
        tk.Label(cr, text="e.g. deepseek-r1:7b (overrides the list)", fg=DIM, bg=BG, font=FONT).pack(side="left")
        br = tk.Frame(w, bg=BG); br.pack(fill="x", padx=12, pady=(8, 0))
        self.dl_btn = btn(br, "[ DOWNLOAD ]", self.pull); self.dl_btn.pack(side="left")
        self.cancel_btn = btn(br, "[ CANCEL ]", self.cancel_pull, fg=WARN); self.cancel_btn.pack(side="left", padx=6)
        st = ttk.Style(w); st.configure("R.Horizontal.TProgressbar", troughcolor=BG, background=FG, bordercolor=LINE, lightcolor=FG, darkcolor=FG)
        self.dl_bar = ttk.Progressbar(w, style="R.Horizontal.TProgressbar", maximum=100, mode="determinate"); self.dl_bar.pack(fill="x", padx=12, pady=(6, 0))
        self.dl_state = L("", fg=DIM); self.dl_state.pack(fill="x", padx=12)
        L("INSTALLED LOCAL MODELS").pack(fill="x", padx=12, pady=(10, 0))
        lf = tk.Frame(w, bg=BG); lf.pack(fill="both", expand=True, padx=12)
        self.inst = tk.Listbox(lf, bg=BG, fg=FG, font=FONT, height=6, selectbackground=FG, selectforeground=BG, highlightthickness=1,
                               highlightbackground=LINE, relief="flat", activestyle="none")
        self.inst.pack(side="left", fill="both", expand=True)
        side = tk.Frame(lf, bg=BG); side.pack(side="left", fill="y", padx=6)
        btn(side, "[ DELETE ]", self.delete_model, fg=WARN).pack(fill="x"); btn(side, "[ REFRESH ]", self.load_installed).pack(fill="x", pady=4)
        self.pull_cancel = None; self.dl_note(); self.load_installed()

    def toggle_howto(self):
        self.how_open = not self.how_open
        if self.how_open: self.how_lbl.pack(fill="x", padx=12, pady=(4, 0), after=self.how_btn)
        else: self.how_lbl.pack_forget()
        self.how_btn.config(text=("\u25be" if self.how_open else "\u25b8") + " HOW TO (step by step)")

    def dl_note(self):
        import modelhub
        i = self.dl_pick.current()
        if i < 0: return
        name, size, ram, role, note = modelhub.CATALOG[i]; f = modelhub.fit(ram, self.ram)
        use = "VISION model" if role == "vision" else "TEXT / PLANNER model" if role == "text" else "TEXT or VISION model"
        self.dl_info.config(text=f"{note}. After downloading, pick it as the {use} in MODELS." +
                            ("  Too big for this computer's RAM." if f == "too big" else "  Close other big apps while using it." if f == "tight" else ""),
                            fg=WARN if f == "too big" else DIM)

    def load_installed(self):
        import modelhub
        def work():
            got = modelhub.installed(self.cfg["ollama"]["host"])
            def show():
                if not self.win.winfo_exists(): return
                self.inst.delete(0, "end")
                if got is None: self.inst.insert("end", "Ollama isn't running - open the Ollama app, then REFRESH."); return
                for n, gb in got: self.inst.insert("end", f"{n:<28} {gb:>5.1f} GB")
                if not got: self.inst.insert("end", "(none yet)")
            self.ui(show)
        threading.Thread(target=work, daemon=True).start()

    def delete_model(self):
        import modelhub
        sel = self.inst.curselection()
        if not sel: self.dl_state.config(text="select an installed model first", fg=WARN); return
        name = self.inst.get(sel[0]).split()[0]
        if ":" not in name and name.startswith(("(", "Ollama")): return
        inuse = name in (self.cfg["ollama"].get("text_model"), self.cfg["ollama"].get("model"))
        if not retro_confirm(self.win, f"Delete {name} from this computer?" + (" It is currently selected in MODELS." if inuse else "")): return
        def work():
            try:
                modelhub.delete(self.cfg["ollama"]["host"], name)
                self.ui(lambda: (self.dl_state.config(text=f"deleted {name}", fg=FG), self.load_installed(), self.load_models()))
            except Exception as e:
                self.ui(lambda: self.dl_state.config(text=f"delete failed: {e}", fg=WARN))
        threading.Thread(target=work, daemon=True).start()

    def cancel_pull(self):
        if self.pull_cancel: self.pull_cancel.set(); self.dl_state.config(text="cancelling...", fg=DIM)

    def pull(self):
        import modelhub
        name = self.pull_name.get().strip() or modelhub.name_from_label(self.dl_pick.get())
        if not name: self.dl_state.config(text="pick a model or type a name, e.g. llama3.2:3b", fg=WARN); return
        if self.pull_cancel and not self.pull_cancel.is_set(): self.dl_state.config(text="a download is already running", fg=WARN); return
        self.pull_cancel = ev = threading.Event(); self.dl_bar["value"] = 0
        self.dl_state.config(text=f"downloading {name} ...", fg=DIM)
        def prog(status, done, total):
            pct = int(done * 100 / total) if total else None
            t = f"downloading {name}: {pct:3d}%  {done/1e9:.2f} / {total/1e9:.2f} GB" if total else f"{name}: {status}"
            self.ui(lambda: (self.dl_state.config(text=t, fg=DIM), self.dl_bar.configure(value=pct) if pct is not None else None))
        def work():
            try:
                modelhub.pull(self.cfg["ollama"]["host"], name, prog, cancel=ev)
                self.ui(lambda: (self.dl_bar.configure(value=100), self.dl_state.config(text=f"{name} is ready - choose it in MODELS and SAVE.", fg=FG),
                                 self.load_installed(), self.load_models()))
            except modelhub.Cancelled:
                self.ui(lambda: self.dl_state.config(text=f"cancelled {name} (downloaded parts are kept; DOWNLOAD resumes)", fg=WARN))
            except Exception as e:
                self.ui(lambda: self.dl_state.config(text=f"download failed: {e}", fg=WARN))
            finally:
                ev.set()
        threading.Thread(target=work, daemon=True).start()

    def _old_pull(self):
        import llm
        name = self.pull_name.get().strip()
        if not name: self.pull_state.config(text="type a model name, e.g. llama3.2:3b", fg=WARN); return
        self.pull_state.config(text=f"pulling {name} ...", fg=DIM)
        def prog(status, done, total):
            t = f"pulling {name}: {int(done * 100 / total):3d}% {done/1e9:.1f}/{total/1e9:.1f} GB" if total else f"pulling {name}: {status}"
            self.ui(lambda: self.pull_state.config(text=t, fg=DIM))
        def work():
            try:
                llm.pull_model(self.cfg["ollama"]["host"], name, prog)
                self.ui(lambda: (self.pull_state.config(text=f"{name} is ready.", fg=FG), self.load_models()))
            except Exception as e:
                self.ui(lambda: self.pull_state.config(text=f"pull failed: {e}", fg=WARN))
        threading.Thread(target=work, daemon=True).start()

    def save(self):
        import settings
        try:
            settings.apply(self.cfg, {"provider": self.prov.get(), "text_model": self.tm.get().strip(), "vision_model": self.vm.get().strip(),
                                      "fallback_local": self.fb.get()})
            self.cfg.setdefault("media", {}).update(auto_skip_ads=bool(self.skip_ads.get()), mute_ads=bool(self.mute_ads.get()))
            settings.save(self.cfg)
        except Exception as e:
            self.msg.config(text=f"couldn't save: {e}", fg=WARN); return
        self.app.settings_changed(); self.msg.config(text="Saved. New messages use these models (no restart needed).", fg=FG)

class ChatApp:
    def __init__(self, cfg, root=None, store=None):
        import chats, settings
        settings.defaults(cfg)
        self.cfg = cfg; self.q = queue.Queue(); self.busy = False; self.agent = None
        self.spin_i = 0; self.status_text = "READY"; self.live = ""
        self.store = store or chats.store(); self.store.current_ids = []
        self.store.listeners.append(lambda what, cid: self.q.put(("chats_changed", (what, cid))))
        r = self.root = root or tk.Tk()
        global FONT
        name, size = themes.get(cfg); set_palette(themes.THEMES[name]); FONT = (FONT[0], size)
        pick_font(r)
        r.title("LISCIA AGENT"); r.configure(bg=BG); r.geometry("980x580")
        # ---- sidebar: chats ----
        side = tk.Frame(r, bg=BG, highlightthickness=1, highlightbackground=LINE, width=250); side.pack(side="left", fill="y", padx=(8, 0), pady=8)
        side.pack_propagate(False)
        import botui  # 3.0.0: chats are bots, each with its own robot
        btn(side, "[ + NEW BOT ]", self.new_bot).pack(fill="x", padx=6, pady=(6, 4))
        tk.Label(side, text="BOTS", fg=DIM, bg=BG, font=FONT, anchor="w").pack(fill="x", padx=6)
        self.bot_list = botui.BotList(side, self._pick_id, self.open_profile)
        row2 = tk.Frame(side, bg=BG); row2.pack(side="bottom", fill="x", padx=6, pady=(0, 6))
        btn(row2, "PROFILE", lambda: self.open_profile(self.store.current_id)).pack(side="left", fill="x", expand=True, padx=(0, 2))
        btn(row2, "TRASH", self.open_trash).pack(side="left", fill="x", expand=True, padx=(2, 0))
        row = tk.Frame(side, bg=BG); row.pack(side="bottom", fill="x", padx=6, pady=(6, 3))
        btn(row, "RENAME", self.rename_chat).pack(side="left", fill="x", expand=True, padx=(0, 2))
        btn(row, "DELETE", self.delete_chat, fg=WARN).pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.bot_list.pack(fill="both", expand=True, padx=6)
        # ---- main column ----
        main = tk.Frame(r, bg=BG); main.pack(side="left", fill="both", expand=True)
        top = tk.Frame(main, bg=BG); top.pack(fill="x", padx=8, pady=(6, 0))
        self.title_lbl = tk.Label(top, text="> LISCIA AGENT", fg=FG, bg=BG, font=FONT + ("bold",)); self.title_lbl.pack(side="left")
        self.stop_btn = FlatButton(top, text="[ STOP ]", command=self.stop, fg=WARN, state="disabled")
        self.stop_btn.pack(side="right")
        btn(top, "[ \u2699 SETTINGS ]", self.open_settings).pack(side="right", padx=6)
        self.model_lbl = tk.Label(main, text="", fg=DIM, bg=BG, font=FONT, anchor="w"); self.model_lbl.pack(fill="x", padx=8)
        self.log = tk.Text(main, bg=BG, fg=FG, font=FONT, wrap="word", relief="flat", insertbackground=FG,
                           highlightthickness=1, highlightbackground=LINE, padx=8, pady=6, height=10)
        for tag, col in (("user", USER), ("agent", FG), ("step", STEP), ("warn", WARN), ("sys", DIM), ("hdr", DIM)):
            self.log.tag_config(tag, foreground=col)
        self.log.tag_config("agent", spacing1=4, spacing3=6, font=FONT + ("bold",)); self.log.tag_config("user", spacing1=8)
        self.log.tag_config("who", underline=False)
        self.log.tag_config("hdr", underline=True); self.log.tag_bind("hdr", "<Enter>", lambda e: self.log.config(cursor="hand2"))
        self.log.tag_bind("hdr", "<Leave>", lambda e: self.log.config(cursor="xterm"))
        self.grp = None; self.grp_n = 0
        self.log.config(state="disabled")
        self.status = tk.Label(main, text="", fg=DIM, bg=BG, font=FONT, anchor="w"); self.status.pack(fill="x", padx=8)
        bottom = tk.Frame(main, bg=BG); bottom.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(bottom, text="$>", fg=FG, bg=BG, font=FONT + ("bold",)).pack(side="left")
        self.entry = tk.Entry(bottom, bg=BG, fg=FG, font=FONT, relief="flat", insertbackground=FG,
                              insertwidth=9, insertontime=500, insertofftime=500,  # blinking block cursor
                              highlightthickness=1, highlightbackground=LINE, highlightcolor=FG)
        self.entry.pack(side="left", fill="x", expand=True, padx=6, ipady=4)
        self.entry.bind("<Return>", lambda e: self.send()); self.entry.focus_set()
        self._bind_history()
        self.log.pack(fill="both", expand=True, padx=8, pady=6, before=self.status)  # packed last so input row always shows
        r.bind("<F12>", lambda e: self.stop()); r.bind("<Command-period>", lambda e: self.stop())
        r.bind("<Control-n>", lambda e: self.new_bot()); r.bind("<Command-n>", lambda e: self.new_bot())
        self.working_cid = None
        self.refresh_model_label(); self.refresh_chats(); self.show_chat(self.store.current())
        import overlay  # 2.2.0: desktop click ring, drawn on the Tk thread
        overlay.HOOK = lambda x, y: self.q.put(("ring", (x, y)))
        self._tick()
        threading.Thread(target=self._preload, daemon=True).start()

    # ---------------- 2.3.8: terminal-style input ----------------
    def _bind_history(self):
        import inputhist
        try: hp = os.path.join(os.path.dirname(self.store.dir), "input_history.json")
        except Exception: hp = os.path.join(os.path.expanduser("~"), ".liscia_input_history.json")
        self.hist = inputhist.History(hp); self._rsearch = None
        e = self.entry
        def setv(t):
            if t is None: return "break"
            e.delete(0, "end"); e.insert(0, t); e.icursor("end"); return "break"
        def cid():
            try: return self.store.current_id
            except Exception: return None
        e.bind("<Up>", lambda ev: setv(self.hist.up(e.get(), cid())))
        e.bind("<Down>", lambda ev: setv(self.hist.down(e.get(), cid())))
        e.bind("<Escape>", lambda ev: (e.delete(0, "end"), self.hist.reset(), self._end_rsearch(), "break")[-1])
        e.bind("<Control-l>", lambda ev: (self.clear_view(), "break")[-1])
        e.bind("<Tab>", lambda ev: self._complete())
        e.bind("<Control-r>", lambda ev: self._reverse_search())
        e.bind("<Key>", lambda ev: self._typed(ev), add="+")

    def _typed(self, ev):
        if ev.keysym not in ("Up", "Down", "Return", "Escape", "Tab") and not (ev.state & 0x4 and ev.keysym in ("r", "l")):
            if self._rsearch is not None: self._end_rsearch()

    def _complete(self):
        import inputhist
        t, cands = inputhist.complete(self.entry.get())
        if t != self.entry.get(): self.entry.delete(0, "end"); self.entry.insert(0, t); self.entry.icursor("end")
        elif len(cands) > 1: self.q.put(("status", "  ".join(cands)))
        return "break"

    def _reverse_search(self):
        """Ctrl+R: the box text is the search; each press finds an older match (status line shows it)."""
        if self._rsearch is None: self._rsearch = self.entry.get()
        hit = self.hist.search(self._rsearch, self.store.current_id, older=self.hist.search_from is not None)
        if hit is not None:
            self.entry.delete(0, "end"); self.entry.insert(0, hit); self.entry.icursor("end")
            self.status.config(text=f"(reverse-i-search)`{self._rsearch}': {hit[:60]}   Ctrl+R older, Esc cancel")
        else: self.status.config(text=f"(failed reverse-i-search)`{self._rsearch}'")
        return "break"

    def _end_rsearch(self):
        self._rsearch = None; self.hist.search_from = None

    def clear_view(self):
        """Ctrl+L: clear what's on screen (the chat and the input history are kept)."""
        self.log.config(state="normal"); self.log.delete("1.0", "end"); self.log.config(state="disabled"); self.grp = None

    INTRO = ("SYSTEM READY. Chat normally, or ask me to do something on your PC.\n"
             "Tips: '/new' new chat, '/settings' models & providers, '/do <task>' forces computer control, '/chat <msg>' plain chat, "
             "'/token' shows your key, '/help' lists commands.\nAbort a task: STOP button, Esc/F12, or slam the mouse into a screen corner.\n")

    # ---------------- chats ----------------
    @property
    def chat_id(self): return self.store.current()["id"]

    def refresh_chats(self):
        lst = self.store.list(); self.store.current_ids = [c["id"] for c in lst]
        self.bot_list.set(lst, self.store.current_id, working=self.working_cid if self.busy else None,
                          unread=getattr(self.bot_list, "unread", set()))

    def cur_bot(self):
        try: return self.store.current().get("bot") or {}
        except Exception: return {}

    def show_chat(self, c):
        self.log.config(state="normal"); self.log.delete("1.0", "end"); self.log.config(state="disabled")
        self.title_lbl.config(text=f"> LISCIA AGENT // {c['title']}")
        self._bot = c.get("bot") or {}
        if not c["messages"]: self.write("sys", self.INTRO)
        for m in c["messages"]:
            if m["role"] == "user": self.write("user", m["content"])
            elif m["role"] == "assistant":
                fb = m.get("from_bot")
                self.write("agent", (fb, m["content"]) if fb else m["content"])
            else: self.write("sys", m["content"])

    def new_chat(self):  # '/new': a fresh conversation with the same kind of bot
        if self.busy: self.write("warn", "Busy - press STOP first, or wait."); return
        c = self.store.new_or_reuse(); self.refresh_chats(); self.show_chat(c); self.entry.focus_set()

    def new_bot(self):
        if self.busy: self.write("warn", "Busy - press STOP first, or wait."); return
        import botui
        d = botui.BotDialog(self, new=True); self.root.wait_window(d.win)
        if not d.result: return
        c = self.store.new(bot=d.result); self.refresh_chats(); self.show_chat(c); self.entry.focus_set()

    def edit_bot(self, cid=None):
        if cid and cid != self.store.current_id: self._pick_id(cid)
        import botui
        c = self.store.current(); d = botui.BotDialog(self, bot=c.get("bot")); self.root.wait_window(d.win)
        if not d.result: return
        c = self.store.update_bot(c["id"], **d.result); self.refresh_chats(); self._bot = c["bot"]
        self.title_lbl.config(text=f"> LISCIA AGENT // {c['title']}")

    def open_profile(self, cid=None):
        import botui
        cid = cid or self.store.current_id
        if cid != self.store.current_id: self._pick_id(cid)
        botui.ProfilePane(self, cid)

    def open_trash(self):
        import botui; botui.trash_dialog(self)

    def _pick_id(self, cid):
        if cid == self.store.current_id: return
        if self.busy: self.write("warn", "Busy - finish or STOP the current task before switching bots."); return
        self.show_chat(self.store.select(cid)); self.bot_list.select(cid)

    def rename_chat(self):
        c = self.store.current(); name = retro_prompt(self.root, "RENAME BOT", c["title"])
        if name: self.store.rename(c["id"], name); self.refresh_chats(); self.title_lbl.config(text=f"> LISCIA AGENT // {name.strip()[:80]}")

    def delete_chat(self):
        if self.busy: self.write("warn", "Busy - press STOP first."); return
        c = self.store.current()
        if not retro_confirm(self.root, f"Delete the bot \"{c['title']}\" and its chat?\nIt goes to TRASH for 30 days (restore it from there)."): return
        self.store.delete(c["id"]); self.refresh_chats(); self.show_chat(self.store.current()); self.refresh_chats()
        self.write("sys", f"\"{c['title']}\" moved to TRASH (30 days). Press [ TRASH ] to restore it.")

    # ---------------- settings ----------------
    def refresh_model_label(self):
        import settings
        self.model_lbl.config(text="   model: " + settings.summary(self.cfg))

    def open_settings(self):
        if getattr(self, "_settings_win", None) and self._settings_win.winfo_exists(): self._settings_win.lift(); return
        self._settings_win = SettingsWindow(self).win

    def settings_changed(self):
        self.agent = None; self.refresh_model_label()
        try:
            import server
            if server.BRIDGE: server.BRIDGE.agent = None  # the panel picks up the new models on its next message
        except Exception: pass
        self.write("sys", "Settings saved: " + __import__("settings").summary(self.cfg))

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
        if __import__("providers").provider_name(self.cfg) != "ollama": return  # cloud provider: nothing to pull or warm
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

    STEPS_OPEN = False  # step logs start collapsed under a "▸ N steps" toggle

    def avatar(self, working=False, bot=None):
        """A small robot for the current bot (or another bot that answered), embedded in the chat log."""
        import robot, bots
        b = bot or getattr(self, "_bot", None) or {}
        ic = robot.RobotIcon(self.log, color=bots.color_hex(b), style=b.get("style", "classic"), size=FONT[1], bg=BG, animate=working)
        if working: ic.set_working(True)
        self.log.window_create("end", window=ic, align="center", padx=2); return ic

    def typing_start(self):
        """'<robot> Name is thinking ···' line while the bot works; removed when its reply arrives."""
        self.typing_stop()
        self.log.config(state="normal"); self.log.mark_set("typing_start", "end-1c"); self.log.mark_gravity("typing_start", "left")
        self._typer = self.avatar(working=True)
        self.log.insert("end", f" {self.bot_name()} is thinking ", ("sys", "typing")); self.log.insert("end", "\u00b7  \n", ("sys", "typing", "tdots"))
        self.log.mark_set("typing_end", "end-1c"); self.log.mark_gravity("typing_end", "left")
        self.log.see("end"); self.log.config(state="disabled"); self._typing = True

    def typing_stop(self):
        if not getattr(self, "_typing", False): return
        self._typing = False
        try:
            self.log.config(state="normal"); self.log.delete("typing_start", "typing_end"); self.log.config(state="disabled")
        except tk.TclError: pass

    def _typing_tick(self):
        if not getattr(self, "_typing", False): return
        r = self.log.tag_ranges("tdots")
        if r:
            n = self.spin_i // 3 % 3 + 1
            self.log.config(state="normal"); self.log.delete(r[0], r[1])
            self.log.insert(r[0], " ".join("\u00b7" * n).ljust(5) + "\n", ("sys", "typing", "tdots")); self.log.config(state="disabled")

    def bot_name(self): return ((getattr(self, "_bot", None) or {}).get("name") or "AGENT")[:24]

    def write(self, tag, text):
        prefix = {"user": "you > ", "agent": "", "step": "   ::  ", "warn": "  !!   ", "sys": ""}[tag]
        self.log.config(state="normal")
        if tag == "agent":
            self.typing_stop()
            other = text if isinstance(text, tuple) else None
            if other: bot, text = other
            else: bot = None
            self.grp = None; ic = self.avatar(bot=bot)
            name = ((bot or {}).get("name") or self.bot_name())[:24]
            self.log.insert("end", f" {name} > ", ("agent", "who"))
            self.log.insert("end", text + "\n", "agent"); self.log.see("end"); self.log.config(state="disabled"); return
        if tag == "user":
            self.log.insert("end", "  ", "user")
        if tag == "step":
            if self.grp is None:  # first step of this task: add the toggle line
                self.grp_n += 1; self.grp = g = f"grp{self.grp_n}"; self.grp_count = 0
                self.log.tag_config(g, elide=not self.STEPS_OPEN)
                self.log.insert("end", "\u25b8 steps\n", ("hdr", f"h{g}"))
                self.log.tag_bind(f"h{g}", "<Button-1>", lambda e, g=g: self.toggle_steps(g))
            self.grp_count += 1; self._set_hdr(self.grp, self.grp_count)
            self.log.insert("end", prefix + text + "\n", (tag, self.grp))
        else:
            if tag in ("agent", "user"): self.grp = None
            self.log.insert("end", prefix + text + "\n", tag)
        self.log.see("end"); self.log.config(state="disabled")

    def _set_hdr(self, g, n):
        r = self.log.tag_ranges(f"h{g}")
        if not r: return
        opened = not int(self.log.tag_cget(g, "elide") or 0)
        arrow = "\u25be" if opened else "\u25b8"
        txt = f"{arrow} {n} step{'s' if n != 1 else ''}" + ("" if opened else "  (click to show)")
        st = self.log.index(r[0]); self.log.delete(r[0], f"{r[1]} -1c"); self.log.insert(st, txt, ("hdr", f"h{g}"))
        self.log._counts = getattr(self.log, "_counts", {}); self.log._counts[g] = n

    def toggle_steps(self, g):
        self.log.config(state="normal")
        self.log.tag_config(g, elide=not int(self.log.tag_cget(g, "elide") or 0))
        self._set_hdr(g, self.log._counts.get(g, 0)); self.log.config(state="disabled")

    def apply_theme(self, name, size):
        """Live: recolour every open window, resize fonts, push the palette to the Chrome side panel (via /status)."""
        global FONT
        old = dict(PAL); new = themes.set_theme(self.cfg, name, size)
        recolor(self.root, old, new, new["size"]); set_palette(new); FONT = (FONT[0], new["size"])
        try:
            from tkinter import ttk
            style_tabs(ttk.Style(self.root))
            ttk.Style(self.root).configure("R.TCombobox", fieldbackground=BG, background=BG, foreground=FG, arrowcolor=FG, bordercolor=LINE)
        except Exception: pass
        self.root.configure(bg=BG)
        try: self.refresh_chats()  # robots follow the new font size
        except Exception: pass

    def _tick(self):
        while not self.q.empty():
            kind, val = self.q.get()
            if kind == "confirm":
                msg, ev, box = val; box["ok"] = retro_confirm(self.root, msg); ev.set()
            elif kind == "card": self._show_card(*val)
            elif kind == "status": self.status_text = val; self.live = ""
            elif kind == "live": self.live = (self.live + val)[-90:]
            elif kind == "stream_start":
                self.typing_stop()
                if self.working_cid: self.bot_list.talking(self.working_cid, True)
                self.log.config(state="normal"); self.grp = None; self._talker = self.avatar(working=True); self._talker.set_talking(True)
                self.log.insert("end", f" {self.bot_name()} > ", ("agent", "who")); self.log.config(state="disabled")
            elif kind == "stream":
                self.log.config(state="normal"); self.log.insert("end", val, "agent"); self.log.see("end"); self.log.config(state="disabled")
            elif kind == "stream_end":
                self.log.config(state="normal"); self.log.insert("end", "\n"); self.log.config(state="disabled")
                t = getattr(self, "_talker", None)
                if t:
                    try: t.set_talking(False); t.happy()
                    except tk.TclError: pass
            elif kind == "ring":
                try:
                    import overlay; overlay.ring(self.root, *val)
                except Exception: pass
            elif kind == "end": self.typing_stop(); self._set_busy(False)
            elif kind == "typing": self.typing_start()
            elif kind == "busy": self._set_busy(True)
            elif kind == "chats_changed":
                what, cid = val
                if what in ("list", "current") or (what == "message" and cid not in self.store.current_ids): self.refresh_chats()
                elif what == "message":
                    self.refresh_chats()
                    if cid != self.store.current_id: self.bot_list.mark_unread(cid)
                    if cid == self.store.current_id and not self.busy:
                        c = self.store.get(cid)
                        if c: self.show_chat(c)  # a message from the Chrome panel in this chat
                if what == "current" and not self.busy and cid and self.title_lbl.cget("text").split("// ", 1)[-1] != (self.store.get(cid) or {}).get("title"):
                    c = self.store.get(cid)
                    if c: self.show_chat(c)
            else: self.write(kind, val)
        try:
            self.bot_list.tick(self.spin_i)
            self._typing_tick()
        except Exception: pass
        if self.busy:
            self.spin_i += 1
            dots = "." * (self.spin_i // 3 % 4)
            live = " ".join(self.live.split())
            self.status.config(text=f"{SPIN[self.spin_i % len(SPIN)]} {self.status_text}{dots}" + (f"  {live[-60:]}" if live else ""), fg=FG)
        else:
            self.status.config(text="READY _" if self.spin_i // 5 % 2 == 0 else "READY", fg=DIM); self.spin_i += 1
        self.root.after(100, self._tick)

    def _show_card(self, msg, ev, box):
        """3.0.0: an Approve/Cancel card inside the chat (tool writes: calendar, email drafts, issues, MCP)."""
        self.log.config(state="normal")
        card = tk.Frame(self.log, bg=BG, highlightthickness=1, highlightbackground=WARN)
        tk.Label(card, text="!! APPROVAL NEEDED", fg=WARN, bg=BG, font=FONT + ("bold",), anchor="w").pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(card, text=msg, fg=FG, bg=BG, font=FONT, anchor="w", justify="left", wraplength=560).pack(fill="x", padx=8)
        bar = tk.Frame(card, bg=BG); bar.pack(anchor="w", padx=8, pady=6)
        res = tk.Label(bar, text="", fg=DIM, bg=BG, font=FONT)
        def done(ok):
            if ev.is_set(): return
            box["ok"] = ok; ev.set()
            for w in bar.winfo_children():
                if isinstance(w, FlatButton): w.configure(state="disabled")
            res.config(text="approved" if ok else "cancelled", fg=FG if ok else WARN)
        FlatButton(bar, text="[ APPROVE ]", command=lambda: done(True), highlightbackground=FG).pack(side="left", padx=(0, 6))
        FlatButton(bar, text="[ CANCEL ]", command=lambda: done(False), fg=WARN).pack(side="left")
        res.pack(side="left", padx=8)
        self.log.insert("end", "\n"); self.log.window_create("end", window=card); self.log.insert("end", "\n")
        self.log.see("end"); self.log.config(state="disabled")

    def card_confirm(self, msg):
        ev, box = threading.Event(), {}
        self.q.put(("card", (msg, ev, box)))
        while not ev.wait(0.5):
            if self.agent and self.agent.kill.event.is_set(): return False
        return box.get("ok", False)

    def _set_busy(self, b):
        self.busy = b
        try:
            if b: self.working_cid = self.store.current_id
            if self.working_cid: self.bot_list.working(self.working_cid, b)
        except Exception: pass
        self.stop_btn.config(state="normal" if b else "disabled")
        self.entry.config(state="disabled" if b else "normal", disabledbackground=BG)
        if not b: self.entry.focus_set()

    def _log(self, msg):
        tag = "step" if msg.startswith("[") else ("warn" if "stop" in msg.lower() else "step")
        self.q.put((tag, msg))
        try:
            import server
            if server.BRIDGE: server.BRIDGE.log(msg)  # narrate in the Chrome side panel too
        except Exception: pass
    def _confirm(self, msg):
        ev, box = threading.Event(), {}
        self.q.put(("confirm", (msg, ev, box))); ev.wait(); return box.get("ok", False)

    def send(self):
        text = self.entry.get().strip()
        if not text or self.busy: return
        try: self.hist.add(text, self.store.current_id)
        except Exception: pass
        low = text.lower().split()[0]
        if low in ("/new", "/newchat", "/clear"): self.entry.delete(0, "end"); self.new_chat(); return
        if low in ("/settings", "/models", "/model"): self.entry.delete(0, "end"); self.open_settings(); return
        if low in ("/remember", "/memory", "/forget", "/bot", "/newbot", "/trash"):
            self.entry.delete(0, "end"); self.write("user", text); self.write("sys", self._bot_cmd(low, text[len(low):].strip())); return
        import slash
        reply = slash.handle(text, copy=self._copy)
        if reply is not None:  # local command: answered here, never sent to the model or logged
            self.entry.delete(0, "end"); self.write("user", text.split()[0]); self.write("sys", reply); return
        self.entry.delete(0, "end"); self.write("user", text); self._set_busy(True)
        self.q.put(("status", "thinking")); self.typing_start()
        threading.Thread(target=self._work, args=(text,), daemon=True).start()

    def _bot_cmd(self, cmd, arg):
        cid = self.store.current_id
        if cmd == "/remember":
            if not arg: return "Usage: /remember <note>"
            self.store.remember(cid, arg); return f"Saved to {self.bot_name()}'s memory."
        if cmd == "/forget":
            c = self.store.get(cid); mem = c["bot"].get("memory") or []
            keep = [m for m in mem if arg and arg.lower() not in m.lower()] if arg else []
            self.store.update_bot(cid, memory=keep); return f"Removed {len(mem) - len(keep)} note(s)."
        if cmd == "/memory":
            mem = self.cur_bot().get("memory") or []
            return "\n".join(f"- {m}" for m in mem) or "Nothing saved yet. Use /remember <note>."
        if cmd in ("/bot",): self.root.after(10, self.edit_bot); return "Opening the bot editor..."
        if cmd == "/newbot": self.root.after(10, self.new_bot); return "Opening NEW BOT..."
        if cmd == "/trash": self.root.after(10, self.open_trash); return "Opening TRASH..."
        return ""

    def _copy(self, text):
        self.root.clipboard_clear(); self.root.clipboard_append(text); self.root.update()

    def _work(self, text):
        cid = self.store.current_id
        try:
            history = self.store.history(cid); ctx = self.store.context(cid)
            import bots, toolhub
            bot = (self.store.get(cid) or {}).get("bot") or {}; persona = bots.persona(bot)
            self.store.add(cid, "user", text)
            self.agent = Agent(bots.bot_cfg(self.cfg, bot), confirm=self._confirm, log=self._log); self.agent.chat_id = cid; self.agent.chat_ctx = ctx
            asked = bots.mentions(text, self.store.list(), exclude=cid)
            if asked:  # 3.0.0: "@Music what should I play?" - hand it to that bot; its robot answers here
                for ocid, ob in asked[:3]: self._ask_bot(cid, ocid, ob, text)
                self.q.put(("end", None)); return
            try:  # 3.0.0: the bot's app connections / MCP tools / memory first
                tools = toolhub.bot_tools(self.cfg, bot, self.store, cid)
                if toolhub.relevant(text, tools):
                    self.q.put(("status", f"{bot.get('name', 'bot')} is checking its tools"))
                    reply = toolhub.try_tools(self.agent.client, text, tools, self.card_confirm, persona, history, log=self._log)
                    if reply is not None:
                        self.q.put(("agent", reply)); self.store.add(cid, "assistant", reply); self.q.put(("end", None)); return
            except Exception as e:
                self.q.put(("step", f"[tools] skipped ({type(e).__name__}: {str(e)[:120]})"))
            self.agent.on_token = lambda p: self.q.put(("live", p))
            started = []
            def stream(p):
                if not started: started.append(1); self.q.put(("stream_start", None))
                self.q.put(("stream", p))
            kind, out = route(self.agent.client, text, history, on_token=stream, persona=persona)
            if kind == "chat":
                if started: self.q.put(("stream_end", None))
                else: self.q.put(("agent", out))
                self.store.add(cid, "assistant", out)
                for ocid, ob in bots.mentions(out, self.store.list(), exclude=cid)[:1]:  # the bot asked a colleague
                    self._ask_bot(cid, ocid, ob, out)
            else:
                self.q.put(("step", f"working on: {out}")); self.q.put(("status", "working on your PC"))
                result = self.agent.run(out)
                self.q.put(("agent", plain_result(result)))
                run = os.path.basename(getattr(self.agent, "last_run_dir", "") or "") or None
                self.store.add(cid, "assistant", plain_result(result), run=run, meta=getattr(self.agent, "last_task_meta", None))
        except Exception as e:
            hint = "" if __import__("providers").provider_name(self.cfg) != "ollama" else "  (is Ollama running? `ollama serve`)"
            self.q.put(("warn", f"Error: {e}{hint}"))
            try: self.store.add(cid, "system", f"error: {e}")
            except Exception: pass
        self.q.put(("end", None))

    def _ask_bot(self, cid, ocid, ob, text):
        """Ask another bot (its persona, tools, memory and history); show + store the reply in this chat with its robot."""
        import bots, toolhub, providers
        me = (self.store.get(cid) or {}).get("bot", {}).get("name", "a bot")
        q = bots.strip_mentions(text, [ob.get("name", "")]).strip()
        self.q.put(("step", f"[handoff] asking {ob.get('name')}")); self.q.put(("status", f"asking {ob.get('name')}"))
        client = providers.make_client(bots.bot_cfg(self.cfg, ob), log=self._log)
        persona = bots.persona(ob) + f"\nAnother bot or the user in the '{me}' chat is asking you this. Answer briefly."
        hist = self.store.history(ocid, 10)
        reply = None
        try:
            tools = toolhub.bot_tools(self.cfg, ob, self.store, ocid)
            reply = toolhub.try_tools(client, q, tools, self.card_confirm, persona, hist, log=self._log)
        except Exception: reply = None
        if reply is None:
            reply = client.text_chat([{"role": "system", "content": __import__("core").CHAT_SYSTEM + "\n\n" + persona}] + hist +
                                     [{"role": "user", "content": q}]).strip()
        self.q.put(("agent", (ob, reply)))
        self.store.add(cid, "assistant", reply, meta=None); c = self.store.get(cid)
        c["messages"][-1]["from_bot"] = {k: ob.get(k) for k in ("name", "color", "style")}; self.store.save(c)
        self.store.add(ocid, "user", f"(from {me}) {q}"); self.store.add(ocid, "assistant", reply)

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
