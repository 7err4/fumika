<script lang="ts">
  // Expert settings of the project (Setup -> expert mode). Every field shows what "auto" means for the current speed;
  // values that differ from the recommendation are marked, "Recommended" puts all of them back.
  import { RotateCcw } from "lucide-svelte";
  import { app, save } from "./store.svelte";
  import { t } from "./i18n.svelte";
  import { RECOMMENDED, SAMPLERS, SCHEDULERS, changed, autoHint, type Adv } from "./expert";

  let open = $state(false);
  const diff = $derived(changed(app.adv));
  const mark = (k: keyof Adv) => diff.includes(k);
  const reset = () => { app.adv = { ...RECOMMENDED }; save(); };
  const hint = (k: keyof Adv) => t("adv.auto", { v: autoHint(k, app.quality) });
</script>

<details class="adv" bind:open>
  <summary>{t("adv.title")}{#if diff.length}<span class="badge" title={diff.join(", ")}>{t("adv.changed", { n: diff.length })}</span>{/if}</summary>
  <div class="grid">
    <label class:mark={mark("sampler")} for="adv-sampler">{t("adv.sampler")}</label>
    <select id="adv-sampler" bind:value={app.adv.sampler} onchange={save} title={hint("sampler")}>
      {#each SAMPLERS as s}<option value={s}>{s === "auto" ? `auto (${autoHint("sampler", app.quality)})` : s}</option>{/each}
    </select>
    <label class:mark={mark("scheduler")} for="adv-scheduler">{t("adv.scheduler")}</label>
    <select id="adv-scheduler" bind:value={app.adv.scheduler} onchange={save}>
      {#each SCHEDULERS as s}<option value={s}>{s === "auto" ? `auto (${autoHint("scheduler", app.quality)})` : s}</option>{/each}
    </select>
    <label class:mark={mark("steps")} for="adv-steps">{t("adv.steps")}</label>
    <input id="adv-steps" type="number" min="0" max="200" bind:value={app.adv.steps} onchange={save} placeholder={hint("steps")} title={hint("steps")} />
    <label class:mark={mark("cfg")} for="adv-cfg">CFG</label>
    <input id="adv-cfg" type="number" min="0" max="20" step="0.1" bind:value={app.adv.cfg} onchange={save} title={hint("cfg")} />
    <label class:mark={mark("slg")} for="adv-slg" title={t("adv.slgHint")}>SLG</label>
    <input id="adv-slg" bind:value={app.adv.slg} onchange={save} placeholder="auto / off / 22" title={hint("slg")} />
    <label class:mark={mark("seed")} for="adv-seed">Seed</label>
    <input id="adv-seed" type="number" min="0" bind:value={app.adv.seed} onchange={save} title={t("adv.seedHint")} />
    <label class:mark={mark("versions")} for="adv-versions">{t("adv.versions")}</label>
    <input id="adv-versions" type="number" min="1" max="8" bind:value={app.adv.versions} onchange={save} />
    <label class:mark={mark("loraStrength")} for="adv-lora">{t("adv.lora")}</label>
    <input id="adv-lora" type="number" min="0" max="2" step="0.05" bind:value={app.adv.loraStrength} onchange={save} />
    <label class:mark={mark("sftStrength")} for="adv-sft">{t("adv.sft")}</label>
    <input id="adv-sft" type="number" min="0" max="2" step="0.05" bind:value={app.adv.sftStrength} onchange={save} />
    <label class:mark={mark("refStrength")} for="adv-ref">{t("adv.ref")}</label>
    <input id="adv-ref" type="number" min="0" max="2" step="0.05" bind:value={app.adv.refStrength} onchange={save} />
  </div>
  <label class:mark={mark("negative")} class="neg" for="adv-neg">{t("adv.negative")}</label>
  <input id="adv-neg" bind:value={app.adv.negative} onchange={save} placeholder={hint("negative")} />
  {#if ["karras", "exponential"].includes(app.adv.scheduler)}<p class="warn">{t("adv.sdScheduler")}</p>{/if}
  <p class="help">{t("adv.help")}</p>
  <button class="btn quiet" onclick={reset} disabled={!diff.length}><RotateCcw size={13} /> {t("adv.reset")}</button>
</details>

<style>
  .adv { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); padding: 6px 10px; }
  .adv[open] { padding-bottom: 10px; }
  summary { cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--ink-2); display: flex; align-items: center; gap: 8px; padding: 2px 0; }
  .badge { font-size: 11px; font-weight: 600; color: var(--pencil); border: 1px solid var(--pencil); border-radius: 99px; padding: 0 7px; }
  .grid { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 5px 10px; align-items: center; margin-top: 8px; }
  label { font-size: 12px; font-weight: 600; color: var(--ink-2); }
  label.mark { color: var(--pencil); }
  label.mark::after { content: " •"; }
  .neg { display: block; margin-top: 8px; }
  input, select { width: 100%; font-size: 12.5px; min-width: 0; }
  .warn { margin: 6px 0 0; font-size: 11.5px; color: var(--pencil); }
  .help { margin: 6px 0; font-size: 11.5px; color: var(--ink-3); }
  .btn { display: inline-flex; align-items: center; gap: 6px; }
</style>
