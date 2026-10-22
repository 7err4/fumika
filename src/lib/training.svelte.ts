// Trainer section state. A training goes through the trainer plugins' workflows in the normal render queue:
// "train" with start=false is the check (dataset report, plan, memory estimate - nothing is trained), start=true launches
// the training in its own console window. Runs are read back from models/loras/<family>_training/<name> (trainer.rs).
import { invoke } from "@tauri-apps/api/core";
import { viewUrl, waitJob, type Job } from "../comfy";
import { app, inTauri, refreshJobs, refreshModels } from "./store.svelte";
import { t, prefs } from "./i18n.svelte";

export type Subject = "character" | "style" | "concept" | "clothing" | "pose";
export type Size = "tiny" | "small" | "medium" | "large" | "huge";
export type Quality = "quick" | "balanced" | "high" | "experimental";
export const SUBJECTS: Subject[] = ["character", "style", "concept", "clothing", "pose"];
export const SIZES: Size[] = ["tiny", "small", "medium", "large", "huge"];
export const VRAMS = [6, 8, 10, 12, 16, 24];
export const QUALITIES: Quality[] = ["quick", "balanced", "high"];

// the Anima wizard's dropdown values (ComfyUI-Anima-LoRA-Training/nodes/training_wizard.py)
const A_SUBJECT: Record<Subject, string> = { character: "character / person", style: "art style", concept: "concept / object",
  clothing: "clothing / accessory", pose: "pose / composition" };
const A_SIZE: Record<Size, [string, number]> = { tiny: ["tiny (1-10 images)", 5], small: ["small (10-30 images)", 4],
  medium: ["medium (30-100 images)", 2], large: ["large (100-500 images)", 1], huge: ["very large (500+ images)", 1] };   // + save interval
const A_VRAM: Record<number, string> = { 6: "6 GB (minimum)", 8: "8 GB (low)", 10: "10 GB", 12: "12 GB", 16: "16 GB", 24: "24 GB+ (high)" };
const A_QUALITY: Record<Quality, string> = { quick: "quick test (fast, lower quality)", balanced: "balanced (recommended)", high: "high quality (slower)",
  experimental: "experimental (adaptive optimizer)" };   // Prodigy, offered in expert mode only
// MOSS easy trainer: rank per subject (the article recipe: 32 characters, 16-32 outfits); epochs stay automatic (~1700 steps)
const M_RANK: Record<Subject, number> = { character: 32, style: 16, concept: 16, clothing: 24, pose: 16 };
export const FOLDER: Record<string, string> = { "moss-lora-trainer": "moss_training", "anima-lora-trainer": "anima_training",
  "sdxl-lora-trainer": "sdxl_training", "slider-trainer": "slider_training" };

export interface TrainFile { name: string; path: string; size: number; modified: number }
export interface TrainRun { plugin: string; name: string; dir: string; state: "prepared" | "starting" | "training" | "finished" | "failed";
  step?: number | null; total?: number | null; remaining?: string | null; loss?: string | null; saved: number; expected?: number | null;
  files: TrainFile[]; samples: string[]; modified: number }
export interface Line { kind: "ok" | "warn" | "err" | "info"; text: string }
export interface Vram { total: number; low: number; high: number; gpu: number; verdict: string }
export interface Check { key: string; ok: boolean; lines: Line[]; plan: string; vram: Vram | null; config: string; images: number | null }

/** expert overrides (Setup -> expert mode); 0 / "" / -1 = the plugin's preset. Anima maps them to the wizard's force_* inputs,
 *  MOSS to its own epochs / rank / learning_rate / resolution. The optimizer comes with the quality preset (Prodigy = experimental). */
export interface TrainAdv { epochs: number; rank: number; lr: number; resolution: number; batch: number; saveEvery: number;
  blocksSwap: number; seed: number; network: "LoRA" | "LoCon" | "LoKr" | "LoHa"; /** SDXL */ trainTe: boolean; vPred: boolean }
export const TRAIN_REC: TrainAdv = { epochs: 0, rank: 0, lr: 0, resolution: 0, batch: 0, saveEvery: 0, blocksSwap: -1, seed: 42, network: "LoRA",
  trainTe: false, vPred: false };
export const trainChanged = (a: TrainAdv) => (Object.keys(TRAIN_REC) as (keyof TrainAdv)[]).filter((k) => a[k] !== TRAIN_REC[k]);

