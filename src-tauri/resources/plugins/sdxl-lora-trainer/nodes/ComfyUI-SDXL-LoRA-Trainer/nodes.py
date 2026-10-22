# -*- coding: utf-8 -*-
"""ComfyUI nodes: train SDXL LoRAs (Illustrious / NoobAI / Pony checkpoints) with sd-scripts sdxl_train_network.py in its own venv
and console window, and test the saved epochs as a grid. Same flow as the MOSS LoRA trainer: run with start = false = check
and plan only, start = true = train."""
import json
import os
import time

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

import folder_paths
import nodes as comfy_nodes

from . import core

COMFY = os.path.dirname(folder_paths.__file__)
LORA_ROOT = folder_paths.get_folder_paths("loras")[0]
TARGET_STEPS = 1600   # a typical character / style LoRA on an anime SDXL checkpoint
AUTO = "auto (Illustrious first)"
CAT = "SDXL LoRA Trainer"


def _run(name, **kw):
    cls = comfy_nodes.NODE_CLASS_MAPPINGS[name]
    if hasattr(cls, "FUNCTION"):
        return getattr(cls(), cls.FUNCTION)(**kw)
    out = cls.execute(**kw)
    return out.result if hasattr(out, "result") else out


def _checkpoint(name):
    fs = folder_paths.get_filename_list("checkpoints")
    if name and name != AUTO:
        if name not in fs:
            raise ValueError(f"checkpoint '{name}' not found in models/checkpoints")
        return name
    for key in ("illustrious", "noob", "animagine", "xl"):
        hit = [f for f in fs if key in f.lower()]
        if hit:
            return sorted(hit, key=len)[0]
    raise ValueError("no SDXL checkpoint in models/checkpoints - download Illustrious XL in Fumika's Setup or pick your file")


def _safe(s):
    return "".join(ch for ch in s.strip() if ch.isalnum() or ch in "-_") or "my_lora"


