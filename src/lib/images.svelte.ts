// Image Studio state (plugins/image-studio): single images - text to image, image to image, inpaint (like A1111) and upscaling
// (Real-ESRGAN x4plus, SeedVR2, redraw with the chosen model) - for every model family (families.ts: MOSS-Image, Anima), with
// any checkpoint of that family and any number of LoRAs. Every image keeps the settings it was made with ("use these settings").
// The pictures stay in the engine's output folder; history, form and prompt presets live in this browser profile.
import { invoke } from "@tauri-apps/api/core";
import { viewUrl, waitJob, type Job } from "../comfy";
import { app, inTauri, refreshJobs, type OutFile } from "./store.svelte";
import { prefs } from "./i18n.svelte";
import { FAMILIES, recommendedPresets, filesFor, helperLora, lorasJson, type Family, type LoraUse, type Preset } from "./families";

export type Mode = "t2i" | "i2i" | "inpaint" | "upscale";
export type Upscaler = "esrgan" | "seedvr2" | "redraw";
export const MODES: Mode[] = ["t2i", "i2i", "inpaint", "upscale"];

export interface ImgForm {
  mode: Mode; family: Family; unet: string; loras: LoraUse[];
  prompt: string; negative: string; size: string; count: number; quality: boolean; sft: boolean; sftStrength: number; seed: number;
  denoise: number; source: string; sourceUrl: string;
  mask: string; maskOnly: boolean; padding: number; maskBlur: number; inDenoise: number;
  upscaler: Upscaler; scale: number; upDenoise: number;
  // expert mode only ("auto" / 0 = the family's tested recipe)
  sampler: string; scheduler: string; steps: number; cfg: number; slg: string;
}
export interface ImgEntry { id: string; created: number; form: ImgForm; state: "busy" | "done" | "error"; jobId?: string; seed: number;
  images: string[]; files: OutFile[]; error?: string }

const FORM_KEY = "fumika-image-form", HIST_KEY = "fumika-images", PRESET_KEY = "fumika-presets";
export const START: ImgForm = { mode: "t2i", family: "moss", unet: "", loras: [], prompt: "", negative: "", size: "square", count: 1,
  quality: true, sft: true, sftStrength: 1.5, seed: 0, denoise: 0.6, source: "", sourceUrl: "",
  mask: "", maskOnly: true, padding: 96, maskBlur: 8, inDenoise: 0.75, upscaler: "esrgan", scale: 2, upDenoise: 0.3,
  sampler: "auto", scheduler: "auto", steps: 0, cfg: 0, slg: "auto" };

export const im = $state({ form: { ...START } as ImgForm, history: [] as ImgEntry[], busy: false, err: "",
  models: { diffusion: [] as string[], checkpoints: [] as string[], loras: [] as string[] }, presets: [] as Preset[] });

export function saveImages() {
  try {
    localStorage.setItem(FORM_KEY, JSON.stringify(im.form)); localStorage.setItem(HIST_KEY, JSON.stringify(im.history.slice(0, 300)));
    localStorage.setItem(PRESET_KEY, JSON.stringify(im.presets));
  } catch { /* storage full: the pictures stay in the output folder */ }
}
export function initImages() {
  try {
    const f = localStorage.getItem(FORM_KEY); if (f) im.form = { ...START, ...JSON.parse(f) };
    const h = localStorage.getItem(HIST_KEY); if (h) im.history = JSON.parse(h);
    const p = localStorage.getItem(PRESET_KEY); im.presets = p ? JSON.parse(p) : recommendedPresets();
  } catch { im.presets = recommendedPresets(); }
  if (!FAMILIES[im.form.family]) im.form.family = Object.keys(FAMILIES)[0];   // its family plugin was switched off
  if ((im.form.upscaler as string) === "moss") im.form.upscaler = "redraw";   // 1.1 name
  refreshModelLists();
}
/** checkpoint and LoRA files of the engine (sub-folders included) */
export async function refreshModelLists() {
  if (!inTauri()) return;
  try {
    const [d, c, l] = await Promise.all(["diffusion_models", "checkpoints", "loras"].map((kind) => invoke<[string, number][]>("list_models", { kind })));
    im.models = { diffusion: d.map((x) => x[0]), checkpoints: c.map((x) => x[0]), loras: l.map((x) => x[0]) };
  } catch { /* engine not installed yet */ }
}

