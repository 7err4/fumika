# -*- coding: utf-8 -*-
"""ComfyUI nodes: train MOSS-Image LoRAs with sd-scripts (own venv, own console window) and test the epochs as a grid."""
import json
import os
import time

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

import folder_paths

from . import core

CAT = "MOSS LoRA Trainer"
COMFY = os.path.dirname(folder_paths.__file__)
DEFAULT_SD = os.path.join(COMFY, "sd-scripts-moss")
LORA_ROOT = folder_paths.get_folder_paths("loras")[0]


def _files(kind, prefer=""):
    """file list of a model folder with the recommended file first (ComfyUI uses the first entry as default)"""
    try:
        fs = folder_paths.get_filename_list(kind) or [""]
    except Exception:   # noqa: BLE001
        return [""]
    return sorted(fs, key=lambda f: prefer not in f) if prefer else fs


class MossTrainerInstall:
    """Checks / installs sd-scripts with MOSS support into its own folder and venv (does not touch ComfyUI's Python).
    'install' runs in a separate window (5-15 min: git clone, torch cu128, requirements); run the node again to see the state."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sd_scripts_dir": ("STRING", {"default": "", "tooltip": "empty = ComfyUI/sd-scripts-moss"}), "action": (["check", "install"], {"default": "check"})}}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("sd_scripts_dir", "status")
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def run(self, sd_scripts_dir, action):
        sd = os.path.abspath(sd_scripts_dir.strip().strip('"')) if sd_scripts_dir.strip() else DEFAULT_SD   # empty = next to ComfyUI
        state = core.install_state(sd)
        log = os.path.join(os.path.dirname(sd), "moss_trainer_install_log.txt")
        if action == "install" and not state.startswith("ready") and not core.install_running(log):   # never two installs at once
            core.start_install(sd, log); state = f"installing in a separate window... (log: {log})"
        elif os.path.isfile(log) and not state.startswith("ready"):
            tail = open(log, "rb").read()[-3000:].decode("utf-8", "replace").replace("\r", "\n").strip().splitlines()[-6:]
            state += "\n--- install log ---\n" + "\n".join(tail)
        return {"ui": {"text": [state]}, "result": (sd, state)}


class MossDatasetCheck:
    """Validates a training folder: <repeats>_<name> subsets, one .txt caption per image, no tag-only captions, no multi-
    candidate captions (they break text-encoder caching). The launcher refuses to start when this reports an error."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"dataset_dir": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("STRING", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("dataset_dir", "ok", "samples_per_epoch", "report")
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def run(self, dataset_dir):
        ok, rep, n = core.check_dataset(dataset_dir.strip().strip('"'))
        return {"ui": {"text": [("READY\n" if ok else "NOT READY\n") + rep]}, "result": (dataset_dir.strip().strip('"'), ok, n, rep)}


