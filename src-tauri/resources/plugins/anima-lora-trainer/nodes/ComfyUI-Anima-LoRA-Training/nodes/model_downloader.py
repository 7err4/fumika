"""
ComfyUI Node: Anima Model Downloader
Downloads Anima model files (DiT, text encoder, VAE) from HuggingFace.
Fetches the latest release of the selected variant (base/aesthetic/turbo);
deprecated preview builds are never auto-selected.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import re
import time
import traceback
from pathlib import Path


# HuggingFace repo and paths
HF_REPO = "circlestone-labs/Anima"
HF_API_BASE = "https://huggingface.co/api/models"
HF_DOWNLOAD_BASE = "https://huggingface.co"
SPLIT_FILES_PREFIX = "split_files"

LOG_PREFIX = "[AnimaModelDownloader]"


def _log(msg: str):
    """Print to ComfyUI server console with prefix."""
    print(f"{LOG_PREFIX} {msg}", flush=True)


def _get_comfyui_root() -> str:
    """Find ComfyUI root from this node's location in custom_nodes/."""
    this_file = Path(__file__).resolve()
    return str(this_file.parent.parent.parent.parent)


def _hf_api_list(subfolder: str) -> list:
    """List files in a HuggingFace repo subfolder via the API.
    Returns list of dicts with 'path', 'size', 'type' keys.
    """
    path = f"{SPLIT_FILES_PREFIX}/{subfolder}"
    url = f"{HF_API_BASE}/{HF_REPO}/tree/main/{path}"
    _log(f"API request: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Anima-LoRA-Training/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            files = [item for item in data if item.get("type") == "file"]
            _log(f"API response: {len(files)} file(s) in {subfolder}/")
            for f in files:
                _log(f"  - {os.path.basename(f.get('path', '?'))} ({f.get('size', 0) / (1024*1024):.1f} MB)")
            return files
    except urllib.error.HTTPError as e:
        _log(f"API HTTP error for {subfolder}: {e.code} {e.reason}")
        return []
    except urllib.error.URLError as e:
        _log(f"API URL error for {subfolder}: {e.reason}")
        return []
    except Exception as e:
        _log(f"API error for {subfolder}: {type(e).__name__}: {e}")
        _log(traceback.format_exc())
        return []


DIT_VARIANTS = ["base", "aesthetic", "turbo"]


def _parse_version(name: str) -> tuple:
    """Extract a sortable version tuple from a filename.
    'anima-base-v1.0.safetensors'  -> (1, 0, '')
    'anima-aesthetic-v1.0b.safetensors' -> (1, 0, 'b')
    'anima-aesthetic-v1.1.safetensors'  -> (1, 1, '')
    Returns (-1, -1, '') if no version found.
    """
    m = re.search(r"[-_]v(\d+)(?:\.(\d+))?([a-z]?)\.safetensors$", name, re.IGNORECASE)
    if not m:
        return (-1, -1, "")
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) else 0
    suffix = m.group(3) or ""
    return (major, minor, suffix)


def _find_latest_diffusion_model(files: list, variant: str = "base") -> str:
    """Given a list of HF file entries for diffusion_models/, return the
    filename of the latest release of the chosen variant (base/aesthetic/turbo).

    Deprecated pre-release files (anima-preview*.safetensors) are always
    excluded — they must never be picked automatically.
    """
    safetensors = [f for f in files if f.get("path", "").endswith(".safetensors")]
    if not safetensors:
        return ""

    names = [os.path.basename(f["path"]) for f in safetensors]

    # Never auto-select deprecated preview builds
    released = [n for n in names if "preview" not in n.lower()]
    if not released:
        _log("WARNING: only preview builds found in repo; refusing to auto-select one")
        return ""

    # Prefer files of the requested variant (e.g. 'anima-base-v1.0.safetensors')
    variant = (variant or "base").lower()
    candidates = [n for n in released if variant in n.lower()]
    if not candidates:
        _log(f"No '{variant}' variant found, falling back to any released model")
        candidates = released

    # Highest semantic version wins (v1.1 > v1.0b > v1.0)
    candidates.sort(key=_parse_version)
    latest = candidates[-1]
    _log(f"Latest '{variant}' diffusion model: {latest} (from {len(names)} file(s), {len(names) - len(released)} preview build(s) skipped)")
    return latest


