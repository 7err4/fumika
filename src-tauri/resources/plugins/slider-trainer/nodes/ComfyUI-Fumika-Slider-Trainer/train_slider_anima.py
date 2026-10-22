#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
train_slider_anima.py
=====================
Standalone *concept slider* LoRA trainer for the Anima diffusion model.

This implements the Concept Sliders objective (Gandikota et al., 2023),
"Option 2": it reuses sd-scripts' Anima model loading + the
``networks.lora_anima`` LoRA module, but runs its OWN training loop.

Key facts about Anima this loop respects:
  * Anima is RECTIFIED FLOW / velocity prediction (NOT DDPM-epsilon).
    Forward:  x_sigma = (1 - sigma) * x0 + sigma * noise,  sigma in [0, 1]
    Model predicts velocity v ~= (noise - x0).
    Sampler step: x_{i+1} = x_i - (sigma_i - sigma_{i+1}) * v
  * The slider guidance arithmetic is therefore done in VELOCITY space.

NO DATASET REQUIRED. The training signal comes entirely from the
positive / negative / neutral text prompts. The model generates its own
partially-denoised latents and is taught to shift them along the axis.

Loss per step (at a partially-denoised latent x_t, frozen base model):
    pos  = v(x_t, positive_prompt)        # frozen, multiplier 0
    neg  = v(x_t, negative_prompt)        # frozen, multiplier 0
    neu  = v(x_t, neutral_prompt)         # frozen, multiplier 0
    delta = guidance_scale * (pos - neg)

    # train the LoRA (grad on):
    pred_plus  = v(x_t, neutral_prompt)  with LoRA at +slider_scale
    pred_minus = v(x_t, neutral_prompt)  with LoRA at -slider_scale
    loss = 0.5 * ( MSE(pred_plus,  neu + delta)
                 + MSE(pred_minus, neu - delta) )

At inference, dialing the LoRA multiplier positive -> positive concept,
negative -> negative concept.

Run from the sd-scripts root directory, e.g.:
    python train_slider_anima.py --config configs/clothing_slider.yml
