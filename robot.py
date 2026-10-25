"""3.0.0: tiny animated pixel robots (Tk Canvas, no images).
States: idle (gentle bob + blink now and then), thinking (pulsing antenna, eyes glance side to side), talking (mouth moves while
a reply streams) and a short happy bounce when a task finishes. Pixel size follows the font size (whole pixels = crisp);
the body colour is the bot's, the background follows the theme."""
import math, random, tkinter as tk

# 9x9 pixel art: H head, E eye, M mouth, A antenna, B body/ears
BASE = {
 "classic": ["....A....", "....A....", ".HHHHHHH.", "BHEHHHEHB", "BHHHHHHHB", "BHHMMMHHB", ".HHHHHHH.", "..H...H..", ".HH...HH."],
 "antenna": ["A.......A", ".A.....A.", "..HHHHH..", ".HEHHHEH.", ".HHHHHHH.", ".HHMMMHH.", "..HHHHH..", "..B...B..", ".BB...BB."],
 "visor":   ["...AAA...", "....A....", ".HHHHHHH.", ".HEEEEEH.", ".HHHHHHH.", ".HHMMMHH.", ".HHHHHHH.", "..H...H..", ".HH...HH."],
}
JUMP = [0, -2, -3, -3, -2, 0, -1, 0]  # happy bounce, in half-pixels

def frame(style, blink=False, talk=0, glow=False, look=0):
    """Return the 9 rows for one animation frame. look = -1/0/1 shifts the eyes."""
    rows = [list(r) for r in BASE.get(style, BASE["classic"])]
    for y, r in enumerate(rows):
        eyes = [x for x, ch in enumerate(r) if ch == "E"]
        if eyes and look and not blink and style != "visor":
            for x in eyes: r[x] = "H"
            for x in eyes:
                nx = min(len(r) - 2, max(1, x + look)); r[nx] = "E"
        for x, ch in enumerate(r):
            if ch == "E" and blink: r[x] = "H"
            if ch == "M":
                if talk == 1 and x == 4: r[x] = "O"
                elif talk == 2: r[x] = "O"
            if ch == "A" and glow: r[x] = "G"
    return ["".join(r) for r in rows]

def px_for(font_size): return max(2, int(font_size) // 5)

class RobotIcon(tk.Canvas):
    def __init__(self, parent, color="#3dff8f", style="classic", size=14, bg="#000000", animate=True):
        self.px = px_for(size)
        super().__init__(parent, width=9 * self.px, height=11 * self.px, bg=bg, highlightthickness=0, bd=0)
        self.color, self.style, self.state = color, style, "idle"
        self._blink, self._t, self._alive, self._jump = 0, random.randint(0, 60), True, -1
        self.draw()
        if animate: self.after(110, self._loop)
        self.bind("<Destroy>", lambda e: setattr(self, "_alive", False))

    # compatibility with 3.0 betas
    @property
    def working(self): return self.state in ("thinking", "talking")

    def set_size(self, size):
        self.px = px_for(size); self.configure(width=9 * self.px, height=11 * self.px); self.draw()

    def set_working(self, on):
        if on: self.state = "thinking"
        elif self.state != "idle": self.state = "idle"; self.happy()
        self.draw()

    def set_talking(self, on): self.state = "talking" if on else "idle"; self.draw()

    def happy(self): self._jump = 0

    def draw(self):
        try: bg = self.cget("bg")
        except tk.TclError: return
        t, p = self._t, self.px
        blink = self._blink > 0
        talk = (t // 2) % 3 if self.state == "talking" else 0
        glow = self.state == "thinking" and (t // 3) % 2 == 0
        look = int(round(math.sin(t / 5.0))) if self.state == "thinking" else 0
        f = frame(self.style, blink=blink, talk=talk, glow=glow, look=look)
        half = max(1, p // 2)
        if 0 <= self._jump < len(JUMP): dy = p + JUMP[self._jump] * half
        elif self.state == "idle": dy = p + (half if (t // 12) % 2 else 0)        # gentle bob
        else: dy = p
        self.delete("all")
        cols = {"H": self.color, "B": self.color, "A": self.color, "G": "#ffffff", "E": bg, "M": bg, "O": "#ffffff" if self.state == "talking" else bg}
        for y, r in enumerate(f):
            for x, ch in enumerate(r):
                if ch in cols: self.create_rectangle(x * p, dy + y * p, x * p + p, dy + y * p + p, fill=cols[ch], width=0)

    def _loop(self):
        if not self._alive: return
        self._t += 1; redraw = False
        if self._jump >= 0:
            self._jump += 1; redraw = True
            if self._jump >= len(JUMP): self._jump = -1
        if self._blink: self._blink -= 1; redraw = True
        elif self.state == "idle" and random.random() < 0.015: self._blink = 2; redraw = True
        if self.state != "idle" or self._t % 12 == 0: redraw = True
        if redraw: self.draw()
        try: self.after(110, self._loop)
        except tk.TclError: pass
