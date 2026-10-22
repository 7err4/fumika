"""
Generates TOML configuration files for sd-scripts Anima LoRA training.
"""

import os
from datetime import datetime


def coerce_seed(value, default: int = 42) -> int:
    """Coerce a seed value to int, falling back to `default` on bad input.

    Why this exists: ComfyUI does not enforce types across node links, and a
    workflow JSON can store widget values as strings. If a non-numeric string
    (e.g. "random") reaches `np.random.seed()` the trainer dies with a numpy
    dtype cast error. We'd rather log and continue with the default than crash
    deep inside the training loop.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        # Surface the bad value so the user can fix their workflow rather than
        # silently training with the default seed.
        print(
            f"[Anima LoRA Training] WARNING: seed value {value!r} "
            f"(type={type(value).__name__}) is not a valid integer. "
            f"Falling back to default seed {default}."
        )
        return default


# Known-numeric keys in the training_params dict, mapped to their target type.
# Must stay in sync with the keys generate_training_config actually reads.
# A key listed here will be coerced to its target type by
# normalize_training_params before any downstream code sees it.
_NUMERIC_PARAM_KEYS = {
    # ---- int ----
    "seed": int,
    "network_rank": int,
    "lr_warmup_steps": int,
    "max_train_epochs": int,
    "max_train_steps": int,
    "train_batch_size": int,
    "keep_tokens": int,
    "save_every_n_epochs": int,
    "qwen3_max_token_length": int,
    "t5_max_token_length": int,
    "blocks_to_swap": int,
    "vae_chunk_size": int,
    "lokr_factor": int,
    "max_data_loader_n_workers": int,
    "sample_every_n_steps": int,
    "sample_every_n_epochs": int,
    # ---- float ----
    "network_alpha": float,
    "learning_rate": float,
    "unet_lr": float,
    "text_encoder_lr": float,
    "discrete_flow_shift": float,
    "sigmoid_scale": float,
    "network_dropout": float,
    "rank_dropout": float,
    "module_dropout": float,
    "loraplus_lr_ratio": float,
    "noise_offset": float,
    "min_snr_gamma": float,
}


_NETWORK_TYPE_BY_INDEX = ("LoRA", "LoKr", "LoHa")

# Valid choices for every dropdown-typed widget that flows into the
# training config. The string defaults match the widget defaults in
# nodes/training_params.py (and the implicit defaults the wizard uses).
# Any new dropdown added to a node must be registered here too,
# otherwise normalize_training_params won't catch a SwarmUI/legacy
# index-encoded payload for that key.
_OPTIMIZER_CHOICES = (
    "AdamW8bit", "AdamW", "AdaFactor", "Prodigy",
    "Lion8bit", "Lion", "DAdaptation", "DAdaptAdam",
)
_LR_SCHEDULER_CHOICES = (
    "cosine", "cosine_with_restarts", "linear",
    "constant", "constant_with_warmup", "polynomial",
)
_ATTN_MODE_CHOICES = ("torch", "xformers", "flash", "sageattn")
_TIMESTEP_SAMPLING_CHOICES = ("sigmoid", "uniform", "sigma", "shift", "flux_shift")
_SAVE_MODEL_AS_CHOICES = ("safetensors", "ckpt")
_LOG_WITH_CHOICES = ("tensorboard", "wandb")
# bf16 is the recommended and default precision for Anima. fp16 is
# supported ONLY as a legacy-GPU path (RTX 20xx / GTX 16xx have fast
# fp16 tensor cores but no native bf16): sd-scripts 0.10.3/0.10.5 added
# conditional fp32 upcasting that fixes the historic fp16 NaN overflow
# (kohya-ss/sd-scripts#2293). On Ampere+ there is zero benefit to fp16.
_MIXED_PRECISION_CHOICES = ("bf16", "fp16")

_DROPDOWN_PARAM_CHOICES = {
    "optimizer_type":    (_OPTIMIZER_CHOICES,         "AdamW8bit"),
    "lr_scheduler":      (_LR_SCHEDULER_CHOICES,      "cosine"),
    "attn_mode":         (_ATTN_MODE_CHOICES,         "torch"),
    "timestep_sampling": (_TIMESTEP_SAMPLING_CHOICES, "sigmoid"),
    "save_model_as":     (_SAVE_MODEL_AS_CHOICES,     "safetensors"),
    "log_with":          (_LOG_WITH_CHOICES,          "tensorboard"),
    "mixed_precision":   (_MIXED_PRECISION_CHOICES,   "bf16"),
    # network_type is also a dropdown, but it has its own dedicated
    # coercer (`coerce_network_type`) wired into both
    # normalize_training_params AND generate_training_config because
    # the latter calls .lower() on it and would crash before
    # _DROPDOWN_PARAM_CHOICES gets a chance to act.
}


def coerce_dropdown(value, valid_choices, default: str) -> str:
    """Coerce a dropdown widget value to one of `valid_choices`.

    Why this exists: ComfyUI does not enforce widget types across node
    links. Some workflow JSON exporters — most notably SwarmUI, and a
    few older ComfyUI versions — serialise dropdown widget values as
    numeric indices (0/1/2/...) instead of the string label. When that
    workflow is reloaded, the dict value arrives as `int`. Calling a
    string method on it crashes; passing it through to TOML produces
    silent garbage that sd-scripts can't parse (e.g.
    `optimizer_type = 0` → "no optimizer named '0'").

    Behaviour:
      - Already a valid string label → returned untouched.
      - Custom non-empty string outside `valid_choices` → returned with
        a warning. Some users intentionally pass custom optimizer
        names (e.g. third-party optimizers) that we don't enumerate.
      - Integer index in [0, len(valid_choices)) → mapped to label.
      - bool, out-of-range int, or any other type → fall back to
        `default` with a warning.
    """
    if isinstance(value, str):
        if value in valid_choices:
            return value
        # Unknown string — could be a legitimate custom value (third-
        # party optimizer, unlisted scheduler). Pass through and let
        # sd-scripts decide whether to accept it.
        print(
            f"[Anima LoRA Training] WARNING: dropdown value {value!r} "
            f"is not in the known choices {valid_choices}. Passing "
            f"through — sd-scripts may reject it."
        )
        return value
    if isinstance(value, bool):
        # bool is a subclass of int in Python; without this branch,
        # True/False would silently map to choices[1]/choices[0].
        print(
            f"[Anima LoRA Training] WARNING: dropdown value {value!r} "
            f"is a bool, not a valid choice. Falling back to {default!r}."
        )
        return default
    if isinstance(value, int):
        if 0 <= value < len(valid_choices):
            return valid_choices[value]
        print(
            f"[Anima LoRA Training] WARNING: dropdown index {value} is "
            f"out of range (valid: 0-{len(valid_choices) - 1}). "
            f"Falling back to {default!r}."
        )
        return default
    print(
        f"[Anima LoRA Training] WARNING: dropdown value {value!r} "
        f"(type={type(value).__name__}) is not a valid choice. "
        f"Falling back to {default!r}."
    )
    return default


def coerce_network_type(value, default: str = "LoRA") -> str:
    """Coerce a network_type value to one of "LoRA"/"LoKr"/"LoHa".

    Thin wrapper around `coerce_dropdown` with the network-type
    choices pinned. Kept as a separate function because two call
    sites use it directly (`generate_training_config` itself, plus
    its own entry in `normalize_training_params`) and changing the
    signature would ripple through both.
    """
    return coerce_dropdown(value, _NETWORK_TYPE_BY_INDEX, default)


# ─── bitsandbytes runtime probe + 8-bit optimizer auto-fallback ──────
# Map every bnb-backed optimizer this pack exposes to its non-bnb
# equivalent. AdamW8bit and Lion8bit are the only ones we offer that
# require the bitsandbytes CUDA backend; the rest (AdaFactor, Prodigy,
# DAdaptation, DAdaptAdam) use pure PyTorch / their own implementations.
_BNB_OPTIMIZER_FALLBACKS = {
    "AdamW8bit": "AdamW",
    "Lion8bit":  "Lion",
}


def _probe_bitsandbytes() -> bool:
    """Uncached probe of whether bitsandbytes' 8-bit optimizer backend is
    actually usable in this Python environment. See _bitsandbytes_is_working
    for the caching wrapper.

    Why the check is needed: on Windows + ComfyUI's embedded Python,
    bitsandbytes commonly installs cleanly (the package imports) but
    silently fails to load its native CUDA library, crashing deep in the
    training loop instead of failing fast at launch.

    Version history matters here (verified against the published wheels):

      - <= 0.46.x: `functional.str2optimizer8bit_blockwise` is defined
        inside an `if lib and lib.compiled_with_cuda:` block, so its
        ABSENCE means the native library failed to load. On failure,
        `cextension.lib` is None (0.44-) or an error-handler mock (0.45+).
      - >= 0.47.0: that dict moved to `backends/cuda/ops.py`, so probing
        functional for it FALSE-NEGATIVES on perfectly healthy installs
        (reported by a user as AdamW8bit being refused on new bnb).
        The stable replacement `functional.optimizer_update_8bit_blockwise`
        exists in functional.py from 0.44 through at least 0.50.
      - 0.45+: a failed native-library load never raises at import time;
        instead `cextension.lib` is an ErrorHandlerMockBNBNativeLibrary
        that raises a helpful error on first use. We detect that mock by
        class name, which is version-stable without importing the class.

    So the probe is layered: import must succeed, the native library must
    not be None/a mock, and either the legacy dict or the modern update
    function must be present.
    """
    try:
        from bitsandbytes import functional as _bnb_functional
    except Exception:
        # ImportError or any init crash: bnb is not safely usable.
        return False

    try:
        from bitsandbytes.cextension import lib as _native_lib
        if _native_lib is None:
            return False  # 0.44-era failed DLL load
        type_name = type(_native_lib).__name__
        if "Mock" in type_name or "ErrorHandler" in type_name:
            return False  # 0.45+ failed native-library load
    except Exception:
        # Very old bnb without cextension.lib in this shape — fall through
        # to the symbol check, which is authoritative for those versions.
        pass

    return any(
        hasattr(_bnb_functional, symbol)
        for symbol in ("str2optimizer8bit_blockwise",      # <= 0.46
                       "optimizer_update_8bit_blockwise")  # 0.44+
    )


def _bitsandbytes_is_working() -> bool:
    """Cached wrapper around _probe_bitsandbytes so repeated launches in
    the same Python process don't pay the import cost."""
    if hasattr(_bitsandbytes_is_working, "_cached"):
        return _bitsandbytes_is_working._cached
    ok = _probe_bitsandbytes()
    _bitsandbytes_is_working._cached = ok
    return ok


