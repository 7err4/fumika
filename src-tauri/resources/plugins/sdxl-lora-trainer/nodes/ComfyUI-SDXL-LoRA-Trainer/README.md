# ComfyUI-SDXL-LoRA-Trainer

Node pack of the Fumika **SDXL LoRA Trainer** plugin (GPL-3.0). Trains LoRAs for SDXL checkpoints (Illustrious, NoobAI, Pony,
Animagine and their mixes) with [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) `sdxl_train_network.py`, in its
own venv and console window (ComfyUI's Python is not touched). An sd-scripts checkout of the MOSS LoRA trainer is reused.

| Node | What it does |
|---|---|
| **SDXL Easy Train (LoRA)** | `start = false`: checks the dataset (`<repeats>_<name>` folders, one `.txt` of Danbooru tags per image, trigger word first) and shows the plan. `start = true`: trains (first time: installs sd-scripts, 5-15 min). Output: `models/loras/sdxl_training/<name>/`. |
| **SDXL Easy Epoch Test** | one row without the LoRA, one per saved file, 3 prompts from your captions (or your own). |

Recipe: LoRA rank 32 / alpha 16, learning rate 1e-4, AdamW8bit, cosine, bf16, sdpa, gradient checkpointing, cached latents,
min-SNR 5, shuffled captions with the first tag kept; optional text encoder training (half learning rate) and v-prediction.
