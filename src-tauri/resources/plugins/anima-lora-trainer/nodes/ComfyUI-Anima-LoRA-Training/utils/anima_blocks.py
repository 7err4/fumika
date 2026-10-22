# -*- coding: utf-8 -*-
"""Layer-expanded Anima (2.9B: 40 DiT blocks, 3.8B: 52) for kohya sd-scripts. Upstream builds the DiT with a fixed 28 blocks
and loads the weights with strict=False, so a bigger checkpoint would train SILENTLY WRONG (the extra blocks are dropped).
patch(sd) inserts a block count read from the checkpoint into library/anima_utils.py - idempotent, run before every launch.
Only top-level `blocks.N.` keys count: the text adapter (`llm_adapter.blocks.N`) and the 3.8B Semantic Connector have their own."""
import os

MARK = "# Fumika: layer-expanded Anima"
ANCHOR = "    with init_empty_weights():\n        model = anima_models.Anima(**dit_config)"
PATCH = '''    # Fumika: layer-expanded Anima (2.9B: 40, 3.8B: 52 blocks) - the block count comes from the checkpoint, not a fixed 28
    import re as _re
    from safetensors import safe_open as _safe_open
    with _safe_open(dit_path, framework="pt") as _f:
        _ids = {int(_m.group(1)) for _k in _f.keys() if (_m := _re.match(r"(?:net\\.|model\\.diffusion_model\\.)?blocks\\.(\\d+)\\.", _k))}
    if _ids:
        dit_config["num_blocks"] = max(_ids) + 1
        logger.info(f"Anima: {dit_config['num_blocks']} DiT blocks in {dit_path}")
'''


def patch(sd):
    """-> "patched" | "already" | "no anima_utils" | "anchor missing" (an sd-scripts version this patch does not know)"""
    p = os.path.join(sd, "library", "anima_utils.py")
    if not os.path.isfile(p):
        return "no anima_utils"
    s = open(p, encoding="utf-8").read()
    if MARK in s:
        return "already"
    if ANCHOR not in s:
        return "anchor missing"
    open(p, "w", encoding="utf-8").write(s.replace(ANCHOR, PATCH + ANCHOR, 1))
    return "patched"
