# ComfyUI-Fumika-Image

Node pack of the Fumika **Image Studio** plugin (GPL-3.0), also used by the Asset Studio (LoRA stack). The plugin's workflows
(text to image, image to image, inpaint, Real-ESRGAN / SeedVR2 / redraw upscale - for MOSS-Image and Anima) use stock ComfyUI
nodes plus:

| Node | What it does |
|---|---|
| **Fumika Load Picture (output / input)** | loads `output:<path>` or `input:<path>` (nothing outside those folders), cover-crops to a size or scales it, caps the long side and rounds both sides to multiples of 16; 4th output = short edge x `target_scale` (SeedVR2). |
| **Fumika LoRA Stack** | any number of LoRAs on a model, JSON list `[{"name": ..., "strength": ...}]`, applied in order. |
| **Fumika Load Mask** | the mask painted in the app (`input:fumika_masks/x.png`, white = redraw) at the picture's size. |
| **Fumika Inpaint Crop / Stitch** | A1111-style inpaint: cut the masked area + padding out, draw it at the model's size, paste it back with a soft mask edge ("whole picture" = full size). Used with SetLatentNoiseMask + Differential Diffusion. |

Upscaler model: Real-ESRGAN x4plus (BSD-3-Clause) as `models/upscale_models/RealESRGAN_x4plus.safetensors`
([Comfy-Org repack](https://huggingface.co/Comfy-Org/Real-ESRGAN_repackaged)).
