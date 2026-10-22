<script lang="ts">
  import { RotateCcw, ImagePlus, X, Maximize2 } from "lucide-svelte";
  import { openZoom } from "./zoom.svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { app, drawPage, pickVersion, removeVersion, save, setReference, inTauri } from "./store.svelte";
  import StoryEditor from "./StoryEditor.svelte";
  import ScenePanel from "./ScenePanel.svelte";
  import AdvancedBox from "./AdvancedBox.svelte";
  import LoraList from "./LoraList.svelte";
  import { filesFor, helperLora } from "./families";
  import { prefs } from "./i18n.svelte";
  import { inputUrl } from "../comfy";
  import { t, jobLabel, type Key } from "./i18n.svelte";

  // must match the STYLES keys of the MossEasyDoujinPage node
  const STYLES = ["Colour manga", "Black & white manga", "3D game render comic"];
  const page = $derived(app.pages[app.selected]);
  const versions = $derived((page?.versions ?? []).filter(Boolean));
  // names of the character list: the reference picture replaces the written look of one of them (default: the first)
  const charNames = $derived(app.characters.split("\n").map((l) => l.split(":")[0].trim()).filter(Boolean));
  // full-size view of the versions; "use this version" picks it like a click on the thumbnail
  const zoomVersions = (k: number) => { const sel = app.selected; openZoom(versions, k, (i) => pickVersion(sel, i), Math.max(0, versions.indexOf(page?.best ?? "")), (i) => removeVersion(sel, i)); };
  // CharRef: one reference picture per book (main character); offered only when the CharRef LoRA is installed
  const charref = $derived(app.catalog.find((c) => c.id === "charref_v2")?.installed ?? false);
  let refErr = $state("");
  async function pickRef() {
    if (!inTauri()) return;
    const f = await open({ filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    if (typeof f !== "string") return;
    try { refErr = ""; await setReference(f); } catch (e) { refErr = String(e); }
  }
  const queue = $derived(app.jobs.filter((j) => j.state === "queued" || j.state === "running").sort((a, b) => (a.state === "running" ? -1 : b.state === "running" ? 1 : 0)));
</script>

<aside class="insp" aria-label={t("insp.aria")}>
  {#if page}
    <div class="head">
      <h2>{t("page.n", { n: app.selected + 1 })}</h2>
      <button class="btn quiet" onclick={() => drawPage(app.selected)} disabled={!app.server.running || page.state === "busy"}>
        <RotateCcw size={14} /> {t(page.state === "done" ? "insp.redraw" : "insp.draw")}
      </button>
    </div>

    <StoryEditor />
    <ScenePanel />
    {#if page.error}<p class="err">{page.error}</p>{/if}

    {#if versions.length}
      <div class="label">{t("insp.versions")} · {versions.length}</div>
      <div class="vers">
        {#each versions as v, k}
          <button class:best={v === page.best} onclick={() => pickVersion(app.selected, k)} ondblclick={() => zoomVersions(k)} aria-label={t("insp.pick", { n: k + 1 })}>
            <img src={v} alt={t("insp.version", { n: k + 1 })} />
          </button>
        {/each}
      </div>
      <button class="btn quiet zoom" onclick={() => zoomVersions(Math.max(0, versions.indexOf(page?.best ?? "")))}><Maximize2 size={14} />{t("zoom.open")}</button>
    {/if}
  {/if}

  {#if queue.length}
    <div class="label">{t("insp.queue")}</div>
    <ol class="queue">
      {#each queue as j, k (j.id)}<li class:now={j.state === "running"}><span>{k === 0 ? t("insp.now") : `#${k}`}</span><span>{j.project}, {jobLabel(j.label)}</span><span>{t(`state.${j.state}` as Key)}</span></li>{/each}
    </ol>
  {/if}

  <div class="proj">
    <div class="label">{t("insp.book")}</div>
    <label for="style">{t("insp.style")}</label>
    <select id="style" bind:value={app.style} onchange={save}>{#each STYLES as s}<option value={s}>{t(`style.${s}` as Key)}</option>{/each}</select>
    <label for="ckpt">{t("img.checkpoint")}</label>
    <select id="ckpt" bind:value={app.unet} onchange={save}>
      <option value="">{t("insp.ckptSetup")}</option>
      {#each filesFor(app.modelFiles.diffusion, "moss") as c}<option value={c.file}>{c.known ? c.file : `${c.file} (?)`}</option>{/each}
    </select>
    <span class="lab">{t("lora.title")}</span>
    <LoraList bind:list={app.loraList} files={filesFor(app.modelFiles.loras, "moss", helperLora)} onchange={save} idPrefix="book-lora" />
    <label for="chars">{t("insp.chars")} <span class="muted">{t("insp.charsHint")}</span></label>
    <textarea id="chars" rows="5" bind:value={app.characters} onchange={save}></textarea>
    <label for="dir">{t("insp.dir")}</label>
    <select id="dir" bind:value={app.direction} onchange={save}>
      <option value="ltr">{t("insp.dir.ltr")}</option><option value="rtl">{t("insp.dir.rtl")}</option>
    </select>
    <label class="check"><input type="checkbox" bind:checked={app.quality} /> {t("insp.quality")}</label>
    {#if app.catalog.find((c) => c.id === "sft_look")?.installed}
      <label class="check"><input type="checkbox" bind:checked={app.sftLook} onchange={save} /> {t("insp.sftLook")}</label>
    {/if}
    {#if prefs.expert}<AdvancedBox />{/if}
    {#if charref}
      <div class="label">{t("insp.ref")}</div>
      <p class="help">{t("insp.refHelp")}</p>
      {#if app.reference}
        <div class="ref">
          <img src={inputUrl(app.reference)} alt={t("insp.refAlt")} />
          <div class="refside">
            <span class="muted">{app.reference.split("/").pop()}</span>
            {#if charNames.length > 1}
              <label class="shows">{t("insp.refShows")}
                <select bind:value={app.refChar} onchange={save}>
                  {#each charNames as n, k}<option value={k === 0 ? "" : n}>{n}</option>{/each}
                </select>
              </label>
            {/if}
            <button class="btn quiet" onclick={pickRef}><ImagePlus size={14} /> {t("insp.refChange")}</button>
            <button class="btn quiet" onclick={() => setReference(null)}><X size={14} /> {t("insp.refRemove")}</button>
          </div>
        </div>
      {:else}
        <button class="btn quiet" onclick={pickRef}><ImagePlus size={14} /> {t("insp.refAdd")}</button>
      {/if}
      {#if refErr}<p class="err">{refErr}</p>{/if}
    {/if}
  </div>
</aside>

<style>
  .insp { border-left: 1px solid var(--rule); padding: 20px 20px 24px; overflow: auto; display: flex; flex-direction: column; gap: 8px; background: var(--board); }
  .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  h2 { font-size: 17px; }
  label { font-size: 12.5px; font-weight: 600; color: var(--ink-2); margin-top: 6px; }
  .label { margin-top: 12px; }
  .help { margin: -2px 0 2px; font-size: 12px; color: var(--ink-3); }
  textarea, select { width: 100%; font-size: 13px; flex-shrink: 0; }
  .insp > * { flex-shrink: 0; }
  .err { margin: 0; padding: 8px 10px; border: 1px solid var(--pencil); color: var(--pencil); background: var(--pencil-wash); border-radius: var(--radius); font-size: 12.5px; }
  .vers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .vers button { padding: 0; border: 1px solid var(--rule); background: var(--sheet); aspect-ratio: 3 / 4.45; cursor: pointer; overflow: hidden; }
  .vers button.best { border: 2px solid var(--ink); }
  .vers img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .zoom { margin-top: 8px; display: inline-flex; align-items: center; gap: 6px; }
  .queue { list-style: none; margin: 0; padding: 0; font-size: 12.5px; }
  .queue li { display: grid; grid-template-columns: 38px 1fr auto; gap: 6px; padding: 5px 0; border-bottom: 1px dotted var(--nr-tint); color: var(--ink-2); }
  .queue li span:first-child, .queue li span:last-child { color: var(--nr-text); font-weight: 600; }
  .queue li.now { color: var(--ink); font-weight: 600; }
  .proj { margin-top: auto; padding-top: 16px; border-top: 1px dashed var(--nr); display: flex; flex-direction: column; gap: 6px; }
  .lab { font-size: 12.5px; font-weight: 600; color: var(--ink-2); margin-top: 6px; }
  .check { display: flex; gap: 8px; align-items: center; font-weight: 500; }
  .ref { display: grid; grid-template-columns: 72px 1fr; gap: 10px; align-items: start; }
  .ref img { width: 72px; aspect-ratio: 3 / 4; object-fit: cover; border: 1px solid var(--rule); background: var(--sheet); display: block; }
  .refside { display: flex; flex-direction: column; gap: 6px; align-items: flex-start; min-width: 0; font-size: 12px; }
  .refside .muted { overflow-wrap: anywhere; }
  .shows { display: flex; align-items: center; gap: 6px; color: var(--ink-2); }
</style>
