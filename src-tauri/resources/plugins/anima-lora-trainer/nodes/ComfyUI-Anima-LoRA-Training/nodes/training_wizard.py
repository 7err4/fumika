"""
ComfyUI Node: Anima LoRA Training Wizard
A questionnaire-driven node that auto-configures training parameters
based on user answers about their LoRA goal and dataset.
"""

import os
import math
import sys
from pathlib import Path

try:
    from ..utils.config_generator import coerce_seed, coerce_network_type
    from ..utils.dataset_check import check_dataset, format_dataset_report
except ImportError:
    # Fallback for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.config_generator import coerce_seed, coerce_network_type
    from utils.dataset_check import check_dataset, format_dataset_report


# ---------------------------------------------------------------------------
# Preset tables: each questionnaire answer contributes to the final config.
# The wizard combines these into a best-practice starting point.
# ---------------------------------------------------------------------------

# What kind of LoRA are you training?
SUBJECT_PRESETS = {
    "character / person": {
        "network_rank": 32,
        "network_alpha": 16.0,
        "learning_rate": 8e-5,
        "keep_tokens": 1,
        "shuffle_caption": True,
        "noise_offset": 0.05,
        "tip": "Character LoRAs benefit from consistent trigger words and varied poses.",
    },
    "art style": {
        "network_rank": 16,
        "network_alpha": 8.0,
        "learning_rate": 1e-4,
        "keep_tokens": 0,
        "shuffle_caption": True,
        "noise_offset": 0.0,
        "tip": "Style LoRAs work best with diverse subjects sharing the same style.",
    },
    "concept / object": {
        "network_rank": 16,
        "network_alpha": 8.0,
        "learning_rate": 1e-4,
        "keep_tokens": 1,
        "shuffle_caption": True,
        "noise_offset": 0.03,
        "tip": "Use a specific trigger word and show the concept in varied contexts.",
    },
    "clothing / accessory": {
        "network_rank": 24,
        "network_alpha": 12.0,
        "learning_rate": 8e-5,
        "keep_tokens": 1,
        "shuffle_caption": True,
        "noise_offset": 0.03,
        "tip": "Show the item on multiple body types and in different scenes.",
    },
    "pose / composition": {
        "network_rank": 12,
        "network_alpha": 6.0,
        "learning_rate": 1e-4,
        "keep_tokens": 0,
        "shuffle_caption": True,
        "noise_offset": 0.0,
        "tip": "Include varied subjects with the same pose/composition.",
    },
}

# How many training images do you have?
DATASET_SIZE_PRESETS = {
    "tiny (1-10 images)": {
        "max_train_epochs": 30,
        "train_batch_size": 1,
        "lr_scheduler": "cosine",
        "lr_warmup_ratio": 0.1,
        "save_every_n_epochs": 5,
        "tip": "Very small datasets risk overfitting. Consider augmentation or adding more images.",
    },
    "small (10-30 images)": {
        "max_train_epochs": 20,
        "train_batch_size": 1,
        "lr_scheduler": "cosine",
        "lr_warmup_ratio": 0.05,
        "save_every_n_epochs": 4,
        "tip": "Good starting range for character/concept LoRAs.",
    },
    "medium (30-100 images)": {
        "max_train_epochs": 12,
        "train_batch_size": 2,
        "lr_scheduler": "cosine",
        "lr_warmup_ratio": 0.05,
        "save_every_n_epochs": 2,
        "tip": "Solid dataset size. Should produce reliable results.",
    },
    "large (100-500 images)": {
        "max_train_epochs": 8,
        "train_batch_size": 2,
        "lr_scheduler": "cosine_with_restarts",
        "lr_warmup_ratio": 0.03,
        "save_every_n_epochs": 1,
        "tip": "Great for style LoRAs. Reduce epochs if you notice overfitting.",
    },
    "very large (500+ images)": {
        "max_train_epochs": 5,
        "train_batch_size": 4,
        "lr_scheduler": "cosine_with_restarts",
        "lr_warmup_ratio": 0.02,
        "save_every_n_epochs": 1,
        "tip": "Large dataset. You may want to use max_train_steps instead of epochs.",
    },
}

