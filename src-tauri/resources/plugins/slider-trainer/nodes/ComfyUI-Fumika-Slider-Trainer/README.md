# ComfyUI-Fumika-Slider-Trainer

Node pack of the Fumika **Slider Trainer** plugin (GPL-3.0). Trains slider LoRAs ([Concept Sliders](https://sliders.baulab.info/)):
one LoRA that turns a single thing up or down - a smile, age, detail, how much clothing - while the rest of the picture stays.
Use the result at -2 ... +2. Training runs in its own venv and console window (ComfyUI's Python is not touched).

| Base model | from two prompts (no dataset) | from two image folders |
|---|---|---|
| **Anima** | `train_slider_anima.py --mode guidance` (bundled, by 7err4) | `train_slider_anima.py --mode image_pair` |
| **SDXL** (Illustrious, NoobAI, Pony) | [ai-toolkit](https://github.com/ostris/ai-toolkit) `slider` | ai-toolkit `image_reference_slider_trainer` (pairs by file name) |

| Node | What it does |
|---|---|
| **Fumika Slider Train (Anima / SDXL)** | `start = false`: checks the prompts / folders, finds the models and shows the plan. `start = true`: trains (first time: installs the trainer, 5-20 min). Output: `models/loras/slider_training/<name>/` with a file and a preview sweep (-2, -1, +1, +2) every `save_every` steps. |

Recipe: rank 8 / alpha 4, learning rate 2e-4, constant, edit strength (guidance) 3, 500 steps. More subjects (`neutral | positive | negative`
per line) make a text slider general; anchors are prompts that must not change.

Trainers:
- Anima: `train_slider_anima.py` runs on [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) (its Anima code: `library/anima_utils.py`,
  `strategy_anima.py`, `networks/lora_anima.py`). An sd-scripts checkout of the MOSS or SDXL trainer is reused, otherwise one is installed to
  `ComfyUI/sd-scripts-sliders`.
- SDXL: ai-toolkit (MIT, Ostris) is cloned to `ComfyUI/ai-toolkit` on first use with its own venv; it is not part of this pack.
