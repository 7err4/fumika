// Asset Studio state. Every asset is one image with a MOSS-Image JSON layout (plugins/asset-studio: node FumikaAssetSheet builds
// the layout, workflow "asset" renders it in the normal queue). The character comes from a description, a character LoRA or the
// book's reference picture (CharRef). Optional: transparent background + one PNG per cell (VN sprites, FumikaSpriteCutout).
import { invoke } from "@tauri-apps/api/core";
import { viewUrl, waitJob, type Job } from "../comfy";
import { app, inTauri, projectName, refreshJobs, save, type AssetEntry, type OutFile } from "./store.svelte";
import { t } from "./i18n.svelte";
import { lorasJson, type LoraUse } from "./families";

export type AssetType = "expressions" | "outfits" | "turnaround" | "profile" | "card" | "chibi" | "pixel";
export type Source = "text" | "lora" | "ref";
export type Style = "Anime colour" | "Ink manga" | "Soft painted";
export const TYPES: AssetType[] = ["expressions", "outfits", "turnaround", "profile", "card", "chibi", "pixel"];
export const STYLES: Style[] = ["Anime colour", "Ink manga", "Soft painted"];
/** assets whose cells are single figures - these can become transparent sprites */
export const CUTTABLE: AssetType[] = ["expressions", "outfits", "turnaround", "chibi", "pixel"];
/** pixel art: a character LoRA above this overrides the pixel style (test 21 Oct) */
export const PIXEL_LORA_MAX = 0.4;

type Box = [number, number, number, number];   // y1, x1, y2, x2 as fractions (same layouts as sheets.py)
function grid(rows: number, cols: number, y0 = .02, y1 = .98, x0 = .02, x1 = .98, gap = .012): Box[] {
  const h = (y1 - y0 - gap * (rows - 1)) / rows, w = (x1 - x0 - gap * (cols - 1)) / cols, out: Box[] = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++)
    out.push([y0 + r * (h + gap), x0 + c * (w + gap), y0 + r * (h + gap) + h, x0 + c * (w + gap) + w]);
  return out;
}
/** layout preview: boxes + aspect (width / height) per asset type */
export const LAYOUT: Record<AssetType, { boxes: Box[]; text?: Box[]; aspect: number }> = {
  expressions: { boxes: grid(3, 3), aspect: 1 },
  outfits: { boxes: grid(1, 4, .03, .97), aspect: 1536 / 1152 },
  turnaround: { boxes: grid(1, 3, .03, .97), aspect: 1536 / 1152 },
  profile: { boxes: [[.03, .45, .96, .98], [.03, .02, .40, .43], [.42, .02, .60, .21], [.42, .23, .60, .43]],
    text: [[.62, .03, .80, .42], [.82, .03, .88, .42], [.90, .03, .97, .42]], aspect: 1024 / 1536 },
  card: { boxes: [[.08, .12, .58, .88]], text: [[.60, .14, .66, .86], [.68, .16, .88, .84]], aspect: 1024 / 1536 },
  chibi: { boxes: grid(2, 3), aspect: 1536 / 1024 },
  pixel: { boxes: [0, 1, 2, 3].map((k): Box => [.1, .02 + k * .245, .9, .02 + k * .245 + .225]), aspect: 2 },
};

/** the editable fields per asset type (keys of the node's fields JSON); "list" fields take one entry per line */
export const FIELDS: Record<AssetType, { key: string; list?: boolean; rows?: number }[]> = {
  expressions: [{ key: "expressions", list: true, rows: 9 }],
  outfits: [{ key: "outfits", list: true, rows: 4 }],
  turnaround: [{ key: "views", list: true, rows: 3 }],
  profile: [{ key: "name" }, { key: "stats", list: true, rows: 4 }, { key: "quote" }, { key: "insets", list: true, rows: 2 }],
  card: [{ key: "card_title" }, { key: "card_text", rows: 3 }, { key: "card_art", rows: 2 }],
  chibi: [{ key: "chibi", list: true, rows: 6 }],
  pixel: [],
};
/** starting values (same defaults as the node, Fumika's example) */
const START: Record<string, string> = {
  expressions: "neutral\nhappy smile\nlaughing\nangry\nsad\nsurprised\nembarrassed, blushing\nsmug grin\nsleepy",
  outfits: "Default: her default outfit\nCasual: a grey oversized hoodie and black shorts\nFestival: a navy yukata with a white floral pattern\n" +
    "Winter: a long beige winter coat, a red scarf and black boots",
  views: "front view\nside view, facing left\nback view, from behind",
  name: "", stats: "JOB: MANGA ARTIST\nLIKES: COFFEE, DEADLINES (NOT)\nTOOL: DIP PEN", quote: "Seven pages by tomorrow?!",
  insets: "her black ribbon tie, close-up\na dip pen and an ink bottle, close-up",
  card_title: "Lucky dip pen", card_text: "Fumika's favourite pen. Every page drawn with it makes the deadline.",
  card_art: "a golden dip pen floating above an open sketchbook, glowing ink drops",
  chibi: "waving\nsleeping on a stack of paper\nholding a giant dip pen\ncrying with joy\ndrinking coffee\nthumbs up",
};

const FORM_KEY = "fumika-assets";
export const as = $state({
  form: { type: "expressions" as AssetType, source: "text" as Source, character: "", lora: "none", loraStrength: 1.0, loras: [] as LoraUse[], unet: "",
    style: "Anime colour" as Style, labels: true, transparent: false, versions: 2, fields: { ...START } as Record<string, string> },
  busy: false,
  err: "",
  msg: "",
});