# What image resolution is your dataset?
# Anima officially supports 512^2 up to 1536^2.
RESOLUTION_PRESETS = {
    "1536x1536 (high VRAM)": {
        "resolution": "1536,1536",
        "tip": "1536 is Anima's maximum. Uses more than twice the memory of "
               "1024 - realistically needs a 16 GB+ card, and your training "
               "images should really be this large to benefit.",
    },
    "1024x1024 (recommended)": {
        "resolution": "1024,1024",
    },
    "768x768": {
        "resolution": "768,768",
    },
    "512x512": {
        "resolution": "512,512",
    },
    "mixed / bucket resolution": {
        "resolution": "1024,1024",
        "tip": "sd-scripts will use aspect ratio bucketing automatically.",
    },
}

# How much VRAM do you have?
#
# `recommended_max_resolution` is the largest square training resolution
# this tier is expected to handle without OOM. It is NOT enforced — the
# wizard only prints a prominent warning when the user's resolution
# choice exceeds it (warn-only policy, the user stays in control).
VRAM_PRESETS = {
    "6 GB (minimum)": {
        "mixed_precision": "bf16",
        "gradient_checkpointing": True,
        "cache_latents": True,
        "cache_text_encoder_outputs": True,
        "cache_latents_to_disk": True,
        "cache_text_encoder_outputs_to_disk": True,
        "blocks_to_swap": 24,
        "vae_chunk_size": 16,
        "attn_mode": "xformers",
        "split_attn": True,
        "train_batch_size_override": 1,
        "recommended_max_resolution": 768,
        "tip": "The bare minimum (~5 GB used). Most of the model sits in normal "
               "RAM, so training is MUCH slower - but the result is just as "
               "good. Keep images at 768x768 or smaller; 1024 will very "
               "likely fail with an out-of-memory error on 6 GB.",
    },
    "8 GB (low)": {
        "mixed_precision": "bf16",
        "gradient_checkpointing": True,
        "cache_latents": True,
        "cache_text_encoder_outputs": True,
        "cache_latents_to_disk": True,
        "cache_text_encoder_outputs_to_disk": True,
        "blocks_to_swap": 20,
        "vae_chunk_size": 32,
        "attn_mode": "xformers",
        "split_attn": True,
        "train_batch_size_override": 1,
        "recommended_max_resolution": 1024,
        "tip": "Tight fit. Parts of the model are parked in normal RAM - training "
               "is slower, but reliable at 1024px. Quality is not affected.",
    },
    "10 GB": {
        "mixed_precision": "bf16",
        "gradient_checkpointing": True,
        "cache_latents": True,
        "cache_text_encoder_outputs": True,
        "cache_latents_to_disk": False,
        "cache_text_encoder_outputs_to_disk": False,
        "blocks_to_swap": 14,
        "vae_chunk_size": 32,
        "attn_mode": "xformers",
        "split_attn": True,
        "train_batch_size_override": 1,
        "recommended_max_resolution": 1024,
        "tip": "Some of the model is parked in normal RAM - a bit slower. "
               "1024x1024 works fine, one image per step.",
    },
    "12 GB": {
        "mixed_precision": "bf16",
        "gradient_checkpointing": True,
        "cache_latents": True,
        "cache_text_encoder_outputs": True,
        "cache_latents_to_disk": False,
        "cache_text_encoder_outputs_to_disk": False,
        "blocks_to_swap": 10,
        "vae_chunk_size": 64,
        "attn_mode": "torch",
        "split_attn": False,
        "recommended_max_resolution": 1024,
        "tip": "Near full speed. A small part of the model is parked in normal "
               "RAM as a safety margin.",
    },
    "16 GB": {
        "mixed_precision": "bf16",
        "gradient_checkpointing": True,
        "cache_latents": True,
        "cache_text_encoder_outputs": True,
        "cache_latents_to_disk": False,
        "cache_text_encoder_outputs_to_disk": False,
        "blocks_to_swap": 0,
        "vae_chunk_size": 64,
        "attn_mode": "torch",
        "split_attn": False,
        "recommended_max_resolution": 1536,
        "tip": "Comfortable. The whole model stays on the GPU - full speed.",
    },
    "24 GB+ (high)": {
        "mixed_precision": "bf16",
        "gradient_checkpointing": False,
        "cache_latents": True,
        "cache_text_encoder_outputs": True,
        "cache_latents_to_disk": False,
        "cache_text_encoder_outputs_to_disk": False,
        "blocks_to_swap": 0,
        "vae_chunk_size": 64,
        "attn_mode": "torch",
        "split_attn": False,
        "recommended_max_resolution": 1536,
        "tip": "Plenty. Fastest settings enabled.",
    },
}


