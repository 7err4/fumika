"""
ComfyUI Node: Anima VRAM Estimator
Estimates peak training VRAM for a TRAINING_PARAMS configuration BEFORE
launching, with a per-component breakdown, a fits/tight/OOM verdict
against your GPU, and concrete suggestions when it doesn't fit.

Pass-through node: place it between any param node (Wizard / Basic /
Advanced / Memory Optimizer) and the Training Launcher.

The model is a calibrated heuristic, not a profiler. Real usage varies
with driver, PyTorch version, and allocator fragmentation — expect the
true peak to land within roughly +/-20% of the estimate. The constants
below are tuned so representative Anima configs match community-reported
numbers (e.g. ~5 GB peak for the 6 GB minimum preset at 768px, batch 1,
heavy block swap).
"""

import copy
import inspect
import math


# ─── Anima (Cosmos-Predict2-2B based) architecture constants ─────────
DIT_WEIGHTS_GB = 4.18          # bf16 DiT checkpoint size on GPU
DIT_NUM_BLOCKS = 28            # transformer blocks (swappable units)
DIT_BLOCK_WEIGHT_FRACTION = 0.88  # share of weights that live in the blocks
DIT_HIDDEN_DIM = 2048
TEXT_ENCODER_GB = 1.2          # Qwen3-0.6B bf16 resident size
VAE_GB = 0.25                  # Qwen-Image VAE (latent caching phase only)

# ─── Calibrated cost-model constants ─────────────────────────────────
BASE_OVERHEAD_GB = 1.0         # CUDA context + allocator reserve + workspaces
SWAP_BUFFER_GB = 0.3           # pinned/double-buffer cost when block swap is on
# Activation multiplier: activations ≈ tokens*hidden*2bytes*batch * K
ACT_K_CHECKPOINTING = 247      # with gradient checkpointing
ACT_K_NO_CHECKPOINTING = 640   # without (stores every block's activations)
# LoRA trainable-parameter estimate: params ≈ rank * this * network factor
LORA_PARAMS_PER_RANK = 1.05e6
NETWORK_PARAM_FACTOR = {"lora": 1.0, "lokr": 0.35, "loha": 2.0}
# Attention backend savings on activation memory
ATTN_FACTOR = {"torch": 1.0, "xformers": 0.90, "flash": 0.88, "sageattn": 0.88}
SPLIT_ATTN_FACTOR = 0.90
# fp16 old-GPU mode costs EXTRA activation memory, counterintuitively:
# sd-scripts' stability fix upcasts Anima's block computations to fp32
# when the input is float16 (verified in library/anima_models.py: the
# residual stream, AdaLN modulation, and conditional block computations
# run in fp32), so a chunk of the activations is 4 bytes instead of 2.
# The exact magnitude is NOT field-measured yet — 1.5 is a theory-derived
# middle estimate between "all fp32" (2.0x) and "only residuals" (~1.3x).
# Recalibrate when real fp16-vs-bf16 measurements come in.
FP16_UPCAST_ACT_FACTOR = 1.5
# Optimizer state bytes per trainable parameter
OPTIMIZER_BYTES_PER_PARAM = {
    "AdamW": 8.0, "AdamW8bit": 2.0, "AdaFactor": 4.0,
    "Prodigy": 16.0, "Lion": 4.0, "Lion8bit": 1.0,
    "DAdaptation": 16.0, "DAdaptAdam": 16.0,
}
# Trainable network weights are kept fp32 (master) + fp32 grads
NETWORK_WEIGHT_BYTES = 4.0
NETWORK_GRAD_BYTES = 4.0

ESTIMATE_TOLERANCE = 0.20      # +/- band around the point estimate

LOG_PREFIX = "[AnimaVRAMEstimator]"


