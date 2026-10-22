# -*- coding: utf-8 -*-
"""Plain-Python helpers of the slider trainer pack (no ComfyUI imports). Two engines:
  Anima  train_slider_anima.py (bundled, by 7err4): Concept Sliders in velocity space on kohya sd-scripts' Anima code -
         mode "guidance" (text only, no dataset) or "image_pair" (folders of the two ends)
  SDXL   ostris ai-toolkit (MIT, own install): "slider" (text) or "image_reference_slider_trainer" (two image folders)
Recipe = slider_lora_best_practices.md: rank 8 / alpha 4, lr 2e-4, guidance ~3, 500 steps, save every 100, constant LR."""
import json
import os
import shutil
import subprocess
import sys

try:
    from . import anima_blocks
except ImportError:   # plain import (unit tests)
    import anima_blocks

HERE = os.path.dirname(os.path.abspath(__file__))
SD_REPO = "https://github.com/kohya-ss/sd-scripts.git"
AITK_REPO = "https://github.com/ostris/ai-toolkit.git"
# torchaudio: ai-toolkit imports it at start (toolkit.config_modules), its requirements do not list it (trainer test 22 Oct)
TORCH = ["torch==2.10.0", "torchvision==0.25.0", "torchaudio==2.10.0", "--index-url", "https://download.pytorch.org/whl/cu128"]
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
ANIMA_FILES = ("library/anima_utils.py", "library/strategy_anima.py", "networks/lora_anima.py")


def venv_python(d):
    return os.path.join(d, ".venv" if os.path.isdir(os.path.join(d, ".venv")) or not os.path.isdir(os.path.join(d, "venv")) else "venv",
                        "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")




def install_running(log):
    """an install started earlier is still going: its log has no INSTALL_EXIT yet and changed in the last 5 minutes (the runner touches it every minute)"""
    import time
    if not os.path.isfile(log) or time.time() - os.path.getmtime(log) > 300:
        return False
    return b"INSTALL_EXIT" not in open(log, "rb").read()[-4000:]

def uv_cmd():
    """-> (uv command, steps to run first). uv on PATH (on Linux the engine puts its own bin/uv there), else uv run through the
    engine's Python after a pip install: ComfyUI's embedded Python has no venv module to fall back on (review 22 Oct)."""
    u = shutil.which("uv")
    return ([u], []) if u else ([sys.executable, "-m", "uv"], [[sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "uv"]])

def _ready(d, need, probe):
    if not all(os.path.isfile(os.path.join(d, f)) for f in need):
        return "missing"
    py = venv_python(d)
    if not os.path.isfile(py):
        return "no_venv"
    try:
        r = subprocess.run([py, "-c", probe], cwd=d, capture_output=True, text=True, timeout=180)
        return "ready " + r.stdout.strip() if r.returncode == 0 else "broken: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    except Exception as e:   # noqa: BLE001
        return f"broken: {e}"


def sd_state(d):
    return _ready(d, ANIMA_FILES, "import torch, accelerate, library.anima_utils; print(torch.__version__, torch.cuda.is_available())")


def aitk_state(d):
    return _ready(d, ("run.py", "toolkit/config_modules.py"), "import torch, toolkit.config_modules; print(torch.__version__, torch.cuda.is_available())")


def pick_sd_scripts(comfy_dir):
    """an installed sd-scripts with Anima support next to ComfyUI (the MOSS / SDXL trainers use the same upstream repo)"""
    for name in ("sd-scripts-moss", "sd-scripts-sdxl", "sd-scripts-sliders"):
        d = os.path.join(comfy_dir, name)
        if sd_state(d).startswith("ready"):
            return d
    return os.path.join(comfy_dir, "sd-scripts-sliders")


def _install(repo, d, log, extra=()):
    steps = []
    if not os.path.isdir(d):
        steps.append(["git", "clone", "--depth", "1", repo, d])
    uv, pre = uv_cmd(); steps += pre   # after the clone: the runner runs these in the trainer folder
    py = venv_python(d)
    if not os.path.isfile(venv_python(d)):
        steps.append(uv + ["venv", "--python", "3.12", os.path.join(d, ".venv")])
    pip = uv + ["pip", "install", "--python", py]
    steps += [pip + TORCH, pip + ["-r", "requirements.txt"]] + [pip + list(e) for e in extra]
    script = os.path.join(os.path.dirname(log), f"_install_steps_{os.path.basename(d)}.json")
    json.dump({"cwd": d, "steps": steps}, open(script, "w", encoding="utf-8"))
    return _spawn([sys.executable, "-u", os.path.join(HERE, "runner.py"), "steps", script, log], os.path.dirname(log))


def start_sd_install(d, log):
    return _install(SD_REPO, d, log)


def start_aitk_install(d, log):
    return _install(AITK_REPO, d, log)


