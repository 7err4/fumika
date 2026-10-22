# -*- coding: utf-8 -*-
"""One-node doujin page for beginners: 3-4 fields. Loads the MOSS models itself (cached), picks the panel layout from the number
of lines, builds the JSON layout, renders 3 seeds and returns the one with the fewest stray (unprompted) speech bubbles."""
import random
import re

import numpy as np
import torch

import folder_paths
import nodes as comfy_nodes

from . import bubbles, layouts
from .story import parse_page  # noqa: F401  (kept importable from here)
from . import expert

STYLES = {
    "Colour manga": "Full color anime manga page, clean lineart, cel shading, black panel borders, white gutters, English text",
    "Black & white manga": "Black and white manga page, ink lineart, screentone shading, clean black panel borders, white gutters, English text",
    "3D game render comic": "Full color 3D rendered comic page in the style of 3D game screenshots, glossy materials, cinematic lighting, black panel borders, white gutters, English text",
}
COVER_STYLES = {
    "Colour manga": "Full color anime manga cover illustration, detailed, glossy anime CG style",
    "Black & white manga": "Full color anime manga cover illustration, detailed, glossy anime CG style",
    "3D game render comic": "Full color 3D game render doujinshi cover in the style of 3D game screenshots, glossy materials, cinematic lighting",
}
REF_PREFIX = "Same character and art style as Picture 1."   # the caption prefix the CharRef LoRAs were trained with
AUTO_LAYOUT ={1: "full", 2: "2h", 3: "3a", 4: "4g", 5: "5"}
_CACHE = {}


def _pick(kind, key):
    hit = [f for f in folder_paths.get_filename_list(kind) if key in f.lower()]
    if not hit:
        raise ValueError(f"{key} not found in models/{kind} - see the README for the model files")
    return hit[0]


def _run(name, **kw):
    """call a stock ComfyUI node (old or new API) and return its outputs tuple"""
    cls = comfy_nodes.NODE_CLASS_MAPPINGS[name]
    if hasattr(cls, "FUNCTION"):
        return getattr(cls(), cls.FUNCTION)(**kw)
    out = cls.execute(**kw)
    return out.result if hasattr(out, "result") else out


AUTO = "auto (find it by name)"
KEYS = {"diffusion_models": ("moss_image", "kromoss", "moss"), "text_encoders": ("qwen3.5", "qwen3_5", "qwen35"), "vae": ("flux2", "flux.2", "flux_2"),
        "loras": ("8step", "dmd")}


def _first(kind, key=None):
    """dropdown: 'auto' first (works on every PC - the saved workflow does not depend on my file names), then the user's files"""
    return [AUTO] + (folder_paths.get_filename_list(kind) or [])


def _resolve(kind, name, what):
    """'auto' -> the first file whose name contains one of the known keywords (any sub-folder); explicit name -> must exist"""
    fs = folder_paths.get_filename_list(kind)
    if name and name != AUTO:
        if name not in fs:
            raise ValueError(f"{what}: '{name}' not found in models/{kind}")
        return name
    for k in KEYS[kind]:
        hit = [f for f in fs if k in f.lower().replace(" ", "")]
        if hit:
            return sorted(hit, key=lambda f: ("base" not in f.lower(), len(f)))[0]
    raise ValueError(f"{what}: no MOSS-Image file found in models/{kind}. Download it (see README) or pick your file in the '{what}' field.")


DIRECTIONS = {"left to right": "ltr", "right to left": "rtl"}
SIZES = {"page 1024x1536": (1024, 1536), "big page 1344x2048": (1344, 2048), "square 1280x1280": (1280, 1280)}
SPEEDS = {"fast (8 steps, turbo LoRA)": "fast", "quality (50 steps)": "quality", "auto (quality only for title pages)": "auto"}


NO_TURBO = "none (always 50 steps)"


def _turbo_choices():
    """turbo LoRA list: files that look like the 8-step DMD LoRA first, then 'none', then all other LoRAs"""
    fs = folder_paths.get_filename_list("loras")
    hit = [f for f in fs if "8step" in f.lower() or "dmd" in f.lower()]
    return hit + [NO_TURBO] + [f for f in fs if f not in hit]


