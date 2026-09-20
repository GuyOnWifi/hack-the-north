"""The share image: the mark, the name and the tagline on the app's yellow.

Rendered rather than hand-made so a rename is one command:
    python scripts/make-og.py        (needs Pillow: brickify's venv has it)
"""
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WEB = Path(__file__).resolve().parent.parent
brand = (WEB / "src/lib/brand.ts").read_text()
name = re.search(r'APP_NAME = "([^"]+)"', brand).group(1)
tagline = re.search(r'APP_TAGLINE = "([^"]+)"', brand).group(1)

W, H = 1200, 630
YELLOW_TOP, YELLOW_BOTTOM, INK = (247, 184, 1), (243, 176, 0), (26, 26, 26)
# Avenir Next Bold is the closest thing on macOS to the app's Figtree black
FONT = "/System/Library/Fonts/Avenir Next.ttc"

img = Image.new("RGB", (W, H), YELLOW_TOP)
draw = ImageDraw.Draw(img)
for y in range(H):  # the same top-to-bottom warmth as the app's yellow
    t = y / H
    draw.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(YELLOW_TOP, YELLOW_BOTTOM)))

mark = Image.open(WEB / "public/brand/mark-512.png").convert("RGBA")
side = 380
mark.thumbnail((side, side))
img.paste(mark, (80, (H - mark.height) // 2), mark)

x = 80 + side + 60
title = ImageFont.truetype(FONT, 104, index=0)
body = ImageFont.truetype(FONT, 42, index=2)
lines = [s.strip() for s in tagline.split(".") if s.strip()]
block = 128 + len(lines) * 58
y = (H - block) // 2
draw.text((x, y), name, font=title, fill=INK)
y += 150
for line in lines:
    draw.text((x, y), line + ".", font=body, fill=INK)
    y += 58

out = WEB / "public/brand/og.png"
img.save(out)
print("wrote", out, f"({name})")