/** Slider Trainer (Concept Sliders): the two ends as prompts (no dataset) or as two image folders; recipe rank 8 / alpha 4, 2e-4, guidance 3, 500 steps */
export interface Slider { family: "anima" | "sdxl"; mode: "text" | "images"; positive: string; negative: string; neutral: string;
  targets: string; anchors: string; pos: string; neg: string; caption: string }
export interface SliderAdv { rank: number; alpha: number; lr: number; guidance: number; steps: number; saveEvery: number; seed: number; vPred: boolean }
export const SLIDER_REC: SliderAdv = { rank: 8, alpha: 4, lr: 2e-4, guidance: 3, steps: 500, saveEvery: 100, seed: 42, vPred: false };
export const sliderChanged = (a: SliderAdv) => (Object.keys(SLIDER_REC) as (keyof SliderAdv)[]).filter((k) => a[k] !== SLIDER_REC[k]);
const SLIDER_BLANK: Slider = { family: "anima", mode: "text", positive: "", negative: "", neutral: "a woman", targets: "", anchors: "",
  pos: "", neg: "", caption: "" };

const FORM_KEY = "fumika-trainer";
const blank = { plugin: "", dataset: "", name: "", trigger: "", subject: "character" as Subject, size: "small" as Size, vram: 12,
  /** Anima trainer: base model file (1.0 / 2.9B / 3.8B v1; kohya gets the block-count patch) */ base: "anima-base-v1.0.safetensors",
  quality: "balanced" as Quality, adv: { ...TRAIN_REC } as TrainAdv, /** SDXL: LoRA or embedding (textual inversion) */ what: "lora" as "lora" | "embedding",
  slider: { ...SLIDER_BLANK } as Slider, sadv: { ...SLIDER_REC } as SliderAdv };

export const tr = $state({
  form: { ...blank },
  check: null as Check | null,
  busy: "" as "" | "check" | "start",
  msg: "",
  err: "",
  runs: [] as TrainRun[],
  grids: {} as Record<string, string>,       // run name -> epoch test grid (MOSS)
  gridBusy: {} as Record<string, boolean>,
});

export const trainers = () => app.plugins.filter((p) => p.enabled && p.ui.includes("trainer"));
export const isAnima = () => tr.form.plugin === "anima-lora-trainer";
/** Anima base models the trainer can use: the installed sizes of the Anima family (3.8B v1.1 needs its own encoder - no kohya support) */
export const animaBases = () => ["anima_base_v10", "anima_29_bf16", "anima_38_expanded"]
  .map((id) => app.catalog.find((c) => c.id === id)).filter((c): c is NonNullable<typeof c> => !!c && c.installed);
export const isSdxl = () => tr.form.plugin === "sdxl-lora-trainer";
export const isSlider = () => tr.form.plugin === "slider-trainer";
/** the base models a slider can be trained for: the switched-on family plugins */
// SDXL sliders wait for a working ai-toolkit slider (its text slider fails upstream, test 22 Oct); every Anima size trains here
export const sliderFamilies = () => (["anima"] as const).filter(() => app.plugins.some((p) => ["family-anima", "family-anima38"].includes(p.id) && p.enabled));
export const safeName = (s: string) => s.trim().replace(/[^A-Za-z0-9_-]/g, "_").replace(/^_+|_+$/g, "");
/** the check stays valid for the same model, folder and name; the other answers only tune the plan */
// expert overrides change memory and steps -> a new check (VRAM estimate) is needed before start
export const formKey = () => isSlider()
  ? [tr.form.plugin, safeName(tr.form.name), JSON.stringify(tr.form.slider), prefs.expert ? JSON.stringify(tr.form.sadv) : ""].join("|")
  : [tr.form.plugin, tr.form.dataset.trim(), safeName(tr.form.name), isSdxl() ? tr.form.what : "",
    prefs.expert ? JSON.stringify(tr.form.adv) : ""].join("|");
/** enough filled in for a check: a dataset for LoRAs, both ends for a slider */
export function formReady(): boolean {
  const f = tr.form, s = f.slider;
  if (!f.plugin || !safeName(f.name)) return false;
  if (!isSlider()) return !!f.dataset.trim();
  return s.mode === "text" ? !!s.positive.trim() && !!s.negative.trim() : !!s.pos.trim() && !!s.neg.trim();
}

