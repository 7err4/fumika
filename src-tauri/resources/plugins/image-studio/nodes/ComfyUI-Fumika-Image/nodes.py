# -*- coding: utf-8 -*-
"""Image Studio node: load a picture the app already has (a finished page / asset / image in the output folder, or a picture the
user imported into the input folder) and bring it to a size MOSS-Image can encode (multiple of 16, long side capped).
fit() has no ComfyUI imports (unit tests)."""
import os


def fit(w, h, width=0, height=0, scale=1.0, max_side=2048, multiple=16):
    """-> (target w, target h, crop box or None). width/height > 0: cover-crop to that size; else scale the picture.
    The long side is capped at max_side, both sides are rounded down to the multiple (at least one multiple)."""
    if width > 0 and height > 0:
        tw, th = width, height
        r = max(tw / w, th / h)   # cover: scale so both sides reach the target, then crop the middle
        cw, ch = tw / r, th / r
        box = (round((w - cw) / 2), round((h - ch) / 2), round((w + cw) / 2), round((h + ch) / 2))
    else:
        tw, th, box = w * scale, h * scale, None
    k = min(1.0, max_side / max(tw, th))
    tw, th = tw * k, th * k
    snap = lambda v: max(multiple, int(v) // multiple * multiple)
    return snap(tw), snap(th), box


def target_short(w, h, scale, multiple=16):
    """short edge after upscaling by scale, rounded to the multiple (SeedVR2 takes the target short edge)"""
    return max(multiple, round(min(w, h) * scale / multiple) * multiple)


def resolve(source, output_dir, input_dir):
    """'output:sub/x.png' / 'input:fumika_refs/x.png' -> absolute path inside that folder (anything leaving it is refused)"""
    kind, _, rel = source.partition(":")
    base = {"output": output_dir, "input": input_dir}.get(kind)
    if base is None or not rel:
        raise ValueError(f"source must be 'output:<path>' or 'input:<path>', got {source!r}")
    base = os.path.realpath(base)
    fp = os.path.realpath(os.path.join(base, rel))
    if not fp.startswith(base + os.sep) or not os.path.isfile(fp):
        raise ValueError(f"picture {source!r} not found")
    return fp


class FumikaLoadSource:
    """Loads a picture from the output or input folder ('output:fumika_images/x_00001_.png') and resizes it for MOSS-Image:
    width + height > 0 = cover-crop to that size, otherwise scale it by `scale`; long side at most max_side, sides multiples of 16."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source": ("STRING", {"default": ""}),
            "width": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 16, "tooltip": "0 = keep the picture's proportions"}),
            "height": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 16}),
            "scale": ("FLOAT", {"default": 1.0, "min": 0.25, "max": 4.0, "step": 0.05}),
            "max_side": ("INT", {"default": 2048, "min": 256, "max": 4096, "step": 16}),
        }, "optional": {
            "target_scale": ("FLOAT", {"default": 1.0, "min": 1.0, "max": 4.0, "step": 0.05, "tooltip": "for upscalers that want a target size: short edge x this"}),
        }}
    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT")
    RETURN_NAMES = ("image", "width", "height", "target_short_edge")
    FUNCTION = "load"
    CATEGORY = "Fumika"

    def load(self, source, width, height, scale, max_side, target_scale=1.0):
        import numpy as np
        import torch
        from PIL import Image
        import folder_paths
        im = Image.open(resolve(source, folder_paths.get_output_directory(), folder_paths.get_input_directory())).convert("RGB")
        tw, th, box = fit(im.width, im.height, width, height, scale, max_side)
        if box:
            im = im.crop(box)
        im = im.resize((tw, th), Image.LANCZOS)
        return (torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0)[None], tw, th, target_short(tw, th, target_scale))


def parse_loras(text):
    """'[{"name": "a.safetensors", "strength": 0.8}, ...]' -> [(name, strength)]; entries without a name or with strength 0 are
    skipped, so the app can send its list as it is"""
    import json
    if not text or not text.strip():
        return []
    out = []
    for e in json.loads(text):
        name, w = str(e.get("name", "")).strip(), float(e.get("strength", 1.0))
        if name and name != "none" and w:
            out.append((name, w))
    return out


class FumikaLoraStack:
    """Any number of LoRAs on a model, one after another (the app's LoRA list). loras = JSON list of {name, strength}.
    With a CLIP and clip_loras on (SDXL / Illustrious / Pony LoRAs train the text encoder too), the LoRA is applied to both;
    MOSS-Image and Anima LoRAs are model-only."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "loras": ("STRING", {"default": "[]", "multiline": True})},
                "optional": {"clip": ("CLIP",), "clip_loras": ("BOOLEAN", {"default": False})}}
    RETURN_TYPES = ("MODEL", "CLIP")
    FUNCTION = "apply"
    CATEGORY = "Fumika"

    def apply(self, model, loras, clip=None, clip_loras=False):
        import nodes as comfy_nodes
        both, only = comfy_nodes.LoraLoader(), comfy_nodes.LoraLoaderModelOnly()
        for name, w in parse_loras(loras):
            if clip is not None and clip_loras:
                model, clip = both.load_lora(model, clip, name, w, w)
            else:
                model = only.load_lora_model_only(model, name, w)[0]
        return (model, clip)


class FumikaModelLoader:
    """One loader for every model family: split files (MOSS-Image, Anima: diffusion model + text encoder + VAE) or a full
    checkpoint (SDXL / Illustrious / Pony, models/checkpoints). clip_skip > 0 = stop at the CLIP layer -clip_skip (2 for most
    anime SDXL models). anima38 = the Anima 3.8B Pro52 bundle (DiT + Semantic Connector v2, needs the comfyui-anima-3-8B pack of
    the family plugin); its native Qwen3 0.6B encoder and VAE load like split."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "loader": (["split", "checkpoint", "anima38"], {"default": "split"}),
            "unet": ("STRING", {"default": "", "tooltip": "diffusion model (split) or checkpoint file"}),
            "text_encoder": ("STRING", {"default": ""}), "vae": ("STRING", {"default": ""}),
            "clip_type": ("STRING", {"default": "stable_diffusion"}),
            "clip_skip": ("INT", {"default": 0, "min": 0, "max": 12}),
        }}
    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    FUNCTION = "load"
    CATEGORY = "Fumika"

    def load(self, loader, unet, text_encoder, vae, clip_type, clip_skip):
        import nodes as comfy_nodes
        run = lambda name, **kw: _call(comfy_nodes.NODE_CLASS_MAPPINGS[name], **kw)
        if loader == "checkpoint":
            m, c, v = run("CheckpointLoaderSimple", ckpt_name=unet)[:3]
        else:
            if loader == "anima38":
                if "Anima38BV2Loader" not in comfy_nodes.NODE_CLASS_MAPPINGS:
                    raise RuntimeError("Anima 3.8B needs its node pack (comfyui-anima-3-8B): switch the Anima 3.8B plugin on in Setup")
                m = run("Anima38BV2Loader", model_name=unet)[0]
            else:
                m = run("UNETLoader", unet_name=unet, weight_dtype="default")[0]
            c = run("CLIPLoader", clip_name=text_encoder, type=clip_type, device="default")[0]
            v = run("VAELoader", vae_name=vae)[0]
        if clip_skip:
            c = run("CLIPSetLastLayer", clip=c, stop_at_clip_layer=-clip_skip)[0]
        return (m, c, v)


class FumikaPromptEncode:
    """The positive prompt for every family: a plain CLIPTextEncode, or - when `te2` names the Qwen3.5 4B encoder (Anima 3.8B
    Pro52) - the pack's Anima38BV2Prompt, which needs the model (its Semantic Connector), the native CLIP and the Qwen3.5 CLIP."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clip": ("CLIP",), "text": ("STRING", {"multiline": True, "default": ""})},
                "optional": {"model": ("MODEL",), "te2": ("STRING", {"default": "", "tooltip": "second text encoder file (Anima 3.8B: qwen35_4b)"})}}
    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "Fumika"

    def encode(self, clip, text, model=None, te2=""):
        import nodes as comfy_nodes
        run = lambda name, **kw: _call(comfy_nodes.NODE_CLASS_MAPPINGS[name], **kw)
        if not te2.strip():
            return run("CLIPTextEncode", clip=clip, text=text)
        if model is None or "Anima38BV2Prompt" not in comfy_nodes.NODE_CLASS_MAPPINGS:
            raise RuntimeError("Anima 3.8B prompts need the model and the comfyui-anima-3-8B pack (Anima 3.8B plugin in Setup)")
        q = run("AnimaQwen35Loader", qwen35_model=te2.strip())[0]
        return (run("Anima38BV2Prompt", model=model, native_clip=clip, qwen35_clip=q, prompt=text)[0],)


