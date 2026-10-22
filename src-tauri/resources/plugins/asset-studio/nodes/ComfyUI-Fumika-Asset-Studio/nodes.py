# -*- coding: utf-8 -*-
"""Fumika Asset Studio nodes: an asset sheet (expression set, outfits, turnaround, profile, item card, chibi stickers) as ONE
MOSS-Image JSON layout, an encoder that adds an optional reference picture (CharRef), and a cutout node that turns a sheet into
transparent PNG sprites (native ComfyUI background removal, ComfyUI >= 0.42)."""
import json
import os

import numpy as np
import torch
from PIL import Image

import folder_paths
import nodes as comfy_nodes

from . import sheets

REF_PREFIX = "Same character and art style as Picture 1."   # the caption prefix the CharRef LoRAs were trained with
NEGATIVE = "gibberish text, extra text, watermark, signature"


def _run(name, **kw):
    """call a stock / other pack's node (old or new API) and return its outputs tuple"""
    cls = comfy_nodes.NODE_CLASS_MAPPINGS[name]
    if hasattr(cls, "FUNCTION"):
        return getattr(cls(), cls.FUNCTION)(**kw)
    out = cls.execute(**kw)
    return out.result if hasattr(out, "result") else out


class FumikaAssetSheet:
    """Layout of one asset as a MOSS-Image JSON prompt + the cell boxes (for cutting sprites) + the image size."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "asset": (list(sheets.ASSETS), {"default": "expressions"}),
            "character": ("STRING", {"multiline": True, "default": "Fumika: an adult manga artist in her twenties with glossy black hair in a messy "
                                     "low ponytail with one light-blue streak in her bangs, light-blue eyes, white oversized shirt with rolled-up "
                                     "sleeves, black ribbon tie, black pleated skirt"}),
            "style": (list(sheets.STYLES), {"default": "Anime colour"}),
        }, "optional": {
            "fields": ("STRING", {"multiline": True, "default": "{}", "tooltip": "JSON: expressions / outfits / views / stats / quote / name / "
                                  "insets / card_title / card_text / card_art / chibi (one entry per line)"}),
            "labels": ("BOOLEAN", {"default": True, "tooltip": "small labels under the cells (off for clean sprites)"}),
        }}
    RETURN_TYPES = ("STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("prompt", "boxes", "width", "height")
    FUNCTION = "build"
    CATEGORY = "Fumika Asset Studio"

    def build(self, asset, character, style, fields="{}", labels=True):
        try:
            f = json.loads(fields or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"fields is not valid JSON: {e}")
        prompt, boxes, w, h = sheets.build(asset, character, f, style, labels)
        return (prompt, json.dumps(boxes), w, h)


class FumikaAssetEncode:
    """Positive + negative conditioning. With a reference picture the prompt goes through the MOSS edit encoder (needs the
    ComfyUI-MOSS-Image-Ostris-Edit nodes and a model patched with MOSSImageOstrisEditModelPatch + a CharRef LoRA)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clip": ("CLIP",), "vae": ("VAE",), "prompt": ("STRING", {"forceInput": True})},
                "optional": {"reference": ("IMAGE",)}}
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "encode"
    CATEGORY = "Fumika Asset Studio"

    def encode(self, clip, vae, prompt, reference=None):
        if reference is None:
            return (_run("CLIPTextEncode", clip=clip, text=prompt)[0], _run("CLIPTextEncode", clip=clip, text=NEGATIVE)[0])
        if "TextEncodeMOSSImageOstrisEdit" not in comfy_nodes.NODE_CLASS_MAPPINGS:
            raise ValueError("the reference picture needs the ComfyUI-MOSS-Image-Ostris-Edit nodes (ComfyUI 0.42 or newer)")
        img = _run("FluxKontextImageScale", image=reference)[0]
        pos = _run("TextEncodeMOSSImageOstrisEdit", clip=clip, vae=vae, image1=img, prompt=REF_PREFIX + " " + prompt)[0]
        neg = _run("TextEncodeMOSSImageOstrisEdit", clip=clip, vae=vae, image1=img, prompt="")[0]
        return (pos, neg)


def _save(arr, sub, name):
    od = os.path.join(folder_paths.get_output_directory(), sub)
    os.makedirs(od, exist_ok=True)
    fn = f"{name}.png"
    Image.fromarray(arr).save(os.path.join(od, fn), compress_level=4)
    return {"filename": fn, "subfolder": sub, "type": "output"}


class FumikaSpriteCutout:
    """Transparent background for a sheet (every version of the batch) and one PNG per layout cell (VN sprites).
    Writes <prefix>_<version>.png (RGBA sheet) and <prefix>_<version>_<cell>.png into the output folder."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "boxes": ("STRING", {"forceInput": True}),
                             "bg_removal_model": ("BACKGROUND_REMOVAL",),
                             "prefix": ("STRING", {"default": "fumika_assets/sprites"})},
                "optional": {"pad": ("INT", {"default": 6, "min": 0, "max": 64, "tooltip": "margin around each cut cell in px"}),
                             "threshold": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                                                     "tooltip": "0 = soft edges; >0 = hard alpha cut-off"})}}
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("rgba", "mask")
    FUNCTION = "cut"
    OUTPUT_NODE = True
    CATEGORY = "Fumika Asset Studio"

    def cut(self, images, boxes, bg_removal_model, prefix, pad=6, threshold=0.0):
        mask = bg_removal_model.encode_image(images)   # (B, H, W), 1 = foreground
        if threshold > 0:
            mask = (mask >= threshold).to(mask.dtype)
        rgba = torch.cat([images[..., :3], mask.unsqueeze(-1).to(images.dtype)], dim=-1).clamp(0, 1)
        sub, base = os.path.split(prefix.strip("/\\") or "fumika_assets/sprites")
        cells = json.loads(boxes or "[]")
        sheets_out, sprites = [], []
        for b in range(rgba.shape[0]):
            arr = (rgba[b].cpu().numpy() * 255).round().astype(np.uint8)
            sheets_out.append(_save(arr, sub, f"{base}_{b + 1}"))
            H, W = arr.shape[:2]
            for c in cells:
                y1, x1, y2, x2 = c["box"]
                y1, x1, y2, x2 = max(0, y1 - pad), max(0, x1 - pad), min(H, y2 + pad), min(W, x2 + pad)
                crop = arr[y1:y2, x1:x2]
                ys, xs = np.nonzero(crop[..., 3] > 8)   # trim to the visible figure
                if len(ys):
                    crop = crop[max(0, ys.min() - pad):ys.max() + pad + 1, max(0, xs.min() - pad):xs.max() + pad + 1]
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in c.get("name", "cell"))
                sprites.append(_save(crop, sub, f"{base}_{b + 1}_{safe}"))
        return {"ui": {"images": sheets_out, "sprites": sprites}, "result": (rgba, mask)}


NODE_CLASS_MAPPINGS = {"FumikaAssetSheet": FumikaAssetSheet, "FumikaAssetEncode": FumikaAssetEncode, "FumikaSpriteCutout": FumikaSpriteCutout}
NODE_DISPLAY_NAME_MAPPINGS = {"FumikaAssetSheet": "Fumika Asset Sheet", "FumikaAssetEncode": "Fumika Asset Encode (+ reference)",
                              "FumikaSpriteCutout": "Fumika Sprite Cutout (transparent PNGs)"}
