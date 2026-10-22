# -*- coding: utf-8 -*-
"""Unit tests for the SDXL trainer core (no ComfyUI, nothing is trained)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core  # noqa: E402


def make_ds(root, captions):
    d = os.path.join(root, "4_fumika"); os.makedirs(d)
    for i, c in enumerate(captions):
        open(os.path.join(d, f"{i}.png"), "wb").close()
        if c is not None:
            open(os.path.join(d, f"{i}.txt"), "w", encoding="utf-8").write(c)
    return d


class Core(unittest.TestCase):
    def test_dataset_check(self):
        with tempfile.TemporaryDirectory() as t:
            make_ds(t, ["fumika7, 1girl, black hair", "1girl, smile"])
            ok, rep, n = core.check_dataset(t, "fumika7")
            self.assertTrue(ok); self.assertEqual(n, 8); self.assertIn("1 captions do not start with the trigger", rep)
        with tempfile.TemporaryDirectory() as t:
            make_ds(t, ["a", None])
            self.assertFalse(core.check_dataset(t)[0])

    def test_toml_and_command(self):
        with tempfile.TemporaryDirectory() as t:
            make_ds(t, ["x"])
            toml = core.dataset_toml(t, 1024, 2)
            self.assertIn("shuffle_caption = true", toml); self.assertIn("keep_tokens = 1", toml); self.assertIn("num_repeats = 4", toml)
        cfg = dict(checkpoint="C:/m/Illustrious.safetensors", output_dir="C:/out", name="fumika", dim=32, alpha=16, lr=1e-4, optimizer="AdamW8bit",
                   save_every=2, seed=42, epochs=8, max_steps=0, train_te=False, v_pred=False)
        a = core.train_command(cfg)
        self.assertEqual(a[0], "sdxl_train_network.py")
        self.assertIn("--network_train_unet_only", a); self.assertIn("--min_snr_gamma", a); self.assertIn("--no_half_vae", a)
        self.assertEqual(a[a.index("--max_train_epochs") + 1], "8"); self.assertNotIn("--max_train_steps", a)
        b = core.train_command({**cfg, "train_te": True, "v_pred": True})
        self.assertNotIn("--network_train_unet_only", b); self.assertEqual(b[b.index("--text_encoder_lr") + 1], "5e-05")
        self.assertIn("--v_parameterization", b); self.assertIn("--zero_terminal_snr", b); self.assertNotIn("--min_snr_gamma", b)

    def test_lycoris_and_embedding(self):
        cfg = dict(checkpoint="C:/m/ill.safetensors", output_dir="C:/out", name="f", dim=16, alpha=8, lr=1e-4, optimizer="AdamW8bit",
                   save_every=2, seed=42, epochs=8, max_steps=0)
        a = core.train_command({**cfg, "network": "LoKr"})
        self.assertEqual(a[a.index("--network_module") + 1], "lycoris.kohya")
        self.assertEqual(a[a.index("--network_args") + 1], "algo=lokr")
        self.assertEqual(core.train_command({**cfg, "network": "LoRA"})[core.train_command({**cfg, "network": "LoRA"}).index("--network_module") + 1], "networks.lora")
        self.assertNotIn("--network_args", core.train_command(cfg))
        e = core.train_command({**cfg, "kind": "embedding", "token": "fumika7", "lr": 5e-3, "template": "style"})
        self.assertEqual(e[0], "sdxl_train_textual_inversion.py")
        self.assertEqual(e[e.index("--token_string") + 1], "fumika7"); self.assertEqual(e[e.index("--init_word") + 1], "woman")
        self.assertIn("--use_style_template", e); self.assertNotIn("--network_module", e)

    def test_sd_scripts_pick(self):
        with tempfile.TemporaryDirectory() as t:   # nothing installed -> its own folder
            self.assertEqual(core.pick_sd_scripts(t), os.path.join(t, "sd-scripts-sdxl"))


if __name__ == "__main__":
    unittest.main()
