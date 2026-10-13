"""Where things live. Source checkout: everything next to the code (as before).
Packaged app (PyInstaller): read-only resources inside the bundle, user data in
  macOS:   ~/Library/Application Support/Liscia Agent
  Windows: %APPDATA%\\Liscia Agent
  Linux:   ~/.local/share/liscia-agent"""
import os, shutil, sys

APP_NAME = "Liscia Agent"

def frozen():
    return bool(getattr(sys, "frozen", False))

def resource_dir():
    """Bundled read-only files (default config.yaml, icon)."""
    if frozen(): return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def user_data_dir(platform=None, env=None, home=None):
    platform, env = platform or sys.platform, os.environ if env is None else env
    home = home or os.path.expanduser("~")
    if platform == "darwin": return os.path.join(home, "Library", "Application Support", APP_NAME)
    if platform.startswith("win"): return os.path.join(env.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), APP_NAME)
    return os.path.join(env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "liscia-agent")

OLD_APP_NAME = "PC Agent"

def migrate_old_data(new, old):
    """1.0.x stored data under 'PC Agent': copy it (config, token, runs) once so nothing is lost."""
    if os.path.isdir(old) and not os.path.exists(new):
        try: shutil.copytree(old, new); return True
        except OSError: pass
    return False

def data_dir():
    if frozen():
        d = user_data_dir()
        migrate_old_data(d, os.path.join(os.path.dirname(d), OLD_APP_NAME))
    else:
        d = resource_dir()
    os.makedirs(d, exist_ok=True); return d

def config_path():
    """User-editable config; on first run of the packaged app, copy the bundled default."""
    p = os.path.join(data_dir(), "config.yaml")
    if not os.path.exists(p):
        shutil.copyfile(os.path.join(resource_dir(), "config.yaml"), p)
    return p

def runs_dir(configured="runs"):
    return configured if os.path.isabs(configured) else os.path.join(data_dir(), configured)

def token_path():
    if not frozen(): return os.path.expanduser("~/.pc-agent/token")
    p = os.path.join(data_dir(), "token")
    old = os.path.expanduser("~/.pc-agent/token")  # keep the token the side panel already knows
    if not os.path.exists(p) and os.path.exists(old):
        try: shutil.copyfile(old, p); os.chmod(p, 0o600)
        except OSError: pass
    return p
