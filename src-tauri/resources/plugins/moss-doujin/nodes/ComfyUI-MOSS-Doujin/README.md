# ComfyUI-MOSS-Doujin

Nodes and example workflows for rendering **whole manga / doujin pages in one generation** with **MOSS-Image** and its native
JSON layout prompts: panel borders, exact speech-bubble text, sound effects, title lettering, double-page spreads and fixed-camera
sequences.

## Nodes

| Node | What it does |
|---|---|
| **MOSS Doujin Character** | identity + outfit → one reusable character sentence. Using the *same* sentence on every page keeps a character consistent across 40+ pages. |
| **MOSS Doujin Page (JSON layout)** | layout preset + one panel description per line + one text item per line → the MOSS JSON prompt, plus width/height for the latent. |
| **MOSS Doujin Layout Preview** | draws panels (grey) and text boxes (red), so you can check a layout before spending GPU time. |
| **MOSS Stray Bubble Mask** | finds speech bubbles that were *not* prompted (gibberish) and outputs a mask + a pre-filled image for a local re-render. |
| **MOSS Pages to PDF** | saves a batch or list of pages as one PDF in the output folder. |
| **MOSS Doujin Freeze Look (WD tagger)** | reads the clothes on a finished page and turns vague items ("patterned scarf") into the wording the page shows ("grey checkered scarf"), so later pages of a scene draw the same pieces. Plain PyTorch port of the WD eva02-large tagger v3, runs on the CPU in about a second; no onnxruntime needed. Files in `models/wd_tagger/`: `wd-eva02-large-tagger-v3.safetensors` ([model.safetensors](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3)) and `wd-eva02-large-tagger-v3_tags.csv` (selected_tags.csv), Apache-2.0. |

### Page node input format

- **panels**: one description per line, in the order of the layout's panels. `{A}`–`{D}` are replaced by the character inputs.
- **text**: one text item per line, written as `panel | kind | text`.
  - `panel` starts at 1.
  - `\n` inside the text is a line break.
  - kinds:
    - `speech`: rounded bubble
    - `sfx`: big lettering in the panel
    - `narration`: box top-left
    - `box`: plain rectangular box, like many doujin artists use
    - `title`: logo lettering on covers
    - `subtitle`
    - `block`: one centred text block that fills the white area under a title (afterword, credits). Prevents the gibberish paragraphs MOSS otherwise writes into empty white space.
- **layouts**:
  - `full`
  - `2h`, `2v`
  - `3a` (wide top), `3b` (wide bottom), `3v`, `3s`
  - `4g` (2×2), `4b`
  - `5`
  - `splash2`
  - `spread_a`, `spread_b`: double-page spreads, use 2048×1536.

### EASY node story format (since v1.4)

One line per panel: `what happens | text | text`. `!text` = sound effect, `>text` = narration box (top corner that is read first), `#text` = title, `##text` = subtitle, anything else is a speech bubble.

- `| Fumika: Seven pages?!`: Fumika says it. The bubble sits on her side of the panel and its tail points at her.
- `| +Fumika: By TOMORROW?!`: a second bubble of Fumika, stacked under her previous one and joined to it by a short neck.
- `| Fumika & Sora: DEADLINE!!`: both say it. One centred bubble with one tail per speaker.
- A colon only marks a speaker when the name is in the character list, so `| Note: buy ink` stays plain text. Old stories without speakers keep working.
- **Sides:** when a panel has a speaker and at least two characters, the node adds "Fumika is on the left side of the panel, Sora on the right side." The first speaker gets the side that is read first. Sides you write yourself ("Sora stands on the left") win.
- **`reading_direction`:** `left to right` (default, for English text) or `right to left` (manga order: panel 1 and the first bubble start on the right, the layout is mirrored). Up to v1.3 the first bubble always sat top right, so English dialogue read backwards.
- Tested 22 Oct with 3 seeds each (left to right and right to left): sides, tails, joined bubbles and two-tail bubbles came out right 9 of 9.