def settings_inputs():
    """optional settings shared by the page and the book node - all have working defaults, beginners can ignore them"""
    return {
        "character_lora": (["none"] + folder_paths.get_filename_list("loras"), {"default": "none", "tooltip": "write the LoRA trigger word in the character line"}),
        "lora_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
        # model files: every list is the user's own folder content, the matching file (by name) is preselected
        "base_model": (_first("diffusion_models", "moss_image"), {"tooltip": "MOSS-Image Base (moss_image_base_bf16) or a MOSS fine-tune (e.g. Kromoss)"}),
        "text_encoder": (_first("text_encoders", "qwen3.5"), {"tooltip": "Qwen3.5-9B text encoder of MOSS-Image"}),
        "vae": (_first("vae", "flux2"), {"tooltip": "FLUX.2 VAE"}),
        "turbo_lora": ([AUTO, NO_TURBO] + folder_paths.get_filename_list("loras"), {"tooltip": "8-step DMD turbo LoRA for fast mode - auto finds it by name; none = every page uses the 50-step mode"}),
        "speed": (list(SPEEDS), {"default": "auto (quality only for title pages)"}),
        "versions": ("INT", {"default": 3, "min": 1, "max": 8, "tooltip": "versions per page; the one with the fewest gibberish bubbles is kept"}),
        "page_size": (list(SIZES), {"default": "page 1024x1536"}),
        "seed": ("INT", {"default": 0, "min": 0, "max": 2**31 - 1, "tooltip": "0 = random every Run"}),
        # v1.1: extra LoRAs (e.g. a second character or a style LoRA), appended at the END so saved workflows keep their values.
        # Several LoRAs can fight each other - lower the strengths (0.6-0.8) if faces or styles start to mix.
        "lora_2": (["none"] + folder_paths.get_filename_list("loras"), {"default": "none", "tooltip": "optional second LoRA (second character or a style)"}),
        "lora_2_strength": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.05}),
        "lora_3": (["none"] + folder_paths.get_filename_list("loras"), {"default": "none", "tooltip": "optional third LoRA"}),
        "lora_3_strength": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.05}),
        # v1.2: reference picture (CharRef). The main character is drawn after this picture ("Picture 1"); needs the
        # ComfyUI-MOSS-Image-Ostris-Edit nodes (ComfyUI >= 0.42) and a CharRef edit LoRA (e.g. moss_image_charref_v2).
        "reference": ("IMAGE", {"tooltip": "optional picture of the main character - the pages draw her after it"}),
        "reference_lora": (["none"] + folder_paths.get_filename_list("loras"), {"default": "none", "tooltip": "CharRef edit LoRA used with the reference picture"}),
        "reference_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
        # v1.3 (app test 21 Oct): the written look of that character overruled the picture -> her description is replaced by
        # "the character shown in Picture 1" while a reference is connected
        "reference_character": ("STRING", {"default": "", "tooltip": "name from the character list the picture shows (empty = the first one); her written description is ignored while a picture is connected"}),
        # v1.4 (22 Oct): speakers ("Fumika: text") put the bubble on her side; the reading direction decides which side is read first.
        # 1.3 placed the first bubble top RIGHT (manga order) even for English text -> dialogue read backwards
        "reading_direction": (list(DIRECTIONS), {"default": "left to right", "tooltip": "left to right for English text; right to left = manga order (panels and the first bubble start on the right)"}),
        # v1.5 (22 Oct): expert overrides - "auto" / 0 keeps the tested recipe of the chosen speed
        "sampler": ([expert.AUTO] + _list("SAMPLERS"), {"default": expert.AUTO, "tooltip": "auto = euler"}),
        "scheduler": ([expert.AUTO] + _list("SCHEDULERS"), {"default": expert.AUTO, "tooltip": "auto = sgm_uniform (quality) / simple (fast)"}),
        "steps": ("INT", {"default": 0, "min": 0, "max": 200, "tooltip": "0 = auto (50 quality / 8 fast)"}),
        "cfg": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 20.0, "step": 0.1, "tooltip": "0 = auto (3 quality / 1 fast)"}),
        "slg_layers": ("STRING", {"default": expert.AUTO, "tooltip": "skip layer guidance: auto = layer 22 in quality mode, off, or layers like 22 or 20,22"}),
        # v1.6 (22 Oct): any number of further LoRAs, JSON list [{"name": ..., "strength": ...}] (the app's LoRA list)
        "loras": ("STRING", {"default": "[]", "tooltip": "more LoRAs as a JSON list of {name, strength}, applied after the three above"}),
        "negative": ("STRING", {"default": expert.AUTO, "multiline": False, "tooltip": "off = none; auto = 'extra speech bubbles, gibberish text, watermark' in quality mode (needs cfg > 1)"}),
    }