def coerce_optimizer_for_runtime(optimizer_type: str) -> tuple:
    """If the requested optimizer is bnb-backed but bitsandbytes is
    broken, fall back to the non-8bit equivalent so training can
    proceed (at the cost of ~2× optimizer-state VRAM).

    Returns (optimizer_to_use, warning_or_none). Caller is expected to
    print/log the warning when it's not None.

    Why auto-fallback rather than hard error: AdamW8bit is the wizard's
    "balanced (recommended)" default, so a fresh user with a broken bnb
    install hits this on the modal path without doing anything wrong.
    Falling back keeps training running; the warning still lets them
    fix bnb later if VRAM is tight.
    """
    if optimizer_type not in _BNB_OPTIMIZER_FALLBACKS:
        return optimizer_type, None
    if _bitsandbytes_is_working():
        return optimizer_type, None
    fallback = _BNB_OPTIMIZER_FALLBACKS[optimizer_type]
    warning = (
        f"bitsandbytes is installed but its native CUDA library failed "
        f"to load, so 8-bit optimizers would crash mid-training. "
        f"Falling back from {optimizer_type} to {fallback} so training "
        f"can still run. Trade-off: ~2x more VRAM on the optimizer "
        f"state. To restore the 8-bit path, repair bitsandbytes — this "
        f"is usually a CUDA version mismatch with your PyTorch build. "
        f"See https://github.com/TimDettmers/bitsandbytes/releases for "
        f"a wheel matching your CUDA version."
    )
    return fallback, warning


