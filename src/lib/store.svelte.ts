// App state (Svelte 5 runes) shared by all views. Talks to the Rust core only through Tauri commands / events.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { renderPage, waitFor, waitJob, cancelProject, splitPages, type Job } from "../comfy";
import { t, applyPrefs, prefs } from "./i18n.svelte";
import { scenePage, type Scene } from "./scene";
import { adv, pageVars, type Adv } from "./expert";
import { lorasJson, setFamilies, type FamilyDef, type LoraUse } from "./families";

export type Section = "project" | "library" | "assets" | "image" | "queue" | "trainer" | "setup" | "reader";
export interface Cfg { install_dir: string | null; port: number; base_model: string; mcp_enabled: boolean; mcp_port: number; mcp_token: string;
  plugins: string[] | null; close_action?: string; export_strip_prompt?: boolean }
export interface Item { id: string; name: string; file: string; dest: string; url: string; size: number; kind: string; group: string; note: string;
  license: string; license_url: string; license_noncommercial: boolean; plugins: string[]; installed: boolean; partial_bytes: number }
/** one plugin card (plugins_list): manifest + state */
export interface PluginInfo { id: string; name: string; version: string; author: string; description: string; kinds: string[]; family: string;
  family_def?: FamilyDef; requires?: string[]; requires_one?: string[];
  content: string; license: string; ui: string[]; models: Item[]; bundled: boolean; enabled: boolean; download_bytes: number;
  noncommercial_models: string[] }
export interface Page { text: string; best?: string; versions?: string[]; state: "todo" | "busy" | "done" | "error"; error?: string;
  jobId?: string; started?: number; seconds?: number;
  /** the text changed after it was drawn: the old versions stay (shown faded) until it is drawn again */ stale?: boolean;
  /** gibberish bubbles found in the kept version (shown in red pencil) */ strays?: number;
  /** live sampler progress from the engine (not saved) */ progress?: Progress;
  /** the chapter cover (drawn like a page; text = what the cover shows, title + chapter are written on it) */ cover?: boolean }
export interface Progress { id: string; step: number; steps: number; pass: number; passes: number }
/** a file in ComfyUI/output (export) */
export interface OutFile { filename: string; subfolder: string }
/** one Asset Studio render (plugins/asset-studio): the sheet versions, optional transparent sheets + cut sprites */
export interface AssetEntry { id: string; asset: string; who: string; created: number; state: "busy" | "done" | "error"; jobId?: string;
  images: string[]; files: OutFile[]; cut?: string[]; cutFiles?: OutFile[]; sprites?: string[]; spriteFiles?: OutFile[]; error?: string }
/** a comic project = a series (cast, style, model settings) with chapters (story, scenes, pages); projects.rs stores them */
export interface ChapterMeta { id: string; title: string }
export interface SeriesMeta { id: string; title: string; chapters: ChapterMeta[]; current?: string }
/** GPU lock (gpulock.rs): a running training holds back new renders unless overridden */
export interface Gate { training: string | null; overridden: boolean; paused: boolean }

const KEY = "fumika-project";
// SFW example so a fresh install shows a working project: "DEADLINE!" with Fumika, the mascot (same story as the bundled
// node defaults, src-tauri/resources/custom_nodes/ComfyUI-MOSS-Doujin/example_workflows/advanced/deadline_story_example.txt)
const EXAMPLE_CHARS = "Fumika: an adult manga artist in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes, white oversized shirt with rolled-up sleeves, black ribbon tie, black pleated skirt\n" +
  "Sora: her editor, an adult woman with short silver hair and glasses, navy blazer, white blouse, grey pencil skirt\n" +
  "Casual Fumika: Fumika, an adult woman in her twenties with glossy black hair in a messy low ponytail with one light-blue streak in her bangs, light-blue eyes, in a grey oversized hoodie and black shorts";