class SdxlEasyTrain:
    """EASY MODE - train an SDXL LoRA.
    1) dataset_folder: a folder with a sub-folder like 4_mychar (images + one .txt with Danbooru tags each, trigger word first).
    2) lora_name: any name.  3) Run with start = false and read the report.
    4) Says READY? Set start = true and Run again. A console window opens and trains (first time: installs itself first)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "dataset_folder": ("STRING", {"default": ""}),
            "lora_name": ("STRING", {"default": "my_character"}),
            "start": ("BOOLEAN", {"default": False, "tooltip": "false = only check and show the plan"}),
        }, "optional": {
            "checkpoint": ([AUTO] + (folder_paths.get_filename_list("checkpoints") or []), {"tooltip": "the SDXL checkpoint to train on (Illustrious XL for Illustrious LoRAs)"}),
            "trigger": ("STRING", {"default": "", "tooltip": "the first tag of your captions; checked and kept in front while shuffling"}),
            "epochs": ("INT", {"default": 0, "min": 0, "max": 200, "tooltip": "0 = automatic (~1600 steps)"}),
            "rank": ("INT", {"default": 32, "min": 4, "max": 128, "step": 4}),
            "learning_rate": ("FLOAT", {"default": 1e-4, "min": 1e-6, "max": 1e-2, "step": 1e-5, "round": 1e-6}),
            "resolution": ("INT", {"default": 1024, "min": 512, "max": 1536, "step": 64, "tooltip": "lower = less VRAM, faster"}),
            "train_text_encoder": ("BOOLEAN", {"default": False, "tooltip": "also train the text encoders (half the learning rate)"}),
            "v_prediction": ("BOOLEAN", {"default": False, "tooltip": "for v-prediction checkpoints such as NoobAI-XL v-pred"}),
            "batch": ("INT", {"default": 1, "min": 1, "max": 8}),
            "save_every": ("INT", {"default": 0, "min": 0, "max": 50, "tooltip": "0 = four files over the run"}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2**31 - 1}),
            # v1.1: LyCORIS network types and embeddings (textual inversion)
            "kind": (["LoRA", "embedding"], {"default": "LoRA", "tooltip": "embedding = textual inversion: a new token for the checkpoint, a few KB"}),
            "network": (list(core.NETWORKS), {"default": "LoRA", "tooltip": "LoCon / LoHa / LoKr = LyCORIS (installed into the trainer on first use)"}),
            "template": (["object", "style"], {"default": "object", "tooltip": "embedding: a character / thing or a style"}),
            "init_word": ("STRING", {"default": "", "tooltip": "embedding: an existing word close to the concept (default 'woman')"}),
            "vectors": ("INT", {"default": 4, "min": 1, "max": 32, "tooltip": "embedding: tokens per embedding"}),
        }}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("report", "log_path")
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def run(self, dataset_folder, lora_name, start, checkpoint=AUTO, trigger="", epochs=0, rank=32, learning_rate=1e-4, resolution=1024,
            train_text_encoder=False, v_prediction=False, batch=1, save_every=0, seed=42, kind="LoRA", network="LoRA", template="object",
            init_word="", vectors=4):
        emb = kind == "embedding"
        ds = dataset_folder.strip().strip('"'); name = _safe(lora_name)
        out = os.path.join(LORA_ROOT, "sdxl_training", name); log = os.path.join(out, "train_log.txt")
        if os.path.isfile(log):   # already trained / training -> show progress instead of a second run
            p = core.progress(log)
            if p["state"] in ("training", "starting", "finished"):
                head = p["state"] + (f": step {p['step']}/{p['total']}, {p['remaining']} left" if "step" in p else "")
                if p["state"] == "finished" and emb:
                    head += "; " + publish_embeddings(out, name)
                s = f"{name}: {head}\n" + ("Done - open the epoch test." if p["state"] == "finished" and not emb else "" if p["state"] == "finished" else "Run again to refresh.")
                return {"ui": {"text": [s]}, "result": (s, log)}
        ok, rep, n = core.check_dataset(ds, trigger.strip())
        lines = [("READY" if ok else "NOT READY - fix the points marked ERROR") + "\n", rep]
        steps_per_epoch = max(1, n // max(1, batch))
        epochs = epochs or (max(2, min(40, round(TARGET_STEPS / steps_per_epoch))) if n else 0)
        save = save_every or max(1, epochs // 4)
        try:
            ck = _checkpoint(checkpoint); lines.append(f"CHECKPOINT {ck}")
        except ValueError as e:
            ck = None; ok = False; lines.append(f"ERROR {e}")
        if emb:
            lr = learning_rate if learning_rate != 1e-4 else 5e-3   # the LoRA default is far too low for an embedding
            if not trigger.strip():
                ok = False; lines.append("ERROR an embedding needs a token: write it in 'trigger' (e.g. fumika7)")
            if n:
                lines.append(f"\nPLAN: embedding '{trigger.strip()}' ({vectors} vectors, {template} template, starts from '{init_word.strip() or 'woman'}'), "
                             f"{epochs} epochs = {epochs * steps_per_epoch} steps, learning rate {lr:g}; a file every {save} epochs")
        elif n:
            lines.append(f"\nPLAN: {network} {epochs} epochs = {epochs * steps_per_epoch} steps, rank {rank}, learning rate {learning_rate:g}"
                         f"{', text encoder too' if train_text_encoder else ''}{', v-prediction' if v_prediction else ''}; a file every {save} epochs")
        sd = core.pick_sd_scripts(COMFY)
        state = core.install_state(sd)
        lines.append(f"TRAINER {sd}: {state}")
        if start and ok:
            ilog = os.path.join(os.path.dirname(sd), "sdxl_trainer_install_log.txt")
            if not state.startswith("ready"):
                if not core.install_running(ilog):   # missing, or broken (installed again: the steps are idempotent)
                    core.start_install(sd, ilog)
                lines.append("\nFirst start: installing the trainer in a separate window (5-15 min). When it says INSTALL_EXIT 0, press Run again.")
            elif not emb and network != "LoRA" and not core.has_lycoris(sd):
                if not core.install_running(ilog):
                    core.start_lycoris_install(sd, ilog)
                lines.append(f"\nFirst {network} run: installing LyCORIS into the trainer in a separate window (1-2 min). Then press Run again.")
            else:
                cfg = dict(dataset_dir=ds, name=name, checkpoint=folder_paths.get_full_path("checkpoints", ck), epochs=epochs, save_every=save,
                           kind="embedding" if emb else "lora", network=network, token=trigger.strip(), init_word=init_word.strip(),
                           vectors=vectors, template=template,
                           dim=rank, alpha=max(1, rank // 2), lr=(learning_rate if learning_rate != 1e-4 else 5e-3) if emb else learning_rate,
                           optimizer="AdamW8bit", resolution=resolution, batch=batch,
                           seed=seed, max_steps=0, output_dir=out, train_te=train_text_encoder, v_pred=v_prediction,
                           sample_prompts="", resume="")
                core.launch(cfg, sd)
                lines.append("\nSTARTED in a separate window. Press Run again any time to see the progress.")
        elif start:
            lines.append("\nNot started: the check is not ready.")
        s = "\n".join(lines)
        return {"ui": {"text": [s]}, "result": (s, log)}


def publish_embeddings(out, name):
    """a finished embedding run: copy its files to models/embeddings/<name>/ so prompts can use embedding:<file>"""
    import shutil
    dst = os.path.join(folder_paths.get_folder_paths("embeddings")[0], name); os.makedirs(dst, exist_ok=True)
    files = [f for f in os.listdir(out) if f.endswith(".safetensors")]
    for f in files:
        shutil.copy2(os.path.join(out, f), dst)
    return f"{len(files)} embedding file(s) copied to models/embeddings/{name} - use them in a prompt as embedding:{name}\\<file>"


def auto_prompts(lora):
    """3 test prompts from the first training caption: its tags (rating tags left out) + three standard scenes"""
    cfgp = os.path.join(os.path.dirname(folder_paths.get_full_path("loras", lora)), "run_config.json")
    tags = []
    if os.path.isfile(cfgp):
        ds = json.load(open(cfgp, encoding="utf-8"))["dataset_dir"]
        for dp, _, fs in os.walk(ds):
            t = sorted(f for f in fs if f.endswith(".txt"))
            if t:
                tags = [x.strip() for x in open(os.path.join(dp, t[0]), encoding="utf-8", errors="replace").read().split(",") if x.strip()]; break
    tags = [x for x in tags if x.lower() not in ("general", "sensitive", "questionable", "explicit", "safe", "nsfw")][:12]
    if not tags:
        raise ValueError("could not read the training captions - write test_prompts yourself")
    base = "masterpiece, best quality, general, " + ", ".join(tags)
    return [f"{base}, full body, standing, smile, park", f"{base}, cowboy shot, from behind, looking back, bedroom",
            f"{base}, portrait, happy, cafe"]


class SdxlEasyEpochTest:
    """EASY MODE - after training: enter the same lora_name and press Run. One row without LoRA, then one row per saved file.
    Take the earliest row where the character looks right - that file is your LoRA."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"lora_name": ("STRING", {"default": "my_character"})},
                "optional": {"test_prompts": ("STRING", {"multiline": True, "default": "", "tooltip": "empty = 3 prompts from your captions; separate own prompts with a line ---"}),
                             "checkpoint": ([AUTO] + (folder_paths.get_filename_list("checkpoints") or []),),
                             "seed": ("INT", {"default": 71000, "min": 0, "max": 2**31 - 1})}}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("grid",)
    FUNCTION = "run"
    CATEGORY = CAT

    def run(self, lora_name, test_prompts="", checkpoint=AUTO, seed=71000):
        folder = "sdxl_training/" + _safe(lora_name)
        names = sorted(n for n in folder_paths.get_filename_list("loras") if n.replace("\\", "/").startswith(folder + "/") and n.endswith(".safetensors"))
        if not names:
            raise ValueError(f"no trained files in models/loras/{folder} yet")
        ps = [p.strip() for p in test_prompts.split("\n---\n") if p.strip()] or auto_prompts(names[0])
        model, clip, vae = _run("CheckpointLoaderSimple", ckpt_name=_checkpoint(checkpoint))[:3]
        clip = _run("CLIPSetLastLayer", clip=clip, stop_at_clip_layer=-2)[0]
        neg_text = "worst quality, low quality, lowres, bad anatomy, bad hands, jpeg artifacts, watermark, signature, text"
        lat = _run("EmptyLatentImage", width=832, height=1216, batch_size=1)[0]
        imgs, labels = [], []
        for lab, lora in [("no LoRA", None)] + [(os.path.basename(n)[:-12], n) for n in names]:
            m, c = (model, clip) if lora is None else _run("LoraLoader", model=model, clip=clip, lora_name=lora, strength_model=1.0, strength_clip=1.0)[:2]
            neg = _run("CLIPTextEncode", clip=c, text=neg_text)[0]
            for j, p in enumerate(ps):
                pos = _run("CLIPTextEncode", clip=c, text=p)[0]
                s = _run("KSampler", model=m, seed=seed + j, steps=28, cfg=5.5, sampler_name="euler_ancestral", scheduler="normal",
                         positive=pos, negative=neg, latent_image=lat, denoise=1.0)[0]
                imgs.append(_run("VAEDecode", samples=s, vae=vae)[0]); labels.append(f"{lab} | prompt {j + 1}")
        return (grid(imgs, labels, len(ps), 384),)


def grid(images, labels, cols, cw):
    ims = [Image.fromarray((b[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)) for b in images]
    ch = int(cw * ims[0].height / ims[0].width); rows = (len(ims) + cols - 1) // cols
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()
    o = Image.new("RGB", (cols * (cw + 6), rows * (ch + 30)), "white"); d = ImageDraw.Draw(o)
    for i, im in enumerate(ims):
        x, y = (i % cols) * (cw + 6), (i // cols) * (ch + 30)
        o.paste(im.convert("RGB").resize((cw, ch)), (x, y + 28)); d.text((x + 4, y + 4), labels[i], fill="black", font=font)
    return torch.from_numpy(np.asarray(o, dtype=np.float32) / 255.0)[None]


NODE_CLASS_MAPPINGS = {"SdxlEasyTrain": SdxlEasyTrain, "SdxlEasyEpochTest": SdxlEasyEpochTest}
NODE_DISPLAY_NAME_MAPPINGS = {"SdxlEasyTrain": "SDXL Easy Train (LoRA)", "SdxlEasyEpochTest": "SDXL Easy Epoch Test"}
