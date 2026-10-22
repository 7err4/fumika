<script lang="ts">
  import { Plus, Play, Square, FileDown, BookImage, Package } from "lucide-svelte";
  import { app, renderBook, stopBook, addPage, avgSeconds, save } from "./store.svelte";
  import PageCell from "./PageCell.svelte";
  import { t } from "./i18n.svelte";
  import Inspector from "./Inspector.svelte";
  import { exportPdf } from "./pdf";
  import { exportCbz } from "./cbz";
  import CoverDialog from "./CoverDialog.svelte";
  let coverOpen = $state(false), note = $state("");
  async function cbz() { try { const n = await exportCbz(); if (n) note = t("cbz.done", { n }); } catch (e) { note = String(e); } }

  const done = $derived(app.pages.filter((p) => p.state === "done").length);
  const busy = $derived(app.pages.filter((p) => p.state === "busy").length);
  const open = $derived(app.pages.filter((p) => p.state === "todo" || p.state === "error").length);
  const avg = $derived(avgSeconds());
  const remaining = $derived(Math.max(1, Math.round(((busy + open) * avg) / 60)));
  // queue order of the waiting jobs: position 0 = drawing now (the running job leads, like the Inspector's queue)
  const order = $derived(app.jobs.filter((j) => j.state === "queued" || j.state === "running")
    .sort((a, b) => (a.state === "running" ? -1 : b.state === "running" ? 1 : 0)).map((j) => j.id));
  const summary = $derived([t("ws.pages", { n: app.pages.length }), t("ws.done", { n: done }), busy ? t("ws.queued", { n: busy }) : "",
    open ? t("ws.open", { n: open }) : "", busy + open ? t("ws.left", { m: remaining }) : ""].filter(Boolean).join(" · "));
  const pos = (jobId?: string) => {
    const i = jobId ? order.indexOf(jobId) : -1;
    return i < 0 ? 0 : i;
  };
</script>

<div class="ws">
  <header class="top">
    <div class="title">
      <div class="names">
        <input class="name" bind:value={app.title} oninput={save} aria-label={t("ws.title")} />
        <span class="sep">·</span>
        <input class="chapter" bind:value={app.chapterTitle} oninput={save} aria-label={t("ws.chapter")} placeholder={t("ws.chapter")} />
      </div>
      <p class="muted">{summary}</p>
    </div>
    <div class="actions">
      <button class="btn quiet" onclick={exportPdf} disabled={!done}><FileDown size={15} /> PDF</button>
      <button class="btn quiet" onclick={cbz} disabled={!done} title={t("cbz.tip")}><Package size={15} /> CBZ</button>
      {#if app.busy || busy}
        <button class="btn" onclick={stopBook}><Square size={14} /> {t("ws.stop")}</button>
      {/if}
      <button class="btn primary" onclick={renderBook} disabled={!app.server.running || open === 0}>
        <Play size={14} /> {t("ws.render")}
      </button>
    </div>
  </header>

  <div class="body">
    <section class="sheet" aria-label={t("ws.sheet")}>
      <button class="cover" class:has={!!app.cover?.best} class:busy={app.cover?.state === "busy"} onclick={() => (coverOpen = true)} title={t("cover.title")}>
        {#if app.cover?.best}<img src={app.cover.best} alt={t("cover.title")} />{:else}<BookImage size={20} strokeWidth={1.5} />{/if}
        <span>{app.cover?.state === "busy" ? t("cover.drawing") : t("cover.title")}</span>
      </button>
      {#each app.pages as page, i (i)}
        <PageCell {page} index={i} selected={app.selected === i} queuePos={pos(page.jobId)} onselect={() => (app.selected = i)} />
      {/each}
      <button class="add" onclick={addPage}><Plus size={18} strokeWidth={1.5} /> {t("ws.add")}</button>
      {#if !app.server.running}
        <p class="hint">{t("ws.hintA")} <button class="link" onclick={() => (app.section = "setup")}>{t("nav.setup")}</button>{(/^[.。．、,!?！？]/).test(t("ws.hintB")) ? t("ws.hintB") : " " + t("ws.hintB")}</p>
      {/if}
    </section>
    <Inspector />
  </div>
  {#if note}<p class="cbz-note" role="status">{note} <button class="link" onclick={() => (note = "")}>×</button></p>{/if}
</div>
{#if coverOpen}<CoverDialog onclose={() => (coverOpen = false)} />{/if}

<style>
  .ws { flex: 1; min-height: 0; display: flex; flex-direction: column; position: relative; }
  .top { display: flex; align-items: center; gap: 20px; padding: 18px 28px 16px; border-bottom: 1px dashed var(--nr); }
  .title { flex: 1; min-width: 0; }
  .cover { width: 116px; height: 174px; align-self: flex-start; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
    border: 1.5px dashed var(--nr); border-radius: 3px; background: none; color: var(--nr-text); font: inherit; font-size: 12.5px; font-weight: 600;
    cursor: pointer; position: relative; overflow: hidden; padding: 0; }
  .cover.has { border-style: solid; border-color: var(--rule); }
  .cover img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  .cover.has span { position: absolute; left: 0; right: 0; bottom: 0; padding: 3px 0; background: var(--sheet); color: var(--ink-2); font-size: 11.5px; }
  .cover.busy { opacity: .7; }
  .cbz-note { position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%); background: var(--sheet); border: 1px solid var(--nr);
    border-radius: var(--radius); padding: 6px 12px; font-size: 13px; color: var(--nr-text); font-weight: 600; box-shadow: var(--lift); }
  .names { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
  .names .name { flex: none; width: auto; min-width: 3ch; field-sizing: content; max-width: 60%; }
  .sep { color: var(--ink-3); font-size: 20px; }
  .chapter { font-size: 18px; font-weight: 600; color: var(--ink-2); border: 1px solid transparent; background: transparent; padding: 2px 6px;
    min-width: 0; flex: 1; }
  .chapter:hover, .chapter:focus { border-color: var(--rule); background: var(--sheet); }
  .name { font-size: 24px; font-weight: 700; letter-spacing: -.01em; border: 1px solid transparent; background: transparent; padding: 2px 6px; margin-left: -7px;
    width: 100%; max-width: 640px; }
  .name:hover { border-color: var(--rule); }
  .title p { font-size: 13px; margin: 2px 0 0; }
  .actions { display: flex; gap: 8px; }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr var(--inspector); }
  .sheet { overflow: auto; padding: 28px 32px 40px; display: grid; grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: 22px 24px; align-content: start; }
  .add { aspect-ratio: 3 / 4.7; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; border: 1px dashed var(--nr);
    background: transparent; color: var(--nr-text); font-weight: 600; cursor: pointer; border-radius: 2px; margin: 9px 9px 47px; }
  .add:hover { background: var(--nr-wash); }
  .hint { grid-column: 1 / -1; color: var(--ink-2); }
  .link { border: 0; background: none; padding: 0; color: var(--nr-text); font-weight: 600; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
  @media (max-width: 1180px) { .body { grid-template-columns: 1fr 264px; } .sheet { padding: 22px 18px 32px; gap: 18px 14px; grid-template-columns: repeat(auto-fill, minmax(116px, 1fr)); } .top { padding: 16px 18px 14px; } }
</style>
