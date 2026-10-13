"""Kill switch (global hotkeys) and confirmation prompts."""
import threading, time

class KillSwitch:
    def __init__(self, keys=("esc", "f12")):
        self.event = threading.Event(); self.keys = {k.lower() for k in keys}; self._l = None; self._run = False

    def start(self):
        import sys
        if sys.platform == "darwin":
            return self._start_mac()
        try:
            from pynput import keyboard
        except Exception as e:
            print(f"[safety] pynput unavailable ({e}); kill hotkey disabled, FAILSAFE still active"); return
        def on_press(key):
            name = getattr(key, "name", None) or getattr(key, "char", None)
            if name and name.lower() in self.keys:
                print(f"\n[safety] {name} pressed - stopping agent"); self.event.set()
        self._l = keyboard.Listener(on_press=on_press); self._l.daemon = True; self._l.start()

    def _start_mac(self):
        """pynput's listener crashes on recent macOS (it calls HIToolbox/TSM off the main
        thread -> SIGTRAP). Instead poll CGEventSourceKeyState, which is thread-safe."""
        codes = {"esc": 53, "escape": 53, "f12": 111}
        keys = [codes[k] for k in self.keys if k in codes]
        try:
            import ctypes, ctypes.util
            cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
            cg.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]
            cg.CGEventSourceKeyState.restype = ctypes.c_bool
        except Exception as e:
            print(f"[safety] kill hotkey unavailable ({e}); use STOP button / mouse-corner FAILSAFE"); return
        self._run = True
        def poll():
            while self._run and not self.event.is_set():
                if any(cg.CGEventSourceKeyState(1, k) for k in keys):  # 1 = HID system state
                    print("\n[safety] kill key pressed - stopping agent"); self.event.set()
                time.sleep(0.05)
        threading.Thread(target=poll, daemon=True).start()

    def stop(self):
        self._run = False
        if self._l: self._l.stop()

    @property
    def killed(self): return self.event.is_set()

def console_confirm(msg):
    return input(f"\n[CONFIRM] {msg}\nAllow? [y/N]: ").strip().lower() in ("y", "yes")