def _parse_resolution(resolution) -> tuple:
    """Parse 'W,H' or a single value into (w, h). Falls back to 1024x1024."""
    try:
        parts = [int(p.strip()) for p in str(resolution).split(",") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
        if len(parts) == 1:
            return parts[0], parts[0]
    except (ValueError, TypeError):
        pass
    return 1024, 1024


def estimate_training_vram(params: dict) -> dict:
    """Estimate peak training-phase VRAM (GB) for a training_params dict.

    Returns a dict with per-component GB values, 'total', and the
    low/high band. All values are heuristic estimates (see module doc).
    """
    w, h = _parse_resolution(params.get("resolution", "1024,1024"))
    batch = max(1, int(params.get("train_batch_size", 1) or 1))
    rank = max(1, int(params.get("network_rank", 16) or 16))
    network_type = str(params.get("network_type", "LoRA")).lower()
    optimizer = str(params.get("optimizer_type", "AdamW8bit"))
    attn_mode = str(params.get("attn_mode", "torch")).lower()
    split_attn = bool(params.get("split_attn", False))
    grad_ckpt = bool(params.get("gradient_checkpointing", True))
    cache_te = bool(params.get("cache_text_encoder_outputs", True)) or \
        bool(params.get("cache_text_encoder_outputs_to_disk", False))
    # Anima 2.9B / 3.8B have 40 / 52 blocks (set by estimate() from the checkpoint, never written into training_params)
    n_blocks = max(1, int(params.get("_dit_blocks", DIT_NUM_BLOCKS) or DIT_NUM_BLOCKS))
    blocks_to_swap = max(0, min(int(params.get("blocks_to_swap", 0) or 0), n_blocks))

    # DiT weights resident on GPU (block swap moves block weights to CPU,
    # but needs pinned transfer buffers and keeps ~2 blocks in flight)
    resident_fraction = 1.0 - DIT_BLOCK_WEIGHT_FRACTION * (blocks_to_swap / n_blocks)
    # Anima 2.9B / 3.8B: more blocks -> bigger weights, more LoRA modules, more checkpointed activations (scale = checkpoint
    # size / Anima 1.0; set by estimate() from the model selector's file, never written into training_params)
    scale = float(params.get("_dit_scale", 1.0) or 1.0)
    dit_gb = DIT_WEIGHTS_GB * scale * resident_fraction + (SWAP_BUFFER_GB if blocks_to_swap > 0 else 0.0)

    # Text encoder: freed after caching when TE outputs are cached
    te_gb = 0.0 if cache_te else TEXT_ENCODER_GB

    # Trainable network: fp32 weights + fp32 grads + optimizer state
    n_params = LORA_PARAMS_PER_RANK * rank * NETWORK_PARAM_FACTOR.get(network_type, 1.0) * scale
    opt_bytes = OPTIMIZER_BYTES_PER_PARAM.get(optimizer, 8.0)
    network_gb = n_params * (NETWORK_WEIGHT_BYTES + NETWORK_GRAD_BYTES + opt_bytes) / 1e9

    # Activations: dominant, scale with tokens x batch.
    # Latent = pixels/8 (VAE), then 2x2 patchify -> tokens = ceil(W/16)*ceil(H/16)
    tokens = math.ceil(w / 16) * math.ceil(h / 16)
    act_base_gb = tokens * DIT_HIDDEN_DIM * 2 * batch / 1e9
    k = ACT_K_CHECKPOINTING if grad_ckpt else ACT_K_NO_CHECKPOINTING
    act_factor = ATTN_FACTOR.get(attn_mode, 1.0) * (SPLIT_ATTN_FACTOR if split_attn else 1.0)
    # fp16 old-GPU mode: stability upcasting makes activations bigger, not smaller
    is_fp16 = str(params.get("mixed_precision", "bf16")).lower() == "fp16"
    if is_fp16:
        act_factor *= FP16_UPCAST_ACT_FACTOR
    activations_gb = act_base_gb * k * act_factor * scale

    total = BASE_OVERHEAD_GB + dit_gb + te_gb + network_gb + activations_gb

    return {
        "overhead": BASE_OVERHEAD_GB,
        "dit_weights": dit_gb,
        "text_encoder": te_gb,
        "network_and_optimizer": network_gb,
        "activations": activations_gb,
        "total": total,
        "total_low": total * (1.0 - ESTIMATE_TOLERANCE),
        "total_high": total * (1.0 + ESTIMATE_TOLERANCE),
        "tokens": tokens,
        "resolution": (w, h),
        "blocks_to_swap": blocks_to_swap,
        "num_blocks": n_blocks,
        "is_fp16": is_fp16,
    }


def _fmt_gb(v: float) -> str:
    return f"{v:.1f} GB"


def _suggestions(params: dict, est: dict, gpu_vram_gb: float) -> list:
    """Concrete, ordered suggestions to bring the estimate under budget.
    Each entry re-runs the estimator on a modified copy of params so the
    user sees the projected effect, not vague advice — and each carries
    a 'where:' line telling them where that knob actually lives, which
    differs between the Wizard (presets + force_* fields) and the manual
    node chain (Basic Params / Memory Optimizer)."""
    out = []
    # The wizard tags its params; manual chains (Basic Params) don't.
    is_wizard = bool(params.get("_wizard_mode"))

    def _project(changes: dict, label: str, where_wizard: str, where_manual: str):
        p = copy.deepcopy(params)
        p.update(changes)
        new_total = estimate_training_vram(p)["total"]
        saved = est["total"] - new_total
        if saved > 0.05:
            where = where_wizard if is_wizard else where_manual
            out.append(
                f"{label}  ->  ~{_fmt_gb(new_total)} (saves ~{_fmt_gb(saved)})"
                f"\n     where: {where}"
            )

    batch = max(1, int(params.get("train_batch_size", 1) or 1))
    if batch > 1:
        _project({"train_batch_size": 1},
                 "Train one image per step",
                 "set force_batch_size=1 on the wizard",
                 "train_batch_size on Basic Params")

    if not params.get("gradient_checkpointing", True):
        _project({"gradient_checkpointing": True},
                 "Turn on the recompute trick - slower, much less VRAM",
                 "on in every GPU preset except '24 GB+ (high)' - pick a lower "
                 "preset, or add a Memory Optimizer node (gradient_checkpointing)",
                 "gradient_checkpointing on the Memory Optimizer node")

    swap = est["blocks_to_swap"]
    if swap < 24:
        _project({"blocks_to_swap": 24},
                 f"Park more of the model in normal RAM - slower steps, same quality ({swap} -> 24 parts)",
                 "set force_blocks_to_swap=24 on the wizard (lower GPU presets also do this)",
                 "blocks_to_swap on the Memory Optimizer node")

    w, h = est["resolution"]
    if max(w, h) > 768:
        _project({"resolution": "768,768"},
                 f"Train on smaller images: {w}x{h} -> 768x768",
                 "pick 768x768 under image_resolution on the wizard",
                 "resolution on Basic Params")
    elif max(w, h) > 512:
        _project({"resolution": "512,512"},
                 f"Train on smaller images: {w}x{h} -> 512x512",
                 "pick 512x512 under image_resolution on the wizard",
                 "resolution on Basic Params")

    if str(params.get("attn_mode", "torch")).lower() == "torch" or not params.get("split_attn", False):
        _project({"attn_mode": "xformers", "split_attn": True},
                 "Switch to memory-saving attention",
                 "comes with GPU presets '10 GB' and below, or add a Memory "
                 "Optimizer node (attn_mode=xformers + split_attn)",
                 "attn_mode=xformers + split_attn on the Memory Optimizer node")

    cache_te = bool(params.get("cache_text_encoder_outputs", True)) or \
        bool(params.get("cache_text_encoder_outputs_to_disk", False))
    if not cache_te:
        _project({"cache_text_encoder_outputs": True},
                 "Prepare captions once up front instead of every step",
                 "on in every GPU preset - if you disabled it, re-enable via a "
                 "Memory Optimizer node (cache_text_encoder_outputs)",
                 "cache_text_encoder_outputs on the Memory Optimizer node")

    optimizer = str(params.get("optimizer_type", "AdamW8bit"))
    if optimizer in ("AdamW", "Prodigy", "DAdaptation", "DAdaptAdam", "Lion"):
        _project({"optimizer_type": "AdamW8bit"},
                 f"Use the memory-saving trainer: {optimizer} -> AdamW8bit",
                 "comes from your quality_goal choice - 'high quality' uses "
                 "AdamW; the other goals already use AdamW8bit",
                 "optimizer_type on Basic Params")

    rank = int(params.get("network_rank", 16) or 16)
    if rank > 16:
        _project({"network_rank": 16},
                 f"Lower LoRA rank {rank} -> 16 (smaller LoRA, slightly less capacity)",
                 "set force_network_rank=16 on the wizard",
                 "network_rank on Basic Params")

    return out


class AnimaVRAMEstimator:
    """
    Estimates peak training VRAM for the connected training parameters,
    with a breakdown, a verdict against your GPU size, and suggestions.
    Pass-through: connect between your param nodes and the Launcher.
    Purely informational — it never modifies the parameters or blocks
    the workflow.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "training_params": ("TRAINING_PARAMS", {
                    "tooltip": "Params from Wizard / Basic / Advanced / Memory Optimizer."
                }),
                "gpu_vram_gb": ("FLOAT", {
                    "default": 12.0, "min": 0.0, "max": 256.0, "step": 0.5,
                    "tooltip": "Your GPU's total VRAM in GB (e.g. 6, 8, 10, 12). "
                               "0 = show the estimate without a fits/OOM verdict."
                }),
            },
            "optional": {
                "model_config": ("ANIMA_MODEL_CONFIG", {
                    "tooltip": "From the Model Selector: the estimate then uses the real DiT size (Anima 2.9B / 3.8B are larger)."
                }),
            },
        }

    RETURN_TYPES = ("TRAINING_PARAMS", "STRING")
    RETURN_NAMES = ("training_params", "vram_report")
    FUNCTION = "estimate"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = True

    def estimate(self, training_params: dict, gpu_vram_gb: float = 12.0, model_config: dict = None):
        import json
        import os
        sized = dict(training_params)
        dit = (model_config or {}).get("pretrained_model") or ""
        notes = []
        if dit and os.path.isfile(dit):
            sized["_dit_scale"] = max(1.0, os.path.getsize(dit) / 1e9 / DIT_WEIGHTS_GB)
            sized["_dit_blocks"] = _count_blocks(dit)
            sized, notes = fit_to_gpu(sized, gpu_vram_gb)
        report, verdict = build_report(sized, gpu_vram_gb)
        if notes:
            report = "\n".join(notes) + "\n\n" + report
        chart = build_chart(estimate_training_vram(sized), gpu_vram_gb, verdict)
        # the adjusted settings go on to the launcher; the size factor is only for the estimate
        training_params = {k: v for k, v in sized.items() if k not in ("_dit_scale", "_dit_blocks")}
        print(f"{LOG_PREFIX} peak estimate report generated (verdict: {verdict})", flush=True)
        # ui -> inline display on the node (text report + bar chart data,
        # mirrors Config Preview); result -> pass-through so the node can
        # sit inline in the chain.
        return {
            "ui": {"text": (report,), "chart": (json.dumps(chart),)},
            "result": (training_params, report),
        }


def build_chart(est: dict, gpu_vram_gb: float, verdict: str) -> dict:
    """Structured per-component data for the node's bar-chart widget.
    Component order and labels are what the JS renders — keep in sync
    with COMPONENT_COLORS in js/vram_estimator.js."""
    try:
        gpu = float(gpu_vram_gb or 0)
    except (TypeError, ValueError):
        gpu = 0.0
    return {
        "components": [
            ["Model on GPU", round(est["dit_weights"], 2)],
            ["Working memory", round(est["activations"], 2)],
            ["LoRA + trainer", round(est["network_and_optimizer"], 2)],
            ["Text encoder", round(est["text_encoder"], 2)],
            ["System overhead", round(est["overhead"], 2)],
        ],
        "total": round(est["total"], 2),
        "low": round(est["total_low"], 2),
        "high": round(est["total_high"], 2),
        "gpu": gpu,
        "verdict": verdict,
    }


def _count_blocks(path: str) -> int:
    """Transformer blocks of a DiT checkpoint from its safetensors header ("blocks.N." keys); Anima 1.0's 28 if unreadable."""
    import json
    import re
    import struct
    try:
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            keys = json.loads(f.read(n)).keys() if 0 < n < 100_000_000 else ()
        idx = [int(m.group(1)) for k in keys for m in [re.search(r"(?:^|\.)blocks\.(\d+)\.", k)] if m]
        return max(idx) + 1 if idx else DIT_NUM_BLOCKS
    except Exception:
        return DIT_NUM_BLOCKS


def fit_to_gpu(params: dict, gpu_vram_gb: float) -> tuple:
    """The wizard's VRAM tiers are tuned for Anima 1.0 (28 blocks). A larger checkpoint (2.9B / 3.8B, params["_dit_scale"] > 1)
    with the same tier can overflow the card - Anima 3.8B on "24 GB+" without gradient checkpointing spilled into shared
    memory at ~60 s/step on 32 GB (Fumika trainer test 23 Oct). Turn on gradient checkpointing, then block swap, until the
    estimate fits. Returns (params, notes)."""
    out, notes = dict(params), []
    if gpu_vram_gb <= 0 or float(out.get("_dit_scale", 1.0)) <= 1.05:
        return out, notes
    # upper end of the band, like the "fits" verdict: the 3.8B estimate without checkpointing was ~15 % low in the test
    fits = lambda p: estimate_training_vram(p)["total_high"] <= gpu_vram_gb * 0.92
    if fits(out):
        return out, notes
    if not out.get("gradient_checkpointing"):
        out["gradient_checkpointing"] = True
        notes.append("Larger Anima model: gradient checkpointing turned on so it fits the card (a little slower).")
    swap = int(out.get("blocks_to_swap", 0) or 0)
    max_swap = int(out.get("_dit_blocks", DIT_NUM_BLOCKS) or DIT_NUM_BLOCKS) - 4
    while not fits(out) and swap < max_swap:
        swap = min(max_swap, swap + 4)
        out["blocks_to_swap"] = swap
    if swap and swap != int(params.get("blocks_to_swap", 0) or 0):
        notes.append(f"Larger Anima model: {swap} blocks swapped to CPU memory so it fits the card (slower).")
    return out, notes


def build_report(training_params: dict, gpu_vram_gb: float, live: bool = False) -> tuple:
    """Build the human-readable VRAM report. Returns (report, verdict).

    `live=True` marks the report as a pre-run estimate driven by the
    browser (see the /anima_lora/estimate_vram endpoint below) — same
    math, different header so users know it updates as they edit.
    """
    est = estimate_training_vram(training_params)
    w, h = est["resolution"]

    if live:
        lines = [
            "── LIVE ESTIMATE (updates as you edit) ──",
            "",
        ]
    else:
        lines = [
            "╔══════════════════════════════════════════╗",
            "║       Estimated Training VRAM Cost       ║",
            "╚══════════════════════════════════════════╝",
            "",
        ]

    # Plain-language summary of the active memory tricks
    tricks = []
    if est["blocks_to_swap"] > 0:
        tricks.append(f"model streaming ({est['blocks_to_swap']}/{est['num_blocks']} parts in RAM)")
    if training_params.get("gradient_checkpointing", True):
        tricks.append("recompute trick")
    if training_params.get("split_attn", False) or \
            str(training_params.get("attn_mode", "torch")).lower() != "torch":
        tricks.append("memory-saving attention")

    lines += [
            f"  Setup: {w}x{h} images, "
            f"{training_params.get('train_batch_size', 1)} per step, "
            f"LoRA rank {training_params.get('network_rank', 16)}, "
            f"{training_params.get('optimizer_type', 'AdamW8bit')} trainer",
            f"  Memory tricks on: {', '.join(tricks) if tricks else 'none'}",
            "",
            "─── What uses the memory ───",
            f"  Model on GPU:            {_fmt_gb(est['dit_weights'])}"
            f"{'  (rest is parked in normal RAM)' if est['blocks_to_swap'] > 0 else ''}",
            f"  Working memory:          {_fmt_gb(est['activations'])}  (grows with image size & batch)"
            f"{chr(10) + '                           NOTE: fp16 old-GPU mode needs MORE of this than bf16!' if est.get('is_fp16') else ''}",
            f"  Your LoRA + trainer:     {_fmt_gb(est['network_and_optimizer'])}",
            f"  Text encoder:            "
            f"{_fmt_gb(est['text_encoder']) if est['text_encoder'] else '0.0 GB (prepared once, then freed)'}",
            f"  System overhead:         {_fmt_gb(est['overhead'])}",
            "  ────────────────────────────",
            f"  ESTIMATED PEAK:          {_fmt_gb(est['total'])}  "
            f"(range {_fmt_gb(est['total_low'])} – {_fmt_gb(est['total_high'])})",
            "",
    ]

    verdict = "info"
    if gpu_vram_gb > 0:
        if est["total_high"] <= gpu_vram_gb * 0.92:
            verdict = "fits"
            lines.append(f"  VERDICT: FITS on {gpu_vram_gb:g} GB with headroom.")
        elif est["total"] <= gpu_vram_gb * 0.95:
            verdict = "tight"
            lines.append(f"  VERDICT: TIGHT on {gpu_vram_gb:g} GB - may run out of memory")
            lines.append("  depending on what else is using the card (see note below).")
        else:
            verdict = "oom"
            lines.append(f"  VERDICT: LIKELY OOM on {gpu_vram_gb:g} GB.")
        lines.append("")
        if verdict != "fits":
            sugg = _suggestions(training_params, est, gpu_vram_gb)
            if sugg:
                lines.append("─── Suggestions (projected new peak) ───")
                for i, s in enumerate(sugg, 1):
                    lines.append(f"  {i}. {s}")
                lines.append("")

    # ── Compact dataset status (full details in the wizard summary) ──
    lines.extend(_dataset_status_lines(training_params))

    lines.append("This is an estimate (about +/-20%), not a measurement.")
    lines.append("Windows and your monitor typically use another 0.5-1 GB of")
    lines.append("the same card. Before training, close games and other")
    lines.append("GPU-hungry apps (video editors, image generators) - and")
    lines.append("don't generate images in ComfyUI while training runs.")

    return "\n".join(lines), verdict


def _dataset_status_lines(training_params: dict) -> list:
    """One-glance dataset status for the estimator report. Compact on
    purpose — the wizard / Basic Params summaries carry the full report."""
    try:
        from ..utils.dataset_check import check_dataset
    except ImportError:
        from utils.dataset_check import check_dataset

    data_dir = (training_params.get("train_data_dir") or "").strip()
    if not data_dir:
        return ["Dataset: no training folder set yet.", ""]
    ds = check_dataset(data_dir, training_params.get("caption_extension", ".txt"))
    if ds["ok"]:
        line = (f"Dataset: OK - {ds['total_images']} image(s), "
                f"{ds['total_steps_per_epoch']} steps/epoch")
        if ds["warnings"]:
            line += f", {len(ds['warnings'])} warning(s) - see the wizard summary"
        return [line, ""]
    out = []
    for e in ds["errors"][:2]:
        out.append(f"Dataset PROBLEM: {e}")
    out.append("Training will NOT start until this is fixed (the Launcher checks it too).")
    out.append("")
    return out


# ─── Live pre-run estimation (no queue needed) ───────────────────────
# The node's JS walks the graph upstream from the estimator, collects
# each param node's type + widget values, and POSTs them here. We
# re-derive TRAINING_PARAMS by calling the SAME node entry functions
# the queue would call — zero logic duplication, so the live number
# always matches what an actual run would report.

def _call_with_known_kwargs(func, widgets: dict, extra: dict = None):
    """Call `func` with only the kwargs it declares, taking values from
    `widgets` (browser-supplied, may contain unknown/extra keys) and
    falling back to the function's own defaults for anything missing."""
    sig = inspect.signature(func)
    kwargs = dict(extra or {})
    for name, param in sig.parameters.items():
        if name in ("self", "kwargs"):
            continue
        if name in widgets:
            kwargs[name] = widgets[name]
        elif param.default is inspect.Parameter.empty and name not in kwargs:
            # Required arg the browser didn't send (e.g. train_data_dir on
            # a fresh node): substitute a neutral value — paths don't
            # affect the VRAM math.
            kwargs[name] = ""
    return func(**kwargs)


def evaluate_chain(chain: list):
    """Re-derive TRAINING_PARAMS from a browser-collected node chain
    (upstream-first order). Returns the params dict, or None if the
    chain contains no param-producing node.

    Unknown node types are skipped (Reroute etc. are already filtered
    out by the JS, but be lenient). Any exception in a node entry
    function aborts cleanly with None — the live path must never take
    down the server.
    """
    # Local imports to avoid circulars at module import time (these
    # modules import config_generator, same as we do).
    try:
        from .training_wizard import AnimaTrainingWizard
        from .training_params import AnimaBasicParams, AnimaAdvancedParams, AnimaMemoryOptimizer
    except ImportError:
        from training_wizard import AnimaTrainingWizard
        from training_params import AnimaBasicParams, AnimaAdvancedParams, AnimaMemoryOptimizer

    params = None
    try:
        for entry in chain or []:
            ntype = entry.get("type", "")
            widgets = entry.get("widgets", {}) or {}
            if ntype == "AnimaTrainingWizard":
                params = _call_with_known_kwargs(AnimaTrainingWizard().configure, widgets)[0]
            elif ntype == "AnimaBasicParams":
                params = _call_with_known_kwargs(AnimaBasicParams().set_params, widgets)[0]
            elif ntype == "AnimaAdvancedParams" and params is not None:
                params = AnimaAdvancedParams().apply_overrides(params, **widgets)[0]
            elif ntype == "AnimaMemoryOptimizer" and params is not None:
                params = AnimaMemoryOptimizer().optimize_memory(params, **widgets)[0]
    except Exception as e:
        print(f"{LOG_PREFIX} live chain evaluation failed: {type(e).__name__}: {e}", flush=True)
        return None
    return params


def live_payload(chain: list, gpu_vram_gb: float) -> dict:
    """Full live-estimate pipeline for the HTTP endpoint.
    Returns {"report": str, "chart": dict|None}."""
    params = evaluate_chain(chain)
    if params is None:
        return {
            "report": ("Connect a Wizard or Basic Params node (optionally through "
                       "Advanced / Memory Optimizer) to see a live VRAM estimate."),
            "chart": None,
        }
    try:
        gpu = float(gpu_vram_gb or 0)
    except (TypeError, ValueError):
        gpu = 0.0
    report, verdict = build_report(params, gpu, live=True)
    chart = build_chart(estimate_training_vram(params), gpu, verdict)
    return {"report": report, "chart": chart}


def live_report(chain: list, gpu_vram_gb: float) -> str:
    """Text-only convenience wrapper around live_payload."""
    return live_payload(chain, gpu_vram_gb)["report"]


def _register_live_endpoint():
    """Register POST /anima_lora/estimate_vram on ComfyUI's server.
    No-op outside a running ComfyUI (pytest, standalone import)."""
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception:
        return

    @PromptServer.instance.routes.post("/anima_lora/estimate_vram")
    async def _estimate_vram(request):
        try:
            data = await request.json()
            payload = live_payload(data.get("chain", []), data.get("gpu_vram_gb", 0))
            return web.json_response(payload)
        except Exception as e:
            return web.json_response({"report": f"Estimate error: {e}", "chart": None}, status=200)


_register_live_endpoint()