export const enabled = () => app.plugins.some((p) => p.enabled && p.id === "image-studio");
const item = (id: string) => app.catalog.find((c) => c.id === id);
const byFile = (file: string) => app.catalog.find((c) => c.file === file);
export const fam = () => FAMILIES[im.form.family];
/** checkpoints / LoRAs offered for the chosen family: its own first, then the files the app cannot assign (marked) */
const ckptFiles = (f: Family) => FAMILIES[f]?.ckptKind === "checkpoints" ? im.models.checkpoints : im.models.diffusion;
export const checkpoints = () => filesFor(ckptFiles(im.form.family), im.form.family);
export const loraFiles = () => filesFor(im.models.loras, im.form.family, helperLora);
/** the checkpoint used: the chosen file, else the family's first installed base model */
export function unetFor(f: ImgForm): string {
  if (f.unet) return f.unet;
  const b = FAMILIES[f.family].bases.map(item).find((x) => x?.installed);
  return b?.file ?? filesFor(ckptFiles(f.family), f.family).find((x) => x.known)?.file ?? "";
}
/** what is missing for the family (text encoder, VAE, a checkpoint) - catalog names for the hint */
export function missing(f: ImgForm): string[] {
  const d = FAMILIES[f.family], out: string[] = [];
  for (const file of [d.te, d.te2 ?? "", d.vae].filter(Boolean)) { const c = byFile(file); if (c && !c.installed) out.push(c.name); }
  if (!unetFor(f)) out.push(item(d.bases[0])?.name ?? d.name);
  return out;
}
export const esrganReady = () => !!item("realesrgan_x4")?.installed;
/** SeedVR2: the VAE + one DiT; the 7B sharp model wins when both are there */
export const seedvr2Dit = () => item("seedvr2_vae")?.installed ? ["seedvr2_7b_sharp", "seedvr2_3b"].map(item).find((x) => x?.installed)?.file ?? "" : "";
export const upscalerReady = (u: Upscaler) => u === "esrgan" ? esrganReady() : u === "seedvr2" ? !!seedvr2Dit() : true;
/** the 8-step turbo recipe is used: MOSS only, "best quality" off and the turbo LoRA installed */
export const fastMode = (f: ImgForm) => FAMILIES[f.family].turbo && !f.quality && !!item("turbo")?.installed;

/** sampling of the family (tested recipe, or the fast one), with expert overrides on top - auto / 0 = recipe */
export function sampling(f: ImgForm, expert: boolean) {
  const d = FAMILIES[f.family], r = fastMode(f) && d.fast ? d.fast : d.recipe;
  if (!expert) return { ...r };
  const slg = f.slg.trim();
  return { steps: f.steps > 0 ? Math.round(f.steps) : r.steps, cfg: f.cfg > 0 ? f.cfg : r.cfg,
    sampler: f.sampler !== "auto" ? f.sampler : r.sampler, scheduler: f.scheduler !== "auto" ? f.scheduler : r.scheduler,
    slg: !d.slg ? "" : slg === "" || slg === "auto" ? r.slg : slg.toLowerCase() === "off" ? "" : slg };
}

/** workflow + variables for the form (the template engine fills plugins/image-studio/workflows/*.json with them) */
export function plan(f: ImgForm, expert: boolean, seed: number, prefix: string): { workflow: string; vars: Record<string, unknown> } {
  const d = FAMILIES[f.family], sft = item("sft_look"), turbo = item("turbo");
  const chain = { loader: d.loader, unet: unetFor(f), text_encoder: d.te, te2: d.te2 ?? "", vae: d.vae, clip_type: d.clip || "stable_diffusion", latent_node: d.latent,
    clip_skip: d.clipSkip, clip_loras: d.clipLoras,
    turbo_lora: fastMode(f) ? turbo!.file : "", loras: lorasJson(f.loras),
    sft_look: d.sft && f.sft && sft?.installed ? sft.file : "", sft_strength: f.sftStrength, negative: f.negative.trim(), seed, prefix,
    ...sampling(f, expert) };
  const [, w, h] = d.sizes.find((s) => s[0] === f.size) ?? d.sizes[0];
  if (f.mode === "t2i") return { workflow: "t2i", vars: { ...chain, prompt: f.prompt.trim(), width: w, height: h, count: f.count } };
  if (f.mode === "i2i") return { workflow: "i2i", vars: { ...chain, prompt: f.prompt.trim(), source: f.source, denoise: f.denoise, count: f.count } };
  if (f.mode === "inpaint") return { workflow: "inpaint", vars: { ...chain, prompt: f.prompt.trim(), source: f.source, mask: `input:${f.mask}`,
    denoise: f.inDenoise, count: f.count, only_masked: f.maskOnly, padding: f.padding, target: d.inpaintSide, mask_blur: f.maskBlur } };
  if (f.upscaler === "seedvr2") return { workflow: "upscale_seedvr2", vars: { source: f.source, prefix, scale: f.scale, seed,
    dit: seedvr2Dit(), max_resolution: 4096 } };
  if (f.upscaler === "esrgan") return { workflow: "upscale_esrgan", vars: { source: f.source, prefix, esrgan_factor: f.scale / 4,
    upscaler: item("realesrgan_x4")?.file ?? "RealESRGAN_x4plus.safetensors" } };
  // redraw: enlarge, then a light redraw with the chosen model adds detail (always the full recipe, never turbo)
  return { workflow: "upscale_redraw", vars: { ...chain, turbo_lora: "", ...(d.recipe), slg: d.slg ? d.recipe.slg : "",
    prompt: f.prompt.trim() || "detailed high resolution illustration, clean lineart", source: f.source, scale: f.scale, denoise: f.upDenoise } };
}

function fill(e: ImgEntry, job: Job) {
  const out = job.outputs?.["13"]?.images ?? [];
  Object.assign(e, { state: "done", images: out.map(viewUrl), files: out.map((x: OutFile) => ({ filename: x.filename, subfolder: x.subfolder })) });
}

