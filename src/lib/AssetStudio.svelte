<script lang="ts">
  import { openZoom } from "./zoom.svelte";
  import { onMount } from "svelte";
  import { app, inTauri } from "./store.svelte";
  import { t, type Key } from "./i18n.svelte";
  import { inputUrl } from "../comfy";
  import LoraList from "./LoraList.svelte";
  import { filesFor, helperLora } from "./families";
  import { as, TYPES, STYLES, FIELDS, LAYOUT, PIXEL_LORA_MAX, saveForm, initAssets, demoAssets, enabled, refReady, cutReady, canCut,
    render, remove, exportFiles, type AssetType, type Source } from "./assets.svelte";

  onMount(() => { initAssets(); if (!inTauri()) demoAssets(); });

  const lay = $derived(LAYOUT[as.form.type]);
  const fields = $derived(FIELDS[as.form.type]);
  // what goes into the preview boxes: the list entries of the current asset (expressions, outfits, views, chibi actions)
  const cellText = $derived.by(() => {
    const list = fields.find((f) => f.list && f.key !== "stats" && f.key !== "insets");
    return list ? (as.form.fields[list.key] ?? "").split("\n").map((l) => l.split(":")[0].split(",")[0].trim()).filter(Boolean) : [];
  });
  const sources: Source[] = ["text", "lora", "ref"];
  const canRender = $derived(enabled() && !!as.form.character.trim() && !as.busy && (app.server.running || !inTauri())
    && (as.form.source !== "lora" || as.form.loras.some((l) => l.name && l.strength)) && (as.form.source !== "ref" || refReady()));
  const ago = (ms: number) => { const m = Math.round((Date.now() - ms) / 60000); return m < 1 ? t("as.now") : m < 60 ? t("as.min", { n: m }) : t("as.hours", { n: Math.round(m / 60) }); };
  let open = $state<Record<string, number>>({});   // entry id -> shown version
  const box = (b: number[]) => `top:${b[0] * 100}%;left:${b[1] * 100}%;height:${(b[2] - b[0]) * 100}%;width:${(b[3] - b[1]) * 100}%`;
  const typeName = (ty: string) => t(`as.t.${ty}` as Key);
</script>