def _call(cls, **kw):
    """run a stock node (old or new API) and return its outputs"""
    if hasattr(cls, "FUNCTION"):
        return getattr(cls(), cls.FUNCTION)(**kw)
    out = cls.execute(**kw)
    return out.result if hasattr(out, "result") else out


# ---- inpaint (like A1111): the mask is painted in the app (white = redraw). "Only masked" cuts the masked area plus padding out,
# draws it at the model's size and pastes it back with a soft edge; "whole picture" redraws at full size inside the mask only.

def crop_box(bbox, w, h, padding, only_masked, multiple=16):
    """bbox (x0, y0, x1, y1) of the mask -> crop (x0, y0, x1, y1) inside the picture. Whole picture: everything."""
    if not only_masked or bbox is None:
        return (0, 0, w, h)
    x0, y0, x1, y1 = bbox
    x0, y0, x1, y1 = max(0, x0 - padding), max(0, y0 - padding), min(w, x1 + padding), min(h, y1 + padding)
    # at least one multiple wide / high, so tiny masks still give a usable patch
    if x1 - x0 < multiple:
        x1 = min(w, x0 + multiple); x0 = max(0, x1 - multiple)
    if y1 - y0 < multiple:
        y1 = min(h, y0 + multiple); y0 = max(0, y1 - multiple)
    return (x0, y0, x1, y1)


