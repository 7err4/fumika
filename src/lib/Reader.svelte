<script lang="ts">
  // Read the open chapter, or the whole series: the series picture, then every chapter (its cover, its finished pages) in order.
  import { invoke } from "@tauri-apps/api/core";
  import { ChevronLeft, ChevronRight, FileDown } from "lucide-svelte";
  import { app, inTauri, type Page } from "./store.svelte";
  import { exportPdf } from "./pdf";
  import { t } from "./i18n.svelte";

  interface Sheet { url: string; chapter: number; chapterTitle: string; page: number }   // page 0 = cover
  let mode = $state<"chapter" | "series">("chapter");
  let series = $state<Sheet[]>([]), loading = $state(false);

  const chapterNo = $derived((app.seriesList.find((s) => s.id === app.seriesId)?.chapters.findIndex((c) => c.id === app.chapterId) ?? 0) + 1);
  const chapterSheets = $derived<Sheet[]>([
    ...(app.cover?.best ? [{ url: app.cover.best, chapter: chapterNo, chapterTitle: app.chapterTitle, page: 0 }] : []),
    ...app.pages.map((p, i) => ({ p, i })).filter(({ p }) => p.best).map(({ p, i }) => ({ url: p.best!, chapter: chapterNo, chapterTitle: app.chapterTitle, page: i + 1 })),
  ]);
  const sheets = $derived(mode === "series" ? series : chapterSheets);

  /** all chapters of the open series in their order (the open one from memory, the others from their files) */
  async function loadSeries() {
    loading = true;
    const meta = app.seriesList.find((s) => s.id === app.seriesId);
    const out: Sheet[] = [];
    if (app.seriesCover) out.push({ url: app.seriesCover, chapter: 0, chapterTitle: app.title, page: 0 });
    for (const [k, c] of (meta?.chapters ?? []).entries()) {
      let pages: Page[] = [], cover: Page | null = null, title = c.title;
      if (c.id === app.chapterId) { pages = app.pages; cover = app.cover; title = app.chapterTitle; }
      else if (inTauri()) {
        try { const d: any = await invoke("chapter_load", { series: app.seriesId, chapter: c.id }); pages = d.pages ?? []; cover = d.cover ?? null; title = d.title ?? title; }
        catch { /* chapter not saved yet */ }
      }
      if (cover?.best && cover.best !== app.seriesCover) out.push({ url: cover.best, chapter: k + 1, chapterTitle: title, page: 0 });
      pages.forEach((p, i) => { if (p.best) out.push({ url: p.best, chapter: k + 1, chapterTitle: title, page: i + 1 }); });
    }
    series = out; loading = false;
  }
  async function setMode(m: "chapter" | "series") {
    mode = m; cur = 0;
    if (m === "series") await loadSeries();
  }

  let cur = $state(0);
  const at = $derived(Math.max(0, Math.min(cur, sheets.length - 1)));
  const sheet = $derived(sheets[at]);
  const where = $derived(!sheet ? "" : sheet.chapter === 0 ? t("read.seriesCover")
    : `${t("proj.chapterN", { n: sheet.chapter })}${sheet.chapterTitle && sheet.chapterTitle !== t("proj.chapterN", { n: sheet.chapter }) ? " · " + sheet.chapterTitle : ""} · ${sheet.page ? t("page.n", { n: sheet.page }) : t("cover.title")}`);
  function key(e: KeyboardEvent) {
    if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
    // manga order: the right arrow goes back
    const next = app.direction === "rtl" ? "ArrowLeft" : "ArrowRight", prev = app.direction === "rtl" ? "ArrowRight" : "ArrowLeft";
    if (e.key === next) cur = Math.min(at + 1, sheets.length - 1);
    if (e.key === prev) cur = Math.max(at - 1, 0);
  }
</script>

<svelte:window onkeydown={key} />
<div class="reader">
  <header>
    <h1>{app.title} {#if mode === "chapter"}<small class="muted">· {app.chapterTitle}</small>{/if}</h1>
    <div class="seg" role="radiogroup" aria-label={t("read.mode")}>
      <button role="radio" aria-checked={mode === "chapter"} class:on={mode === "chapter"} onclick={() => setMode("chapter")}>{t("read.chapter")}</button>
      <button role="radio" aria-checked={mode === "series"} class:on={mode === "series"} onclick={() => setMode("series")}>{t("read.series")}</button>
    </div>
    <span class="muted">{sheets.length ? (mode === "series" ? `${where} · ${at + 1} / ${sheets.length}` : t("read.of", { n: at + 1, m: sheets.length })) : loading ? "…" : t("read.none")}</span>
    <span class="sp"></span>
    <button class="btn quiet" onclick={() => (cur = at - 1)} disabled={at <= 0} aria-label={t("read.prev")}><ChevronLeft size={16} /></button>
    <button class="btn quiet" onclick={() => (cur = at + 1)} disabled={at >= sheets.length - 1} aria-label={t("read.next")}><ChevronRight size={16} /></button>
    {#if mode === "chapter"}<button class="btn" onclick={exportPdf} disabled={!sheets.length}><FileDown size={15} /> PDF</button>{/if}
  </header>
  <div class="stage">
    {#if sheet}<img src={sheet.url} alt={where} />{:else if !loading}<p class="muted">{t("read.empty")}</p>{/if}
  </div>
</div>

<style>
  .reader { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  header { display: flex; align-items: center; gap: 12px; padding: 16px 28px; border-bottom: 1px dashed var(--nr); flex-wrap: wrap; }
  h1 { font-size: 18px; }
  .sp { flex: 1; }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius); padding: 2px; background: var(--sheet); }
  .seg button { border: 0; background: none; padding: 4px 10px; border-radius: 3px; color: var(--ink-2); font: inherit; font-size: 12.5px; cursor: pointer; }
  .seg button.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }
  .stage { flex: 1; min-height: 0; position: relative; display: grid; place-items: center; padding: 24px; }
  /* absolutely placed so the page always fits the stage (a grid row would grow to the image height and crop it) */
  img { position: absolute; inset: 24px; margin: auto; max-height: calc(100% - 48px); max-width: calc(100% - 48px);
    box-shadow: var(--lift); background: var(--sheet); }
</style>
