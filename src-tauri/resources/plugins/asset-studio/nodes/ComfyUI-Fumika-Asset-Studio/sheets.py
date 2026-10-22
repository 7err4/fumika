# -*- coding: utf-8 -*-
"""Asset sheet layouts for MOSS-Image JSON prompts (abs_centralized, yxyx). One asset = one image with fixed boxes, so the same
character appears in every cell. No ComfyUI imports here, so it also works from plain Python scripts and tests.

build(asset, character, fields, style) -> (prompt_json, boxes, width, height)
  boxes: [{"name": ..., "box": [y1, x1, y2, x2]}] in top-left pixel coordinates (the cells to cut sprites from)"""
import json

STYLES = {
    "Anime colour": "Clean anime illustration style: crisp lineart, flat cel shading, soft colours.",
    "Ink manga": "Clean manga illustration style: crisp black ink lineart, flat cel shading, ink black and paper white.",
    "Soft painted": "Soft painted anime illustration style: gentle shading, warm light, detailed eyes.",
}
ASSETS = ("expressions", "outfits", "turnaround", "profile", "card", "chibi", "pixel")
SIZES = {"expressions": (1536, 1536), "outfits": (1536, 1152), "turnaround": (1536, 1152), "profile": (1024, 1536),
         "card": (1024, 1536), "chibi": (1536, 1024), "pixel": (1536, 768)}
DEFAULTS = {
    "expressions": "neutral\nhappy smile\nlaughing\nangry\nsad\nsurprised\nembarrassed, blushing\nsmug grin\nsleepy",
    "outfits": "Default: her default outfit\nCasual: a grey oversized hoodie and black shorts\nFestival: a navy yukata with a white floral pattern\n"
               "Winter: a long beige winter coat, a red scarf and black boots",
    "views": "front view\nside view, facing left\nback view, from behind",
    "stats": "JOB: MANGA ARTIST\nLIKES: COFFEE\nTOOL: DIP PEN",
    "quote": "",
    "insets": "close-up of her eyes\nclose-up of her shoes",   # concrete objects: vague wording got lettered as captions
    "card_title": "LUCKY ITEM",
    "card_text": "A short description of the item.",
    "card_art": "a glowing magic item floating above an open book",
    "chibi": "waving\nsleeping\nholding a giant pen\ncrying with joy\ndrinking coffee\nthumbs up",
}


def lines(s):
    return [x.strip() for x in str(s).splitlines() if x.strip()]


def who(character):
    """'Name: looks' (first non-empty line) -> (name, description sentence)"""
    first = (lines(character) or ["the character"])[0]
    name, _, desc = first.partition(":")
    name = name.strip() or "the character"
    return name, (f"{name}, {desc.strip()}" if desc.strip() else name)


def grid(rows, cols, y0=.02, y1=.98, x0=.02, x1=.98, gap=.012):
    h, w = (y1 - y0 - gap * (rows - 1)) / rows, (x1 - x0 - gap * (cols - 1)) / cols
    return [(y0 + r * (h + gap), x0 + c * (w + gap), y0 + r * (h + gap) + h, x0 + c * (w + gap) + w) for r in range(rows) for c in range(cols)]


def px(fr, W, H):
    y1, x1, y2, x2 = fr
    return [round(y1 * H), round(x1 * W), round(y2 * H), round(x2 * W)]


