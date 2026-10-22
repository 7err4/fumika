"""
ComfyUI Node: Anima LoRA Training Launcher
Generates config and launches sd-scripts training in a new command window.
"""

import os
import sys
import shlex
import subprocess
import platform
import json
from datetime import datetime
from pathlib import Path


def _sanitize_window_title(title: str) -> str:
    """Strip characters that break Windows CMD `title` and AppleScript window names.

    CMD's `title` directive treats `"` as a string boundary and breaks on newlines.
    Replace `"` with `'` and collapse newlines to spaces — the title is purely
    cosmetic so a lossy transform is fine.
    """
    return title.replace('"', "'").replace("\n", " ").replace("\r", " ").strip()


def _applescript_string_escape(s: str) -> str:
    """Escape a string for embedding inside an AppleScript double-quoted literal.

    Backslash must be escaped first so the second pass doesn't double-escape it.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')

# Import relative to package
try:
    from ..utils.config_generator import (
        generate_training_config, write_toml_config, config_to_cli_args,
        normalize_training_params,
    )
    from ..utils.dataset_check import check_dataset, format_dataset_report
    from ..utils.dep_check import probe_modules, pip_name
    from ..utils import anima_blocks
except ImportError:
    # Fallback for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.config_generator import (
        generate_training_config, write_toml_config, config_to_cli_args,
        normalize_training_params,
    )
    from utils.dataset_check import check_dataset, format_dataset_report
    from utils import anima_blocks
    from utils.dep_check import probe_modules, pip_name


class AnimaTrainingLauncher:
    """
    Takes the validated sd-scripts path, model config, and training params,
    generates a TOML config file, and launches training in a new command window.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sdscripts_path": ("STRING", {
                    "forceInput": True,
                    "tooltip": "Path to sd-scripts (from SD-Scripts Manager node)."
                }),
                "is_ready": ("BOOLEAN", {
                    "forceInput": True,
                    "tooltip": "Whether sd-scripts is ready (from SD-Scripts Manager node)."
                }),
                "model_config": ("ANIMA_MODEL_CONFIG", {
                    "tooltip": "Model configuration (from Model Selector node)."
                }),
                "training_params": ("TRAINING_PARAMS", {
                    "tooltip": "Training parameters (from Training Params node)."
                }),
            },
            "optional": {
                "config_format": (["toml", "cli_args"], {
                    "default": "toml",
                    "tooltip": "Config format: TOML file or direct CLI arguments."
                }),
                "python_executable": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Custom Python path. Leave empty for sd-scripts venv or system Python."
                }),
                "extra_args": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Additional CLI arguments to pass to sd-scripts (one per line)."
                }),
                "resume_from": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Path to a saved training state folder to resume from. Leave empty for fresh training."
                }),
                "sample_prompts": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Sample prompts to generate during training (one per line). Leave empty to disable."
                }),
                "sample_every_n_steps": ("INT", {
                    "default": 0, "min": 0, "max": 100000, "step": 10,
                    "tooltip": "Generate sample images every N steps. 0 = disabled."
                }),
                "sample_every_n_epochs": ("INT", {
                    "default": 0, "min": 0, "max": 100, "step": 1,
                    "tooltip": "Generate sample images every N epochs. 0 = disabled."
                }),
                "sample_sampler": (["euler", "euler_a", "ddim", "dpmsolver++", "dpmsingle", "pndm", "lms"],
                                    {"default": "euler"}),
                "dry_run": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Generate config and command but don't actually launch training."
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("config_path", "command", "status_message")
    FUNCTION = "launch_training"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Always re-execute: this node launches an external process
        import time
        return time.time()

    def _find_python(self, sdscripts_path: str, custom_python: str = "") -> str:
        """Resolve which Python interpreter the training script will run on.

        Resolution order:
          1. ``custom_python`` from the launcher widget if the user
             explicitly set one.
          2. ``sys.executable`` (the Python that ComfyUI itself is
             running on, which is ``python_embeded/python.exe`` on
             Windows portable installs).

        Previously this method also auto-detected a ``venv/`` or
        ``.venv/`` subfolder inside sd-scripts and preferred that
        Python over ``sys.executable``. The intent was to support
        users who had followed kohya-ss' upstream guide (which
        creates a venv inside sd-scripts/), but in practice this
        caused a silent mismatch on ComfyUI portable installs:

          * SD-Scripts Manager runs ``pip install`` against
            ``sys.executable``, i.e. ``python_embeded/``.
          * If a stale ``sd-scripts/venv/`` exists from a previous
            manual setup, the launcher used that venv's Python
            instead, which has no ``accelerate``, ``transformers``,
            etc. installed.

        Users who actually want their own venv can still point the
        ``python_executable`` widget at it explicitly. The implicit
        detection was strictly harmful for the modal ComfyUI-portable
        + Manager workflow.
        """
        if custom_python and os.path.exists(custom_python):
            return custom_python
        return sys.executable

    def _find_training_script(self, sdscripts_path: str) -> str:
        """Find the appropriate training script for Anima LoRA."""
        # Check for dedicated Anima training script first
        candidates = [
            "anima_train_network.py",
            "sdxl_train_network.py",  # Some versions use this with anima flags
            "train_network.py",       # Generic fallback
        ]
        for script in candidates:
            path = os.path.join(sdscripts_path, script)
            if os.path.exists(path):
                return path

        # Default to train_network.py
        return os.path.join(sdscripts_path, "train_network.py")

    def _build_command(self, python_exe: str, training_script: str,
                       config_path: str, config_format: str,
                       config: dict, extra_args: str) -> list:
        """Build the full training command."""
        cmd = [python_exe, training_script]

        if config_format == "toml":
            cmd.extend(["--config_file", config_path])
        else:
            # Pass as CLI args
            cmd.extend(config_to_cli_args(config))

        # Add extra args.
        # Use shlex.split so quoted arguments with spaces survive intact —
        # `--logging_dir "C:\My Logs\run1"` should be 2 args, not 3.
        # posix=False keeps Windows-style backslashes as literal characters
        # rather than treating them as escape sequences. On non-Windows we
        # use the default posix mode for normal shell-style quoting.
        posix_mode = (platform.system() != "Windows")
        if extra_args.strip():
            for line in extra_args.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        cmd.extend(shlex.split(line, posix=posix_mode))
                    except ValueError:
                        # Unmatched quote etc. — fall back to naive split rather
                        # than abort the whole launch.
                        cmd.extend(line.split())

        return cmd

    # ─── Accelerate config + wrapper writers ───────────────────────────
    def _write_accelerate_config(self, target_dir: str, ts: str,
                                 mixed_precision: str = "bf16") -> str:
        """Write a single-process accelerate config alongside the wrapper.

        Why this exists: without an explicit accelerate config,
        ``Accelerator()`` falls back to whatever's in
        ``~/.cache/huggingface/accelerate/default_config.yaml`` — which
        is often left in multi-GPU / distributed state by other LoRA
        training tools (Forge LoRA UI, kohya_ss launcher GUI,
        OneTrainer, ...). On Windows where NCCL isn't compiled, the
        downstream ``init_process_group`` then crashes with
        ``ValueError: environment variable RANK expected, but not set``
        ~10 seconds into training. Our own config sidesteps the
        user's accelerate state entirely.

        Returns the absolute path so the wrapper can point
        ``ACCELERATE_CONFIG_FILE`` at it.
        """
        # Keep the accelerate config in sync with the training config's
        # precision - a bf16 accelerate config would silently override an
        # fp16 (old-GPU mode) run.
        mp = "fp16" if mixed_precision == "fp16" else "bf16"
        cfg_path = os.path.join(target_dir, f"_accelerate_config_{ts}.yaml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(
                "# Auto-generated by ComfyUI-Anima-LoRA-Training.\n"
                "# Forces single-process mode regardless of the system's\n"
                "# default accelerate config (which other LoRA tools\n"
                "# may have left in multi-GPU state).\n"
                "compute_environment: LOCAL_MACHINE\n"
                "distributed_type: 'NO'\n"
                "machine_rank: 0\n"
                "main_training_function: main\n"
                f"mixed_precision: {mp}\n"
                "num_machines: 1\n"
                "num_processes: 1\n"
                "rdzv_backend: static\n"
                "same_network: true\n"
                "use_cpu: false\n"
            )
        return cfg_path

    def _write_train_wrapper(self, wrapper_path: str, sdscripts_path: str,
                             train_script: str, accelerate_cfg_path: str) -> None:
        """Write the Python wrapper that runs the training script.

        The wrapper does three things before invoking runpy:
          1. Strip leaked torch.distributed env vars (RANK, LOCAL_RANK,
             ...) that a parent process — Forge, voice-cloning tool,
             a previous failed ``accelerate launch`` — may have left
             in the environment. Otherwise accelerate would try to
             init distributed mode and crash on Windows.
          2. Point accelerate at our own single-process config via
             ``ACCELERATE_CONFIG_FILE``.
          3. Inject sd-scripts into sys.path and chdir there (the
             original reason this wrapper exists — ComfyUI's embedded
             Python uses a ._pth file that interferes with env-var
             PYTHONPATH).
        """
        with open(wrapper_path, "w", encoding="utf-8") as wf:
            wf.write("import sys, os, runpy\n\n")
            wf.write("# Clear any leaked torch.distributed env vars from a\n")
            wf.write("# parent process — accelerate would otherwise try to\n")
            wf.write("# initialize distributed mode and crash on Windows\n")
            wf.write("# where NCCL isn't compiled.\n")
            wf.write("for _v in ('RANK', 'WORLD_SIZE', 'LOCAL_RANK',\n")
            wf.write("           'LOCAL_WORLD_SIZE', 'MASTER_ADDR',\n")
            wf.write("           'MASTER_PORT', 'TORCHELASTIC_RUN_ID'):\n")
            wf.write("    os.environ.pop(_v, None)\n\n")
            wf.write("# Force accelerate to use our single-process config\n")
            wf.write("# instead of whatever the user's accelerate setup did.\n")
            wf.write(f"os.environ['ACCELERATE_CONFIG_FILE'] = r\"{accelerate_cfg_path}\"\n\n")
            wf.write(f"sd_root = r\"{sdscripts_path}\"\n")
            wf.write("if sd_root not in sys.path:\n")
            wf.write("    sys.path.insert(0, sd_root)\n")
            wf.write("os.chdir(sd_root)\n")
            wf.write(f"sys.argv[0] = r\"{train_script}\"\n")
            wf.write(f"runpy.run_path(r\"{train_script}\", run_name=\"__main__\")\n")

    # Modules sd-scripts imports at top of anima_train_network.py /
    # train_network.py. If any of these is missing in the target
    # Python, training crashes immediately in the spawned terminal
    # window with `ModuleNotFoundError`, which beginners can't easily
    # debug — the wrapper window flashes the traceback, they don't
    # read it, they ask "why nothing happens". We probe before
    # spawning so the error surfaces in the Launcher node's status
    # output (visible in ComfyUI itself).
    # attn_mode value -> module that must be importable in the TRAINING python
    _ATTN_BACKEND_MODULES = {
        "xformers": "xformers",
        "flash": "flash_attn",
        "sageattn": "sageattention",
    }

    def _attention_backend_available(self, python_exe: str, attn_mode: str):
        """Check whether the requested attention backend is importable in
        the training Python. Returns True/False, or None when the probe
        itself failed (treat as unknown -> keep the user's choice).

        Why: sd-scripts imports xformers OPTIONALLY (xops = None when
        missing) and only crashes at step 1, mid-training, with
        `AttributeError: 'NoneType' object has no attribute
        'memory_efficient_attention'` (field report). Our low-VRAM
        presets default to xformers, so this must fail fast and fall
        back instead.
        """
        module = self._ATTN_BACKEND_MODULES.get(str(attn_mode).lower())
        if module is None:
            return True  # torch & friends: always available
        try:
            result = subprocess.run(
                [python_exe, "-c", f"import {module}"],
                capture_output=True, text=True, timeout=120,
            )
            return result.returncode == 0
        except Exception:
            return None

    def _check_sdscripts_dependencies(self, python_exe: str) -> tuple:
        """Probe the target Python for sd-scripts' startup dependencies.

        Returns ``(ok: bool|None, missing: list[str], stderr: str)``.
        None = inconclusive (probe timeout etc.) - warn but don't block.

        Delegates to utils.dep_check, which covers the FULL import chain
        of anima_train_network.py. The old 3-module list (accelerate,
        transformers, torch) let a missing `diffusers` through - training
        then crashed at import time inside the spawned window (field
        report, Aug 2026).
        """
        return probe_modules(python_exe, timeout=90)

    def _launch_in_new_window(self, cmd: list, sdscripts_path: str, title: str,
                              output_dir: str = "", timestamp: str = "",
                              mixed_precision: str = "bf16") -> tuple:
        """Launch training in a new command/terminal window."""
        system = platform.system()
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        # Sanitize title — used in CMD `title` directive on Windows and in the
        # AppleScript do-script string on macOS, both of which break on `"`.
        safe_title = _sanitize_window_title(title)
        # Unique suffix so concurrent training runs writing to the same
        # output_dir don't overwrite each other's wrapper/bat mid-execution.
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            if system == "Windows":
                # Write a temp .bat file to avoid Windows quoting nightmares
                # with spaces in paths
                bat_dir = output_dir if output_dir else sdscripts_path
                bat_path = os.path.join(bat_dir, f"_run_training_{ts}.bat")
                # Write a small Python wrapper that injects sd-scripts into
                # sys.path before running the training script.  This is more
                # reliable than PYTHONPATH because ComfyUI's embedded Python
                # uses a ._pth file that can interfere with env-var paths.
                wrapper_path = os.path.join(bat_dir, f"_train_wrapper_{ts}.py")
                # cmd[1] is the training script path
                train_script = cmd[1]
                # Write a single-process accelerate config and have the
                # wrapper point ACCELERATE_CONFIG_FILE at it (see
                # _write_accelerate_config for the rationale).
                accelerate_cfg = self._write_accelerate_config(bat_dir, ts, mixed_precision)
                self._write_train_wrapper(
                    wrapper_path, sdscripts_path, train_script, accelerate_cfg,
                )

                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write(f"@echo off\n")
                    f.write(f"title {safe_title}\n")
                    f.write(f"cd /d \"{sdscripts_path}\"\n")
                    f.write(f"set \"PYTHONPATH={sdscripts_path};%PYTHONPATH%\"\n")
                    f.write(f"echo Starting Anima LoRA Training...\n")
                    f.write(f"echo.\n")
                    # Use the wrapper script instead of the training script directly
                    f.write(f"\"{cmd[0]}\" \"{wrapper_path}\"")
                    for arg in cmd[2:]:  # skip cmd[1] (training script), wrapper handles it
                        if " " in arg or "=" in arg:
                            f.write(f" ^\n  \"{arg}\"")
                        else:
                            f.write(f" ^\n  {arg}")
                    f.write(f"\n\necho.\n")
                    f.write(f"echo Training finished with exit code %ERRORLEVEL%\n")
                    f.write(f"pause\n")

                # Launch the .bat in a new console window. Avoid shell=True so
                # the user-supplied output_name (embedded in `title`) cannot
                # affect command-line parsing. CREATE_NEW_CONSOLE gives us the
                # detached window without invoking `start`; the bat's own
                # `title` line provides the window title.
                creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                subprocess.Popen(
                    [bat_path],
                    cwd=sdscripts_path,
                    creationflags=creationflags,
                )
                return True, f"Launched in new CMD window.\nBatch file: {bat_path}"

            elif system == "Darwin":  # macOS
                # Use osascript to open Terminal. Both interpolated values are
                # escaped for AppleScript's string literal grammar — without
                # this, a `"` or `\` anywhere in the path or command breaks
                # the `do script "..."` parse.
                safe_path = _applescript_string_escape(sdscripts_path)
                safe_cmd = _applescript_string_escape(cmd_str)
                apple_script = f'''
                tell application "Terminal"
                    do script "cd \\"{safe_path}\\" && {safe_cmd}"
                    activate
                end tell
                '''
                subprocess.Popen(["osascript", "-e", apple_script])
                return True, f"Launched in new Terminal window"

            else:  # Linux
                # Terminal emulators only exist in a graphical session.
                # Headless environments (Google Colab, cloud notebooks,
                # remote servers, docker) have neither a display nor any
                # emulator - a user on Colab reported "training doesn't
                # start" because every spawn attempt below failed.
                has_display = bool(os.environ.get("DISPLAY")
                                   or os.environ.get("WAYLAND_DISPLAY"))
                if has_display:
                    terminals = [
                        ["gnome-terminal", "--", "bash", "-c"],
                        ["xfce4-terminal", "-e"],
                        ["konsole", "-e"],
                        ["xterm", "-e"],
                    ]
                    for term_cmd in terminals:
                        try:
                            full_term = term_cmd + [f"cd '{sdscripts_path}' && {cmd_str}; read -p 'Press Enter to close...'"]
                            subprocess.Popen(full_term, cwd=sdscripts_path)
                            return True, f"Launched in {term_cmd[0]}"
                        except FileNotFoundError:
                            continue

                # ── Headless fallback ──
                # No window possible: run training as a detached background
                # process and stream all output to a log file the user can
                # follow. Same wrapper hardening as the Windows path
                # (sys.path injection + single-process accelerate config).
                target_dir = output_dir if output_dir else sdscripts_path
                wrapper_path = os.path.join(target_dir, f"_train_wrapper_{ts}.py")
                accelerate_cfg = self._write_accelerate_config(target_dir, ts, mixed_precision)
                self._write_train_wrapper(
                    wrapper_path, sdscripts_path, cmd[1], accelerate_cfg,
                )
                log_path = os.path.join(target_dir, f"training_log_{ts}.txt")
                log_f = open(log_path, "w", encoding="utf-8")
                try:
                    proc = subprocess.Popen(
                        [cmd[0], wrapper_path] + list(cmd[2:]),
                        cwd=sdscripts_path,
                        stdout=log_f, stderr=subprocess.STDOUT,
                        start_new_session=True,  # survives ComfyUI restarts
                    )
                finally:
                    log_f.close()  # child holds its own copy of the fd
                reason = ("no graphical session" if not has_display
                          else "no terminal emulator installed")
                return True, (
                    f"No terminal window possible on this system ({reason}).\n"
                    f"Training is running in the BACKGROUND instead (PID {proc.pid}).\n"
                    f"\n"
                    f"Progress log: {log_path}\n"
                    f"Follow it live with:  tail -f \"{log_path}\"\n"
                    f"(On Colab/Jupyter: run  !tail -f \"{log_path}\"  in a cell,\n"
                    f"or open the file in the file browser and refresh.)"
                )

        except Exception as e:
            return False, f"Launch error: {str(e)}"

    def launch_training(self, *args, **kwargs):
        """ComfyUI entry point. Wraps the real implementation so the
        status message is ALWAYS visible: shown inline on the node
        (ui.text + js/launcher_status.js) and printed to the console.

        Why: a user reported 'training doesn't start, no error, only the
        toml appears'. The launcher had returned a perfectly good error
        (failed dependency pre-flight) into the status_message OUTPUT -
        which nothing in the stock workflows displays. Silent failure.
        """
        result = self._launch_training_impl(*args, **kwargs)
        status = result[2] if len(result) > 2 else ""
        for line in (status or "").splitlines():
            print(f"[AnimaTrainingLauncher] {line}", flush=True)
        return {"ui": {"text": (status,)}, "result": result}

    def _launch_training_impl(self, sdscripts_path: str, is_ready: bool,
                        model_config: dict, training_params: dict,
                        config_format: str = "toml",
                        python_executable: str = "",
                        extra_args: str = "",
                        resume_from: str = "",
                        sample_prompts: str = "",
                        sample_every_n_steps: int = 0,
                        sample_every_n_epochs: int = 0,
                        sample_sampler: str = "euler",
                        dry_run: bool = False) -> tuple:
        """Generate config and launch training."""

        messages = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if resume_from and resume_from.strip():
            messages.append(f"Resuming from: {resume_from.strip()}")

        # --- Validation ---
        if not is_ready:
            return ("", "", "ERROR: sd-scripts is not ready. Check the SD-Scripts Manager node.")

        if not model_config.get("is_valid", False):
            return ("", "", "ERROR: Model configuration is invalid. Check the Model Selector node.")

        if not training_params.get("train_data_dir"):
            return ("", "", "ERROR: train_data_dir is required.")

        if not training_params.get("output_dir"):
            return ("", "", "ERROR: output_dir is required.")

        # --- Dataset structure gate ---
        # Catch the classic "training found 0 images" failure BEFORE
        # spawning a terminal that dies with a cryptic sd-scripts error.
        # Hard errors block the launch; warnings are shown but don't.
        ds = check_dataset(training_params["train_data_dir"],
                           training_params.get("caption_extension", ".txt"))
        ds_report = "\n".join(format_dataset_report(ds))
        if not ds["ok"]:
            return ("", "", "ERROR: Your training folder is not set up the way "
                            "sd-scripts needs it - training would find 0 images "
                            "and stop.\n\n" + ds_report)
        if ds["warnings"]:
            messages.append(ds_report)

        # Coerce all numeric fields up-front. Guards against widget values that
        # arrived as strings via Primitive/Reroute nodes or workflow JSON edits.
        # Without this, downstream `if value > 0:` checks crash with TypeError,
        # or the TOML quotes the value and sd-scripts hands numpy a string.
        training_params = normalize_training_params(training_params)

        # --- Generate config ---
        output_dir = training_params["output_dir"]
        os.makedirs(output_dir, exist_ok=True)

        # Write sample prompts file if provided
        sample_prompts_path = ""
        if sample_prompts and sample_prompts.strip():
            prompts_lines = [l.strip() for l in sample_prompts.strip().split("\n") if l.strip()]
            if prompts_lines:
                sample_prompts_path = os.path.join(output_dir, "sample_prompts.txt")
                with open(sample_prompts_path, "w", encoding="utf-8") as f:
                    for line in prompts_lines:
                        f.write(line + "\n")
                messages.append(f"Sample prompts ({len(prompts_lines)}): {sample_prompts_path}")

        # Resolve the training Python early - the attention-backend check
        # below must probe the SAME interpreter that will run training.
        python_exe = self._find_python(sdscripts_path, python_executable)

        # --- Attention backend fallback ---
        # The low-VRAM presets request xformers, but xformers is not part
        # of sd-scripts' requirements. If it isn't importable, fall back
        # to standard PyTorch attention (SDPA) - similar memory behavior,
        # works everywhere, and split_attn keeps working with it.
        attn_mode = str(training_params.get("attn_mode", "torch")).lower()
        if not dry_run and attn_mode in self._ATTN_BACKEND_MODULES:
            available = self._attention_backend_available(python_exe, attn_mode)
            if available is False:
                training_params["attn_mode"] = "torch"
                messages.append(
                    f"Note: '{attn_mode}' attention is not installed in the "
                    f"training Python - using standard PyTorch attention "
                    f"instead (works everywhere, similar VRAM). To use "
                    f"{attn_mode}, install it: \"{python_exe}\" -m pip "
                    f"install {self._ATTN_BACKEND_MODULES[attn_mode]}"
                )

        config = generate_training_config(
            output_dir=output_dir,
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
            # Resume
            resume=resume_from.strip() if resume_from else "",
            save_state=True,
            # Sampling
            sample_every_n_steps=sample_every_n_steps,
            sample_every_n_epochs=sample_every_n_epochs,
            sample_prompts=sample_prompts_path,
            sample_sampler=sample_sampler,
            # Logging
            log_with=training_params.get("log_with", "tensorboard"),
            # seed is already coerced by normalize_training_params above.
            seed=training_params.get("seed", 42),
            max_data_loader_n_workers=training_params.get("max_data_loader_n_workers", 2),
        )

        # Write TOML config
        config_filename = f"training_config_{timestamp}.toml"
        config_path = os.path.join(output_dir, config_filename)
        write_toml_config(config, config_path)
        messages.append(f"Config saved: {config_path}")

        # --- Build command ---
        # (python_exe already resolved above, before the attention check)
        training_script = self._find_training_script(sdscripts_path)
        messages.append(f"Python: {python_exe}")
        messages.append(f"Script: {training_script}")

        # Pre-flight: verify sd-scripts dependencies are importable in the
        # Python we're about to launch with. Skipped in dry_run so the user
        # can still inspect the generated config and bat files even from a
        # not-yet-configured environment.
        if not dry_run:
            deps_ok, missing, deps_err = self._check_sdscripts_dependencies(python_exe)
            if deps_ok is None:
                # Probe couldn't decide (timeout / infrastructure error).
                # Warn but DON'T block - blocking on an unreliable probe
                # is worse than letting sd-scripts report a real problem.
                messages.append(f"Dependency check inconclusive ({deps_err}) - launching anyway.")
            elif not deps_ok:
                req_path = os.path.join(sdscripts_path, "requirements.txt")
                error = [
                    "ERROR: sd-scripts dependencies are not installed in the",
                    f"Python that would run training:",
                    f"  {python_exe}",
                    "",
                ]
                if missing:
                    error.append("Missing packages: " + ", ".join(pip_name(m) for m in missing))
                else:
                    error.append("Probe failed (see stderr below).")
                error.extend([
                    "",
                    "Fix (recommended): run the SD-Scripts Manager node with",
                    "  action = install_or_update",
                    "  install_requirements = True",
                    "and watch its status output — if you see 'pip install",
                    "failed', that's why dependencies are missing.",
                    "",
                    "Manual fix from a terminal:",
                    f'  "{python_exe}" -m pip install -r "{req_path}"',
                ])
                if deps_err:
                    # Tail, not head: the exception line sits at the END
                    # of a traceback.
                    error.extend(["", "Probe stderr (tail):", deps_err[-500:]])
                messages.append("")
                messages.append("\n".join(error))
                return (config_path, "", "\n".join(messages))
            if deps_ok:
                messages.append("Dependencies: OK (full sd-scripts import chain)")

        # Anima 2.9B / 3.8B have 40 / 52 DiT blocks; upstream sd-scripts assumes 28 and would drop the rest silently
        blocks = anima_blocks.patch(sdscripts_path)
        if blocks == "anchor missing":
            messages.append("WARNING: this sd-scripts version is unknown to the Anima block-count patch - Anima 2.9B / 3.8B would "
                            "train wrong; Anima 1.0 is fine.")
        elif blocks == "patched":
            messages.append("sd-scripts: Anima block-count patch applied (2.9B / 3.8B checkpoints load all their blocks)")

        cmd = self._build_command(
            python_exe, training_script, config_path,
            config_format, config, extra_args
        )
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        messages.append(f"Command: {cmd_str}")

        # --- Dry run mode ---
        if dry_run:
            messages.append("\nDRY RUN - Config generated but training NOT launched.")
            if platform.system() == "Windows":
                script_path = os.path.join(output_dir, f"launch_training_{timestamp}.bat")
                dr_wrapper = os.path.join(output_dir, f"_train_wrapper_{timestamp}.py")
                train_script = cmd[1]
                # Same accelerate-config hardening as the live launch path
                # so dry-run output is faithful to what the real run will do.
                dr_accelerate_cfg = self._write_accelerate_config(
                    output_dir, timestamp, config.get("mixed_precision", "bf16"))
                self._write_train_wrapper(
                    dr_wrapper, sdscripts_path, train_script, dr_accelerate_cfg,
                )
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(f"@echo off\n")
                    f.write(f"cd /d \"{sdscripts_path}\"\n")
                    f.write(f"set \"PYTHONPATH={sdscripts_path};%PYTHONPATH%\"\n")
                    f.write(f"\"{cmd[0]}\" \"{dr_wrapper}\"")
                    for arg in cmd[2:]:
                        if " " in arg or "=" in arg:
                            f.write(f" ^\n  \"{arg}\"")
                        else:
                            f.write(f" ^\n  {arg}")
                    f.write(f"\npause\n")
            else:
                script_path = os.path.join(output_dir, f"launch_training_{timestamp}.sh")
                with open(script_path, "w") as f:
                    f.write(f"#!/bin/bash\n")
                    f.write(f'cd "{sdscripts_path}"\n')
                    f.write(f"{cmd_str}\n")
                    f.write(f'echo "Training complete. Press Enter to close."\n')
                    f.write(f"read\n")
                os.chmod(script_path, 0o755)

            messages.append(f"Launch script saved: {script_path}")
            return (config_path, cmd_str, "\n".join(messages))

        # --- Launch training in a new terminal window ---
        title = f"Anima LoRA Training - {training_params.get('output_name', 'training')}"
        # Reuse the timestamp generated at the top of launch_training so the
        # wrapper/bat filenames line up with `training_config_{timestamp}.toml`.
        # models left on the GPU by earlier renders make the training spill into shared memory (80 s/step, test 23 Oct)
        try:
            import comfy.model_management as mm
            mm.unload_all_models()
            mm.soft_empty_cache()
        except Exception:
            pass
        success, msg = self._launch_in_new_window(
            cmd, sdscripts_path, title, output_dir, timestamp=timestamp,
            mixed_precision=config.get("mixed_precision", "bf16"),
        )
        messages.append(msg)

        if success:
            messages.append("\nTraining launched successfully!")
            if "BACKGROUND" not in msg:
                messages.append("Monitor the training in the terminal window.")
            messages.append(f"Output will be saved to: {output_dir}")
        else:
            messages.append("\nFailed to launch training. See error above.")
            messages.append("You can manually run the command shown above.")

        return (config_path, cmd_str, "\n".join(messages))
