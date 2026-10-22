# Bundled copy

Source: https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler, commit 4490bd1f482e026674543386bb2a4d176da245b9 (24 Dec 2025),
Apache License 2.0 (see LICENSE). Bundled by the Fumika Image Studio plugin for its SeedVR2 upscaler.

Changes: none to the code. Left out of this copy: `docs/`, `example_workflows/`, `inference_cli.py` (not used inside ComfyUI).
The Python packages it needs are installed by Fumika from the plugin manifest (`python`), with the engine's torch / numpy /
transformers / opencv pinned; `opencv-python` from requirements.txt is not installed because the engine already has
`opencv-python-headless`.