class AnimaModelDownloader:
    """
    Downloads Anima model files from HuggingFace (circlestone-labs/Anima).
    Automatically detects the latest release of the chosen variant
    (base/aesthetic/turbo); deprecated preview builds are skipped.
    Files are saved to the appropriate ComfyUI/models/ subfolders.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["check_and_download", "check_only", "force_redownload"], {
                    "default": "check_and_download",
                    "tooltip": "check_only: see what's available. check_and_download: download missing files. force_redownload: re-download everything."
                }),
            },
            "optional": {
                "download_dit": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Download the latest Anima DiT model (~4.2 GB)."
                }),
                "dit_variant": (DIT_VARIANTS, {
                    "default": "base",
                    "tooltip": "Which Anima release line to download. 'base' is the pretrained model - LoRAs should be trained on this. 'aesthetic' and 'turbo' are fine-tuned/distilled variants for inference."
                }),
                "download_text_encoder": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Download Qwen3-0.6B text encoder (~1.2 GB)."
                }),
                "download_vae": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Download Qwen-Image VAE (~242 MB)."
                }),
                "custom_models_dir": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Override ComfyUI models directory. Leave empty for auto-detection."
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status_message",)
    FUNCTION = "manage_models"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        import time
        return time.time()

    def _get_models_root(self, custom_dir: str) -> str:
        """Get the ComfyUI models directory."""
        if custom_dir and custom_dir.strip():
            _log(f"Using custom models dir: {custom_dir.strip()}")
            return custom_dir.strip()

        # Try folder_paths first (most reliable in ComfyUI context)
        try:
            import folder_paths
            if hasattr(folder_paths, "models_dir"):
                _log(f"Using folder_paths.models_dir: {folder_paths.models_dir}")
                return folder_paths.models_dir
        except Exception:
            pass

        root = _get_comfyui_root()
        models_dir = os.path.join(root, "models")
        _log(f"Using fallback models dir: {models_dir}")
        return models_dir

    def manage_models(self, action: str,
                      download_dit: bool = True,
                      dit_variant: str = "base",
                      download_text_encoder: bool = True,
                      download_vae: bool = True,
                      custom_models_dir: str = "") -> tuple:

        _log("=" * 60)
        _log(f"Starting model manager (action={action})")
        _log(f"  download_dit={download_dit} (variant={dit_variant}), download_te={download_text_encoder}, download_vae={download_vae}")

        messages = ["=== Anima Model Downloader ==="]
        models_root = self._get_models_root(custom_models_dir)
        messages.append(f"Models directory: {models_root}")

        if not os.path.isdir(models_root):
            try:
                os.makedirs(models_root, exist_ok=True)
                _log(f"Created models directory: {models_root}")
                messages.append(f"Created models directory: {models_root}")
            except OSError as e:
                _log(f"ERROR: Cannot create models directory: {e}")
                return (f"ERROR: Cannot create models directory: {models_root}\n{e}",)

        # ── Gather info from HuggingFace ──
        _log(f"Querying HuggingFace repo: {HF_REPO}")
        messages.append(f"\nQuerying HuggingFace: {HF_REPO}...")

        download_plan = []  # List of (hf_subfolder, filename, dest_dir, size, label)

        # --- DiT (diffusion_models) ---
        if download_dit:
            _log("Checking diffusion_models/...")
            dit_files = _hf_api_list("diffusion_models")
            if dit_files:
                latest = _find_latest_diffusion_model(dit_files, dit_variant)
                if latest:
                    entry = next((f for f in dit_files if os.path.basename(f["path"]) == latest), None)
                    size = entry.get("size", 0) if entry else 0
                    dest_dir = os.path.join(models_root, "diffusion_models")
                    download_plan.append(("diffusion_models", latest, dest_dir, size, f"DiT Model ({dit_variant}, latest)"))
                    messages.append(f"\nDiT: {latest} ({size / (1024**3):.2f} GB)")
                    all_names = [os.path.basename(f["path"]) for f in dit_files if f["path"].endswith(".safetensors")]
                    released = [n for n in all_names if "preview" not in n.lower()]
                    if len(released) > 1:
                        messages.append(f"  Available versions: {', '.join(released)}")
                        messages.append(f"  Selected (latest {dit_variant}): {latest}")
                    skipped = len(all_names) - len(released)
                    if skipped:
                        messages.append(f"  ({skipped} deprecated preview build(s) ignored)")
                else:
                    messages.append("\nDiT: No .safetensors files found in repo")
                    _log("No .safetensors found in diffusion_models/")
            else:
                messages.append("\nDiT: Could not query HuggingFace (check network)")

        # --- Text Encoder ---
        if download_text_encoder:
            _log("Checking text_encoders/...")
            te_files = _hf_api_list("text_encoders")
            if te_files:
                for f in te_files:
                    fname = os.path.basename(f["path"])
                    if fname.endswith(".safetensors"):
                        size = f.get("size", 0)
                        dest_dir = os.path.join(models_root, "text_encoders")
                        download_plan.append(("text_encoders", fname, dest_dir, size, "Qwen3 Text Encoder"))
                        messages.append(f"Text Encoder: {fname} ({size / (1024**3):.2f} GB)")
            else:
                messages.append("\nText Encoder: Could not query HuggingFace")

        # --- VAE ---
        if download_vae:
            _log("Checking vae/...")
            vae_files = _hf_api_list("vae")
            if vae_files:
                for f in vae_files:
                    fname = os.path.basename(f["path"])
                    if fname.endswith(".safetensors"):
                        size = f.get("size", 0)
                        dest_dir = os.path.join(models_root, "vae")
                        download_plan.append(("vae", fname, dest_dir, size, "Qwen-Image VAE"))
                        messages.append(f"VAE: {fname} ({size / (1024**2):.0f} MB)")
            else:
                messages.append("\nVAE: Could not query HuggingFace")

        if not download_plan:
            msg = "Nothing to download (all toggles disabled or repo unreachable)."
            _log(msg)
            messages.append(f"\n{msg}")
            return ("\n".join(messages),)

        _log(f"Download plan: {len(download_plan)} file(s)")

        # ── Check existing files ──
        to_download = []
        for hf_sub, fname, dest_dir, size, label in download_plan:
            dest_path = os.path.join(dest_dir, fname)
            exists = os.path.exists(dest_path)
            local_size = os.path.getsize(dest_path) if exists else 0

            if exists and action != "force_redownload":
                if size > 0 and abs(local_size - size) / size > 0.01:
                    _log(f"  {label}: size mismatch local={local_size} vs remote={size}")
                    messages.append(f"  {label}: EXISTS but size mismatch (local {local_size / (1024**2):.0f} MB vs remote {size / (1024**2):.0f} MB) - will re-download")
                    to_download.append((hf_sub, fname, dest_path, size, label))
                else:
                    _log(f"  {label}: already downloaded at {dest_path}")
                    messages.append(f"  {label}: Already downloaded")
            else:
                if exists and action == "force_redownload":
                    _log(f"  {label}: force re-download")
                    messages.append(f"  {label}: Force re-download requested")
                else:
                    _log(f"  {label}: not found at {dest_path}")
                    messages.append(f"  {label}: Not found locally - will download")
                to_download.append((hf_sub, fname, dest_path, size, label))

        # ── Check only mode ──
        if action == "check_only":
            if to_download:
                total_size = sum(s for _, _, _, s, _ in to_download)
                messages.append(f"\n{len(to_download)} file(s) need downloading.")
                messages.append(f"Total download size: ~{total_size / (1024**3):.2f} GB")
            else:
                messages.append("\nAll selected models are already downloaded.")
            messages.append("\nSet action to 'check_and_download' to download missing files.")
            _log("Check-only complete")
            return ("\n".join(messages),)

        # ── Download missing files ──
        if not to_download:
            _log("All files present, nothing to download")
            messages.append("\nAll selected models are already downloaded. Nothing to do.")
            return ("\n".join(messages),)

        total_size = sum(s for _, _, _, s, _ in to_download)
        _log(f"Downloading {len(to_download)} file(s), total ~{total_size / (1024**3):.2f} GB")
        messages.append(f"\nDownloading {len(to_download)} file(s) (~{total_size / (1024**3):.2f} GB)...")
        messages.append("Progress is shown in the ComfyUI console and progress bar.\n")

        # Setup ComfyUI progress bar
        pbar = None
        try:
            from comfy.utils import ProgressBar
            # Total progress = sum of all bytes to download
            pbar = ProgressBar(total_size)
            _log("ComfyUI ProgressBar initialized")
        except Exception as e:
            _log(f"Could not create ProgressBar: {e} (will use console only)")

        all_ok = True
        cumulative_downloaded = 0

        for idx, (hf_sub, fname, dest_path, size, label) in enumerate(to_download):
            messages.append(f"[{idx+1}/{len(to_download)}] Downloading {label}: {fname}...")
            _log(f"--- File {idx+1}/{len(to_download)}: {fname} ---")
            download_url = f"{HF_DOWNLOAD_BASE}/{HF_REPO}/resolve/main/{SPLIT_FILES_PREFIX}/{hf_sub}/{fname}"

            # Create a per-file progress callback that updates the global bar
            file_base = cumulative_downloaded
            def _progress(downloaded, total_file, _base=file_base, _pbar=pbar, _total=total_size):
                if _pbar:
                    _pbar.update_absolute(_base + downloaded, _total)

            ok, msg = _download_file_with_callback(
                download_url, dest_path, label,
                expected_size=size,
                progress_fn=_progress
            )

            if ok:
                messages.append(f"  OK - {msg}")
                cumulative_downloaded += size
                if pbar:
                    pbar.update_absolute(cumulative_downloaded, total_size)
            else:
                messages.append(f"  FAILED - {msg}")
                all_ok = False

        # ── Summary ──
        _log("=" * 60)
        if all_ok:
            _log("All downloads complete!")
            messages.append(f"\n=== All downloads complete ===")
            messages.append("Models are ready. Use the Model Selector node to select them.")
        else:
            _log("Some downloads failed!")
            messages.append(f"\n=== Some downloads failed ===")
            messages.append("Check the ComfyUI console for details.")

        return ("\n".join(messages),)


def _download_file_with_callback(url: str, dest_path: str, label: str,
                                  expected_size: int = 0,
                                  progress_fn=None) -> tuple:
    """Download a file with a progress callback function.
    progress_fn(downloaded_bytes, total_bytes) is called periodically.
    Returns (success: bool, message: str).
    """
    tmp_path = dest_path + ".download"
    _log(f"Download start: {label}")
    _log(f"  URL: {url}")
    _log(f"  Dest: {dest_path}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Anima-LoRA-Training/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", expected_size) or 0)
            _log(f"  Content-Length: {total} bytes ({total / (1024*1024):.1f} MB)")

            # Check for redirect / error
            if resp.status != 200:
                _log(f"  HTTP status: {resp.status}")

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            downloaded = 0
            chunk_size = 8 * 1024 * 1024  # 8 MB chunks
            last_pct_print = -5
            start_time = time.time()

            with open(tmp_path, "wb") as f:
                while True:
                    try:
                        chunk = resp.read(chunk_size)
                    except Exception as read_err:
                        _log(f"  Read error at {downloaded/(1024*1024):.0f} MB: {read_err}")
                        raise
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Progress callback for ComfyUI bar
                    if progress_fn and total > 0:
                        progress_fn(downloaded, total)

                    # Console progress every 5%
                    if total > 0:
                        pct = downloaded * 100 / total
                        if pct - last_pct_print >= 5:
                            elapsed = time.time() - start_time
                            speed = downloaded / (1024 * 1024 * max(elapsed, 0.1))
                            remaining = total - downloaded
                            eta = remaining / (downloaded / max(elapsed, 0.1)) if downloaded > 0 else 0
                            _log(f"  [{label}] {pct:.0f}%  {downloaded/(1024*1024):.0f}/{total/(1024*1024):.0f} MB  {speed:.1f} MB/s  ETA {eta:.0f}s")
                            last_pct_print = pct
                    elif downloaded % (50 * 1024 * 1024) < chunk_size:
                        _log(f"  [{label}] {downloaded/(1024*1024):.0f} MB downloaded...")

        elapsed = time.time() - start_time

        # Verify download
        tmp_size = os.path.getsize(tmp_path)
        if total > 0 and abs(tmp_size - total) > 1024:
            _log(f"  SIZE MISMATCH: expected {total}, got {tmp_size}")
            os.remove(tmp_path)
            return False, f"Size mismatch: expected {total/(1024*1024):.0f} MB, got {tmp_size/(1024*1024):.0f} MB"

        # Rename temp file to final
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(tmp_path, dest_path)

        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        speed = size_mb / max(elapsed, 0.1)
        _log(f"  [{label}] COMPLETE: {size_mb:.0f} MB in {elapsed:.1f}s ({speed:.1f} MB/s)")
        return True, f"Downloaded ({size_mb:.0f} MB in {elapsed:.0f}s, {speed:.1f} MB/s)"

    except urllib.error.HTTPError as e:
        _log(f"  [{label}] HTTP ERROR: {e.code} {e.reason}")
        _cleanup_tmp(tmp_path)
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        _log(f"  [{label}] URL ERROR: {e.reason}")
        _cleanup_tmp(tmp_path)
        return False, f"Network error: {e.reason}"
    except Exception as e:
        _log(f"  [{label}] FAILED: {type(e).__name__}: {e}")
        _log(traceback.format_exc())
        _cleanup_tmp(tmp_path)
        return False, f"{type(e).__name__}: {str(e)}"


def _cleanup_tmp(tmp_path: str):
    """Remove partial download file."""
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
            _log(f"  Cleaned up: {tmp_path}")
        except OSError:
            pass