class MossTagsToSentences:
    """Turns a Danbooru-tag dataset (e.g. from an Anima / Illustrious LoRA) into MOSS sentence captions:
    rating sentence + trigger and identity sentence + one fixed sentence per outfit token + 'Scene details: <other tags>'.
    Writes a NEW folder (images copied), the source stays untouched."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_dir": ("STRING", {"default": ""}), "output_dir": ("STRING", {"default": ""}),
            "trigger": ("STRING", {"default": "ohwx"}),
            "identity": ("STRING", {"multiline": True, "default": "an adult woman in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes"}),
            "outfits": ("STRING", {"multiline": True, "default": "ohwxdef = She wears her default outfit: white tank top, black mini skirt, red boots.",
                                   "tooltip": "one per line: <outfit tag> = <sentence>"}),
            "drop_tags": ("STRING", {"multiline": True, "default": "1girl, solo", "tooltip": "tags covered by the identity sentence (comma separated)"}),
        }}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("dataset_dir", "example_caption")
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True

    def run(self, source_dir, output_dir, trigger, identity, outfits, drop_tags):
        src, dst = source_dir.strip().strip('"'), output_dir.strip().strip('"')
        if not os.path.isdir(src):
            raise ValueError(f"source_dir not found: {src}")
        if os.path.abspath(src) == os.path.abspath(dst):
            raise ValueError("output_dir must be a different folder")
        n = core.tags_to_sentences(src, dst, trigger.strip(), identity, core.parse_outfits(outfits), drop_tags.split(","))
        ex = ""
        for dp, _, fs in os.walk(dst):
            t = [f for f in fs if f.endswith(".txt")]
            if t:
                ex = open(os.path.join(dp, t[0]), encoding="utf-8").read(); break
        return {"ui": {"text": [f"{n} captions written to {dst}\n\nexample:\n{ex}"]}, "result": (dst, ex)}


class MossTrainConfig:
    """All training settings. Defaults = the article recipe (rank 32 / alpha 16, AdamW8bit 1e-4 cosine, logit-normal timesteps
    -1.09 / 0.95 shift 1, TE frozen + cached, bf16). LoRAs are written to models/loras/<subfolder>/<name> so the epoch test can
    load them directly."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "dataset_dir": ("STRING", {"forceInput": True}),
            "name": ("STRING", {"default": "my_moss_lora"}),
            "dit": (_files("diffusion_models", "moss_image_base"), {"tooltip": "moss_image_base_bf16.safetensors - train on Base, not on a turbo / fine-tune"}),
            "text_encoder": (_files("text_encoders", "qwen3.5_9b"), {"tooltip": "qwen3.5_9b_int8_convrot.safetensors"}),
            "vae": (_files("vae", "flux2-vae"), {"tooltip": "flux2-vae.safetensors"}),
            "epochs": ("INT", {"default": 8, "min": 1, "max": 200}),
            "save_every": ("INT", {"default": 2, "min": 1, "max": 50}),
            "dim": ("INT", {"default": 32, "min": 4, "max": 256, "step": 4}),
            "alpha": ("INT", {"default": 16, "min": 1, "max": 256}),
            "lr": ("FLOAT", {"default": 1e-4, "min": 1e-6, "max": 1e-2, "step": 1e-5, "round": 1e-6}),
            "optimizer": (["AdamW8bit", "AdamW", "Prodigy"], {"default": "AdamW8bit"}),
            "resolution": ("INT", {"default": 1024, "min": 512, "max": 1536, "step": 64}),
            "batch": ("INT", {"default": 1, "min": 1, "max": 8}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2**31 - 1}),
            "max_steps": ("INT", {"default": 0, "min": 0, "max": 100000, "tooltip": "0 = use epochs; >0 stops early (quick test)"}),
            "lora_subfolder": ("STRING", {"default": "moss_training"}),
            "sample_prompts": ("STRING", {"multiline": True, "default": "", "tooltip": "optional, prompts separated by a line with ---; rendered every save"}),
        }, "optional": {"samples_per_epoch": ("INT", {"forceInput": True}), "resume_from": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("MOSS_TRAIN_CONFIG", "STRING")
    RETURN_NAMES = ("config", "summary")
    FUNCTION = "build"
    CATEGORY = CAT
    OUTPUT_NODE = True

    def build(self, dataset_dir, name, dit, text_encoder, vae, epochs, save_every, dim, alpha, lr, optimizer, resolution, batch, seed,
              max_steps, lora_subfolder, sample_prompts, samples_per_epoch=0, resume_from=""):
        out = os.path.join(LORA_ROOT, lora_subfolder.strip(), name.strip())
        cfg = dict(dataset_dir=dataset_dir, name=name.strip(), dit=folder_paths.get_full_path("diffusion_models", dit),
                   text_encoder=folder_paths.get_full_path("text_encoders", text_encoder), vae=folder_paths.get_full_path("vae", vae),
                   epochs=epochs, save_every=save_every, dim=dim, alpha=alpha, lr=lr, optimizer=optimizer, resolution=resolution,
                   batch=batch, seed=seed, max_steps=max_steps, output_dir=out, sample_prompts=sample_prompts, resume=resume_from.strip())
        steps = max_steps or (samples_per_epoch * epochs // batch if samples_per_epoch else 0)
        s = (f"{name}: {epochs} epochs, save every {save_every}, rank {dim}/{alpha}, lr {lr:g} {optimizer}, {resolution}px, batch {batch}\n"
             f"output: {out}\n" + (f"~{steps} steps (~{steps * 2 / 60:.0f} min at ~2 s/step on an RTX 5090)\n" if steps else "")
             + "\n--- dataset.toml ---\n" + (core.dataset_toml(dataset_dir, resolution, batch) if os.path.isdir(dataset_dir) else "(dataset not found)")
             + "\n--- command ---\n" + " ".join(core.train_command(cfg)))
        return {"ui": {"text": [s]}, "result": (cfg, s)}


class MossTrainLaunch:
    """Starts the training in its own console window (live progress there, ComfyUI stays usable). Refuses to start when the
    dataset check failed or sd-scripts is not installed. Set 'start' to true to launch - false only shows the plan."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"config": ("MOSS_TRAIN_CONFIG",), "sd_scripts_dir": ("STRING", {"forceInput": True}),
                             "dataset_ok": ("BOOLEAN", {"forceInput": True}), "start": ("BOOLEAN", {"default": False})}}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("log_path",)
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True

    def run(self, config, sd_scripts_dir, dataset_ok, start):
        log = os.path.join(config["output_dir"], "train_log.txt")
        if not start:
            return {"ui": {"text": ["Not started (start = false). Check the summary, then set start = true and run again."]}, "result": (log,)}
        if not dataset_ok:
            raise ValueError("Dataset check failed - fix the dataset first (see the MOSS Dataset Check report).")
        st = core.install_state(sd_scripts_dir)
        if not st.startswith("ready"):
            raise ValueError(f"sd-scripts not ready ({st}). Run MOSS Trainer Install with action = install first.")
        if os.path.isfile(log) and core.progress(log)["state"] in ("training", "starting") and time.time() - os.path.getmtime(log) < 120:
            raise ValueError(f"A training is already writing to {log}. Use another name or wait until it finished.")
        pid, log = core.launch(config, sd_scripts_dir)
        return {"ui": {"text": [f"Training started (pid {pid}) in a separate window.\nlog: {log}"]}, "result": (log,)}


class MossTrainStatus:
    """Shows progress of a running training (step, ETA, loss, last log lines). Queue it again to refresh."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"log_path": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def run(self, log_path):
        p = core.progress(log_path.strip().strip('"'))
        head = p["state"]
        if "step" in p:
            head += f" - step {p['step']}/{p['total']} ({100 * p['step'] // max(p['total'], 1)}%), elapsed {p['elapsed']}, left {p['remaining']}" + (f", loss {p['loss']}" if p.get("loss") else "")
        s = f"{head}\nlog updated {p.get('updated', '-')}\n\n{p['tail']}"
        return {"ui": {"text": [s]}, "result": (s,)}


class MossEpochGridPlan:
    """Epoch test plan: every saved epoch of a training (+ optional 'no LoRA' baseline) x every test prompt, fixed seed per
    prompt. Outputs LISTS - the nodes after it run once per item, MOSS Epoch Grid collects the images."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "lora_folder": ("STRING", {"default": "moss_training/my_moss_lora", "tooltip": "relative to models/loras"}),
            "prompts": ("STRING", {"multiline": True, "default": "Safe image. ohwx, ... full body, standing, smile.\n---\nSafe image. ohwx, ... upper body, sitting at a desk, looking at viewer."}),
            "include_baseline": ("BOOLEAN", {"default": True}), "seed": ("INT", {"default": 71000, "min": 0, "max": 2**31 - 1}),
            "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
        }}
    RETURN_TYPES = ("STRING", "FLOAT", "STRING", "INT", "STRING", "INT")
    RETURN_NAMES = ("lora_name", "strength", "prompt", "seed", "label", "columns")
    OUTPUT_IS_LIST = (True, True, True, True, True, False)
    FUNCTION = "plan"
    CATEGORY = CAT

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def plan(self, lora_folder, prompts, include_baseline, seed, strength):
        folder = lora_folder.strip().strip("/\\").replace("\\", "/")
        names = sorted(n for n in folder_paths.get_filename_list("loras") if n.replace("\\", "/").startswith(folder + "/") and n.endswith(".safetensors"))
        if not names:
            raise ValueError(f"no LoRAs found in models/loras/{folder}")
        ps = [p.strip() for p in prompts.split("\n---\n") if p.strip()]
        rows = ([(names[0], 0.0, "no LoRA")] if include_baseline else []) + [(n, strength, os.path.basename(n)[:-12]) for n in names]
        L = [[], [], [], [], []]
        for lora, w, lab in rows:
            for j, p in enumerate(ps):
                for k, v in enumerate((lora, w, p, seed + j, f"{lab} | p{j + 1}")):
                    L[k].append(v)
        return (*L, len(ps))


class MossEpochLoraLoader:
    """LoRA loader that takes the LoRA name as a STRING (from MOSS Epoch Test Plan) - the stock loader only accepts its dropdown.
    Strength 0 returns the model unchanged (the 'no LoRA' baseline row)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "lora_name": ("STRING", {"forceInput": True}), "strength": ("FLOAT", {"forceInput": True})}}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load"
    CATEGORY = CAT

    def load(self, model, lora_name, strength):
        if strength == 0:
            return (model,)
        import comfy.sd
        import comfy.utils
        path = folder_paths.get_full_path("loras", lora_name)
        if path is None:
            raise ValueError(f"LoRA not found: {lora_name}")
        m, _ = comfy.sd.load_lora_for_models(model, None, comfy.utils.load_torch_file(path, safe_load=True), strength, 0)
        return (m,)


