<script lang="ts">
  // Inpaint mask like A1111: paint over the picture (red = redraw), erase, brush size, invert, clear. The mask canvas has the
  // picture's own resolution; save() hands the mask out as a PNG (white = redraw, black = keep).
  import { Brush, Eraser, FlipHorizontal2, Trash2 } from "lucide-svelte";
  import { t } from "./i18n.svelte";

  let { src, onsave }: { src: string; onsave: (png: Uint8Array) => void } = $props();
  let canvas = $state<HTMLCanvasElement>();
  let img = $state<HTMLImageElement>();
  let size = $state(48), erase = $state(false), dirty = $state(false), painted = $state(false);
  let drawing = false, last: [number, number] | null = null;

  function setup() {
    if (!canvas || !img || img.dataset.missing) return;   // placeholder of a missing picture (main.ts): no mask on it
    canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
    painted = false; dirty = false;
  }
  const pos = (e: PointerEvent): [number, number] => {
    const r = canvas!.getBoundingClientRect();
    return [(e.clientX - r.left) * canvas!.width / r.width, (e.clientY - r.top) * canvas!.height / r.height];
  };
  function stroke(p: [number, number]) {
    const c = canvas!.getContext("2d")!;
    c.globalCompositeOperation = erase ? "destination-out" : "source-over";
    c.strokeStyle = c.fillStyle = "rgb(255, 40, 40)"; c.lineWidth = size; c.lineCap = c.lineJoin = "round";
    c.beginPath();
    if (last) { c.moveTo(...last); c.lineTo(...p); c.stroke(); } else { c.arc(p[0], p[1], size / 2, 0, Math.PI * 2); c.fill(); }
    last = p; dirty = true; if (!erase) painted = true;
  }
  function down(e: PointerEvent) { drawing = true; last = null; canvas!.setPointerCapture(e.pointerId); stroke(pos(e)); }
  function move(e: PointerEvent) { if (drawing) stroke(pos(e)); }
  function up() { drawing = false; last = null; }
  function clear() { canvas!.getContext("2d")!.clearRect(0, 0, canvas!.width, canvas!.height); dirty = true; painted = false; }
  function invert() {
    const c = canvas!.getContext("2d")!, d = c.getImageData(0, 0, canvas!.width, canvas!.height);
    for (let i = 0; i < d.data.length; i += 4) { const a = d.data[i + 3]; Object.assign(d.data, { [i]: 255, [i + 1]: 40, [i + 2]: 40, [i + 3]: 255 - a }); }
    c.putImageData(d, 0, 0); dirty = true; painted = true;
  }
  /** the painted area as a black / white PNG at the picture's resolution */
  export async function save() {
    const w = canvas!.width, h = canvas!.height, src2 = canvas!.getContext("2d")!.getImageData(0, 0, w, h);
    const out = document.createElement("canvas"); out.width = w; out.height = h;
    const o = out.getContext("2d")!, d = o.createImageData(w, h);
    for (let i = 0; i < d.data.length; i += 4) { const v = src2.data[i + 3] > 127 ? 255 : 0; d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = 255; }
    o.putImageData(d, 0, 0);
    const blob = await new Promise<Blob | null>((r) => out.toBlob(r, "image/png"));
    if (!blob) return;
    onsave(new Uint8Array(await blob.arrayBuffer())); dirty = false;
  }
  export const status = () => ({ dirty, painted });
</script>

<div class="mp">
  <div class="tools">
    <div class="seg" role="radiogroup" aria-label={t("mask.tool")}>
      <button role="radio" aria-checked={!erase} class:on={!erase} onclick={() => (erase = false)}><Brush size={14} /> {t("mask.paint")}</button>
      <button role="radio" aria-checked={erase} class:on={erase} onclick={() => (erase = true)}><Eraser size={14} /> {t("mask.erase")}</button>
    </div>
    <label class="size" for="mask-size">{t("mask.size")} <input id="mask-size" type="range" min="4" max="300" step="2" bind:value={size} /> <b>{size}</b></label>
    <button class="icon" onclick={invert} title={t("mask.invert")} aria-label={t("mask.invert")}><FlipHorizontal2 size={15} /></button>
    <button class="icon" onclick={clear} title={t("mask.clear")} aria-label={t("mask.clear")}><Trash2 size={15} /></button>
  </div>
  <div class="stage">
    <img bind:this={img} {src} alt={t("img.source")} onload={setup} draggable="false" />
    <canvas bind:this={canvas} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}
      style:cursor={`url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24'%3E%3Ccircle cx='12' cy='12' r='10' fill='none' stroke='%23000' stroke-width='1.5'/%3E%3C/svg%3E") 12 12, crosshair`}
      aria-label={t("mask.canvas")}></canvas>
  </div>
  <p class="hint">{t(painted ? (dirty ? "mask.unsaved" : "mask.saved") : "mask.howto")}</p>
</div>

<style>
  .mp { display: flex; flex-direction: column; gap: 6px; }
  .tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius); padding: 2px; background: var(--sheet); }
  .seg button { border: 0; background: none; padding: 4px 10px; border-radius: 3px; color: var(--ink-2); font-size: 12.5px; cursor: pointer; display: inline-flex; gap: 5px; align-items: center; }
  .seg button.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }
  .size { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ink-2); font-weight: 600; }
  .size input { width: 110px; }
  .size b { font-variant-numeric: tabular-nums; min-width: 2.5em; color: var(--nr-text); }
  .icon { border: 0; background: transparent; color: var(--ink-3); padding: 4px; border-radius: 3px; cursor: pointer; display: inline-flex; }
  .icon:hover { background: var(--nr-wash); color: var(--ink); }
  .stage { position: relative; align-self: start; max-width: 100%; border: 1px solid var(--rule); background: var(--sheet); touch-action: none; }
  .stage img { display: block; max-width: 100%; max-height: 560px; user-select: none; }
  .stage canvas { position: absolute; inset: 0; width: 100%; height: 100%; opacity: .5; }
  .hint { margin: 0; font-size: 12px; color: var(--ink-3); }
</style>
