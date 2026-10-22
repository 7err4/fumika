# -*- coding: utf-8 -*-
"""Story text -> panel descriptions + text items for layouts.page_json. No ComfyUI imports (unit tests, the app's tools).

Page syntax: one line per panel   what happens | text | text
  !text = sound effect, >text = narration box, #text = title, ##text = subtitle, anything else = speech bubble
  Fumika: text         spoken by Fumika (bubble on her side, tail at her)
  +Fumika: text        a second bubble of Fumika, connected to her previous one (no own tail)
  Fumika & Sora: text  both say it (one centred bubble, one tail per speaker)
A colon only marks a speaker when the name is in the character list, so "Note: ..." stays plain text."""
import re

SIDES = {"ltr": ("left", "right"), "rtl": ("right", "left")}


def parse_characters(characters):
    """'Name: description' per line -> [(name, description)]"""
    out = []
    for ln in characters.splitlines():
        name, _, desc = ln.partition(":")
        if name.strip() and desc.strip():
            out.append((name.strip(), desc.strip()))
    return out


def split_speaker(t, names):
    """'+Fumika & Sora: text' -> (["Fumika", "Sora"], connected, "text"). Unknown names -> ([], False, t) unchanged."""
    m = re.match(r"^(\+)?\s*([^:\n]{1,80}?)\s*:\s*(.+)$", t, re.S)
    if not m:
        return [], False, t
    low = {n.lower(): n for n in names}
    who = [low.get(w.strip().lower()) for w in m.group(2).split("&")]
    if not who or None in who:
        return [], False, t
    return list(dict.fromkeys(who)), bool(m.group(1)), m.group(3).strip()


def _placeholders(desc, names):
    """mark every whole-word name as @@k@@ (k = index in names, longest names first so 'Casual Fumika' beats 'Fumika')"""
    for k in sorted(range(len(names)), key=lambda i: -len(names[i])):
        desc = re.sub(rf"(?<![\w@])\b{re.escape(names[k])}\b", f"@@{k}@@", desc)
    return desc


def _sides_sentence(cast, side_of):
    parts = [f"{n} {'is ' if i == 0 else ''}" + (f"on the {side_of[n]} side" + (" of the panel" if i == 0 else "")
                                                if side_of[n] != "middle" else "in the middle") for i, n in enumerate(cast)]
    return (parts[0] + "." if len(parts) == 1 else
            ", ".join(parts[:-1]) + " and " + parts[-1] + "." if len(parts) > 2 else parts[0] + ", " + parts[1] + ".")


def panel_sides(desc, speakers, names, direction="ltr"):
    """-> ({name: side}, sentence to append or ""). Only for panels with a named speaker and at least two characters.
    Sides the user wrote ("Sora stands on the left") win; the rest follows the order of first speakers (first speaker =
    the side that is read first)."""
    ph = _placeholders(desc, names)
    mentioned = [names[int(k)] for k in re.findall(r"@@(\d+)@@", ph)]
    cast = list(dict.fromkeys(speakers + mentioned))
    if not speakers or len(cast) < 2:
        return {}, ""
    first, second = SIDES[direction]
    written = {}
    for n in cast:
        m = re.search(rf"@@{names.index(n)}@@[^.;,@]*?\b(left|right)\b", ph, re.I)
        if m:
            written[n] = m.group(1).lower()
    free = [s for s in (first, second) if s not in written.values()] + ["middle"]
    side_of = dict(written)
    for n in cast:
        if n not in side_of and free:
            side_of[n] = free.pop(0)
    rest = [n for n in cast if n in side_of and n not in written]   # sides the user wrote are already in the text
    return side_of, (_sides_sentence(rest, side_of) if rest else "")


def parse_page(page, characters, ref_name=None, direction="ltr"):
    """page: one line per panel 'what happens | text | text'. characters: one per line 'Name: description'. ref_name: the
    character a reference picture shows ("" = the first one, None = no picture) - she is described as the one in Picture 1.
    -> (panel descriptions, text items (panel, text, kind, spec), has_title). spec for speech: {"who": [(name, side)],
    "connected": bool}; side = left / right / middle / None (only one character in the panel)."""
    chars = [(n, f"{n} ({d})") for n, d in parse_characters(characters)]
    if ref_name is not None and chars:
        k = next((i for i, (n, _) in enumerate(chars) if n.lower() == ref_name.strip().lower()), 0)
        chars[k] = (chars[k][0], f"{chars[k][0]} (the character shown in Picture 1)")
    names = [n for n, _ in chars]
    panels, bub = [], []
    for ln in [x for x in page.splitlines() if x.strip()]:
        parts = [p.strip() for p in ln.split("|")]
        items = []
        for t in parts[1:]:
            if not t:
                continue
            kind = ("sfx" if t.startswith("!") else "subtitle" if t.startswith("##") else "title" if t.startswith("#") else
                    "narration" if t.startswith(">") else "speech")
            who, conn, text = split_speaker(t, names) if kind == "speech" else ([], False, t)
            text = text[1:].strip() if kind == "narration" else text.lstrip("!#").strip() if kind != "speech" else text
            items.append((text, kind, who, conn))
        speakers = list(dict.fromkeys(n for _, _, who, _ in items for n in who))
        side_of, sentence = panel_sides(parts[0], speakers, names, direction)
        desc = parts[0] if not sentence else parts[0].rstrip(" .") + ". " + sentence
        # first mention of each name -> full description (keeps characters consistent)
        desc = _placeholders(desc, names)
        for k, (name, full) in enumerate(chars):
            desc = desc.replace(f"@@{k}@@", full, 1).replace(f"@@{k}@@", name)
        panels.append(desc)
        for text, kind, who, conn in items:
            spec = {"who": [(n, side_of.get(n)) for n in who], "connected": conn} if who else None
            bub.append((len(panels) - 1, text, kind, spec))
    return panels, bub, any(b[2] == "title" for b in bub)
