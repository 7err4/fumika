# -*- coding: utf-8 -*-
"""Plain-Python helpers of the MOSS LoRA trainer pack (no ComfyUI imports): sd-scripts install, dataset check, tag -> sentence
captions, dataset.toml / command building, launching and progress parsing. Settings are the ones tested for the Civitai article
(MOSS-Image-Base, sd-scripts moss_image_train_network.py, RTX 5090)."""
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
    if not os.path.isfile(os.path.join(sd, "moss_image_train_network.py")):
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


def start_install(sd, log):
    """Clone sd-scripts + create its own venv + install torch (cu128) and requirements, in the background. Uses uv (picks Python
    3.12; installed into the engine's Python first when it is not on PATH). Returns immediately; progress goes to `log`."""
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
    script = os.path.join(os.path.dirname(log), "_install_steps.json")
    json.dump({"cwd": sd, "steps": steps}, open(script, "w", encoding="utf-8"))
    return _spawn([sys.executable, "-u", os.path.join(HERE, "runner.py"), "steps", script, log], os.path.dirname(log))


# ---------------------------------------------------------------- dataset
SUB = re.compile(r"^(\d+)_(.+)$")


def is_tag_caption(t):
    t = t.strip()
    parts = [p.strip() for p in t.split(",")]
    return len(parts) >= 4 and "." not in t[:-1] and sum(len(p.split()) <= 3 for p in parts) / len(parts) > 0.8


def check_dataset(root):
    """-> (ok, report text, samples per epoch). Same rules as the trainer: <repeats>_<name> folders, one .txt per image."""
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
    tags = multi = 0
    for d in good:
        rep = int(SUB.match(d).group(1)); p = os.path.join(root, d)
        imgs = [f for f in os.listdir(p) if f.lower().endswith(IMG_EXT)]
        miss = [f for f in imgs if not os.path.isfile(os.path.join(p, os.path.splitext(f)[0] + ".txt"))]
        empty = 0
        for f in imgs:
            tp = os.path.join(p, os.path.splitext(f)[0] + ".txt")
            if os.path.isfile(tp):
                t = open(tp, encoding="utf-8", errors="replace").read()
                empty += not t.strip(); tags += is_tag_caption(t); multi += "---===---" in t
        total += rep * len(imgs); imgs_all += len(imgs)
        lines.append(f"OK    {d}: {len(imgs)} images x {rep} = {rep * len(imgs)} samples" + (f", {len(miss)} WITHOUT caption" if miss else "")
                     + (f", {empty} empty captions" if empty else ""))
        if not imgs:
            lines.append(f"ERROR {d} contains no images"); ok = False
        if miss:
            ok = False
    if tags:
        lines.append(f"WARN  {tags} captions look like tag lists. MOSS was trained on sentences - use the 'MOSS Tag Captions to "
                     "Sentences' node (identity + outfit sentences + 'Scene details: <tags>').")
    if multi:
        lines.append(f"ERROR {multi} captions contain '---===---' candidates. They cannot be combined with cached text encoder outputs - "
                     "put alternative captions into a separate subset folder instead."); ok = False
    lines.append(f"TOTAL {imgs_all} images, {total} samples per epoch")
    return ok and total > 0, "\n".join(lines), total


# ---------------------------------------------------------------- captions
# WD tagger rating label -> rating sentence of the caption (editable table next to this file)
RATING = {k: v for k, v in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ratings.json"),
                                         encoding="utf-8")).items() if not k.startswith("_")}


def tags_to_sentences(src, dst, trigger, identity, outfits, drop, default_rating=None):
    """Convert Danbooru-tag captions into the MOSS caption format used for the article LoRAs:
    <rating sentence> <trigger + identity sentence> <outfit sentence for each outfit token> Scene details: <remaining tags>.
    outfits: {token: sentence}. Images are copied, subset folders kept. Returns number of captions written."""
    n = 0
    drop = {d.strip().lower() for d in drop if d.strip()} | {trigger.lower()}
    for dirpath, _, files in os.walk(src):
        rel = os.path.relpath(dirpath, src); out = os.path.join(dst, rel) if rel != "." else dst
        for f in files:
            if not f.lower().endswith(IMG_EXT):
                continue
            os.makedirs(out, exist_ok=True); shutil.copy2(os.path.join(dirpath, f), out)
            tp = os.path.join(dirpath, os.path.splitext(f)[0] + ".txt")
            tags = [t.strip() for t in open(tp, encoding="utf-8", errors="replace").read().split(",")] if os.path.isfile(tp) else []
            low = [t.lower() for t in tags]
            rating = next((RATING[t] for t in low if t in RATING), default_rating or RATING["sensitive"])
            outf = " ".join(outfits[t] for t in low if t in outfits)
            rest = [t for t, l in zip(tags, low) if t and l not in RATING and l not in outfits and l not in drop]
            cap = " ".join(x for x in (rating, f"{trigger}, {identity.strip().rstrip('.')}." if identity.strip() else trigger + ".", outf,
                                       ("Scene details: " + ", ".join(rest) + ".") if rest else "") if x)
            open(os.path.join(out, os.path.splitext(f)[0] + ".txt"), "w", encoding="utf-8").write(cap); n += 1
    return n


