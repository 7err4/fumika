"""
ComfyUI Nodes: Anima LoRA Training Parameters (Chunked)

Three nodes for manual parameter configuration:
  - AnimaBasicParams:    Essential settings (dataset, rank, LR, epochs)
  - AnimaAdvancedParams: Optional overrides (dropout, noise, regex, LoRA+)
  - AnimaMemoryOptimizer: VRAM/memory tuning (caching, precision, block swap)

Each node can accept an upstream TRAINING_PARAMS input and override specific
fields. This lets you chain: Wizard -> Advanced -> Memory -> Launcher
or build purely manual: Basic -> Advanced -> Memory -> Launcher.
"""

import copy
import sys
from pathlib import Path

try:
    from ..utils.config_generator import coerce_seed
    from ..utils.dataset_check import check_dataset, format_dataset_report
except ImportError:
    # Fallback for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.config_generator import coerce_seed
    from utils.dataset_check import check_dataset, format_dataset_report


class AnimaBasicParams:
    """
    Essential training parameters. Start here for manual configuration.
    Sets the core values: dataset path, LoRA architecture, learning rate, and schedule.
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
                "resolution": ("STRING", {
                    "default": "1024,1024",
                    "multiline": False,
                    "tooltip": "Training resolution (W,H or single value for square)."
                }),
                "network_type": (["LoRA", "LoKr", "LoHa"], {
                    "default": "LoRA",
                    "tooltip": "Network architecture. LoRA: standard low-rank. LoKr: Kronecker product (smaller file size). LoHa: Hadamard product (good for styles)."
                }),
                "network_rank": ("INT", {
                    "default": 16, "min": 1, "max": 256, "step": 1,
                    "tooltip": "Network rank. Higher = more capacity. 8-32 typical for LoRA, 4-16 for LoKr/LoHa."
                }),
                "network_alpha": ("FLOAT", {
                    "default": 8.0, "min": 0.1, "max": 256.0, "step": 0.1,
                    "tooltip": "Network alpha. Usually rank/2. Controls learning strength."
                }),
                "learning_rate": ("FLOAT", {
                    "default": 1e-4, "min": 1e-7, "max": 1e-1, "step": 1e-6,
                    "tooltip": "Base learning rate."
                }),
                "optimizer_type": ([
                    "AdamW8bit", "AdamW", "AdaFactor", "Prodigy",
                    "Lion8bit", "Lion", "DAdaptation", "DAdaptAdam"
                ], {"default": "AdamW8bit"}),
                "lr_scheduler": ([
                    "cosine", "cosine_with_restarts", "linear",
                    "constant", "constant_with_warmup", "polynomial"
                ], {"default": "cosine"}),
                "max_train_epochs": ("INT", {
                    "default": 10, "min": 1, "max": 1000, "step": 1,
                    "tooltip": "Training epochs. More = longer training."
                }),
                "train_batch_size": ("INT", {
                    "default": 1, "min": 1, "max": 16, "step": 1,
                    "tooltip": "Batch size. Higher needs more VRAM."
                }),
            },
            "optional": {
                "seed": ("INT", {
                    "default": 42, "min": 0, "max": 2147483647,
                }),
                "caption_extension": ("STRING", {"default": ".txt"}),
                "shuffle_caption": ("BOOLEAN", {"default": True}),
                "keep_tokens": ("INT", {
                    "default": 0, "min": 0, "max": 100,
                    "tooltip": "Leading tokens to keep unshuffled (trigger words)."
                }),
                "save_every_n_epochs": ("INT", {
                    "default": 1, "min": 1, "max": 100,
                }),
                "lr_warmup_steps": ("INT", {
                    "default": 0, "min": 0, "max": 10000,
                }),
                # LoKr-specific
                "lokr_factor": ("INT", {
                    "default": -1, "min": -1, "max": 64, "step": 1,
                    "tooltip": "LoKr decomposition factor. -1 = auto. Only used with LoKr."
                }),
                # LoKr/LoHa shared
                "use_tucker": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Tucker decomposition for conv layers. Reduces params at slight quality cost. Used with LoKr/LoHa."
                }),
            }
        }

    RETURN_TYPES = ("TRAINING_PARAMS", "STRING")
    RETURN_NAMES = ("training_params", "summary")
    FUNCTION = "set_params"
    CATEGORY = "Anima LoRA Training/Manual"
    OUTPUT_NODE = False

    def set_params(self, train_data_dir, output_dir, output_name, resolution,
                   network_type, network_rank, network_alpha, learning_rate,
                   optimizer_type, lr_scheduler, max_train_epochs, train_batch_size,
                   seed=42, caption_extension=".txt", shuffle_caption=True,
                   keep_tokens=0, save_every_n_epochs=1, lr_warmup_steps=0,
                   lokr_factor=-1, use_tucker=False) -> tuple:

        params = {
            "train_data_dir": train_data_dir.strip(),
            "output_dir": output_dir.strip(),
            "output_name": output_name.strip(),
            "resolution": resolution.strip(),
            "network_type": network_type,
            "network_rank": network_rank,
            "network_alpha": network_alpha,
            "learning_rate": learning_rate,
            "optimizer_type": optimizer_type,
            "lr_scheduler": lr_scheduler,
            "lr_warmup_steps": lr_warmup_steps,
            "max_train_epochs": max_train_epochs,
            "max_train_steps": 0,
            "train_batch_size": train_batch_size,
            # Defensive cast: an upstream node (Primitive/Reroute/external seed
            # generator) or a hand-edited workflow JSON may deliver `seed` as a
            # string, which would later land in the TOML as `seed = "1234"` and
            # crash numpy's `np.random.seed()` with `Cannot cast scalar from
            # dtype('<U4') to dtype('int64')`. Coerce to int; fall back to 42
            # on non-numeric input rather than raising in the node.
            "seed": coerce_seed(seed),
            "caption_extension": caption_extension,
            "shuffle_caption": shuffle_caption,
            "keep_tokens": keep_tokens,
            "save_every_n_epochs": save_every_n_epochs,
            "save_model_as": "safetensors",
            "log_with": "tensorboard",
            "max_data_loader_n_workers": 2,
            # Defaults for fields the other nodes will override
            "timestep_sampling": "sigmoid",
            "discrete_flow_shift": 1.0,
            "sigmoid_scale": 1.0,
            "attn_mode": "torch",
            "split_attn": False,
            "qwen3_max_token_length": 512,
            "t5_max_token_length": 512,
            "mixed_precision": "bf16",
            "gradient_checkpointing": True,
            "cache_latents": True,
            "cache_latents_to_disk": False,
            "cache_text_encoder_outputs": True,
            "cache_text_encoder_outputs_to_disk": False,
            "blocks_to_swap": 0,
            "vae_chunk_size": 64,
            "network_dropout": 0.0,
            "rank_dropout": 0.0,
            "module_dropout": 0.0,
            "train_llm_adapter": False,
            "loraplus_lr_ratio": 0.0,
            "noise_offset": 0.0,
            "min_snr_gamma": 0.0,
            "include_patterns": "",
            "exclude_patterns": "",
            "network_reg_dims": "",
            "network_reg_lrs": "",
            "unet_lr": 0.0,
            "text_encoder_lr": 0.0,
            # LoKr/LoHa specific
            "lokr_factor": lokr_factor,
            "use_tucker": use_tucker,
        }

        summary_lines = [
            f"Basic: {network_type} rank={network_rank}, alpha={network_alpha}, "
            f"lr={learning_rate}, opt={optimizer_type}, "
            f"epochs={max_train_epochs}, batch={train_batch_size}, "
            f"res={resolution}",
            "",
        ]
        # Dataset folder check (structure, captions, repeats)
        summary_lines.extend(format_dataset_report(
            check_dataset(train_data_dir, caption_extension)))
        return (params, "\n".join(summary_lines))


class AnimaAdvancedParams:
    """
    Advanced overrides. Connect TRAINING_PARAMS from Wizard or Basic Params.
    Only the fields you change here will override the upstream values.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "training_params": ("TRAINING_PARAMS", {
                    "tooltip": "Upstream params from Wizard or Basic Params node."
                }),
            },
            "optional": {
                # --- Anima-specific ---
                "timestep_sampling": (["(keep current)", "sigmoid", "uniform", "sigma", "shift", "flux_shift"],
                                      {"default": "(keep current)"}),
                "discrete_flow_shift": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 10.0, "step": 0.1,
                    "tooltip": "Rectified Flow shift. -1 = keep current."
                }),
                "sigmoid_scale": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 5.0, "step": 0.1,
                    "tooltip": "Sigmoid scale. -1 = keep current."
                }),
                "qwen3_max_token_length": ("INT", {
                    "default": -1, "min": -1, "max": 2048, "step": 64,
                    "tooltip": "Qwen3 max tokens. -1 = keep current."
                }),
                "t5_max_token_length": ("INT", {
                    "default": -1, "min": -1, "max": 2048, "step": 64,
                    "tooltip": "T5 max tokens. -1 = keep current."
                }),

                # --- Dropout ---
                "network_dropout": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Network dropout. -1 = keep current."
                }),
                "rank_dropout": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Rank dropout. -1 = keep current."
                }),
                "module_dropout": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Module dropout. -1 = keep current."
                }),

                # --- LoRA extras ---
                "train_llm_adapter": (["(keep current)", "yes", "no"],
                                      {"default": "(keep current)"}),
                "loraplus_lr_ratio": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "LoRA+ LR ratio. -1 = keep current. 0 = disabled."
                }),
                "noise_offset": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Noise offset. -1 = keep current."
                }),
                "min_snr_gamma": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 20.0, "step": 0.1,
                    "tooltip": "Min-SNR gamma. -1 = keep current."
                }),

                # --- Separate LRs ---
                "unet_lr": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 1e-1, "step": 1e-6,
                    "tooltip": "Separate DiT LR. -1 = keep current."
                }),
                "text_encoder_lr": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 1e-1, "step": 1e-6,
                    "tooltip": "Separate text encoder LR. -1 = keep current."
                }),

                # --- Regex module control ---
                "include_patterns": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Regex to force-include modules. Empty = keep current."
                }),
                "exclude_patterns": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Regex to exclude modules. Empty = keep current."
                }),
                "network_reg_dims": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Per-module rank (pattern=rank). Empty = keep current."
                }),
                "network_reg_lrs": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Per-module LR (pattern=lr). Empty = keep current."
                }),
            }
        }

    RETURN_TYPES = ("TRAINING_PARAMS", "STRING")
    RETURN_NAMES = ("training_params", "overrides_applied")
    FUNCTION = "apply_overrides"
    CATEGORY = "Anima LoRA Training/Manual"
    OUTPUT_NODE = False

    def apply_overrides(self, training_params, **kwargs) -> tuple:
        params = copy.deepcopy(training_params)
        applied = []

        # Float overrides: -1 means "keep current"
        for key in ["discrete_flow_shift", "sigmoid_scale", "network_dropout",
                     "rank_dropout", "module_dropout", "loraplus_lr_ratio",
                     "noise_offset", "min_snr_gamma", "unet_lr", "text_encoder_lr"]:
            val = kwargs.get(key, -1.0)
            if val >= 0:
                params[key] = val
                applied.append(f"{key}={val}")

        # Int overrides: -1 means "keep current"
        for key in ["qwen3_max_token_length", "t5_max_token_length"]:
            val = kwargs.get(key, -1)
            if val >= 0:
                params[key] = val
                applied.append(f"{key}={val}")

        # Dropdown overrides
        ts = kwargs.get("timestep_sampling", "(keep current)")
        if ts != "(keep current)":
            params["timestep_sampling"] = ts
            applied.append(f"timestep_sampling={ts}")

        tla = kwargs.get("train_llm_adapter", "(keep current)")
        if tla != "(keep current)":
            params["train_llm_adapter"] = (tla == "yes")
            applied.append(f"train_llm_adapter={tla}")

        # String overrides: empty means "keep current"
        for key in ["include_patterns", "exclude_patterns", "network_reg_dims", "network_reg_lrs"]:
            val = kwargs.get(key, "")
            if val.strip():
                params[key] = val.strip()
                applied.append(f"{key}=<set>")

        msg = f"Advanced overrides: {', '.join(applied)}" if applied else "No advanced overrides applied."
        return (params, msg)


