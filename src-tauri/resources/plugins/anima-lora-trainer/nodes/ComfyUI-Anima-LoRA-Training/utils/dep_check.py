"""
Shared sd-scripts dependency probe.

Used by BOTH the SD-Scripts Manager (after pip install, to verify the
install actually worked before reporting is_ready=True) and the Training
Launcher (pre-flight before spawning the training window).

Why the module list is what it is: a field report showed the old 3-module
probe (accelerate/transformers/torch) passing while `diffusers` was
missing — training then crashed at import time inside the terminal
window. This list was derived by statically tracing the module-level
imports along the anima_train_network.py -> library/* chain in sd-scripts
main. Optional/guarded imports (bitsandbytes, xformers, wandb, deepspeed,
prodigyopt, ...) are deliberately excluded: sd-scripts starts without them.
"""

import subprocess

# Import-name order: cheap modules first, heavy ones last (a missing cheap
# module fails fast without paying the torch import).
REQUIRED_MODULES = (
    # ftfy: library/clip_tokenizer.py imports it at module level (Fumika trainer test 23 Oct: missing -> crash at start)
    "toml", "ftfy", "einops", "voluptuous", "imagesize", "packaging", "rich",
    "tqdm", "numpy", "PIL", "cv2", "safetensors", "huggingface_hub",
    "torch", "torchvision", "accelerate", "transformers", "diffusers",
)

# import name -> pip package name, where they differ (for fix-it messages)
PIP_NAMES = {
    "PIL": "pillow",
    "cv2": "opencv-python",
}


def pip_name(module: str) -> str:
    return PIP_NAMES.get(module, module)


def probe_modules(python_exe: str, timeout: int = 90):
    """Probe `python_exe` for all REQUIRED_MODULES in one subprocess.

    Returns (ok, missing, detail):
      ok = True   -> everything imports
      ok = False  -> something is missing/broken; `missing` has import
                     names when parseable, `detail` the stderr tail
      ok = None   -> probe itself failed (timeout etc.) - inconclusive,
                     callers should warn but not block on this
    """
    probe_code = "; ".join(f"import {m}" for m in REQUIRED_MODULES)
    try:
        result = subprocess.run(
            [python_exe, "-c", probe_code],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return True, [], ""
        stderr = result.stderr or result.stdout or ""
        missing = [
            m for m in REQUIRED_MODULES
            if (f"No module named '{m}'" in stderr
                or f'No module named "{m}"' in stderr)
        ]
        return False, missing, stderr.strip()[-800:]
    except subprocess.TimeoutExpired:
        return None, [], f"Dependency probe timed out after {timeout}s (slow torch import?)."
    except FileNotFoundError:
        return False, [], f"Python executable not found: {python_exe}"
    except Exception as e:  # probe infrastructure failed -> inconclusive
        return None, [], f"Dependency probe error: {type(e).__name__}: {e}"


def diagnose_modules(python_exe: str, timeout_each: int = 120):
    """Per-module diagnosis for when the combined probe failed.

    The combined probe stops at the FIRST failing import, which led to
    fix-one-find-the-next loops in the field (voluptuous -> imagesize ->
    broken cv2, three round trips). This checks every module separately
    and classifies the failures:

    Returns (missing, broken):
      missing: list of import names that raise ModuleNotFoundError for
               themselves -> installable
      broken:  dict {import_name: last_error_line} for modules that are
               installed but crash on import (e.g. an opencv-python
               built for a different numpy/Python) -> need reinstall,
               not install

    Only call this after probe_modules returned False - it pays one
    subprocess per module (the torch import alone can take a while).
    """
    missing, broken = [], {}
    for m in REQUIRED_MODULES:
        try:
            r = subprocess.run(
                [python_exe, "-c", f"import {m}"],
                capture_output=True, text=True, timeout=timeout_each,
            )
        except Exception as e:
            broken[m] = f"probe failed: {type(e).__name__}"
            continue
        if r.returncode == 0:
            continue
        err = (r.stderr or r.stdout or "").strip()
        last = err.splitlines()[-1].strip() if err else "unknown error"
        if (f"No module named '{m}'" in err) or (f'No module named "{m}"' in err):
            missing.append(m)
        else:
            broken[m] = last[:200]
    return missing, broken