const EXAMPLE_STORY = "Fumika grins at the viewer holding up a dip pen in front of a pile of manga pages | #DEADLINE! | ##by Fumika\n\n" +
  "Fumika sags over a blank manga page at her desk late at night, a cold coffee mug beside her | Nothing...\n" +
  "Her phone lights up on the desk with a message from Sora | !BZZT\n" +
  "Close-up of Fumika, panicking | Seven pages by tomorrow?!\n\n" +
  "Fumika stares out of the window at the city lights, deep in thought | ...\n" +
  "Fumika's eyes light up, a light bulb above her head | That's it!\n" +
  "Fumika inks a page at full speed, ink drops flying | !SCRATCH SCRATCH\n\n" +
  "Morning sun through the window, Fumika asleep on her desk on a stack of finished pages | Zzz...\n" +
  "Sora opens the door holding two coffees, surprised | Sora: Fumika...?\n" +
  "Sora smiles at the finished pages, Fumika gives a sleepy thumbs up | Fumika: Made it... | +Fumika: Seven pages.\n\n" +
  "Casual Fumika walks out into the morning street, stretching, the sun rising behind the buildings | Free at last!\n" +
  "Close-up of Casual Fumika yawning | ...Bed.";

export const app = $state({
  section: "project" as Section,
  cfg: null as Cfg | null,
  catalog: [] as Item[],
  plugins: [] as PluginInfo[],
  pluginsChosen: true,
  loras: [] as [string, number][],
  server: { installed: false, running: false, port: 0, log_tail: "", version: null as string | null, version_ok: true, ui: false },
  // the open series (title = series title) and chapter; everything below up to `assets` belongs to one of them (see seriesData)
  seriesList: [] as SeriesMeta[],
  seriesId: "",
  chapterId: "",
  chapterTitle: "",
  cover: null as Page | null,   // chapter cover
  seriesCover: "",              // picture of the series (a chapter cover chosen for it)
  title: "Deadline",
  style: "Colour manga",
  characters: EXAMPLE_CHARS,
  story: EXAMPLE_STORY,
  lora: "none",   // up to 0.1: one LoRA per book (read once into loraList)
  loraList: [] as LoraUse[],   // any number of LoRAs for the pages, in order
  unet: "",       // checkpoint of this book ("" = the base model chosen in Setup)
  modelFiles: { diffusion: [] as string[], loras: [] as string[] },   // engine model folders (list_models), sub-folders included
  quality: false,
  sftLook: true,   // SFT look LoRA at 1.5 on every page (when installed)
  reference: "",   // CharRef: picture of the main character in ComfyUI/input ("fumika_refs/x.png"), "" = none
  direction: "ltr" as "ltr" | "rtl",   // reading direction: left to right (English text) / right to left (manga order)
  refChar: "",     // which character from the list the picture shows ("" = the first one); her written look is ignored then
  pages: [] as Page[],
  scenes: [] as Scene[],
  adv: adv() as Adv,   // expert settings of this project (used only while expert mode is on in Setup)   // pages with a shared place / cast / outfit state (scene.ts); written into the panels when drawn
  selected: 0,
  jobs: [] as Job[],
  progress: {} as Record<string, string>,
  gpu: null as [number, number] | null,   // VRAM used / total MB
  now: Date.now(),                        // 1 s ticker for the running-page estimate
  busy: false,
  engineNote: "",   // "python:<plugin name>" while a plugin's Python packages are installed (engine-note event)
  assets: [] as AssetEntry[],
  gate: { training: null, overridden: false, paused: false } as Gate,
});

/** average seconds of this project's finished pages (45 s until one is known) */
export const avgSeconds = () => {
  const s = app.pages.filter((p) => p.seconds).map((p) => p.seconds!);
  return s.length ? s.reduce((a, b) => a + b, 0) / s.length : 45;
};
export const projectName = () => app.title.replace(/[^\w\- ]/g, "").trim() || "doujin";
/** the queue's project of a chapter's pages (also what "Stop" cancels) */
const jobProject = (title: string, chapter: string) => `${title.replace(/[^\w\- ]/g, "").trim() || "doujin"} · ${chapter.trim() || "1"}`;
const newId = (p: string) => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

