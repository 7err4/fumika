# -*- coding: utf-8 -*-
"""Page JSON builder for MOSS-Image layout prompts (abs_centralized, yxyx). Shared by the nodes; no ComfyUI imports here so it can
also be used from plain Python scripts."""
import json

MARGIN = 16   # outer margin and gutter in px
# panel rectangles as fractions (y1, x1, y2, x2) of the page
LAYOUTS = {
    "full": [(0, 0, 1, 1)],
    "2h": [(0, 0, .5, 1), (.5, 0, 1, 1)],
    "2v": [(0, 0, 1, .5), (0, .5, 1, 1)],
    "3a": [(0, 0, .4, 1), (.4, 0, 1, .5), (.4, .5, 1, 1)],
    "3b": [(0, 0, .6, .5), (0, .5, .6, 1), (.6, 0, 1, 1)],
    "3v": [(0, 0, .33, 1), (.33, 0, .66, 1), (.66, 0, 1, 1)],
    "3s": [(0, 0, .3, 1), (.3, 0, .62, 1), (.62, 0, 1, 1)],
    "4g": [(0, 0, .5, .5), (0, .5, .5, 1), (.5, 0, 1, .5), (.5, .5, 1, 1)],
    "4b": [(0, 0, .3, .5), (0, .5, .3, 1), (.3, 0, .55, 1), (.55, 0, 1, 1)],
    "5": [(0, 0, .3, .5), (0, .5, .3, 1), (.3, 0, .6, 1), (.6, 0, 1, .5), (.6, .5, 1, 1)],
    "splash2": [(0, 0, .75, 1), (.75, 0, 1, 1)],
    "spread_a": [(0, 0, .45, .5), (0, .5, .45, 1), (.45, 0, 1, 1)],
    "spread_b": [(0, 0, 1, .5), (0, .5, .5, .75), (0, .75, .5, 1), (.5, .5, 1, 1)],
}
KINDS = ("speech", "sfx", "narration", "box", "title", "subtitle", "block")
CAPTIONS = {
    "speech": "white rounded speech bubble with black hand-lettered text",
    "sfx": "big bold hand-lettered sound effect drawn inside the panel",
    "narration": "rectangular narration box with black text",
    "box": "plain white rectangular text box with a thin black border and hand-lettered uppercase English text",
    "title": "large bold stylized title logo lettering",
    "subtitle": "small clean subtitle lettering",
    "block": "large white rectangular text block with a thin black border and black hand-lettered text, nothing else in the white area",
}
BOX_SLOTS = [(1, 0), (1, 1), (0, 0), (0, 1), (1, .5), (0, .5)]
NO_TEXT = ". No speech bubbles and no text in this panel"



def rects(layout, W, H, direction="ltr"):
    """panel rectangles in reading order; right-to-left (manga) mirrors the layout so panel 1 sits top right"""
    fr = LAYOUTS[layout] if direction != "rtl" else [(y1, 1 - x2, y2, 1 - x1) for y1, x1, y2, x2 in LAYOUTS[layout]]
    return [[round(y1 * H) + MARGIN, round(x1 * W) + MARGIN, round(y2 * H) - MARGIN, round(x2 * W) - MARGIN]
            for y1, x1, y2, x2 in fr]


def _at(name, side):
    return f"{name} on the {side}" if side in ("left", "right") else f"{name} in the middle" if side == "middle" else name