def _list(name):
    """sampler / scheduler names of this ComfyUI"""
    import comfy.samplers
    return list(getattr(comfy.samplers.KSampler, name, []))


def _models(o):
    bm, te, va = (_resolve("diffusion_models", o["base_model"], "base_model"), _resolve("text_encoders", o["text_encoder"], "text_encoder"),
                  _resolve("vae", o["vae"], "vae"))
    tl = None if o["turbo_lora"] == NO_TURBO else _resolve("loras", o["turbo_lora"], "turbo_lora")
    key = (bm, te, va, tl)
    if _CACHE.get("key") != key:   # keep only one model set in memory
        _CACHE.clear()
        print(f"[MOSS Easy] models: {bm} | {te} | {va} | turbo: {tl}")
        unet = _run("UNETLoader", unet_name=bm, weight_dtype="default")[0]
        clip = _run("CLIPLoader", clip_name=te, type="moss_image", device="default")[0]
        vae = _run("VAELoader", vae_name=va)[0]
        turbo = None if tl is None else _run("LoraLoaderModelOnly", model=unet, lora_name=tl, strength_model=1.0)[0]
        _CACHE.update(key=key, m=(unet, turbo, clip, vae))
    return _CACHE["m"]


def _opts(kw):
    d = {"character_lora": "none", "lora_strength": 1.0, "base_model": AUTO, "text_encoder": AUTO, "vae": AUTO,
         "speed": "auto (quality only for title pages)", "turbo_lora": AUTO,
         "versions": 3, "page_size": "page 1024x1536", "seed": 0,
         "lora_2": "none", "lora_2_strength": 0.8, "lora_3": "none", "lora_3_strength": 0.8,
         "reference": None, "reference_lora": "none", "reference_strength": 1.0, "reference_character": "", "reading_direction": "left to right",
         "sampler": expert.AUTO, "scheduler": expert.AUTO, "steps": 0, "cfg": 0.0, "slg_layers": expert.AUTO, "negative": expert.AUTO, "loras": "[]"}
    d.update({k: v for k, v in kw.items() if v is not None})
    if not d["seed"]:
        d["seed"] = random.randint(1, 2**31 - 1)
    return d


