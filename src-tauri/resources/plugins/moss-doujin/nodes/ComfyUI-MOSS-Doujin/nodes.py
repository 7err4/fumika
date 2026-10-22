# -*- coding: utf-8 -*-
"""ComfyUI nodes for MOSS-Image doujin pages: character sentence, page JSON builder, layout preview, stray-bubble mask, pages -> PDF."""
import os

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

import folder_paths

from . import bubbles, layouts

DEFAULT_STYLE = "Black and white manga page, ink lineart, screentone shading, clean black panel borders, white gutters, English text"
CAT = "MOSS Doujin"


class MossDoujinCharacter:
    """Identity + outfit as one reusable sentence. Paste the SAME sentence into every panel - that is what keeps a character
    consistent over 40 pages."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "identity": ("STRING", {"multiline": True, "default": "an adult woman in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes"}),
            "outfit": ("STRING", {"multiline": True, "default": "white oversized shirt with rolled-up sleeves, black ribbon tie, black pleated skirt"}),
            "name": ("STRING", {"default": "Fumika"}),
        }}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("character",)
    FUNCTION = "build"
    CATEGORY = CAT

    def build(self, identity, outfit, name):
        s = f"{name} ({identity.strip()})" if name.strip() else identity.strip()
        return (f"{s}, wearing {outfit.strip()}" if outfit.strip() else s,)


class MossDoujinPage:
    """Builds the MOSS JSON layout prompt for one page. panels = one description per line (placeholders {A} {B} {C} {D} are
    replaced by the character inputs). text = one item per line: panel | kind | text  (kinds: speech, sfx, narration, box,
    title, subtitle; \\n = line break). Connect `prompt` to CLIPTextEncode, width/height to EmptyFlux2LatentImage."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "layout": (list(layouts.LAYOUTS), {"default": "3a"}),
            "width": ("INT", {"default": 1024, "min": 512, "max": 4096, "step": 16}),
            "height": ("INT", {"default": 1536, "min": 512, "max": 4096, "step": 16}),
            "style": ("STRING", {"multiline": True, "default": DEFAULT_STYLE}),
            "panels": ("STRING", {"multiline": True, "default": "{A} sits at her desk late at night\nClose-up of {A} yawning\n{A} inks a manga page"}),
            "text": ("STRING", {"multiline": True, "default": "1 | narration | Tokyo, 2 a.m.\n2 | speech | So tired...\n3 | speech | One more page."}),
            "note": ("STRING", {"multiline": True, "default": "", "tooltip": "extra summary sentence, e.g. 'Fixed camera: all four panels show the same room from exactly the same camera angle.' or the spread note"}),
            "scene_in_summary": ("BOOLEAN", {"default": False, "tooltip": "repeat the panel descriptions in the summary (helps style LoRAs trained with scene captions)"}),
            "only_listed_text": ("BOOLEAN", {"default": True, "tooltip": "append 'Only the listed text boxes, no other text.'"}),
        }, "optional": {
            "A": ("STRING", {"forceInput": True}), "B": ("STRING", {"forceInput": True}),
            "C": ("STRING", {"forceInput": True}), "D": ("STRING", {"forceInput": True}),
            "reading_direction": (["left to right", "right to left"], {"default": "left to right", "tooltip": "right to left = manga order: panel 1 and the first bubble start on the right"}),
        }}
    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("prompt", "width", "height")
    FUNCTION = "build"
    CATEGORY = CAT

    def build(self, layout, width, height, style, panels, text, note, scene_in_summary, only_listed_text, A="", B="", C="", D="",
              reading_direction="left to right"):
        chars = {"A": A, "B": B, "C": C, "D": D}
        fill = lambda s: s.replace("{A}", chars["A"]).replace("{B}", chars["B"]).replace("{C}", chars["C"]).replace("{D}", chars["D"])
        js, _ = layouts.page_json(style.strip().rstrip("."), layout, [fill(p) for p in layouts.parse_panels(panels)],
                                  layouts.parse_bubbles(text), width, height, note.strip(), scene_in_summary, only_listed_text,
                                  "rtl" if reading_direction == "right to left" else "ltr")
        return (js, width, height)


