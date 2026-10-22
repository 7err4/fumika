# -*- coding: utf-8 -*-
"""Unit tests for story.parse_page and layouts.page_json (no ComfyUI needed).   python -m unittest discover -s tests"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import layouts  # noqa: E402
from story import parse_page, split_speaker  # noqa: E402

CHARS = "Fumika: an adult manga artist, black ponytail\nSora: her editor, short silver hair, glasses\nMia: a tall courier, round human ears"
W, H = 1024, 1536


def texts(js):
    return [i for i in json.loads(js)["items"] if i["label"] == "text"]


def panel_caps(js):
    return [i["caption"] for i in json.loads(js)["items"] if i["label"] == "panel"]


def build(page, direction="ltr", layout=None):
    panels, bub, _ = parse_page(page, CHARS, direction=direction)
    lay = layout or {1: "full", 2: "2h", 3: "3a"}[len(panels)]
    return panels, bub, layouts.page_json("Style", lay, panels, bub, W, H, direction=direction)[0]


def side(item):
    """left / right / middle of a text item by its centre (abs_centralized: x = 0 is the page centre)"""
    y1, x1, y2, x2 = item["bbox"]; c = (x1 + x2) / 2
    return "middle" if abs(c) < 60 else "left" if c < 0 else "right"


class SpeakerSyntax(unittest.TestCase):
    def test_split(self):
        n = ["Fumika", "Sora"]
        self.assertEqual(split_speaker("Fumika: Seven pages?!", n), (["Fumika"], False, "Seven pages?!"))
        self.assertEqual(split_speaker("+fumika: By TOMORROW?!", n), (["Fumika"], True, "By TOMORROW?!"))
        self.assertEqual(split_speaker("Fumika & Sora: DEADLINE!!", n), (["Fumika", "Sora"], False, "DEADLINE!!"))
        # a colon is only a speaker when every name is in the character list
        self.assertEqual(split_speaker("Note: buy ink", n), ([], False, "Note: buy ink"))
        self.assertEqual(split_speaker("Fumika & Bob: hi", n), ([], False, "Fumika & Bob: hi"))
        self.assertEqual(split_speaker("Time is 3:00", n), ([], False, "Time is 3:00"))

    def test_old_syntax_unchanged(self):
        panels, bub, title = parse_page("Fumika at her desk | Nothing... | !BZZT\nCover art | #DEADLINE! | ##by Fumika", CHARS)
        self.assertEqual(panels[0], "Fumika (an adult manga artist, black ponytail) at her desk")
        self.assertEqual([b[:3] for b in bub], [(0, "Nothing...", "speech"), (0, "BZZT", "sfx"), (1, "DEADLINE!", "title"),
                                                (1, "by Fumika", "subtitle")])
        self.assertTrue(all(b[3] is None for b in bub)); self.assertTrue(title)

    def test_speaker_text_and_spec(self):
        _, bub, _ = parse_page("Sora and Fumika in the studio | Fumika: Seven pages?! | +Fumika: By TOMORROW?!", CHARS)
        self.assertEqual(bub[0][1], "Seven pages?!")
        self.assertEqual(bub[0][3], {"who": [("Fumika", "left")], "connected": False})
        self.assertEqual(bub[1][3], {"who": [("Fumika", "left")], "connected": True})

    def test_sides_from_first_speaker(self):
        panels, bub, _ = parse_page("Sora and Fumika in the studio | Fumika: Seven pages?! | Sora: You promised.", CHARS)
        self.assertTrue(panels[0].endswith("Fumika is on the left side of the panel, Sora on the right side."))
        self.assertEqual([b[3]["who"][0] for b in bub], [("Fumika", "left"), ("Sora", "right")])
        _, bub, _ = parse_page("Sora and Fumika in the studio | Fumika: Seven pages?! | Sora: You promised.", CHARS, direction="rtl")
        self.assertEqual([b[3]["who"][0] for b in bub], [("Fumika", "right"), ("Sora", "left")])

    def test_silent_character_gets_the_other_side(self):
        panels, bub, _ = parse_page("Fumika hands Sora the pages | Fumika: Done!", CHARS)
        self.assertIn("Fumika is on the left side of the panel, Sora on the right side.", panels[0])
        # full description only at the first mention
        self.assertEqual(panels[0].count("silver hair"), 1); self.assertEqual(panels[0].count("ponytail"), 1)

    def test_written_sides_win(self):
        panels, bub, _ = parse_page("Sora stands on the left, Fumika stands on the right | Fumika: Hi | Sora: Hi", CHARS)
        self.assertNotIn("side of the panel", panels[0])
        self.assertEqual([b[3]["who"][0] for b in bub], [("Fumika", "right"), ("Sora", "left")])
        panels, bub, _ = parse_page("Sora waits on the right side | Fumika: Hi", CHARS)
        self.assertEqual(bub[0][3]["who"], [("Fumika", "left")])
        self.assertTrue(panels[0].endswith(". Fumika (an adult manga artist, black ponytail) is on the left side of the panel."))

    def test_unmentioned_speaker_is_introduced(self):
        panels, _, _ = parse_page("Sora reads the pages | Sora: Hm. | Fumika: Well?", CHARS)
        self.assertIn("Fumika (an adult manga artist", panels[0])

    def test_single_character_no_side(self):
        panels, bub, _ = parse_page("Close-up of Fumika, panicking | Fumika: Seven pages by tomorrow?!", CHARS)
        self.assertEqual(panels[0], "Close-up of Fumika (an adult manga artist, black ponytail), panicking")
        self.assertEqual(bub[0][3]["who"], [("Fumika", None)])

    def test_three_characters(self):
        panels, bub, _ = parse_page("Fumika, Sora and Mia at the door | Mia: Delivery! | Fumika: Finally | Sora: Sign here", CHARS)
        self.assertTrue(panels[0].endswith("Mia is on the left side of the panel, Fumika on the right side and Sora in the middle."))


class PageJson(unittest.TestCase):
    def test_reading_order_ltr(self):
        # the 1.3 bug: first bubble top RIGHT for English text
        _, _, js = build("Fumika at her desk | Nothing... | Maybe...")
        t = texts(js)
        self.assertEqual([side(i) for i in t], ["left", "right"])
        self.assertLessEqual(t[0]["bbox"][0], t[1]["bbox"][0])

    def test_reading_order_rtl(self):
        _, _, js = build("Fumika at her desk | Nothing... | Maybe...", "rtl")
        self.assertEqual([side(i) for i in texts(js)], ["right", "left"])

    def test_rtl_mirrors_panels(self):
        _, _, ltr = build("A | x\nB | y\nC | z")
        _, _, rtl = build("A | x\nB | y\nC | z", "rtl")
        p_l = [i["bbox"] for i in json.loads(ltr)["items"] if i["label"] == "panel"]
        p_r = [i["bbox"] for i in json.loads(rtl)["items"] if i["label"] == "panel"]
        self.assertLess(p_l[1][1], 0); self.assertGreater(p_r[1][3], 0)   # layout 3a: panel 2 bottom-left vs bottom-right
        self.assertEqual(p_r[1][1], -p_l[1][3])

    def test_speaker_bubbles(self):
        _, _, js = build("Sora stands on the left side of the panel and Fumika on the right side | Fumika: Seven pages?! | Sora: You promised.")
        t = texts(js)
        self.assertEqual([side(i) for i in t], ["right", "left"])
        self.assertTrue(t[0]["caption"].endswith("its tail points down at Fumika on the right"))
        self.assertTrue(t[1]["caption"].endswith("its tail points down at Sora on the left"))
        # Sora's bubble is read after Fumika's -> it may not sit level with / above it on the side read first
        self.assertGreater(t[1]["bbox"][0], t[0]["bbox"][0])

    def test_connected(self):
        _, _, js = build("Sora and Fumika in the studio | Fumika: Seven pages?! | +Fumika: By TOMORROW?!")
        a, b = texts(js)
        self.assertEqual(side(a), side(b)); self.assertEqual(a["bbox"][1], b["bbox"][1])
        self.assertEqual(b["bbox"][0] - a["bbox"][2], 24)
        self.assertIn("connected to the speech bubble above it by a short neck, no tail of its own", b["caption"])

    def test_connected_without_previous_bubble_falls_back(self):
        _, _, js = build("Sora and Fumika | +Fumika: Hi")
        self.assertIn("its tail points down at Fumika on the left", texts(js)[0]["caption"])

    def test_together(self):
        _, _, js = build("Sora and Fumika shout | Sora & Fumika: DEADLINE!!")
        t = texts(js)[0]
        self.assertEqual(side(t), "middle")
        self.assertTrue(t["caption"].endswith("one bubble with two tails: one tail points down at Sora on the left, the other at Fumika on the right"))

    def test_no_overlap_and_inside_panel(self):
        _, _, js = build("Fumika, Sora and Mia talk | Fumika: a | Sora: b | Mia: c | Fumika: d | Sora & Mia: e\nB | x", layout="2h")
        d = json.loads(js); panel = d["items"][0]["bbox"]; t = texts(js)[:-1]   # the last item belongs to panel 2
        for i, a in enumerate(t):
            self.assertTrue(panel[0] <= a["bbox"][0] and a["bbox"][2] <= panel[2] and panel[1] <= a["bbox"][1] and a["bbox"][3] <= panel[3])
            for b in t[i + 1:]:
                self.assertFalse(layouts._overlap(a["bbox"], b["bbox"]), (a["text"], b["text"]))

    def test_boxes_match_json(self):
        panels, bub, _ = parse_page("Sora and Fumika | Fumika: a | Sora: b\nB | !BAM", CHARS)
        js, boxes = layouts.page_json("S", "2h", panels, bub, W, H)
        self.assertEqual(layouts.text_boxes_from_json(js, W, H), boxes)

    def test_narration(self):
        _, bub, _ = parse_page("Tokyo at night | >Tokyo, 2 a.m. | Fumika: So tired...", CHARS)
        self.assertEqual(bub[0][:3], (0, "Tokyo, 2 a.m.", "narration"))
        for d, corner in (("ltr", "left"), ("rtl", "right")):
            _, _, js = build("Fumika at her desk | >Tokyo, 2 a.m. | So tired...", d)
            n, sp = texts(js)
            self.assertEqual(side(n), corner)
            self.assertFalse(layouts._overlap(n["bbox"], sp["bbox"]))

    def test_three_tuple_bubbles_still_work(self):
        js, _ = layouts.page_json("S", "2h", ["a", "b"], layouts.parse_bubbles("1 | speech | hi\n2 | narration | Later"), W, H)
        self.assertEqual(len(texts(js)), 2)


if __name__ == "__main__":
    unittest.main()
