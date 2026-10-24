# PyInstaller spec: `pyinstaller liscia_agent.spec` -> dist/Liscia Agent.app (macOS) or dist/Liscia Agent/Liscia Agent.exe (Windows)
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
MAC, WIN = sys.platform == "darwin", sys.platform.startswith("win")
VERSION = "2.2.2"

hidden = collect_submodules("pyautogui") + ["pymsgbox", "pytweening", "pyscreeze", "mouseinfo", "pyperclip", "yaml", "mss", "webagent", "extlink", "server", "paths", "slash", "docmaker", "planner", "policy", "appindex", "appui", "winbind", "adapters", "commands", "appfirst", "chats", "settings", "keystore", "providers", "media", "followups", "themes", "creds", "accounts", "ads", "overlay", "docx", "openpyxl", "pptx", "psutil"]
hidden += [m for m in collect_submodules("pynput") if ("_darwin" in m if MAC else "_win32" in m if WIN else "_xorg" in m) or m.count(".") <= 1]
hidden += collect_submodules("keyring") + (["win32ctypes", "win32ctypes.core"] if WIN else [])
if MAC: hidden += ["Quartz", "AppKit", "Foundation", "objc"]
if WIN: hidden += ["uiautomation", "comtypes", "comtypes.client", "comtypes.stream"] + collect_submodules("comtypes")

a = Analysis(["agent.py"], pathex=["."], datas=[("config.yaml", "."), ("smtc.ps1", "."), ("app_hints.json", "."), ("icon.png", "."), ("icon.ico", ".")] + collect_data_files("docx") + collect_data_files("openpyxl") + collect_data_files("pptx") + (collect_data_files("uiautomation") if WIN else []),
             hiddenimports=hidden, excludes=["pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Liscia Agent", console=False,
          icon="build/AppIcon.icns" if MAC else "icon.ico", target_arch="arm64" if MAC else None,
          codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Liscia Agent")
if MAC:
    app = BUNDLE(coll, name="Liscia Agent.app", icon="build/AppIcon.icns", bundle_identifier="local.liscia.agent",
                 version=VERSION, info_plist={
        "CFBundleName": "Liscia Agent", "CFBundleDisplayName": "Liscia Agent",
        "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": "Liscia Agent controls Safari, Chrome and other apps (opening sites, reading page links) to complete tasks you ask for.",
        "NSScreenCaptureUsageDescription": "Liscia Agent takes screenshots so its local AI model can see the screen and decide where to click.",
        "NSAccessibilityUsageDescription": "Liscia Agent moves the mouse, clicks and types to do tasks on your computer.",
        "NSInputMonitoringUsageDescription": "Liscia Agent watches for the Esc/F12 emergency-stop keys.",
    })