# ---------------------------------------------------------------- prompts / folders
def parse_lines(text):
    """'neutral | positive | negative' per line -> [dict]; lines with one part are taken as extra neutral subjects"""
    out = []
    for ln in (text or "").splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if not parts[0]:
            continue
        out.append({"neutral": parts[0], "positive": parts[1] if len(parts) > 1 else "", "negative": parts[2] if len(parts) > 2 else ""})
    return out


def count_images(folder):
    return len([f for f in os.listdir(folder) if f.lower().endswith(IMG_EXT)]) if folder and os.path.isdir(folder) else 0


def check(cfg):
    """-> (ok, report lines). cfg: the node's settings (see nodes.FumikaSliderTrain)."""
    lines, ok = [], True
    if cfg["mode"] == "text":
        for k in ("positive", "negative"):
            if not cfg[k].strip():
                ok = False; lines.append(f"ERROR the {k} prompt is empty - it is one end of the slider")
        if cfg["positive"].strip() and cfg["positive"].strip() == cfg["negative"].strip():
            ok = False; lines.append("ERROR positive and negative are the same - the slider axis is their difference")
        t = parse_lines(cfg.get("targets", ""))
        lines.append(f"OK    axis: '{cfg['negative'][:60]}' (-)  <->  '{cfg['positive'][:60]}' (+)")
        lines.append(f"OK    {1 + len(t)} subject(s)" + (" - more subjects = a cleaner, more general slider" if not t else ""))
    else:
        n_pos, n_neg = count_images(cfg["pos_folder"]), count_images(cfg["neg_folder"])
        for side, n, d in (("positive", n_pos, cfg["pos_folder"]), ("negative", n_neg, cfg["neg_folder"])):
            if not n:
                ok = False; lines.append(f"ERROR no images in the {side} folder: {d or '(empty)'}")
            else:
                lines.append(f"OK    {side} end: {n} images")
        if n_pos and n_neg and n_pos != n_neg and cfg["family"] == "sdxl":
            lines.append("WARN  ai-toolkit pairs the images by file name: both folders should hold the same names")
    if cfg["rank"] > 16:
        lines.append(f"WARN  rank {cfg['rank']} is high for a slider - 4-8 (16 for SDXL) keeps the edit precise")
    return ok, lines


# ---------------------------------------------------------------- configs
def anima_config(cfg, out):
    """YAML dict for train_slider_anima.py (its option names)"""
    c = {"dit": cfg["dit"], "text_encoder": cfg["text_encoder"], "vae": cfg["vae"], "output_dir": out, "name": cfg["name"],
         "rank": cfg["rank"], "alpha": cfg["alpha"], "lr": cfg["lr"], "steps": cfg["steps"], "save_every": cfg["save_every"],
         "guidance_scale": cfg["guidance"], "gradient_checkpointing": True, "seed": cfg["seed"],
         "sample_every": cfg["save_every"], "sample_multipliers": "-2,-1,1,2"}
    if cfg.get("sample_prompt", "").strip():
        c["sample_prompts"] = [cfg["sample_prompt"].strip()]
    if cfg["mode"] == "text":
        c.update(mode="guidance", positive=cfg["positive"].strip(), negative=cfg["negative"].strip(), neutral=cfg["neutral"].strip())
        t = parse_lines(cfg.get("targets", ""))
        if t:   # the main prompts are the first target; more subjects make the direction general
            def tail(p):   # only what an end adds to the neutral prompt ("1girl, solo, big smile" -> "big smile")
                n = c["neutral"]
                return p[len(n):].lstrip(" ,") if n and p.startswith(n) else p
            c["targets"] = [{"neutral": c["neutral"], "positive": c["positive"], "negative": c["negative"]}] + [
                {"neutral": x["neutral"], "positive": x["positive"] or f"{x['neutral']}, {tail(c['positive'])}",
                 "negative": x["negative"] or f"{x['neutral']}, {tail(c['negative'])}"} for x in t]
        anchors = [a.strip() for a in (cfg.get("anchors") or "").splitlines() if a.strip()]
        if anchors:
            c["anchor"] = anchors; c["anchor_weight"] = cfg.get("anchor_weight", 0.5)
    else:
        c.update(mode="image_pair", pos_images=cfg["pos_folder"], neg_images=cfg["neg_folder"], pair_caption=cfg.get("pair_caption", "").strip())
    return c