def _speed_label(blocks_to_swap: int) -> str:
    """Plain-language training-speed description for a preset.
    The speed cost comes almost entirely from how much of the model is
    parked in normal RAM (block swap)."""
    if blocks_to_swap == 0:
        return "full speed"
    if blocks_to_swap <= 10:
        return "near full speed"
    if blocks_to_swap <= 14:
        return "a bit slower"
    if blocks_to_swap <= 20:
        return "slower"
    return "much slower"


def _vram_preset_tooltip() -> str:
    """Generated from VRAM_PRESETS so the dropdown tooltip always shows
    what each tier actually means — written for users with no training
    background: speed, max image size, and 'nothing is locked'."""
    lines = [
        "How much memory (VRAM) does your graphics card have?",
        "(Not sure? Windows: Task Manager > Performance > GPU > 'Dedicated GPU memory')",
        "",
        "This picks safe STARTING settings for your card - nothing is locked.",
        "You can change everything afterwards (force_* fields below, or a",
        "Memory Optimizer node). What each choice means for you:",
    ]
    for name, p in VRAM_PRESETS.items():
        parts = [
            f"trains {_speed_label(p['blocks_to_swap'])}",
            f"images up to {p['recommended_max_resolution']}px",
        ]
        if p.get("train_batch_size_override"):
            parts.append("one image per step")
        lines.append(f"- {name}: " + ", ".join(parts))
    lines.append("")
    lines.append("Smaller cards are slower because parts of the model are parked in")
    lines.append("normal RAM and fetched only when needed. Quality is NOT affected -")
    lines.append("only speed and the recommended image size.")
    lines.append("")
    lines.append("'images up to Xpx' is a RECOMMENDATION, not a cap: your")
    lines.append("image_resolution choice is never changed by this preset. If it is")
    lines.append("too big for the card, you only get a warning.")
    return "\n".join(lines)


def parse_resolution_max_dim(resolution: str) -> int:
    """Return the largest dimension from a resolution string.
    Accepts "1024,1024", "832,1216", or a single value "768".
    Returns 0 if the string can't be parsed (never raises — this feeds
    a warn-only path and must not break the wizard)."""
    try:
        parts = [int(p.strip()) for p in str(resolution).split(",") if p.strip()]
        return max(parts) if parts else 0
    except (ValueError, TypeError):
        return 0

# What quality vs. speed trade-off do you want?
QUALITY_PRESETS = {
    "quick test (fast, lower quality)": {
        "epoch_multiplier": 0.5,
        "rank_modifier": -8,
        "optimizer_type": "AdamW8bit",
        "timestep_sampling": "sigmoid",
        "tip": "Fast iteration. Use this to verify your dataset and captions.",
    },
    "balanced (recommended)": {
        "epoch_multiplier": 1.0,
        "rank_modifier": 0,
        "optimizer_type": "AdamW8bit",
        "timestep_sampling": "sigmoid",
        "tip": "Good balance of quality and training time.",
    },
    "high quality (slower)": {
        "epoch_multiplier": 1.5,
        "rank_modifier": 8,
        "optimizer_type": "AdamW",
        "timestep_sampling": "sigmoid",
        "tip": "More epochs and higher rank for best results. Takes longer.",
    },
    "experimental (adaptive optimizer)": {
        "epoch_multiplier": 1.0,
        "rank_modifier": 0,
        "optimizer_type": "Prodigy",
        "timestep_sampling": "sigmoid",
        "learning_rate_override": 1.0,
        "tip": "Prodigy auto-tunes the learning rate. Set LR to 1.0.",
    },
}