/** what a series file holds: the cast and everything that stays the same from chapter to chapter */
function seriesData() {
  const meta = app.seriesList.find((x) => x.id === app.seriesId);
  return { id: app.seriesId, title: app.title, chapters: meta?.chapters ?? [], current: app.chapterId, style: app.style,
    characters: app.characters, loraList: app.loraList, unet: app.unet, sftLook: app.sftLook, reference: app.reference, refChar: app.refChar,
    direction: app.direction, adv: app.adv, assets: app.assets, cover: app.seriesCover };
}
/** what a chapter file holds: its story, scenes and pages (page numbers start at 1 in every chapter) */
function chapterData() {
  const clean = ({ progress, ...p }: Page) => p;
  return { id: app.chapterId, title: app.chapterTitle, story: app.story, scenes: app.scenes, pages: app.pages.map(clean),
    cover: app.cover ? clean(app.cover) : null };
}
function applySeries(p: any) {
  Object.assign(app, { seriesId: p.id, title: p.title ?? "", style: p.style ?? "Colour manga", characters: p.characters ?? "",
    loraList: p.loraList ?? (p.lora && p.lora !== "none" ? [{ name: p.lora, strength: 1 }] : []), unet: p.unet ?? "", sftLook: p.sftLook ?? true,
    reference: p.reference ?? "", refChar: p.refChar ?? "", direction: p.direction === "rtl" ? "rtl" : "ltr", adv: adv(p.adv), assets: p.assets ?? [],
    seriesCover: p.cover ?? "" });
}
function applyChapter(c: any) {
  Object.assign(app, { chapterId: c.id, chapterTitle: c.title ?? "", story: c.story ?? "", scenes: c.scenes ?? [], pages: c.pages ?? [],
    cover: c.cover ?? null });
  app.selected = 0;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
async function writeNow() {
  saveTimer = null;
  if (!inTauri() || !app.seriesId || !app.chapterId) {
    try { localStorage.setItem(KEY, JSON.stringify({ ...seriesData(), ...chapterData() })); } catch { /* demo only */ }
    return;
  }
  const meta = app.seriesList.find((x) => x.id === app.seriesId);
  if (meta) { meta.title = app.title; const ch = meta.chapters.find((c) => c.id === app.chapterId); if (ch) ch.title = app.chapterTitle; meta.current = app.chapterId; }
  try {
    await invoke("series_save", { id: app.seriesId, data: seriesData() });
    await invoke("chapter_save", { series: app.seriesId, chapter: app.chapterId, data: chapterData() });
  } catch (e) { console.error("save failed", e); }
}
/** save the open series + chapter (debounced: the editors call this on every change) */
export function save() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(writeNow, 250);
}
async function flush() { if (saveTimer) { clearTimeout(saveTimer); await writeNow(); } }

/** a page of a chapter that is not open any more finished: write the result into that chapter's file */
async function persistPage(sid: string, cid: string, p: Page) {
  if (sid === app.seriesId && cid === app.chapterId) { save(); return; }
  try {
    const c: any = await invoke("chapter_load", { series: sid, chapter: cid });
    const { progress, ...clean } = p;
    if (p.cover) { if (c.cover?.jobId !== p.jobId) return; c.cover = clean; }
    else {
      const i = (c.pages ?? []).findIndex((x: Page) => x.jobId && x.jobId === p.jobId);
      if (i < 0) return;
      c.pages[i] = clean;
    }
    await invoke("chapter_save", { series: sid, chapter: cid, data: c });
  } catch (e) { console.error("saving a finished page failed", e); }
}
/** pages that were drawing when the app closed or the chapter was left: the persistent queue kept their jobs */
function resumePages() {
  const sid = app.seriesId, cid = app.chapterId;
  [...app.pages, ...(app.cover ? [app.cover] : [])].forEach((p) => {
    if (p.state === "busy" && p.jobId) waitFor(p.jobId).then((r) => finish(p, r),
      (e) => Object.assign(p, { state: "error", error: String(e), progress: undefined })).finally(() => persistPage(sid, cid, p));
  });
}