export function saveForm() { try { localStorage.setItem(FORM_KEY, JSON.stringify(tr.form)); } catch { /* not kept */ } }
export function initTrainer() {
  let kept = false;
  try { const f = localStorage.getItem(FORM_KEY); if (f) { Object.assign(tr.form, JSON.parse(f)); kept = true; } } catch { /* defaults */ }
  tr.form.adv = { ...TRAIN_REC, ...(tr.form.adv ?? {}) };
  tr.form.what ??= "lora";
  tr.form.slider = { ...SLIDER_BLANK, ...(tr.form.slider ?? {}) };
  tr.form.sadv = { ...SLIDER_REC, ...(tr.form.sadv ?? {}) };
  const ts = trainers();
  if (!ts.some((p) => p.id === tr.form.plugin)) tr.form.plugin = ts[0]?.id ?? "";
  const fams = sliderFamilies();
  if (fams.length && !(fams as readonly string[]).includes(tr.form.slider.family)) tr.form.slider.family = fams[0];
  // first visit: GPU memory from the card (VRAM total in MB), rounded down to the wizard's tiers
  if (app.gpu && !kept) tr.form.vram = [...VRAMS].reverse().find((v) => v * 1024 <= app.gpu![1] + 512) ?? 6;
}

/** FumikaSliderTrain inputs (slider-trainer/workflows/train.json) */
export function sliderVars(start: boolean, f = tr.form, expert = prefs.expert) {
  const s = f.slider, a = expert ? f.sadv : SLIDER_REC;
  const v: Record<string, unknown> = { family: s.family, mode: s.mode, name: safeName(f.name), start, rank: a.rank, alpha: a.alpha,
    learning_rate: a.lr, guidance: a.guidance, steps: a.steps, save_every: a.saveEvery, seed: a.seed, v_pred: s.family === "sdxl" && a.vPred };
  if (s.mode === "text") Object.assign(v, { positive: s.positive.trim(), negative: s.negative.trim(), neutral: s.neutral.trim() || "a woman",
    targets: s.targets, anchors: s.anchors, sample_prompt: s.neutral.trim() });
  else Object.assign(v, { pos_folder: s.pos.trim(), neg_folder: s.neg.trim(), pair_caption: s.caption.trim(), sample_prompt: s.caption.trim() });
  return v;
}

function vars(start: boolean, outDir = "") {
  const f = tr.form, name = safeName(f.name);
  if (isSlider()) return sliderVars(start);
  const a = prefs.expert ? f.adv : TRAIN_REC;
  // SDXL (same easy-train flow as MOSS): 1024 fits from 12 GB with gradient checkpointing; the trigger word is checked in the captions
  if (isSdxl()) return { dataset: f.dataset.trim(), name, start, rank: a.rank || M_RANK[f.subject], trigger: f.trigger.trim(),
    resolution: a.resolution || (f.vram >= 12 ? 1024 : 768), epochs: a.epochs, learning_rate: a.lr || 1e-4, batch: a.batch || 1,
    save_every: a.saveEvery, seed: a.seed, train_te: a.trainTe, v_pred: a.vPred,
    kind: f.what === "embedding" ? "embedding" : "LoRA", network: a.network, template: f.subject === "style" ? "style" : "object" };
  if (!isAnima()) return { dataset: f.dataset.trim(), name, start, rank: a.rank || M_RANK[f.subject],
    resolution: a.resolution || (f.vram >= 24 ? 1024 : 768), epochs: a.epochs, learning_rate: a.lr || 1e-4 };
  const [size, every] = A_SIZE[f.size];
  const scene = f.subject === "character" ? ", 1girl, solo, upper body, looking at viewer, simple background"
    : f.subject === "style" ? ", 1girl, solo, cowboy shot, city street, day" : "";
  // the chosen base when installed, else an installed one (only 2.9B / 3.8B there: never a 1.0 that is missing)
  const bases = animaBases();
  const base = bases.some((c) => c.file === f.base) ? f.base : bases[0]?.file ?? "anima-base-v1.0.safetensors";
  return { dataset: f.dataset.trim(), output_dir: outDir, name, start, dit_model: base, subject: A_SUBJECT[f.subject], dataset_size: size,
    // top tier "24 GB+": the card's real size, so the estimate does not slow a 32 GB card down for Anima 2.9B / 3.8B
    gpu_vram: A_VRAM[f.vram], gpu_vram_gb: f.vram === 24 && app.gpu ? Math.max(24, Math.floor(app.gpu[1] / 1024)) : f.vram, quality: A_QUALITY[f.quality],
    sample_prompt: f.trigger.trim() ? f.trigger.trim() + scene : "", sample_every: f.trigger.trim() ? every : 0,
    network_type: a.network, training_seed: a.seed, force_epochs: a.epochs, force_rank: a.rank, force_lr: a.lr, force_batch: a.batch,
    force_resolution: a.resolution ? `${a.resolution},${a.resolution}` : "", force_save_every: a.saveEvery, force_blocks_to_swap: a.blocksSwap };
}