def parse_outfits(text):
    out = {}
    for ln in text.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip():
                out[k.strip().lower()] = v.strip()
    return out


# ---------------------------------------------------------------- training
def dataset_toml(root, resolution, batch):
    L = ['[general]', 'caption_extension = ".txt"', 'shuffle_caption = false', '[[datasets]]', f'resolution = {resolution}',
         f'batch_size = {batch}', 'enable_bucket = true', 'bucket_reso_steps = 64', 'min_bucket_reso = 512', 'max_bucket_reso = 1536']
    for d in sorted(os.listdir(root)):
        m = SUB.match(d)
        if m and os.path.isdir(os.path.join(root, d)):
            L += ['[[datasets.subsets]]', f'image_dir = {json.dumps(os.path.join(root, d).replace(os.sep, "/"), ensure_ascii=False)}', f'num_repeats = {int(m.group(1))}']
    return "\n".join(L) + "\n"


def train_command(cfg):
    """cfg: dict from the config node. Returns the argument list for moss_image_train_network.py (paths absolute)."""
    c = cfg; out = c["output_dir"]
    a = ["moss_image_train_network.py",
         "--pretrained_model_name_or_path", c["dit"], "--text_encoder", c["text_encoder"], "--vae", c["vae"],
         "--dataset_config", os.path.join(out, "dataset.toml"), "--output_dir", out, "--output_name", c["name"],
         "--save_model_as", "safetensors", "--network_module", "networks.lora_generic",
         "--network_dim", str(c["dim"]), "--network_alpha", str(c["alpha"]), "--network_train_unet_only",
         "--learning_rate", str(c["lr"]), "--optimizer_type", c["optimizer"], "--lr_scheduler", "cosine", "--lr_warmup_steps", "50",
         "--timestep_sampling", "sigma", "--weighting_scheme", "logit_normal", "--logit_mean", "-1.09", "--logit_std", "0.95",
         "--discrete_flow_shift", "1.0", "--save_every_n_epochs", str(c["save_every"]),
         "--mixed_precision", "bf16", "--gradient_checkpointing", "--cache_latents", "--cache_latents_to_disk",
         "--cache_text_encoder_outputs", "--cache_text_encoder_outputs_to_disk", "--max_data_loader_n_workers", "2",
         "--persistent_data_loader_workers", "--seed", str(c["seed"]), "--logging_dir", os.path.join(out, "logs")]
    # sd-scripts: --max_train_epochs overrides --max_train_steps, so pass only one of them
    a += ["--max_train_steps", str(c["max_steps"])] if c.get("max_steps") else ["--max_train_epochs", str(c["epochs"])]
    if c.get("sample_prompts", "").strip():
        a += ["--sample_prompts", os.path.join(out, "samples.txt"), "--sample_every_n_epochs", str(c["save_every"]), "--sample_sampler", "euler"]
    if c.get("resume"):
        a += ["--network_weights", c["resume"]]
    return a


def write_run_files(cfg):
    out = cfg["output_dir"]; os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "dataset.toml"), "w", encoding="utf-8").write(dataset_toml(cfg["dataset_dir"], cfg["resolution"], cfg["batch"]))
    if cfg.get("sample_prompts", "").strip():
        open(os.path.join(out, "samples.txt"), "w", encoding="utf-8").write(
            "\n".join(f"{p.strip()} --w 832 --h 1216 --d {i + 1} --s 30 --l 3.0" for i, p in enumerate(cfg["sample_prompts"].split("\n---\n")) if p.strip()) + "\n")
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
