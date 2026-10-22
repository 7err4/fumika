# -*- coding: utf-8 -*-
"""Unit tests for the slider trainer core (no ComfyUI, nothing is trained)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core  # noqa: E402

BASE = dict(family="anima", mode="text", name="smile", positive="a woman, big smile", negative="a woman, frowning", neutral="a woman",
            targets="", anchors="", anchor_weight=0.5, pos_folder="", neg_folder="", pair_caption="", rank=8, alpha=4.0, lr=2e-4,
            guidance=3.0, steps=500, save_every=100, sample_prompt="", seed=42, v_pred=False,
            dit="D:/m/anima.safetensors", text_encoder="D:/m/qwen.safetensors", vae="D:/m/vae.safetensors", checkpoint="D:/m/ill.safetensors")


def folder(root, name, files):
    d = os.path.join(root, name); os.makedirs(d)
    for f in files:
        open(os.path.join(d, f), "wb").close()
    return d


class Core(unittest.TestCase):
    def test_check_text(self):
        ok, rep = core.check(BASE)
        self.assertTrue(ok, rep)
        self.assertFalse(core.check({**BASE, "negative": ""})[0])
        self.assertFalse(core.check({**BASE, "negative": BASE["positive"]})[0])
        self.assertIn("WARN", "\n".join(core.check({**BASE, "rank": 32})[1]))

    def test_check_images(self):
        with tempfile.TemporaryDirectory() as t:
            p = folder(t, "pos", ["a.png", "b.png", "notes.txt"]); n = folder(t, "neg", ["a.png"])
            ok, rep = core.check({**BASE, "mode": "images", "pos_folder": p, "neg_folder": n})
            self.assertTrue(ok); self.assertIn("positive end: 2 images", "\n".join(rep))
            self.assertIn("same names", "\n".join(core.check({**BASE, "family": "sdxl", "mode": "images", "pos_folder": p, "neg_folder": n})[1]))
            self.assertFalse(core.check({**BASE, "mode": "images", "pos_folder": p, "neg_folder": os.path.join(t, "nope")})[0])

    def test_anima_config(self):
        c = core.anima_config(BASE, "D:/out")
        self.assertEqual((c["mode"], c["positive"], c["rank"], c["guidance_scale"], c["save_every"]), ("guidance", "a woman, big smile", 8, 3.0, 100))
        self.assertNotIn("targets", c); self.assertNotIn("anchor", c)
        c = core.anima_config({**BASE, "targets": "a man\nan old woman | an old woman, grinning | an old woman, scowling\n", "anchors": "a cat\n\n"}, "D:/out")
        self.assertEqual(len(c["targets"]), 3)
        self.assertEqual(c["targets"][1], {"neutral": "a man", "positive": "a man, big smile", "negative": "a man, frowning"})
        self.assertEqual(c["targets"][2]["positive"], "an old woman, grinning")
        self.assertEqual(c["anchor"], ["a cat"])
        # an end that starts with the neutral prompt only adds its difference to another subject
        c = core.anima_config({**BASE, "neutral": "1girl, solo", "positive": "1girl, solo, big smile", "negative": "1girl, solo, frown",
                               "targets": "1girl, solo, outdoors"}, "D:/out")
        self.assertEqual((c["targets"][1]["positive"], c["targets"][1]["negative"]), ("1girl, solo, outdoors, big smile", "1girl, solo, outdoors, frown"))
        c = core.anima_config({**BASE, "mode": "images", "pos_folder": "D:/p", "neg_folder": "D:/n", "pair_caption": "1girl"}, "D:/out")
        self.assertEqual((c["mode"], c["pos_images"], c["neg_images"], c["pair_caption"]), ("image_pair", "D:/p", "D:/n", "1girl"))
        # every key must be an option of the bundled script (it warns about and ignores unknown keys)
        src = open(os.path.join(core.HERE, "train_slider_anima.py"), encoding="utf-8").read()
        for k in list(c) + ["targets", "anchor", "anchor_weight", "positive", "negative", "neutral", "sample_prompts"]:
            self.assertIn(f'"--{k}"', src, k)

    def test_aitk_config(self):
        j = core.aitk_config({**BASE, "family": "sdxl", "anchors": "a cat"}, "D:/loras/slider_training")
        p = j["config"]["process"][0]
        self.assertEqual((j["job"], p["type"], p["model"]["is_xl"], p["network"]["linear"], j["config"]["training_folder"]), ("train", "slider", True, 8, "D:/loras/slider_training"))
        self.assertEqual(p["slider"]["targets"][0]["target_class"], "a woman")
        self.assertEqual(p["slider"]["anchors"][0]["prompt"], "a cat")
        self.assertEqual(p["sample"]["prompts"][0], "a woman --m -2")
        j = core.aitk_config({**BASE, "family": "sdxl", "mode": "images", "pos_folder": "D:/p", "neg_folder": "D:/n", "v_pred": True}, "D:/x")
        p = j["config"]["process"][0]
        self.assertEqual((j["job"], p["type"], p["slider"]["datasets"][0]["pos_folder"], p["model"]["is_v_pred"]),
                         ("extension", "image_reference_slider_trainer", "D:/p", True))

    def test_yaml_roundtrip(self):
        import yaml
        with tempfile.TemporaryDirectory() as t:
            y = os.path.join(t, "s.yml"); core.write_yaml(core.anima_config(BASE, t), y)
            self.assertEqual(yaml.safe_load(open(y, encoding="utf-8"))["negative"], "a woman, frowning")


if __name__ == "__main__":
    unittest.main()
