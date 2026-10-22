# -*- coding: utf-8 -*-
"""Freeze the look: read the clothing of a drawn page with the WD tagger and turn each vaguely written item ("patterned scarf")
into the concrete wording the page shows ("grey checkered scarf"), so the later pages of a scene draw the same piece.
Tested 21 Oct (research_moss/freeze_test.py): colour reliable, pattern only when a Danbooru tag exists for it.
freeze_items() has no ComfyUI imports (unit tests)."""
import json
import os

COLOURS = ("red", "blue", "green", "yellow", "orange", "purple", "pink", "brown", "black", "white", "grey", "gray", "beige",
           "aqua", "light blue", "dark blue", "light brown", "dark green", "navy", "silver", "gold")
# words that describe what happens to the piece, not what it looks like
STATES = {"open", "removed", "unworn", "holding", "adjusting", "untied", "torn", "wet", "partially", "lifted", "pulled", "off", "no"}


def _noun(wording):
    return wording.lower().split()[-1] if wording.strip() else ""


def freeze_item(wording, tags):
    """wording: the item as written ("patterned scarf"); tags: [(tag, score)] best first.
    -> (frozen wording, the tags it was built from). One colour (the best scoring), other look words in score order."""
    noun = _noun(wording)
    if not noun:
        return wording, []
    hits = [(t, s) for t, s in tags if t.lower().split()[-1] == noun and t.lower() != noun]
    colour, other, used = None, [], []
    for t, _ in hits:
        mod = t.lower()[: -len(noun)].strip()
        if not mod or any(w in STATES for w in mod.split()):
            continue
        if mod in COLOURS or mod.replace("-", " ") in COLOURS:
            if colour is None:
                colour = mod.replace("gray", "grey"); used.append(t)
        elif mod not in other and len(other) < 2:
            other.append(mod); used.append(t)
    if colour is None and not other:
        return wording, []
    return " ".join([w for w in [colour] if w] + other + [noun]), used


def freeze_items(items, tags):
    """items: wordings, one per item -> {wording: frozen}"""
    return {w: freeze_item(w, tags)[0] for w in items if w.strip()}


class MossDoujinFreezeLook:
    """Reads the clothing of a finished page (WD eva02-large tagger v3, Apache-2.0, runs on the CPU in about a second) and
    returns a concrete wording per item. page = path inside the output folder ("doujin_studio/Deadline/p01_00001_.png").
    items = one wording per line ("patterned scarf"). Output: JSON {"items": {wording: frozen}, "tags": [...]}."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "page": ("STRING", {"default": ""}),
            "items": ("STRING", {"multiline": True, "default": "patterned scarf"}),
            "threshold": ("FLOAT", {"default": 0.35, "min": 0.05, "max": 0.95, "step": 0.01}),
        }}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("frozen",)
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "MOSS Doujin"
    _model = None

    def run(self, page, items, threshold):
        import folder_paths
        from PIL import Image
        from . import wd_tagger
        out = os.path.realpath(folder_paths.get_output_directory())
        fp = os.path.realpath(os.path.join(out, page))
        if not fp.startswith(out + os.sep) or not os.path.isfile(fp):
            raise ValueError(f"page {page!r} not found in the output folder")
        if MossDoujinFreezeLook._model is None:
            w = folder_paths.get_full_path("wd_tagger", "wd-eva02-large-tagger-v3.safetensors")
            c = folder_paths.get_full_path("wd_tagger", "wd-eva02-large-tagger-v3_tags.csv")
            if not w or not c:
                raise ValueError("WD tagger files not found in models/wd_tagger (wd-eva02-large-tagger-v3.safetensors + _tags.csv)")
            MossDoujinFreezeLook._model = wd_tagger.load(w, c)
        tags = wd_tagger.tag(*MossDoujinFreezeLook._model, Image.open(fp), threshold)
        res = json.dumps({"items": freeze_items(items.splitlines(), tags), "tags": [t for t, _ in tags]}, ensure_ascii=False)
        print(f"[MOSS Freeze] {page}: {res[:300]}")
        return {"ui": {"text": [res]}, "result": (res,)}


def register_folder():
    """models/wd_tagger for the tagger weights + tag list"""
    import folder_paths
    if "wd_tagger" not in folder_paths.folder_names_and_paths:
        folder_paths.folder_names_and_paths["wd_tagger"] = ([os.path.join(folder_paths.models_dir, "wd_tagger")], {".safetensors", ".csv"})
