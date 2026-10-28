"""Renders Misen's app icon (1024×1024, no alpha) from the design-handoff palette.
Run: python3 ios/make_icon.py   (needs Pillow; uses the bundled Newsreader font)"""
import math, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

S = 1024
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Mise/Assets.xcassets/AppIcon.appiconset/AppIcon.png")
FONT = os.path.join(HERE, "Mise/Fonts/Newsreader-SemiBold.ttf")

def hex_(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
TERRA_LIGHT, TERRA, CREAM, INK, GREEN, GREEN_LIGHT = map(hex_, ["#E08A5B", "#C4573A", "#F6EEE0", "#2A241E", "#5E7C4F", "#8FA96A"])

# 140° gradient, light top-left to deep bottom-right
bg = Image.new("RGB", (S, S))
px = bg.load()
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S)
        px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TERRA_LIGHT, TERRA))

# soft shadow under the plate
shadow = Image.new("L", (S, S), 0)
r = 330
cx, cy = S // 2, S // 2 + 6
ImageDraw.Draw(shadow).ellipse([cx - r, cy - r + 22, cx + r, cy + r + 22], fill=90)
shadow = shadow.filter(ImageFilter.GaussianBlur(28))
bg.paste(Image.new("RGB", (S, S), (120, 45, 25)), (0, 0), shadow)

d = ImageDraw.Draw(bg)
# plate and rim
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CREAM)
ri = 268
d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], outline=(234, 223, 205), width=6)

# serif M
font = ImageFont.truetype(FONT, 380)
box = d.textbbox((0, 0), "M", font=font)
w, h = box[2] - box[0], box[3] - box[1]
d.text((cx - w / 2 - box[0], cy - h / 2 - box[1] - 6), "M", font=font, fill=TERRA)

# herb leaf on the rim, upper right
def leaf(x0, y0, length, width, angle, fill, vein):
    """A pointed leaf from its base (x0, y0), pointing along `angle` degrees."""
    n = 40
    upper = [(length * i / n, width / 2 * math.sin(math.pi * i / n) ** 0.9) for i in range(n + 1)]
    lower = [(x, -y) for x, y in reversed(upper)]
    a = math.radians(angle)
    def rot(x, y): return (x0 + x * math.cos(a) - y * math.sin(a), y0 + x * math.sin(a) + y * math.cos(a))
    d.polygon([rot(x, y) for x, y in upper + lower], fill=fill)
    d.line([rot(0, 0), rot(length * 0.85, 0)], fill=vein, width=6)

# a short stem with two leaves, resting on the plate rim at upper right
bx, by = cx + 175, cy - 205
d.line([(bx - 40, by + 34), (bx, by)], fill=GREEN, width=10)
leaf(bx, by, 190, 86, -62, GREEN, GREEN_LIGHT)
leaf(bx, by, 165, 76, -12, GREEN_LIGHT, GREEN)

bg.save(OUT, "PNG")
print("wrote", OUT)
