# -*- coding: utf-8 -*-
"""Plain-Python helpers of the SDXL LoRA trainer pack (no ComfyUI imports): sd-scripts install, dataset check, dataset.toml /
command building for sdxl_train_network.py, launching and progress parsing. Recipe = the usual kohya SDXL LoRA settings for
Illustrious / NoobAI / Pony checkpoints (Danbooru tag captions, trigger word first)."""
import json
import os
import re
import shutil
import subprocess
import sys
import time

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
REPO = "https://github.com/kohya-ss/sd-scripts.git"
TORCH = ["torch==2.10.0", "torchvision", "--index-url", "https://download.pytorch.org/whl/cu128"]
LYCORIS = ["lycoris-lora"]   # LoKr / LoHa / LoCon (KohakuBlueleaf, Apache-2.0) - installed into the trainer's own venv
# network types: (network_module, network_args)
NETWORKS = {
    "LoRA": ("networks.lora", []),
    "LoCon": ("lycoris.kohya", ["algo=locon", "conv_dim=8", "conv_alpha=4"]),
    "LoHa": ("lycoris.kohya", ["algo=loha", "conv_dim=8", "conv_alpha=4"]),
    "LoKr": ("lycoris.kohya", ["algo=lokr", "factor=8", "full_matrix=True"]),
}
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- install
def venv_python(sd):
    return os.path.join(sd, ".venv", "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python")




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

def install_state(sd):
    if not os.path.isfile(os.path.join(sd, "sdxl_train_network.py")):
        return "missing"
    py = venv_python(sd)
    if not os.path.isfile(py):
        return "no_venv"
    try:
        r = subprocess.run([py, "-c", "import torch, accelerate, library; print(torch.__version__, torch.cuda.is_available())"],
                           cwd=sd, capture_output=True, text=True, timeout=180)
        return "ready " + r.stdout.strip() if r.returncode == 0 else "broken: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    except Exception as e:   # noqa: BLE001
        return f"broken: {e}"


def has_lycoris(sd):
    try:
        return subprocess.run([venv_python(sd), "-c", "import lycoris"], cwd=sd, capture_output=True, timeout=120).returncode == 0
    except Exception:   # noqa: BLE001
        return False


def start_lycoris_install(sd, log):
    """only the LyCORIS package, into an already installed trainer venv (separate window, like the full install)"""
    uv, pre = uv_cmd(); py = venv_python(sd)
    pip = uv + ["pip", "install", "--python", py]
    script = os.path.join(os.path.dirname(log), "_install_steps_lycoris.json")
    json.dump({"cwd": sd, "steps": pre + [pip + LYCORIS]}, open(script, "w", encoding="utf-8"))
    return _spawn([sys.executable, "-u", os.path.join(HERE, "runner.py"), "steps", script, log], os.path.dirname(log))


def pick_sd_scripts(comfy_dir):
    """the sd-scripts checkout to use: an installed one next to ComfyUI (the MOSS trainer's is the same upstream repo, so it is
    shared - no second 5-15 min install), else ComfyUI/sd-scripts-sdxl"""
    for name in ("sd-scripts-sdxl", "sd-scripts-moss"):
        d = os.path.join(comfy_dir, name)
        if install_state(d).startswith("ready"):
            return d
    return os.path.join(comfy_dir, "sd-scripts-sdxl")


def start_install(sd, log):
    """Clone sd-scripts + its own venv + torch (cu128) + requirements in a separate window; progress goes to `log`."""
    steps = []
    if not os.path.isdir(sd):
        steps.append(["git", "clone", "--depth", "1", REPO, sd])
    uv, pre = uv_cmd(); steps += pre   # after the clone: the runner runs these in the sd-scripts folder
    py = venv_python(sd)
    if not os.path.isfile(py):
        steps.append(uv + ["venv", "--python", "3.12", os.path.join(sd, ".venv")])
    pip = uv + ["pip", "install", "--python", py]
    steps.append(pip + TORCH)
    steps.append(pip + ["-r", "requirements.txt"])
    steps.append(pip + LYCORIS)
    script = os.path.join(os.path.dirname(log), "_install_steps_sdxl.json")
    json.dump({"cwd": sd, "steps": steps}, open(script, "w", encoding="utf-8"))
    return _spawn([sys.executable, "-u", os.path.join(HERE, "runner.py"), "steps", script, log], os.path.dirname(log))


# ---------------------------------------------------------------- dataset
SUB = re.compile(r"^(\d+)_(.+)$")


