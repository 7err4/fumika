# Changelog

## 0.1.0 - 2026-10-23

First version.

- **Windows and Linux**: Windows installer (current user, no admin) and Linux AppImage / .deb. On Linux the engine is ComfyUI
  0.42.1 with its own Python 3.13 and the same PyTorch as the Windows build (2.14.0, CUDA 13), installed by uv into the install
  folder.

- **Series and chapters**: a project is a series (cast, style, model settings shared by all chapters) with any number of
  chapters (story, scenes, pages; page numbers start at 1 in each chapter), like Civitai Comics. Create, switch, rename, reorder
  and delete in the sidebar; deleted series / chapters move to `projects/_deleted`. A chapter's pages keep rendering into it
  while another one is open. Each chapter: a story (one line per panel, `what happens | speech bubble`) becomes comic pages;
  three versions per page, the cleanest is kept; reader view and PDF export; example series "Deadline".
- **Covers, CBZ, series reader**: each chapter can get a drawn cover (series title + chapter written on it; one can be the
  series picture). Export a chapter as PDF or **CBZ** (comic archive with ComicInfo.xml: series, chapter number, reading direction)
  for Komga / Kavita / YACReader / Mihon. The reader shows one chapter or the whole series in order.
- **Plugins**: pick at first start, only their models are downloaded. Bundled: MOSS Doujin, Image Studio, Asset Studio, MOSS / Anima / SDXL
  LoRA Trainers, Slider Trainer, and the model families MOSS-Image, Anima (1.0, 2.9B, 3.8B Expanded), Anima 3.8B Pro52 and
  SDXL / Illustrious.
  Licences of all models are shown before a download; non-commercial model licences need an explicit OK.
- **Story editor**: each page as panel cards (what happens, characters on the panel, texts with kind and speaker; add, move and
  delete panels, at most 5) or as plain text; both views write the same story text. Speakers (`Fumika:`, `+Fumika:` joined,
  `Fumika & Sora:` together) put the bubble on the speaker's side; reading direction per project (left to right / right to left).
- **Scenes**: pages that share place, time and light, a cast with a look per scene and the outfit as a list of pieces; tick
  per panel what a character takes off or puts on, every panel gets the current clothing state when it is drawn. **Freeze
  the look** (optional WD tagger): reads the pieces on the first page so later pages draw them the same; the wording stays editable.
- **Expert mode** (Setup, default off): per project sampler, scheduler, steps, CFG, skip layer guidance, negative prompt, fixed
  seed, versions and LoRA / SFT look / reference strengths, each marked when it differs from the recommendation; in the trainer
  epochs, rank, learning rate, resolution and for Anima batch, save interval, block swap, seed, network type and Prodigy.
- **Tray**: the first time the window is closed, Fumika explains that it keeps running in the tray (and how to quit), with
  "keep running" / "quit" and "don't ask again". Starting Fumika again only brings the running window back (single instance).
- **Languages**: English, German, French, Italian, Spanish (Spain and Latin America), Brazilian Portuguese, Japanese, Korean,
  Simplified and Traditional Chinese. The first start follows the system language; the tray menu follows too.
- **Guided setup**: four steps (plugins, install folder, models, engine) with a status line each; optional models folded away,
  every model marked as required / recommended / optional.
- **Generation data in every picture**: next to ComfyUI's graph (ComfyUI opens the picture as a workflow), an A1111-style
  `parameters` text (prompt, negative, steps, sampler, CFG, seed, size, model + AutoV2 hash, LoRA hashes) that A1111, Forge
  and Civitai read - Civitai fills in the generation data and links the models (comic pages name their real recipe, also when
  it is on "auto"). Setup → Export: leave the prompt data out of
  exported pictures and CBZ (the AI marking stays).
- **Trainers**: the engine's models are unloaded before a training starts (renders left on the GPU made training spill into
  shared memory); the Anima trainer installs sd-scripts' packages without touching the engine's own versions (it used to stop
  at opencv and leave ftfy and others out).
- **AI marking** (EU AI Act Art. 50(2)): every rendered PNG gets an XMP packet with the IPTC digital source type
  `trainedAlgorithmicMedia` plus `Software` / `Description` text chunks (checkpoint name, never LoRA names); the PDF export
  carries the same XMP and document properties. Exports copy the marked files.
- **Library**: your own checkpoints and LoRAs, from Civitai, Hugging Face or anywhere else. A checkpoint's architecture (MOSS-Image,
  SDXL, Anima, Anima 3.8B) is recognised from the file itself, whatever it is called, and filed in a folder per architecture so the
  pickers and the MCP tools offer it there; unknown files (GGUF) can be assigned by hand. Files on the engine's drive are linked,
  not copied.
