# comfyui-anima-3-8B

Minimal ComfyUI nodes for the
[`lylogummy/Anima-3.8B`](https://huggingface.co/lylogummy/Anima-3.8B)
model, its Qwen3.5 4B text encoder, progressive-cross adapter, and timestep-aware
Semantic Connector v2. All inference functionality is included in this package;
`comfyui-qwen35-anima` is not required.

This package registers:

- `AnimaQwen35Loader` — Load Qwen3.5 4B (Anima)
- `AnimaQwen35UnifiedPrompt` — Qwen3.5 Unified Prompt (Anima)
- `Anima38BV2Loader` — anima.3-8B-v2
- `Anima38BV2Prompt` — anima.3-8B-v2 Prompt

## Installation

Use a current ComfyUI build with native Anima support (`comfy.ldm.anima`). Update
ComfyUI first if that module is missing.

Clone the repository into `ComfyUI/custom_nodes`:

```powershell
git clone https://github.com/GumGum10/comfyui-anima-3-8B.git
```

Install its dependencies. From `ComfyUI/custom_nodes` in the Windows portable
build:

```powershell
..\..\python_embeded\python.exe -m pip install -r comfyui-anima-3-8B\requirements.txt
```

For other ComfyUI installations:

```bash
python -m pip install -r comfyui-anima-3-8B/requirements.txt
```

Restart ComfyUI after installation.

## Model files

For the v2 release, the DiT and fixed-strength Semantic Connector v2 are one bundled
checkpoint. The native Qwen3 0.6B encoder and VAE remain shared base-Anima
dependencies. Subfolders are allowed.

| File | ComfyUI directory |
| --- | --- |
| `Anima-3.8B-v2.safetensors` | `models/diffusion_models` |
| [`qwen35_4b.safetensors`](https://huggingface.co/lylogummy/Anima-3.8B/blob/main/text_encoders/qwen35_4b.safetensors) | `models/text_encoders` |
| [`qwen_3_06b_base.safetensors`](https://huggingface.co/circlestone-labs/Anima/blob/main/split_files/text_encoders/qwen_3_06b_base.safetensors) | `models/text_encoders` |
| [`qwen_image_vae.safetensors`](https://huggingface.co/circlestone-labs/Anima/blob/main/split_files/vae/qwen_image_vae.safetensors) | `models/vae` |

The older separate-model path remains available as a backup:

| File | ComfyUI directory |
| --- | --- |
| [`Anima-3.8B.safetensors`](https://huggingface.co/lylogummy/Anima-3.8B/blob/main/difussion_models/Anima-3.8B.safetensors) | `models/diffusion_models` |
| [`Anima-3.8B-expanded_adapter.safetensors`](https://huggingface.co/lylogummy/Anima-3.8B/blob/main/text_encoders/Anima-3.8B-expanded_adapter.safetensors) | `models/text_encoders` |

The adapter dropdown identifies compatible `.safetensors` files by checkpoint
metadata, so the adapter may use a different filename. Supported architectures:

- `anima_progressive_qwen35_cross_adapter_v1`
- `anima_qwen35_quality_anchored_semantic_connector_v2`

Semantic Connector v2 is evaluated inside every denoising step because its
semantic extraction is timestep-aware. The extension includes the required
Anima sampler patch and keeps a 64-entry conditioning-run registry so ComfyUI
can safely reuse cached conditioning across repeated generations.

## Workflow

For v2:

1. Load the bundle with `anima.3-8B-v2`.
2. Load `qwen_3_06b_base.safetensors` with `CLIPLoader`, using type
   `stable_diffusion`.
3. Load `qwen35_4b.safetensors` with `Load Qwen3.5 4B (Anima)`.
4. Connect all three outputs to `anima.3-8B-v2 Prompt` and enter one prompt.
5. Send `expanded` to the sampler. Strength is fixed at the trained value of
   `1.0`; both text encoders are released after their conditioning is produced.

For the backup separate-adapter path:

1. Load `Anima-3.8B.safetensors` with ComfyUI's `UNETLoader`.
2. Load `qwen_3_06b_base.safetensors` with `CLIPLoader`, using type
   `stable_diffusion`. This is the `native_clip` input.
3. Load `qwen35_4b.safetensors` with `Load Qwen3.5 4B (Anima)`.
4. Connect the model and both CLIP outputs to `Qwen3.5 Unified Prompt (Anima)`.
5. Select the adapter, enter one prompt, and set `adapter_strength`.
6. Send `expanded` to the sampler's positive conditioning. The `native` output
   is available for comparisons or fallback workflows.

A complete API-format example is included at `examples/api_workflow.json`.

## Building the release bundle

`bundle_v2.py` validates that the connector's recorded native-adapter hash
matches the selected DiT before writing a combined checkpoint. It refuses to
overwrite an existing output:

```powershell
python bundle_v2.py `
  --base path\to\Anima-base.safetensors `
  --adapter path\to\semantic_connector_v2.safetensors `
  --output path\to\Anima-3.8B-v2.safetensors
```

## Bundled tokenizer

The official Qwen3.5 tokenizer is included in `qwen35_tokenizer/`; users do not
need to download it separately. The node loads this bundled copy before checking
other local locations and never downloads tokenizer files at runtime.

The tokenizer files are unmodified copies from `Qwen/Qwen3.5-4B`, revision
`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`. See
`THIRD_PARTY_NOTICES.md` for attribution and license information.

## Verified configuration

The package has been tested with the 52-block Anima 3.8B checkpoint,
`qwen_3_06b_base.safetensors`, `qwen35_4b.safetensors`, progressive-cross v1,
and the 608M-parameter Semantic Connector v2. A standalone ComfyUI startup test
is run with only `comfyui-anima-3-8B` enabled to prevent accidental dependencies
on other custom-node packs.
