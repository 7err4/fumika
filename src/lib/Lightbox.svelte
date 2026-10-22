<script lang="ts">
  import { ChevronLeft, ChevronRight, X, Check, Trash2 } from "lucide-svelte";
  import { zoom, closeZoom } from "./zoom.svelte";
  import { t } from "./i18n.svelte";

  const n = $derived(zoom.images.length);
  const go = (d: number) => (zoom.at = (zoom.at + d + n) % n);
  function key(e: KeyboardEvent) {
    if (!n) return;
    if (e.key === "Escape") closeZoom();
    else if (e.key === "ArrowRight") go(1);
    else if (e.key === "ArrowLeft") go(-1);
    else return;
    e.preventDefault();
  }
  function use() { zoom.pick?.(zoom.at); zoom.picked = zoom.at; }
  // removes the version from the page only - the image file stays in the engine's output folder
  function drop() {
    if (!zoom.remove) return;
    const left = zoom.remove(zoom.at);
    if (!left.length) return closeZoom();
    zoom.images = left; zoom.at = Math.min(zoom.at, left.length - 1); zoom.picked = -1;
  }
</script>

<svelte:window onkeydown={key} />

{#if n}
  <!-- Escape closes (window key handler); a click on the dark backdrop closes too -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="lb" role="dialog" aria-modal="true" aria-label={t("zoom.title")} tabindex="-1" onclick={(e) => e.target === e.currentTarget && closeZoom()}>
    <img src={zoom.images[zoom.at]} alt={t("zoom.image", { n: zoom.at + 1, of: n })} />
    <div class="bar">
      {#if n > 1}<button class="ic" onclick={() => go(-1)} aria-label={t("zoom.prev")}><ChevronLeft size={18} /></button>{/if}
      <span class="count">{zoom.at + 1} / {n}</span>
      {#if n > 1}<button class="ic" onclick={() => go(1)} aria-label={t("zoom.next")}><ChevronRight size={18} /></button>{/if}
      {#if zoom.pick}
        <button class="btn" disabled={zoom.picked === zoom.at} onclick={use}><Check size={15} />{zoom.picked === zoom.at ? t("zoom.used") : t("zoom.use")}</button>
      {/if}
      {#if zoom.remove && n > 1}
        <button class="ic" onclick={drop} aria-label={t("zoom.remove")} title={t("zoom.remove")}><Trash2 size={16} /></button>
      {/if}
      <button class="ic" onclick={closeZoom} aria-label={t("zoom.close")}><X size={18} /></button>
    </div>
  </div>
{/if}

<style>
  .lb { position: fixed; inset: 0; z-index: 100; background: rgba(12, 12, 12, .86); display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 12px; padding: 24px; }
  img { max-width: 100%; max-height: calc(100% - 56px); object-fit: contain; background: var(--sheet); box-shadow: var(--lift); }
  .bar { display: flex; align-items: center; gap: 8px; background: var(--sheet); border-radius: var(--radius); padding: 6px 8px; }
  .count { min-width: 52px; text-align: center; font-size: 13px; font-weight: 600; color: var(--ink-2); font-variant-numeric: tabular-nums; }
  .ic { display: grid; place-items: center; width: 32px; height: 32px; border: 0; border-radius: var(--radius); background: none; color: var(--ink); cursor: pointer; }
  .ic:hover { background: var(--nr-wash); }
  .btn { display: inline-flex; align-items: center; gap: 6px; }
</style>
