# -*- coding: utf-8 -*-
"""Beginner nodes: one node to train (checks, installs, picks epochs from the dataset size, launches) and one node to test all
saved epochs as a grid (test prompts built from the training captions). Recipe = MossTrainConfig defaults."""
import json
import os
import re
import time

import folder_paths
import nodes as comfy_nodes

from . import core

TARGET_STEPS = 1700   # ~1 h on an RTX 5090, the article recipe for a ~200 samples/epoch character
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
KEYS = {"diffusion_models": ("moss_image_base", "moss_image", "moss"), "text_encoders": ("qwen3.5", "qwen3_5", "qwen35"), "vae": ("flux2", "flux.2", "flux_2"),
        "loras": ("8step", "dmd")}


def _first(kind, key=None):
    """dropdown: 'auto' first (saved workflows work on every PC), then the user's own files"""
    return [AUTO] + (folder_paths.get_filename_list(kind) or [])


def model_inputs(with_turbo=False):
    d = {"base_model": (_first("diffusion_models", "moss_image_base"), {"tooltip": "train on MOSS-Image BASE (moss_image_base_bf16), not on a turbo / fine-tune"}),
         "text_encoder": (_first("text_encoders", "qwen3.5"), {"tooltip": "Qwen3.5-9B text encoder of MOSS-Image"}),
         "vae": (_first("vae", "flux2"), {"tooltip": "FLUX.2 VAE"})}
    if with_turbo:
        d["turbo_lora"] = (_first("loras", "8step"), {"tooltip": "8-step DMD turbo LoRA used to render the test grid"})
    return d


def _check(kind, name, what):
    """'auto' -> first file whose name contains a known keyword (any sub-folder); explicit name -> must exist"""
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


def auto_prompts(lora):
    """3 test prompts from the first training caption: its identity part + three standard scenes"""
    cfgp = os.path.join(os.path.dirname(folder_paths.get_full_path("loras", lora)), "run_config.json")
    base = ""
    if os.path.isfile(cfgp):
        ds = json.load(open(cfgp, encoding="utf-8"))["dataset_dir"]
        for dp, _, fs in os.walk(ds):
            t = sorted(f for f in fs if f.endswith(".txt"))
            if t:
                base = open(os.path.join(dp, t[0]), encoding="utf-8", errors="replace").read(); break
    base = base.split("Scene details:")[0]
    for r in sorted(set(core.RATING.values()), key=len, reverse=True):   # strip the rating sentence
        if base.strip().startswith(r):
            base = base.strip()[len(r):]; break
    base = base.strip()
    if not base:
        raise ValueError("could not read the training captions - write test_prompts yourself")
    return [f"Safe image. {base} Scene details: full body, standing, smiling, sunny park.",
            f"Suggestive image. {base} Scene details: cowboy shot, from behind, looking back over the shoulder, bedroom.",
            f"Safe image. {base} Scene details: close-up portrait, happy, cafe."]