export const canGenerate = (f: ImgForm) => (f.mode === "t2i" ? !!f.prompt.trim() : !!f.source) && (f.mode !== "inpaint" || !!f.mask)
  && (f.mode !== "upscale" || upscalerReady(f.upscaler)) && ((f.mode === "upscale" && f.upscaler !== "redraw") || !missing(f).length);

export async function generate() {
  const f = im.form;
  if (!enabled() || !canGenerate(f)) return;
  im.busy = true; im.err = ""; saveImages();
  const seed = f.seed > 0 ? f.seed : Math.floor(Math.random() * 2 ** 31);
  const id = crypto.randomUUID();
  const { workflow, vars } = plan(f, prefs.expert, seed, `fumika_images/${new Date().toISOString().slice(0, 10)}/${f.mode}_${id.slice(0, 8)}`);
  im.history.unshift({ id, created: Date.now(), form: JSON.parse(JSON.stringify(f)), state: "busy", seed, images: [], files: [] });
  const e = im.history[0];
  try {
    e.jobId = await invoke<string>("queue_workflow", { project: "Image Studio", label: `image-${f.mode}`, plugin: "image-studio", workflow, vars });
    saveImages(); refreshJobs(); im.busy = false;
    fill(e, await waitJob(e.jobId));
  } catch (err) { Object.assign(e, { state: "error", error: String(err) }); }
  im.busy = false; saveImages();
}

export function resumeImages() {
  for (const e of im.history) if (e.state === "busy" && e.jobId)
    waitJob(e.jobId).then((j) => fill(e, j), (err) => Object.assign(e, { state: "error", error: String(err) })).finally(saveImages);
}

/** "use these settings": the form takes the entry's settings and seed */
export function reuse(e: ImgEntry) { im.form = { ...START, ...JSON.parse(JSON.stringify(e.form)), seed: e.seed }; saveImages(); }
/** an image of the history becomes the source of image to image / inpaint / upscale (a new source needs a new mask) */
export function useAsSource(e: ImgEntry, k: number, mode: Mode) {
  const fl = e.files[k];
  if (!fl) return;
  Object.assign(im.form, { mode, source: `output:${fl.subfolder ? fl.subfolder + "/" : ""}${fl.filename}`, sourceUrl: e.images[k], mask: "",
    prompt: im.form.prompt || e.form.prompt, family: e.form.mode === "upscale" ? im.form.family : e.form.family });
  saveImages();
}
/** a picture from disk: copied into ComfyUI/input/fumika_refs (same as the reference picture) */
export async function pickSource(path: string, url: (n: string) => string) {
  const name = await invoke<string>("import_reference", { path });
  Object.assign(im.form, { source: `input:${name}`, sourceUrl: url(name), mask: "" }); saveImages();
}
/** the painted mask (PNG bytes, white = redraw) -> ComfyUI/input/fumika_masks */
export async function storeMask(png: Uint8Array) {
  im.form.mask = await invoke<string>("save_mask", { png: Array.from(png) }); saveImages();
}
export function removeImage(e: ImgEntry) { im.history = im.history.filter((x) => x.id !== e.id); saveImages(); }

// presets: the user's own list (the recommended ones are only where it starts)
export function addPreset(p: Omit<Preset, "id">) { im.presets.push({ ...p, id: crypto.randomUUID() }); saveImages(); }
export function removePreset(id: string) { im.presets = im.presets.filter((p) => p.id !== id); saveImages(); }
export function restorePresets() {
  const have = new Set(im.presets.map((p) => p.id));
  im.presets.push(...recommendedPresets().filter((p) => !have.has(p.id))); saveImages();
}
export const presetsFor = (f: Family) => im.presets.filter((p) => p.family === f || p.family === "all");

export function demoImages() {
  im.form.prompt = "Fumika, an adult manga artist with a black ponytail, sketching in a sunny park, watercolour";
  im.models = { diffusion: ["moss_image_base_bf16.safetensors", "kromoss_bf16.safetensors", "anima-base-v1.0.safetensors", "myMix_v3.safetensors"],
    checkpoints: ["Illustrious-XL-v2.0.safetensors", "waiIllustriousSDXL_v160.safetensors", "myMix_v3.safetensors"],
    loras: ["fumika_moss_v1.safetensors", "terra_anima_v1_e10.safetensors", "style_ink.safetensors", "kromoss_8steps_dmd_lora.safetensors",
      "fumika_illustrious_xl_v1.safetensors"] };
  const d = (n: number, mode: Mode, img: string): ImgEntry => ({ id: `d${n}`, created: Date.now() - n * 900000, seed: 1000 + n, state: "done",
    form: { ...START, mode, prompt: im.form.prompt }, images: [img], files: [{ filename: img.split("/").pop()!, subfolder: "demo" }] });
  if (!inTauri()) im.history = [d(1, "t2i", "/demo-pages/p01.png"), d(2, "upscale", "/demo-pages/p02.png"), d(3, "i2i", "/demo-pages/p03.png")];
}