<div class="as">
  <header><h1>{t("nav.assets")}</h1></header>
  <p class="muted lead">{t("as.lead")}</p>

  {#if !enabled()}
    <p class="note">{t("as.noPlugin")}</p>
  {:else}
    <div class="desk">
      <section class="form" aria-labelledby="as-new">
        <h2 id="as-new" class="label">{t("as.type")}</h2>
        <div class="types" role="radiogroup" aria-labelledby="as-new">
          {#each TYPES as ty (ty)}
            {@const L = LAYOUT[ty]}
            <button role="radio" aria-checked={as.form.type === ty} class:on={as.form.type === ty}
              onclick={() => { as.form.type = ty; saveForm(); }}>
              <span class="mini" style:aspect-ratio={String(L.aspect)} aria-hidden="true">
                {#each L.boxes as b}<i style={box(b)}></i>{/each}
                {#each L.text ?? [] as b}<i class="tx" style={box(b)}></i>{/each}
              </span>
              <b>{typeName(ty)}</b>
            </button>
          {/each}
        </div>
        <p class="hint" class:warn={as.form.type === "pixel"}>{t(`as.d.${as.form.type}` as Key)}</p>

        <label class="flabel" for="as-char">{t("as.character")}</label>
        <textarea id="as-char" rows="3" bind:value={as.form.character} onchange={saveForm} spellcheck="false"></textarea>
        <p class="hint">{t("as.charHint")}</p>

        <span class="flabel" id="as-src">{t("as.source")}</span>
        <div class="seg" role="radiogroup" aria-labelledby="as-src">
          {#each sources as s}
            <button role="radio" aria-checked={as.form.source === s} class:on={as.form.source === s}
              onclick={() => { as.form.source = s; saveForm(); }}>{t(`as.src.${s}` as Key)}</button>
          {/each}
        </div>
        {#if as.form.source === "lora"}
          <span class="flabel">{t("lora.title")}</span>
          <LoraList bind:list={as.form.loras} files={filesFor(app.modelFiles.loras, "moss", helperLora)} onchange={saveForm} idPrefix="as-lora" />
        {:else if as.form.source === "ref"}
          {#if refReady()}
            <div class="ref"><img src={inputUrl(app.reference)} alt={t("as.refAlt")} /><p class="hint">{t("as.refUsed")}</p></div>
          {:else}
            <p class="hint warn">{app.reference ? t("as.refNoLora") : t("as.refNone")}</p>
          {/if}
        {/if}

        {#if as.form.source === "lora" && as.form.type === "pixel"}<p class="hint">{t("as.pixelLora", { max: PIXEL_LORA_MAX })}</p>{/if}

        {#if as.form.type !== "pixel"}
          <label class="flabel" for="as-style">{t("as.style")}</label>
          <select id="as-style" bind:value={as.form.style} onchange={saveForm}>
            {#each STYLES as s}<option value={s}>{t(`as.st.${s.split(" ")[0].toLowerCase()}` as Key)}</option>{/each}
          </select>
        {/if}

        {#each fields as f (f.key)}
          <label class="flabel" for="as-f-{f.key}">{t(`as.f.${f.key}` as Key)}{#if f.list}<span class="muted">&nbsp;· {t("as.oneLine")}</span>{/if}</label>
          {#if f.rows}
            <textarea id="as-f-{f.key}" rows={f.rows} bind:value={as.form.fields[f.key]} onchange={saveForm} spellcheck="false"></textarea>
          {:else}
            <input id="as-f-{f.key}" type="text" bind:value={as.form.fields[f.key]} onchange={saveForm}
              placeholder={f.key === "name" ? t("as.namePh") : ""} />
          {/if}
        {/each}

        <div class="opts">
          {#if canCut()}
            <label class="check"><input type="checkbox" bind:checked={as.form.transparent} onchange={saveForm} disabled={inTauri() && !cutReady()} />
              {t("as.transparent")}</label>
            <p class="hint">{inTauri() && !cutReady() ? t("as.cutMissing") : t("as.transparentHint")}</p>
          {/if}
          {#if as.form.type !== "pixel"}
            <label class="check"><input type="checkbox" bind:checked={as.form.labels} onchange={saveForm}
              disabled={as.form.transparent && canCut()} /> {t("as.labels")}</label>
          {/if}
          <label class="inline" for="as-v">{t("as.versions")}
            <select id="as-v" bind:value={as.form.versions} onchange={saveForm}>{#each [1, 2, 3, 4] as v}<option value={v}>{v}</option>{/each}</select>
          </label>
        </div>

        <div class="actions">
          <button class="btn primary" disabled={!canRender} onclick={render}>{t("as.render")}</button>
        </div>
        {#if app.gate.paused}<p class="hint">{t("gate.waits")}</p>{/if}
        {#if inTauri() && !app.server.running}<p class="hint">{t("as.needEngine")}</p>{/if}
        <p class="hint">{t("as.time", { n: as.form.versions })}</p>
        {#if as.err}<p class="errnote">{as.err}</p>{/if}
        {#if as.msg}<p class="note">{as.msg}</p>{/if}
      </section>

      <section class="preview" aria-label={t("as.preview")}>
        <h2 class="label">{t("as.preview")}</h2>
        <div class="sheet" style:aspect-ratio={String(lay.aspect)}>
          {#each lay.boxes as b, i}<span class="cell" style={box(b)}>{#if cellText[i]}<small>{cellText[i]}</small>{/if}</span>{/each}
          {#each lay.text ?? [] as b}<span class="cell tx" style={box(b)}></span>{/each}
          <i class="corner tl"></i><i class="corner br"></i>
        </div>
        <p class="hint">{t("as.previewHint")}</p>
      </section>
    </div>

    <section class="results" aria-labelledby="as-res">
      <h2 id="as-res" class="label">{t("as.results")}</h2>
      {#if !app.assets.length}
        <p class="muted">{t("as.noResults")}</p>
      {:else}
        {#each app.assets as e (e.id)}
          {@const v = Math.min(open[e.id] ?? 0, Math.max(0, e.images.length - 1))}
          <article class="res {e.state}">
            <div class="rtop">
              <div><b>{typeName(e.asset)}</b> <span class="muted">{e.who} · {ago(e.created)}</span></div>
              <div class="rstate">{t(`as.state.${e.state}` as Key)}</div>
            </div>
            {#if e.state === "busy"}
              <div class="pending" style:aspect-ratio={String(LAYOUT[e.asset as AssetType]?.aspect ?? 1)}>
                {#each LAYOUT[e.asset as AssetType]?.boxes ?? [] as b}<span class="cell" style={box(b)}></span>{/each}
              </div>
            {:else if e.state === "error"}
              <p class="errnote">{e.error}</p>
            {:else}
              <div class="shown">
                <button class="mainbtn" onclick={() => openZoom(e.images, v, (k) => (open[e.id] = k), v)} title={t("zoom.open")}><img class="main" src={e.images[v]} alt={`${typeName(e.asset)} ${v + 1}`} /></button>
                {#if e.images.length > 1}
                  <div class="vers" role="radiogroup" aria-label={t("insp.versions")}>
                    {#each e.images as im, k}
                      <button role="radio" aria-checked={k === v} class:best={k === v} onclick={() => (open[e.id] = k)}
                        aria-label={t("insp.pick", { n: k + 1 })}><img src={im} alt="" loading="lazy" /></button>
                    {/each}
                  </div>
                {/if}
              </div>
              {#if e.cut?.length}
                <h3 class="label sub">{t("as.cutTitle")}</h3>
                <div class="checker"><img src={e.cut[Math.min(v, e.cut.length - 1)]} alt={t("as.cutTitle")} /></div>
                {#if e.sprites?.length}
                  <div class="sprites">{#each e.sprites.filter((s) => s.includes(`_${v + 1}_`)) as s}<span class="checker"><img src={s} alt="" loading="lazy" /></span>{/each}</div>
                {/if}
              {/if}
              <div class="ract">
                <button class="btn quiet" disabled={!inTauri()} onclick={() => exportFiles([e.files[v]].filter(Boolean))}>{t("as.export")}</button>
                {#if e.files.length > 1}<button class="btn quiet" disabled={!inTauri()} onclick={() => exportFiles(e.files)}>{t("as.exportAll")}</button>{/if}
                {#if e.spriteFiles?.length}
                  <button class="btn quiet" disabled={!inTauri()}
                    onclick={() => exportFiles([...(e.cutFiles ?? []), ...(e.spriteFiles ?? [])])}>{t("as.exportSprites", { n: e.spriteFiles.length })}</button>
                {/if}
                <button class="btn quiet" onclick={() => remove(e)}>{t("as.remove")}</button>
              </div>
            {/if}
          </article>
        {/each}
      {/if}
    </section>
  {/if}
</div>

<style>
  .as { overflow: auto; padding: 24px 32px 40px; }
  .as > * { max-width: 1100px; }
  h1 { font-size: 22px; }
  .lead { max-width: 68ch; margin: 6px 0 18px; }
  .label { margin: 0 0 10px; }
  .desk { display: grid; grid-template-columns: minmax(320px, 440px) minmax(0, 1fr); gap: 28px; align-items: start; }
  @media (max-width: 1180px) { .desk { grid-template-columns: 1fr; } }

  .form { display: flex; flex-direction: column; gap: 6px; }
  .flabel { font-size: 13px; font-weight: 600; color: var(--ink-2); margin-top: 8px; }
  .form input[type="text"], .form select, .form textarea { width: 100%; }
  .form textarea { resize: vertical; font: inherit; font-size: 13px; }
  .two { display: grid; grid-template-columns: 1fr 120px; gap: 0 12px; }
  .two > div { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .hint { margin: 0; font-size: 12px; color: var(--ink-3); }
  .hint.warn { color: var(--nr-text); font-weight: 600; }
  .actions { display: flex; gap: 8px; margin: 16px 0 6px; }
  .seg { display: inline-flex; align-self: start; border: 1px solid var(--rule); border-radius: var(--radius); padding: 2px; background: var(--sheet); }
  .seg button { border: 0; background: none; padding: 6px 14px; border-radius: 3px; color: var(--ink-2); font-weight: 500; font-size: 13px; cursor: pointer; }
  .seg button:hover { background: var(--nr-wash); }
  .seg button.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }

  /* type picker: each type is a small dummy sheet with its layout in non-repro blue */
  .types { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
  .types button { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 10px 8px 8px; background: var(--sheet);
    border: 1px solid var(--rule); border-radius: var(--radius); cursor: pointer; color: var(--ink-2); font-size: 12.5px; }
  .types button:hover { background: var(--nr-wash); }
  .types button.on { border-color: var(--nr); outline: 2px solid var(--nr); outline-offset: -2px; color: var(--ink); }
  .types b { font-weight: 600; }
  .mini { position: relative; width: 56px; max-height: 56px; background: var(--sheet); border: 1px solid var(--rule); }
  .mini i { position: absolute; border: 1px dashed var(--nr); }
  .mini i.tx { border-style: dotted; background: var(--nr-wash); }
  .ref { display: flex; gap: 10px; align-items: center; margin-top: 6px; }
  .ref img { width: 56px; aspect-ratio: 1; object-fit: cover; border: 1px solid var(--rule); background: var(--sheet); }
  .opts { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }
  .check { display: flex; gap: 8px; align-items: center; font-size: 13px; }
  .inline { display: flex; gap: 10px; align-items: center; font-size: 13px; font-weight: 600; color: var(--ink-2); }
  .inline select { width: auto; }

  .preview { position: sticky; top: 0; }
  .sheet { position: relative; max-height: 560px; max-width: 100%; margin: 0 auto; background: var(--sheet); border: 1px dashed var(--nr); }
  .cell { position: absolute; border: 1px dashed var(--nr); display: flex; align-items: flex-end; justify-content: center; overflow: hidden; }
  .cell small { font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--nr-text); padding: 0 4px 4px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
  .cell.tx { border-style: dotted; background: var(--nr-wash); }
  .corner { position: absolute; width: 14px; height: 14px; border-color: var(--nr); border-style: solid; }
  .corner.tl { top: -8px; left: -8px; border-width: 1px 0 0 1px; }
  .corner.br { bottom: -8px; right: -8px; border-width: 0 1px 1px 0; }

  .errnote { margin: 12px 0 0; padding: 8px 10px; border-radius: var(--radius); background: var(--pencil-wash); color: var(--pencil); font-size: 13px; white-space: pre-wrap; }
  .note { color: var(--nr-text); font-weight: 600; margin: 12px 0 0; }

  .results { margin-top: 30px; padding-top: 18px; border-top: 1px dashed var(--nr); }
  .res { padding: 16px 0; border-bottom: 1px solid var(--rule); display: flex; flex-direction: column; gap: 10px; }
  .rtop { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; flex-wrap: wrap; }
  .rtop b { font-size: 15px; }
  .rtop .muted { font-size: 12.5px; margin-left: 6px; }
  .rstate { font-size: 13px; font-weight: 600; color: var(--nr-text); }
  .done .rstate { color: var(--ink); }
  .error .rstate { color: var(--pencil); }
  /* a render in progress is an empty dashed sheet with blue-washed cells (like a waiting page) */
  .pending { position: relative; width: min(300px, 100%); background: var(--sheet); border: 1px dashed var(--nr); }
  .pending .cell { background: var(--nr-wash); }
  .shown { display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
  .main { max-width: min(620px, 100%); max-height: 440px; object-fit: contain; border: 2px solid var(--ink); background: var(--sheet); }
  .vers { display: flex; flex-direction: column; gap: 8px; }
  .vers button { padding: 0; border: 1px solid var(--rule); background: var(--sheet); cursor: pointer; }
  .vers button.best { border: 2px solid var(--ink); }
  .vers img { display: block; width: 72px; max-height: 108px; object-fit: contain; }
  .sub { margin: 6px 0 0; }
  /* transparent results on a light checkerboard so the cut-out edge is visible */
  .checker { background-color: var(--sheet);
    background-image: linear-gradient(45deg, var(--nr-wash) 25%, transparent 25%), linear-gradient(-45deg, var(--nr-wash) 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, var(--nr-wash) 75%), linear-gradient(-45deg, transparent 75%, var(--nr-wash) 75%);
    background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0; border: 1px solid var(--rule); align-self: start; }
  .checker > img { display: block; max-width: min(620px, 100%); max-height: 420px; object-fit: contain; }
  .sprites { display: flex; gap: 8px; flex-wrap: wrap; }
  .sprites .checker img { max-height: 120px; max-width: 120px; }
  .ract { display: flex; gap: 8px; flex-wrap: wrap; }
  .mainbtn { display: block; width: 100%; padding: 0; border: 0; background: none; cursor: zoom-in; }
</style>