Built-in rules (each one fixes a problem found in testing):
- **Silent panels:** every panel without text gets "No speech bubbles and no text in this panel". Otherwise MOSS fills empty space with gibberish bubbles.
- **Single text-free page:** a page that is one panel with no text does *not* get that note, because MOSS would print the sentence as a subtitle.
- **Extra bubbles:** `only_listed_text` adds "Only the listed text boxes, no other text."
- **Covers (EASY nodes, since v1.3):** a one-panel title page gets the positive sentence "The title logo (and the small subtitle) is the only lettering on the cover; everything else is pure illustration." Give it a subtitle with `##` in the story line (`| #DEADLINE! | ##by Fumika`): in a 3-seed test the subtitle plus that sentence made 3 of 3 covers clean, without them every cover got invented kanji, taglines or badges. Negative wording ("no tagline") makes it worse.
- **Summary note:**
  - **Spreads:** `A double-page spread: two manga pages side by side, the wide bottom panel runs across both pages.`
  - **Fixed camera:** `Fixed camera: all four panels show the same room from exactly the same camera angle and framing, only the people change.`

## Example workflows (`example_workflows/`)

1. **01 page turbo**: a 3-panel page with two characters, MOSS-Base + 8-step DMD turbo LoRA (8 steps, CFG 1, euler/simple). About 5 s per page on an RTX 5090.
2. **02 spread / fixed camera**: a double-page spread at 2048×1536 with a panel across the gutter.
3. **03 cover full mode**: a cover with title lettering in full mode: 50 steps, CFG 3, euler/sgm_uniform, SkipLayerGuidanceDiTSimple layer 22, real negative. Turbo mode often scrambles title words; full mode gets them right.
4. **04 clean stray bubbles**: load a rendered page and give the same page JSON. The bubble mask feeds a prefill, a masked 8-step re-render at denoise 0.55, and a composite back onto the original.

Each generation workflow has a bypassed **character LoRA** slot after the turbo LoRA. Pick your LoRA, un-bypass it and set the strength.
In the EASY nodes, `lora_2` and `lora_3` (since v1.1) add a second character or a style LoRA. Several LoRAs can fight each other: if faces or styles start to mix, lower the strengths to about 0.6-0.8.

