# -*- coding: utf-8 -*-
"""Unit tests for fit() and resolve()."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodes import crop_box, fit, parse_loras, resolve, target_short, work_size  # noqa: E402


class Fit(unittest.TestCase):
    def test_scale_and_snap(self):
        self.assertEqual(fit(1024, 1536, scale=1.25), (1280, 1920, None))
    def test_cap_keeps_ratio(self):
        w, h, _ = fit(1024, 1536, scale=2.0, max_side=2048)
        self.assertEqual(h, 2048); self.assertEqual(w, 1360)               # 1365.3 rounded down to a multiple of 16
    def test_cover_crop(self):
        w, h, box = fit(1000, 500, 512, 512)
        self.assertEqual((w, h), (512, 512)); self.assertEqual(box, (250, 0, 750, 500))
    def test_target_short(self):
        self.assertEqual(target_short(1024, 1536, 2.0), 2048)
        self.assertEqual(target_short(1000, 700, 1.5), 1056)   # 1050 -> nearest multiple of 16

    def test_odd_sizes_snap(self):
        self.assertEqual(fit(1001, 777)[:2], (992, 768))


class Inpaint(unittest.TestCase):
    def test_crop_box(self):
        self.assertEqual(crop_box((100, 200, 300, 260), 1024, 1536, 32, True), (68, 168, 332, 292))
        self.assertEqual(crop_box((0, 0, 50, 50), 1024, 1536, 32, True), (0, 0, 82, 82))          # clamped at the edge
        self.assertEqual(crop_box((100, 200, 300, 260), 1024, 1536, 32, False), (0, 0, 1024, 1536))
        self.assertEqual(crop_box(None, 1024, 1536, 32, True), (0, 0, 1024, 1536))                # empty mask: whole picture
        self.assertEqual(crop_box((500, 500, 502, 501), 1024, 1536, 0, True), (500, 500, 516, 516))

    def test_work_size(self):
        self.assertEqual(work_size(264, 124, 1024), (1024, 480))
        self.assertEqual(work_size(1024, 1536, 1536), (1024, 1536))


class Loras(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_loras('[{"name": "a.safetensors", "strength": 0.8}, {"name": "", "strength": 1}, {"name": "b", "strength": 0},'
                                     ' {"name": "none"}, {"name": "c.safetensors"}]'), [("a.safetensors", 0.8), ("c.safetensors", 1.0)])
        self.assertEqual(parse_loras(""), []); self.assertEqual(parse_loras("[]"), [])


class Resolve(unittest.TestCase):
    def test_inside_only(self):
        with tempfile.TemporaryDirectory() as d:
            out, inp = os.path.join(d, "out"), os.path.join(d, "in"); os.makedirs(os.path.join(out, "sub")); os.makedirs(inp)
            open(os.path.join(out, "sub", "a.png"), "wb").close(); open(os.path.join(d, "secret.txt"), "w").close()
            self.assertTrue(resolve("output:sub/a.png", out, inp).endswith("a.png"))
            for bad in ("output:../secret.txt", "output:", "web:x.png", "input:sub/a.png"):
                with self.assertRaises(ValueError):
                    resolve(bad, out, inp)


if __name__ == "__main__":
    unittest.main()
