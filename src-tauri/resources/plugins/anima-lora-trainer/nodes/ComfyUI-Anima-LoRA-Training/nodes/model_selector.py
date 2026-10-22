"""
ComfyUI Node: Anima Base Model Selector
Scans ComfyUI model folders and shows available models as dropdowns.
"""

import os
import glob
from pathlib import Path


def _get_comfyui_root() -> str:
    """Find ComfyUI root from this node's location in custom_nodes/."""
    this_file = Path(__file__).resolve()
    # nodes/ -> ComfyUI-Anima-LoRA-Training/ -> custom_nodes/ -> ComfyUI/
    return str(this_file.parent.parent.parent.parent)


def _scan_models(subfolder: str, extensions: tuple = (".safetensors", ".pth", ".ckpt")) -> list:
    """Scan a ComfyUI models subfolder and return relative filenames."""
    root = _get_comfyui_root()
    found = []

    # Check multiple possible locations
    search_dirs = [
        os.path.join(root, "models", subfolder),
    ]

    # Also try folder_paths if ComfyUI is loaded
    try:
        import folder_paths
        if hasattr(folder_paths, "get_folder_paths"):
            extra = folder_paths.get_folder_paths(subfolder)
            if extra:
                search_dirs.extend(extra)
    except Exception:
        pass

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for ext in extensions:
            for path in glob.glob(os.path.join(search_dir, "**", f"*{ext}"), recursive=True):
                rel = os.path.relpath(path, search_dir)
                found.append(rel)

    return sorted(set(found)) if found else ["(none found)"]


def _scan_directories(subfolder: str) -> list:
    """Scan for subdirectories (e.g. HuggingFace model dirs with config.json)."""
    root = _get_comfyui_root()
    found = []

    search_dirs = [os.path.join(root, "models", subfolder)]

    try:
        import folder_paths
        if hasattr(folder_paths, "get_folder_paths"):
            extra = folder_paths.get_folder_paths(subfolder)
            if extra:
                search_dirs.extend(extra)
    except Exception:
        pass

    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for entry in os.scandir(search_dir):
            if entry.is_dir():
                found.append(entry.name)
        # Also find .safetensors files directly
        for ext in (".safetensors", ".pth"):
            for path in glob.glob(os.path.join(search_dir, f"*{ext}")):
                found.append(os.path.basename(path))

    return sorted(set(found)) if found else ["(none found)"]


def _resolve_model_path(subfolder: str, filename: str) -> str:
    """Resolve a relative filename back to its full absolute path."""
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename

    root = _get_comfyui_root()
    search_dirs = [os.path.join(root, "models", subfolder)]

    try:
        import folder_paths
        if hasattr(folder_paths, "get_folder_paths"):
            extra = folder_paths.get_folder_paths(subfolder)
            if extra:
                search_dirs.extend(extra)
    except Exception:
        pass

    for search_dir in search_dirs:
        full = os.path.join(search_dir, filename)
        if os.path.exists(full):
            return full

    # Fallback: return as-is (user may have typed a custom path)
    return filename


# ---------------------------------------------------------------------------
# Scan at class-load time so ComfyUI can populate dropdown menus
# ---------------------------------------------------------------------------
def _dit_models() -> list:
    found = _scan_models("diffusion_models") + _scan_models("checkpoints") + _scan_models("unet") + _scan_models("anima")
    return sorted(set(m for m in found if m != "(none found)")) or ["(none found - place models in ComfyUI/models/)"]


_DIT_MODELS = _dit_models()

_TEXT_ENCODERS = _scan_directories("text_encoders") + _scan_directories("clip") + _scan_models("text_encoders") + _scan_models("clip")
_TEXT_ENCODERS = sorted(set(m for m in _TEXT_ENCODERS if m != "(none found)")) or ["(none found)"]

_VAES = _scan_models("vae") + _scan_models("anima")
_VAES = sorted(set(m for m in _VAES if m != "(none found)")) or ["(none found)"]