async function queue(workflow: string, label: string, v: object): Promise<Job> {
  const id = await invoke<string>("queue_workflow", { project: "Trainer", label, plugin: tr.form.plugin, workflow, vars: v, priority: 5 });
  refreshJobs();
  return waitJob(id);
}

const text = (job: Job, node: string) => String(job.outputs?.[node]?.text?.[0] ?? "");
const bucket = (n: number): Size => (n <= 10 ? "tiny" : n <= 30 ? "small" : n <= 100 ? "medium" : n <= 500 ? "large" : "huge");

/** MOSS easy report: READY / NOT READY, OK|WARN|ERROR lines, TOTAL, PLAN */
export function parseMoss(s: string, key: string): Check {
  const lines: Line[] = []; let plan = "", images: number | null = null;
  for (const raw of s.split("\n")) {
    const l = raw.trim();
    if (!l || /^(NOT )?READY/.test(l)) continue;
    if (l.startsWith("PLAN:")) { plan = l.slice(5).trim(); continue; }
    const m = l.match(/^TOTAL (\d+) images/); if (m) images = +m[1];
    lines.push({ kind: l.startsWith("ERROR") ? "err" : l.startsWith("WARN") ? "warn" : l.startsWith("OK") ? "ok" : "info",
      text: l.replace(/^(OK|WARN|ERROR)\s+/, "") });
  }
  return { key, ok: /^READY/.test(s.trim()), lines, plan, vram: null, config: "", images };
}

