// Model families (architectures): loaders, the tested recipe, which options exist for them, which model files belong to them and
// their recommended prompt presets. The app reads them from the switched-on model family plugins (plugin.json "family_def");
// the built-in copies below are the fallback for the browser demo and the tests. Pure module (tests/families.test.ts).

export type Family = string;
export interface FamilyDef {
  id: Family; name: string;
  /** split = diffusion model + text encoder + VAE (MOSS-Image, Anima); checkpoint = one file (SDXL) */
  loader: "split" | "checkpoint" | "anima38";
  te: string; vae: string; clip: string; latent: string;
  /** second text encoder (Anima 3.8B Pro52: Qwen3.5 4B), read by FumikaPromptEncode */
  te2?: string;
  /** models/ folder of its checkpoints, catalog ids of the ones the app can download (first = default) */
  ckptKind: "diffusion_models" | "checkpoints"; bases: string[];
  recipe: { steps: number; cfg: number; sampler: string; scheduler: string; slg: string };
  fast?: { steps: number; cfg: number; sampler: string; scheduler: string; slg: string };
  /** options that only exist for this architecture (the UI hides the others) */
  turbo: boolean; sft: boolean; slg: boolean;
  /** CLIP layer to stop at (2 for anime SDXL), LoRAs also on the text encoder (SDXL) */
  clipSkip: number; clipLoras: boolean;
  /** file name pattern (regex) of its models; order = which family is tried first */
  match: string; order: number;
  /** tensor name fragments that all occur in its checkpoints (the library recognises files with any name) */
  detect?: string[];
  sizes: [string, number, number][]; inpaintSide: number;
  presets?: { id: string; name: string; positive: string; negative: string }[];
}

const SIZES_1MP: [string, number, number][] = [["square", 1024, 1024], ["portrait", 832, 1216], ["landscape", 1216, 832], ["page", 896, 1344], ["wide", 1344, 768]];
const BUILTIN: FamilyDef[] = [
  { id: "moss", name: "MOSS-Image", loader: "split", te: "qwen3.5_9b_int8_convrot.safetensors", vae: "flux2-vae.safetensors", clip: "moss_image",
    latent: "EmptyFlux2LatentImage", ckptKind: "diffusion_models", bases: ["moss_base_bf16", "moss_base_int8", "kromoss"],
    recipe: { steps: 50, cfg: 3, sampler: "euler", scheduler: "sgm_uniform", slg: "22" }, fast: { steps: 8, cfg: 1, sampler: "euler", scheduler: "simple", slg: "" },
    turbo: true, sft: true, slg: true, clipSkip: 0, clipLoras: false, match: "moss|kromoss|charref", order: 1, inpaintSide: 1024,
    sizes: [["square", 1024, 1024], ["portrait", 896, 1152], ["landscape", 1152, 896], ["page", 1024, 1536], ["wide", 1536, 1024]],
    presets: [{ id: "moss-clean", name: "MOSS: no stray text", positive: "", negative: "extra speech bubbles, gibberish text, watermark" },
      { id: "moss-detail", name: "MOSS: detailed illustration", positive: "detailed anime illustration, clean lineart, soft shading", negative: "blurry, low detail, watermark" }] },
  { id: "sdxl", name: "SDXL / Illustrious", loader: "checkpoint", te: "", vae: "", clip: "", latent: "EmptyLatentImage", ckptKind: "checkpoints",
    bases: ["illustrious_xl_v20", "sdxl_animagine_40"], recipe: { steps: 28, cfg: 5.5, sampler: "euler_ancestral", scheduler: "normal", slg: "" },
    turbo: false, sft: false, slg: false, clipSkip: 2, clipLoras: true, match: "xl|illustrious|noob|pony|sdxl|animagine|wai", order: 2,
    inpaintSide: 1024, sizes: SIZES_1MP,
    presets: [{ id: "sdxl-quality", name: "Illustrious: quality tags", positive: "masterpiece, best quality, amazing quality, very aesthetic, absurdres, newest",
      negative: "worst quality, low quality, lowres, bad anatomy, bad hands, jpeg artifacts, watermark, signature, text" },
      { id: "pony-quality", name: "Pony: score tags", positive: "score_9, score_8_up, score_7_up", negative: "score_4, score_5, score_6, worst quality, low quality, watermark, text" }] },
  { id: "anima", name: "Anima", loader: "split", te: "qwen_3_06b_base.safetensors", vae: "qwen_image_vae.safetensors", clip: "stable_diffusion",
    latent: "EmptyLatentImage", ckptKind: "diffusion_models", bases: ["anima_base_v10"],
    recipe: { steps: 30, cfg: 4.5, sampler: "er_sde", scheduler: "simple", slg: "" },
    turbo: false, sft: false, slg: false, clipSkip: 0, clipLoras: false, match: "anima", order: 3, inpaintSide: 1024, sizes: SIZES_1MP,
    presets: [{ id: "anima-quality", name: "Anima: quality tags", positive: "masterpiece, best quality, score_7, newest",
      negative: "worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts" },
      { id: "anima-clean", name: "Anima: clean picture (no text)", positive: "masterpiece, best quality",
        negative: "worst quality, low quality, blurry, jpeg artifacts, artist name, signature, watermark, username, text" }] },
];