def normalize_training_params(params: dict) -> dict:
    """Return a copy of `params` with all known-numeric values coerced to int/float.

    Why: ComfyUI does not enforce widget types across node links, so any
    `INT`/`FLOAT` widget value can arrive as a string when wired through a
    Primitive/Reroute node, an external seed/value generator, or a hand-edited
    workflow JSON. Two failure modes follow:

      1. `generate_training_config` does `if value > 0:` checks on numeric
         params — `str > int` raises `TypeError` in Python 3, so the launcher
         crashes before the TOML is even written.
      2. If a string survives all the comparisons and reaches `_dump_toml`,
         it's quoted as `key = "1234"`. sd-scripts then loads it via
         `toml.load` and stuffs the dict straight into an `argparse.Namespace`
         — bypassing argparse's `type=int`/`type=float` coercion — so the
         trainer crashes deep inside numpy/torch with a dtype cast error.

    Coercing once here, at the launcher entry, neutralises both failure modes
    without sprinkling `int(...)` / `float(...)` casts at every call site.

    Behaviour:
      - None passes through untouched (unet_lr/text_encoder_lr legitimately None).
      - Already-correct types pass through untouched.
      - Numeric strings ("1234", "1e-4") coerce cleanly.
      - seed gets a vocal warning on bad input via coerce_seed; everything else
        falls back silently to 0 / 0.0 to avoid noisy logs for benign cases.
    """
    out = dict(params)

    # seed: emit a warning so the user notices their workflow is feeding garbage.
    if "seed" in out:
        out["seed"] = coerce_seed(out["seed"])

    # network_type: same defensive coercion. Older workflow JSONs sometimes
    # serialise the dropdown as an int index instead of the string label,
    # which would crash `generate_training_config` later on `.lower()`.
    if "network_type" in out:
        out["network_type"] = coerce_network_type(out["network_type"])

    # Generic dropdown coercion. Catches the same SwarmUI/legacy index
    # serialisation for every other dropdown-typed key that flows into
    # the training config. Without this, a dropdown stored as int 0
    # would crash sd-scripts indirectly by writing `optimizer_type = 0`
    # (or similar) into the TOML — the trainer fails with an opaque
    # error like "no optimizer named '0'" deep in setup.
    for key, (choices, default) in _DROPDOWN_PARAM_CHOICES.items():
        if key in out:
            out[key] = coerce_dropdown(out[key], choices, default)

    for key, target_type in _NUMERIC_PARAM_KEYS.items():
        if key == "seed":
            continue  # already handled above with the warning variant
        if key not in out:
            continue
        value = out[key]
        if value is None:
            continue  # legitimate None (e.g. unet_lr / text_encoder_lr unset)
        try:
            out[key] = target_type(value)
        except (TypeError, ValueError):
            out[key] = 0 if target_type is int else 0.0

    return out


