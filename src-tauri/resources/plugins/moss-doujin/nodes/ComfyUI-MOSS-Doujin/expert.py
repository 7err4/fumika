# -*- coding: utf-8 -*-
"""Expert settings of the EASY nodes: every value has "auto" = the tested recipe (quality: 50 steps, cfg 3, euler / sgm_uniform,
skip layer guidance on layer 22, negative against stray bubbles; fast: 8 steps turbo LoRA, cfg 1, euler / simple, no SLG, no
negative). No ComfyUI imports (unit tests)."""

AUTO = "auto"
NEGATIVE = "extra speech bubbles, gibberish text, watermark"


def sampling(o, slow):
    """o: node settings (missing keys = auto). slow: the 50-step quality mode is used.
    -> dict(steps, cfg, sampler, scheduler, slg (single layers string, "" = off), negative)"""
    g = lambda k: o.get(k, AUTO)
    steps = int(g("steps") if g("steps") not in (AUTO, None, "", 0) else (50 if slow else 8))
    cfg = float(g("cfg") if g("cfg") not in (AUTO, None, "", 0) else (3.0 if slow else 1.0))
    sampler = g("sampler") if g("sampler") not in (AUTO, None, "") else "euler"
    scheduler = g("scheduler") if g("scheduler") not in (AUTO, None, "") else ("sgm_uniform" if slow else "simple")
    slg = str(g("slg_layers")).strip()
    slg = ("22" if slow else "") if slg in (AUTO, "None", "") else "" if slg.lower() == "off" else slg
    neg = g("negative")
    neg = (NEGATIVE if slow else "") if neg in (AUTO, None) else "" if str(neg).strip().lower() == "off" else neg
    return {"steps": steps, "cfg": cfg, "sampler": sampler, "scheduler": scheduler, "slg": slg, "negative": neg}


def differs(o, slow):
    """names of the settings that are not auto (shown in the log, so a deliberate 'steps 12' is visible later)"""
    return [k for k in ("steps", "cfg", "sampler", "scheduler", "slg_layers", "negative") if o.get(k, AUTO) not in (AUTO, None, 0, "")]


def lora_list(text):
    """'[{"name": "a.safetensors", "strength": 0.8}]' -> [(name, strength)]; empty names, "none" and strength 0 are skipped"""
    import json
    if not text or not str(text).strip():
        return []
    out = []
    for e in json.loads(text):
        name, w = str(e.get("name", "")).strip(), float(e.get("strength", 1.0))
        if name and name != "none" and w:
            out.append((name, w))
    return out
