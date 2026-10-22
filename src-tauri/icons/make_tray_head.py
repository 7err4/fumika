"""Tray icon v2 (21 Oct): Fumika's head as hand-placed 16x16 pixel art (after mascot_lora/assets/fumika/head_0_3.png) - ink-black
hair with the light-blue streak in her bangs, light-blue eyes, low ponytail to the right, white collar with the black ribbon.
A grey 1 px outline keeps the black hair visible on a dark taskbar. Saved as tray.png at 32x32 (exact 2x nearest, so Windows'
16 px tray downscale gives back the original pixels) plus tray-preview.png (dark / light taskbar at 16 and 32 px, 4x).
The previous app-tile icon stays available: make_tray_tile.py."""
from PIL import Image
import os

PIX = [
    "....OOOOOOO.....",
    "...OKKKKKKKOO...",
    "..OKKKKKKKKKKO..",
    ".OKKKBBKKKKKKKO.",
    ".OKKBBKKKKKKKKO.",
    ".OKBBKKKKKKKKKO.",
    ".OKBBKSKKKSKKKO.",
    ".OKBSSSSKSSSSKOO",
    ".OKKSKKSSSKKSKKO",
    ".OKKSEESSSEESKKO",
    ".OKKSEESSSEESKKO",
    ".OKKSSSSMSSSSKKO",
    "..OKKSSSSSSSKKKO",
    "..OKKKSSSSSKOKKO",
    "...OOWWWWWWOOKO.",
    ".....OWKKWO..O..",
]
COL = {".": (0, 0, 0, 0), "O": (92, 98, 106, 255), "K": (21, 21, 21, 255), "B": (132, 196, 244, 255), "S": (250, 226, 212, 255),
       "E": (52, 142, 214, 255), "M": (196, 112, 112, 255), "W": (255, 255, 255, 255)}
assert len(PIX) == 16 and all(len(row) == 16 for row in PIX), [len(r) for r in PIX]

im = Image.new("RGBA", (16, 16))
im.putdata([COL[c] for row in PIX for c in row])
here = os.path.dirname(os.path.abspath(__file__))
im.resize((32, 32), Image.NEAREST).save(os.path.join(here, "tray.png"))

prev = Image.new("RGBA", (4 * 52 + 4, 56), (0, 0, 0, 0))
for i, (bg, size) in enumerate([((32, 32, 32, 255), 16), ((32, 32, 32, 255), 32), ((243, 243, 243, 255), 16), ((243, 243, 243, 255), 32)]):
    tile = Image.new("RGBA", (48, 48), bg)
    tile.alpha_composite(im.resize((size, size), Image.NEAREST), ((48 - size) // 2, (48 - size) // 2))
    prev.paste(tile, (4 + i * 52, 4))
prev.resize((prev.width * 4, prev.height * 4), Image.NEAREST).save(os.path.join(here, "tray-preview.png"))
print("ok")

# macOS menu bar (for the later Mac build): a template image - black + alpha only, macOS tints it for light / dark menu bars.
# Hair, outline, eyes and the ribbon stay solid; face and collar become holes so the head still reads as a silhouette.
tpl = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
tpl.putdata([(0, 0, 0, 255) if c in "OKBE" else (0, 0, 0, 0) for row in PIX for c in row])
tpl.resize((32, 32), Image.NEAREST).save(os.path.join(here, "tray-macTemplate@2x.png"))
tpl.save(os.path.join(here, "tray-macTemplate.png"))
