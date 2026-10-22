"""App icon v2 (21 Oct, user: taskbar should show Fumika like the tray): two drawings for two size ranges, as most apps do.
  large (48 px and up, macOS .icns, store logos): Fumika's drawn head (head-source.png = mascot_lora/assets/fumika/head_0_3.png)
        on a paper-white rounded tile in Apple's macOS icon grid (824 px body on a 1024 canvas, 100 px margin, corner radius 185,
        soft shadow), so the macOS build later gets a proper Big-Sur-style icon.
  small (16 / 24 / 32 px: Windows taskbar, title bar): since 22 Oct (user: "higher resolution in the taskbar and the title bar")
        the same drawn head on a tight tile (thin margin, thinner rim), downscaled with Lanczos + a light unsharp mask; also
        written as ../../public/app-icon.png (64 px) for the title bar. The tray keeps the 16x16 pixel head (make_tray_head.py).
Steps: python make_icon_head.py  ->  icon-source.png (large)  ->  npx tauri icon src-tauri/icons/icon-source.png
       ->  python make_icon_head.py ico  (rewrites icon.ico and 32x32.png with the pixel head for the small sizes)
The former manuscript-tile icon: make_icon.py."""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def pixel_head():
    import make_tray_head as T   # writes tray.png / tray-preview.png again (same pixels)
    return T.im


def large():
    S, M, R = 1024, 100, 185
    can = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh = Image.new("L", (S, S), 0)
    ImageDraw.Draw(sh).rounded_rectangle([M, M + 12, S - M, S - M + 12], radius=R, fill=110)
    can.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(18)))       # soft drop shadow (macOS look)
    body = S - 2 * M
    head = Image.open(os.path.join(HERE, "head-source.png")).convert("RGBA")
    head = head.crop((60, 0, 1024, 964)).resize((body, body), Image.LANCZOS)          # face a little left of centre -> recentre
    tile = Image.new("RGBA", (body, body), (255, 255, 255, 255))
    tile.alpha_composite(head)
    mask = Image.new("L", (body, body), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, body - 1, body - 1], radius=R, fill=255)
    can.paste(tile, (M, M), mask)
    ImageDraw.Draw(can).rounded_rectangle([M, M, S - M - 1, S - M - 1], radius=R, outline=(21, 21, 21, 255), width=10)   # ink rim
    can.save(os.path.join(HERE, "icon-source.png")); print("icon-source.png")


def tight(s):
    """drawn head on a full-size tile for the small sizes: drawn at 256 px, then scaled down"""
    S = 256
    M, R = 6, 52
    body = S - 2 * M
    head = Image.open(os.path.join(HERE, "head-source.png")).convert("RGBA")
    head = head.crop((60, 0, 1024, 964)).resize((body, body), Image.LANCZOS)          # same framing as the large icon
    tile = Image.new("RGBA", (body, body), (255, 255, 255, 255))
    tile.alpha_composite(head)
    mask = Image.new("L", (body, body), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, body - 1, body - 1], radius=R, fill=255)
    can = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    can.paste(tile, (M, M), mask)
    ImageDraw.Draw(can).rounded_rectangle([M, M, S - M - 1, S - M - 1], radius=R, outline=(21, 21, 21, 255), width=8)
    out = can.resize((s, s), Image.LANCZOS)
    return out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=1)) if s <= 32 else out


def save_ico(frames, path):
    """ICO with the LARGEST entry first: Tauri takes the first entry as the window icon (taskbar, Alt+Tab), Explorer and
    the installer pick the fitting size themselves. Written by hand because Pillow orders the entries small to large."""
    import io, struct
    frames = sorted(frames, key=lambda f: -f.width)
    blobs = []
    for f in frames:
        b = io.BytesIO(); f.save(b, "PNG"); blobs.append(b.getvalue())
    out = struct.pack("<HHH", 0, 1, len(frames))
    off = 6 + 16 * len(frames)
    for f, b in zip(frames, blobs):
        out += struct.pack("<BBBBHHII", f.width % 256, f.height % 256, 0, 0, 1, 32, len(b), off)
        off += len(b)
    open(path, "wb").write(out + b"".join(blobs))


def ico():
    small = {s: tight(s) for s in (16, 24, 32)}
    src = Image.open(os.path.join(HERE, "icon-source.png")).convert("RGBA")
    frames = [small[16], small[24], small[32]] + [src.resize((s, s), Image.LANCZOS) for s in (48, 64, 128, 256)]
    save_ico(frames, os.path.join(HERE, "icon.ico"))
    small[32].save(os.path.join(HERE, "32x32.png"))
    tight(64).save(os.path.join(HERE, "..", "..", "public", "app-icon.png"))
    got = Image.open(os.path.join(HERE, "icon.ico")); print("icon.ico", sorted(got.info.get("sizes", [])))
    prev = Image.new("RGBA", (16 + 24 + 32 + 64 + 60, 80), (32, 32, 32, 255))
    x = 10
    for s in (16, 24, 32, 64):
        prev.alpha_composite(small.get(s) or tight(64), (x, 8)); x += s + 12
    prev.resize((prev.width * 4, prev.height * 4), Image.NEAREST).save(os.path.join(HERE, "small-preview.png"))


if __name__ == "__main__":
    ico() if sys.argv[1:] == ["ico"] else large()
