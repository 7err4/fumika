<script lang="ts">
  // Scene of the selected page: shared setting, cast with a look for this scene and the outfit as an item list.
  // The clothing changes are ticked per panel in the story editor cards; scene.ts writes the state into every panel.
  import { invoke } from "@tauri-apps/api/core";
  import { Plus, X, Trash2, Snowflake, Pencil, Download } from "lucide-svelte";
  import { app, save, freezeScene, refreshModels, inTauri } from "./store.svelte";
  import { t } from "./i18n.svelte";
  import { charNames } from "./story";
  import { sceneOf, newId, type Scene } from "./scene";

  const scene = $derived(sceneOf(app.scenes, app.selected));
  const names = $derived(charNames(app.characters));
  const descOf = (n: string) => {
    const l = app.characters.split("\n").find((x) => x.split(":")[0].trim() === n);
    return l ? l.slice(l.indexOf(":") + 1).trim() : "";
  };
  let addName = $state("");
  // freeze the look: needs the optional WD tagger files (model + tag list)
  const tagger = $derived(["wd_tagger", "wd_tagger_tags"].every((id) => app.catalog.find((c) => c.id === id)?.installed));
  let freezing = $state(false), freezeErr = $state("");
  // both tagger files (weights + tag list, Apache-2.0); progress arrives through the dl-progress events like in Setup
  const taggerBusy = $derived(!!app.progress["wd_tagger"] && app.progress["wd_tagger"] !== t("dl.done"));
  async function loadTagger() {
    freezeErr = "";
    for (const id of ["wd_tagger_tags", "wd_tagger"]) {
      try { await invoke("download", { id }); } catch (e) { freezeErr = String(e); return; }
    }
    await refreshModels().catch(() => {});
  }
  async function doFreeze(s: Scene) {
    freezing = true; freezeErr = "";
    try { await freezeScene(s); } catch (e) { freezeErr = String(e); }
    freezing = false;
  }

  function create() {
    // a new scene starts on this page and runs to the next scene (or this page only)
    const next = app.scenes.filter((s) => s.from > app.selected).map((s) => s.from).sort((a, b) => a - b)[0];
    app.scenes.push({ id: newId(), name: t("scene.defaultName", { n: app.scenes.length + 1 }), from: app.selected,
      to: next !== undefined ? next - 1 : app.selected, place: "", time: "", light: "", cast: [], changes: [] });
    save();
  }
  function remove(s: Scene) { app.scenes.splice(app.scenes.indexOf(s), 1); save(); }
  // keep the range inside the book and clear of the neighbouring scenes
  function setRange(s: Scene, which: "from" | "to", v: number) {
    const others = app.scenes.filter((x) => x !== s);
    let n = Math.max(0, Math.min(app.pages.length - 1, (v || 1) - 1));
    for (const o of others) {
      if (which === "to" && o.from > s.from && n >= o.from) n = o.from - 1;
      if (which === "from" && o.to < s.to && n <= o.to) n = o.to + 1;
    }
    s[which] = n;
    if (s.from > s.to) s[which === "from" ? "to" : "from"] = n;
    save();
  }
  function addCast(s: Scene) {
    if (!addName || s.cast.some((c) => c.name === addName)) return;
    // the look starts as the description from the character list - take the clothes out, they come from the items
    s.cast.push({ name: addName, look: descOf(addName), items: [] });
    addName = ""; save();
  }
  const addItem = (s: Scene, k: number) => { s.cast[k].items.push({ id: newId(), name: "", wording: "", start: "on" }); };
  function removeItem(s: Scene, k: number, id: string) {
    const c = s.cast[k];
    c.items = c.items.filter((it) => it.id !== id);
    s.changes = s.changes.filter((ch) => !(ch.char === c.name && ch.item === id));
    save();
  }
  function removeCast(s: Scene, k: number) {
    const n = s.cast[k].name;
    s.cast.splice(k, 1); s.changes = s.changes.filter((ch) => ch.char !== n); save();
  }
</script>