Reference picture (since v1.2): connect a picture of the main character to `reference` and pick a CharRef edit LoRA in `reference_lora` - the pages draw her after the picture, no character LoRA needed. The picture replaces the written look of one character: `reference_character` names her (empty = the first line of the character list); her description is ignored while a picture is connected (since v1.3 - before, a different written look overruled the picture). Needs ComfyUI 0.42 or newer and the [ComfyUI-MOSS-Image-Ostris-Edit](https://github.com/ostris/ComfyUI-MOSS-Image-Ostris-Edit) nodes (MIT). One reference per page: it fits the main character; other characters come from their text.

## Models

- `moss_image_base_bf16.safetensors` (diffusion model)
- `qwen3.5_9b_int8_convrot.safetensors` (CLIPLoader, type `moss_image`)
- `flux2-vae.safetensors`
- `kromoss_8steps_dmd_lora.safetensors` (8-step turbo LoRA)

Needs a ComfyUI version with native MOSS-Image support. The gibberish check needs opencv. If it is missing (e.g. a fresh ComfyUI portable), the pack installs `opencv-python-headless` automatically on the first start; ComfyUI Manager does the same via requirements.txt.

## Tips from 40-page tests

- **Two people talking in one panel? Give both a line.** If only one has text, MOSS invents a gibberish bubble for the other on almost every seed.
- **Black-and-white style LoRAs: no colour words.** Describe the characters by shape (hair length, glasses, body, outfit type), not by colour ("red hair", "black blouse"). Colour words override the ink look.

- **Re-roll instead of fighting gibberish:** render dense pages with 2–3 seeds and keep the cleanest. The Stray Bubble Mask
  output `stray_count` is a usable score. Negative prompts with CFG 2 or full mode did **not** remove gibberish in tests.
- **Cleanest formats:**
  - big pages (1344×2048) and double-page spreads with few, short bubbles
  - 3–4 panels per page
  - ≤ 12 words per bubble
- **Fixed camera across pages:** keep the same seed and the same room/camera sentence. Room, furniture and window stay almost identical.
- **Style LoRAs** trained on text-heavy pages add extra boxes; lower the LoRA to ~0.8 and keep `only_listed_text` on.
- **Cleanup limits:** the cleanup works best on colour / flat pages. Dense screentone pages can keep grey smears; re-rolling is better there.

## License

Copyright (C) 2026 7err4. Licensed under the GNU General Public License v3.0 (see LICENSE) - this pack runs inside
ComfyUI (GPL-3.0). Versions released before 21 Oct 2026 were published under MIT and stay MIT. Models have their own licenses (MOSS-Image: Apache 2.0).

## Where the model files go

Put them anywhere inside the normal ComfyUI model folders; sub-folders and other file names are fine:

| File | Folder |
|---|---|
| MOSS-Image Base (or a MOSS fine-tune such as Kromoss) | `models/diffusion_models/` |
| Qwen3.5-9B text encoder | `models/text_encoders/` (or `models/clip/`) |
| FLUX.2 VAE | `models/vae/` |
| 8-step DMD turbo LoRA (optional, 6× faster) | `models/loras/` |

The easy nodes have `auto (find it by name)` preselected. They look for a file with `moss_image` / `qwen3.5` / `flux2` / `8step`
in its name. If yours is named differently, just pick it in the node's dropdown. Without the turbo LoRA, every page uses the
slower 50-step mode.


**Downloads** (right-click → save into the folder in brackets):
- MOSS-Image Base: [bf16, 24 GB+ VRAM](https://huggingface.co/Comfy-Org/MOSS-Image/resolve/main/diffusion_models/moss_image_base_bf16.safetensors) or [int8, smaller GPUs](https://huggingface.co/Comfy-Org/MOSS-Image/resolve/main/diffusion_models/moss_image_base_int8_convrot.safetensors) (`models/diffusion_models`)
- [Qwen3.5-9B text encoder](https://huggingface.co/Comfy-Org/MOSS-Image/resolve/main/text_encoders/qwen3.5_9b_int8_convrot.safetensors) (`models/text_encoders`)
- [FLUX.2 VAE](https://huggingface.co/Comfy-Org/MOSS-Image/resolve/main/vae/flux2-vae.safetensors) (`models/vae`)
- [8-step turbo LoRA](https://huggingface.co/lodestones/Kromoss/resolve/main/8-steps-dmd-lora.safetensors) (`models/loras`)

## Changelog
- v1.6: `loras` input in the EASY nodes - any number of further LoRAs as a JSON list `[{"name", "strength"}]`.
- v1.5: expert overrides in the EASY nodes (`sampler`, `scheduler`, `steps`, `cfg`, `slg_layers`, `negative`; auto / 0 = the tested recipe, pixel-identical to v1.4). karras / exponential give block artefacts on MOSS.
- v1.4: freeze-look node (WD tagger); `>` narration boxes in the EASY story format; speakers per bubble (`Name:`, `+Name:`, `A & B:`), bubbles on the speaker's side, `reading_direction` setting (fixes the right-to-left bubble order of English pages).
- v1.3: covers without invented text (subtitle + positive sentence); the reference picture wins over the written look.
- v1.2: optional reference picture (CharRef) in the EASY nodes.
- v1.1: EASY nodes take up to 3 LoRAs (`character_lora`, `lora_2`, `lora_3`, each with its own strength). Old workflows keep working.
- v1.0: first release.
