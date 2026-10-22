<script lang="ts">
  import { onMount } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { revealItemInDir } from "@tauri-apps/plugin-opener";
  import { app, inTauri } from "./store.svelte";
  import { t, num, prefs, type Key } from "./i18n.svelte";
  import { trainImgUrl } from "../comfy";
  import { animaBases, TRAIN_REC, trainChanged, isSdxl, isSlider, sliderFamilies, SLIDER_REC, sliderChanged, formReady } from "./training.svelte";
  import { tr, trainers, isAnima, formKey, saveForm, initTrainer, demoTrainer, runCheck, startTraining, refreshRuns, epochTest, useFile,
    SUBJECTS, SIZES, VRAMS, QUALITIES, FOLDER, type TrainRun } from "./training.svelte";

  onMount(() => {
    initTrainer();
    if (!inTauri()) { demoTrainer(); return; }
    refreshRuns();
    const timer = setInterval(refreshRuns, 4000);   // progress of runs training in their own window
    return () => clearInterval(timer);
  });

  const list = $derived(trainers());
  const stale = $derived(!!tr.check && tr.check.key !== formKey());
  const canCheck = $derived(formReady() && !tr.busy && (app.server.running || !inTauri()));
  const fams = $derived(sliderFamilies());
  const canStart = $derived(!!tr.check?.ok && !stale && !tr.busy);
  const mb = (b: number) => num(b / 1e6, 0) + " MB";
  const famOf = (id: string) => app.plugins.find((p) => p.id === id)?.family ?? id;

  async function pickFolder(set: (d: string) => void = (d) => { tr.form.dataset = d; }) {
    if (!inTauri()) return;
    const d = await open({ directory: true });
    if (typeof d === "string") { set(d); saveForm(); }
  }
  function reveal(r: TrainRun) { if (inTauri() && r.dir) revealItemInDir(r.files[r.files.length - 1]?.path || r.dir).catch(() => {}); }
  function stateLine(r: TrainRun): string {
    const bits = [t(`tr.st.${r.state}` as Key)];
    if (r.state === "training" && r.step != null && r.total) bits.push(t("tr.step", { step: r.step, total: r.total }));
    if (r.state === "training" && r.remaining) bits.push(t("tr.left", { t: r.remaining }));
    if (r.loss && r.state === "training") bits.push(t("tr.loss", { loss: r.loss }));
    return bits.join(" · ");
  }
  const ticks = (r: TrainRun) => Math.max(r.expected ?? 0, r.saved);
  // memory bar: GPU total = full width; the estimate fills, the likely range is a bracket
  const pct = (x: number, gpu: number) => Math.min(100, (x / Math.max(gpu, x, 1)) * 100);
</script>