def work_size(cw, ch, target, multiple=16):
    """size the crop is drawn at: long side = target (small crops get enlarged = more detail), multiples of 16"""
    k = target / max(cw, ch)
    snap = lambda v: max(multiple, round(v * k / multiple) * multiple)
    return snap(cw), snap(ch)


class FumikaLoadMask:
    """Loads the painted mask (input:fumika_masks/x.png; white = redraw) at the size of the picture."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask": ("STRING", {"default": ""}), "image": ("IMAGE",)}}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "load"
    CATEGORY = "Fumika"

    def load(self, mask, image):
        import numpy as np
        import torch
        from PIL import Image
        import folder_paths
        m = Image.open(resolve(mask, folder_paths.get_output_directory(), folder_paths.get_input_directory()))
        m = (m.getchannel("A") if m.mode in ("RGBA", "LA") and m.getextrema()[-1][0] < 255 else m.convert("L"))
        m = m.resize((image.shape[2], image.shape[1]), Image.BILINEAR)
        return (torch.from_numpy(np.asarray(m, dtype=np.float32) / 255.0)[None],)


class FumikaInpaintCrop:
    """Cuts the masked area (+ padding) out and scales it to the model's size; whole picture = the full picture at that size.
    Returns the patch, its mask (soft edge) and the crop info for FumikaInpaintStitch."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",), "mask": ("MASK",),
            "only_masked": ("BOOLEAN", {"default": True}),
            "padding": ("INT", {"default": 32, "min": 0, "max": 512, "step": 8}),
            "target": ("INT", {"default": 1024, "min": 256, "max": 2048, "step": 16, "tooltip": "long side the patch is drawn at"}),
            "mask_blur": ("INT", {"default": 4, "min": 0, "max": 64}),
        }}
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("patch", "patch_mask", "crop")
    FUNCTION = "crop"
    CATEGORY = "Fumika"

    def crop(self, image, mask, only_masked, padding, target, mask_blur):
        import json
        import torch
        import torch.nn.functional as F
        h, w = image.shape[1], image.shape[2]
        m = mask[0] if mask.dim() == 3 else mask
        ys, xs = torch.nonzero(m > 0.5, as_tuple=True)
        bbox = None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        x0, y0, x1, y1 = crop_box(bbox, w, h, padding, only_masked)
        # only masked: the patch is drawn at `target` (small areas get more pixels = more detail); whole picture: at its own size
        tw, th = work_size(x1 - x0, y1 - y0, target if only_masked else min(max(w, h), 2048))
        patch = image[:, y0:y1, x0:x1, :].permute(0, 3, 1, 2)
        patch = F.interpolate(patch, size=(th, tw), mode="bicubic", align_corners=False).clamp(0, 1).permute(0, 2, 3, 1)
        pm = F.interpolate(m[y0:y1, x0:x1][None, None], size=(th, tw), mode="bilinear", align_corners=False)
        if mask_blur:
            pm = _blur(pm, mask_blur)
        return (patch, pm[0], json.dumps({"box": [x0, y0, x1, y1], "size": [w, h]}))