class MossEpochGrid:
    """Collects the images of an epoch test into one labelled grid (rows = epochs, columns = prompts)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "labels": ("STRING", {"forceInput": True}), "columns": ("INT", {"forceInput": True}),
                             "cell_width": ("INT", {"default": 384, "min": 128, "max": 1024})}}
    INPUT_IS_LIST = True
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "grid"
    CATEGORY = CAT

    def grid(self, images, labels, columns, cell_width):
        cols, cw = columns[0], cell_width[0]
        ims = [Image.fromarray((b[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)) for b in images]
        ch = int(cw * ims[0].height / ims[0].width); rows = (len(ims) + cols - 1) // cols
        try:
            font = ImageFont.load_default(size=18)
        except TypeError:
            font = ImageFont.load_default()
        o = Image.new("RGB", (cols * (cw + 6), rows * (ch + 30)), "white"); d = ImageDraw.Draw(o)
        for i, im in enumerate(ims):
            x, y = (i % cols) * (cw + 6), (i // cols) * (ch + 30)
            o.paste(im.convert("RGB").resize((cw, ch)), (x, y + 28)); d.text((x + 4, y + 4), labels[i] if i < len(labels) else "", fill="black", font=font)
        return (torch.from_numpy(np.array(o).astype(np.float32) / 255.0)[None],)


from .easy import MossEasyEpochTest, MossEasyTrain  # noqa: E402

NODE_CLASS_MAPPINGS = {"MossEasyTrain": MossEasyTrain, "MossEasyEpochTest": MossEasyEpochTest, "MossTrainerInstall": MossTrainerInstall, "MossDatasetCheck": MossDatasetCheck, "MossTagsToSentences": MossTagsToSentences,
                       "MossTrainConfig": MossTrainConfig, "MossTrainLaunch": MossTrainLaunch, "MossTrainStatus": MossTrainStatus,
                       "MossEpochGridPlan": MossEpochGridPlan, "MossEpochLoraLoader": MossEpochLoraLoader, "MossEpochGrid": MossEpochGrid}
NODE_DISPLAY_NAME_MAPPINGS = {"MossEasyTrain": "MOSS Easy Train (one node)", "MossEasyEpochTest": "MOSS Easy Epoch Test (one node)", "MossTrainerInstall": "MOSS Trainer Install / Check", "MossDatasetCheck": "MOSS Dataset Check",
                              "MossTagsToSentences": "MOSS Tag Captions to Sentences", "MossTrainConfig": "MOSS Train Config",
                              "MossTrainLaunch": "MOSS Train Launch", "MossTrainStatus": "MOSS Train Status",
                              "MossEpochGridPlan": "MOSS Epoch Test Plan", "MossEpochLoraLoader": "MOSS Epoch LoRA Loader",
                              "MossEpochGrid": "MOSS Epoch Grid"}
