<script lang="ts">
  import { app, avgSeconds, type Page } from "./store.svelte";
  import { t } from "./i18n.svelte";
  import { openZoom } from "./zoom.svelte";

  let { page, index, selected, queuePos, onselect }: {
    page: Page; index: number; selected: boolean; queuePos: number; onselect: () => void;
  } = $props();

  // panel guides follow the page script: one line = one panel (same layouts as the render node: 1-5 panels)
  const panels = $derived(Math.min(5, Math.max(1, page.text.split("\n").filter((l) => l.trim()).length)));
  const code = $derived(`P${String(index + 1).padStart(2, "0")}`);
  const drawing = $derived(page.state === "busy" && queuePos === 0 && (!!page.progress || !!page.started));
  // real sampler steps from the engine's websocket; before the first step arrives, an estimate from this book's average page time
  const pr = $derived(page.progress);
  const frac = $derived(!drawing ? 0 : pr ? Math.min(1, (pr.pass - 1 + pr.step / pr.steps) / pr.passes)
    : Math.min(0.95, (app.now - page.started!) / 1000 / avgSeconds()));
  const fill = (k: number) => Math.round(100 * Math.min(1, Math.max(0, frac * panels - k)));
  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const versions = $derived(page.versions?.length ?? 0);
  const status = $derived(
    page.state === "done" ? [page.seconds ? mmss(page.seconds) : t("cell.done"), versions ? t("cell.versions", { n: versions }) : ""].filter(Boolean).join(" · ")
    : page.state === "busy" ? (queuePos > 0 ? t("cell.waiting", { n: queuePos })
      : pr ? [pr.passes > 1 ? t("cell.pass", { pass: pr.pass }) : "", `${pr.step}/${pr.steps}`].filter(Boolean).join(" · ")
      : drawing ? `≈ ${Math.round(frac * 100)} %` : t("cell.drawing"))
    : page.state === "error" ? (page.strays ? t("cell.gibberish", { n: page.strays }) : t("cell.error"))
    : page.stale ? t("cell.changed") : t("cell.open"));
  const names = $derived(app.characters.split("\n").map((l) => l.split(":")[0].trim()).filter((n) => n && page.text.includes(n)));
  const lora = $derived(app.loraList.filter((l) => l.name).map((l) => l.name.split(/[\\/]/).pop()!.replace(/\.safetensors$/, "").replace(/-0+\d+$/, "")).join(" + "));
  const note = $derived([...names, lora].filter(Boolean).join(" · "));
</script>

<button class="cell {page.state}" class:waiting={page.state === "busy" && queuePos > 0} class:sel={selected} onclick={onselect}
  ondblclick={() => page.best && openZoom((page.versions ?? []).filter(Boolean), Math.max(0, (page.versions ?? []).indexOf(page.best)))}
  title={page.state === "done" ? t("zoom.dbl") : undefined}
  aria-label={t("cell.aria", { n: index + 1, status })} aria-pressed={selected}>
  <span class="trim">
    {#if page.best && (page.state === "done" || page.stale)}
      <img class:stale={page.stale && page.state !== "done"} src={page.best} alt={t("page.n", { n: index + 1 })} loading="lazy" />
    {:else}
      <span class="guides p{panels}">
        {#each Array(panels) as _, k}<i style:--fill="{fill(k)}%"></i>{/each}
      </span>
    {/if}
  </span>
  <span class="lab"><span>{code}</span><span>{status}</span></span>
  {#if note}<span class="note" title={note}>{note}</span>{/if}
</button>

<style>
  .cell { position: relative; display: block; width: 100%; aspect-ratio: 3 / 4.7; padding: 0; border: 0; background: none; cursor: pointer; text-align: left; }
  /* trim corner marks: the page sits on the board like a manuscript sheet */
  .cell::before, .cell::after { content: ""; position: absolute; width: 14px; height: 14px; border: 0 solid var(--nr); pointer-events: none; }
  .cell::before { top: 0; left: 0; border-width: 1px 0 0 1px; }
  .cell::after { top: calc(100% - 52px); right: 0; border-width: 0 1px 1px 0; }
  .trim { position: absolute; inset: 9px 9px 47px; background: var(--sheet); border: 1px solid var(--nr); overflow: hidden; display: block;
    transition: outline-color .15s ease-out; outline: 2px solid transparent; outline-offset: 4px; }
  .sel .trim { outline-color: var(--nr); }
  .cell:hover .trim { border-color: var(--nr-text); }
  img { width: 100%; height: 100%; object-fit: cover; display: block; }
  img.stale { opacity: .45; filter: grayscale(.6); }
  .lab { position: absolute; left: 9px; right: 9px; bottom: 24px; display: flex; justify-content: space-between; gap: 6px; font-size: 12px; font-weight: 600; color: var(--nr-text); white-space: nowrap; }
  /* blue-pencil margin note: who is on the page and which LoRA draws it */
  .note { position: absolute; left: 9px; right: 9px; bottom: 6px; font-size: 11.5px; color: var(--nr-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* panel guides (non-repro blue): open = dashed, waiting = blue wash, drawing = hatching filling panel by panel, error = red pencil */
  .guides { position: absolute; inset: 8px; display: grid; gap: 6px; }
  .guides i { border: 1px dashed var(--nr); position: relative; overflow: hidden; }
  .p1 { grid-template-rows: 1fr; }
  .p2 { grid-template-rows: 1fr 1fr; }
  .p3 { grid-template-rows: .9fr 1.1fr 1fr; }
  .p4 { grid-template: 1fr 1fr / 1fr 1fr; }
  .p5 { grid-template: 1fr 1fr 1fr / 1fr 1fr; }
  .p5 i:first-child { grid-column: 1 / 3; }
  .todo .trim { background: transparent; border-style: dashed; }
  .waiting .guides i { background: var(--nr-wash); }
  .busy:not(.waiting) .guides i { border-style: solid; }
  .busy:not(.waiting) .guides i::after { content: ""; position: absolute; inset: 0;
    background: repeating-linear-gradient(-45deg, var(--nr-tint) 0 2px, transparent 2px 7px);
    clip-path: inset(0 calc(100% - var(--fill, 0%)) 0 0); transition: clip-path 1s linear; }
  /* the one authored moment: a finished page inks in, blue trim turning to ink */
  .done .trim { border-color: var(--ink); animation: ink .9s cubic-bezier(.16, 1, .3, 1); }
  .done .guides i { border: 2px solid var(--ink); }
  @keyframes ink { from { border-color: var(--nr); filter: saturate(0) contrast(.6); } to { border-color: var(--ink); filter: none; } }
  @media (prefers-reduced-motion: reduce) { .done .trim { animation: none; } .busy .guides i::after { transition: none; } }
  .error .trim { border-color: var(--pencil); }
  .error .guides i { border-color: var(--pencil); }
  .error .lab span:last-child { color: var(--pencil); }
</style>
