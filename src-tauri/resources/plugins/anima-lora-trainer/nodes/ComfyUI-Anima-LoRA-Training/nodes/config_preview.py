"""
ComfyUI Node: Anima Training Config Preview
Shows the full TOML config that would be generated, for review before launching.
Read-only — no side effects.
"""

import io
import sys
from pathlib import Path

try:
    from ..utils.config_generator import (
        generate_training_config, _dump_toml, normalize_training_params,
    )
    from ..utils.dataset_check import check_dataset, format_dataset_report
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.config_generator import (
        generate_training_config, _dump_toml, normalize_training_params,
    )
    from utils.dataset_check import check_dataset, format_dataset_report


class AnimaConfigPreview:
    """
    Generates and displays the full TOML training config without launching anything.
    Connect after your param nodes (Wizard, Basic, Advanced, Memory) to see
    exactly what will be passed to sd-scripts.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_config": ("ANIMA_MODEL_CONFIG", {
                    "tooltip": "Model configuration (from Model Selector node)."
                }),
                "training_params": ("TRAINING_PARAMS", {
                    "tooltip": "Training parameters (from any param node)."
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "preview"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        import time
        return time.time()

    def preview(self, model_config: dict, training_params: dict):

        # Validate inputs minimally
        if not model_config.get("is_valid", False):
            return {"ui": {"text": ("ERROR: Model configuration is invalid. Check the Model Selector node.",)}}

        if not training_params.get("train_data_dir"):
            return {"ui": {"text": ("ERROR: train_data_dir is not set.",)}}

        if not training_params.get("output_dir"):
            return {"ui": {"text": ("ERROR: output_dir is not set.",)}}

        # Coerce numeric fields so the preview matches what the launcher will
        # actually write — see normalize_training_params for the rationale.
        training_params = normalize_training_params(training_params)

        # Generate the config dict using the same function the launcher uses
        config = generate_training_config(
            output_dir=training_params["output_dir"],
            pretrained_model=model_config["pretrained_model"],
            qwen3_path=model_config["qwen3_path"],
            vae_path=model_config["vae_path"],
            train_data_dir=training_params["train_data_dir"],
            # Network
            network_type=training_params.get("network_type", "LoRA"),
            network_rank=training_params.get("network_rank", 16),
            network_alpha=training_params.get("network_alpha", 8.0),
            # Training
            learning_rate=training_params.get("learning_rate", 1e-4),
            unet_lr=training_params.get("unet_lr", None),
            text_encoder_lr=training_params.get("text_encoder_lr", None),
            optimizer_type=training_params.get("optimizer_type", "AdamW8bit"),
            lr_scheduler=training_params.get("lr_scheduler", "cosine"),
            lr_warmup_steps=training_params.get("lr_warmup_steps", 0),
            max_train_epochs=training_params.get("max_train_epochs", 10),
            max_train_steps=training_params.get("max_train_steps", 0),
            train_batch_size=training_params.get("train_batch_size", 1),
            resolution=training_params.get("resolution", "1024,1024"),
            # Anima
            timestep_sampling=training_params.get("timestep_sampling", "sigmoid"),
            discrete_flow_shift=training_params.get("discrete_flow_shift", 1.0),
            sigmoid_scale=training_params.get("sigmoid_scale", 1.0),
            attn_mode=training_params.get("attn_mode", "torch"),
            split_attn=training_params.get("split_attn", False),
            qwen3_max_token_length=training_params.get("qwen3_max_token_length", 512),
            t5_max_token_length=training_params.get("t5_max_token_length", 512),
            # Memory
            cache_latents=training_params.get("cache_latents", True),
            cache_latents_to_disk=training_params.get("cache_latents_to_disk", False),
            cache_text_encoder_outputs=training_params.get("cache_text_encoder_outputs", True),
            cache_text_encoder_outputs_to_disk=training_params.get("cache_text_encoder_outputs_to_disk", False),
            blocks_to_swap=training_params.get("blocks_to_swap", 0),
            vae_chunk_size=training_params.get("vae_chunk_size", 64),
            gradient_checkpointing=training_params.get("gradient_checkpointing", True),
            mixed_precision=training_params.get("mixed_precision", "bf16"),
            # LoRA advanced
            network_dropout=training_params.get("network_dropout", 0.0),
            rank_dropout=training_params.get("rank_dropout", 0.0),
            module_dropout=training_params.get("module_dropout", 0.0),
            train_llm_adapter=training_params.get("train_llm_adapter", False),
            loraplus_lr_ratio=training_params.get("loraplus_lr_ratio", 0.0),
            noise_offset=training_params.get("noise_offset", 0.0),
            min_snr_gamma=training_params.get("min_snr_gamma", 0.0),
            # Regex
            include_patterns=training_params.get("include_patterns", ""),
            exclude_patterns=training_params.get("exclude_patterns", ""),
            network_reg_dims=training_params.get("network_reg_dims", ""),
            network_reg_lrs=training_params.get("network_reg_lrs", ""),
            # LoKr/LoHa specific
            lokr_factor=training_params.get("lokr_factor", -1),
            use_tucker=training_params.get("use_tucker", False),
            # Optional paths
            llm_adapter_path=model_config.get("llm_adapter_path", ""),
            t5_tokenizer_path=model_config.get("t5_tokenizer_path", ""),
            # Dataset
            caption_extension=training_params.get("caption_extension", ".txt"),
            shuffle_caption=training_params.get("shuffle_caption", True),
            keep_tokens=training_params.get("keep_tokens", 0),
            # Saving
            save_every_n_epochs=training_params.get("save_every_n_epochs", 1),
            save_model_as=training_params.get("save_model_as", "safetensors"),
            output_name=training_params.get("output_name", ""),
            # Logging
            log_with=training_params.get("log_with", "tensorboard"),
            # Seed
            seed=training_params.get("seed", 42),
            max_data_loader_n_workers=training_params.get("max_data_loader_n_workers", 2),
        )

        # Dataset structure status on top — this node is the one always-
        # visible text panel in the wizard example workflow, so the check
        # must surface here, not only in the (unwired) wizard summary.
        ds = check_dataset(training_params["train_data_dir"],
                           training_params.get("caption_extension", ".txt"))
        ds_block = "\n".join(format_dataset_report(ds))

        # Render annotated TOML string
        toml_str = ds_block + "\n" + _annotated_toml(config)

        return {"ui": {"text": (toml_str,)}}


# ─── Parameter annotations ───────────────────────────────────────────
# Maps each TOML key to a short educational comment.

PARAM_ANNOTATIONS = {
    # Model
    "pretrained_model_name_or_path": "Path to the Anima DiT base model (.safetensors)",
    "qwen3": "Qwen3-0.6B text encoder (always frozen during training)",
    "vae": "Qwen-Image VAE (16ch, 8x spatial downscale)",
    "llm_adapter_path": "Optional LLM Adapter weights (bridges Qwen3 → T5 space)",
    "t5_tokenizer_path": "Optional T5 tokenizer directory (default: bundled configs/t5_old/)",

    # Network (LoRA / LoKr / LoHa)
    "network_module": "Network implementation: networks.lora_anima (LoRA), networks.lokr (LoKr), or networks.loha (LoHa)",
    "network_dim": "Network rank — higher = more capacity but more VRAM. 8-32 for LoRA, 4-16 for LoKr/LoHa",
    "network_alpha": "Scaling factor — usually rank/2. Controls learning strength",
    "network_args": "Extra args: algo selection (lokr/loha), regex dims/lrs, adapter training, dropout, etc.",
    "network_dropout": "Probability of dropping entire network during training (regularization)",
    "network_train_unet_only": "Only train DiT network, freeze text encoder (required when caching TE outputs)",

    # Training
    "learning_rate": "Base learning rate. 1e-4 typical for rank≤16, 2e-5 for rank≥32",
    "unet_lr": "Separate learning rate for DiT (overrides base LR for DiT)",
    "text_encoder_lr": "Separate learning rate for text encoder",
    "optimizer_type": "Optimizer: AdamW8bit (less VRAM), AdamW (precise), Prodigy (auto-tuning)",
    "lr_scheduler": "How LR changes over time: cosine (gradual decay), constant, linear",
    "lr_warmup_steps": "Steps of gradual LR warmup before full rate kicks in",
    "max_train_epochs": "Total training passes over the dataset",
    "max_train_steps": "Alternative: stop after N steps instead of epochs (0 = use epochs)",
    "train_batch_size": "Images per step. Higher = faster + more VRAM. Affects effective LR",
    "resolution": "Training resolution (must be multiples of 16 for Anima's VAE)",
    "seed": "Random seed for reproducibility",

    # Anima-specific
    "timestep_sampling": "How noise levels are sampled: sigmoid (default), uniform, shift",
    "discrete_flow_shift": "Rectified Flow shift value (used with 'shift' sampling)",
    "sigmoid_scale": "Scale factor for sigmoid/shift/flux_shift sampling",
    "attn_mode": "Attention backend: torch (default), xformers (needs split_attn), flash",
    "split_attn": "Split attention to save VRAM (required for xformers mode)",
    "qwen3_max_token_length": "Max tokens for Qwen3 text encoder (longer = more caption detail)",
    "t5_max_token_length": "Max tokens for T5 tokenizer",

    # Memory
    "mixed_precision": "Training precision — bf16 required for Anima (fp16 causes NaN)",
    "gradient_checkpointing": "Trade compute for VRAM: recompute activations instead of storing",
    "cache_latents": "Pre-encode images with VAE once, reuse cached tensors (saves VRAM)",
    "cache_latents_to_disk": "Cache latents to disk instead of RAM (slower but unlimited)",
    "cache_text_encoder_outputs": "Pre-encode captions once (saves VRAM, disables caption shuffle)",
    "cache_text_encoder_outputs_to_disk": "Cache text encoder outputs to disk",
    "blocks_to_swap": "Swap N DiT blocks between CPU↔GPU (saves VRAM, slower training)",
    "vae_chunk_size": "Process VAE in chunks of this size to reduce peak VRAM (64 recommended)",
    "vae_disable_cache": "Disable VAE internal caching to reduce VRAM usage",

    # Noise / loss
    "noise_offset": "Add noise offset for better contrast/exposure learning (0.0-0.1 typical)",
    "min_snr_gamma": "Min-SNR loss weighting — balances learning across noise levels (5.0 common)",

    # Dataset
    "train_data_dir": "Folder with training images and .txt caption files",
    "caption_extension": "File extension for caption files",
    "shuffle_caption": "Randomly reorder caption tags each epoch (disabled when caching TE)",
    "keep_tokens": "Number of leading tokens to never shuffle (e.g., trigger words)",

    # Saving
    "output_dir": "Where trained LoRA and checkpoints are saved",
    "output_name": "Filename for the output LoRA (without extension)",
    "save_every_n_epochs": "Save a checkpoint every N epochs",
    "save_model_as": "Output format: safetensors (recommended) or ckpt",
    "save_state": "Save full training state (optimizer etc.) for resuming later",

    # Resume
    "resume": "Path to a saved training state to resume from",

    # Sampling
    "sample_prompts": "Path to .txt file with prompts for sample image generation",
    "sample_sampler": "Sampler for sample generation: euler, ddim, dpmsolver++, etc.",
    "sample_at_first": "Generate a baseline sample at step 0 before training starts",
    "sample_every_n_steps": "Generate sample images every N training steps",
    "sample_every_n_epochs": "Generate sample images every N epochs",

    # Logging
    "logging_dir": "Directory for training logs (tensorboard, etc.)",
    "log_with": "Logging backend: tensorboard, wandb, etc.",

    # Data loader
    "max_data_loader_n_workers": "Parallel workers for loading training data",
    "persistent_data_loader_workers": "Keep data workers alive between epochs (faster)",
}

# Group keys into sections for readability
SECTION_HEADERS = {
    "pretrained_model_name_or_path": "═══ MODEL ═══",
    "network_module": "═══ NETWORK (LoRA / LoKr / LoHa) ═══",
    "learning_rate": "═══ TRAINING ═══",
    "timestep_sampling": "═══ ANIMA-SPECIFIC ═══",
    "mixed_precision": "═══ MEMORY & PERFORMANCE ═══",
    "noise_offset": "═══ NOISE / LOSS ═══",
    "train_data_dir": "═══ DATASET ═══",
    "output_dir": "═══ SAVING ═══",
    "resume": "═══ RESUME ═══",
    "sample_prompts": "═══ SAMPLE GENERATION ═══",
    "logging_dir": "═══ LOGGING ═══",
    "max_data_loader_n_workers": "═══ DATA LOADER ═══",
}


def _annotated_toml(config: dict) -> str:
    """Render config dict as TOML with section headers and inline annotations."""
    buf = io.StringIO()
    buf.write("# ─── Anima LoRA Training Config ───\n\n")

    for key, value in config.items():
        # Section header
        if key in SECTION_HEADERS:
            buf.write(f"\n# {SECTION_HEADERS[key]}\n")

        # Annotation comment
        if key in PARAM_ANNOTATIONS:
            buf.write(f"# {PARAM_ANNOTATIONS[key]}\n")

        # Value
        if isinstance(value, bool):
            buf.write(f"{key} = {'true' if value else 'false'}\n")
        elif isinstance(value, int):
            buf.write(f"{key} = {value}\n")
        elif isinstance(value, float):
            if abs(value) < 1e-3 and value != 0:
                buf.write(f'{key} = {value:.10f}'.rstrip('0').rstrip('.') + '\n')
            else:
                buf.write(f"{key} = {value}\n")
        elif isinstance(value, str):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            buf.write(f'{key} = "{escaped}"\n')
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
            buf.write(f"{key} = [{', '.join(items)}]\n")
        else:
            buf.write(f'{key} = "{value}"\n')

    return buf.getvalue()
