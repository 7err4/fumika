# -*- coding: utf-8 -*-
"""Unit tests for expert.sampling: auto = the tested recipes, overrides win."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from expert import NEGATIVE, differs, lora_list, sampling  # noqa: E402


class Expert(unittest.TestCase):
    def test_auto_is_the_tested_recipe(self):
        self.assertEqual(sampling({}, True), {"steps": 50, "cfg": 3.0, "sampler": "euler", "scheduler": "sgm_uniform", "slg": "22", "negative": NEGATIVE})
        self.assertEqual(sampling({"steps": 0, "cfg": 0.0, "sampler": "auto", "scheduler": "auto", "slg_layers": "auto", "negative": "auto"}, False),
                         {"steps": 8, "cfg": 1.0, "sampler": "euler", "scheduler": "simple", "slg": "", "negative": ""})

    def test_overrides(self):
        o = {"steps": 30, "cfg": 4.5, "sampler": "dpmpp_2m", "scheduler": "karras", "slg_layers": "20,22", "negative": "blurry"}
        self.assertEqual(sampling(o, True), {"steps": 30, "cfg": 4.5, "sampler": "dpmpp_2m", "scheduler": "karras", "slg": "20,22", "negative": "blurry"})
        self.assertEqual(sampling({"slg_layers": "off"}, True)["slg"], "")
        self.assertEqual(sampling({"slg_layers": "22"}, False)["slg"], "22")   # SLG on purpose in fast mode
        self.assertEqual(sampling({"negative": "off"}, True)["negative"], "")   # the app's empty field means auto, "off" = none
        self.assertEqual(differs(o, True), ["steps", "cfg", "sampler", "scheduler", "slg_layers", "negative"])
        self.assertEqual(differs({"steps": 0, "sampler": "auto"}, True), [])


    def test_lora_list(self):
        self.assertEqual(lora_list('[{"name": "a.safetensors", "strength": 0.8}, {"name": "none"}, {"name": "b", "strength": 0}, {"name": "c"}]'),
                         [("a.safetensors", 0.8), ("c", 1.0)])
        self.assertEqual(lora_list("[]"), []); self.assertEqual(lora_list(""), [])


if __name__ == "__main__":
    unittest.main()