def speech_caption(who, connected):
    """bubble caption naming the speaker(s) - wordings tested 21 Oct (research_moss/bubble_scene_test.py, 3/3 seeds each)"""
    if connected:
        return f"{CAPTIONS['speech']}, connected to the speech bubble above it by a short neck, no tail of its own"
    if len(who) == 1:
        return f"{CAPTIONS['speech']}, its tail points down at {_at(*who[0])}"
    if len(who) == 2:
        return f"{CAPTIONS['speech']}, one bubble with two tails: one tail points down at {_at(*who[0])}, the other at {_at(*who[1])}"
    ns = [_at(*w) for w in who]
    return f"{CAPTIONS['speech']}, one bubble with {len(who)} tails pointing down at {', '.join(ns[:-1])} and {ns[-1]}"


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def speech_box(r, text, spec, st, direction="ltr"):
    """Place a speech bubble in panel r. st = the panel's placement state (bubbles placed so far). Bubbles go on the speaker's
    side, never above / before the previous bubble in reading order, never on top of another bubble.
    -> (box y1 x1 y2 x2, caption)"""
    ph, pw = r[2] - r[0], r[3] - r[1]
    first, second = ("left", "right") if direction != "rtl" else ("right", "left")
    rank = {first: 0, "middle": 1, second: 2}
    lines = text.count("\n") + 1; bh = min(int(ph * .32), 46 * lines + 50); bw = min(int(pw * .55), 300)
    who = [tuple(w) for w in (spec or {}).get("who", [])]
    connected = bool((spec or {}).get("connected")) and len(who) == 1
    if len(who) > 1:
        side = "middle"
    elif who and who[0][1]:
        side = who[0][1]
    else:   # no speaker / only one character in the panel: alternate, starting on the side that is read first
        side = first if st.setdefault("plain", 0) % 2 == 0 else second
        st["plain"] += 1
    x0 = r[1] + 12 if side == "left" else r[3] - 12 - bw if side == "right" else r[1] + (pw - bw) // 2
    prev = st.get("by", {}).get(who[0][0]) if connected else None
    if prev is not None and st["placed"] and st["placed"][-1][0] is prev[0]:
        b = prev[0]; y = b[2] + 24; x0 = b[1]; bw = b[3] - b[1]   # directly under her last bubble, joined by a short neck
    else:
        connected = False
        y = r[0] + 12
        last = st["placed"][-1][0] if st.get("placed") else None
        if last is not None:
            ls = st["placed"][-1][1]
            y = max(y, last[0] if rank[side] > rank[ls] else last[0] + (last[2] - last[0]) // 2 + 12)
        moved = True
        while moved:   # push down below any bubble it would cover
            moved = False
            for b, _ in st.get("placed", []):
                if _overlap((y, x0, y + bh, x0 + bw), b):
                    y = b[2] + 12; moved = True
        y = max(r[0] + 12, min(y, r[2] - 12 - bh))
    box = [y, x0, y + bh, x0 + bw]
    st.setdefault("placed", []).append((box, side))
    if len(who) == 1:
        st.setdefault("by", {})[who[0][0]] = (box, side)
    cap = speech_caption(who, connected) if who else CAPTIONS["speech"]
    return box, cap


def bubble_box(kind, r, text, n_kind, n_panel, W, H):
    """Place a text item inside panel rect r (top-left absolute px). n_kind / n_panel = how many items of this kind / in this panel came before."""
    ph, pw = r[2] - r[0], r[3] - r[1]
    if kind == "sfx":
        return [r[0] + int(ph * .45), r[1] + int(pw * .08), r[0] + int(ph * .45) + 120, r[1] + int(pw * .6)]
    if kind == "title":
        return [r[0] + 24, r[1] + 40, r[0] + 24 + int(ph * .16), r[3] - 40]
    if kind == "subtitle":
        return [r[2] - 24 - int(ph * .05), r[1] + int(pw * .2), r[2] - 24, r[3] - int(pw * .2)]
    if kind == "box":
        sy, sx = BOX_SLOTS[n_kind % len(BOX_SLOTS)]; bw = int(pw * .3); bh = min(int(ph * .28), 30 * (len(text) // 16 + 1) + 30)
        y0 = r[0] + 14 if sy == 0 else r[2] - 14 - bh; x0 = r[1] + 14 + int(sx * (pw - 28 - bw))
        return [y0, x0, y0 + bh, x0 + bw]
    if kind == "block":   # afterword / credits: one centred text block that fills the white area under the title
        return [r[0] + int(ph * .2), r[1] + int(pw * .1), r[0] + int(ph * .55), r[3] - int(pw * .1)]
    lines = text.count("\n") + 1; bh = min(int(ph * .32), 46 * lines + 50); bw = min(int(pw * .55), 300)
    if kind == "narration":
        return [r[0] + 10, r[1] + 10, r[0] + 10 + bh, r[1] + 10 + int(pw * .6)]
    return speech_box(r, text, None, {"placed": [], "plain": n_panel})[0]   # speech: see speech_box


def page_json(style, layout, panels, bubbles, W=1024, H=1536, note="", scene_in_summary=False, only_listed_text=True, direction="ltr"):
    """panels: list of panel descriptions (one per layout panel, in reading order). bubbles: list of (panel_index, text, kind)
    or (panel_index, text, kind, spec) with spec = {"who": [(name, side)], "connected": bool} for speech (see story.py).
    direction: "ltr" (English, default) or "rtl" (manga: panels and the first bubble start on the right).
    Returns (json string, list of absolute text boxes x1,y1,x2,y2) - the boxes are what the stray-bubble detector keeps."""
    rs = rects(layout, W, H, direction)
    if len(panels) != len(rs):
        raise ValueError(f"layout {layout} has {len(rs)} panels, got {len(panels)} panel descriptions")
    used = {b[0] for b in bubbles}; items = []
    for i, (r, desc) in enumerate(zip(rs, panels)):
        # a single text-free panel would print the note itself as a subtitle -> only on multi-panel pages
        cap = desc + ("" if i in used or (len(rs) == 1 and not bubbles) else NO_TEXT)
        items.append({"label": "panel", "bbox": centred(r, W, H), "caption": cap})
    per_kind, per_panel, speech, boxes = {}, {}, {}, []
    for bu in bubbles:
        pi, text, kind = bu[:3]; spec = bu[3] if len(bu) > 3 else None
        if kind not in KINDS:
            raise ValueError(f"unknown text kind {kind!r}, use one of {KINDS}")
        if kind == "speech":
            b, cap = speech_box(rs[pi], text, spec, speech.setdefault(pi, {"placed": []}), direction)
        elif kind == "narration":   # top corner that is read first; speech bubbles of the panel keep clear of it
            b, cap = bubble_box(kind, rs[pi], text, 0, 0, W, H), CAPTIONS[kind]
            if direction == "rtl":
                b = [b[0], rs[pi][1] + rs[pi][3] - b[3], b[2], rs[pi][1] + rs[pi][3] - b[1]]
            speech.setdefault(pi, {"placed": []})["placed"].append((b, "left" if direction != "rtl" else "right"))
        else:
            b, cap = bubble_box(kind, rs[pi], text, per_kind.get((pi, kind), 0), per_panel.get(pi, 0), W, H), CAPTIONS[kind]
        per_kind[(pi, kind)] = per_kind.get((pi, kind), 0) + 1; per_panel[pi] = per_panel.get(pi, 0) + 1
        items.append({"label": "text", "bbox": centred(b, W, H), "text": text, "caption": cap})
        boxes.append((b[1], b[0], b[3], b[2]))
    summ = f"{style}. A {len(rs)}-panel page." if len(rs) > 1 else f"{style}. A single full-page illustration."
    if note:
        summ += " " + note
    if scene_in_summary:
        summ += " " + " ".join(panels)
    if only_listed_text and bubbles:
        summ += " Only the listed text boxes, no other text."
    return json.dumps({"summary": {"caption": summ}, "items": items, "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"},
                      ensure_ascii=False), boxes


def centred(b, W, H):
    return [b[0] - H // 2, b[1] - W // 2, b[2] - H // 2, b[3] - W // 2]


def text_boxes_from_json(js, W, H):
    """Absolute x1,y1,x2,y2 boxes of all text items of a MOSS page JSON (for the stray-bubble detector)."""
    d = json.loads(js)
    return [(i["bbox"][1] + W // 2, i["bbox"][0] + H // 2, i["bbox"][3] + W // 2, i["bbox"][2] + H // 2)
            for i in d.get("items", []) if i.get("label") == "text"]


def parse_panels(text):
    """One panel per line; blank lines ignored."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def parse_bubbles(text):
    """One text item per line: <panel number starting at 1> | <kind> | <text>  (use \\n inside the text for a line break)."""
    out = []
    for n, ln in enumerate(text.splitlines(), 1):
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split("|", 2)]
        if len(parts) != 3:
            raise ValueError(f"bubble line {n}: expected 'panel | kind | text', got {ln!r}")
        out.append((int(parts[0]) - 1, parts[2].replace("\\n", "\n"), parts[1]))
    return out