class MossEasyTrain:
    """EASY MODE - train a MOSS LoRA.
    1) dataset_folder: a folder with a sub-folder like 4_mychar (images + one .txt caption each).
    2) lora_name: any name.  3) Run with start = false and read the report.
    4) Says READY? Set start = true and Run again. A console window opens and trains (first time: installs itself first)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "dataset_folder": ("STRING", {"default": ""}),
            "lora_name": ("STRING", {"default": "my_character"}),
            "start": ("BOOLEAN", {"default": False, "tooltip": "false = only check and show the plan"}),
        }, "optional": {**model_inputs(),
            "epochs": ("INT", {"default": 0, "min": 0, "max": 200, "tooltip": "0 = automatic (~1700 steps)"}),
            "rank": ("INT", {"default": 32, "min": 4, "max": 128, "step": 4, "tooltip": "LoRA size; 32 for characters, 16-32 for outfits"}),
            "learning_rate": ("FLOAT", {"default": 1e-4, "min": 1e-6, "max": 1e-2, "step": 1e-5, "round": 1e-6}),
            "resolution": ("INT", {"default": 1024, "min": 512, "max": 1536, "step": 64, "tooltip": "lower = less VRAM, faster"}),
        }}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("report", "log_path")
    FUNCTION = "run"
    CATEGORY = "MOSS LoRA Trainer"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def run(self, dataset_folder, lora_name, start, base_model=None, text_encoder=None, vae=None, epochs=0, rank=32, learning_rate=1e-4, resolution=1024):
        from .nodes import DEFAULT_SD, LORA_ROOT
        ds = dataset_folder.strip().strip('"'); name = "".join(ch for ch in lora_name.strip() if ch.isalnum() or ch in "-_") or "my_lora"
        out = os.path.join(LORA_ROOT, "moss_training", name); log = os.path.join(out, "train_log.txt")
        if os.path.isfile(log):   # already trained / training -> show progress instead of a second run
            p = core.progress(log)
            if p["state"] in ("training", "starting", "finished"):
                head = p["state"] + (f": step {p['step']}/{p['total']}, {p['remaining']} left" if "step" in p else "")
                s = f"{name}: {head}\n" + ("Done - open the epoch test workflow." if p["state"] == "finished" else "Run again to refresh.")
                return {"ui": {"text": [s]}, "result": (s, log)}
        ok, rep, n = core.check_dataset(ds)
        lines = [("READY" if ok else "NOT READY - fix the points marked ERROR") + "\n", rep]
        epochs = epochs or (max(2, min(40, round(TARGET_STEPS / max(n, 1)))) if n else 0)
        save = max(1, epochs // 4)
        if n:
            lines.append(f"\nPLAN: {epochs} epochs = {epochs * n} steps (~{epochs * n * 2 / 60:.0f} min on an RTX 5090), a file is saved every {save} epochs")
        state = core.install_state(DEFAULT_SD)
        if start and ok:
            if not state.startswith("ready"):
                ilog = os.path.join(os.path.dirname(DEFAULT_SD), "moss_trainer_install_log.txt")
                if not core.install_running(ilog):   # missing, or broken (installed again: the steps are idempotent)
                    core.start_install(DEFAULT_SD, ilog)
                lines.append("\nFirst start: installing the trainer in a separate window (5-15 min). When it says INSTALL_EXIT 0, press Run again.")
            else:
                bm = _check("diffusion_models", base_model, "base_model")
                te = _check("text_encoders", text_encoder, "text_encoder")
                va = _check("vae", vae, "vae")
                cfg = dict(dataset_dir=ds, name=name, dit=folder_paths.get_full_path("diffusion_models", bm),
                           text_encoder=folder_paths.get_full_path("text_encoders", te), vae=folder_paths.get_full_path("vae", va),
                           epochs=epochs, save_every=save, dim=rank, alpha=max(1, rank // 2), lr=learning_rate, optimizer="AdamW8bit",
                           resolution=resolution, batch=1, seed=42, max_steps=0, output_dir=out, sample_prompts="", resume="")
                core.launch(cfg, DEFAULT_SD)
                lines.append("\nSTARTED in a separate window. Press Run again any time to see the progress.")
        elif start:
            lines.append("\nNot started: the dataset is not ready.")
        s = "\n".join(lines)
        return {"ui": {"text": [s]}, "result": (s, log)}


class MossEasyEpochTest:
    """EASY MODE - after training: enter the same lora_name and press Run. You get a grid: first row without LoRA, then one row
    per saved file. Take the earliest row where the character looks right - that file is your LoRA."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "lora_name": ("STRING", {"default": "my_character", "tooltip": "the name used for training"}),
        }, "optional": {
            "test_prompts": ("STRING", {"multiline": True, "default": "",
                                        "tooltip": "optional - empty = 3 prompts built from your training captions. Separate own prompts with a line ---"}),
            **model_inputs(with_turbo=True),
        }}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("grid",)
    FUNCTION = "run"
    CATEGORY = "MOSS LoRA Trainer"

    def run(self, lora_name, test_prompts="", base_model=None, text_encoder=None, vae=None, turbo_lora=None, seed=71000):
        from .nodes import MossEpochGrid
        folder = "moss_training/" + lora_name.strip()
        names = sorted(n for n in folder_paths.get_filename_list("loras") if n.replace("\\", "/").startswith(folder + "/") and n.endswith(".safetensors"))
        if not names:
            raise ValueError(f"no trained files in models/loras/{folder} yet (press R in ComfyUI to refresh after training)")
        ps = [p.strip() for p in test_prompts.split("\n---\n") if p.strip()] or auto_prompts(names[0])
        key = (base_model, text_encoder, vae, turbo_lora)
        if _CACHE.get("key") != key:
            _CACHE.clear()
            unet = _run("UNETLoader", unet_name=_check("diffusion_models", base_model, "base_model"), weight_dtype="default")[0]
            turbo = _run("LoraLoaderModelOnly", model=unet, lora_name=_check("loras", turbo_lora, "turbo_lora"), strength_model=1.0)[0]
            clip = _run("CLIPLoader", clip_name=_check("text_encoders", text_encoder, "text_encoder"), type="moss_image", device="default")[0]
            _CACHE.update(key=key, m=(turbo, clip, _run("VAELoader", vae_name=_check("vae", vae, "vae"))[0]))
        turbo, clip, vae = _CACHE["m"]
        conds = [_run("CLIPTextEncode", clip=clip, text=p)[0] for p in ps]; neg = _run("CLIPTextEncode", clip=clip, text="")[0]
        lat = _run("EmptyFlux2LatentImage", width=832, height=1216, batch_size=1)[0]
        imgs, labels = [], []
        for lab, lora in [("no LoRA", None)] + [(os.path.basename(n)[:-12], n) for n in names]:
            m = turbo if lora is None else _run("LoraLoaderModelOnly", model=turbo, lora_name=lora, strength_model=1.0)[0]
            for j, c in enumerate(conds):
                s = _run("KSampler", model=m, seed=seed + j, steps=8, cfg=1.0, sampler_name="euler", scheduler="simple",
                         positive=c, negative=neg, latent_image=lat, denoise=1.0)[0]
                imgs.append(_run("VAEDecode", samples=s, vae=vae)[0]); labels.append(f"{lab} | prompt {j + 1}")
        return MossEpochGrid().grid(imgs, labels, [len(ps)], [384])