/** open a chapter of the open series */
export async function openChapter(cid: string) {
  if (cid === app.chapterId) return;
  await flush();
  let c: any;
  try { c = await invoke("chapter_load", { series: app.seriesId, chapter: cid }); } catch { c = { id: cid, title: "", story: "", scenes: [], pages: [] }; }
  applyChapter({ ...c, id: cid });
  syncPages(); resumePages(); save();
}
/** open another series (its last open chapter) */
export async function openSeries(sid: string) {
  if (sid === app.seriesId) return;
  await flush();
  const meta = app.seriesList.find((x) => x.id === sid);
  if (!meta) return;
  const r = await invoke<{ series: any[] }>("projects_list");
  const full = r.series.find((x) => x.id === sid) ?? meta;
  applySeries(full);
  app.chapterId = "";
  const cid = full.current && meta.chapters.some((c) => c.id === full.current) ? full.current : meta.chapters[0]?.id;
  if (cid) await openChapter(cid);
}
/** a new series with one empty chapter */
export async function newSeries() {
  await flush();
  const sid = newId("s"), cid = newId("c");
  app.seriesList.unshift({ id: sid, title: t("proj.untitled"), chapters: [{ id: cid, title: t("proj.chapterN", { n: 1 }) }], current: cid });
  applySeries({ id: sid, title: t("proj.untitled") });
  applyChapter({ id: cid, title: t("proj.chapterN", { n: 1 }) });
  syncPages(); await writeNow();
  app.section = "project";
}
export async function newChapter() {
  const meta = app.seriesList.find((x) => x.id === app.seriesId);
  if (!meta) return;
  await flush();
  const cid = newId("c"), title = t("proj.chapterN", { n: meta.chapters.length + 1 });
  meta.chapters.push({ id: cid, title });
  applyChapter({ id: cid, title });
  syncPages(); await writeNow();
  app.section = "project";
}
export function moveChapter(cid: string, by: -1 | 1) {
  const meta = app.seriesList.find((x) => x.id === app.seriesId);
  if (!meta) return;
  const i = meta.chapters.findIndex((c) => c.id === cid), j = i + by;
  if (i < 0 || j < 0 || j >= meta.chapters.length) return;
  [meta.chapters[i], meta.chapters[j]] = [meta.chapters[j], meta.chapters[i]];
  save();
}
/** delete a chapter (a series keeps at least one); the file goes to projects/_deleted */
export async function deleteChapter(cid: string) {
  const meta = app.seriesList.find((x) => x.id === app.seriesId);
  if (!meta || meta.chapters.length < 2) return;
  const i = meta.chapters.findIndex((c) => c.id === cid);
  meta.chapters.splice(i, 1);
  await invoke("chapter_delete", { series: app.seriesId, chapter: cid }).catch(() => {});
  if (cid === app.chapterId) { app.chapterId = ""; await openChapter(meta.chapters[Math.max(0, i - 1)].id); } else save();
}
/** delete a series with its chapters (moved to projects/_deleted); the last one is replaced by a new empty series */
export async function deleteSeries(sid: string) {
  await invoke("series_delete", { id: sid }).catch(() => {});
  app.seriesList = app.seriesList.filter((x) => x.id !== sid);
  if (sid !== app.seriesId) return;
  app.seriesId = ""; app.chapterId = "";
  if (app.seriesList.length) await openSeries(app.seriesList[0].id); else await newSeries();
}

/** first start with series files: take over the single project of 0.1 betas, else create the example "Deadline" */
async function loadProjects() {
  const r = await invoke<{ exists: boolean; series: any[] }>("projects_list");
  if (!r.exists || !r.series.length) {
    let old: any = null;
    try { old = JSON.parse(localStorage.getItem(KEY) || "null"); } catch { /* none */ }
    const sid = newId("s"), cid = newId("c");
    if (!r.exists && old) {   // the beta's one project becomes series + chapter 1
      applySeries({ ...old, id: sid });
      applyChapter({ id: cid, title: t("proj.chapterN", { n: 1 }), story: old.story, scenes: old.scenes, pages: old.pages });
    } else if (!r.exists) {   // very first start: the example series
      applySeries({ id: sid, title: "Deadline", characters: EXAMPLE_CHARS });
      applyChapter({ id: cid, title: t("proj.chapterN", { n: 1 }), story: EXAMPLE_STORY });
    } else {                  // every series was deleted: start with an empty one
      applySeries({ id: sid, title: t("proj.untitled") });
      applyChapter({ id: cid, title: t("proj.chapterN", { n: 1 }) });
    }
    app.seriesList = [{ id: sid, title: app.title, chapters: [{ id: cid, title: app.chapterTitle }], current: cid }];
    syncPages(); await writeNow();
    return;
  }
  app.seriesList = r.series.map((x) => ({ id: x.id, title: x.title, chapters: x.chapters ?? [], current: x.current }));
  let last = "";
  try { last = localStorage.getItem(KEY + "-open") || ""; } catch { /* none */ }
  const first = r.series.find((x) => x.id === last) ?? r.series[0];
  applySeries(first);
  const cid = first.current && (first.chapters ?? []).some((c: ChapterMeta) => c.id === first.current) ? first.current : first.chapters?.[0]?.id;
  if (cid) {
    let c: any;
    try { c = await invoke("chapter_load", { series: first.id, chapter: cid }); } catch { c = { title: "" }; }
    applyChapter({ ...c, id: cid });
  }
  syncPages();
}
$effect.root(() => { $effect(() => { const id = app.seriesId; if (id) try { localStorage.setItem(KEY + "-open", id); } catch { /* private window */ } }); });

