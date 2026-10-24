"""2.1.0: colour themes + font size for the chat app (and the Chrome side panel via /status). Saved in config.yaml under ui:."""
THEMES = {
    "terminal": {"name": "Terminal Green", "bg": "#000000", "fg": "#3dff8f", "dim": "#9fe8c0", "step": "#c2f5d8", "user": "#ffffff", "warn": "#ffd23f", "line": "#2e7d55"},
    "dark":     {"name": "Dark",           "bg": "#1e1f22", "fg": "#ececec", "dim": "#b4b8bf", "step": "#d0d3d8", "user": "#8ab4f8", "warn": "#f2b84b", "line": "#4a4d52"},
    "light":    {"name": "Light",          "bg": "#fafafa", "fg": "#1d1d1f", "dim": "#4a4f57", "step": "#33373d", "user": "#0b57d0", "warn": "#a8321b", "line": "#b9bcc2"},
    "contrast": {"name": "High Contrast",  "bg": "#000001", "fg": "#ffffff", "dim": "#e6e6e6", "step": "#f2f2f2", "user": "#00ffff", "warn": "#ffff00", "line": "#fffffe"},
    "solarized":{"name": "Solarized Dark", "bg": "#002b36", "fg": "#eee8d5", "dim": "#a3b1b1", "step": "#c9d1cf", "user": "#46a5e8", "warn": "#e0b030", "line": "#2c5763"},
    "dracula":  {"name": "Dracula",        "bg": "#282a36", "fg": "#f8f8f2", "dim": "#c3c7da", "step": "#dcdfea", "user": "#8be9fd", "warn": "#ffb86c", "line": "#555a75"},
}
DEFAULT, DEFAULT_SIZE, SIZES = "terminal", 13, (10, 22)
KEYS = ("bg", "fg", "dim", "step", "user", "warn", "line")

def get(cfg):
    u = (cfg or {}).get("ui") or {}
    name = u.get("theme") if u.get("theme") in THEMES else DEFAULT
    try: size = max(SIZES[0], min(SIZES[1], int(u.get("font_size", DEFAULT_SIZE))))
    except (TypeError, ValueError): size = DEFAULT_SIZE
    return name, size

def palette(cfg):
    name, size = get(cfg); return dict(THEMES[name], id=name, size=size)

def set_theme(cfg, name=None, size=None):
    u = cfg.setdefault("ui", {})
    if name is not None:
        if name not in THEMES: raise ValueError(f"unknown theme {name}")
        u["theme"] = name
    if size is not None: u["font_size"] = max(SIZES[0], min(SIZES[1], int(size)))
    return palette(cfg)

def contrast(a, b):
    """WCAG contrast ratio of two #rrggbb colours."""
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)