/** Anima: dataset block of the config preview (node 5), VRAM estimator (node 4), launcher status (node 6) */
export function parseAnima(job: Job, key: string): Check {
  const pre = text(job, "5"), lines: Line[] = []; let images: number | null = null;
  const cut = pre.split("\n").findIndex((l) => /^\s*(#|\[)/.test(l));
  for (const raw of (cut < 0 ? pre.split("\n") : pre.split("\n").slice(0, cut))) {
    const l = raw.trim();
    if (!l || l.startsWith("───")) continue;
    const m = l.match(/^Total: (\d+) image/); if (m) images = +m[1];
    lines.push({ kind: l.startsWith("PROBLEM") ? "err" : l.startsWith("Warning") ? "warn" : /looks good/.test(l) ? "ok" : "info",
      text: l.replace(/^(PROBLEM|Warning):\s*/, "") });
  }
  const status = text(job, "6");
  if (/sd-scripts is not ready/.test(status)) lines.push({ kind: "info", text: "sd-scripts: installed on the first start (5-15 min)" });
  else if (status.startsWith("ERROR")) lines.push({ kind: "err", text: status.replace(/^ERROR:\s*/, "").split("\n")[0] });
  let vram: Vram | null = null;
  try { const c = JSON.parse(job.outputs?.["4"]?.chart?.[0] ?? "null"); if (c) vram = { total: c.total, low: c.low, high: c.high, gpu: c.gpu, verdict: c.verdict }; }
  catch { /* no estimate */ }
  return { key, ok: !lines.some((l) => l.kind === "err") && !!pre, lines, plan: "", vram, config: cut < 0 ? "" : pre.split("\n").slice(cut).join("\n"), images };
}

export async function runCheck() {
  if (!formReady()) return;
  tr.busy = "check"; tr.err = ""; tr.msg = ""; saveForm();
  const key = formKey();
  try {
    const out = isAnima() ? await invoke<string>("trainer_dir", { plugin: tr.form.plugin }) + "/" + safeName(tr.form.name) : "";
    const job = await queue("train", `train-check ${safeName(tr.form.name)}`, vars(false, out));
    tr.check = isAnima() ? parseAnima(job, key) : parseMoss(text(job, "1"), key);
    if (tr.check.images) tr.form.size = bucket(tr.check.images);
  } catch (e) { tr.err = String(e); }
  tr.busy = "";
  refreshRuns();
}

export async function startTraining() {
  if (!tr.check?.ok || tr.check.key !== formKey()) return;
  tr.busy = "start"; tr.err = ""; saveForm();
  try {
    const out = isAnima() ? await invoke<string>("trainer_dir", { plugin: tr.form.plugin }) + "/" + safeName(tr.form.name) : "";
    const job = await queue("train", `train-start ${safeName(tr.form.name)}`, vars(true, out));
    const s = isAnima() ? text(job, "6") : text(job, "1");
    if (/^ERROR|NOT READY|Not started/m.test(s)) tr.err = s.split("\n").find((l) => /ERROR|NOT|Not/.test(l)) ?? s;
    else {
      tr.msg = /installing/i.test(s) ? s.split("\n").filter(Boolean).pop() ?? t("tr.started") : t("tr.started");
      tr.check = null;   // a second press must not start the same run again: a new check first
    }
  } catch (e) { tr.err = String(e); }
  tr.busy = "";
  refreshRuns();
}

export async function refreshRuns() {
  if (!inTauri()) return;
  try { tr.runs = await invoke<TrainRun[]>("trainer_runs"); } catch { /* not set up */ }
}

/** MOSS: render every saved file of a run as a grid (MossEasyEpochTest) */
export async function epochTest(run: TrainRun) {
  tr.gridBusy[run.name] = true;
  try {
    const id = await invoke<string>("queue_workflow", { project: "Trainer", label: `train-epochs ${run.name}`, plugin: run.plugin,
      workflow: "epochs", vars: { name: run.name }, priority: 5 });
    refreshJobs();
    const job = await waitJob(id);
    tr.grids[run.name] = viewUrl(job.outputs["2"].images[0]);
  } catch (e) { tr.err = String(e); }
  tr.gridBusy[run.name] = false;
}

export async function useFile(f: TrainFile) {
  try { tr.msg = t("tr.used", { name: await invoke<string>("import_lora", { path: f.path }) }); refreshModels(); }
  catch (e) { tr.err = String(e); }
}

/** browser preview (vite dev without Tauri): a filled form, a finished check and three runs */
export function demoTrainer() {
  Object.assign(tr.form, { plugin: "anima-lora-trainer", dataset: "D:\\datasets\\fumika_v1", name: "fumika_anima_v1", trigger: "fumika7err4",
    subject: "character", size: "medium", vram: 24, quality: "balanced" });
  tr.check = { key: formKey(), ok: true, plan: "", images: 49, config: "[general]\nshuffle_caption = true\n…",
    vram: { total: 15.8, low: 14.2, high: 17.6, gpu: 24, verdict: "fits" },
    lines: [{ kind: "info", text: "4_fumika:  39 image(s) x 4 repeats = 156 steps/epoch" },
      { kind: "info", text: "4_skirt:  10 image(s) x 4 repeats = 40 steps/epoch" },
      { kind: "info", text: "Total: 49 image(s), 196 steps per epoch (x batch size)" },
      { kind: "warn", text: "3 caption(s) do not contain the trigger word 'fumika7err4'" },
      { kind: "ok", text: "Folder structure looks good." }] };
  const now = Math.floor(Date.now() / 1000);
  const f = (name: string, mb: number, ago: number): TrainFile => ({ name, path: "", size: mb * 1e6, modified: now - ago });
  tr.runs = [
    { plugin: "moss-lora-trainer", name: "terra_moss_v1", dir: "", state: "training", step: 706, total: 2128, remaining: "43:16", loss: "0.244",
      saved: 1, expected: 4, files: [f("terra_moss_v1-000002.safetensors", 152, 600)], samples: [], modified: now - 30 },
    { plugin: "anima-lora-trainer", name: "fumika_anima_v1", dir: "", state: "finished", saved: 3, expected: 3,
      files: [f("fumika_anima_v1-000004.safetensors", 86, 9000), f("fumika_anima_v1-000008.safetensors", 86, 6000), f("fumika_anima_v1.safetensors", 86, 3000)],
      samples: [], modified: now - 3000 },
    { plugin: "moss-lora-trainer", name: "sketch_style", dir: "", state: "failed", saved: 0, expected: 4, files: [], samples: [], modified: now - 86400 },
  ];
}