/** story text -> page list, keeping finished pages whose text did not change */
export function syncPages() {
  const blocks = splitPages(app.story);
  // a changed page keeps its versions (an edit in the story editor should not throw finished renders away)
  app.pages = blocks.map((b, i) => {
    const o = app.pages[i];
    if (o && o.text === b) return o;
    if (o?.best && o.state !== "busy") return { ...o, text: b, state: "todo" as const, stale: true, error: undefined, strays: undefined, progress: undefined };
    return { text: b, state: "todo" as const };
  });
  if (app.selected >= app.pages.length) app.selected = Math.max(0, app.pages.length - 1);
  save();
}

/** replace one page's text inside the story */
export function setPageText(i: number, text: string) {
  const blocks = splitPages(app.story);
  blocks[i] = text.trim();
  app.story = blocks.join("\n\n");
  syncPages();
}

export function addPage() {
  app.story = (app.story.trim() + "\n\n" + t("ed.newPage")).trim();
  syncPages();
  app.selected = app.pages.length - 1;
}

let abort: AbortController | null = null;

/** the CharRef LoRA file when a reference picture is set and the LoRA is installed, "" otherwise */
export function refLora(): string {
  const c = app.catalog.find((x) => x.id === "charref_v2");
  return app.reference && c?.installed ? c.file : "";
}

/** the user picked a reference picture: copy it into ComfyUI/input/fumika_refs */
export async function setReference(path: string | null) {
  app.reference = path ? await invoke<string>("import_reference", { path }) : "";
  save();
}

/** a page job finished: keep its images and how long it drew (also for jobs resumed after an app restart) */
// Redrawing keeps the earlier versions (user 21 Oct): new ones first, the old ones after; only removeVersion drops one.
function finish(p: Page, r: { best: string; versions: string[] }) {
  const versions = [...new Set([...r.versions, ...(p.versions ?? [])].filter(Boolean))];
  Object.assign(p, { best: r.best, versions, state: "done", stale: false, progress: undefined,
    seconds: p.started ? Math.round((Date.now() - p.started) / 1000) : undefined });
}

/** take a version off the page (the image file stays in the engine's output folder); returns the versions left */
export function removeVersion(i: number, v: number): string[] {
  const p = app.pages[i];
  const vs = (p.versions ?? []).filter(Boolean);
  if (vs.length < 2 || !vs[v]) return vs;
  const gone = vs.splice(v, 1)[0];
  p.versions = vs;
  if (p.best === gone) p.best = vs[0];
  save();
  return vs;
}

/** everything a page render needs, taken when it is queued (opening another chapter meanwhile changes nothing) */
function context() {
  return { sid: app.seriesId, cid: app.chapterId, project: jobProject(app.title, app.chapterTitle), title: app.title, chapterTitle: app.chapterTitle,
    style: app.style, characters: app.characters,
    loraList: $state.snapshot(app.loraList), unet: app.unet, sftLook: app.sftLook, reference: app.reference, refChar: app.refChar,
    direction: app.direction, quality: app.quality, adv: $state.snapshot(app.adv), scenes: $state.snapshot(app.scenes) };
}
export async function drawPage(i: number, submitted = () => {}, ctx = context(), p = app.pages[i]) {
  const base = app.catalog.find((c) => c.id === app.cfg?.base_model);
  const sft = app.catalog.find((c) => c.id === "sft_look");
  const ref = refLora();
  Object.assign(p, { state: "busy", error: undefined, started: undefined, progress: undefined, strays: undefined });
  try {
    // a cover: one panel with what it shows, the series title and the chapter written on it; pages: scenes into every panel
    const sp = p.cover ? { page: `${p.text.replace(/\n+/g, " ").trim()} | #${ctx.title} | ##${ctx.chapterTitle}`, characters: ctx.characters }
      : scenePage(p.text, i, ctx.scenes, ctx.characters);
    const r = await renderPage({ style: ctx.style, characters: sp.characters, page: sp.page, lora: "", loras: lorasJson(ctx.loraList),
      base_model: ctx.unet || (base?.installed ? base.file : ""), sft_look: ctx.sftLook && sft?.installed ? sft.file : "",
      reference: ref && ctx.reference ? ctx.reference : "", reference_lora: ctx.reference ? ref : "", reference_character: ctx.refChar,
      reading_direction: ctx.direction === "rtl" ? "right to left" : "left to right", quality: ctx.quality,
      ...pageVars(ctx.adv, prefs.expert, () => Math.floor(Math.random() * 2 ** 31), i),
      prefix: `doujin_studio/${ctx.sid || projectName()}/${ctx.cid || "c"}/${p.cover ? "cover" : "p" + String(i + 1).padStart(2, "0")}` },
      ctx.project, p.cover ? "Cover" : `Page ${i + 1}`, (id) => { p.jobId = id; persistPage(ctx.sid, ctx.cid, p); submitted(); }, abort?.signal);
    finish(p, r);
  } catch (e) { Object.assign(p, { state: "error", error: String(e), progress: undefined }); }
  submitted();
  persistPage(ctx.sid, ctx.cid, p);
}

