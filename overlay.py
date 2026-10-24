"""2.2.0: desktop click marker. The chat app registers HOOK; the executor calls it just before a mouse click outside Chrome.
The marker is a ring in a small borderless, always-on-top, transparent window: its centre (and everything but the ring) is
fully transparent, which macOS and Windows both treat as click-through, so the real click lands on the app underneath."""
HOOK = None

def show(x, y):
    if HOOK:
        try: HOOK(x, y)
        except Exception: pass

def ring(root, x, y, color="#3dff8f", size=56, ms=900):
    """Draw on the Tk thread. Returns the Toplevel (destroyed after ms)."""
    import sys, tkinter as tk
    w = tk.Toplevel(root); w.overrideredirect(True)
    try: w.attributes("-topmost", True)
    except tk.TclError: pass
    key = "#010203"
    if sys.platform == "darwin":
        try: w.attributes("-transparent", True); key = "systemTransparent"
        except tk.TclError: pass
    w.configure(bg=key)
    if sys.platform.startswith("win"):
        try: w.attributes("-transparentcolor", key)
        except tk.TclError: pass
        try:  # fully click-through (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            import ctypes
            w.update_idletasks(); hwnd = ctypes.windll.user32.GetParent(w.winfo_id())
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x8000000)
        except Exception: pass
    w.geometry(f"{size}x{size}+{int(x - size / 2)}+{int(y - size / 2)}")
    c = tk.Canvas(w, width=size, height=size, bg=key, highlightthickness=0); c.pack()
    o = c.create_oval(6, 6, size - 6, size - 6, outline=color, width=4)
    def grow(i=0):
        if i > 6 or not w.winfo_exists(): return
        d = 6 + i * 2; c.coords(o, d, d, size - d, size - d); w.after(60, grow, i + 1)
    grow(); w.after(ms, w.destroy); return w
