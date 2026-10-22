<script lang="ts">
  import { BookOpen, Library, LayoutTemplate, ListOrdered, GraduationCap, Settings, Eye, Image, ExternalLink, Plus, Trash2, ChevronUp, ChevronDown } from "lucide-svelte";
  import { ask } from "@tauri-apps/plugin-dialog";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { app, hasUi, inTauri, openSeries, openChapter, newSeries, newChapter, moveChapter, deleteChapter, deleteSeries, type Section, type SeriesMeta, type ChapterMeta } from "./store.svelte";
  import { t, num, jobLabel, type Key } from "./i18n.svelte";

  // [section, label, icon, plugin area it needs ("" = always)]
  const all: [Section, Key, typeof BookOpen, string][] = [
    ["project", "nav.project", BookOpen, "comic"], ["reader", "nav.reader", Eye, "comic"], ["library", "nav.library", Library, "comic"],
    ["assets", "nav.assets", LayoutTemplate, "assets"], ["image", "nav.image", Image, "image"], ["queue", "nav.queue", ListOrdered, ""], ["trainer", "nav.trainer", GraduationCap, "trainer"],
  ];
  const items = $derived(all.filter(([, , , ui]) => !ui || hasUi(ui)));
  const comic = $derived(hasUi("comic"));
  const running = $derived(app.jobs.filter((j) => j.state === "running" || j.state === "queued").length);
  const engine = $derived(t(app.server.running ? "engine.ready" : app.server.installed ? "engine.off" : "engine.missing"));
  const vram = $derived(app.gpu ? t("rail.vram", { used: num(app.gpu[0] / 1024), total: Math.round(app.gpu[1] / 1024) }) : "");
  const drawing = $derived(app.jobs.find((j) => j.state === "running"));
  const sure = async (msg: string) => !inTauri() || await ask(msg, { title: t("proj.delete"), kind: "warning" });
  async function delSeries(s: SeriesMeta) { if (await sure(t("proj.askDelSeries", { name: s.title }))) deleteSeries(s.id); }
  async function delChapter(c: ChapterMeta) { if (await sure(t("proj.askDelChapter", { name: c.title }))) deleteChapter(c.id); }
  const goSeries = (s: SeriesMeta) => { app.section = "project"; openSeries(s.id); };
  const goChapter = (c: ChapterMeta) => { app.section = "project"; openChapter(c.id); };
</script>