def _blur(m, r):
    """box blur of radius r on a (1, 1, H, W) mask, twice (close to a gaussian)"""
    import torch.nn.functional as F
    k = 2 * r + 1
    for _ in range(2):
        m = F.avg_pool2d(F.pad(m, (r, r, r, r), mode="replicate"), k, stride=1)
    return m


class FumikaInpaintStitch:
    """Pastes the redrawn patch back into the picture with the soft mask; outside the mask the picture stays untouched."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "patch": ("IMAGE",), "mask": ("MASK",), "crop": ("STRING", {"forceInput": True}),
                             "mask_blur": ("INT", {"default": 4, "min": 0, "max": 64})}}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "stitch"
    CATEGORY = "Fumika"

    def stitch(self, image, patch, mask, crop, mask_blur):
        import json
        import torch.nn.functional as F
        x0, y0, x1, y1 = json.loads(crop)["box"]
        m = mask[0] if mask.dim() == 3 else mask
        m = m[None, None]
        if mask_blur:
            m = _blur(m, mask_blur)
        m = m[0, 0, y0:y1, x0:x1][None, :, :, None]
        p = F.interpolate(patch.permute(0, 3, 1, 2), size=(y1 - y0, x1 - x0), mode="bicubic", align_corners=False).clamp(0, 1).permute(0, 2, 3, 1)
        out = image.repeat(p.shape[0], 1, 1, 1).clone()
        out[:, y0:y1, x0:x1, :] = out[:, y0:y1, x0:x1, :] * (1 - m) + p * m
        return (out,)


NODE_CLASS_MAPPINGS = {"FumikaLoadSource": FumikaLoadSource, "FumikaLoraStack": FumikaLoraStack, "FumikaModelLoader": FumikaModelLoader,
                       "FumikaPromptEncode": FumikaPromptEncode, "FumikaLoadMask": FumikaLoadMask,
                       "FumikaInpaintCrop": FumikaInpaintCrop, "FumikaInpaintStitch": FumikaInpaintStitch}
NODE_DISPLAY_NAME_MAPPINGS = {"FumikaLoadSource": "Fumika Load Picture (output / input)", "FumikaLoraStack": "Fumika LoRA Stack",
                              "FumikaModelLoader": "Fumika Model Loader (any family)", "FumikaPromptEncode": "Fumika Prompt (any family)",
                              "FumikaLoadMask": "Fumika Load Mask", "FumikaInpaintCrop": "Fumika Inpaint Crop",
                              "FumikaInpaintStitch": "Fumika Inpaint Stitch"}
