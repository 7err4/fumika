# ComfyUI-Anima-LoRA-Training

A ComfyUI custom node pack for training LoRA models on the **Anima** architecture using [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts).

Train Anima LoRAs / LoKr / LoHa directly from ComfyUI with zero command-line knowledge required. Works on GPUs from 6 GB up.

## Features

- **One-click model download** from HuggingFace (always grabs the latest release of your chosen Anima variant: base / aesthetic / turbo — deprecated preview builds are never selected)
- **Automatic sd-scripts installation** and updates
- **Wizard mode** - answer 5 questions, get optimal training parameters
- **Low-VRAM presets** - tiers from 6 GB up to 24 GB+. Smaller cards train slower, not worse
- **Live VRAM estimate** - the VRAM Estimator node shows the expected memory cost *while you edit*, before you ever click Run, with a bar chart of what uses the memory and concrete suggestions when it won't fit
- **Dataset check** - your training folder is validated (structure, captions, repeats) with plain-language fixes; the Launcher refuses to start a run that would find 0 images
- **Everything is tweakable** - presets are starting points, not locks. Override any value with the wizard's force_* fields or the manual override nodes
- **Annotated config preview** - see your full TOML config with educational parameter descriptions
- **Resume training** from saved checkpoints
- **Sample image generation** during training
- **Cross-platform** - Windows, Linux, macOS

## Included Nodes

| Node | Description |
|------|-------------|
| **Model Downloader (Anima)** | Downloads the Anima DiT (base/aesthetic/turbo, latest version auto-detected), Qwen3 text encoder, and VAE from HuggingFace |
| **SD-Scripts Manager** | Checks, installs, and updates kohya-ss/sd-scripts |
| **Model Selector** | Scans ComfyUI model folders and picks your base model, text encoder, and VAE |
| **Training Wizard** | Questionnaire-driven auto-configuration (subject type, dataset size, VRAM, quality) with force_* overrides for every key parameter |
| **Basic Parameters** | Manual core training settings (rank, LR, epochs, batch size) |
| **Advanced Parameters** | Optional overrides (dropout, noise offset, regex patterns, LoRA+) |
| **Memory Optimizer** | VRAM tuning (caching, precision, block swapping, attention mode) |
| **Config Preview** | Shows the dataset check and the full annotated TOML config inline on the node |
| **VRAM Estimator** | Live memory estimate with bar chart, fits/OOM verdict, dataset status, and suggestions - updates as you edit, no run needed |
| **Training Launcher** | Validates the dataset, generates the config, and launches training in a new terminal window |

## Installation

1. Extract this folder into `ComfyUI/custom_nodes/`
2. Restart ComfyUI (fully - close the console and relaunch)

No pip dependencies required - the pack uses only Python standard library.

## Quick Start

1. Load `example_workflow_wizard.json` from the node pack folder
2. Run the workflow once - it will download sd-scripts and Anima model files automatically
3. Set your `train_data_dir` and `output_dir` paths
4. Answer the 5 wizard questions (subject, dataset size, resolution, VRAM, quality)
5. Watch the VRAM Estimator node - it shows whether your settings fit your card *before* you start
6. Set `dry_run` to `false` and run - training launches in a new terminal window

## Dataset Preparation

sd-scripts requires your training data to follow this folder structure:

```
train_data_dir/
  <repeats>_<concept>/
      image1.png
      image1.txt        <- matching caption file
      image2.jpg
      image2.txt
```

**Naming convention:**
- `<repeats>` = how many times each image is seen per epoch (e.g. `10`)
- `<concept>` = your trigger word (e.g. `ohwx`)
- Example: `10_ohwx/` means 10 repeats with trigger word "ohwx"

**Caption files (.txt):**
Each image needs a matching `.txt` file with a one-line description:
```
ohwx, a woman with red hair, sitting on a bench, park background
```

**The pack checks this for you.** The wizard summary, Config Preview, and VRAM Estimator all show a dataset report: images per folder, steps per epoch, missing captions, and the two classic mistakes - images placed directly in `train_data_dir` (they would be silently ignored) and subfolders without the `10_` repeats prefix (they would be silently skipped). The Training Launcher blocks the run entirely if the folder is broken, instead of opening a terminal that dies with a cryptic error.

## GPU Memory (VRAM)

Pick your card size in the wizard and it configures safe starting settings. **Presets are starting points, not locks** - the summary shows exactly what each preset set, and everything can be changed (force_* fields on the wizard, or a Memory Optimizer node).

| Preset | Training speed | Recommended max image size |
|--------|---------------|---------------------------|
| 6 GB (minimum) | much slower | 768px |
| 8 GB (low) | slower | 1024px |
| 10 GB | a bit slower | 1024px |
| 12 GB | near full speed | 1024px |
| 16 GB | full speed | 1536px |
| 24 GB+ (high) | fastest | 1536px |

Smaller cards are slower because parts of the model are parked in normal RAM and fetched only when needed ("model streaming" / block swap). **Quality is not affected** - only speed and the practical image size.

Your `image_resolution` choice is never changed by a preset. If it exceeds what your card can handle, you get a clear warning - your choice always wins.

### The VRAM Estimator

Place it between your param nodes and the Launcher (the example workflows already do). It shows:

- a **live estimate** that updates about a second after you change any upstream setting - no run needed
- a **bar chart**: model on GPU, working memory (grows with image size and batch), your LoRA + trainer, text encoder, system overhead - scaled against your card size with a dashed line at the limit
- a **verdict**: FITS / TIGHT / LIKELY OOM against your `gpu_vram_gb`
- **suggestions** with projected savings, each saying exactly *where* to change it in your workflow (wizard field, preset, or Memory Optimizer node)
- a compact **dataset status** line