def check_dataset(root, trigger=""):
    """-> (ok, report text, samples per epoch). <repeats>_<name> folders, one .txt caption per image (Danbooru tags)."""
    lines, ok, total, imgs_all = [], True, 0, 0
    if not os.path.isdir(root):
        return False, f"ERROR: folder not found: {root}", 0
    subs = [d for d in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, d))]
    good = [d for d in subs if SUB.match(d)]
    for d in subs:
        if not SUB.match(d):
            lines.append(f"WARN  '{d}' is ignored - subset folders must be named <repeats>_<name>, e.g. 4_fumika")
    if not good:
        return False, "\n".join(lines + [f"ERROR: no <repeats>_<name> folders in {root}"]), 0
    no_trigger = 0
    for d in good:
        rep = int(SUB.match(d).group(1)); p = os.path.join(root, d)
        imgs = [f for f in os.listdir(p) if f.lower().endswith(IMG_EXT)]
        miss = [f for f in imgs if not os.path.isfile(os.path.join(p, os.path.splitext(f)[0] + ".txt"))]
        empty = 0
        for f in imgs:
            tp = os.path.join(p, os.path.splitext(f)[0] + ".txt")
            if os.path.isfile(tp):
                t = open(tp, encoding="utf-8", errors="replace").read().strip()
                empty += not t
                if trigger and not t.lower().startswith(trigger.lower()):
                    no_trigger += 1
        total += rep * len(imgs); imgs_all += len(imgs)
        lines.append(f"OK    {d}: {len(imgs)} images x {rep} = {rep * len(imgs)} samples" + (f", {len(miss)} WITHOUT caption" if miss else "")
                     + (f", {empty} empty captions" if empty else ""))
        if not imgs:
            lines.append(f"ERROR {d} contains no images"); ok = False
        if miss:
            ok = False
    if no_trigger:
        lines.append(f"WARN  {no_trigger} captions do not start with the trigger word '{trigger}' (it is kept in front while the "
                     "other tags are shuffled)")
    lines.append(f"TOTAL {imgs_all} images, {total} samples per epoch")
    return ok and total > 0, "\n".join(lines), total


# ---------------------------------------------------------------- training
def dataset_toml(root, resolution, batch, shuffle=True):
    # tag captions: shuffled every step, the first tag (trigger word) stays in front
    L = ['[general]', 'caption_extension = ".txt"', f'shuffle_caption = {"true" if shuffle else "false"}', 'keep_tokens = 1',
         '[[datasets]]', f'resolution = {resolution}', f'batch_size = {batch}', 'enable_bucket = true', 'bucket_reso_steps = 64',
         'min_bucket_reso = 512', 'max_bucket_reso = 2048']
    for d in sorted(os.listdir(root)):
        m = SUB.match(d)
        if m and os.path.isdir(os.path.join(root, d)):
            L += ['[[datasets.subsets]]', f'image_dir = {json.dumps(os.path.join(root, d).replace(os.sep, "/"), ensure_ascii=False)}', f'num_repeats = {int(m.group(1))}']
    return "\n".join(L) + "\n"


def ti_command(cfg):
    """embedding (textual inversion) for SDXL: sdxl_train_textual_inversion.py. The captions are not used - a template per
    kind (object = character / thing, style) around the token, as kohya's TI scripts do it."""
    c = cfg; out = c["output_dir"]
    a = ["sdxl_train_textual_inversion.py", "--pretrained_model_name_or_path", c["checkpoint"],
         "--dataset_config", os.path.join(out, "dataset.toml"), "--output_dir", out, "--output_name", c["name"],
         "--save_model_as", "safetensors", "--token_string", c["token"], "--init_word", c.get("init_word") or "woman",
         "--num_vectors_per_token", str(c.get("vectors", 4)), "--learning_rate", str(c["lr"]), "--optimizer_type", c["optimizer"],
         "--lr_scheduler", "constant", "--save_every_n_epochs", str(c["save_every"]), "--mixed_precision", "bf16", "--no_half_vae",
         "--gradient_checkpointing", "--sdpa", "--cache_latents", "--cache_latents_to_disk", "--max_data_loader_n_workers", "2",
         "--persistent_data_loader_workers", "--seed", str(c["seed"]), "--logging_dir", os.path.join(out, "logs"),
         "--use_style_template" if c.get("template") == "style" else "--use_object_template"]
    a += ["--max_train_steps", str(c["max_steps"])] if c.get("max_steps") else ["--max_train_epochs", str(c["epochs"])]
    return a