or with explicit flags (see --help).
"""

import os
import sys
import argparse
import random
import math

# Make `library` and `networks` importable when run from the sd-scripts root.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import torch
import torch.nn.functional as F

from library import anima_utils, qwen_image_autoencoder_kl
from library import strategy_anima
from library.hunyuan_image_utils import get_timesteps_sigmas, step as flow_step
import networks.lora_anima as lora_anima


# --------------------------------------------------------------------------- #
# Config                                                                       #
# --------------------------------------------------------------------------- #
def build_arg_parser():
    p = argparse.ArgumentParser(description="Concept slider LoRA trainer for Anima.")
    p.add_argument("--config", type=str, default=None,
                   help="Optional YAML config; values become defaults, CLI flags override.")

    # models
    p.add_argument("--dit", type=str, help="Path to Anima DiT .safetensors")
    p.add_argument("--text_encoder", type=str, help="Path to Qwen3-0.6B text encoder (dir or .safetensors)")
    p.add_argument("--vae", type=str, default=None, help="Path to Qwen-Image VAE (only needed for --sample_every)")

    # output
    p.add_argument("--output_dir", type=str, default="output/slider")
    p.add_argument("--name", type=str, default="anima_slider")

    # the slider axis
    p.add_argument("--positive", type=str, help="Prompt for the +1 extreme")
    p.add_argument("--negative", type=str, help="Prompt for the -1 extreme")
    p.add_argument("--neutral", type=str, default="", help="Neutral/target prompt (the thing you generate). Often the target_class, e.g. 'a woman'.")
    p.add_argument("--targets", default=None,
                   help="(YAML only) list of {neutral, positive, negative} dicts. Each step picks one at "
                        "random, so the slider learns coverage across many subjects/outfit priors. When set, "
                        "it overrides the single positive/negative/neutral above.")
    p.add_argument("--anchor", action="append", default=[],
                   help="Anchor prompt(s) whose output should NOT change with the slider. Repeatable.")
    p.add_argument("--anchor_weight", type=float, default=0.5)

    # image-pair (visual slider) mode — learn the axis from example images instead of prompts.
    p.add_argument("--mode", type=str, default="guidance", choices=["guidance", "image_pair"],
                   help="guidance = prompt-pair concept slider; image_pair = visual slider from example images.")
    p.add_argument("--neg_images", type=str, default=None, help="(image_pair) folder of NEGATIVE-end images (e.g. classy/elegant).")
    p.add_argument("--pos_images", type=str, default=None, help="(image_pair) folder of POSITIVE-end images (e.g. trashy).")
    p.add_argument("--image_root", type=str, default=None,
                   help="(image_pair, GRADED) root folder whose subfolder NAMES are signed weights "
                        "('-2','-1','1','2','3'...). Sign=side, magnitude=how far along the axis.")
    p.add_argument("--pair_caption", type=str, default="", help="(image_pair) caption for both ends; empty = unconditional.")
    p.add_argument("--pair_caption_pool", action="append", default=[],
                   help="(image_pair) repeatable / YAML list: one caption is drawn per step and used for BOTH sides of "
                        "that step (keeps the pair symmetric). Overrides --pair_caption. Per-image sidecar .txt wins over both.")
    p.add_argument("--pair_sigma_shift", type=float, default=1.0,
                   help="(image_pair) shift applied to the logit-normal sigma: s' = k*s / (1 + (k-1)*s). 1.0 = old behaviour "
                        "(median sigma 0.5); 3.0 = like Anima's flow shift -> more high-noise steps, where composition / "
                        "outfit are decided (weak sliders on characters with a strong outfit prior).")

    # network
    p.add_argument("--rank", type=int, default=8, help="LoRA dim. 4-8 is ideal for sliders.")
    p.add_argument("--alpha", type=float, default=4.0)
    p.add_argument("--slider_scale", type=float, default=1.0,
                   help="LoRA multiplier used DURING training for the +/- passes.")
    p.add_argument("--guidance_scale", type=float, default=3.0,
                   help="eta: how hard to push toward (positive-negative). 2-5 typical.")

    # training
    p.add_argument("--steps", type=int, default=500)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--height", type=int, default=1024)
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--flow_shift", type=float, default=3.0, help="Sigma schedule shift.")
    p.add_argument("--denoise_steps", type=int, default=30,
                   help="Scheduler resolution for the partial-denoise that produces x_t.")
    p.add_argument("--grad_clip", type=float, default=1.0)
    p.add_argument("--gradient_checkpointing", action="store_true")
    p.add_argument("--log_every", type=int, default=1, help="Print a loss/timing line every N steps.")

    # saving / sampling
    p.add_argument("--save_every", type=int, default=250)
    p.add_argument("--sample_every", type=int, default=100, help="0 disables previews. Needs --vae.")
    p.add_argument("--sample_steps", type=int, default=55)
    p.add_argument("--sample_height", type=int, default=0, help="Preview height; 0 = use --height. Lets you train small but preview at 1024.")
    p.add_argument("--sample_width", type=int, default=0, help="Preview width; 0 = use --width.")
    p.add_argument("--sample_cfg", type=float, default=5.0)
    p.add_argument("--sample_negative", type=str, default="",
                   help="Negative prompt used for CFG during previews. Empty = no negative (flatter images).")
    p.add_argument("--sample_at_end", action="store_true",
                   help="Render one preview sweep AFTER training finishes (use with sample_every: 0 to sample only at the end).")
    p.add_argument("--sample_multipliers", type=str, default="-2,-1,1,2")
    p.add_argument("--sample_prompts", action="append", default=[],
                   help="Prompt(s) to render sweeps for. Defaults to --neutral if none.")
    p.add_argument("--save_dtype", type=str, default="fp16", choices=["fp16", "bf16", "fp32"])

    # quick sanity-check mode: low-res, frequent previews, capped steps. Lets you see EARLY
    # whether the concept sticks before committing to a full high-res run.
    p.add_argument("--preview", action="store_true",
                   help="Fast low-res sanity run: trains + samples at --preview_res, samples often, caps steps.")
    p.add_argument("--preview_res", type=int, default=512)
    p.add_argument("--preview_steps", type=int, default=200)
    p.add_argument("--preview_sample_every", type=int, default=25)
    return p


def apply_preview_mode(args):
    """When --preview is set, force a quick low-res configuration so you can judge the concept
    early. Training resolution drops, previews fire often and at the same low res, steps are capped."""
    if not getattr(args, "preview", False):
        return args
    args.height = args.width = args.preview_res
    args.sample_height = args.sample_width = args.preview_res
    args.sample_every = args.preview_sample_every
    if args.save_every == 0 or args.save_every > args.preview_steps:
        args.save_every = max(args.preview_steps // 2, 50)
    args.steps = min(args.steps, args.preview_steps)
    print(f"[slider] PREVIEW MODE: {args.preview_res}px train+sample, {args.steps} steps, "
          f"sample every {args.sample_every}. Use this to check the concept, then drop --preview for the full run.")
    return args


def apply_yaml_config(args, parser):
    """If --config given, load YAML and use as defaults for any flag the user
    did not explicitly pass on the command line."""
    if not args.config:
        return args
    import yaml
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Which args did the user explicitly set on the CLI?
    explicit = set()
    for tok in sys.argv[1:]:
        if tok.startswith("--"):
            explicit.add(tok[2:].split("=")[0])

    for key, val in cfg.items():
        if key == "config":
            continue
        if not hasattr(args, key):
            print(f"[slider] WARNING: unknown config key '{key}' ignored")
            continue
        if key in explicit:
            continue  # CLI wins
        setattr(args, key, val)
    return args


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
DTYPE = torch.bfloat16


def load_models(args, device):
    print("[slider] loading Anima DiT ...")
    dit = anima_utils.load_anima_model(
        device=device,
        dit_path=args.dit,
        attn_mode="torch",
        split_attn=False,
        loading_device="cpu",
        dit_weight_dtype=DTYPE,
        fp8_scaled=False,
    )
    dit = dit.to(device, dtype=DTYPE).eval().requires_grad_(False)
    if args.gradient_checkpointing:
        for fn in ("enable_gradient_checkpointing", "gradient_checkpointing_enable"):
            if hasattr(dit, fn):
                try:
                    getattr(dit, fn)()
                    print(f"[slider] gradient checkpointing via {fn}()")
                    break
                except Exception as e:  # pragma: no cover
                    print(f"[slider] {fn}() failed: {e}")

    print("[slider] loading Qwen3 text encoder ...")
    text_encoder, _tok = anima_utils.load_qwen3_text_encoder(
        qwen3_path=args.text_encoder, dtype=DTYPE, device=str(device)
    )
    text_encoder = text_encoder.to(device, dtype=DTYPE).eval().requires_grad_(False)

    vae = None
    want_preview = bool(args.sample_every and args.sample_every > 0) or getattr(args, "sample_at_end", False)
    want_imgpair = getattr(args, "mode", "guidance") == "image_pair"
    if want_preview or want_imgpair:
        if not args.vae:
            if want_imgpair:
                raise SystemExit("[slider] image_pair mode requires --vae (to encode the example images).")
            print("[slider] WARNING: --sample_every set but no --vae given; disabling previews.")
            args.sample_every = 0
        else:
            print("[slider] loading VAE ...")
            vae = qwen_image_autoencoder_kl.load_vae(args.vae, device=str(device))
            vae = vae.to(device, dtype=DTYPE).eval()
    return dit, text_encoder, vae


def build_text_embedder(args, dit, text_encoder, device):
    tok = strategy_anima.AnimaTokenizeStrategy(
        qwen3_path=args.text_encoder, t5_tokenizer_path=None,
        qwen3_max_length=512, t5_max_length=512,
    )
    enc = strategy_anima.AnimaTextEncodingStrategy()

    @torch.no_grad()
    def embed(prompt: str) -> torch.Tensor:
        tokens = tok.tokenize(prompt)
        out = enc.encode_tokens(tok, [text_encoder], tokens)
        # out = [prompt_embeds, qwen3_attn_mask, t5_input_ids, t5_attn_mask]
        ctx = dit._preprocess_text_embeds(
            source_hidden_states=out[0].to(device),
            target_input_ids=out[2].to(device),
            target_attention_mask=out[3].to(device),
            source_attention_mask=out[1].to(device),
        )
        return ctx.to(device, dtype=DTYPE).detach()

    return embed


def make_network(args, text_encoder, dit, device):
    net = lora_anima.create_network(
        args.slider_scale,          # multiplier (overwritten via set_multiplier each step)
        args.rank,                  # network_dim
        args.alpha,                 # network_alpha
        None,                       # vae (unused)
        [text_encoder],             # text_encoders
        dit,                        # unet / DiT
        train_llm_adapter="false",
    )
    # Slider lives entirely in the DiT; do not touch the text encoder.
    net.apply_to([text_encoder], dit, apply_text_encoder=False, apply_unet=True)
    net = net.to(device, dtype=DTYPE)
    net.prepare_grad_etc(None, dit)
    net.train()
    return net


# --------------------------------------------------------------------------- #
# Sampling (preview sweeps)                                                    #
# --------------------------------------------------------------------------- #
@torch.no_grad()
def sample_image(dit, vae, net, ctx, uncond_ctx, args, device, multiplier, seed):
    net.set_multiplier(multiplier)
    g = torch.Generator(device="cpu").manual_seed(seed)
    sh = args.sample_height or args.height
    sw = args.sample_width or args.width
    hl, wl = sh // 8, sw // 8
    lat = torch.randn(1, 16, 1, hl, wl, generator=g).to(device, dtype=DTYPE)
    pad = torch.zeros(1, 1, hl, wl, device=device, dtype=DTYPE)
    _, sigmas = get_timesteps_sigmas(args.sample_steps, args.flow_shift, device)
    for i in range(args.sample_steps):
        t = sigmas[i].to(device, dtype=DTYPE).reshape(1)
        v_c = dit(lat, t, ctx, padding_mask=pad)
        if args.sample_cfg and args.sample_cfg != 1.0:
            v_u = dit(lat, t, uncond_ctx, padding_mask=pad)
            v = v_u + args.sample_cfg * (v_c - v_u)
        else:
            v = v_c
        lat = flow_step(lat, v, sigmas, i).to(DTYPE)
    img = vae.decode_to_pixels(lat.squeeze(2))  # [1,3,H,W] in [-1,1]
    img = ((img.float().clamp(-1, 1) + 1) * 127.5).round().to(torch.uint8)
    return img[0].permute(1, 2, 0).cpu().numpy()  # HWC


def save_sweep(dit, vae, net, embed, args, device, tag):
    from PIL import Image
    import numpy as np
    prompts = args.sample_prompts or [args.neutral or args.positive]
    mults = [float(x) for x in str(args.sample_multipliers).split(",") if x.strip() != ""]
    uncond_ctx = embed(getattr(args, "sample_negative", "") or "")
    os.makedirs(os.path.join(args.output_dir, "samples"), exist_ok=True)
    for pi, prompt in enumerate(prompts):
        ctx = embed(prompt)
        tiles = []
        for m in mults:
            arr = sample_image(dit, vae, net, ctx, uncond_ctx, args, device, m, args.seed + pi)
            tiles.append(arr)
        net.set_multiplier(args.slider_scale)  # restore
        strip = np.concatenate(tiles, axis=1)  # side by side across multipliers
        out = os.path.join(args.output_dir, "samples", f"{tag}_p{pi}.png")
        Image.fromarray(strip).save(out)
        print(f"[slider] saved sweep -> {out}  (multipliers {mults})")


# --------------------------------------------------------------------------- #
# Image-pair (visual slider) mode                                              #
# --------------------------------------------------------------------------- #
def _list_images(folder):
    import glob
    files = []
    for e in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp"):
        files += glob.glob(os.path.join(folder, e))
        files += glob.glob(os.path.join(folder, e.upper()))
    return sorted(set(files))


@torch.no_grad()
def _load_image_latent(path, vae, h, w, device):
    """Load -> center-crop/resize to (h,w) -> [-1,1] -> VAE latent [1,16,1,h/8,w/8]."""
    from PIL import Image
    import numpy as np
    img = Image.open(path).convert("RGB")
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
    iw, ih = img.size
    left, top = (iw - w) // 2, (ih - h) // 2
    img = img.crop((left, top, left + w, top + h))
    arr = np.asarray(img).astype("float32") / 127.5 - 1.0       # HWC in [-1,1]
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device, dtype=DTYPE)  # [1,3,H,W]
    lat = vae.encode_pixels_to_latents(t)                       # [1,16,h/8,w/8]
    if lat.dim() == 4:
        lat = lat.unsqueeze(2)                                  # -> [1,16,1,h/8,w/8]
    return lat.detach()


def _sidecar_caption(path):
    """<image>.txt next to the image -> its caption, else None."""
    t = os.path.splitext(path)[0] + ".txt"
    if os.path.isfile(t):
        with open(t, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def _collect_weighted_items(args, vae, device):
    """Build [(latent, weight)] items.
    - GRADED mode (args.image_root): each subfolder NAME is the signed multiplier the images
      inside should be reconstructed at (e.g. '-2','-1','1','2','3'). Magnitude = how far along
      the axis (e.g. skin level), sign = which side (classy/trashy).
    - LEGACY mode (args.neg_images/--pos_images): two folders at -/+ slider_scale."""
    items = []
    root = getattr(args, "image_root", None)
    if root:
        for sub in sorted(os.listdir(root)):
            d = os.path.join(root, sub)
            if not os.path.isdir(d):
                continue
            try:
                wt = float(sub.replace("+", ""))   # folder name -> weight
            except ValueError:
                print(f"[slider] skipping non-numeric folder '{sub}'")
                continue
            files = _list_images(d)
            if not files:
                continue
            for f in files:
                items.append((_load_image_latent(f, vae, args.height, args.width, device), wt, _sidecar_caption(f)))
            print(f"[slider]   weight {wt:+g}: {len(files)} images  ({sub})")
    else:
        assert args.neg_images and args.pos_images, "image_pair needs --image_root OR --neg_images/--pos_images"
        for f in _list_images(args.neg_images):
            items.append((_load_image_latent(f, vae, args.height, args.width, device), -args.slider_scale, _sidecar_caption(f)))
        for f in _list_images(args.pos_images):
            items.append((_load_image_latent(f, vae, args.height, args.width, device), +args.slider_scale, _sidecar_caption(f)))
    return items


def train_image_pair_loop(args, dit, vae, net, embed, optimizer, device):
    """Concept Sliders 'visual slider' loss, with PER-IMAGE weights: train the LoRA so that
    multiplier w reconstructs the images assigned weight w. Sign selects the side of the axis,
    magnitude selects how far along it (graded slider in a single LoRA)."""
    import time
    print("[slider] image_pair: encoding images ...")
    items = _collect_weighted_items(args, vae, device)
    assert items, "no training images found"
    neg_items = [it for it in items if it[1] < 0]
    pos_items = [it for it in items if it[1] > 0]
    sides = [s for s in (neg_items, pos_items) if s]
    assert sides, "need at least one weight folder (e.g. '1','2','3' for a one-directional 0->N slider)"
    print(f"[slider] image_pair (graded): {len(items)} images, "
          f"{len(neg_items)} negative-side / {len(pos_items)} positive-side"
          + ("   [one-directional]" if len(sides) == 1 else ""))

    pool = [c for c in (getattr(args, "pair_caption_pool", None) or []) if c is not None]
    if isinstance(pool, str):
        pool = [pool]
    _ctx_cache = {}

    def ctx_for(caption):
        if caption not in _ctx_cache:
            _ctx_cache[caption] = embed(caption)
        return _ctx_cache[caption]

    default_caps = pool or [args.pair_caption or ""]
    for c in default_caps:
        ctx_for(c)
    n_side = sum(1 for it in items if it[2] is not None)
    shift = float(getattr(args, "pair_sigma_shift", 1.0) or 1.0)
    print(f"[slider] image_pair captions: {len(default_caps)} pool caption(s), {n_side} sidecar .txt; "
          f"sigma shift {shift:g}")
    hl, wl = args.height // 8, args.width // 8
    pad = torch.zeros(1, 1, hl, wl, device=device, dtype=DTYPE)

    def noised(x0):
        # logit-normal timestep sampling (sigma in (0,1)), flow-matching forward + velocity target
        sigma = torch.sigmoid(torch.randn(1, device=device))
        if shift != 1.0:
            sigma = shift * sigma / (1.0 + (shift - 1.0) * sigma)
        sigma = sigma.to(DTYPE)
        noise = torch.randn_like(x0)
        x_t = ((1.0 - sigma) * x0 + sigma * noise).to(DTYPE)
        return x_t, (noise - x0), sigma.reshape(1)

    def one_pass(x0, wt, ctx):
        net.set_multiplier(wt)
        x_t, v_t, t = noised(x0)
        pred = dit(x_t, t, ctx, padding_mask=pad).float()
        loss = F.mse_loss(pred, v_t.float())
        loss.backward()
        return loss.item()

    print(f"[slider] image_pair training {args.steps} steps "
          f"(rank={args.rank}, res={args.height}x{args.width})")
    for stepi in range(1, args.steps + 1):
        _t = time.time()
        optimizer.zero_grad(set_to_none=True)
        total = 0.0

        # train one image from each non-empty side per step, at its OWN weight; one pool caption per step
        # for both sides (symmetric pair), a sidecar caption overrides it for that image
        step_cap = random.choice(default_caps)
        for side in sides:
            x0, wt, cap = random.choice(side)
            total += one_pass(x0, wt, ctx_for(cap if cap is not None else step_cap))

        if args.grad_clip and args.grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(net.parameters(), args.grad_clip)
        optimizer.step()

        if stepi % args.log_every == 0 or stepi == 1:
            print(f"[slider] step {stepi}/{args.steps}  loss={total:.5f}  ({time.time()-_t:.1f}s)", flush=True)
        if args.save_every and stepi % args.save_every == 0 and stepi < args.steps:
            _save(net, args, f"{args.name}-step{stepi:06d}")
        if args.sample_every and vae is not None and (stepi % args.sample_every == 0 or stepi == 1):
            net.eval()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            with torch.no_grad():
                save_sweep(dit, vae, net, embed, args, device, tag=f"step{stepi:06d}")
            net.train()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    _save(net, args, args.name)
    if getattr(args, "sample_at_end", False) and vae is not None:
        print("[slider] rendering final sample sweep ...")
        net.eval()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        with torch.no_grad():
            save_sweep(dit, vae, net, embed, args, device, tag="final")
    print("[slider] done.")


# --------------------------------------------------------------------------- #
# Training                                                                     #
# --------------------------------------------------------------------------- #
def train(args):
    assert args.dit and args.text_encoder, "Need --dit and --text_encoder"
    if getattr(args, "mode", "guidance") == "guidance":
        assert (args.positive and args.negative) or getattr(args, "targets", None), \
            "guidance mode needs --positive/--negative prompts or a targets list"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    dit, text_encoder, vae = load_models(args, device)
    embed = build_text_embedder(args, dit, text_encoder, device)
    net = make_network(args, text_encoder, dit, device)
    params, _ = net.prepare_optimizer_params_with_multiple_te_lrs(None, args.lr, args.lr)
    optimizer = torch.optim.AdamW(params, lr=args.lr)

    # IMAGE-PAIR (visual slider) mode: learn the axis from example images, not prompts.
    if getattr(args, "mode", "guidance") == "image_pair":
        train_image_pair_loop(args, dit, vae, net, embed, optimizer, device)
        return

    # ---- guidance (prompt-pair) mode ----
    # Multi-target: each entry is a {neu, pos, neg} triple; a step picks one at
    # random, so the slider learns the axis across many subject priors.
    print("[slider] encoding prompts ...")
    targets = []
    if getattr(args, "targets", None):
        for t in args.targets:
            targets.append({
                "neu": embed(t.get("neutral", args.neutral)),
                "pos": embed(t["positive"]),
                "neg": embed(t["negative"]),
            })
        print(f"[slider] {len(targets)} training targets (multi-subject)")
    else:
        targets.append({"neu": embed(args.neutral),
                        "pos": embed(args.positive),
                        "neg": embed(args.negative)})
    anchor_ctxs = [embed(a) for a in args.anchor]

    hl, wl = args.height // 8, args.width // 8
    pad = torch.zeros(1, 1, hl, wl, device=device, dtype=DTYPE)

    print(f"[slider] training {args.steps} steps  (rank={args.rank}, alpha={args.alpha}, "
          f"eta={args.guidance_scale}, scale={args.slider_scale}, res={args.height}x{args.width})")

    import time
    for stepi in range(1, args.steps + 1):
        _t_start = time.time()
        # pick this step's subject/outfit context
        tgt = random.choice(targets)
        pos_ctx, neg_ctx, neu_ctx = tgt["pos"], tgt["neg"], tgt["neu"]
        # --- produce a partially-denoised on-manifold latent x_t with the base model ---
        _, sigmas = get_timesteps_sigmas(args.denoise_steps, args.flow_shift, device)
        stop = random.randint(1, args.denoise_steps - 1)  # how many denoise steps to take
        lat = torch.randn(1, 16, 1, hl, wl, device=device, dtype=DTYPE)
        net.set_multiplier(0.0)
        with torch.no_grad():
            for i in range(stop):
                t = sigmas[i].to(device, dtype=DTYPE).reshape(1)
                v = dit(lat, t, neu_ctx, padding_mask=pad)
                lat = flow_step(lat, v, sigmas, i).to(DTYPE)
        x_t = lat.detach()
        cur_t = sigmas[stop].to(device, dtype=DTYPE).reshape(1)

        # --- frozen base predictions at (x_t, cur_t) ---
        with torch.no_grad():
            net.set_multiplier(0.0)
            pos = dit(x_t, cur_t, pos_ctx, padding_mask=pad).float()
            neg = dit(x_t, cur_t, neg_ctx, padding_mask=pad).float()
            neu = dit(x_t, cur_t, neu_ctx, padding_mask=pad).float()
            delta = args.guidance_scale * (pos - neg)
            target_plus = (neu + delta).detach()
            target_minus = (neu - delta).detach()
            anchor_bases = []
            for a_ctx in anchor_ctxs:
                anchor_bases.append(dit(x_t, cur_t, a_ctx, padding_mask=pad).float().detach())

        # --- trainable +/- passes on the neutral prompt ---
        # Back-prop each pass on its own so only ONE autograd graph is alive at a
        # time. Gradients accumulate into the LoRA params; this is mathematically
        # identical to summing the losses but uses a fraction of the peak VRAM.
        optimizer.zero_grad(set_to_none=True)
        loss_total = 0.0

        net.set_multiplier(+args.slider_scale)
        pred_plus = dit(x_t, cur_t, neu_ctx, padding_mask=pad).float()
        loss_plus = 0.5 * F.mse_loss(pred_plus, target_plus)
        loss_plus.backward()
        loss_total += loss_plus.item()
        del pred_plus, loss_plus

        net.set_multiplier(-args.slider_scale)
        pred_minus = dit(x_t, cur_t, neu_ctx, padding_mask=pad).float()
        loss_minus = 0.5 * F.mse_loss(pred_minus, target_minus)
        loss_minus.backward()
        loss_total += loss_minus.item()
        del pred_minus, loss_minus

        # --- anchors: slider must NOT move these (preserve at +/- scale) ---
        if anchor_bases:
            aw = args.anchor_weight / len(anchor_bases)
            for a_ctx, a_base in zip(anchor_ctxs, anchor_bases):
                net.set_multiplier(+args.slider_scale)
                ap = dit(x_t, cur_t, a_ctx, padding_mask=pad).float()
                la = aw * 0.5 * F.mse_loss(ap, a_base)
                la.backward()
                loss_total += la.item()
                del ap, la
                net.set_multiplier(-args.slider_scale)
                am = dit(x_t, cur_t, a_ctx, padding_mask=pad).float()
                la = aw * 0.5 * F.mse_loss(am, a_base)
                la.backward()
                loss_total += la.item()
                del am, la

        if args.grad_clip and args.grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(net.parameters(), args.grad_clip)
        optimizer.step()

        if stepi % args.log_every == 0 or stepi == 1:
            dt = time.time() - _t_start
            print(f"[slider] step {stepi}/{args.steps}  loss={loss_total:.5f}  "
                  f"({dt:.1f}s, stop={stop}, sigma={cur_t.item():.3f})", flush=True)

        if args.save_every and stepi % args.save_every == 0 and stepi < args.steps:
            _save(net, args, f"{args.name}-step{stepi:06d}")
        if args.sample_every and vae is not None and (stepi % args.sample_every == 0 or stepi == 1):
            net.eval()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            with torch.no_grad():
                save_sweep(dit, vae, net, embed, args, device, tag=f"step{stepi:06d}")
            net.train()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    _save(net, args, args.name)
    if getattr(args, "sample_at_end", False) and vae is not None:
        print("[slider] rendering final sample sweep ...")
        net.eval()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        with torch.no_grad():
            save_sweep(dit, vae, net, embed, args, device, tag="final")
    print("[slider] done.")


def _save(net, args, name):
    save_dtype = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[args.save_dtype]
    path = os.path.join(args.output_dir, f"{name}.safetensors")
    meta = {
        "anima_slider_neutral": str(args.neutral),
        "anima_slider_guidance_scale": str(args.guidance_scale),
        "anima_slider_rank": str(args.rank),
        "anima_slider_multi_target": str(bool(getattr(args, "targets", None))),
    }
    net.set_multiplier(1.0)  # neutral state for save
    net.save_weights(path, save_dtype, meta)
    print(f"[slider] saved LoRA -> {path}")


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    args = apply_yaml_config(args, parser)
    args = apply_preview_mode(args)
    train(args)


if __name__ == "__main__":
    main()
