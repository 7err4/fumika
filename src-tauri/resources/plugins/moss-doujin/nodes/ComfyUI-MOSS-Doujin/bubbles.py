# -*- coding: utf-8 -*-
"""Stray speech-bubble detection for rendered MOSS pages: closed contours that are mostly white inside and contain several small
letter-like blobs. A detected bubble that overlaps a prompted text box (+ margin) is kept, every other one is "stray"."""
import subprocess
import sys

import numpy as np

try:
    import cv2
except ImportError:   # fresh ComfyUI portable has no opencv: install the headless build once, else run without the bubble check
    try:
        print("[MOSS Doujin] opencv not found - installing opencv-python-headless (one time) ...")
        subprocess.check_call([sys.executable, "-s", "-m", "pip", "install", "opencv-python-headless"])
        import cv2
    except Exception as ex:   # noqa: BLE001
        cv2 = None
        print(f"[MOSS Doujin] could not install opencv ({ex}) - gibberish-bubble check disabled, pages still render")

AVAILABLE = cv2 is not None


def detect(gray, min_glyphs=4):
    if not AVAILABLE:
        return []
    H, W = gray.shape; A = H * W
    _, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    cnts, _ = cv2.findContours(255 - bw, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c); a = w * h
        if not (0.0012 * A < a < 0.07 * A and 0.3 < w / max(h, 1) < 4):
            continue
        if cv2.contourArea(c) < 0.85 * max(cv2.contourArea(cv2.convexHull(c)), 1) or cv2.contourArea(c) < 0.55 * a:
            continue
        mask = np.zeros((h, w), np.uint8); cv2.drawContours(mask, [c - [x, y]], -1, 255, -1)
        roi = gray[y:y + h, x:x + w][cv2.erode(mask, np.ones((5, 5), np.uint8)) > 0]
        if not (roi.size and roi.mean() > 205 and 0.01 < (roi < 110).mean() < 0.35):
            continue
        ink = ((gray[y:y + h, x:x + w] < 110) & (cv2.erode(mask, np.ones((7, 7), np.uint8)) > 0)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(ink)
        if sum(1 for k in range(1, n) if 6 < stats[k, cv2.CC_STAT_AREA] < 0.02 * w * h) >= min_glyphs:
            out.append((x, y, w, h, c))
    keep = []   # drop bubbles nested in a bigger one
    for b in sorted(out, key=lambda b: -b[2] * b[3]):
        if not any(b[0] >= k[0] - 4 and b[1] >= k[1] - 4 and b[0] + b[2] <= k[0] + k[2] + 4 and b[1] + b[3] <= k[1] + k[3] + 4 for k in keep):
            keep.append(b)
    return keep


def stray_mask(rgb, text_boxes, margin=60, dilate=14, min_glyphs=4):
    """rgb: HxWx3 uint8. Returns (mask uint8 0/255, prefilled rgb, number of stray bubbles, number of detected bubbles)."""
    if not AVAILABLE:
        return np.zeros(rgb.shape[:2], np.uint8), rgb.copy(), 0, 0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY); H, W = gray.shape
    found = detect(gray, min_glyphs)
    near = lambda b, t: not (b[0] > t[2] + margin or b[0] + b[2] < t[0] - margin or b[1] > t[3] + margin or b[1] + b[3] < t[1] - margin)
    stray = [b for b in found if not any(near(b, t) for t in text_boxes)]
    mask = np.zeros((H, W), np.uint8)
    for b in stray:
        cv2.drawContours(mask, [b[4]], -1, 255, -1)
    if stray and dilate:
        mask = cv2.dilate(mask, np.ones((dilate * 2 + 1, dilate * 2 + 1), np.uint8))
    prefilled = cv2.inpaint(rgb, mask, 9, cv2.INPAINT_TELEA) if stray else rgb.copy()
    return mask, prefilled, len(stray), len(found)