def train_command(cfg):
    """cfg: dict from SdxlEasyTrain. Returns the argument list for sdxl_train_network.py (paths absolute)."""
    c = cfg; out = c["output_dir"]
    if c.get("kind") == "embedding":
        return ti_command(c)
    module, args = NETWORKS[c.get("network", "LoRA")]
    a = ["sdxl_train_network.py",
         "--pretrained_model_name_or_path", c["checkpoint"],
         "--dataset_config", os.path.join(out, "dataset.toml"), "--output_dir", out, "--output_name", c["name"],
         "--save_model_as", "safetensors", "--network_module", module,
         "--network_dim", str(c["dim"]), "--network_alpha", str(c["alpha"]),
         "--learning_rate", str(c["lr"]), "--optimizer_type", c["optimizer"], "--lr_scheduler", "cosine", "--lr_warmup_steps", "50",
         "--save_every_n_epochs", str(c["save_every"]), "--mixed_precision", "bf16", "--save_precision", "bf16", "--no_half_vae",
         "--gradient_checkpointing", "--sdpa", "--cache_latents", "--cache_latents_to_disk",
         "--max_data_loader_n_workers", "2", "--persistent_data_loader_workers", "--seed", str(c["seed"]),
         "--logging_dir", os.path.join(out, "logs")]
    if args:
        a += ["--network_args", *args]
    if c.get("train_te"):
        a += ["--unet_lr", str(c["lr"]), "--text_encoder_lr", str(c["lr"] / 2)]
    else:
        a += ["--network_train_unet_only"]
    if c.get("v_pred"):   # NoobAI v-pred and other v-prediction checkpoints
        a += ["--v_parameterization", "--zero_terminal_snr"]
    else:
        a += ["--min_snr_gamma", "5"]
    a += ["--max_train_steps", str(c["max_steps"])] if c.get("max_steps") else ["--max_train_epochs", str(c["epochs"])]
    if c.get("sample_prompts", "").strip():
        a += ["--sample_prompts", os.path.join(out, "samples.txt"), "--sample_every_n_epochs", str(c["save_every"]), "--sample_sampler", "euler_a"]
    if c.get("resume"):
        a += ["--network_weights", c["resume"]]
    return a


def write_run_files(cfg):
    out = cfg["output_dir"]; os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "dataset.toml"), "w", encoding="utf-8").write(dataset_toml(cfg["dataset_dir"], cfg["resolution"], cfg["batch"]))
    if cfg.get("sample_prompts", "").strip():
        open(os.path.join(out, "samples.txt"), "w", encoding="utf-8").write(
            "\n".join(f"{p.strip()} --w 832 --h 1216 --d {i + 1} --s 28 --l 5.5" for i, p in enumerate(cfg["sample_prompts"].split("\n---\n")) if p.strip()) + "\n")
    json.dump(cfg, open(os.path.join(out, "run_config.json"), "w", encoding="utf-8"), indent=1)


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


def launch(cfg, sd):
    free_engine_vram()
    write_run_files(cfg)
    log = os.path.join(cfg["output_dir"], "train_log.txt")
    cmd = [venv_python(sd), "-u"] + train_command(cfg)
    return _spawn([sys.executable, "-u", os.path.join(HERE, "runner.py"), "one", log, sd, "--"] + cmd, cfg["output_dir"]), log


def _spawn(cmd, cwd):
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0   # own window: training survives a ComfyUI restart
    p = subprocess.Popen(cmd, cwd=cwd, creationflags=flags, start_new_session=os.name != "nt",
                         stdout=subprocess.DEVNULL if os.name != "nt" else None, stderr=subprocess.STDOUT if os.name != "nt" else None)
    return p.pid


STEP = re.compile(r"steps:\s+(\d+)%\|[^|]*\|\s*(\d+)/(\d+)\s*\[([^\]<]*)<([^,\]]*)[^\]]*?(?:avr_loss=([\d.]+))?\]")


def progress(log):
    """Parse the newest tqdm line of a training log -> dict(state, step, total, elapsed, remaining, loss, last lines)."""
    if not os.path.isfile(log):
        return {"state": "no log yet", "tail": ""}
    raw = open(log, "rb").read()[-200000:].decode("utf-8", "replace")
    m = None
    for m in STEP.finditer(raw):
        pass
    tail = "\n".join([ln for ln in raw.replace("\r", "\n").splitlines() if ln.strip() and "steps:" not in ln][-12:])
    st = "finished" if "TRAIN_EXIT 0" in raw else ("FAILED" if re.search(r"TRAIN_EXIT [1-9]", raw) else ("training" if m else "starting"))
    d = {"state": st, "tail": tail, "updated": time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(log)))}
    if m:
        d.update(step=int(m.group(2)), total=int(m.group(3)), elapsed=m.group(4).strip(), remaining=m.group(5).strip(), loss=m.group(6))
    return d