class AnimaModelSelector:
    """
    Scans ComfyUI model folders and presents available models in dropdown menus.
    Select your Anima DiT checkpoint, Qwen3 text encoder, and VAE.
    """

    @classmethod
    def INPUT_TYPES(cls):
        # rescanned on every call: ComfyUI validates a prompt's combo values against this list, so a base model downloaded
        # while the engine runs (Anima 2.9B / 3.8B from the trainer's base model choice) is accepted without a restart
        return {
            "required": {
                "dit_model": (_dit_models(), {
                    "tooltip": "Anima DiT model from ComfyUI/models/ (checkpoints, diffusion_models, unet, or anima)."
                }),
                "qwen3_encoder": (_TEXT_ENCODERS, {
                    "tooltip": "Qwen3-0.6B text encoder from ComfyUI/models/ (text_encoders or clip)."
                }),
                "vae": (_VAES, {
                    "tooltip": "Qwen-Image VAE from ComfyUI/models/ (vae or anima)."
                }),
            },
            "optional": {
                "dit_custom_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Override: paste a full path to a DiT model instead of using the dropdown."
                }),
                "qwen3_custom_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Override: paste a full path to Qwen3 encoder."
                }),
                "vae_custom_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Override: paste a full path to VAE."
                }),
                "llm_adapter_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Optional: separate LLM adapter weights. Leave empty to auto-load from DiT."
                }),
            }
        }

    RETURN_TYPES = ("ANIMA_MODEL_CONFIG", "STRING")
    RETURN_NAMES = ("model_config", "status_message")
    FUNCTION = "select_model"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = False

    def _resolve(self, dropdown_val: str, custom_path: str, subfolder: str, label: str) -> tuple:
        """Resolve a model selection from dropdown or custom path override."""
        if custom_path.strip():
            path = custom_path.strip()
            if os.path.exists(path):
                size = os.path.getsize(path) / (1024 * 1024) if os.path.isfile(path) else 0
                return path, True, f"{label}: {os.path.basename(path)} ({size:.0f} MB) [custom path]"
            return path, False, f"{label}: NOT FOUND at custom path: {path}"

        if "(none found" in dropdown_val:
            return "", False, f"{label}: No models found. Place files in ComfyUI/models/{subfolder}/"

        # Resolve from the subfolder search paths
        for sub in [subfolder, "diffusion_models", "checkpoints", "unet", "anima",
                     "text_encoders", "clip", "vae"]:
            resolved = _resolve_model_path(sub, dropdown_val)
            if os.path.exists(resolved):
                size = os.path.getsize(resolved) / (1024 * 1024) if os.path.isfile(resolved) else 0
                info = f"({size:.0f} MB)" if size else "(directory)"
                return resolved, True, f"{label}: {dropdown_val} {info}"

        return dropdown_val, False, f"{label}: Could not resolve path for {dropdown_val}"

    def select_model(self, dit_model: str, qwen3_encoder: str, vae: str,
                     dit_custom_path: str = "", qwen3_custom_path: str = "",
                     vae_custom_path: str = "", llm_adapter_path: str = "") -> tuple:

        messages = ["=== Anima Model Configuration ==="]
        all_valid = True

        dit_path, dit_ok, dit_msg = self._resolve(dit_model, dit_custom_path, "diffusion_models", "DiT Model")
        messages.append(dit_msg)
        if not dit_ok:
            all_valid = False

        qwen3_path, qwen3_ok, qwen3_msg = self._resolve(qwen3_encoder, qwen3_custom_path, "text_encoders", "Qwen3 Encoder")
        messages.append(qwen3_msg)
        if not qwen3_ok:
            all_valid = False

        # Warn if a non-Qwen3 text encoder is selected
        te_name = os.path.basename(qwen3_path).lower() if qwen3_path else ""
        if qwen3_ok and te_name and "qwen" not in te_name:
            messages.append(
                f"  WARNING: '{os.path.basename(qwen3_path)}' does not appear to be a Qwen3 encoder.\n"
                f"  The recommended text encoder is 'qwen_3_06b_base.safetensors'.\n"
                f"  Non-Qwen3 encoders (e.g. clip_l) may work but are NOT officially supported\n"
                f"  and could produce unexpected results during training."
            )

        vae_path, vae_ok, vae_msg = self._resolve(vae, vae_custom_path, "vae", "VAE")
        messages.append(vae_msg)
        if not vae_ok:
            all_valid = False

        # Optional adapter
        adapter_resolved = ""
        if llm_adapter_path.strip():
            if os.path.exists(llm_adapter_path.strip()):
                adapter_resolved = llm_adapter_path.strip()
                messages.append(f"LLM Adapter: {os.path.basename(adapter_resolved)}")
            else:
                messages.append(f"LLM Adapter: NOT FOUND at {llm_adapter_path}")

        status = "READY" if all_valid else "INCOMPLETE - check missing models above"
        messages.insert(1, f"Status: {status}\n")

        model_config = {
            "pretrained_model": dit_path,
            "qwen3_path": qwen3_path,
            "vae_path": vae_path,
            "llm_adapter_path": adapter_resolved,
            "t5_tokenizer_path": "",
            "is_valid": all_valid,
        }

        return (model_config, "\n".join(messages))