class MossDoujinLayoutPreview:
    """Draws the panels (grey) and text boxes (red) of a page prompt - check the layout before spending GPU time."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"prompt": ("STRING", {"forceInput": True}), "width": ("INT", {"forceInput": True}), "height": ("INT", {"forceInput": True})}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "draw"
    CATEGORY = CAT

    def draw(self, prompt, width, height):
        import json
        d = json.loads(prompt); im = Image.new("RGB", (width, height), "white"); dr = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default(size=max(18, width // 40))
        except TypeError:   # Pillow < 10.1
            font = ImageFont.load_default()
        for it in d["items"]:
            y1, x1, y2, x2 = it["bbox"]; b = (x1 + width // 2, y1 + height // 2, x2 + width // 2, y2 + height // 2)
            if it["label"] == "panel":
                dr.rectangle(b, outline=(0, 0, 0), width=6, fill=(235, 235, 235)); dr.text((b[0] + 10, b[1] + 10), it["caption"][:60], fill=(60, 60, 60), font=font)
            else:
                dr.rectangle(b, outline=(220, 0, 0), width=4); dr.text((b[0] + 8, b[1] + 8), it.get("text", "")[:40], fill=(220, 0, 0), font=font)
        return (torch.from_numpy(np.array(im).astype(np.float32) / 255.0)[None],)


class MossStrayBubbleMask:
    """Finds speech bubbles that were NOT prompted (gibberish) by comparing detected bubbles with the text boxes of the page
    prompt. Outputs a mask of the stray ones and a pre-filled image (bubble + lettering erased with OpenCV inpainting).
    Feed prefilled -> VAEEncode -> SetLatentNoiseMask(mask) -> KSampler (denoise ~0.55 colour, ~0.7 screentone) -> VAEDecode ->
    ImageCompositeMasked(destination = original image, mask). Best on colour pages; dense screentone stays the hard case."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",), "prompt": ("STRING", {"forceInput": True}),
            "margin": ("INT", {"default": 60, "min": 0, "max": 400, "tooltip": "px a bubble may sit outside its prompted box and still count as prompted"}),
            "dilate": ("INT", {"default": 14, "min": 0, "max": 64}),
            "min_glyphs": ("INT", {"default": 4, "min": 1, "max": 40, "tooltip": "letter-like blobs a bubble must contain (filters faces / white shapes)"}),
        }}
    RETURN_TYPES = ("MASK", "IMAGE", "INT")
    RETURN_NAMES = ("mask", "prefilled", "stray_count")
    FUNCTION = "run"
    CATEGORY = CAT

    def run(self, image, prompt, margin, dilate, min_glyphs):
        masks, fills, n = [], [], 0
        for img in image:
            rgb = (img.cpu().numpy() * 255).clip(0, 255).astype(np.uint8); H, W = rgb.shape[:2]
            m, f, k, _ = bubbles.stray_mask(rgb, layouts.text_boxes_from_json(prompt, W, H), margin, dilate, min_glyphs)
            masks.append(torch.from_numpy(m.astype(np.float32) / 255.0)); fills.append(torch.from_numpy(f.astype(np.float32) / 255.0)); n += k
        return (torch.stack(masks), torch.stack(fills), n)


class MossPagesToPDF:
    """Saves a batch (or list) of page images as one PDF in the output folder."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "filename": ("STRING", {"default": "doujin"}),
                             "max_long_side": ("INT", {"default": 1600, "min": 512, "max": 4096})}}
    INPUT_IS_LIST = True
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = CAT

    def save(self, images, filename, max_long_side):
        filename, mls = filename[0], max_long_side[0]; pages = []
        for batch in images:
            for img in batch:
                im = Image.fromarray((img.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)); im.thumbnail((mls, mls)); pages.append(im.convert("RGB"))
        out = os.path.join(folder_paths.get_output_directory(), f"{filename}.pdf")
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=100, quality=85)
        return {"ui": {"text": [out]}}


from .easy import MossEasyDoujinBook, MossEasyDoujinPage  # noqa: E402
from .freeze import MossDoujinFreezeLook, register_folder  # noqa: E402

register_folder()

NODE_CLASS_MAPPINGS = {"MossEasyDoujinBook": MossEasyDoujinBook, "MossEasyDoujinPage": MossEasyDoujinPage, "MossDoujinCharacter": MossDoujinCharacter, "MossDoujinPage": MossDoujinPage,
                       "MossDoujinLayoutPreview": MossDoujinLayoutPreview, "MossStrayBubbleMask": MossStrayBubbleMask,
                       "MossPagesToPDF": MossPagesToPDF, "MossDoujinFreezeLook": MossDoujinFreezeLook}
NODE_DISPLAY_NAME_MAPPINGS = {"MossEasyDoujinBook": "MOSS Easy Doujin Book (whole manga)", "MossEasyDoujinPage": "MOSS Easy Doujin Page (one node)", "MossDoujinCharacter": "MOSS Doujin Character", "MossDoujinPage": "MOSS Doujin Page (JSON layout)",
                              "MossDoujinLayoutPreview": "MOSS Doujin Layout Preview", "MossStrayBubbleMask": "MOSS Stray Bubble Mask",
                              "MossPagesToPDF": "MOSS Pages to PDF", "MossDoujinFreezeLook": "MOSS Doujin Freeze Look (WD tagger)"}