def _dump_toml(config: dict, f) -> None:
    """Minimal TOML serializer — no external dependency needed."""
    for key, value in config.items():
        if isinstance(value, bool):
            f.write(f"{key} = {'true' if value else 'false'}\n")
        elif isinstance(value, int):
            f.write(f"{key} = {value}\n")
        elif isinstance(value, float):
            # Avoid scientific notation for small floats (learning rates)
            if abs(value) < 1e-3 and value != 0:
                f.write(f'{key} = {value:.10f}'.rstrip('0').rstrip('.') + '\n')
            else:
                f.write(f"{key} = {value}\n")
        elif isinstance(value, str):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            f.write(f'{key} = "{escaped}"\n')
        elif isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, str):
                    escaped = item.replace('\\', '\\\\').replace('"', '\\"')
                    items.append(f'"{escaped}"')
                elif isinstance(item, bool):
                    items.append('true' if item else 'false')
                else:
                    items.append(str(item))
            f.write(f"{key} = [{', '.join(items)}]\n")
        else:
            f.write(f'{key} = "{value}"\n')


def generate_training_config(
    # Paths
    output_dir: str,
    pretrained_model: str,
    qwen3_path: str,
    vae_path: str,
    train_data_dir: str,
    # Network params
    network_type: str = "LoRA",  # "LoRA", "LoKr", or "LoHa"
    network_rank: int = 16,
    network_alpha: float = 8.0,
    # LoKr-specific
    lokr_factor: int = -1,  # Kronecker decomposition factor (-1 = auto)
    # LoKr/LoHa shared
    use_tucker: bool = False,  # Tucker decomposition for conv layers
    # Training basics
    learning_rate: float = 1e-4,
    unet_lr: float = None,
    text_encoder_lr: float = None,
    optimizer_type: str = "AdamW8bit",
    lr_scheduler: str = "cosine",
    lr_warmup_steps: int = 0,
    max_train_epochs: int = 10,
    max_train_steps: int = None,
    train_batch_size: int = 1,
    resolution: str = "1024,1024",
    # Advanced
    timestep_sampling: str = "sigmoid",
    discrete_flow_shift: float = 1.0,
    sigmoid_scale: float = 1.0,
    attn_mode: str = "torch",
    split_attn: bool = False,
    qwen3_max_token_length: int = 512,
    t5_max_token_length: int = 512,
    # Memory optimization
    cache_latents: bool = True,
    cache_latents_to_disk: bool = False,
    cache_text_encoder_outputs: bool = True,
    cache_text_encoder_outputs_to_disk: bool = False,
    blocks_to_swap: int = 0,
    vae_chunk_size: int = 64,
    gradient_checkpointing: bool = True,
    mixed_precision: str = "bf16",
    # LoRA advanced
    network_dropout: float = 0.0,
    rank_dropout: float = 0.0,
    module_dropout: float = 0.0,
    train_llm_adapter: bool = False,
    loraplus_lr_ratio: float = 0.0,
    noise_offset: float = 0.0,
    min_snr_gamma: float = 0.0,
    # Network regex patterns
    include_patterns: str = "",
    exclude_patterns: str = "",
    network_reg_dims: str = "",
    network_reg_lrs: str = "",
    # Optional paths
    llm_adapter_path: str = "",
    t5_tokenizer_path: str = "",
    # Resume
    resume: str = "",
    save_state: bool = True,
    # Sampling
    sample_every_n_steps: int = 0,
    sample_every_n_epochs: int = 0,
    sample_prompts: str = "",
    sample_sampler: str = "euler",
    # Dataset
    caption_extension: str = ".txt",
    shuffle_caption: bool = True,
    keep_tokens: int = 0,
    # Saving
    save_every_n_epochs: int = 1,
    save_model_as: str = "safetensors",
    output_name: str = "",
    # Logging
    logging_dir: str = "",
    log_with: str = "tensorboard",
    # Seed
    seed: int = 42,
    # Misc
    max_data_loader_n_workers: int = 2,
    persistent_data_loader_workers: bool = True,
) -> dict:
    """Generate a complete training configuration dictionary."""

    if not output_name:
        output_name = f"anima_lora_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if not logging_dir:
        logging_dir = os.path.join(output_dir, "logs")

    config = {}

    # --- Model section ---
    config["pretrained_model_name_or_path"] = pretrained_model
    config["qwen3"] = qwen3_path
    config["vae"] = vae_path

    if llm_adapter_path:
        config["llm_adapter_path"] = llm_adapter_path
    if t5_tokenizer_path:
        config["t5_tokenizer_path"] = t5_tokenizer_path

    # --- Network section ---
    # Select network module based on type (all built into sd-scripts).
    # Defensive coerce: a direct caller (or a path that bypasses
    # normalize_training_params) might still hand us an int dropdown
    # index from a re-loaded workflow JSON. coerce_network_type is a
    # no-op on already-coerced strings, so this doesn't double-warn.
    network_type = coerce_network_type(network_type)
    network_type_lower = network_type.lower().strip()
    if network_type_lower == "lokr":
        config["network_module"] = "networks.lokr"
    elif network_type_lower == "loha":
        config["network_module"] = "networks.loha"
    else:
        # LoRA — Anima requires the dedicated lora_anima module, NOT generic lora
        config["network_module"] = "networks.lora_anima"

    config["network_dim"] = network_rank
    config["network_alpha"] = network_alpha

    # Build network_args
    network_args = []

    # LoKr-specific args
    if network_type_lower == "lokr":
        if lokr_factor != -1:
            network_args.append(f"factor={lokr_factor}")
        if use_tucker:
            network_args.append("use_tucker=True")
    # LoHa-specific args
    elif network_type_lower == "loha":
        if use_tucker:
            network_args.append("use_tucker=True")

    if train_llm_adapter:
        network_args.append("train_llm_adapter=True")
    if rank_dropout > 0:
        network_args.append(f"rank_dropout={rank_dropout}")
    if module_dropout > 0:
        network_args.append(f"module_dropout={module_dropout}")
    if loraplus_lr_ratio > 0:
        network_args.append(f"loraplus_lr_ratio={loraplus_lr_ratio}")
    if include_patterns:
        network_args.append(f"include_patterns={include_patterns}")
    if exclude_patterns:
        network_args.append(f"exclude_patterns={exclude_patterns}")
    if network_reg_dims:
        network_args.append(f"network_reg_dims={network_reg_dims}")
    if network_reg_lrs:
        network_args.append(f"network_reg_lrs={network_reg_lrs}")
    network_args.append("verbose=True")

    if network_args:
        config["network_args"] = network_args

    if network_dropout > 0:
        config["network_dropout"] = network_dropout

    # --- Training section ---
    config["learning_rate"] = learning_rate
    if unet_lr is not None and unet_lr > 0:
        config["unet_lr"] = unet_lr
    if text_encoder_lr is not None and text_encoder_lr > 0:
        config["text_encoder_lr"] = text_encoder_lr

    # If user picked an 8-bit optimizer (AdamW8bit / Lion8bit) but
    # bitsandbytes can't actually run in this Python environment, swap
    # to the non-8bit equivalent. This catches the common Windows-
    # embedded-Python case where bnb is installed but its CUDA DLLs
    # didn't load — would otherwise crash ~30s into training with a
    # cryptic `NameError: str2optimizer8bit_blockwise` deep in
    # accelerate/optimizer.py.
    optimizer_type, _opt_warning = coerce_optimizer_for_runtime(optimizer_type)
    if _opt_warning:
        print(f"[Anima LoRA Training] WARNING: {_opt_warning}")
    config["optimizer_type"] = optimizer_type
    config["lr_scheduler"] = lr_scheduler
    if lr_warmup_steps > 0:
        config["lr_warmup_steps"] = lr_warmup_steps

    if max_train_steps and max_train_steps > 0:
        config["max_train_steps"] = max_train_steps
    else:
        config["max_train_epochs"] = max_train_epochs

    config["train_batch_size"] = train_batch_size
    config["resolution"] = resolution
    # Force int — if a string slips in here, _dump_toml will quote it and
    # sd-scripts' toml.load will hand numpy a `str`, which crashes
    # `np.random.seed()` with a dtype('<U4') -> int64 cast error.
    # Non-numeric input falls back to the default seed rather than raising.
    config["seed"] = coerce_seed(seed)

    # --- Aspect-ratio bucketing ---
    # Without this, sd-scripts forces every image to exactly the
    # `resolution` value (e.g. 1024×1024) and CENTER-CROPS anything
    # non-square — portraits lose heads/feet, landscapes lose sides.
    # Bucketing sorts images into aspect-ratio-matched buckets
    # (832×1216, 1216×832, 1024×1024, …) so nothing meaningful gets
    # cropped. `bucket_no_upscale = True` keeps images at native size
    # rather than upscaling them to fill a larger bucket — important
    # when the user pre-normalised their dataset to longest_edge=1024.
    # `bucket_reso_steps = 64` is a multiple of Anima's VAE constraint
    # (Qwen-Image VAE has 8× spatial downscale; latents need to be a
    # multiple of the DiT patch size, so image dims need a multiple of
    # at least 16 — 64 satisfies that with margin and matches the SDXL
    # community default).
    config["enable_bucket"] = True
    config["min_bucket_reso"] = 256
    config["max_bucket_reso"] = 2048
    config["bucket_reso_steps"] = 64
    config["bucket_no_upscale"] = True

    # --- Anima-specific ---
    config["timestep_sampling"] = timestep_sampling
    config["discrete_flow_shift"] = discrete_flow_shift
    config["sigmoid_scale"] = sigmoid_scale
    config["attn_mode"] = attn_mode
    if split_attn:
        config["split_attn"] = True
    config["qwen3_max_token_length"] = qwen3_max_token_length
    config["t5_max_token_length"] = t5_max_token_length

    # --- Memory optimization ---
    if cache_latents:
        config["cache_latents"] = True
    if cache_latents_to_disk:
        config["cache_latents_to_disk"] = True
    if cache_text_encoder_outputs or cache_text_encoder_outputs_to_disk:
        config["cache_text_encoder_outputs"] = True
        # Can't train text encoder when its outputs are cached
        config["network_train_unet_only"] = True
    if cache_text_encoder_outputs_to_disk:
        config["cache_text_encoder_outputs_to_disk"] = True
    if blocks_to_swap > 0:
        # blocks_to_swap is incompatible with cpu/unsloth offload checkpointing
        config["blocks_to_swap"] = blocks_to_swap
    if vae_chunk_size > 0:
        config["vae_chunk_size"] = vae_chunk_size
    # Recommended by official docs to reduce VRAM for Qwen-Image VAE
    config["vae_disable_cache"] = True
    if gradient_checkpointing:
        config["gradient_checkpointing"] = True

    # bf16 unless the user explicitly opted into the legacy fp16 path
    # (pre-Ampere GPUs). Anything else falls back to bf16 — fp16 on Anima
    # is only safe with sd-scripts >= 0.10.5 (conditional fp32 upcasting),
    # which the SD-Scripts Manager installs by default.
    config["mixed_precision"] = "fp16" if mixed_precision == "fp16" else "bf16"

    # --- Noise / loss ---
    if noise_offset > 0:
        config["noise_offset"] = noise_offset
    if min_snr_gamma > 0:
        config["min_snr_gamma"] = min_snr_gamma

    # --- Dataset ---
    config["train_data_dir"] = train_data_dir
    config["caption_extension"] = caption_extension
    # shuffle_caption is incompatible with cache_text_encoder_outputs
    if shuffle_caption and not cache_text_encoder_outputs:
        config["shuffle_caption"] = True
    if keep_tokens > 0:
        config["keep_tokens"] = keep_tokens

    # --- Saving ---
    config["output_dir"] = output_dir
    config["output_name"] = output_name
    config["save_every_n_epochs"] = save_every_n_epochs
    config["save_model_as"] = save_model_as
    # Always save training state so we can resume later
    if save_state:
        config["save_state"] = True

    # --- Resume ---
    if resume:
        config["resume"] = resume

    # --- Sampling ---
    if sample_prompts:
        config["sample_prompts"] = sample_prompts
        config["sample_sampler"] = sample_sampler
        # Always generate a baseline sample at step 0 for reference
        config["sample_at_first"] = True
        if sample_every_n_steps > 0:
            config["sample_every_n_steps"] = sample_every_n_steps
        if sample_every_n_epochs > 0:
            config["sample_every_n_epochs"] = sample_every_n_epochs

    # --- Logging ---
    config["logging_dir"] = logging_dir
    config["log_with"] = log_with

    # --- Data loader ---
    config["max_data_loader_n_workers"] = max_data_loader_n_workers
    if persistent_data_loader_workers:
        config["persistent_data_loader_workers"] = True

    return config


def write_toml_config(config: dict, output_path: str) -> str:
    """Write the config dictionary to a TOML file and return the path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        _dump_toml(config, f)
    return output_path


def config_to_cli_args(config: dict) -> list:
    """Convert a config dictionary to a list of CLI arguments for sd-scripts."""
    args = []
    for key, value in config.items():
        flag = f"--{key}"
        if isinstance(value, bool):
            if value:
                args.append(flag)
        elif isinstance(value, list):
            args.append(flag)
            for item in value:
                args.append(str(item))
        else:
            args.append(flag)
            args.append(str(value))
    return args