/** freeze the look: the WD tagger reads the clothes on the scene's first page (its chosen version); every item gets the
 *  concrete wording the page shows ("patterned scarf" -> "grey checkered scarf"), used on all later panels of the scene */
export async function freezeScene(s: Scene) {
  const p = app.pages[s.from];
  if (!p?.best) throw new Error(t("scene.freezeNeedsPage", { n: s.from + 1 }));
  const u = new URL(p.best, location.href);
  const page = [u.searchParams.get("subfolder"), u.searchParams.get("filename")].filter(Boolean).join("/");
  const items = [...new Set(s.cast.flatMap((c) => c.items.map((it) => it.wording.trim()).filter(Boolean)))];
  if (!items.length) throw new Error(t("scene.freezeNoItems"));
  const id = await invoke<string>("queue_workflow", { project: jobProject(app.title, app.chapterTitle), label: `freeze ${s.name}`, plugin: "moss-doujin",
    workflow: "freeze", vars: { page, items: items.join("\n") } });
  const job = await waitJob(id);
  const r = JSON.parse(job.outputs?.["1"]?.text?.[0] ?? "{}") as { items?: Record<string, string>; tags?: string[] };
  for (const c of s.cast) for (const it of c.items) {
    const f = r.items?.[it.wording.trim()];
    it.frozen = f && f !== it.wording.trim() ? f : undefined;
  }
  s.frozenFrom = s.from;
  save();
}

/** the default cover description (English, it goes into the prompt): the first character of the cast on the cover */
export function coverText(): string {
  const who = app.characters.split("\n")[0]?.split(":")[0]?.trim();
  return `${who || "The main character"} on the cover of a manga chapter, dynamic pose, eye-catching composition, no speech bubbles`;
}
/** draw (or redraw) the chapter cover */
export async function drawCover() {
  if (!app.cover) app.cover = { text: coverText(), state: "todo", cover: true };
  await drawPage(0, () => {}, context(), app.cover);
}
export function pickCoverVersion(v: number) {
  if (app.cover?.versions?.[v]) { app.cover.best = app.cover.versions[v]; save(); }
}

export async function renderBook() {
  syncPages();
  abort = new AbortController();
  app.busy = true;
  // queue the pages one after another so the render order is the page order, then wait for all of them
  const all: Promise<void>[] = [];
  const ctx = context(), pages = app.pages;   // this chapter, even if another one is opened while the pages are queued
  for (const [i, p] of pages.entries()) {
    if (p.state === "done" || p.state === "busy") continue;
    await new Promise<void>((queued) => all.push(drawPage(i, queued, ctx, p)));
  }
  await Promise.all(all);
  app.busy = false;
}

export async function stopBook() {
  abort?.abort();
  await cancelProject(jobProject(app.title, app.chapterTitle));
  app.busy = false;
}

export function pickVersion(i: number, v: number) {
  const p = app.pages[i];
  if (p.versions?.[v]) { p.best = p.versions[v]; save(); }
}

