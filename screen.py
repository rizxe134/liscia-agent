"""Screenshot capture, downscaling and coordinate grid overlay."""
from PIL import Image, ImageDraw

def capture():
    import mss
    with mss.mss() as s:
        mon = s.monitors[1]  # primary monitor
        raw = s.grab(mon)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

def prepare(img, width=1280, grid=100):
    """Downscale and draw a labelled grid. Returns (image, scale) where
    real_px = model_px * scale."""
    scale = img.width / width if img.width > width else 1.0
    if scale != 1.0:
        img = img.resize((width, round(img.height / scale)), Image.LANCZOS)
    img = img.copy()
    if grid:
        d = ImageDraw.Draw(img, "RGBA")
        for x in range(0, img.width, grid):
            d.line([(x, 0), (x, img.height)], fill=(255, 0, 0, 90))
            d.text((x + 2, 2), str(x), fill=(255, 0, 0, 255))
        for y in range(0, img.height, grid):
            d.line([(0, y), (img.width, y)], fill=(0, 0, 255, 90))
            d.text((2, y + 2), str(y), fill=(0, 0, 255, 255))
    return img, scale

def point_ratio(gui, pixel_width):
    """pyautogui uses points; on Retina Macs the screenshot has 2x as many pixels."""
    try:
        w = gui.size()[0]
        r = float(w) / pixel_width
        return r if 0.2 < r <= 1.0 else 1.0
    except Exception:
        return 1.0

def image_hash(img, size=(64, 40)):
    """Tiny grayscale thumbnail used to detect whether the screen changed."""
    return list(img.convert("L").resize(size).tobytes())

def hash_diff(a, b, tol=12):
    """Fraction of thumbnail pixels that changed by more than tol."""
    if not a or not b or len(a) != len(b): return 1.0
    return sum(1 for x, y in zip(a, b) if abs(x - y) > tol) / len(a)

def is_blank(img, spread=10):
    """True when a screenshot is (almost) one flat colour - on macOS that means Screen Recording permission is missing."""
    g = img.convert("L").resize((96, 60))
    lo, hi = g.getextrema()
    return hi - lo <= spread