/** the families in use: from the switched-on family plugins (setFamilies), the built-ins until then */
export const FAMILIES: Record<Family, FamilyDef> = Object.fromEntries(BUILTIN.map((d) => [d.id, d]));
export let FAMILY_IDS: Family[] = BUILTIN.map((d) => d.id);
/** plugins' family_def list -> the families the app offers (none = keep the built-ins, e.g. in the browser demo) */
export function setFamilies(defs: FamilyDef[]) {
  if (!defs.length) return;
  for (const k of Object.keys(FAMILIES)) delete FAMILIES[k];
  for (const d of [...defs].sort((a, b) => (a.order ?? 9) - (b.order ?? 9))) FAMILIES[d.id] = d;
  FAMILY_IDS = Object.keys(FAMILIES);
}
const ordered = () => Object.values(FAMILIES).sort((a, b) => (a.order ?? 9) - (b.order ?? 9));

/** which architecture a model file belongs to: its folder ("anima38/x.safetensors", where the library files it), else its name
 *  ("" = unknown: offered for every architecture, marked) */
export function familyOf(file: string): Family | "" {
  const parts = file.split(/[\\/]/), n = parts.pop()!.toLowerCase();
  if (parts.length && Object.prototype.hasOwnProperty.call(FAMILIES, parts[0])) return parts[0];
  return ordered().find((d) => new RegExp(d.match, "i").test(n))?.id ?? "";
}
/** files for an architecture: its own first, then the unknown ones; files of other architectures are left out */
export function filesFor(files: string[], f: Family, skip: (n: string) => boolean = () => false): { file: string; known: boolean }[] {
  const mine = files.filter((x) => familyOf(x) === f && !skip(x)).map((file) => ({ file, known: true }));
  const other = files.filter((x) => familyOf(x) === "" && !skip(x)).map((file) => ({ file, known: false }));
  return [...mine, ...other];
}
/** helper files that are no checkpoints / LoRAs to pick (turbo, SFT look, CharRef edit LoRAs) */
export const helperLora = (n: string) => /8steps|dmd|sft_look|charref/i.test(n);

/** prompt presets: the user's list; the recommended ones (from the families) are only the starting entries */
export interface Preset { id: string; family: Family | "all"; name: string; positive: string; negative: string; builtin?: boolean }
export const recommendedPresets = (): Preset[] =>
  ordered().flatMap((d) => (d.presets ?? []).map((p) => ({ ...p, family: d.id, builtin: true })));

/** apply a preset to the prompt fields: its tags go in front of the prompt (once), its negative replaces the negative field */
export function applyPreset(p: Preset, prompt: string, negative: string): { prompt: string; negative: string } {
  const pos = p.positive.trim();
  const has = pos && prompt.toLowerCase().startsWith(pos.toLowerCase());
  return { prompt: !pos || has ? prompt : prompt.trim() ? `${pos}, ${prompt.trim()}` : pos, negative: p.negative.trim() || negative };
}

export interface LoraUse { name: string; strength: number }
/** the LoRA list as the FumikaLoraStack node takes it (empty rows / strength 0 left out) */
export const lorasJson = (l: LoraUse[], cap = Infinity) =>
  JSON.stringify(l.filter((x) => x.name && x.name !== "none" && x.strength).map((x) => ({ name: x.name, strength: Math.min(x.strength, cap) })));