export async function refreshServer() {
  try { app.server = await invoke("server_status"); } catch { /* not configured */ }
}
export async function refreshModels() {
  app.catalog = await invoke("catalog_status");
  app.loras = await invoke("list_loras");
  try {
    const [d, l] = await Promise.all([invoke<[string, number][]>("list_models", { kind: "diffusion_models" }),
      invoke<[string, number][]>("list_models", { kind: "loras" })]);
    app.modelFiles = { diffusion: d.map((x) => x[0]), loras: l.map((x) => x[0]) };
  } catch { /* engine not installed yet */ }
}
export async function refreshJobs() {
  try { app.jobs = await invoke<Job[]>("queue_list", {}); } catch { /* core not ready */ }
}
/** an app area that some switched-on plugin brings ("comic", "trainer") */
export const hasUi = (ui: string) => app.plugins.some((p) => p.enabled && p.ui.includes(ui));
export async function refreshPlugins() {
  const r = await invoke<{ chosen: boolean; plugins: PluginInfo[] }>("plugins_list");
  app.plugins = r.plugins; app.pluginsChosen = r.chosen;
  // the architectures the app offers = the switched-on model family plugins
  setFamilies(r.plugins.filter((p) => p.enabled && p.family_def).map((p) => p.family_def!));
}
export async function setPlugins(ids: string[]) {
  try {
    return await invoke<string[]>("plugins_set", { ids });
  } finally {
    // the core adds the plugins the choice requires (model families) and saves before it installs: reload also when the
    // node / pip install failed, or the cards and a later saveCfg work with the old list
    app.cfg = await invoke("get_config");
    await refreshPlugins(); await refreshModels().catch(() => {});
  }
}
export async function saveCfg() { if (app.cfg) await invoke("set_config", { new: app.cfg }); }

const demoPlugin = (id: string, name: string, kinds: string[], family: string, ui: string[], gb: number, nc: string[] = []): PluginInfo =>
  ({ id, name, version: "1.0.0", author: "7err4", description: "", kinds, family, content: "sfw", license: "GPL-3.0", ui, models: [],
    bundled: true, enabled: true, download_bytes: gb * 1e9, noncommercial_models: nc });
const DEMO_PLUGINS = [demoPlugin("family-moss", "MOSS-Image", ["family"], "MOSS-Image", [], 21.4),
  demoPlugin("family-anima", "Anima", ["family"], "Anima", [], 5.6, ["Anima Base v1.0"]),
  { ...demoPlugin("family-sdxl", "SDXL / Illustrious", ["family"], "SDXL / Illustrious", [], 6.9), enabled: false },
  { ...demoPlugin("anima-lora-trainer", "Anima LoRA Trainer", ["train"], "Anima", ["trainer"], 0, ["Anima Base v1.0"]), requires: ["family-anima"] },
  { ...demoPlugin("asset-studio", "Asset Studio", ["generate"], "MOSS-Image", ["assets"], 0.4), requires: ["family-moss"] },
  { ...demoPlugin("image-studio", "Image Studio", ["generate"], "any", ["image"], 0.07), requires_one: ["family-moss", "family-anima", "family-sdxl"] },
  { ...demoPlugin("moss-doujin", "MOSS Doujin", ["generate"], "MOSS-Image", ["comic"], 0), requires: ["family-moss"] },
  { ...demoPlugin("moss-lora-trainer", "MOSS LoRA Trainer", ["train"], "MOSS-Image", ["trainer"], 0), requires: ["family-moss"] },
  { ...demoPlugin("slider-trainer", "Slider Trainer", ["train"], "Anima", ["trainer"], 0), requires_one: ["family-anima", "family-anima38"] }];

/** plain browser (vite dev without Tauri): show the layout with demo states instead of failing on invoke */
export const inTauri = () => typeof (window as any).__TAURI_INTERNALS__ !== "undefined";

