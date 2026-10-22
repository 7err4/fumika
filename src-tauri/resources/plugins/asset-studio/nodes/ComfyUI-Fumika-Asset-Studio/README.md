# ComfyUI Fumika Asset Studio

Character assets for **MOSS-Image**, each in one image with a JSON layout prompt, so the same character appears in every cell:

| Asset | Size | Cells |
|---|---|---|
| expressions | 1536x1536 | 3x3 bust portraits, one expression each (visual novel sprites) |
| outfits | 1536x1152 | 4 full-body views, one outfit each |
| turnaround | 1536x1152 | front / side / back |
| profile | 1024x1536 | figure, face close-up, 2 detail insets, stats, quote, name plate |
| card | 1024x1536 | framed item / codex card with illustration, title and text |
| chibi | 1536x1024 | 6 chibi stickers |
| pixel | 1536x768 | experimental: 4-frame 16-bit pixel-art walk cycle (varies a lot by seed, render several) |

## Nodes

- **Fumika Asset Sheet**: asset type + character line (`Name: looks and outfit`) + style + optional `fields` JSON
  (`expressions`, `outfits`, `views`, `stats`, `quote`, `name`, `insets`, `card_title`, `card_text`, `card_art`, `chibi`; lists one
  entry per line). Outputs the prompt, the cell boxes (JSON, for cutting) and the image size.
- **Fumika Asset Encode (+ reference)**: positive / negative conditioning. With a reference picture the prompt goes through the MOSS edit
  encoder ("Same character and art style as Picture 1.") - needs [ComfyUI-MOSS-Image-Ostris-Edit](https://github.com/ostris/ComfyUI-MOSS-Image-Ostris-Edit)
  (ComfyUI 0.42+), the edit model patch and a CharRef LoRA.
- **Fumika Sprite Cutout**: transparent background with ComfyUI's native background removal (BiRefNet, `models/background_removal`,
  e.g. [Comfy-Org/BiRefNet](https://huggingface.co/Comfy-Org/BiRefNet), MIT) and one trimmed PNG per cell.

Render with MOSS full mode: 50 steps, cfg 3, euler / sgm_uniform, SkipLayerGuidance on single layer 22. A character LoRA works on all
assets; for pixel art keep it at 0.4 or lower, stronger it overrides the pixel style.

Copyright (C) 2026 7err4. Licensed under the GNU General Public License v3.0 (see LICENSE) - this pack runs inside ComfyUI (GPL-3.0).
Models have their own licenses (MOSS-Image: Apache 2.0, BiRefNet: MIT).
