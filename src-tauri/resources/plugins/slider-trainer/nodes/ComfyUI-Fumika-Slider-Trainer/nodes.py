# -*- coding: utf-8 -*-
"""ComfyUI node: train a slider LoRA (Concept Sliders) for Anima or SDXL - from two prompts (no dataset) or from two image folders.
start = false: check + plan only; start = true: install the engine on first use, then train in its own window."""
import os
import time

import folder_paths

from . import core

COMFY = os.path.dirname(folder_paths.__file__)
LORA_ROOT = folder_paths.get_folder_paths("loras")[0]
AUTO = "auto (find it by name)"


def _find(kind, keys, name, what):
    fs = folder_paths.get_filename_list(kind)
    if name and name != AUTO:
        if name not in fs:
            raise ValueError(f"{what}: '{name}' not found in models/{kind}")
        return folder_paths.get_full_path(kind, name)
    for k in keys:
        hit = [f for f in fs if k in f.lower()]
        if hit:
            return folder_paths.get_full_path(kind, sorted(hit, key=len)[0])
    raise ValueError(f"{what}: no file found in models/{kind} (looked for {', '.join(keys)})")


def _safe(s):
    return "".join(ch for ch in s.strip() if ch.isalnum() or ch in "-_") or "my_slider"


class FumikaSliderTrain:
    """Slider LoRA. Text mode: positive / negative = the two ends (they should differ ONLY in the concept), neutral = what you
    generate ('a woman'); optional more subjects (one per line: neutral | positive | negative) and anchors (prompts that must not
    change). Image mode: a folder of positive-end and one of negative-end pictures. Use the result at -2 ... +2."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "family": (["anima", "sdxl"], {"default": "anima"}),
            "mode": (["text", "images"], {"default": "text", "tooltip": "text = no dataset (Concept Sliders); images = two folders of pictures"}),
            "slider_name": ("STRING", {"default": "my_slider"}),
            "start": ("BOOLEAN", {"default": False, "tooltip": "false = only check and show the plan"}),
        }, "optional": {
            "positive": ("STRING", {"multiline": True, "default": ""}), "negative": ("STRING", {"multiline": True, "default": ""}),
            "neutral": ("STRING", {"default": "a woman"}),
            "targets": ("STRING", {"multiline": True, "default": "", "tooltip": "more subjects, one per line: neutral | positive | negative"}),
            "anchors": ("STRING", {"multiline": True, "default": "", "tooltip": "prompts that must not change, one per line (optional)"}),
            "anchor_weight": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
            "pos_folder": ("STRING", {"default": ""}), "neg_folder": ("STRING", {"default": ""}),
            "pair_caption": ("STRING", {"default": "", "tooltip": "images: caption for both ends (a .txt next to an image wins)"}),
            "rank": ("INT", {"default": 8, "min": 1, "max": 64}), "alpha": ("FLOAT", {"default": 4.0, "min": 0.1, "max": 64.0, "step": 0.5}),
            "learning_rate": ("FLOAT", {"default": 2e-4, "min": 1e-6, "max": 1e-2, "step": 1e-5, "round": 1e-6}),
            "guidance": ("FLOAT", {"default": 3.0, "min": 0.5, "max": 10.0, "step": 0.5, "tooltip": "text mode: edit strength at training time"}),
            "steps": ("INT", {"default": 500, "min": 50, "max": 5000, "step": 50}),
            "save_every": ("INT", {"default": 100, "min": 10, "max": 1000, "step": 10}),
            "sample_prompt": ("STRING", {"default": "", "tooltip": "preview prompt (empty = the neutral prompt)"}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2**31 - 1}),
            "v_prediction": ("BOOLEAN", {"default": False, "tooltip": "SDXL v-prediction checkpoints (NoobAI v-pred)"}),
            "checkpoint": ([AUTO] + (folder_paths.get_filename_list("checkpoints") or []), {"tooltip": "SDXL checkpoint"}),
        }}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("report", "log_path")
    FUNCTION = "run"
    CATEGORY = "Fumika Slider Trainer"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kw):
        return time.time()

    def run(self, family, mode, slider_name, start, positive="", negative="", neutral="a woman", targets="", anchors="", anchor_weight=0.5,
            pos_folder="", neg_folder="", pair_caption="", rank=8, alpha=4.0, learning_rate=2e-4, guidance=3.0, steps=500, save_every=100,
            sample_prompt="", seed=42, v_prediction=False, checkpoint=AUTO):
        name = _safe(slider_name); out = os.path.join(LORA_ROOT, "slider_training", name); log = os.path.join(out, "train_log.txt")
        cfg = dict(family=family, mode=mode, name=name, positive=positive, negative=negative, neutral=neutral, targets=targets, anchors=anchors,
                   anchor_weight=anchor_weight, pos_folder=pos_folder.strip().strip('"'), neg_folder=neg_folder.strip().strip('"'),
                   pair_caption=pair_caption, rank=rank, alpha=alpha, lr=learning_rate, guidance=guidance, steps=steps, save_every=save_every,
                   sample_prompt=sample_prompt, seed=seed, v_pred=v_prediction)
        if os.path.isfile(log):   # never a second run into the same folder while one is still going (also not on start)
            raw = open(log, "rb").read()[-4000:].decode("utf-8", "replace")
            if "TRAIN_EXIT" not in raw:
                s = (f"{name}: still training - see its window (or press Run again). If it is not running any more, delete "
                     f"{out} or pick another name.")
                return {"ui": {"text": [s]}, "result": (s, log)}
        ok, lines = core.check(cfg)
        if family == "sdxl":   # kept for later: ai-toolkit's text slider fails in its current version (test 22 Oct)
            ok = False
            lines.insert(0, "ERROR SDXL sliders are not available yet (the ai-toolkit slider training is broken upstream) - use Anima")
        try:
            if family == "anima":
                cfg.update(dit=_find("diffusion_models", ("anima-base", "anima"), AUTO, "Anima model"),
                           text_encoder=_find("text_encoders", ("qwen_3_06b", "qwen3_06b", "qwen_3"), AUTO, "Qwen3 text encoder"),
                           vae=_find("vae", ("qwen_image_vae", "qwen_image"), AUTO, "Qwen-Image VAE"))
                lines.append(f"MODEL {os.path.basename(cfg['dit'])}")
            else:
                cfg["checkpoint"] = _find("checkpoints", ("illustrious", "noob", "animagine", "xl"), checkpoint, "SDXL checkpoint")
                lines.append(f"MODEL {os.path.basename(cfg['checkpoint'])}")
        except ValueError as e:
            ok = False; lines.append(f"ERROR {e}")
        lines.append(f"\nPLAN: {'text' if mode == 'text' else 'image'} slider for {'Anima' if family == 'anima' else 'SDXL'}, {steps} steps, rank {rank} / alpha {alpha:g}, "
                     f"learning rate {learning_rate:g}" + (f", guidance {guidance:g}" if mode == "text" else "") + f"; a file + preview every {save_every} steps. "
                     "Pick the last clean file and use it at -1 ... +1 (up to +-2).")
        if family == "anima":
            eng = core.pick_sd_scripts(COMFY); state = core.sd_state(eng); install = core.start_sd_install
        else:
            eng = os.path.join(COMFY, "ai-toolkit"); state = core.aitk_state(eng); install = core.start_aitk_install
        lines.append(f"TRAINER {eng}: {state}")
        if start and ok:
            if not state.startswith("ready"):
                ilog = os.path.join(os.path.dirname(eng), f"slider_trainer_install_{family}.txt")
                if not core.install_running(ilog):   # missing, or broken (installed again: the steps are idempotent)
                    install(eng, ilog)
                lines.append("\nFirst start: installing the trainer in a separate window (5-20 min). When it says INSTALL_EXIT 0, press Run again.")
            else:
                core.launch(cfg, out, eng)
                lines.append("\nSTARTED in a separate window. Press Run again any time to see the progress.")
        elif start:
            lines.append("\nNot started: the check is not ready.")
        s = ("READY\n\n" if ok else "NOT READY - fix the points marked ERROR\n\n") + "\n".join(lines)
        return {"ui": {"text": [s]}, "result": (s, log)}


NODE_CLASS_MAPPINGS = {"FumikaSliderTrain": FumikaSliderTrain}
NODE_DISPLAY_NAME_MAPPINGS = {"FumikaSliderTrain": "Fumika Slider Train (Anima / SDXL)"}