export async function boot() {
  applyPrefs();
  if (!inTauri()) {
    app.seriesList = [{ id: "demo", title: "Deadline", chapters: [{ id: "c1", title: "Chapter 1" }, { id: "c2", title: "Chapter 2" }], current: "c1" },
      { id: "demo2", title: "Summer Camp", chapters: [{ id: "c1", title: "Chapter 1" }] }];
    Object.assign(app, { seriesId: "demo", chapterId: "c1", chapterTitle: "Chapter 1" });
    syncPages();
    const demo: Page["state"][] = ["done", "done", "error", "busy", "busy", "todo"];
    app.pages.forEach((p, i) => Object.assign(p, { state: demo[i] ?? "todo", seconds: demo[i] === "done" ? 44 : undefined,
      error: demo[i] === "error" ? t("demo.gibberish") : undefined, strays: demo[i] === "error" ? 4 : undefined,
      versions: demo[i] === "done" ? ["", "", ""] : undefined, jobId: demo[i] === "busy" ? `demo${i}` : undefined }));
    app.jobs = [{ id: "demo3", project: "Deadline", label: "Page 4", state: "running", outputs: null, error: null },
      { id: "demo4", project: "Deadline", label: "Page 5", state: "queued", outputs: null, error: null }];
    app.server = { installed: true, running: true, port: 8291, log_tail: "", version: "0.42.1", version_ok: true, ui: true };
    app.plugins = DEMO_PLUGINS;
    const q = new URLSearchParams(location.search);
    const sec = q.get("section") as Section | null;   // ?section=setup: preview captures
    if (sec) app.section = sec;
    if (q.has("sel")) app.selected = Math.min(app.pages.length - 1, Number(q.get("sel")) || 0);   // ?sel=3: page 4 in the inspector
    if (q.has("demo_pages")) {   // ?demo_pages: real renders from public/demo-pages (local only, gitignored) for screenshots
      const full = Number(q.get("demo_pages")) || 0;   // =1: every page finished
      app.pages.forEach((p, i) => {
        if (full || p.state === "done") Object.assign(p, { state: "done", error: undefined, strays: undefined, jobId: undefined, progress: undefined,
          seconds: 44 + 7 * i, best: `/demo-pages/p${String(i + 1).padStart(2, "0")}.png`,
          versions: [0, 1, 2].map((k) => `/demo-pages/p${String(i + 1).padStart(2, "0")}_v${k}.png`) });
      });
      if (full) app.jobs = [];
    }
    if (q.has("gate")) app.gate = { training: "moss_image_train_network.py · terra_moss_v1", overridden: false, paused: true };
    app.gpu = [21400, 32607];
    app.pages[3].started = Date.now() - 26000;
    app.pages[3].progress = { id: "demo3", step: 31, steps: 50, pass: 2, passes: 3 };
    setInterval(() => (app.now = Date.now()), 1000);
    return;
  }
  app.cfg = await invoke("get_config");
  await refreshPlugins().catch(() => {});
  await loadProjects().catch((e) => console.error("projects", e));
  resumePages();
  await refreshModels().catch(() => {});
  await refreshServer();
  await refreshJobs();
  try { app.gate = await invoke<Gate>("queue_gate"); } catch { /* older core */ }
  listen<Gate>("queue-gate", (ev) => { app.gate = ev.payload; });
  listen<string>("engine-note", (ev) => { app.engineNote = ev.payload; });
  if (!app.pluginsChosen) app.section = "setup";   // first start: choose plugins
  else if (!app.cfg?.install_dir || !app.server.installed) { if (!app.server.running) app.section = "setup"; }
  else if (!app.server.running) invoke("server_start").catch(() => {});
  listen<Job>("job-update", (ev) => {
    // the estimate on a drawing page starts when its job reaches the engine, not when it was queued
    if (ev.payload.state === "running") { const p = app.pages.find((x) => x.jobId === ev.payload.id); if (p) { p.started = Date.now(); save(); } }
    refreshJobs();
  });
  listen<Progress>("job-progress", (ev) => {
    const p = app.pages.find((x) => x.jobId === ev.payload.id);
    if (p && p.state === "busy") p.progress = ev.payload;
  });
  listen<any>("dl-progress", (ev) => {
    const p = ev.payload;
    app.progress[p.id] = p.state === "running" ? `${(p.done / 1e9).toFixed(1)} / ${(p.total / 1e9).toFixed(1)} GB · ${p.mb_per_s.toFixed(0)} MB/s`
      : p.state === "done" ? t("dl.done") : `${p.state}: ${p.message}`;
    if (p.state !== "running") refreshModels();
  });
  setInterval(refreshServer, 3000);
  const gpu = async () => { try { app.gpu = await invoke("gpu_usage"); } catch { /* no GPU */ } };
  gpu(); setInterval(gpu, 5000);
  setInterval(() => (app.now = Date.now()), 1000);
}