<nav class="rail" aria-label={t("nav.aria")}>
  {#each items as [id, label, Icon] (id)}
    <button class="item" class:on={app.section === id} aria-current={app.section === id ? "page" : undefined} onclick={() => (app.section = id)}>
      <Icon size={17} strokeWidth={1.75} /> <span>{t(label)}</span>
      {#if id === "queue" && running}<em>{running}</em>{/if}
    </button>
  {/each}

  {#if comic}
    <div class="label head series-head"><span>{t("rail.series")}</span>
      <button class="mini" onclick={newSeries} title={t("proj.newSeries")} aria-label={t("proj.newSeries")}><Plus size={14} /></button></div>
    <div class="series">
      {#each app.seriesList as s (s.id)}
        {@const cur = s.id === app.seriesId}
        <div class="row" class:cur>
          <button class="item proj" class:on={cur && app.section === "project"} onclick={() => goSeries(s)}>
            <span>{cur ? app.title : s.title}</span><small>{t("rail.chapters", { n: s.chapters.length })}</small></button>
          <button class="mini hover" onclick={() => delSeries(s)} title={t("proj.delSeries")} aria-label={t("proj.delSeries")}><Trash2 size={13} /></button>
        </div>
        {#if cur}
          <ol class="chapters">
            {#each s.chapters as c, k (c.id)}
              <li class="row" class:on={c.id === app.chapterId}>
                <button class="ch" onclick={() => goChapter(c)}><b>{k + 1}</b><span>{c.id === app.chapterId ? app.chapterTitle : c.title}</span>
                  {#if c.id === app.chapterId}<small>{t("rail.pages", { n: app.pages.length })}</small>{/if}</button>
                <span class="tools hover">
                  <button class="mini" disabled={k === 0} onclick={() => moveChapter(c.id, -1)} aria-label={t("proj.up")} title={t("proj.up")}><ChevronUp size={13} /></button>
                  <button class="mini" disabled={k === s.chapters.length - 1} onclick={() => moveChapter(c.id, 1)} aria-label={t("proj.down")} title={t("proj.down")}><ChevronDown size={13} /></button>
                  <button class="mini" disabled={s.chapters.length < 2} onclick={() => delChapter(c)} aria-label={t("proj.delChapter")} title={t("proj.delChapter")}><Trash2 size={13} /></button>
                </span>
              </li>
            {/each}
            <li><button class="ch add" onclick={newChapter}><Plus size={13} /> {t("proj.newChapter")}</button></li>
          </ol>
        {/if}
      {/each}
    </div>
  {/if}

  <div class="foot">
    <button class="item" class:on={app.section === "setup"} onclick={() => (app.section = "setup")}>
      <Settings size={17} strokeWidth={1.75} /> <span>{t("nav.setup")}</span>
    </button>
    <div class="engine" class:ok={app.server.running}>
      <span><i></i>{engine}{#if app.server.running && app.server.ui}<button class="web" title={t("engine.webTip")} onclick={() => inTauri() && openUrl(`http://127.0.0.1:${app.server.port}/`)}>{t("engine.web")} <ExternalLink size={11} strokeWidth={2} /></button>{/if}</span>
      {#if vram}<small>{vram}</small>{/if}
      {#if drawing}<small>{t("rail.drawing", { project: drawing.project, label: jobLabel(drawing.label) })}</small>{/if}
      {#if app.engineNote.startsWith("python:")}<small class="gate">{t("engine.python", { name: app.engineNote.slice(7) })}</small>{/if}
      {#if app.gate.paused}<small class="gate">{t("gate.paused")}</small>
      {:else if app.gate.overridden}<small class="gate">{t("gate.overridden")}</small>{/if}
    </div>
  </div>
</nav>

<style>
  .rail { border-right: 1px solid var(--rule); padding: 14px 14px 14px; display: flex; flex-direction: column; gap: 2px; background: var(--board); }
  .item { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; background: none; border-radius: var(--radius);
    color: var(--ink-2); font-weight: 500; text-align: left; cursor: pointer; }
  .item:hover { background: var(--nr-wash); color: var(--ink); }
  .item.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }
  .item em { margin-left: auto; font-style: normal; font-size: 11.5px; font-weight: 700; color: var(--nr-text); }
  .head { margin: 22px 10px 6px; }
  .item:first-of-type { margin-top: 0; }
  .proj { justify-content: space-between; }
  .proj span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .proj small { color: var(--ink-3); font-size: 12px; white-space: nowrap; }
  .series-head { display: flex; align-items: center; justify-content: space-between; }
  .series { display: flex; flex-direction: column; gap: 2px; overflow: auto; min-height: 0; }
  .row { position: relative; display: flex; align-items: center; }
  .row .proj { flex: 1; min-width: 0; padding-right: 28px; }
  .mini { display: inline-grid; place-items: center; width: 22px; height: 22px; border: 0; border-radius: 4px; background: none; color: var(--ink-3); cursor: pointer; padding: 0; }
  .mini:hover:not(:disabled) { background: var(--nr-wash); color: var(--ink); }
  .mini:disabled { opacity: .3; cursor: default; }
  .row > .mini.hover { position: absolute; right: 4px; }
  .hover { opacity: 0; transition: opacity .12s; }
  .row:hover .hover, .row:focus-within .hover { opacity: 1; }
  .chapters { list-style: none; margin: 0 0 6px 12px; padding: 0 0 0 8px; border-left: 1px dashed var(--nr); display: flex; flex-direction: column; gap: 1px; }
  .ch { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 7px; border: 0; background: none; padding: 5px 6px; border-radius: var(--radius);
    color: var(--ink-2); font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
  .ch:hover { background: var(--nr-wash); color: var(--ink); }
  .ch b { font-size: 11px; color: var(--ink-3); min-width: 12px; }
  .ch span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ch small { color: var(--ink-3); font-size: 11.5px; white-space: nowrap; }
  li.on .ch { background: var(--nr-tint); color: var(--ink); font-weight: 600; }
  .chapters .tools { display: inline-flex; position: absolute; right: 2px; background: var(--board); border-radius: 4px; }
  .ch.add { color: var(--nr-text); font-weight: 600; font-size: 12.5px; align-items: center; }
  .foot { margin-top: auto; display: flex; flex-direction: column; gap: 6px; }
  .engine { display: flex; flex-direction: column; gap: 2px; padding: 10px 10px 4px; font-size: 12.5px; color: var(--ink-3); border-top: 1px dashed var(--nr); }
  .engine span { display: flex; align-items: center; gap: 8px; }
  .engine small { font-size: 11.5px; padding-left: 15px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .engine i { width: 7px; height: 7px; border-radius: 50%; border: 1.5px solid var(--ink-3); }
  .engine .gate { color: var(--nr-text); font-weight: 600; }
  .engine.ok { color: var(--ink-2); }
  .engine .web { margin-left: auto; display: inline-flex; align-items: center; gap: 3px; border: 0; background: none; padding: 0;
    font: inherit; font-size: 11.5px; color: var(--nr-text); cursor: pointer; }
  .engine .web:hover { text-decoration: underline; }
  .engine.ok i { background: var(--ok); border-color: var(--ok); }
</style>