class MossEasyDoujinPage:
    """EASY MODE - one node, one finished page.
    characters: one line per character   Name: what they look like and wear
    page: one line per panel (1-5 lines)   what happens | speech bubble | another bubble
          ! in front of a bubble = sound effect, # = big title (covers), ## = small subtitle under it (e.g. ## by Fumika - keeps covers
          free of invented taglines). Speakers: | Fumika: text  (bubble on her side), | +Fumika: text (joined to her last bubble),
          | Fumika & Sora: text (both say it)
    Press Run - the node draws 3 versions and keeps the cleanest."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "style": (list(STYLES), {"default": "Colour manga"}),
            "characters": ("STRING", {"multiline": True, "default":
                "Fumika: an adult manga artist in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes, white oversized shirt with rolled-up sleeves, black ribbon tie, black pleated skirt\n"
                "Sora: her editor, an adult woman with short silver hair and glasses, navy blazer, white blouse, grey pencil skirt"}),
            "page": ("STRING", {"multiline": True, "default":
                "Fumika sags over a blank manga page at her desk late at night, a cold coffee mug beside her | Nothing...\n"
                "Her phone lights up on the desk with a message from Sora | !BZZT\n"
                "Close-up of Fumika, panicking | Seven pages by tomorrow?!"}),
        }, "optional": settings_inputs()}
    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("page", "all_versions")
    FUNCTION = "render"
    CATEGORY = "MOSS Doujin"

    @classmethod
    def IS_CHANGED(cls, seed=0, **kw):
        return random.random() if not seed else seed   # seed 0 = new versions every Run

    def render(self, style, characters, page, **kw):
        o = _opts(kw)
        return render_page(style, characters, page, o, o["seed"])


def render_page(style, characters, page, o, seed):
    """-> (best image, all versions). Shared by the page and the book node. o = settings from _opts()"""
    direction = DIRECTIONS.get(o["reading_direction"], "ltr")
    panels, bub, title = parse_page(page, characters, o["reference_character"] if o.get("reference") is not None else None, direction)
    if not 1 <= len(panels) <= 5:
        raise ValueError(f"a page needs 1 to 5 panel lines, this one has {len(panels)}:\n{page}")
    lay = AUTO_LAYOUT[len(panels)]; W, H = SIZES[o["page_size"]]
    slow = {"fast": False, "quality": True, "auto": title}[SPEEDS[o["speed"]]]   # titles need the slow mode to be spelled right
    # covers: illustration style instead of "manga page" (the page style invites magazine-like taglines on a cover);
    # tested 20 Oct: negative wording like "no tagline" makes it worse
    cover = title and len(panels) == 1
    sty = COVER_STYLES.get(style, STYLES[style]) if cover else STYLES[style]
    # cover test 21 Oct (research_moss/cover_test.py, 3 seeds each): without help every cover got invented kanji / taglines / badges;
    # a real subtitle claims the author slot and this POSITIVE sentence the rest -> 3 of 3 clean, title spelled right every time
    sub = any(b[2] == "subtitle" for b in bub)
    note = (f"The title logo{' and the small subtitle are' if sub else ' is'} the only lettering on the cover; everything else is pure "
            "illustration.") if cover else ""
    js, boxes = layouts.page_json(sty, lay, panels, bub, W, H, note=note, direction=direction)
    unet, turbo, clip, vae = _models(o)
    slow = slow or turbo is None
    model = unet if slow else turbo
    for name, w in ((o["character_lora"], o["lora_strength"]), (o["lora_2"], o["lora_2_strength"]), (o["lora_3"], o["lora_3_strength"]),
                    *expert.lora_list(o["loras"])):
        if name != "none" and w:
            model = _run("LoraLoaderModelOnly", model=model, lora_name=name, strength_model=w)[0]
    ref = o.get("reference")
    if ref is not None:   # CharRef: reference latents through the edit patch, then the CharRef LoRA (tested on whole pages 21 Oct)
        if "MOSSImageOstrisEditModelPatch" not in comfy_nodes.NODE_CLASS_MAPPINGS:
            raise ValueError("the reference picture needs the ComfyUI-MOSS-Image-Ostris-Edit nodes (ComfyUI 0.42 or newer)")
        model = _run("MOSSImageOstrisEditModelPatch", model=model, kv_cache=True)[0]
        if o["reference_lora"] != "none" and o["reference_strength"]:
            model = _run("LoraLoaderModelOnly", model=model, lora_name=o["reference_lora"], strength_model=o["reference_strength"])[0]
    sm = expert.sampling(o, slow)
    if sm["slg"]:
        model = _run("SkipLayerGuidanceDiTSimple", model=model, double_layers="", single_layers=sm["slg"], start_percent=0.0, end_percent=1.0)[0]
    if ref is not None:
        img = _run("FluxKontextImageScale", image=ref)[0]
        pos = _run("TextEncodeMOSSImageOstrisEdit", clip=clip, vae=vae, image1=img, prompt=REF_PREFIX + " " + js)[0]
        neg = _run("TextEncodeMOSSImageOstrisEdit", clip=clip, vae=vae, image1=img, prompt="")[0]
    else:
        pos = _run("CLIPTextEncode", clip=clip, text=js)[0]
        neg = _run("CLIPTextEncode", clip=clip, text=sm["negative"])[0]
    lat = _run("EmptyFlux2LatentImage", width=W, height=H, batch_size=1)[0]
    imgs, scores = [], []
    for k in range(o["versions"]):
        s = _run("KSampler", model=model, seed=seed + k, steps=sm["steps"], cfg=sm["cfg"], sampler_name=sm["sampler"],
                 scheduler=sm["scheduler"], positive=pos, negative=neg, latent_image=lat, denoise=1.0)[0]
        im = _run("VAEDecode", samples=s, vae=vae)[0]
        scores.append(bubbles.stray_mask((im[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8), boxes)[2]); imgs.append(im)
    best = min(range(len(imgs)), key=lambda k: (scores[k], k))
    ex = expert.differs(o, slow)
    print(f"[MOSS Easy] seed {seed}, {sm['steps']} steps cfg {sm['cfg']} {sm['sampler']}/{sm['scheduler']} slg {sm['slg'] or 'off'}"
          f"{' (expert: ' + ', '.join(ex) + ')' if ex else ''}, stray bubbles per version {scores} -> keeping version {best + 1}")
    return imgs[best], torch.cat(imgs, 0)


class MossEasyDoujinBook:
    """EASY MODE - a whole manga in one Run.
    characters: one line per character   Name: what they look like and wear
    story: one block per page, pages separated by an empty line. Inside a page: one line per panel
           what happens | speech bubble        (! = sound effect, # = big title, ## = subtitle, e.g. on the cover)
    Every page is drawn 3 times and the cleanest version is kept. The pages and a PDF are saved to output/doujin/<title>/."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "title": ("STRING", {"default": "my_doujin"}),
            "style": (list(STYLES), {"default": "Colour manga"}),
            "characters": ("STRING", {"multiline": True, "default":
                "Fumika: an adult manga artist in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes, white oversized shirt with rolled-up sleeves, black ribbon tie, black pleated skirt\n"
                "Sora: her editor, an adult woman with short silver hair and glasses, navy blazer, white blouse, grey pencil skirt"}),
            "story": ("STRING", {"multiline": True, "default":
                "Fumika grins at the viewer holding up a dip pen in front of a pile of manga pages | #DEADLINE!\n"
                "\n"
                "Fumika sags over a blank manga page at her desk late at night, a cold coffee mug beside her | Nothing...\n"
                "Her phone lights up on the desk with a message from Sora | !BZZT\n"
                "Close-up of Fumika, panicking | Seven pages by tomorrow?!\n"
                "\n"
                "Fumika stares out of the window at the city lights, deep in thought | ...\n"
                "Fumika's eyes light up, a light bulb above her head | That's it!\n"
                "Fumika inks a page at full speed, ink drops flying | !SCRATCH SCRATCH\n"
                "\n"
                "Morning sun through the window, Fumika asleep on her desk on a stack of finished pages | Zzz...\n"
                "Sora opens the door holding two coffees, surprised | Fumika...?\n"
                "Sora smiles at the finished pages, Fumika gives a sleepy thumbs up | Made it..."}),
        }, "optional": settings_inputs()}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("pages",)
    FUNCTION = "render"
    CATEGORY = "MOSS Doujin"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, seed=0, **kw):
        return random.random() if not seed else seed

    def render(self, title, style, characters, story, **kw):
        o = _opts(kw)
        import os
        import comfy.utils
        from PIL import Image
        pages = [b.strip() for b in re.split(r"\n\s*\n", story.strip()) if b.strip()]
        if not pages:
            raise ValueError("story is empty - write one block per page, pages separated by an empty line")
        name = "".join(c for c in title if c.isalnum() or c in "-_ ").strip() or "doujin"
        od = os.path.join(folder_paths.get_output_directory(), "doujin", name); os.makedirs(od, exist_ok=True)
        pbar = comfy.utils.ProgressBar(len(pages)); seed = o["seed"]; out, pil = [], []
        for i, pg in enumerate(pages, 1):
            best, _ = render_page(style, characters, pg, o, seed + 1000 * i)
            im = Image.fromarray((best[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8))
            im.save(os.path.join(od, f"p{i:02d}.png")); pil.append(im.convert("RGB")); out.append(best); pbar.update(1)
            print(f"[MOSS Easy Book] page {i}/{len(pages)} done")
        pil[0].save(os.path.join(od, f"{name}.pdf"), save_all=True, append_images=pil[1:], resolution=100, quality=88)
        return {"ui": {"text": [f"{len(pages)} pages + PDF saved to {od}"]}, "result": (torch.cat(out, 0),)}