<div class="scene">
  <div class="shead">
    <span class="label">{t("scene.title")}</span>
    {#if scene}<button class="icon" onclick={() => remove(scene)} aria-label={t("scene.delete")} title={t("scene.delete")}><Trash2 size={14} /></button>{/if}
  </div>
  {#if !scene}
    <p class="help">{t("scene.none")}</p>
    <button class="btn quiet" onclick={create}><Plus size={14} /> {t("scene.create")}</button>
  {:else}
    <input bind:value={scene.name} onchange={save} aria-label={t("scene.name")} class="sname" />
    <div class="range">
      <label>{t("scene.pages")}
        <input type="number" min="1" max={app.pages.length} value={scene.from + 1} onchange={(e) => setRange(scene, "from", +e.currentTarget.value)} /></label>
      <span>–</span>
      <input type="number" min="1" max={app.pages.length} value={scene.to + 1} onchange={(e) => setRange(scene, "to", +e.currentTarget.value)} aria-label={t("scene.to")} />
    </div>
    <input bind:value={scene.place} onchange={save} placeholder={t("scene.place")} aria-label={t("scene.place")} />
    <div class="two">
      <input bind:value={scene.time} onchange={save} placeholder={t("scene.time")} aria-label={t("scene.time")} />
      <input bind:value={scene.light} onchange={save} placeholder={t("scene.light")} aria-label={t("scene.light")} />
    </div>
    {#each scene.cast as c, k (c.name)}
      <div class="cast">
        <div class="ctop"><span class="who">{c.name}</span>
          <button class="icon" onclick={() => removeCast(scene, k)} aria-label={t("scene.removeCast")} title={t("scene.removeCast")}><X size={14} /></button></div>
        <label class="small" for={`look-${k}`}>{t("scene.look")}</label>
        <textarea id={`look-${k}`} rows="2" bind:value={c.look} onchange={save}></textarea>
        <span class="small">{t("scene.items")}</span>
        {#each c.items as it (it.id)}
          <div class="item">
            <input bind:value={it.name} onchange={save} placeholder={t("scene.itemName")} aria-label={t("scene.itemName")} />
            <input bind:value={it.wording} onchange={save} placeholder={t("scene.itemWords")} aria-label={t("scene.itemWords")} />
            <label class="start" title={t("scene.startHint")}><input type="checkbox" checked={it.start === "on"}
              onchange={(e) => { it.start = e.currentTarget.checked ? "on" : "off"; save(); }} /> {t("scene.start")}</label>
            <button class="icon" onclick={() => removeItem(scene, k, it.id)} aria-label={t("scene.removeItem")} title={t("scene.removeItem")}><X size={13} /></button>
          </div>
          {#if it.frozen !== undefined}
            <div class="frozen" title={t("scene.frozen", { n: (scene.frozenFrom ?? scene.from) + 1 })}>
              <span class="fname">{it.name || it.wording}:</span>
              <input bind:value={it.frozen} onchange={save} aria-label={t("scene.frozen", { n: (scene.frozenFrom ?? scene.from) + 1 })} />
              <Pencil size={12} />
              <button class="icon" onclick={() => { it.frozen = undefined; save(); }} aria-label={t("scene.unfreeze")} title={t("scene.unfreeze")}><X size={12} /></button>
            </div>
          {/if}
        {/each}
        <button class="add" onclick={() => addItem(scene, k)}><Plus size={13} /> {t("scene.addItem")}</button>
      </div>
    {/each}
    {#if names.some((n) => !scene.cast.some((c) => c.name === n))}
      <div class="addcast">
        <select bind:value={addName} aria-label={t("scene.addCast")}>
          <option value="">{t("scene.addCast")}</option>
          {#each names.filter((n) => !scene.cast.some((c) => c.name === n)) as n}<option value={n}>{n}</option>{/each}
        </select>
        <button class="btn quiet" onclick={() => addCast(scene)} disabled={!addName}><Plus size={14} /></button>
      </div>
    {/if}
    {#if scene.cast.some((c) => c.items.length)}
      <p class="help">{t("scene.howto")}</p>
      {#if tagger}
        <button class="btn quiet" onclick={() => doFreeze(scene)} disabled={freezing || !app.server.running || !app.pages[scene.from]?.best}>
          <Snowflake size={14} /> {freezing ? t("scene.freezing", { n: scene.from + 1 }) : t(scene.cast.some((c) => c.items.some((it) => it.frozen !== undefined)) ? "scene.refreeze" : "scene.freeze")}
        </button>
        <p class="help">{t("scene.freezeHelp", { n: scene.from + 1 })}</p>
      {:else}
        <p class="help">{t("scene.needTagger")}</p>
        {#if inTauri()}
          <button class="btn quiet" onclick={loadTagger} disabled={taggerBusy}><Download size={14} /> {app.progress["wd_tagger"] ?? t("scene.loadTagger")}</button>
        {/if}
      {/if}
      {#if freezeErr}<p class="err">{freezeErr}</p>{/if}
    {/if}
  {/if}
</div>

<style>
  .scene { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--nr); }
  .shead { display: flex; align-items: center; justify-content: space-between; }
  .label { font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
  .help { margin: 0; font-size: 12px; color: var(--ink-3); }
  input:not([type="checkbox"]), textarea, select { width: 100%; font-size: 13px; min-width: 0; }
  .sname { font-weight: 600; }
  .range { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ink-2); }
  .range label { display: flex; align-items: center; gap: 6px; font-weight: 600; }
  .range input { width: 64px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .cast { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); padding: 8px 10px; display: flex; flex-direction: column; gap: 5px; }
  .ctop { display: flex; align-items: center; justify-content: space-between; }
  .who { font-size: 12.5px; font-weight: 700; color: var(--nr-text); }
  .small { font-size: 11.5px; font-weight: 600; color: var(--ink-3); }
  textarea { field-sizing: content; min-height: 3em; max-height: 10em; resize: vertical; }
  .item { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr) auto auto; gap: 4px; align-items: center; }
  .start { display: flex; align-items: center; gap: 3px; font-size: 11.5px; color: var(--ink-2); white-space: nowrap; }
  .icon { border: 0; background: transparent; color: var(--ink-3); padding: 3px; border-radius: 3px; cursor: pointer; display: inline-flex; }
  .icon:hover { background: var(--nr-wash); color: var(--ink); }
  .add { align-self: flex-start; border: 0; background: transparent; color: var(--nr-text); font-size: 12px; font-weight: 600; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; padding: 2px 0; }
  .frozen { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; gap: 5px; align-items: center; margin: -1px 0 2px 8px;
    padding: 2px 4px 2px 9px; border: 1.5px solid var(--nr-text); border-radius: 99px; background: var(--nr-wash); color: var(--nr-text); }
  .frozen .fname { font-size: 11.5px; font-weight: 700; }
  .frozen input { border: 0; background: transparent; padding: 1px 2px; font-size: 12px; color: var(--ink); }
  .err { margin: 0; padding: 6px 9px; border: 1px solid var(--pencil); color: var(--pencil); background: var(--pencil-wash); border-radius: var(--radius); font-size: 12px; }
  .addcast { display: grid; grid-template-columns: 1fr auto; gap: 6px; }
  .btn { display: inline-flex; align-items: center; gap: 6px; align-self: flex-start; }
</style>