class AnimaTrainingWizard:
    """
    Answer a few questions about your LoRA project and dataset.
    The wizard automatically configures optimal training parameters.

    Connect directly to the Training Launcher for the simplest workflow,
    or chain through Advanced / Memory nodes to tweak individual settings.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "train_data_dir": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Path to your training images folder (with .txt caption files)."
                }),
                "output_dir": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Where to save the trained LoRA file."
                }),
                "output_name": ("STRING", {
                    "default": "my_anima_lora",
                    "multiline": False,
                    "tooltip": "Name for your output LoRA file."
                }),

                # --- The Questionnaire ---
                "what_are_you_training": (list(SUBJECT_PRESETS.keys()), {
                    "default": "character / person",
                    "tooltip": "What kind of subject is this LoRA for?"
                }),
                "dataset_size": (list(DATASET_SIZE_PRESETS.keys()), {
                    "default": "small (10-30 images)",
                    "tooltip": "Roughly how many training images do you have?"
                }),
                "image_resolution": (list(RESOLUTION_PRESETS.keys()), {
                    "default": "1024x1024 (recommended)",
                    "tooltip": "What resolution should training run at?\n"
                               "YOUR CHOICE IS ALWAYS USED EXACTLY AS-IS - the "
                               "gpu_vram preset never changes or caps it.\n"
                               "If it's more than your card can handle you get a "
                               "clear warning (training still starts, but may "
                               "stop with an out-of-memory error)."
                }),
                "gpu_vram": (list(VRAM_PRESETS.keys()), {
                    "default": "12 GB",
                    "tooltip": _vram_preset_tooltip()
                }),
                "quality_goal": (list(QUALITY_PRESETS.keys()), {
                    "default": "balanced (recommended)",
                    "tooltip": "Quick test vs. high-quality result?"
                }),
                "network_type": (["LoRA", "LoKr", "LoHa"], {
                    "default": "LoRA",
                    "tooltip": "Network architecture. LoRA: standard. LoKr: Kronecker product (compact). LoHa: Hadamard product (good for styles)."
                }),
            },
            "optional": {
                "training_seed": ("INT", {
                    "default": 42, "min": 0, "max": 2147483647, "step": 1,
                    "tooltip": "Random seed for reproducibility."
                }),
                "caption_extension": ("STRING", {
                    "default": ".txt",
                    "tooltip": "File extension for caption files."
                }),
                # Schedule overrides — 0 = use the dataset/quality preset's
                # auto-computed value, anything > 0 short-circuits the
                # preset. The `force_*` naming + 0-sentinel matches the
                # convention used by the new ComfyUI_LoRATrainerLauncher
                # pack for INT overrides (force_network_rank,
                # force_batch_size, ...).
                "force_save_every_n_epochs": ("INT", {
                    "default": 0, "min": 0, "max": 100, "step": 1,
                    "tooltip": "Save a checkpoint every N epochs. 0 = use "
                               "dataset_size preset (5 / 4 / 2 / 1 / 1 for "
                               "tiny / small / medium / large / very large)."
                }),
                "force_max_train_epochs": ("INT", {
                    "default": 0, "min": 0, "max": 1000, "step": 1,
                    "tooltip": "Total training epochs. 0 = derived from "
                               "dataset_size × quality_goal preset. "
                               "Ignored when force_max_train_steps > 0."
                }),
                "force_max_train_steps": ("INT", {
                    "default": 0, "min": 0, "max": 1000000, "step": 100,
                    "tooltip": "Stop after N steps instead of epochs. 0 = "
                               "epoch-based (use max_train_epochs). When "
                               "set, takes precedence over epochs."
                }),
                "force_resolution": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Training resolution override (W,H or single "
                               "value, e.g. '768,768'). Empty = use the "
                               "image_resolution preset. Overriding above "
                               "your VRAM tier's recommendation may OOM."
                }),
                "force_network_rank": ("INT", {
                    "default": 0, "min": 0, "max": 256, "step": 1,
                    "tooltip": "Network rank override. 0 = use subject/"
                               "quality preset (incl. the Lycoris halving). "
                               "Alpha is re-derived as rank/2."
                }),
                "force_learning_rate": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 1e-6,
                    "tooltip": "Learning rate override. 0 = use subject/"
                               "quality preset. Remember: Prodigy wants 1.0."
                }),
                "force_batch_size": ("INT", {
                    "default": 0, "min": 0, "max": 16, "step": 1,
                    "tooltip": "Batch size override. 0 = use dataset preset "
                               "(capped by the VRAM tier). Higher batch "
                               "sizes need significantly more VRAM."
                }),
                "force_blocks_to_swap": ("INT", {
                    "default": -1, "min": -1, "max": 34, "step": 1,
                    "tooltip": "Block swap override. -1 = use VRAM preset. "
                               "0 = explicitly disable swapping. Higher = "
                               "less VRAM but slower steps."
                }),
                "old_gpu_fp16": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "ONLY for GPUs without native bf16: RTX 20xx and "
                               "GTX 16xx. Those cards train much faster in fp16.\n"
                               "On RTX 30xx or newer, leave this OFF - fp16 has "
                               "zero benefit there and only adds risk.\n"
                               "Heads up: fp16 mode needs MORE VRAM than bf16 "
                               "(the stability fix computes parts in fp32) - "
                               "check the VRAM Estimator, and consider a smaller "
                               "resolution or more block swap.\n"
                               "Needs a current sd-scripts (the SD-Scripts Manager "
                               "installs it). If your loss ever becomes NaN, turn "
                               "this off again."
                }),
            }
        }

    RETURN_TYPES = ("TRAINING_PARAMS", "STRING")
    RETURN_NAMES = ("training_params", "wizard_summary")
    FUNCTION = "configure"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = False

    def configure(self, train_data_dir: str, output_dir: str, output_name: str,
                  what_are_you_training: str, dataset_size: str,
                  image_resolution: str, gpu_vram: str, quality_goal: str,
                  network_type: str = "LoRA",
                  training_seed: int = 42, caption_extension: str = ".txt",
                  force_save_every_n_epochs: int = 0,
                  force_max_train_epochs: int = 0,
                  force_max_train_steps: int = 0,
                  force_resolution: str = "",
                  force_network_rank: int = 0,
                  force_learning_rate: float = 0.0,
                  force_batch_size: int = 0,
                  force_blocks_to_swap: int = -1,
                  old_gpu_fp16: bool = False) -> tuple:

        # Coerce network_type up-front. ComfyUI's native widget delivers
        # the chosen label as a string ("LoRA"/"LoKr"/"LoHa"), but SwarmUI
        # and some workflow JSON exporters serialise the dropdown as a
        # numeric index (0/1/2) — calling `.lower()` on an int below would
        # crash with `AttributeError: 'int' object has no attribute 'lower'`
        # before the launcher's normalize_training_params gets a chance to
        # see it. Same defensive coerce that the launcher does, just applied
        # earlier in the chain.
        network_type = coerce_network_type(network_type)

        subject = SUBJECT_PRESETS[what_are_you_training]
        dataset = DATASET_SIZE_PRESETS[dataset_size]
        resolution = RESOLUTION_PRESETS[image_resolution]
        vram = VRAM_PRESETS[gpu_vram]
        quality = QUALITY_PRESETS[quality_goal]

        # --- Combine presets ---
        # Rank: subject base + quality modifier, clamped. We keep the
        # pre-Lycoris-adjustment value around so the wizard summary can
        # show "20 (halved from 40 for LoKr)" instead of just "20".
        rank_lora = max(4, subject["network_rank"] + quality.get("rank_modifier", 0))

        # Lycoris (LoKr / LoHa) needs a much lower rank than plain LoRA.
        # The decomposition only delivers actual parameter reduction when
        # `rank` is well below sqrt(dim) for the layer dimensions involved
        # (typically 1024-3072 in Anima's DiT). With LoRA-sized ranks
        # (32-40), sd-scripts logs "lora_dim X is large for dim=N,
        # using full matrix mode" on essentially every layer and falls
        # back to training the FULL weight matrix — effectively a
        # partial fine-tune, with massively more parameters, ~5-10x
        # slower steps, and proportionally larger output files.
        # Halving brings character-class ranks (32+8=40) down to 20,
        # which keeps real Kronecker decomposition active across all
        # Anima DiT layer sizes.
        is_lycoris = network_type.lower() in ("lokr", "loha")
        rank = max(4, rank_lora // 2) if is_lycoris else rank_lora

        # Explicit rank override beats the preset AND the Lycoris halving —
        # the user typed an exact number, so we honour it exactly.
        rank_overridden = force_network_rank > 0
        if rank_overridden:
            rank = force_network_rank

        alpha = rank / 2.0

        # Learning rate: explicit override > quality override (Prodigy) > subject preset
        lr_overridden = force_learning_rate > 0
        if lr_overridden:
            lr = force_learning_rate
        else:
            lr = quality.get("learning_rate_override", subject["learning_rate"])

        # Epochs: dataset base * quality multiplier, with explicit override.
        # 0 sentinel = "use the preset"; any positive value short-circuits.
        if force_max_train_epochs > 0:
            epochs = force_max_train_epochs
        else:
            epochs = max(1, round(dataset["max_train_epochs"] * quality.get("epoch_multiplier", 1.0)))

        # Step-based training takes precedence over epoch-based when set.
        # The launcher / config_generator already handles the "if
        # max_train_steps > 0 use it else use max_train_epochs" branching;
        # we just pass the override through.
        max_train_steps = max(0, force_max_train_steps)

        # Save-every-N-epochs: explicit override > dataset_size preset.
        save_every_n_epochs = (
            force_save_every_n_epochs
            if force_save_every_n_epochs > 0
            else dataset["save_every_n_epochs"]
        )

        # Batch size: explicit override > VRAM cap > dataset suggestion
        batch_overridden = force_batch_size > 0
        if batch_overridden:
            batch = force_batch_size
        else:
            batch = dataset["train_batch_size"]
            if "train_batch_size_override" in vram:
                batch = min(batch, vram["train_batch_size_override"])

        # Block swap: explicit override (-1 sentinel, since 0 = "disable
        # swapping" is a meaningful user choice) > VRAM preset.
        swap_overridden = force_blocks_to_swap >= 0
        blocks_to_swap = force_blocks_to_swap if swap_overridden else vram["blocks_to_swap"]

        # Resolution: explicit override > image_resolution preset.
        res_overridden = bool(force_resolution.strip()) and parse_resolution_max_dim(force_resolution) > 0
        final_resolution = force_resolution.strip() if res_overridden else resolution["resolution"]

        # --- Warn-only VRAM sanity check ---
        # The chosen resolution is NEVER changed by the VRAM tier; we only
        # warn loudly when it exceeds what the tier is expected to handle.
        vram_warning = None
        res_max_dim = parse_resolution_max_dim(final_resolution)
        rec_max = vram.get("recommended_max_resolution", 0)
        if rec_max and res_max_dim > rec_max:
            vram_warning = (
                f"Your resolution ({final_resolution}) is bigger than the "
                f"'{gpu_vram}' preset's recommended maximum of {rec_max}x{rec_max}. "
                f"The wizard has NOT changed it - your choice always wins - "
                f"but training will likely stop with an OUT OF MEMORY error. "
                f"To fix: pick {rec_max}x{rec_max} or lower under image_resolution, "
                f"or check the VRAM Estimator node first."
            )
        if batch_overridden and batch > 1 and vram.get("train_batch_size_override") == 1:
            extra = (
                f"Batch size {batch} overrides the '{gpu_vram}' tier's cap of 1. "
                f"Each extra batch item adds several GB of activation memory."
            )
            vram_warning = f"{vram_warning}\n  Also: {extra}" if vram_warning else extra

        # Warmup steps: estimated from epochs and dataset
        lr_warmup_steps = max(0, round(epochs * dataset.get("lr_warmup_ratio", 0.05) * 100))

        # Build the full params dict
        params = {
            "train_data_dir": train_data_dir.strip(),
            "output_dir": output_dir.strip(),
            "output_name": output_name.strip(),
            "resolution": final_resolution,

            # Network architecture
            "network_type": network_type,
            "network_rank": rank,
            "network_alpha": alpha,

            # Learning rate
            "learning_rate": lr,
            "optimizer_type": quality["optimizer_type"],
            "lr_scheduler": dataset["lr_scheduler"],
            "lr_warmup_steps": lr_warmup_steps,

            # Training. epochs / max_train_steps come from the locals
            # computed above, which already honour the force_* overrides
            # (max_train_steps = 0 means epoch-based; > 0 short-circuits).
            "max_train_epochs": epochs,
            "max_train_steps": max_train_steps,
            "train_batch_size": batch,

            # Anima-specific
            "timestep_sampling": quality["timestep_sampling"],
            "discrete_flow_shift": 1.0,
            "sigmoid_scale": 1.0,
            "attn_mode": vram["attn_mode"],
            "split_attn": vram["split_attn"],
            "qwen3_max_token_length": 512,
            "t5_max_token_length": 512,

            # Memory. fp16 is the legacy path for GPUs without native
            # bf16 (RTX 20xx / GTX 16xx) - explicit opt-in only.
            "mixed_precision": "fp16" if old_gpu_fp16 else vram["mixed_precision"],
            "gradient_checkpointing": vram["gradient_checkpointing"],
            "cache_latents": vram["cache_latents"],
            "cache_latents_to_disk": vram["cache_latents_to_disk"],
            "cache_text_encoder_outputs": vram["cache_text_encoder_outputs"],
            "cache_text_encoder_outputs_to_disk": vram["cache_text_encoder_outputs_to_disk"],
            "blocks_to_swap": blocks_to_swap,
            "vae_chunk_size": vram["vae_chunk_size"],

            # LoRA training options
            "network_dropout": 0.0,
            "rank_dropout": 0.0,
            "module_dropout": 0.0,
            "train_llm_adapter": False,
            "loraplus_lr_ratio": 0.0,
            "noise_offset": subject.get("noise_offset", 0.0),
            "min_snr_gamma": 0.0,

            # Regex patterns (empty = defaults)
            "include_patterns": "",
            "exclude_patterns": "",
            "network_reg_dims": "",
            "network_reg_lrs": "",

            # LoKr/LoHa defaults (override via Advanced Params)
            "lokr_factor": -1,
            "use_tucker": False,

            # Dataset
            "caption_extension": caption_extension,
            "shuffle_caption": subject.get("shuffle_caption", True),
            "keep_tokens": subject.get("keep_tokens", 0),

            # Saving — preset value or force_save_every_n_epochs override.
            "save_every_n_epochs": save_every_n_epochs,
            "save_model_as": "safetensors",

            # Logging
            "log_with": "tensorboard",

            # Other
            # Defensive cast: see training_params.py for the rationale.
            "seed": coerce_seed(training_seed),
            "max_data_loader_n_workers": 2,

            # Metadata (for summary, not passed to sd-scripts)
            "_wizard_mode": True,
        }

        # --- Build human-readable summary ---
        tips = [p.get("tip", "") for p in [subject, dataset, resolution, vram, quality] if p.get("tip")]

        summary = [
            "╔══════════════════════════════════════════╗",
            "║   Anima LoRA Training Wizard - Summary   ║",
            "╚══════════════════════════════════════════╝",
            "",
            f"  Subject type:     {what_are_you_training}",
            f"  Dataset size:     {dataset_size}",
            f"  Resolution:       {final_resolution}"
            f"{'  (override)' if res_overridden else '  (your choice — presets never change it)'}",
            f"  GPU VRAM:         {gpu_vram}",
            f"  Quality goal:     {quality_goal}",
            "",
            "─── Auto-configured Parameters ───",
            "",
            f"  Network Type:     {network_type}",
            f"  Rank:             {rank}"
            f"{'  (override)' if rank_overridden else (f'  (halved from {rank_lora} — Lycoris needs lower rank)' if is_lycoris else '')}",
            f"  Alpha:            {alpha}",
            f"  Learning Rate:    {lr}"
            f"{'  (override)' if lr_overridden else ''}",
            f"  Optimizer:        {quality['optimizer_type']}",
            f"  LR Scheduler:     {dataset['lr_scheduler']}",
            f"  Warmup Steps:     {lr_warmup_steps}",
            # Annotate epochs / steps / save-frequency with their source so
            # the user can tell at a glance whether the preset or their
            # explicit override won.
            f"  Epochs:           {epochs}"
            f"{'  (override)' if force_max_train_epochs > 0 else '  (preset)'}",
            f"  Max Train Steps:  {max_train_steps if max_train_steps > 0 else '— (epoch-based)'}"
            f"{'  (override)' if force_max_train_steps > 0 else ''}",
            f"  Batch Size:       {batch}"
            f"{'  (override)' if batch_overridden else ('  (capped by VRAM preset)' if not batch_overridden and vram.get('train_batch_size_override') and dataset['train_batch_size'] > batch else '')}",
            f"  Noise Offset:     {subject.get('noise_offset', 0.0)}",
            "",
            f"─── Memory Settings (from the '{gpu_vram}' preset) ───",
            "",
            "  These are starting values picked for your card — NOT locked.",
            "  Change any of them with the force_* fields on this node, or",
            "  by adding a Memory Optimizer node after the wizard.",
            "",
            (f"  Model streaming:  {blocks_to_swap} of 28 model parts stay in normal RAM"
             f"{'  (override)' if swap_overridden else ''}" if blocks_to_swap > 0 else
             f"  Model streaming:  off — whole model stays on the GPU (fastest)"
             f"{'  (override)' if swap_overridden else ''}"),
            *(["                    and are fetched when needed. Costs speed, not",
               f"                    quality. (blocks_to_swap={blocks_to_swap})"] if blocks_to_swap > 0 else []),
            f"  Attention:        "
            f"{'memory-saving mode (' + vram['attn_mode'] + ' + split_attn)' if vram['split_attn'] else 'standard (' + vram['attn_mode'] + ')'}",
            f"  Recompute trick:  "
            f"{'on — redoes some math instead of storing it. Slower,' if vram['gradient_checkpointing'] else 'off — faster, but uses much more VRAM.'}",
            *(["                    but uses far less VRAM. (gradient_checkpointing)"] if vram['gradient_checkpointing'] else []),
            f"  Prep & reuse:     images and captions are converted once and reused",
            f"                    every epoch (cached "
            f"{'on disk' if vram['cache_latents_to_disk'] else 'in RAM'}). Big VRAM saving, no downside.",
            (f"  Precision:        fp16 — old-GPU mode (RTX 20xx / GTX 16xx)"
             if old_gpu_fp16 else
             f"  Precision:        bf16 — recommended for Anima"),
            *(["                    Only useful on cards without native bf16.",
               "                    If loss becomes NaN, turn old_gpu_fp16 off."]
              if old_gpu_fp16 else []),
            (f"  Safe image size:  up to {rec_max}px — your {res_max_dim}px choice fits"
             if rec_max and res_max_dim and res_max_dim <= rec_max else
             f"  Safe image size:  up to {rec_max}px — your {res_max_dim}px choice EXCEEDS"),
            *([f"                    this. It is KEPT AS-IS (presets never change your",
               f"                    resolution) — see the warning below."]
              if rec_max and res_max_dim > rec_max else []),
            "",
            f"  Output:           {output_dir}/{output_name}.safetensors",
            f"  Saving every:     {save_every_n_epochs} epoch(s)"
            f"{'  (override)' if force_save_every_n_epochs > 0 else '  (preset)'}",
            "",
        ]

        # --- Dataset folder check (structure, captions, repeats) ---
        ds = check_dataset(train_data_dir, caption_extension)
        summary.extend(format_dataset_report(ds))
        if not ds["ok"]:
            print(f"[AnimaTrainingWizard] DATASET PROBLEM(S): {'; '.join(ds['errors'])}", flush=True)

        if vram_warning:
            # Warn-only policy: the wizard never silently changes the user's
            # choices, but it makes the risk impossible to miss.
            summary.append("!!!!!!!!!!!!!!! VRAM WARNING !!!!!!!!!!!!!!!")
            for line in vram_warning.split("\n"):
                summary.append(f"  {line}")
            summary.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            summary.append("")
            print(f"[AnimaTrainingWizard] VRAM WARNING: {vram_warning}", flush=True)

        if tips:
            summary.append("─── Tips ───")
            summary.append("")
            for i, tip in enumerate(tips, 1):
                summary.append(f"  {i}. {tip}")
            summary.append("")

        summary.append("Connect to Training Launcher to start, or chain through")
        summary.append("Advanced Params / Memory Optimizer to fine-tune settings.")

        return (params, "\n".join(summary))
