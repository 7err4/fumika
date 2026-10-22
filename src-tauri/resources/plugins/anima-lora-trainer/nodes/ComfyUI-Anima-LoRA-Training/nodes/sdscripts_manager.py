"""
ComfyUI Node: SD-Scripts Version Checker & Installer
Checks for sd-scripts installation, verifies version, and downloads/updates if necessary.
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path

try:
    from ..utils.dep_check import probe_modules, diagnose_modules, pip_name
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from utils.dep_check import probe_modules, diagnose_modules, pip_name


class AnimaSDScriptsManager:
    """
    Checks if sd-scripts is installed at the expected location (sibling to ComfyUI).
    Downloads or updates sd-scripts if necessary.
    Outputs the validated sd-scripts path for downstream nodes.
    """

    SDSCRIPTS_REPO = "https://github.com/kohya-ss/sd-scripts.git"
    MINIMUM_VERSION = "0.9.1"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["check_only", "install_or_update", "force_reinstall"],
                           {"default": "install_or_update"}),
                "branch": (["main", "dev"],
                           {"default": "main"}),
            },
            "optional": {
                "custom_sdscripts_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Override path to sd-scripts. Leave empty for auto-detection (sibling to ComfyUI)."
                }),
                "install_requirements": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Run pip install -r requirements.txt after cloning/updating."
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("sdscripts_path", "version", "status_message", "is_ready")
    FUNCTION = "manage_sdscripts"
    CATEGORY = "Anima LoRA Training"
    OUTPUT_NODE = False

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Always re-check: install/update status can change externally
        import time
        return time.time()

    def _get_default_sdscripts_path(self) -> str:
        """Resolve the default sd-scripts path as a subfolder of ComfyUI.

        This file lives at::

            <ComfyUI>/custom_nodes/ComfyUI-Anima-LoRA-Training/nodes/sdscripts_manager.py

        Walking up parents:
            ``.py``         -> ``nodes/``
            ``.parent``     -> pack root (``ComfyUI-Anima-LoRA-Training/``)
            ``.parent``     -> ``custom_nodes/``
            ``.parent``     -> ``<ComfyUI>/``

        Final layout: ``<ComfyUI>/sd-scripts/``. Previous versions of
        this function had misleading variable names that read as if the
        target was a sibling-to-ComfyUI directory; the computation in
        practice landed inside ComfyUI/, which is the layout we keep
        because it's what users in the wild already have.
        """
        this_file = Path(__file__).resolve()
        pack_root = this_file.parent.parent       # ComfyUI-Anima-LoRA-Training/
        custom_nodes_dir = pack_root.parent       # custom_nodes/
        comfyui_dir = custom_nodes_dir.parent     # ComfyUI/
        sdscripts_dir = comfyui_dir / "sd-scripts"
        return str(sdscripts_dir)

    def _get_version(self, sdscripts_path: str) -> str:
        """Try to determine the sd-scripts version from the repo."""
        version_file = os.path.join(sdscripts_path, "library", "train_util.py")
        setup_file = os.path.join(sdscripts_path, "setup.py")
        pyproject = os.path.join(sdscripts_path, "pyproject.toml")

        # Try git describe
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                capture_output=True, text=True, cwd=sdscripts_path, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().lstrip("v")
        except Exception:
            pass

        # Try git log for latest tag-like reference
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                capture_output=True, text=True, cwd=sdscripts_path, timeout=10
            )
            if result.returncode == 0:
                return f"git-{result.stdout.strip()[:7]}"
        except Exception:
            pass

        return "unknown"

    def _check_anima_support(self, sdscripts_path: str) -> bool:
        """Check if the sd-scripts version supports Anima training."""
        anima_doc = os.path.join(sdscripts_path, "docs", "anima_train_network.md")
        anima_module = os.path.join(sdscripts_path, "anima_train_network.py")

        # Also check for anima references in the training scripts
        train_network = os.path.join(sdscripts_path, "train_network.py")

        if os.path.exists(anima_doc) or os.path.exists(anima_module):
            return True

        # Fallback: grep for "anima" in train_network.py
        if os.path.exists(train_network):
            try:
                with open(train_network, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                    if "anima" in content:
                        return True
            except Exception:
                pass

        return False

    def _clone_sdscripts(self, sdscripts_path: str, branch: str) -> tuple:
        """Clone sd-scripts from GitHub."""
        try:
            result = subprocess.run(
                ["git", "clone", "--branch", branch, "--depth", "1",
                 self.SDSCRIPTS_REPO, sdscripts_path],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                return False, f"Git clone failed: {result.stderr}"
            return True, "Clone successful"
        except subprocess.TimeoutExpired:
            return False, "Git clone timed out after 5 minutes"
        except Exception as e:
            return False, f"Git clone error: {str(e)}"

    def _update_sdscripts(self, sdscripts_path: str, branch: str) -> tuple:
        """Pull latest changes for sd-scripts."""
        try:
            # Fetch and checkout the target branch
            subprocess.run(
                ["git", "fetch", "origin", branch],
                capture_output=True, text=True, cwd=sdscripts_path, timeout=120
            )
            subprocess.run(
                ["git", "checkout", branch],
                capture_output=True, text=True, cwd=sdscripts_path, timeout=30
            )
            result = subprocess.run(
                ["git", "pull", "origin", branch],
                capture_output=True, text=True, cwd=sdscripts_path, timeout=120
            )
            if result.returncode != 0:
                return False, f"Git pull failed: {result.stderr}"
            return True, "Update successful"
        except subprocess.TimeoutExpired:
            return False, "Git pull timed out"
        except Exception as e:
            return False, f"Git update error: {str(e)}"

    @staticmethod
    def _engine_requirements(sdscripts_path: str, req_file: str):
        """requirements.txt for the Fumika engine: packages the engine pins (fumika_constraints.txt next to ComfyUI's main.py:
        torch, transformers, numpy, safetensors, ...) keep the engine's version, and opencv-python is left out when cv2 is there
        already - the engine ships opencv-python-headless, a second OpenCV package would break it, and while ComfyUI runs its
        cv2.pyd is locked, so pip stopped at "access denied" and installed nothing after it (ftfy, bitsandbytes, ...;
        Fumika trainer test 23 Oct). Returns (requirements file, constraints file or None)."""
        import re
        cons = None
        # <ComfyUI>/custom_nodes/<pack>/nodes/this file -> <ComfyUI> (the engine runs with the folder above ComfyUI as cwd)
        comfy_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        for d in (comfy_root, os.path.dirname(os.path.abspath(sdscripts_path)), os.path.join(os.getcwd(), "ComfyUI")):
            c = os.path.join(d, "fumika_constraints.txt")
            if os.path.isfile(c):
                cons = c
                break
        norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()
        pinned = set()
        if cons:
            with open(cons, encoding="utf-8") as f:
                pinned = {norm(re.split(r"[=<>!~\[; ]", l.strip(), 1)[0]) for l in f if l.strip()}
        # independent of the constraints file: a second OpenCV next to the engine's breaks it (and its cv2.pyd is locked)
        try:
            import cv2  # noqa: F401
            pinned |= {"opencv-python", "opencv-contrib-python"}
        except Exception:
            pass
        if not pinned:
            return req_file, None
        keep = []
        with open(req_file, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            t = line.strip()
            name = norm(re.split(r"[=<>!~\[; ]", t, 1)[0]) if t and not t.startswith(("#", "-")) else ""
            if name and name in pinned:
                keep.append("# kept the engine's version: " + t + "\n")
            else:
                keep.append(line if line.endswith("\n") else line + "\n")
        out = os.path.join(sdscripts_path, "requirements_fumika.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.writelines(keep)
        return out, cons

    def _install_requirements(self, sdscripts_path: str) -> tuple:
        """Install sd-scripts Python requirements."""
        req_file = os.path.join(sdscripts_path, "requirements.txt")
        if not os.path.exists(req_file):
            return True, "No requirements.txt found, skipping"

        try:
            req, cons = self._engine_requirements(sdscripts_path, req_file)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req] + (["-c", cons] if cons else []),
                capture_output=True, text=True, cwd=sdscripts_path, timeout=600
            )
            if result.returncode != 0:
                # stderr can legitimately be empty/None depending on how the
                # host process was started - a field report showed the old
                # unguarded `result.stderr[:500]` turning the REAL pip error
                # into "'NoneType' object is not subscriptable".
                detail = ((result.stderr or "") + (result.stdout or "")).strip()
                return False, (f"pip install failed (exit code {result.returncode}):\n"
                               f"{detail[-800:] if detail else '(no output captured)'}")
            return True, "Requirements installed"
        except subprocess.TimeoutExpired:
            return False, "pip install timed out after 10 minutes"
        except Exception as e:
            return False, f"pip install error: {type(e).__name__}: {e}"

    def _install_packages(self, packages: list) -> tuple:
        """Install specific packages UNPINNED via pip.

        Used as fallback when `pip install -r requirements.txt` fails on a
        version pin that can't be satisfied - field case: sd-scripts pins
        safetensors==0.4.5, which has no prebuilt wheels for Python 3.13
        on Windows, so pip tries a Rust/MSVC source build and dies on
        machines without build tools. The unpinned current versions ship
        wheels for every supported Python and sd-scripts runs fine on
        them (ComfyUI itself uses far newer safetensors).
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", *packages],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                detail = ((result.stderr or "") + (result.stdout or "")).strip()
                return False, (f"pip install {' '.join(packages)} failed "
                               f"(exit code {result.returncode}):\n{detail[-500:]}")
            return True, f"Installed: {', '.join(packages)}"
        except Exception as e:
            return False, f"pip install error: {type(e).__name__}: {e}"

    def manage_sdscripts(self, action: str, branch: str,
                         custom_sdscripts_path: str = "",
                         install_requirements: bool = True) -> tuple:
        """Main entry point for the node."""

        sdscripts_path = custom_sdscripts_path.strip() if custom_sdscripts_path.strip() else self._get_default_sdscripts_path()
        messages = []
        is_installed = os.path.isdir(sdscripts_path) and os.path.exists(
            os.path.join(sdscripts_path, ".git")
        )

        # --- CHECK ONLY ---
        if action == "check_only":
            if not is_installed:
                return (sdscripts_path, "not_installed",
                        f"sd-scripts NOT found at: {sdscripts_path}", False)

            version = self._get_version(sdscripts_path)
            has_anima = self._check_anima_support(sdscripts_path)

            if not has_anima:
                return (sdscripts_path, version,
                        f"sd-scripts {version} found but does NOT support Anima. Update required.", False)

            return (sdscripts_path, version,
                    f"sd-scripts {version} found with Anima support at: {sdscripts_path}", True)

        # --- FORCE REINSTALL ---
        if action == "force_reinstall" and is_installed:
            # Sanity check: only rm if the directory actually looks like an
            # sd-scripts checkout. Guards against a typo in
            # `custom_sdscripts_path` silently nuking something unrelated —
            # `is_installed` only verifies a `.git/` exists, which is true of
            # any git repo.
            looks_like_sdscripts = (
                os.path.exists(os.path.join(sdscripts_path, "train_network.py"))
                or os.path.exists(os.path.join(sdscripts_path, "library", "train_util.py"))
            )
            if not looks_like_sdscripts:
                return (
                    sdscripts_path, "aborted",
                    f"Refused to force-reinstall: {sdscripts_path} does not look "
                    f"like an sd-scripts checkout (no train_network.py / "
                    f"library/train_util.py found). Verify your "
                    f"custom_sdscripts_path before retrying.",
                    False,
                )
            shutil.rmtree(sdscripts_path, ignore_errors=True)
            is_installed = False
            messages.append("Removed existing sd-scripts for fresh install.")

        # --- INSTALL OR UPDATE ---
        if not is_installed:
            messages.append(f"Cloning sd-scripts ({branch}) to: {sdscripts_path}")
            success, msg = self._clone_sdscripts(sdscripts_path, branch)
            messages.append(msg)
            if not success:
                return (sdscripts_path, "failed", "\n".join(messages), False)
        else:
            messages.append(f"Updating sd-scripts ({branch}) at: {sdscripts_path}")
            success, msg = self._update_sdscripts(sdscripts_path, branch)
            messages.append(msg)
            if not success:
                # Non-fatal: we can still try to use the existing version
                messages.append("Warning: Update failed, using existing version.")

        # Install requirements
        if install_requirements:
            messages.append("Installing Python requirements...")
            success, msg = self._install_requirements(sdscripts_path)
            messages.append(msg)

            # If pip failed, decide whether that actually matters by
            # IMPORTING the modules sd-scripts needs at startup. pip can
            # fail although everything is already installed (harmless) -
            # but previously a failed pip only produced a warning and the
            # node still reported is_ready=True, so users with genuinely
            # missing modules (field report: `diffusers`) sailed through
            # to a crash in the training window. Probe only on failure to
            # avoid paying a torch import on every healthy queue.
            if not success:
                deps_ok, missing, detail = probe_modules(sys.executable)
                if deps_ok is False:
                    # Per-module diagnosis: the combined probe stops at the
                    # first failure, which caused fix-one-find-the-next
                    # round trips in the field. This finds EVERYTHING at
                    # once and separates "missing" from "installed but
                    # broken" (e.g. a cv2 built for another numpy/Python).
                    missing, broken = diagnose_modules(sys.executable)

                    if missing:
                        # Self-heal: install ONLY the missing packages,
                        # unpinned. Sidesteps requirements pins that can't
                        # build on this Python (e.g. safetensors==0.4.5 on
                        # Python 3.13: no wheels, needs Rust+MSVC).
                        pkgs = [pip_name(m) for m in missing]
                        messages.append(f"Requirements install failed - installing the "
                                        f"missing package(s) directly: {', '.join(pkgs)}")
                        retry_ok, retry_msg = self._install_packages(pkgs)
                        messages.append(retry_msg)
                        if retry_ok and not broken:
                            deps_ok, missing, detail = probe_modules(sys.executable)
                        elif retry_ok:
                            missing = []  # installed; broken remains blocking

                if deps_ok is False:
                    messages.append("")
                    messages.append("DEPENDENCY CHECK FAILED - sd-scripts cannot start like this.")
                    if missing:
                        messages.append("Still missing: " + ", ".join(pip_name(m) for m in missing))
                        messages.append("Fix from a terminal:")
                        messages.append(f'  "{sys.executable}" -m pip install '
                                        + " ".join(pip_name(m) for m in missing))
                    if broken:
                        messages.append("Installed but BROKEN (crash on import):")
                        for mod, err in broken.items():
                            messages.append(f"  {pip_name(mod)}: {err}")
                        messages.append("Fix from a terminal (reinstalls a current version):")
                        for mod in broken:
                            messages.append(f'  "{sys.executable}" -m pip install '
                                            f'--upgrade --force-reinstall {pip_name(mod)}')
                    if not missing and not broken:
                        messages.append(f"Details: ...{detail[-400:]}")
                        messages.append("Fix from a terminal:")
                        messages.append(f'  "{sys.executable}" -m pip install -r '
                                        f'"{os.path.join(sdscripts_path, "requirements.txt")}"')
                    messages.append("then run this node again.")
                    return (sdscripts_path, self._get_version(sdscripts_path),
                            "\n".join(messages), False)
                elif deps_ok is None:
                    messages.append(f"Warning: pip failed and the dependency check was "
                                    f"inconclusive ({detail}) - training may not work.")
                else:
                    messages.append("All required packages are present - continuing. "
                                    "(The failed pin from requirements.txt is not needed at runtime.)")

        # Final check
        version = self._get_version(sdscripts_path)
        has_anima = self._check_anima_support(sdscripts_path)

        if has_anima:
            messages.append(f"sd-scripts {version} ready with Anima support.")
            return (sdscripts_path, version, "\n".join(messages), True)
        else:
            messages.append(f"sd-scripts {version} installed but Anima support not detected. "
                            "Ensure you are using the latest main branch.")
            return (sdscripts_path, version, "\n".join(messages), False)
