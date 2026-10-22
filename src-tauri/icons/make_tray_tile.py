"""Tray icon v1 (option, superseded 21 Oct by make_tray_head.py - running this writes tray.png back to the tile): the app icon as hand-placed 16x16 pixel art (ink tile, white page, three panels, the drawing panel hatched
in non-repro blue, blue trim marks). A grey 1 px rim keeps the tile visible on a dark taskbar. Saved as tray.png at
32x32 (exact 2x nearest, so Windows' 16 px tray downscale gives back the original pixels) plus tray-preview.png."""
from PIL import Image
import os

PIX = [
    "..RRRRRRRRRRRR..",
    ".RBBKKKKKKKKKKR.",
    "RKBKWWWWWWWWKKKR",
    "RKKKWKKKKKKWKKKR",
    "RKKKWKWWWWKWKKKR",
    "RKKKWKWWWWKWKKKR",
    "RKKKWKKKKKKWKKKR",
    "RKKKWWWWWWWWKKKR",
    "RKKKWKKKWWBWKKKR",
    "RKKKWKWKWBWWKKKR",
    "RKKKWKWKWWBWKKKR",
    "RKKKWKWKWBWWKKKR",
    "RKKKWKKKWWBWKKKR",
    "RKKKWWWWWWWWKBKR",
    ".RKKKKKKKKKKBBR.",
    "..RRRRRRRRRRRR..",
]
COL = {".": (0, 0, 0, 0), "R": (92, 98, 106, 255), "K": (21, 21, 21, 255), "W": (255, 255, 255, 255), "B": (111, 179, 232, 255)}
assert len(PIX) == 16 and all(len(row) == 16 for row in PIX)

im = Image.new("RGBA", (16, 16))
im.putdata([COL[c] for row in PIX for c in row])
here = os.path.dirname(__file__)
im.resize((32, 32), Image.NEAREST).save(os.path.join(here, "tray.png"))

prev = Image.new("RGBA", (4 * 52 + 4, 56), (0, 0, 0, 0))
for i, (bg, size) in enumerate([((32, 32, 32, 255), 16), ((32, 32, 32, 255), 32), ((243, 243, 243, 255), 16), ((243, 243, 243, 255), 32)]):
    tile = Image.new("RGBA", (48, 48), bg)
    tile.alpha_composite(im.resize((size, size), Image.NEAREST), ((48 - size) // 2, (48 - size) // 2))
    prev.paste(tile, (4 + i * 52, 4))
prev.resize((prev.width * 4, prev.height * 4), Image.NEAREST).save(os.path.join(here, "tray-preview.png"))
print("ok")