def centred(b, W, H):
    return [b[0] - H // 2, b[1] - W // 2, b[2] - H // 2, b[3] - W // 2]


class Sheet:
    def __init__(self, W, H):
        self.W, self.H, self.items, self.boxes = W, H, [], []

    def panel(self, fr, caption, name=None):
        b = px(fr, self.W, self.H)
        self.items.append({"label": "panel", "bbox": centred(b, self.W, self.H), "caption": caption})
        if name is not None:
            self.boxes.append({"name": name, "box": b})

    def text(self, fr, text, caption):
        self.items.append({"label": "text", "bbox": centred(px(fr, self.W, self.H), self.W, self.H), "text": text, "caption": caption})

    def label_under(self, fr, text, h=.035):
        self.text((fr[2] - h, fr[1] + .01, fr[2] - .004, fr[3] - .01), text, "small clean uppercase label")

    def json(self, summary):
        return json.dumps({"summary": {"caption": summary + " Only the listed text, no other text."}, "items": self.items,
                           "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}, ensure_ascii=False)


def _get(fields, key):
    v = fields.get(key)
    return DEFAULTS[key] if v is None or str(v).strip() == "" else v


def build(asset, character, fields=None, style="Anime colour", labels=True):
    if asset not in ASSETS:
        raise ValueError(f"unknown asset '{asset}' - one of {', '.join(ASSETS)}")
    f = fields or {}
    W, H = SIZES[asset]
    name, desc = who(character)
    sty = STYLES.get(style, STYLES["Anime colour"])
    s = Sheet(W, H)
    if asset == "expressions":
        ex = (lines(_get(f, "expressions")) + lines(DEFAULTS["expressions"]))[:9]
        for k, (fr, e) in enumerate(zip(grid(3, 3), ex)):
            s.panel(fr, f"bust portrait of {name}, front view, {e}", f"{k + 1:02d}_{e.split(',')[0]}")
            if labels:
                s.label_under(fr, e.split(",")[0].upper())
        summ = (f"Visual novel character expression sheet of {desc}. The same bust portrait nine times on a plain light grey background, "
                f"same angle, same pose, same outfit, only the facial expression changes. {sty}")
    elif asset == "outfits":
        outs = (lines(_get(f, "outfits")) + lines(DEFAULTS["outfits"]))[:4]
        for k, (fr, o) in enumerate(zip(grid(1, 4, y0=.03, y1=.97), outs)):
            lab, _, what = o.partition(":")
            what = what.strip() or lab.strip()
            s.panel(fr, f"full-body {name}, standing, front view, wearing {what}", f"{k + 1:02d}_{lab.strip()}")
            if labels:
                s.label_under(fr, lab.strip().upper())
        summ = (f"Character outfit sheet of {desc}. Four full-body views side by side on a plain white background, same standing pose, "
                f"same face and hair, only the outfit changes. {sty}")
    elif asset == "turnaround":
        views = (lines(_get(f, "views")) + lines(DEFAULTS["views"]))[:3]
        for k, (fr, v) in enumerate(zip(grid(1, 3, y0=.03, y1=.97), views)):
            s.panel(fr, f"full-body {name}, {v}", f"{k + 1:02d}_{v.split(',')[0]}")
            if labels:
                s.label_under(fr, v.split(" ")[0].upper())
        summ = (f"Character model sheet turnaround of {desc}. Three full-body views on a plain white background, same scale, "
                f"neutral standing pose with arms slightly away from the body. {sty}")
    elif asset == "profile":
        ins = (lines(_get(f, "insets")) + lines(DEFAULTS["insets"]))[:2]
        s.panel((.03, .45, .96, .98), f"full-body {name}, standing, smile, looking at viewer", "figure")
        s.panel((.03, .02, .40, .43), f"large framed close-up of {name}'s face, smiling", "face")
        # engine test 21 Oct: the inset wording was lettered as a caption -> say it is a picture without text
        # engine test 21 Oct (2nd): MOSS still letters a caption under each inset -> give it the caption (last word, "EYES")
        for k, (x1, x2) in enumerate(((.02, .21), (.23, .43))):
            s.panel((.42, x1, .57, x2), f"small round inset picture, no text: {ins[k]}", f"inset_{k + 1}")
            s.text((.575, x1 + .01, .60, x2 - .01), ins[k].split()[-1].upper(), "small clean uppercase label")
        s.text((.62, .03, .80, .42), "\n".join(lines(_get(f, "stats"))[:5]), "stat list in small clean uppercase letters")
        quote = str(f.get("quote") or "").strip()
        if quote:
            s.text((.82, .03, .88, .42), quote, "big slanted comic lettering quote")
        s.text((.90, .03, .97, .42), str(f.get("name") or name).upper(), "name plate, large name lettering")
        # engine test 21 Oct: stray header / inset captions / handwritten notes appeared -> forbid them by name
        summ = (f"Character profile sheet of {desc}. Clean infographic layout on a light paper background with thin blue frames. "
                f"No title at the top, no captions under the inset pictures, no handwritten notes, no numbers, no decorative text. {sty}")
    elif asset == "card":
        s.panel((.08, .12, .58, .88), "illustration window: " + str(_get(f, "card_art")), "art")
        s.text((.60, .14, .66, .86), str(_get(f, "card_title")).upper(), "title banner lettering")
        s.text((.68, .16, .88, .84), str(_get(f, "card_text")), "description box with small clean text")
        summ = ("A single fantasy item card on a plain dark background: ornate card frame with a gem at the top, an illustration window, "
                f"a title banner and a description box. {sty}")
    elif asset == "pixel":
        # experimental (21 Oct): a real side-view walk cycle comes out on some seeds only -> render several versions and pick.
        # The style must win over character LoRAs (the app caps them at 0.4); no downscale / palette post-process (ruins colours)
        for k in range(4):
            x = .02 + k * .245
            s.panel((.1, x, .9, x + .225), f"16-bit pixel-art game sprite of {desc}, walking to the right, side view, walk cycle frame {k + 1} of 4",
                    f"frame_{k + 1}")
        summ = ("Retro 16-bit pixel-art sprite sheet for a 2D game: four frames of a walk cycle of the same character, side view, facing right, "
                "identical size and baseline, chunky visible pixels, limited 16-colour palette, no anti-aliasing, flat solid light green "
                "background. No text.")
        return json.dumps({"summary": {"caption": summ}, "items": s.items, "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"},
                          ensure_ascii=False), s.boxes, W, H
    else:   # chibi
        acts = (lines(_get(f, "chibi")) + lines(DEFAULTS["chibi"]))[:6]
        for k, (fr, a) in enumerate(zip(grid(2, 3), acts)):
            s.panel(fr, f"chibi {name} {a}", f"{k + 1:02d}_{a.split(' ')[0]}")
        summ = (f"Sticker sheet: six chibi versions of {desc}. Super-deformed chibi, big head, tiny body, white sticker outline, "
                f"plain white background. {sty}")
    return s.json(summ), s.boxes, W, H
