# -*- coding: utf-8 -*-
"""Unit tests for freeze.freeze_item (tags -> frozen wording)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from freeze import freeze_item, freeze_items  # noqa: E402

# real tags of research_moss/out/freeze_test/p1_c0.png and p1_c1.png (21 Oct), scores rounded
C0 = [("1girl", .99), ("scarf", .95), ("jacket", .9), ("grey scarf", .7), ("denim jacket", .66), ("blue jacket", .6),
      ("black skirt", .55), ("open jacket", .5), ("pleated skirt", .45), ("black scarf", .4), ("skirt", .9)]
C1 = [("scarf", .96), ("checkered clothes", .6), ("checkered scarf", .55), ("plaid scarf", .38), ("blue jacket", .7), ("jacket", .9)]


class Freeze(unittest.TestCase):
    def test_one_colour_only(self):   # 21 Oct the test script made "a grey black scarf" out of both colour tags
        self.assertEqual(freeze_item("patterned scarf", C0), ("grey scarf", ["grey scarf"]))

    def test_pattern(self):
        self.assertEqual(freeze_item("patterned scarf", C1)[0], "checkered plaid scarf")

    def test_states_are_no_look(self):
        self.assertEqual(freeze_item("jacket", C0)[0], "blue denim jacket")
        self.assertNotIn("open", freeze_item("jacket", C0)[0])

    def test_nothing_found_keeps_wording(self):
        self.assertEqual(freeze_item("red beanie", C0), ("red beanie", []))

    def test_items(self):
        self.assertEqual(freeze_items(["patterned scarf", "skirt", ""], C0), {"patterned scarf": "grey scarf", "skirt": "black pleated skirt"})


if __name__ == "__main__":
    unittest.main()