def aitk_config(cfg, root):
    """ai-toolkit job for SDXL: text slider (process 'slider') or image reference slider (two folders)"""
    model = {"name_or_path": cfg["checkpoint"], "is_xl": True, "is_v_pred": bool(cfg.get("v_pred"))}
    sample_p = (cfg.get("sample_prompt") or cfg.get("neutral") or "1girl, solo").strip()
    sample = {"sampler": "ddpm", "sample_every": cfg["save_every"], "width": 1024, "height": 1024, "seed": cfg["seed"], "walk_seed": False,
              "guidance_scale": 5.5, "sample_steps": 28, "network_multiplier": 1.0,
              "prompts": [f"{sample_p} --m {m}" for m in (-2, -1, 1, 2)], "neg": "worst quality, low quality, lowres, watermark"}
    proc = {
            "network": {"type": "lierla", "linear": cfg["rank"], "linear_alpha": cfg["alpha"]},
            "train": {"noise_scheduler": "ddpm", "steps": cfg["steps"], "lr": cfg["lr"], "gradient_checkpointing": True, "train_unet": True,
                      "train_text_encoder": False, "optimizer": "adamw8bit", "lr_scheduler": "constant", "max_denoising_steps": 40,
                      "batch_size": 1, "dtype": "bf16", "noise_offset": 0.0},
            "model": model, "save": {"dtype": "float16", "save_every": cfg["save_every"], "max_step_saves_to_keep": 20},
            "sample": sample, "logging": {"log_every": 10, "use_wandb": False, "verbose": False}}
    if cfg["mode"] == "text":
        proc["type"] = "slider"; proc["train"]["min_snr_gamma"] = 5.0
        targets = [{"target_class": cfg["neutral"].strip(), "positive": cfg["positive"].strip(), "negative": cfg["negative"].strip(),
                    "weight": 1.0, "shuffle": False}]
        targets += [{"target_class": x["neutral"], "positive": x["positive"] or cfg["positive"].strip(), "negative": x["negative"] or cfg["negative"].strip(),
                     "weight": 1.0, "shuffle": False} for x in parse_lines(cfg.get("targets", ""))]
        anchors = [{"prompt": a.strip(), "neg_prompt": "", "multiplier": cfg.get("anchor_weight", 0.5)} for a in (cfg.get("anchors") or "").splitlines() if a.strip()]
        proc["slider"] = {"resolutions": [[1024, 1024]], "batch_full_slide": True, "targets": targets, "anchors": anchors}
        job = "train"
    else:
        proc["type"] = "image_reference_slider_trainer"
        proc["slider"] = {"datasets": [{"pos_folder": cfg["pos_folder"], "neg_folder": cfg["neg_folder"], "network_weight": 2.0,
                                        "target_class": cfg.get("pair_caption", "").strip(), "size": 1024}]}
        job = "extension"
    # training_folder / device belong to the job config, not the process (ai-toolkit: 'Missing "config.training_folder"', test 22 Oct)
    return {"job": job, "config": {"name": cfg["name"], "training_folder": root, "device": "cuda:0", "process": [proc]},
            "meta": {"name": "[name]", "version": "1.0"}}


def write_yaml(d, path):
    import yaml
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(d, f, sort_keys=False, allow_unicode=True)


def free_engine_vram():
    """Unload the engine's models before a training starts: the training is its own process, and models left on the GPU by
    earlier renders (several GB for Anima 2.9B / 3.8B or MOSS) made it spill into shared memory - 80 s per step instead of
    ~1 s (Fumika trainer test 23 Oct). Outside ComfyUI (tests, CLI) there is nothing to free."""
    try:
        import comfy.model_management as mm
        mm.unload_all_models()
        mm.soft_empty_cache()
    except Exception:
        pass


def launch(cfg, out, engine_dir):
    """write the config and start the engine in its own window; -> (pid, log)"""
    free_engine_vram()
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "train_log.txt")
    json.dump(cfg, open(os.path.join(out, "run_config.json"), "w", encoding="utf-8"), indent=1)
    if cfg["family"] == "anima":
        anima_blocks.patch(engine_dir)   # 2.9B / 3.8B: all 40 / 52 DiT blocks instead of a fixed 28
        y = os.path.join(out, "slider.yml"); write_yaml(anima_config(cfg, out), y)
        cmd = [venv_python(engine_dir), "-u", os.path.join(HERE, "train_slider_anima.py"), "--config", y]
        env = {"PYTHONPATH": engine_dir}   # the script imports sd-scripts' library / networks
    else:
        y = os.path.join(out, "slider_aitk.yaml"); write_yaml(aitk_config(cfg, os.path.dirname(out)), y)
        cmd = [venv_python(engine_dir), "-u", "run.py", y]
        env = {}
    return _spawn([sys.executable, "-u", os.path.join(HERE, "runner.py"), "one", log, engine_dir, "--"] + cmd, out, env), log


def _spawn(cmd, cwd, env=None):
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0   # own window: training survives a ComfyUI restart
    e = dict(os.environ); e.update(env or {})
    return subprocess.Popen(cmd, cwd=cwd, creationflags=flags, start_new_session=os.name != "nt",
                         stdout=subprocess.DEVNULL if os.name != "nt" else None, stderr=subprocess.STDOUT if os.name != "nt" else None, env=e).pid
