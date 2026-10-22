"""App icon: a manuscript page on an ink tile - three ink panels, one still hatched in non-repro blue, blue trim marks.
Drawn at 4x and downsampled. Run once, then: npx tauri icon src-tauri/icons/icon-source.png"""
from PIL import Image, ImageChops, ImageDraw
import os

S = 4096                      # 4x of 1024
INK, SHEET, NR = (21, 21, 21), (255, 255, 255), (111, 179, 232)
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
u = S / 1024

# tile (rounded square, the taskbar/tray silhouette)
d.rounded_rectangle([40 * u, 40 * u, 984 * u, 984 * u], radius=210 * u, fill=INK)

# page (portrait, 2:3)
x0, y0, x1, y1 = 262 * u, 170 * u, 762 * u, 854 * u
d.rectangle([x0, y0, x1, y1], fill=SHEET)

# blue trim marks outside two corners
w, L = 22 * u, 92 * u
g = 40 * u
d.rectangle([x0 - g - w, y0 - g - w, x0 - g + L, y0 - g], fill=NR)
d.rectangle([x0 - g - w, y0 - g - w, x0 - g, y0 - g + L], fill=NR)
d.rectangle([x1 + g - L, y1 + g, x1 + g + w, y1 + g + w], fill=NR)
d.rectangle([x1 + g, y1 + g - L, x1 + g + w, y1 + g + w], fill=NR)

# panels: wide top, two below; bottom-right still being drawn (blue hatching)
m, gap, bw = 44 * u, 30 * u, 26 * u
px0, py0, px1, py1 = x0 + m, y0 + m, x1 - m, y1 - m
mid = py0 + (py1 - py0) * 0.46
cx = (px0 + px1) / 2
panels = [(px0, py0, px1, mid - gap / 2), (px0, mid + gap / 2, cx - gap / 2, py1), (cx + gap / 2, mid + gap / 2, px1, py1)]
for i, (a, b, c, e) in enumerate(panels):
    if i == 2:
        hatch = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hatch)
        step = 70 * u
        k = -S
        while k < S * 2:
            hd.line([(k, e), (k + (e - b), b)], fill=NR + (255,), width=int(16 * u))
            k += step
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rectangle([a + bw, b + bw, c - bw, e - bw], fill=255)
        im.paste(hatch, (0, 0), ImageChops.multiply(hatch.split()[3], mask))
        d.rectangle([a, b, c, e], outline=NR, width=int(bw))
    else:
        d.rectangle([a, b, c, e], outline=INK, width=int(bw))

out = os.path.join(os.path.dirname(__file__), "icon-source.png")
im.resize((1024, 1024), Image.LANCZOS).save(out)
print(out)
