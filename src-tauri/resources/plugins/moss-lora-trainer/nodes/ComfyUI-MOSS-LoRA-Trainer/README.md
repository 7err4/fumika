# ComfyUI-MOSS-LoRA-Trainer

Train **MOSS-Image LoRAs** (characters, outfits, styles) from inside ComfyUI, then pick the best epoch from a grid.
It uses kohya **sd-scripts** (`moss_image_train_network.py`), installed into its own folder and Python environment, so your
ComfyUI Python stays untouched. The training runs in a separate console window, so ComfyUI stays usable.

## Easy mode (recommended)

**00_EASY_train_a_lora** — one node:
1. Make a dataset folder with sub-folders named `<repeats>_<name>` (e.g. `my_dataset/4_mychar`). Put the images in it, each
   with a `.txt` caption of the same name.
2. Enter the folder and a name. Run with `start = false` and read the report.
3. When it says READY, set `start = true` and run again.
   - **First time only:** the trainer installs itself, which takes 5–15 minutes. Run again when it's done.
   - The node picks the number of epochs from your dataset size, using the goal you set: quick test, normal or thorough.

**01_EASY_test_the_epochs** — one node: renders every saved file (plus "no LoRA") with your test prompts into one grid.

## Advanced mode

- **02_advanced_train:**
  - install / check
  - tag captions → sentence captions
  - dataset check
  - full config (rank, lr, optimizer, resolution, sample prompts, resume)
  - launch
  - status
- **03_advanced_epoch_grid:** the same grid with normal ComfyUI nodes (change sampler, size, strength…).

## Captions — the one thing that matters

MOSS reads **sentences**, not tag lists. The format that worked for the released LoRAs:

```
<rating sentence> <trigger>, <identity sentence>. <outfit sentence>. Scene details: <what happens>.
Safe image. ohwx, an adult woman in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in
her bangs, light-blue eyes. She wears a white oversized shirt with rolled-up sleeves, a black ribbon tie and a black pleated
skirt. Scene details: standing in a park, smiling, from the side.
```

- Use the **same identity sentence** in every caption, and the same one when you prompt later.
- The caption starts with a rating sentence picked from the image's WD tagger rating (`general` / `sensitive` /
  `questionable` / `explicit`). The sentences are MOSS-Image's own rating vocabulary and live in `ratings.json` -
  edit that file if your base model expects others.
- Have a Danbooru-tag dataset already? **MOSS Tag Captions to Sentences** converts it. It writes a new folder and leaves
  your original untouched.
- **Do not** use several caption variants per image (`---===---`). They break text-encoder caching; use a second
  subset folder instead.

## Settings (tested)

| | |
|---|---|
| LoRA rank / alpha | 32 / 16 |
| Optimizer | AdamW8bit, lr 1e-4, cosine, 50 warmup steps |
| Timesteps | sigma, logit-normal −1.09 / 0.95, shift 1.0 |
| Speed | bf16, gradient checkpointing, latents + text encoder cached, ~2 s/step at 1024² on an RTX 5090 |
| Samples per epoch | ~200 for a character → 8 epochs ≈ 1 h |

## Requirements

- ComfyUI with native MOSS-Image support, plus the models:
  - `moss_image_base_bf16.safetensors` — **train on Base**, not on a turbo or fine-tune
  - `qwen3.5_9b_int8_convrot.safetensors`
  - `flux2-vae.safetensors`
  - `kromoss_8steps_dmd_lora.safetensors` (for the epoch test)
- NVIDIA GPU. 32 GB is tested; 24 GB should work with batch 1; smaller cards are untested.
- git. `uv` is used when available (faster); otherwise Python's venv.
- **Close other GPU work while training.** Training and rendering at the same time does not fit.

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

## Install

Extract into `ComfyUI/custom_nodes/`, restart ComfyUI, open **Templates → ComfyUI-MOSS-LoRA-Trainer**.
sd-scripts is installed to `ComfyUI/sd-scripts-moss` on the first training start.

Copyright (C) 2026 7err4. Licensed under the GNU General Public License v3.0 (see LICENSE) - this pack runs inside
ComfyUI (GPL-3.0). Versions released before 21 Oct 2026 were published under MIT and stay MIT. Models have their own licenses (MOSS-Image: Apache 2.0).