<div class="tr">
  <header>
    <h1>{t("nav.trainer")}</h1>
  </header>
  <p class="muted lead">{t("tr.lead")}</p>

  {#if !list.length}
    <p class="note">{t("tr.noPlugin")}</p>
  {:else}
    <div class="desk">
      <section class="form" aria-labelledby="tr-new">
        <h2 id="tr-new" class="label">{t("tr.new")}</h2>

        {#if list.length > 1}
          <span class="flabel" id="tr-fam">{t("tr.family")}</span>
          <div class="seg" role="radiogroup" aria-labelledby="tr-fam">
            {#each list as p (p.id)}
              <button role="radio" aria-checked={tr.form.plugin === p.id} class:on={tr.form.plugin === p.id}
                onclick={() => { tr.form.plugin = p.id; saveForm(); }}>{p.id === "slider-trainer" ? t("tr.sl.tab") : p.family}</button>
            {/each}
          </div>
        {/if}

        {#if isSlider()}
          <p class="hint">{t("tr.sl.lead")}</p>
          <div class="two">
            <div>
              <span class="flabel" id="sl-fam">{t("tr.sl.base")}</span>
              <div class="seg" role="radiogroup" aria-labelledby="sl-fam">
                {#each fams as f}
                  <button role="radio" aria-checked={tr.form.slider.family === f} class:on={tr.form.slider.family === f}
                    onclick={() => { tr.form.slider.family = f; saveForm(); }}>{f === "anima" ? "Anima" : "SDXL"}</button>
                {/each}
              </div>
            </div>
            <div>
              <label class="flabel" for="tr-name">{t("tr.name")}</label>
              <input id="tr-name" type="text" bind:value={tr.form.name} onchange={saveForm} placeholder="smile_slider" spellcheck="false" />
            </div>
          </div>
          <span class="flabel" id="sl-mode">{t("tr.sl.from")}</span>
          <div class="seg" role="radiogroup" aria-labelledby="sl-mode">
            <button role="radio" aria-checked={tr.form.slider.mode === "text"} class:on={tr.form.slider.mode === "text"} onclick={() => { tr.form.slider.mode = "text"; saveForm(); }}>{t("tr.sl.text")}</button>
            <button role="radio" aria-checked={tr.form.slider.mode === "images"} class:on={tr.form.slider.mode === "images"} onclick={() => { tr.form.slider.mode = "images"; saveForm(); }}>{t("tr.sl.images")}</button>
          </div>
          {#if tr.form.slider.mode === "text"}
            <label class="flabel" for="sl-neu">{t("tr.sl.neutral")}</label>
            <input id="sl-neu" type="text" bind:value={tr.form.slider.neutral} onchange={saveForm} placeholder="a woman" spellcheck="false" />
            <div class="two">
              <div>
                <label class="flabel" for="sl-neg">{t("tr.sl.minus")}</label>
                <textarea id="sl-neg" rows="2" bind:value={tr.form.slider.negative} onchange={saveForm} placeholder="a woman, frowning" spellcheck="false"></textarea>
              </div>
              <div>
                <label class="flabel" for="sl-pos">{t("tr.sl.plus")}</label>
                <textarea id="sl-pos" rows="2" bind:value={tr.form.slider.positive} onchange={saveForm} placeholder="a woman, big smile" spellcheck="false"></textarea>
              </div>
            </div>
            <p class="hint">{t("tr.sl.textHint")}</p>
            <label class="flabel" for="sl-tg">{t("tr.sl.targets")}</label>
            <textarea id="sl-tg" rows="3" bind:value={tr.form.slider.targets} onchange={saveForm} placeholder={"a man\nan old woman | an old woman, grinning | an old woman, scowling"} spellcheck="false"></textarea>
            <p class="hint">{t("tr.sl.targetsHint")}</p>
          {:else}
            <label class="flabel" for="sl-fneg">{t("tr.sl.minusDir")}</label>
            <div class="pick">
              <input id="sl-fneg" type="text" bind:value={tr.form.slider.neg} onchange={saveForm} placeholder="D:\sliders\smile\minus" spellcheck="false" />
              <button class="btn quiet" onclick={() => pickFolder((d) => { tr.form.slider.neg = d; })}>{t("tr.choose")}</button>
            </div>
            <label class="flabel" for="sl-fpos">{t("tr.sl.plusDir")}</label>
            <div class="pick">
              <input id="sl-fpos" type="text" bind:value={tr.form.slider.pos} onchange={saveForm} placeholder="D:\sliders\smile\plus" spellcheck="false" />
              <button class="btn quiet" onclick={() => pickFolder((d) => { tr.form.slider.pos = d; })}>{t("tr.choose")}</button>
            </div>
            <label class="flabel" for="sl-cap">{t("tr.sl.caption")}</label>
            <input id="sl-cap" type="text" bind:value={tr.form.slider.caption} onchange={saveForm} placeholder="1girl, solo, portrait" spellcheck="false" />
            <p class="hint">{t(tr.form.slider.family === "sdxl" ? "tr.sl.imagesHintSdxl" : "tr.sl.imagesHint")}</p>
          {/if}
          {#if prefs.expert}
            <details class="tadv">
              <summary>{t("adv.title")}{#if sliderChanged(tr.form.sadv).length}<span class="badge">{t("adv.changed", { n: sliderChanged(tr.form.sadv).length })}</span>{/if}</summary>
              {#if tr.form.slider.mode === "text"}
                <label class="flabel" for="sl-anc">{t("tr.sl.anchors")}</label>
                <textarea id="sl-anc" rows="2" bind:value={tr.form.slider.anchors} onchange={saveForm} placeholder="a cat" spellcheck="false"></textarea>
              {/if}
              <div class="tgrid">
                <label class:mark={tr.form.sadv.steps !== SLIDER_REC.steps} for="sa-steps">{t("tr.sl.steps")}</label>
                <input id="sa-steps" type="number" min="50" max="5000" step="50" bind:value={tr.form.sadv.steps} onchange={saveForm} />
                <label class:mark={tr.form.sadv.saveEvery !== SLIDER_REC.saveEvery} for="sa-save">{t("tr.sl.every")}</label>
                <input id="sa-save" type="number" min="10" max="1000" step="10" bind:value={tr.form.sadv.saveEvery} onchange={saveForm} />
                <label class:mark={tr.form.sadv.rank !== SLIDER_REC.rank} for="sa-rank">Rank</label>
                <input id="sa-rank" type="number" min="1" max="64" bind:value={tr.form.sadv.rank} onchange={saveForm} />
                <label class:mark={tr.form.sadv.alpha !== SLIDER_REC.alpha} for="sa-alpha">Alpha</label>
                <input id="sa-alpha" type="number" min="0.5" max="64" step="0.5" bind:value={tr.form.sadv.alpha} onchange={saveForm} />
                <label class:mark={tr.form.sadv.lr !== SLIDER_REC.lr} for="sa-lr">{t("tr.a.lr")}</label>
                <input id="sa-lr" type="number" min="0.000001" max="0.01" step="0.00001" bind:value={tr.form.sadv.lr} onchange={saveForm} />
                {#if tr.form.slider.mode === "text"}
                  <label class:mark={tr.form.sadv.guidance !== SLIDER_REC.guidance} for="sa-g">{t("tr.sl.guidance")}</label>
                  <input id="sa-g" type="number" min="0.5" max="10" step="0.5" bind:value={tr.form.sadv.guidance} onchange={saveForm} />
                {/if}
                <label class:mark={tr.form.sadv.seed !== SLIDER_REC.seed} for="sa-seed">Seed</label>
                <input id="sa-seed" type="number" min="0" bind:value={tr.form.sadv.seed} onchange={saveForm} />
                {#if tr.form.slider.family === "sdxl"}
                  <label class="check2" class:mark={tr.form.sadv.vPred}><input type="checkbox" bind:checked={tr.form.sadv.vPred} onchange={saveForm} /> {t("tr.a.vpred")}</label><span></span>
                {/if}
              </div>
              <p class="hint">{t("tr.sl.advHint")}</p>
              <button class="btn quiet" onclick={() => { tr.form.sadv = { ...SLIDER_REC }; saveForm(); }} disabled={!sliderChanged(tr.form.sadv).length}>{t("adv.reset")}</button>
            </details>
          {/if}
        {:else}
        <label class="flabel" for="tr-ds">{t("tr.dataset")}</label>
        <div class="pick">
          <input id="tr-ds" type="text" bind:value={tr.form.dataset} onchange={saveForm} placeholder="D:\datasets\my_character" spellcheck="false" />
          <button class="btn quiet" onclick={() => pickFolder()}>{t("tr.choose")}</button>
        </div>
        <p class="hint">{t("tr.datasetHint")}</p>

        <div class="two">
          <div>
            <label class="flabel" for="tr-name">{t("tr.name")}</label>
            <input id="tr-name" type="text" bind:value={tr.form.name} onchange={saveForm} placeholder="my_character" spellcheck="false" />
          </div>
          <div>
            <label class="flabel" for="tr-trig">{t("tr.trigger")}</label>
            <input id="tr-trig" type="text" bind:value={tr.form.trigger} onchange={saveForm} placeholder="ohwx" spellcheck="false" />
          </div>
        </div>
        <p class="hint">{t("tr.triggerHint")}</p>

        {#if isSdxl()}
          <span class="flabel">{t("tr.what")}</span>
          <div class="seg" role="radiogroup" aria-label={t("tr.what")}>
            <button role="radio" aria-checked={tr.form.what === "lora"} class:on={tr.form.what === "lora"} onclick={() => { tr.form.what = "lora"; saveForm(); }}>LoRA / LyCORIS</button>
            <button role="radio" aria-checked={tr.form.what === "embedding"} class:on={tr.form.what === "embedding"} onclick={() => { tr.form.what = "embedding"; saveForm(); }}>{t("tr.embedding")}</button>
          </div>
          {#if tr.form.what === "embedding"}<p class="hint">{t("tr.embeddingHint")}</p>{/if}
        {/if}

        <div class="two">
          <div>
            <label class="flabel" for="tr-subj">{t("tr.subject")}</label>
            <select id="tr-subj" bind:value={tr.form.subject} onchange={saveForm}>
              {#each SUBJECTS as s}<option value={s}>{t(`tr.subj.${s}` as Key)}</option>{/each}
            </select>
          </div>
          <div>
            <label class="flabel" for="tr-vram">{t("tr.vram")}</label>
            <select id="tr-vram" bind:value={tr.form.vram} onchange={saveForm}>
              {#each VRAMS as v}<option value={v}>{v === 24 ? "24+ GB" : `${v} GB`}</option>{/each}
            </select>
          </div>
        </div>

        {#if isAnima() && app.catalog.some((c) => c.id === "anima38_pro52" && c.installed)}
          <p class="hint">{t("tr.v11Hint")}</p>
        {/if}
        {#if isAnima() && animaBases().length > 1}
          <div class="two">
            <div>
              <label class="flabel" for="tr-base">{t("tr.base")}</label>
              <select id="tr-base" bind:value={tr.form.base} onchange={saveForm}>
                {#each animaBases() as c}<option value={c.file}>{c.name}</option>{/each}
              </select>
            </div>
            <p class="hint">{t("tr.baseHint")}</p>
          </div>
        {/if}
        {#if isAnima()}
          <div class="two">
            <div>
              <label class="flabel" for="tr-size">{t("tr.size")}</label>
              <select id="tr-size" bind:value={tr.form.size} onchange={saveForm}>
                {#each SIZES as s}<option value={s}>{t(`tr.size.${s}` as Key)}</option>{/each}
              </select>
            </div>
            <div>
              <label class="flabel" for="tr-q">{t("tr.quality")}</label>
              <select id="tr-q" bind:value={tr.form.quality} onchange={saveForm}>
                {#each QUALITIES as q}<option value={q}>{t(`tr.q.${q}` as Key)}</option>{/each}
                {#if prefs.expert}<option value="experimental">{t("tr.q.experimental")}</option>{/if}
              </select>
            </div>
          </div>
        {/if}

        {#if prefs.expert}
          <details class="tadv">
            <summary>{t("adv.title")}{#if trainChanged(tr.form.adv).length}<span class="badge">{t("adv.changed", { n: trainChanged(tr.form.adv).length })}</span>{/if}</summary>
            <div class="tgrid">
              <label class:mark={tr.form.adv.epochs !== TRAIN_REC.epochs} for="ta-ep">{t("tr.a.epochs")}</label>
              <input id="ta-ep" type="number" min="0" max="1000" bind:value={tr.form.adv.epochs} onchange={saveForm} />
              <label class:mark={tr.form.adv.rank !== TRAIN_REC.rank} for="ta-rank">Rank</label>
              <input id="ta-rank" type="number" min="0" max="256" bind:value={tr.form.adv.rank} onchange={saveForm} />
              <label class:mark={tr.form.adv.lr !== TRAIN_REC.lr} for="ta-lr">{t("tr.a.lr")}</label>
              <input id="ta-lr" type="number" min="0" max="1" step="0.00001" bind:value={tr.form.adv.lr} onchange={saveForm} />
              <label class:mark={tr.form.adv.resolution !== TRAIN_REC.resolution} for="ta-res">{t("tr.a.res")}</label>
              <input id="ta-res" type="number" min="0" max="2048" step="64" bind:value={tr.form.adv.resolution} onchange={saveForm} />
              {#if isSdxl()}
                <label class:mark={tr.form.adv.batch !== TRAIN_REC.batch} for="ta-batch">Batch</label>
                <input id="ta-batch" type="number" min="0" max="8" bind:value={tr.form.adv.batch} onchange={saveForm} />
                <label class:mark={tr.form.adv.saveEvery !== TRAIN_REC.saveEvery} for="ta-save">{t("tr.a.save")}</label>
                <input id="ta-save" type="number" min="0" max="50" bind:value={tr.form.adv.saveEvery} onchange={saveForm} />
                <label class:mark={tr.form.adv.seed !== TRAIN_REC.seed} for="ta-seed">Seed</label>
                <input id="ta-seed" type="number" min="0" bind:value={tr.form.adv.seed} onchange={saveForm} />
                <label class="check2" class:mark={tr.form.adv.trainTe}><input type="checkbox" bind:checked={tr.form.adv.trainTe} onchange={saveForm} /> {t("tr.a.te")}</label><span></span>
                <label class="check2" class:mark={tr.form.adv.vPred}><input type="checkbox" bind:checked={tr.form.adv.vPred} onchange={saveForm} /> {t("tr.a.vpred")}</label><span></span>
                {#if tr.form.what === "lora"}
                  <label class:mark={tr.form.adv.network !== TRAIN_REC.network} for="ta-net2">{t("tr.a.net")}</label>
                  <select id="ta-net2" bind:value={tr.form.adv.network} onchange={saveForm}>{#each ["LoRA", "LoCon", "LoHa", "LoKr"] as n}<option value={n}>{n}</option>{/each}</select>
                {/if}
              {/if}
              {#if isAnima()}
                <label class:mark={tr.form.adv.batch !== TRAIN_REC.batch} for="ta-batch">Batch</label>
                <input id="ta-batch" type="number" min="0" max="16" bind:value={tr.form.adv.batch} onchange={saveForm} />
                <label class:mark={tr.form.adv.saveEvery !== TRAIN_REC.saveEvery} for="ta-save">{t("tr.a.save")}</label>
                <input id="ta-save" type="number" min="0" max="100" bind:value={tr.form.adv.saveEvery} onchange={saveForm} />
                <label class:mark={tr.form.adv.blocksSwap !== TRAIN_REC.blocksSwap} for="ta-swap">{t("tr.a.swap")}</label>
                <input id="ta-swap" type="number" min="-1" max="34" bind:value={tr.form.adv.blocksSwap} onchange={saveForm} />
                <label class:mark={tr.form.adv.seed !== TRAIN_REC.seed} for="ta-seed">Seed</label>
                <input id="ta-seed" type="number" min="0" bind:value={tr.form.adv.seed} onchange={saveForm} />
                <label class:mark={tr.form.adv.network !== TRAIN_REC.network} for="ta-net">{t("tr.a.net")}</label>
                <select id="ta-net" bind:value={tr.form.adv.network} onchange={saveForm}>{#each ["LoRA", "LoKr", "LoHa"] as n}<option value={n}>{n}</option>{/each}</select>
              {/if}
            </div>
            <p class="hint">{t(isAnima() ? "tr.a.helpAnima" : isSdxl() ? "tr.a.helpSdxl" : "tr.a.helpMoss")}</p>
            <button class="btn quiet" onclick={() => { tr.form.adv = { ...TRAIN_REC }; saveForm(); }} disabled={!trainChanged(tr.form.adv).length}>{t("adv.reset")}</button>
          </details>
        {/if}
        {/if}

        <div class="actions">
          <button class="btn" disabled={!canCheck} onclick={runCheck}>{tr.busy === "check" ? t("tr.checking") : t("tr.check")}</button>
          <button class="btn primary" disabled={!canStart} onclick={startTraining}>{tr.busy === "start" ? t("tr.starting") : t("tr.start")}</button>
        </div>
        {#if inTauri() && !app.server.running}<p class="hint">{t("tr.needEngine")}</p>{/if}
        <p class="hint">{t("tr.gpuShared")}</p>
      </section>

      <section class="result" class:stale aria-labelledby="tr-res" aria-live="polite">
        <h2 id="tr-res" class="label">{t("tr.result")}</h2>
        {#if !tr.check}
          <p class="muted empty">{t("tr.noCheck")}</p>
        {:else}
          <p class="verdict" class:bad={!tr.check.ok}>{tr.check.ok ? t("tr.ready") : t("tr.notReady")}</p>
          <ul class="lines">
            {#each tr.check.lines as l}<li class={l.kind}><i aria-hidden="true"></i>{l.text}</li>{/each}
          </ul>
          {#if tr.check.plan}<p class="plan"><span class="label">{t("tr.plan")}</span> {tr.check.plan}</p>{/if}
          {#if tr.check.vram}
            {@const v = tr.check.vram}
            <div class="vram">
              <div class="vhead"><span class="label">{t("tr.vramEst")}</span>
                <span class:over={v.gpu > 0 && v.total > v.gpu}>{t("tr.vramOf", { est: num(v.total), gpu: num(v.gpu, 0) })}</span></div>
              <div class="track" role="img" aria-label={t("tr.vramRange", { low: num(v.low), high: num(v.high) })}>
                <span class="fill" class:over={v.gpu > 0 && v.total > v.gpu} style:width="{pct(v.total, v.gpu)}%"></span>
                <span class="range" style:left="{pct(v.low, v.gpu)}%" style:width="{pct(v.high, v.gpu) - pct(v.low, v.gpu)}%"></span>
              </div>
              <p class="hint">{t("tr.vramRange", { low: num(v.low), high: num(v.high) })}</p>
            </div>
          {/if}
          {#if tr.check.config}
            <details><summary>{t("tr.config")}</summary><pre>{tr.check.config}</pre></details>
          {/if}
        {/if}
        {#if tr.err}<p class="errnote">{tr.err}</p>{/if}
        {#if tr.msg}<p class="note">{tr.msg}</p>{/if}
      </section>
    </div>

    <section class="runs" aria-labelledby="tr-runs">
      <div class="rhead">
        <h2 id="tr-runs" class="label">{t("tr.runs")}</h2>
        {#if inTauri()}<button class="btn quiet" onclick={refreshRuns}>{t("tr.refresh")}</button>{/if}
      </div>
      {#if !tr.runs.length}
        <p class="muted">{t("tr.noRuns")}</p>
      {:else}
        {#each tr.runs as r (r.plugin + r.name)}
          <article class="run {r.state}">
            <div class="rtop">
              <div class="rname"><b>{r.name}</b> <span class="muted">{famOf(r.plugin)}</span></div>
              <div class="rstate">{stateLine(r)}</div>
            </div>
            {#if r.state === "training" && r.step != null && r.total}
              <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax={r.total} aria-valuenow={r.step}
                aria-label={t("tr.step", { step: r.step, total: r.total })}><span style:width="{(r.step / r.total) * 100}%"></span></div>
            {/if}
            {#if ticks(r)}
              <div class="ticks" title={r.expected ? t("tr.saved", { n: r.saved, total: r.expected }) : t("tr.savedN", { n: r.saved })}>
                {#each Array(ticks(r)) as _, i}<span class:inked={i < r.saved}></span>{/each}
                <small class="muted">{r.expected ? t("tr.saved", { n: r.saved, total: r.expected }) : t("tr.savedN", { n: r.saved })}</small>
              </div>
            {/if}
            {#if r.files.length}
              <ul class="files">
                {#each [...r.files].reverse() as f (f.name)}
                  <li><span class="fname">{f.name}</span><span class="muted num">{mb(f.size)}</span>
                    <button class="btn quiet" disabled={!inTauri()} onclick={() => useFile(f)}>{t("tr.use")}</button></li>
                {/each}
              </ul>
            {/if}
            {#if r.samples.length}
              <div class="samples" aria-label={t("tr.samples")}>
                {#each r.samples.slice(-6) as s}<img src={trainImgUrl(`${FOLDER[r.plugin]}/${r.name}/${s}`)} alt={s} loading="lazy" />{/each}
              </div>
            {/if}
            {#if tr.grids[r.name]}<img class="grid" src={tr.grids[r.name]} alt={t("tr.epochsGrid")} />{/if}
            <div class="ract">
              {#if r.plugin !== "anima-lora-trainer" && r.plugin !== "slider-trainer" && r.files.length}
                <button class="btn quiet" disabled={!!tr.gridBusy[r.name] || !inTauri()} title={t("tr.epochsHint")} onclick={() => epochTest(r)}>{t("tr.epochs")}</button>
              {/if}
              <button class="btn quiet" disabled={!inTauri() || !r.dir} onclick={() => reveal(r)}>{t("tr.open")}</button>
            </div>
          </article>
        {/each}
      {/if}
    </section>
  {/if}
</div>

<style>
  .tr { overflow: auto; padding: 24px 32px 40px; }
  .tr > * { max-width: 1100px; }
  header { display: flex; align-items: baseline; gap: 14px; }
  h1 { font-size: 22px; }
  .lead { max-width: 68ch; margin: 6px 0 18px; }
  .label { margin: 0 0 10px; }
  .desk { display: grid; grid-template-columns: minmax(320px, 440px) minmax(0, 1fr); gap: 28px; align-items: start; }
  @media (max-width: 1180px) { .desk { grid-template-columns: 1fr; } }

  .form { display: flex; flex-direction: column; gap: 6px; }
  .flabel { font-size: 13px; font-weight: 600; color: var(--ink-2); margin-top: 8px; }
  .form input[type="text"], .form select, .form textarea { width: 100%; }
  .form textarea { resize: vertical; font: inherit; font-size: 13px; }
  .pick { display: flex; gap: 8px; }
  .pick input { flex: 1; min-width: 0; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
  .two > div { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .hint { margin: 0; font-size: 12px; color: var(--ink-3); }
  .actions { display: flex; gap: 8px; margin: 16px 0 6px; }
  .tadv { margin-top: 14px; border: 1px solid var(--rule); border-radius: var(--radius); padding: 6px 12px 10px; background: var(--sheet); }
  .tadv summary { cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--ink-2); display: flex; gap: 8px; align-items: center; }
  .tadv .badge { font-size: 11px; color: var(--pencil); border: 1px solid var(--pencil); border-radius: 99px; padding: 0 7px; }
  .tgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr) minmax(90px, 1fr)); gap: 6px 10px; align-items: center; margin: 10px 0 4px; }
  .tgrid label { font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
  .tgrid label.mark { color: var(--pencil); }
  .tgrid input, .tgrid select { width: 100%; min-width: 0; }
  .tgrid .check2 { display: flex; gap: 6px; align-items: center; }
  .tgrid .check2 input { width: auto; }
  .seg { display: inline-flex; align-self: start; border: 1px solid var(--rule); border-radius: var(--radius); padding: 2px; background: var(--sheet); }
  .seg button { border: 0; background: none; padding: 6px 14px; border-radius: 3px; color: var(--ink-2); font-weight: 500; font-size: 13px; cursor: pointer; }
  .seg button:hover { background: var(--nr-wash); }
  .seg button.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }

  /* the check is a sheet on the board; dashed while empty or out of date (blue = not final yet) */
  .result { background: var(--sheet); border: 1px solid var(--rule); padding: 16px 18px; min-height: 220px; }
  .result:has(.empty), .result.stale { border-style: dashed; border-color: var(--nr); }
  .result.stale .lines, .result.stale .vram { opacity: .55; }
  .empty { max-width: 52ch; margin: 0; }
  .verdict { font-weight: 700; margin: 0 0 10px; }
  .verdict.bad { color: var(--pencil); }
  .lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .lines li { display: grid; grid-template-columns: 14px 1fr; gap: 6px; align-items: baseline; color: var(--ink-2); overflow-wrap: anywhere; }
  .lines i { width: 8px; height: 8px; border: 1px solid var(--nr); display: inline-block; }
  .lines .ok i { background: var(--nr); }
  .lines .warn i { border-style: dashed; }
  .lines .err { color: var(--pencil); }
  .lines .err i { border-color: var(--pencil); background: var(--pencil); }
  .plan { margin: 12px 0 0; font-size: 13px; }
  .plan .label { margin-right: 6px; }
  .vram { margin-top: 14px; }
  .vhead { display: flex; justify-content: space-between; align-items: baseline; font-size: 13px; font-weight: 600; }
  .vhead .label { margin: 0; }
  .vhead .over { color: var(--pencil); }
  .track { position: relative; height: 12px; border: 1px dashed var(--nr); margin: 6px 0 4px; }
  .fill { position: absolute; inset: 0 auto 0 0; background: var(--nr-tint); }
  .fill.over { background: var(--pencil-wash); }
  .range { position: absolute; top: -4px; bottom: -4px; border-left: 1px solid var(--nr-text); border-right: 1px solid var(--nr-text); }
  details { margin-top: 12px; font-size: 13px; }
  summary { cursor: pointer; color: var(--nr-text); font-weight: 600; }
  pre { background: var(--board); border: 1px solid var(--rule); border-radius: var(--radius); padding: 10px; font-size: 12px; overflow: auto; max-height: 220px; }
  .errnote { margin: 12px 0 0; padding: 8px 10px; border-radius: var(--radius); background: var(--pencil-wash); color: var(--pencil); font-size: 13px; white-space: pre-wrap; }
  .note { color: var(--nr-text); font-weight: 600; margin: 12px 0 0; }

  .runs { margin-top: 30px; padding-top: 18px; border-top: 1px dashed var(--nr); }
  .rhead { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
  .rhead .label { margin: 0; }
  .run { padding: 14px 0; border-bottom: 1px solid var(--rule); display: flex; flex-direction: column; gap: 8px; }
  .rtop { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; flex-wrap: wrap; }
  .rname b { font-size: 15px; }
  .rname .muted { font-size: 12.5px; margin-left: 6px; }
  .rstate { font-size: 13px; font-weight: 600; color: var(--nr-text); }
  .finished .rstate { color: var(--ink); }
  .failed .rstate { color: var(--pencil); }
  .prepared .rstate { color: var(--ink-3); font-weight: 500; }
  .bar { height: 4px; background: var(--nr-wash); }
  .bar span { display: block; height: 100%; background: var(--nr); }
  /* saved files as trims: dashed blue = still to come, inked = saved (The Ink Is Earned) */
  .ticks { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
  .ticks span { width: 14px; height: 18px; border: 1px dashed var(--nr); }
  .ticks span.inked { border: 2px solid var(--ink); }
  .ticks small { margin-left: 6px; font-size: 12px; }
  .files { list-style: none; margin: 0; padding: 0; font-size: 13px; }
  .files li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 12px; align-items: center; padding: 4px 0; }
  .fname { overflow-wrap: anywhere; }
  .samples { display: flex; gap: 8px; flex-wrap: wrap; }
  .samples img { width: 96px; aspect-ratio: 2 / 3; object-fit: cover; border: 1px solid var(--rule); background: var(--sheet); }
  .grid { max-width: 100%; max-height: 520px; object-fit: contain; align-self: start; border: 1px solid var(--rule); }
  .ract { display: flex; gap: 8px; }
</style>