class AnimaMemoryOptimizer:
    """
    VRAM and memory optimization settings. Connect after Wizard/Basic or Advanced.
    Adjust caching, precision, and block swapping for your GPU.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "training_params": ("TRAINING_PARAMS", {
                    "tooltip": "Upstream params to apply memory settings to."
                }),
            },
            "optional": {
                "mixed_precision": (["(keep current)", "bf16", "fp16"],
                                    {"default": "(keep current)",
                                     "tooltip": "bf16 is recommended for Anima. fp16 is ONLY for "
                                                "GPUs without native bf16 (RTX 20xx / GTX 16xx) - "
                                                "faster there, zero benefit on RTX 30xx+. Needs a "
                                                "current sd-scripts; if loss becomes NaN, go back "
                                                "to bf16."}),
                "attn_mode": (["(keep current)", "torch", "xformers", "flash", "sageattn"],
                              {"default": "(keep current)"}),
                "gradient_checkpointing": (["(keep current)", "yes", "no"],
                                           {"default": "(keep current)"}),
                "split_attn": (["(keep current)", "yes", "no"],
                               {"default": "(keep current)"}),
                "cache_latents": (["(keep current)", "yes", "no"],
                                  {"default": "(keep current)"}),
                "cache_latents_to_disk": (["(keep current)", "yes", "no"],
                                          {"default": "(keep current)"}),
                "cache_text_encoder_outputs": (["(keep current)", "yes", "no"],
                                               {"default": "(keep current)"}),
                "cache_text_encoder_outputs_to_disk": (["(keep current)", "yes", "no"],
                                                       {"default": "(keep current)"}),
                "blocks_to_swap": ("INT", {
                    "default": -1, "min": -1, "max": 34, "step": 1,
                    "tooltip": "Blocks to swap to CPU. -1 = keep current. 0 = disabled."
                }),
                "vae_chunk_size": ("INT", {
                    "default": -1, "min": -1, "max": 64, "step": 1,
                    "tooltip": "VAE chunk size. -1 = keep current. 0 = no chunking."
                }),
                "max_data_loader_n_workers": ("INT", {
                    "default": -1, "min": -1, "max": 16, "step": 1,
                    "tooltip": "Data loader workers. -1 = keep current."
                }),
            }
        }

    RETURN_TYPES = ("TRAINING_PARAMS", "STRING")
    RETURN_NAMES = ("training_params", "memory_summary")
    FUNCTION = "optimize_memory"
    CATEGORY = "Anima LoRA Training/Manual"
    OUTPUT_NODE = False

    def optimize_memory(self, training_params, **kwargs) -> tuple:
        params = copy.deepcopy(training_params)
        applied = []

        # Dropdown string overrides
        for key in ["mixed_precision", "attn_mode"]:
            val = kwargs.get(key, "(keep current)")
            if val != "(keep current)":
                params[key] = val
                applied.append(f"{key}={val}")

        # Dropdown bool overrides
        for key in ["gradient_checkpointing", "split_attn", "cache_latents",
                     "cache_latents_to_disk", "cache_text_encoder_outputs",
                     "cache_text_encoder_outputs_to_disk"]:
            val = kwargs.get(key, "(keep current)")
            if val != "(keep current)":
                params[key] = (val == "yes")
                applied.append(f"{key}={val}")

        # Int overrides
        for key in ["blocks_to_swap", "vae_chunk_size", "max_data_loader_n_workers"]:
            val = kwargs.get(key, -1)
            if val >= 0:
                params[key] = val
                applied.append(f"{key}={val}")

        # Build summary of current memory config
        summary_lines = [
            "─── Memory Configuration ───",
            f"  Precision:        {params.get('mixed_precision', 'bf16')}",
            f"  Attention:        {params.get('attn_mode', 'torch')}",
            f"  Grad Checkpoint:  {params.get('gradient_checkpointing', True)}",
            f"  Cache Latents:    {params.get('cache_latents', True)} (disk: {params.get('cache_latents_to_disk', False)})",
            f"  Cache TE:         {params.get('cache_text_encoder_outputs', True)} (disk: {params.get('cache_text_encoder_outputs_to_disk', False)})",
            f"  Block Swap:       {params.get('blocks_to_swap', 0)}",
            f"  VAE Chunk:        {params.get('vae_chunk_size', 0)}",
            "",
        ]
        if applied:
            summary_lines.append(f"Overrides: {', '.join(applied)}")
        else:
            summary_lines.append("No memory overrides applied (using upstream values).")

        return (params, "\n".join(summary_lines))
