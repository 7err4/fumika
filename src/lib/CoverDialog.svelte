<script lang="ts">
  // The chapter cover: what it shows (the series title and the chapter are written on it), draw, pick a version,
  // use it as the series picture too.
  import { X } from "lucide-svelte";
  import { app, drawCover, pickCoverVersion, coverText, save } from "./store.svelte";
  import { t } from "./i18n.svelte";

  let { onclose }: { onclose: () => void } = $props();
  if (!app.cover) app.cover = { text: coverText(), state: "todo", cover: true };
  const c = $derived(app.cover!);
  const versions = $derived((c.versions ?? []).filter(Boolean));
  function remove() { app.cover = null; save(); onclose(); }
  function forSeries() { if (c.best) { app.seriesCover = c.best; save(); } }
</script>

<div class="veil" role="presentation" onclick={(e) => { if (e.target === e.currentTarget) onclose(); }}>
  <div class="box" role="dialog" aria-modal="true" aria-labelledby="cover-title">
    <header><h2 id="cover-title">{t("cover.title")}</h2>
      <button class="btn quiet x" onclick={onclose} aria-label={t("cover.close")}><X size={16} /></button></header>
    <div class="cols">
      <div class="pic">
        {#if c.best}<img src={c.best} alt={t("cover.title")} />{:else}<div class="empty">{t("cover.none")}</div>{/if}
        {#if versions.length > 1}
          <div class="vers">{#each versions as v, k}<button class:on={v === c.best} onclick={() => pickCoverVersion(k)} aria-label={t("insp.pick", { n: k + 1 })}><img src={v} alt="" /></button>{/each}</div>
        {/if}
      </div>
      <div class="form">
        <label for="cover-what">{t("cover.what")}</label>
        <textarea id="cover-what" rows="5" bind:value={c.text} oninput={save}></textarea>
        <p class="muted small">{t("cover.hint", { title: app.title, chapter: app.chapterTitle })}</p>
        <div class="row">
          <button class="btn primary" disabled={!app.server.running || c.state === "busy"} onclick={drawCover}>
            {c.state === "busy" ? t("cover.drawing") : c.best ? t("insp.redraw") : t("cover.draw")}</button>
          {#if c.state === "error"}<span class="err small">{c.error}</span>{/if}
        </div>
        <div class="row">
          <button class="btn" disabled={!c.best || app.seriesCover === c.best} onclick={forSeries}>
            {app.seriesCover && app.seriesCover === c.best ? t("cover.isSeries") : t("cover.seriesUse")}</button>
          <button class="btn quiet" onclick={remove}>{t("cover.remove")}</button>
        </div>
      </div>
    </div>
  </div>
</div>

<style>
  .veil { position: fixed; inset: 0; z-index: 40; display: grid; place-items: center; background: rgba(0, 0, 0, .45); }
  .box { width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; background: var(--sheet); border: 1px solid var(--nr);
    border-radius: var(--radius); box-shadow: var(--lift); padding: 16px 20px 18px; }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  h2 { font-size: 16px; margin: 0; }
  .x { padding: 4px 6px; }
  .cols { display: grid; grid-template-columns: 240px 1fr; gap: 18px; }
  .pic img, .empty { width: 240px; aspect-ratio: 2 / 3; object-fit: cover; border: 1px solid var(--rule); border-radius: 3px; background: var(--board); }
  .empty { display: grid; place-items: center; color: var(--ink-3); font-size: 13px; border-style: dashed; }
  .vers { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
  .vers button { padding: 0; border: 2px solid transparent; border-radius: 3px; background: none; cursor: pointer; }
  .vers button.on { border-color: var(--nr); }
  .vers img { width: 52px; aspect-ratio: 2 / 3; object-fit: cover; display: block; }
  .form { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  label { font-size: 13px; font-weight: 600; color: var(--ink-2); }
  textarea { width: 100%; resize: vertical; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
  .small { font-size: 12px; }
  .err { color: var(--pencil); }
  @media (max-width: 640px) { .cols { grid-template-columns: 1fr; } }
</style>