- **Image Studio** plugin: text to image and image to image with MOSS-Image (sizes, count, LoRA, SFT look, fixed seed, expert
  sampling), upscaling with Real-ESRGAN x4plus or a light MOSS redraw; a history keeps every picture with its settings ("use these
  settings", "image to image from this", "upscale this").
- **Slider Trainer** plugin: slider LoRAs (Concept Sliders) for Anima - from two prompts without a dataset, or from two folders
  of pictures; previews at -2 / -1 / +1 / +2 with every saved file, on the bundled `train_slider_anima.py` (kohya sd-scripts).
  SDXL sliders (ai-toolkit) are prepared but switched off: ai-toolkit's slider training fails in its current version.
- **Anima 2.9B and 3.8B**: Anima 2.9B (Gazingstars123) and Anima 3.8B v1 (lylogummy) as further Anima base models with
  downloads; Anima 3.8B v1.1 (Qwen3.5 4B text encoder, Semantic Connector v2) as its own family plugin with the
  comfyui-anima-3-8B nodes (GumGum10, MIT). The **Anima LoRA trainer trains on 1.0, 2.9B and 3.8B v1** (base model choice;
  kohya sd-scripts gets a block-count patch, it assumed 28 blocks and would drop the rest silently); v1.1 has the same DiT weights as
  v1 (all 1168 tensors identical, it only adds the connector and the text encoder), so a LoRA trained on 3.8B v1 is a v1.1
  LoRA too (tested on the v1.1 pipeline; there it keeps the character best at a strength of about 1.3). The memory estimate uses the real model size and turns on gradient checkpointing / block swap
  when a larger model would not fit the card.
- **SDXL LoRA Trainer** plugin: LoRAs, LyCORIS (LoCon / LoHa / LoKr, installed into the trainer on first use) and embeddings
  (textual inversion) for SDXL checkpoints with kohya sd-scripts - same flow as the other trainers (check, plan, train in its own
  window, epoch test); an installed sd-scripts of the MOSS trainer is reused.
- **Model family plugins**: MOSS-Image, Anima and SDXL / Illustrious are plugins of their own (models, loaders, tested recipe,
  options and recommended presets in the manifest); workspaces and trainers name the family they need and Setup switches it
  on with them; the plugin list is grouped (model families, workspaces, trainers). **SDXL / Illustrious**: Illustrious XL v2.0
  (CreativeML OpenRAIL-M) as default checkpoint, Animagine XL 4.0 optional, any SDXL / Pony / NoobAI checkpoint, clip skip 2,
  LoRAs on model and text encoder.
- **Image Studio for every architecture**: MOSS-Image, Anima (incl. 3.8B v1.1) and SDXL, each with its own tested recipe and any checkpoint of that
  architecture (files the app cannot assign are offered and marked); options an architecture does not have are hidden.
  **Inpaint** like A1111: paint the mask on the picture, only masked (with padding, drawn at full model size) or whole picture,
  mask blur, soft paste-back (Differential Diffusion). **Prompt presets** the user manages (recommended ones to start with;
  nothing is put into the negative prompt automatically).
- **Any number of LoRAs** in the Image Studio, on comic pages and in the Asset Studio (a LoRA list with strengths, in order);
  comic pages and assets can also use another MOSS checkpoint.
- **SeedVR2 upscaler** in the Image Studio (ByteDance SeedVR2 3B / 7B sharp, Apache-2.0): adds real detail, keeps faces and lettering.
- **Plugin Python packages**: a plugin can list pip requirements; the app installs them once into its engine with torch, numpy,
  transformers, opencv and the other core packages pinned, and shows "Installing Python packages" meanwhile.
- **Engine log in UTF-8**: node packs that print emoji no longer fail to load.
- **Edited pages keep their versions** (shown faded as "changed") until they are drawn again.
- **Reference picture** (MOSS Doujin): draw the main character from one image (CharRef v2, downloaded from
  [Hugging Face](https://huggingface.co/7err4/MOSS-Image-CharRef)), no LoRA training needed.
- **SFT look** (MOSS Doujin): richer pages on MOSS-Image Base, on by default. Kromoss is listed as experimental.
- **Trainer**: check a dataset (steps, memory estimate) before training, start, follow runs, test epochs, use a LoRA in comics.
- **Engine**: installs its own ComfyUI (portable 0.42.1) with its own Python into one folder; persistent render queue.
- **MCP server** (optional, local, token-protected) so AI agents (LM Studio, Claude, ...) can drive the studio: comic pages, MOSS JSON
  layouts, single images with MOSS-Image / Anima / SDXL (`list_models`, `render_image` incl. image to image and any number of
  LoRAs) and upscaling (`upscale_image`, SeedVR2 or Real-ESRGAN), all through the persistent render queue.
- **Interface**: 11 languages (see Languages above), light / dark, colour schemes Fumika and Terra, tray icon (with a hint on the
  first close), sketch-to-ink splash.
- **Licence**: Apache License 2.0 with the Commons Clause (commercial use and free forks allowed, selling the software is not);
  node packs GPL-3.0. Contributions: see CONTRIBUTING.md.
