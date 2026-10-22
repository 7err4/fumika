<script lang="ts">
  // Any number of LoRAs with a strength each (FumikaLoraStack / the doujin node apply them in this order).
  // files: what fits the chosen architecture; known = false marks files the app cannot assign to an architecture.
  import { Plus, X, ChevronUp } from "lucide-svelte";
  import { t } from "./i18n.svelte";
  import type { LoraUse } from "./families";

  let { list = $bindable(), files, onchange = () => {}, max = 2, idPrefix = "lora" }:
    { list: LoraUse[]; files: { file: string; known: boolean }[]; onchange?: () => void; max?: number; idPrefix?: string } = $props();

  const add = () => { list.push({ name: files.find((f) => !list.some((l) => l.name === f.file))?.file ?? "", strength: 1 }); onchange(); };
  const remove = (k: number) => { list.splice(k, 1); onchange(); };
  const up = (k: number) => { if (k > 0) { [list[k - 1], list[k]] = [list[k], list[k - 1]]; onchange(); } };
  const label = (f: { file: string; known: boolean }) => f.known ? f.file : `${f.file} (?)`;
</script>

<div class="loras">
  {#each list as l, k}
    <div class="row">
      <select id={`${idPrefix}-${k}`} bind:value={l.name} onchange={onchange} aria-label={t("lora.file", { n: k + 1 })}>
        {#if l.name && !files.some((f) => f.file === l.name)}<option value={l.name}>{l.name} ({t("lora.missing")})</option>{/if}
        {#each files as f}<option value={f.file}>{label(f)}</option>{/each}
      </select>
      <input type="number" min="-2" max={max} step="0.05" bind:value={l.strength} onchange={onchange} aria-label={t("lora.strength", { n: k + 1 })} />
      <button class="icon" onclick={() => up(k)} disabled={k === 0} aria-label={t("ed.up")} title={t("ed.up")}><ChevronUp size={14} /></button>
      <button class="icon" onclick={() => remove(k)} aria-label={t("lora.remove")} title={t("lora.remove")}><X size={14} /></button>
    </div>
  {/each}
  <button class="add" onclick={add} disabled={!files.length}><Plus size={13} /> {t(list.length ? "lora.addMore" : "lora.add")}</button>
  {#if files.some((f) => !f.known)}<p class="hint">{t("lora.unknownHint")}</p>{/if}
</div>

<style>
  .loras { display: flex; flex-direction: column; gap: 5px; }
  .row { display: grid; grid-template-columns: minmax(0, 1fr) 76px auto auto; gap: 4px; align-items: center; }
  select, input { width: 100%; min-width: 0; font-size: 12.5px; }
  .icon { border: 0; background: transparent; color: var(--ink-3); padding: 3px; border-radius: 3px; cursor: pointer; display: inline-flex; }
  .icon:hover:not(:disabled) { background: var(--nr-wash); color: var(--ink); }
  .icon:disabled { opacity: .35; cursor: default; }
  .add { align-self: flex-start; border: 0; background: transparent; color: var(--nr-text); font-size: 12px; font-weight: 600; cursor: pointer;
    display: inline-flex; gap: 4px; align-items: center; padding: 2px 0; }
  .add:disabled { color: var(--ink-3); cursor: default; }
  .hint { margin: 0; font-size: 11.5px; color: var(--ink-3); }
</style>