export function saveForm() { try { localStorage.setItem(FORM_KEY, JSON.stringify(as.form)); } catch { /* not kept */ } }
export function initAssets() {
  try { const f = localStorage.getItem(FORM_KEY); if (f) { const v = JSON.parse(f); Object.assign(as.form, v, { fields: { ...START, ...v.fields } }); } }
  catch { /* defaults */ }
  // up to 0.1: one LoRA + strength
  if (!as.form.loras?.length && as.form.lora && as.form.lora !== "none") as.form.loras = [{ name: as.form.lora, strength: as.form.loraStrength }];
  as.form.loras ??= []; as.form.unet ??= "";
  if (!as.form.character.trim()) as.form.character = app.characters.split("\n").find((l) => l.includes(":")) ?? "";
}

export const enabled = () => app.plugins.some((p) => p.enabled && p.id === "asset-studio");
const item = (id: string) => app.catalog.find((c) => c.id === id);
/** CharRef is usable: the book has a reference picture and the CharRef LoRA is installed */
export const refReady = () => !!app.reference && !!item("charref_v2")?.installed;
/** background removal model installed */
export const cutReady = () => !!item("birefnet")?.installed;
export const canCut = () => CUTTABLE.includes(as.form.type);
/** the name in the first character line ("Fumika: ..." -> Fumika) */
export const who = () => (as.form.character.split(":")[0] || "").trim() || "character";

function vars() {
  const f = as.form, base = item(app.cfg?.base_model ?? ""), sft = item("sft_look"), pixel = f.type === "pixel";
  const fields: Record<string, string> = {};
  for (const fd of FIELDS[f.type]) if (f.fields[fd.key]?.trim()) fields[fd.key] = f.fields[fd.key].trim();
  const ref = f.source === "ref" && refReady();
  const cut = f.transparent && canCut() && cutReady();
  return {
    asset: f.type, character: f.character.trim(), style: f.style, fields: JSON.stringify(fields), labels: f.labels && !cut,
    loras: f.source === "lora" ? lorasJson(f.loras, pixel ? PIXEL_LORA_MAX : Infinity) : "[]",
    // the SFT look pulls pixel sheets back towards painted anime
    base_model: f.unet || (base?.installed ? base.file : ""), sft_look: app.sftLook && sft?.installed && !pixel ? sft.file : "",
    reference: ref ? app.reference : "", reference_lora: ref ? item("charref_v2")!.file : "",
    versions: f.versions, transparent: cut, bg_model: cut ? item("birefnet")!.file : "",
    seed: Math.floor(Math.random() * 2 ** 31),
    prefix: `fumika_assets/${projectName()}/${f.type}_${Date.now().toString(36)}`,
  };
}

const ref = (im: { filename: string; subfolder: string }): OutFile => ({ filename: im.filename, subfolder: im.subfolder });

/** the finished job's outputs: node 16 = sheet versions, node 18 = transparent sheets + sprites */
function fill(e: AssetEntry, job: Job) {
  const imgs = job.outputs?.["16"]?.images ?? [];
  const cut = job.outputs?.["18"];
  Object.assign(e, { state: "done", images: imgs.map(viewUrl), files: imgs.map(ref),
    cut: (cut?.images ?? []).map(viewUrl), cutFiles: (cut?.images ?? []).map(ref),
    sprites: (cut?.sprites ?? []).map(viewUrl), spriteFiles: (cut?.sprites ?? []).map(ref) });
}

export async function render() {
  if (!enabled() || !as.form.character.trim()) return;
  as.busy = true; as.err = ""; as.msg = ""; saveForm();
  const e: AssetEntry = { id: crypto.randomUUID(), asset: as.form.type, who: who(), created: Date.now(), state: "busy", images: [], files: [] };
  app.assets.unshift(e);
  const entry = app.assets[0];
  try {
    const id = await invoke<string>("queue_workflow", { project: projectName(), label: `asset-${as.form.type} ${who()}`,
      plugin: "asset-studio", workflow: "asset", vars: vars() });
    entry.jobId = id; save(); refreshJobs();
    as.busy = false;
    fill(entry, await waitJob(id));
  } catch (err) { Object.assign(entry, { state: "error", error: String(err) }); }
  as.busy = false;
  save();
}

/** assets that were rendering when the app closed: the persistent queue kept their jobs */
export function resumeAssets() {
  for (const e of app.assets) if (e.state === "busy" && e.jobId)
    waitJob(e.jobId).then((j) => fill(e, j), (err) => Object.assign(e, { state: "error", error: String(err) })).finally(save);
}

export function remove(e: AssetEntry) {
  app.assets = app.assets.filter((x) => x.id !== e.id); save();
}

export async function exportFiles(files: OutFile[]) {
  if (!inTauri() || !files.length) return;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const dir = await open({ directory: true });
  if (typeof dir !== "string") return;
  try { as.msg = t("as.exported", { n: await invoke<number>("export_outputs", { files, dir }), dir }); as.err = ""; }
  catch (err) { as.err = String(err); }
}

/** browser preview: a filled form and prototype renders from public/demo-assets (local only, gitignored) */
export function demoAssets() {
  as.form.character = app.characters.split("\n")[0];
  const d = (asset: AssetType, n: number, extra: Partial<AssetEntry> = {}): AssetEntry => ({ id: asset, asset, who: "Fumika",
    created: Date.now() - n * 600000, state: "done", images: [0, 1].map((k) => `/demo-assets/${asset}_${k}.png`), files: [], ...extra });
  app.assets = [d("expressions", 1), d("pixel", 2), d("profile", 3), d("outfits", 4), d("card", 5), d("chibi", 6), d("turnaround", 7)];
  if (new URLSearchParams(location.search).has("demo_busy"))
    app.assets.unshift({ id: "busy", asset: "expressions", who: "Fumika", created: Date.now(), state: "busy", images: [], files: [] });
}