The estimate is a calibrated heuristic (about ±20%), not a profiler. Windows and your monitor typically use another 0.5-1 GB of the same card.

## Two Workflow Modes

### Wizard Mode (Recommended for beginners)
Answer 5 simple questions and the wizard auto-configures everything:
- What are you training? (character, style, concept, clothing, pose)
- Dataset size? (tiny to very large)
- Image resolution? (512 to 1536 - Anima's supported range)
- GPU VRAM? (6 GB to 24 GB+)
- Quality goal? (quick test to high quality)

Need to deviate from the presets without leaving the wizard? Use the `force_*` fields: resolution, network rank, learning rate, batch size, block swap, epochs, steps, and save frequency.

### Manual Mode (Full control)
Chain together Basic Params -> Advanced -> Memory -> Launcher for complete control over every training parameter.

## Anima Architecture

Anima uses a DiT (Diffusion Transformer) architecture with:
- **Qwen3-0.6B** text encoder
- **Qwen-Image** VAE
- **LLM Adapter** for text-image alignment
- Network module: `networks.lora_anima`
- Uses **bf16** precision (recommended). **fp16 old-GPU mode** is available for cards without native bf16 (RTX 20xx / GTX 16xx) - enable `old_gpu_fp16` on the wizard or pick fp16 in the Memory Optimizer. On RTX 30xx+ fp16 has no benefit; if loss becomes NaN, switch back to bf16. Requires a current sd-scripts (the Manager installs it).
- Supported training resolutions: 512x512 up to 1536x1536

Per the official model card, LoRAs should be trained on the **base** model (the downloader's default variant).

## Requirements

- ComfyUI (any recent version)
- Python 3.10+
- Git (for sd-scripts installation)
- GPU with 6 GB+ VRAM (12 GB+ recommended; 6-10 GB tiers use aggressive memory saving and train slower - on 6 GB, train at 768x768 or lower)

No external Python packages required.

## Troubleshooting

**sd-scripts fails to install:** Make sure `git` is in your system PATH.

**Training fails with module error:** The node pack uses a `runpy` wrapper to handle Python path issues with ComfyUI's embedded Python. If you still get import errors, check the sd-scripts installation in the ComfyUI console.

**"Training would find 0 images":** Your dataset folder structure is wrong - see Dataset Preparation above. The error message tells you exactly what to fix (usually: images must be inside a `10_yourname` subfolder, not directly in `train_data_dir`).

**Out-of-memory during training:** Check the VRAM Estimator's suggestions. Quick wins: lower the image size, raise `force_blocks_to_swap`, and close other GPU-hungry apps. Don't generate images in ComfyUI while training runs.

**Training crawls / seems stuck at step 1:** On Windows this is usually VRAM overflowing - instead of an error, the driver pages into slow "shared GPU memory" and each step takes forever. Check Task Manager > Performance > GPU: if "Dedicated GPU memory" is maxed out and "Shared GPU memory" is climbing, lower the resolution or raise block swap. Note that fp16 old-GPU mode needs MORE VRAM than bf16, not less.

**Live estimate not updating:** The live estimate needs the pack's web extension - do a hard refresh in the browser (Ctrl+Shift+R) after installing or updating the pack.

**Model files not found:** Use the Model Downloader node first, or manually place files in:
- `ComfyUI/models/diffusion_models/` (DiT model)
- `ComfyUI/models/text_encoders/` (Qwen3 encoder)
- `ComfyUI/models/vae/` (VAE)

**Text encoder warning:** The recommended encoder is `qwen_3_06b_base.safetensors`. Other encoders like `clip_l` may work but are not officially supported.

## What's New

- Model Downloader: variant selection (base/aesthetic/turbo), always latest release, never deprecated preview builds
- New VRAM presets for 6 GB, 8 GB, and 10 GB cards
- 1536x1536 resolution preset (Anima's maximum)
- New VRAM Estimator node: live estimate, bar chart, verdict, and where-to-fix suggestions
- Dataset folder check in the wizard, Basic Params, Config Preview, VRAM Estimator, and as a hard gate in the Launcher
- Wizard force_* overrides for resolution, rank, learning rate, batch size, and block swap
- All user-facing text rewritten in plain language - presets explain what they do and that they can be tweaked
- Example workflows updated to include the VRAM Estimator
- Launcher status is now shown directly on the node and in the console - launch problems can no longer fail silently
- Colab / headless support: when no terminal window can be opened, training runs in the background and logs to training_log_<timestamp>.txt in your output folder
- Fixed: AdamW8bit was wrongly refused on bitsandbytes 0.47+ (the compatibility check now works across old and new versions)
- Dependency check no longer blocks the launch when the probe merely times out (slow torch import)
- fp16 old-GPU mode for RTX 20xx / GTX 16xx (cards without native bf16) - explicit opt-in, bf16 stays the default

## Credits

- [Anima](https://huggingface.co/circlestone-labs/Anima) by Circlestone Labs
- [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) for the training backend
- Built for [ComfyUI](https://github.com/comfyanonymous/ComfyUI)

## License

Copyright (C) 2026 7err4. Licensed under the GNU General Public License v3.0 (see LICENSE) - this pack runs inside
ComfyUI (GPL-3.0). Versions released before 21 Oct 2026 were published under MIT and stay MIT. Models have their own licenses (Anima: CircleStone Labs Non-Commercial License; LoRAs trained on it are derivatives under that
license, images are yours). sd-scripts (Apache 2.0) is downloaded at first use.
