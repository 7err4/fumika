<script lang="ts">
  import { onMount } from "svelte";
  import { open as openDialog } from "@tauri-apps/plugin-dialog";
  import { ImagePlus, Copy, Wand2, Maximize2, Trash2, Brush, Plus, X, RotateCcw } from "lucide-svelte";
  import { openZoom } from "./zoom.svelte";
  import { app, inTauri } from "./store.svelte";
  import { t, prefs, type Key } from "./i18n.svelte";
  import { inputUrl } from "../comfy";
  import { SAMPLERS, SCHEDULERS } from "./expert";
  import { FAMILIES, FAMILY_IDS, applyPreset, type Family } from "./families";
  import LoraList from "./LoraList.svelte";
  import MaskPainter from "./MaskPainter.svelte";
  import { im, MODES, START, initImages, saveImages, enabled, upscalerReady, generate, reuse, useAsSource, pickSource, removeImage,
    demoImages, checkpoints, loraFiles, unetFor, missing, fastMode, canGenerate, storeMask, presetsFor, addPreset, removePreset,
    restorePresets, sampling, type Mode, type Upscaler } from "./images.svelte";

  onMount(() => { initImages(); if (!inTauri()) demoImages(); });
  const f = $derived(im.form);
  const d = $derived(FAMILIES[f.family]);
  const needSource = $derived(f.mode !== "t2i");
  // the model is not used by Real-ESRGAN / SeedVR2: architecture, checkpoint, LoRAs and prompt are hidden there
  const usesModel = $derived(f.mode !== "upscale" || f.upscaler === "redraw");
  const miss = $derived(usesModel ? missing(f) : []);
  let painter = $state<MaskPainter>();
  let maskBusy = $state(false);
  const canGo = $derived(enabled() && !im.busy && !maskBusy && (app.server.running || !inTauri()) && canGenerate(f));
  const ago = (ms: number) => { const m = Math.round((Date.now() - ms) / 60000); return m < 1 ? t("as.now") : m < 60 ? t("as.min", { n: m }) : t("as.hours", { n: Math.round(m / 60) }); };
  async function pick() {
    if (!inTauri()) return;
    const p = await openDialog({ filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    if (typeof p === "string") { try { await pickSource(p, inputUrl); } catch (e) { im.err = String(e); } }
  }
  const setMode = (m: Mode) => { im.form.mode = m; saveImages(); };
  const setFamily = (fm: Family) => { Object.assign(im.form, { family: fm, unet: "", size: FAMILIES[fm].sizes.some((s) => s[0] === f.size) ? f.size : "square" }); saveImages(); };
  const setUp = (u: Upscaler) => { im.form.upscaler = u; saveImages(); };
  const summary = (e: typeof im.history[number]) => e.form.mode === "upscale"
    ? `${{ esrgan: "Real-ESRGAN", seedvr2: "SeedVR2", redraw: FAMILIES[e.form.family]?.name ?? "" }[e.form.upscaler] ?? ""} ×${e.form.scale}` : e.form.prompt;
  /** inpaint: the painted mask is stored before the job starts */
  async function go() {
    if (f.mode === "inpaint" && painter) {
      const s = painter.status();
      if (s.dirty || !f.mask) { maskBusy = true; try { await painter.save(); } catch (e) { im.err = String(e); } maskBusy = false; }
    }
    generate();
  }
  // presets: chosen in the list, applied with a click (nothing is put in automatically)
  let presetId = $state("");
  const presets = $derived(presetsFor(f.family));
  function apply() {
    const p = im.presets.find((x) => x.id === presetId);
    if (!p) return;
    Object.assign(im.form, applyPreset(p, f.prompt, f.negative)); saveImages();
  }
  const recipe = $derived(sampling(f, false));
</script>

<div class="is">
  <header><h1>{t("nav.image")}</h1></header>
  <p class="muted lead">{t("img.lead")}</p>

  {#if !enabled()}
    <p class="note">{t("img.noPlugin")}</p>
  {:else}
    <div class="desk">
      <section class="form" aria-label={t("img.form")}>
        <div class="seg" role="radiogroup" aria-label={t("img.mode")}>
          {#each MODES as m}<button role="radio" aria-checked={f.mode === m} class:on={f.mode === m} onclick={() => setMode(m)}>{t(`img.m.${m}` as Key)}</button>{/each}
        </div>

        {#if f.mode === "upscale"}
          <span class="flabel">{t("img.upscaler")}</span>
          <div class="seg" role="radiogroup" aria-label={t("img.upscaler")}>
            <button role="radio" aria-checked={f.upscaler === "esrgan"} class:on={f.upscaler === "esrgan"} onclick={() => setUp("esrgan")}>Real-ESRGAN</button>
            <button role="radio" aria-checked={f.upscaler === "seedvr2"} class:on={f.upscaler === "seedvr2"} onclick={() => setUp("seedvr2")}>SeedVR2</button>
            <button role="radio" aria-checked={f.upscaler === "redraw"} class:on={f.upscaler === "redraw"} onclick={() => setUp("redraw")}>{t("img.redraw")}</button>
          </div>
          <p class="hint">{t(f.upscaler === "esrgan" ? "img.esrganHint" : f.upscaler === "seedvr2" ? "img.seedHint" : "img.redrawHint")}</p>
          {#if !upscalerReady(f.upscaler)}<p class="hint warn">{t(f.upscaler === "esrgan" ? "img.needEsrgan" : "img.needSeed")}</p>{/if}
        {/if}

        {#if usesModel}
          <span class="flabel">{t("img.family")}</span>
          <div class="seg" role="radiogroup" aria-label={t("img.family")}>
            {#each FAMILY_IDS as fm}<button role="radio" aria-checked={f.family === fm} class:on={f.family === fm} onclick={() => setFamily(fm)}>{FAMILIES[fm].name}</button>{/each}
          </div>
          <label class="flabel" for="img-ckpt">{t("img.checkpoint")}</label>
          <select id="img-ckpt" bind:value={im.form.unet} onchange={saveImages}>
            <option value="">{t("img.ckptDefault", { file: unetFor({ ...f, unet: "" }) || t("img.none") })}</option>
            {#each checkpoints() as c}<option value={c.file}>{c.known ? c.file : `${c.file} (?)`}</option>{/each}
          </select>
          {#if miss.length}<p class="hint warn">{t("img.needModels", { list: miss.join(", ") })}</p>{/if}
        {/if}

        {#if needSource}
          <span class="flabel">{t("img.source")}</span>
          {#if f.mode === "inpaint" && f.sourceUrl}
            <MaskPainter bind:this={painter} src={f.sourceUrl} onsave={(png) => storeMask(png)} />
          {:else}
            <div class="src">
              {#if f.sourceUrl}<img src={f.sourceUrl} alt={t("img.source")} />{:else}<span class="empty">{t("img.noSource")}</span>{/if}
              <button class="btn quiet" onclick={pick} disabled={!inTauri()}><ImagePlus size={14} /> {t("img.pick")}</button>
            </div>
          {/if}
          {#if f.mode === "inpaint" && f.sourceUrl}<button class="btn quiet small" onclick={pick} disabled={!inTauri()}><ImagePlus size={14} /> {t("img.pickOther")}</button>{/if}
          <p class="hint">{t("img.sourceHint")}</p>
        {/if}

        {#if usesModel}
          <label class="flabel" for="img-prompt">{t(f.mode === "upscale" ? "img.promptUp" : f.mode === "inpaint" ? "img.promptIn" : "img.prompt")}</label>
          <textarea id="img-prompt" rows="4" bind:value={im.form.prompt} onchange={saveImages} spellcheck="false"></textarea>
          {#if f.mode !== "upscale"}
            <label class="flabel" for="img-neg">{t("img.negative")}</label>
            <textarea id="img-neg" rows="2" bind:value={im.form.negative} onchange={saveImages} spellcheck="false" placeholder={t("img.negHint")}></textarea>
          {/if}
          <div class="presets">
            <select bind:value={presetId} aria-label={t("pre.choose")}>
              <option value="">{t("pre.choose")}</option>
              {#each presets as p}<option value={p.id}>{p.name}</option>{/each}
            </select>
            <button class="btn quiet small" onclick={apply} disabled={!presetId}>{t("pre.apply")}</button>
          </div>
          <details class="pman">
            <summary>{t("pre.manage")}</summary>
            {#each im.presets as p (p.id)}
              <div class="pre">
                <div class="prow">
                  <input bind:value={p.name} onchange={saveImages} aria-label={t("pre.name")} />
                  <select bind:value={p.family} onchange={saveImages} aria-label={t("img.family")}>
                    <option value="all">{t("pre.all")}</option>{#each FAMILY_IDS as fm}<option value={fm}>{FAMILIES[fm].name}</option>{/each}
                  </select>
                  <button class="icon" onclick={() => removePreset(p.id)} aria-label={t("pre.delete")} title={t("pre.delete")}><X size={14} /></button>
                </div>
                <input bind:value={p.positive} onchange={saveImages} placeholder={t("pre.positive")} aria-label={t("pre.positive")} />
                <input bind:value={p.negative} onchange={saveImages} placeholder={t("pre.negative")} aria-label={t("pre.negative")} />
              </div>
            {/each}
            <div class="pact">
              <button class="btn quiet small" onclick={() => addPreset({ family: f.family, name: t("pre.newName"), positive: "", negative: f.negative.trim() })}><Plus size={13} /> {t("pre.add")}</button>
              <button class="btn quiet small" onclick={restorePresets}><RotateCcw size={13} /> {t("pre.restore")}</button>
            </div>
          </details>
        {/if}

        {#if f.mode === "t2i"}
          <span class="flabel">{t("img.size")}</span>
          <div class="sizes" role="radiogroup" aria-label={t("img.size")}>
            {#each d.sizes as [k, w, h]}
              <button role="radio" aria-checked={f.size === k} class:on={f.size === k} onclick={() => { im.form.size = k; saveImages(); }} title={`${w} × ${h}`}>
                <i style:aspect-ratio={`${w} / ${h}`}></i><span>{t(`img.s.${k}` as Key)}</span><small>{w}×{h}</small>
              </button>
            {/each}
          </div>
        {/if}

        {#if f.mode === "i2i"}
          <label class="flabel" for="img-den">{t("img.denoise")} <b>{f.denoise.toFixed(2)}</b></label>
          <input id="img-den" type="range" min="0.1" max="1" step="0.05" bind:value={im.form.denoise} onchange={saveImages} />
          <p class="hint">{t("img.denoiseHint")}</p>
        {/if}

        {#if f.mode === "inpaint"}
          <label class="flabel" for="img-inden">{t("img.denoise")} <b>{f.inDenoise.toFixed(2)}</b></label>
          <input id="img-inden" type="range" min="0.1" max="1" step="0.05" bind:value={im.form.inDenoise} onchange={saveImages} />
          <div class="seg" role="radiogroup" aria-label={t("in.area")}>
            <button role="radio" aria-checked={f.maskOnly} class:on={f.maskOnly} onclick={() => { im.form.maskOnly = true; saveImages(); }}>{t("in.only")}</button>
            <button role="radio" aria-checked={!f.maskOnly} class:on={!f.maskOnly} onclick={() => { im.form.maskOnly = false; saveImages(); }}>{t("in.whole")}</button>
          </div>
          <div class="two">
            {#if f.maskOnly}
              <div><label class="flabel" for="img-pad">{t("in.padding")} <b>{f.padding}px</b></label>
                <input id="img-pad" type="range" min="0" max="256" step="8" bind:value={im.form.padding} onchange={saveImages} /></div>
            {/if}
            <div><label class="flabel" for="img-blur">{t("in.blur")} <b>{f.maskBlur}px</b></label>
              <input id="img-blur" type="range" min="0" max="48" step="1" bind:value={im.form.maskBlur} onchange={saveImages} /></div>
          </div>
          <p class="hint">{t("in.hint")}</p>
        {/if}

        {#if f.mode === "upscale"}
          <label class="flabel" for="img-scale">{t("img.scale")} <b>×{f.scale}</b></label>
          <input id="img-scale" type="range" min="1.25" max={f.upscaler === "redraw" ? 2.5 : 4} step="0.25" bind:value={im.form.scale} onchange={saveImages} />
          {#if f.upscaler === "redraw"}
            <label class="flabel" for="img-upd">{t("img.denoise")} <b>{f.upDenoise.toFixed(2)}</b></label>
            <input id="img-upd" type="range" min="0.1" max="0.6" step="0.05" bind:value={im.form.upDenoise} onchange={saveImages} />
          {/if}
        {/if}

        {#if usesModel}
          <div class="row">
            {#if f.mode !== "upscale"}
              <label class="inline" for="img-count">{t("img.count")}
                <select id="img-count" bind:value={im.form.count} onchange={saveImages}>{#each [1, 2, 3, 4] as n}<option value={n}>{n}</option>{/each}</select></label>
              {#if d.turbo && app.catalog.find((c) => c.id === "turbo")?.installed}
                <label class="check"><input type="checkbox" bind:checked={im.form.quality} onchange={saveImages} /> {t("img.quality")}</label>
              {/if}
            {/if}
            {#if d.sft && app.catalog.find((c) => c.id === "sft_look")?.installed}
              <label class="check"><input type="checkbox" bind:checked={im.form.sft} onchange={saveImages} /> {t("insp.sftLook")}</label>
            {/if}
          </div>
          <span class="flabel">{t("lora.title")}</span>
          <LoraList bind:list={im.form.loras} files={loraFiles()} onchange={saveImages} idPrefix="img-lora" />
          <label class="flabel" for="img-seed">Seed</label>
          <input id="img-seed" type="number" min="0" bind:value={im.form.seed} onchange={saveImages} title={t("adv.seedHint")} />

          {#if prefs.expert}
            <details class="adv">
              <summary>{t("adv.title")} <span class="muted">· {t("img.recipe", { steps: recipe.steps, cfg: recipe.cfg, sampler: recipe.sampler, scheduler: recipe.scheduler })}</span></summary>
              <div class="grid">
                <label for="img-sampler">{t("adv.sampler")}</label>
                <select id="img-sampler" bind:value={im.form.sampler} onchange={saveImages}>{#each SAMPLERS as s}<option value={s}>{s}</option>{/each}{#if !SAMPLERS.includes(d.recipe.sampler)}<option value={d.recipe.sampler}>{d.recipe.sampler}</option>{/if}</select>
                <label for="img-sched">{t("adv.scheduler")}</label>
                <select id="img-sched" bind:value={im.form.scheduler} onchange={saveImages}>{#each SCHEDULERS as s}<option value={s}>{s}</option>{/each}</select>
                <label for="img-steps">{t("adv.steps")}</label>
                <input id="img-steps" type="number" min="0" max="200" bind:value={im.form.steps} onchange={saveImages} placeholder={String(recipe.steps)} />
                <label for="img-cfg">CFG</label>
                <input id="img-cfg" type="number" min="0" max="20" step="0.1" bind:value={im.form.cfg} onchange={saveImages} placeholder={String(recipe.cfg)} />
                {#if d.slg}
                  <label for="img-slg">SLG</label>
                  <input id="img-slg" bind:value={im.form.slg} onchange={saveImages} placeholder="auto / off / 22" />
                {/if}
                {#if d.sft}
                  <label for="img-sft">{t("adv.sft")}</label>
                  <input id="img-sft" type="number" min="0" max="2" step="0.05" bind:value={im.form.sftStrength} onchange={saveImages} />
                {/if}
              </div>
              {#if f.family === "moss" && ["karras", "exponential"].includes(f.scheduler)}<p class="hint warn">{t("adv.sdScheduler")}</p>{/if}
              <p class="hint">{t("adv.help")}</p>
              <button class="btn quiet small" onclick={() => { Object.assign(im.form, { sampler: START.sampler, scheduler: START.scheduler, steps: 0, cfg: 0, slg: "auto", sftStrength: START.sftStrength }); saveImages(); }}>{t("adv.reset")}</button>
            </details>
          {/if}
          {#if fastMode(f)}<p class="hint">{t("img.fastHint")}</p>{/if}
        {/if}

        <div class="actions">
          <button class="btn primary" disabled={!canGo} onclick={go}>{#if f.mode === "inpaint"}<Brush size={15} />{:else}<Wand2 size={15} />{/if}
            {t(f.mode === "upscale" ? "img.goUp" : f.mode === "inpaint" ? "img.goIn" : "img.go")}</button>
        </div>
        {#if f.mode === "inpaint" && f.sourceUrl && !painter?.status().painted && !f.mask}<p class="hint">{t("mask.howto")}</p>{/if}
        {#if app.gate.paused}<p class="hint">{t("gate.waits")}</p>{/if}
        {#if inTauri() && !app.server.running}<p class="hint">{t("as.needEngine")}</p>{/if}
        {#if im.err}<p class="errnote">{im.err}</p>{/if}
      </section>

      <section class="hist" aria-labelledby="img-hist">
        <h2 id="img-hist" class="label">{t("img.history")}</h2>
        {#if !im.history.length}<p class="muted">{t("img.noHistory")}</p>{/if}
        <div class="cards">
          {#each im.history as e (e.id)}
            <article class="card {e.state}">
              {#if e.state === "busy"}
                <div class="pending"><span>{t("as.state.busy")}</span></div>
              {:else if e.state === "error"}
                <p class="errnote">{e.error}</p>
              {:else}
                <button class="thumb" onclick={() => openZoom(e.images, 0)} title={t("zoom.open")}>
                  <img src={e.images[0]} alt={summary(e)} loading="lazy" />{#if e.images.length > 1}<em>{e.images.length}</em>{/if}
                </button>
              {/if}
              <div class="meta">
                <span class="mode">{t(`img.m.${e.form.mode}` as Key)}{#if e.form.mode !== "upscale" || e.form.upscaler === "redraw"} · {FAMILIES[e.form.family]?.name ?? ""}{/if}</span>
                <span class="muted">{ago(e.created)} · seed {e.seed}{#if e.form.loras?.length} · {t("lora.n", { n: e.form.loras.length })}{/if}</span>
                <p title={summary(e)}>{summary(e)}</p>
              </div>
              <div class="act">
                <button class="icon" onclick={() => reuse(e)} title={t("img.reuse")} aria-label={t("img.reuse")}><Copy size={14} /></button>
                {#if e.state === "done"}
                  <button class="icon" onclick={() => useAsSource(e, 0, "i2i")} title={t("img.toI2i")} aria-label={t("img.toI2i")}><Wand2 size={14} /></button>
                  <button class="icon" onclick={() => useAsSource(e, 0, "inpaint")} title={t("img.toIn")} aria-label={t("img.toIn")}><Brush size={14} /></button>
                  <button class="icon" onclick={() => useAsSource(e, 0, "upscale")} title={t("img.toUp")} aria-label={t("img.toUp")}><Maximize2 size={14} /></button>
                {/if}
                <button class="icon" onclick={() => removeImage(e)} title={t("as.remove")} aria-label={t("as.remove")}><Trash2 size={14} /></button>
              </div>
            </article>
          {/each}
        </div>
      </section>
    </div>
  {/if}
</div>

<style>
  .is { overflow: auto; padding: 24px 32px 40px; }
  h1 { font-size: 22px; }
  .lead { max-width: 68ch; margin: 6px 0 18px; }
  .label { margin: 0 0 10px; }
  .desk { display: grid; grid-template-columns: minmax(340px, 460px) minmax(0, 1fr); gap: 28px; align-items: start; }
  @media (max-width: 1180px) { .desk { grid-template-columns: 1fr; } }
  .form { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .flabel { font-size: 13px; font-weight: 600; color: var(--ink-2); margin-top: 8px; }
  .flabel b { color: var(--nr-text); font-variant-numeric: tabular-nums; }
  .form input[type="number"], .form select, .form textarea, .form input:not([type]) { width: 100%; }
  .form textarea { resize: vertical; font: inherit; font-size: 13px; }
  .hint { margin: 0; font-size: 12px; color: var(--ink-3); }
  .hint.warn { color: var(--pencil); font-weight: 600; }
  .seg { display: inline-flex; flex-wrap: wrap; align-self: start; border: 1px solid var(--rule); border-radius: var(--radius); padding: 2px; background: var(--sheet); }
  .seg button { border: 0; background: none; padding: 6px 12px; border-radius: 3px; color: var(--ink-2); font-weight: 500; font-size: 13px; cursor: pointer; }
  .seg button:hover { background: var(--nr-wash); }
  .seg button.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }
  .src { display: flex; gap: 10px; align-items: center; }
  .src img { width: 72px; height: 72px; object-fit: cover; border: 1px solid var(--rule); background: var(--sheet); }
  .src .empty { width: 72px; height: 72px; border: 1px dashed var(--nr); display: grid; place-items: center; font-size: 11px; color: var(--ink-3); text-align: center; }
  .btn.small { align-self: flex-start; font-size: 12.5px; padding: 4px 10px; display: inline-flex; gap: 5px; align-items: center; }
  .presets { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; margin-top: 6px; }
  .pman { border: 1px solid var(--rule); border-radius: var(--radius); padding: 4px 10px 8px; background: var(--sheet); }
  .pman summary { cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
  .pre { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; border-bottom: 1px dotted var(--nr-tint); }
  .prow { display: grid; grid-template-columns: minmax(0, 1fr) 120px auto; gap: 4px; align-items: center; }
  .pre input, .pre select { font-size: 12.5px; width: 100%; min-width: 0; }
  .pact { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .sizes { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }
  .sizes button { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 4px 6px; background: var(--sheet); border: 1px solid var(--rule);
    border-radius: var(--radius); cursor: pointer; font-size: 12px; color: var(--ink-2); }
  .sizes button.on { outline: 2px solid var(--nr); outline-offset: -2px; color: var(--ink); }
  .sizes i { display: block; height: 30px; max-width: 44px; border: 1px dashed var(--nr); }
  .sizes small { font-size: 10.5px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
  .row { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
  .check { display: flex; gap: 8px; align-items: center; font-size: 13px; }
  .inline { display: flex; gap: 8px; align-items: center; font-size: 13px; font-weight: 600; color: var(--ink-2); }
  .inline select { width: auto; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
  .two > div { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .adv { margin-top: 10px; border: 1px solid var(--rule); border-radius: var(--radius); padding: 6px 10px 10px; background: var(--sheet); }
  .adv summary { cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
  .adv summary .muted { font-weight: 400; }
  .grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 5px 10px; align-items: center; margin: 8px 0; }
  .grid label { font-size: 12px; font-weight: 600; color: var(--ink-2); }
  .actions { display: flex; gap: 8px; margin: 16px 0 6px; }
  .actions .btn { display: inline-flex; gap: 6px; align-items: center; }
  .errnote { margin: 8px 0 0; padding: 8px 10px; border-radius: var(--radius); background: var(--pencil-wash); color: var(--pencil); font-size: 13px; white-space: pre-wrap; }
  .note { color: var(--nr-text); font-weight: 600; }
  .icon { border: 0; background: transparent; color: var(--ink-3); padding: 4px; border-radius: 3px; cursor: pointer; display: inline-flex; }
  .icon:hover { background: var(--nr-wash); color: var(--ink); }

  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 16px; }
  .card { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .thumb { position: relative; padding: 0; border: 2px solid var(--ink); background: var(--sheet); cursor: zoom-in; aspect-ratio: 1; overflow: hidden; }
  .thumb img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .thumb em { position: absolute; right: 6px; bottom: 6px; font-style: normal; font-size: 11px; font-weight: 700; background: var(--ink); color: var(--sheet); padding: 1px 6px; border-radius: 99px; }
  .pending { aspect-ratio: 1; border: 1px dashed var(--nr); background: var(--nr-wash); display: grid; place-items: center; color: var(--nr-text); font-weight: 600; font-size: 13px; }
  .meta { display: flex; flex-direction: column; gap: 1px; font-size: 12px; min-width: 0; }
  .meta .mode { font-weight: 700; color: var(--nr-text); }
  .meta p { margin: 2px 0 0; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .act { display: flex; gap: 2px; }
</style>
