<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open, ask } from "@tauri-apps/plugin-dialog";
  import { app, inTauri, refreshModels } from "./store.svelte";
  import { refreshModelLists } from "./images.svelte";
  import { FAMILIES, FAMILY_IDS } from "./families";
  import { t, num } from "./i18n.svelte";

  interface Ckpt { kind: string; file: string; size: number; family: string; detected: string }
  const DEMO: Ckpt[] = [{ kind: "diffusion_models", file: "moss\\miaomiaoHaremMOSS_baseV10_fp16.safetensors", size: 10.16e9, family: "moss", detected: "" },
    { kind: "checkpoints", file: "myMix_v3.safetensors", size: 6.94e9, family: "", detected: "sdxl" },
    { kind: "diffusion_models", file: "someModel.gguf", size: 8.1e9, family: "", detected: "" }];

  let msg = $state(""), busy = $state(false), ckpts = $state<Ckpt[]>([]), arch = $state("");
  const gb = (b: number) => num(b / 1e9, 2) + " GB";
  const famName = (id: string) => FAMILIES[id]?.name ?? id;

  async function loadCkpts() {
    if (!inTauri()) { ckpts = DEMO; return; }
    try { ckpts = await invoke<Ckpt[]>("list_checkpoints"); } catch { ckpts = []; }
  }
  $effect(() => { loadCkpts(); });
  async function changed() { await loadCkpts(); refreshModels(); refreshModelLists(); }

  async function importLora() {
    const f = await open({ filters: [{ name: "LoRA", extensions: ["safetensors"] }] });
    if (typeof f === "string") { try { msg = t("lib.added", { name: await invoke<string>("import_lora", { path: f }) }); } catch (e) { msg = String(e); } refreshModels(); }
  }
  async function sure(name: string) { return !inTauri() || await ask(t("lib.askDel", { name }), { title: t("lib.remove"), kind: "warning" }); }
  async function remove(name: string) { if (!(await sure(name))) return; await invoke("delete_lora", { name }); refreshModels(); }

  async function importCkpt() {
    const f = await open({ filters: [{ name: "Checkpoint", extensions: ["safetensors", "gguf", "ckpt"] }] });
    if (typeof f !== "string") return;
    busy = true; msg = t("lib.ck.copying");
    try {
      const [fam, file] = await invoke<[string, string]>("import_checkpoint", { path: f, family: arch || null });
      msg = t("lib.ck.added", { name: file, arch: famName(fam) });
    } catch (e) { msg = String(e); }
    busy = false; changed();
  }
  async function assign(c: Ckpt, family: string) {
    if (!family || family === c.family) return;
    try { await invoke("assign_checkpoint", { kind: c.kind, file: c.file, family }); } catch (e) { msg = String(e); }
    changed();
  }
  async function removeCkpt(c: Ckpt) {
    if (!(await sure(c.file))) return;
    try { await invoke("delete_checkpoint", { kind: c.kind, file: c.file }); } catch (e) { msg = String(e); }
    changed();
  }
</script>

<div class="lib">
  <header><h1>{t("nav.library")}</h1></header>
  <p class="muted lead">{t("lib.lead")}</p>

  <section>
    <div class="bar">
      <h2>{t("lib.ck.title")}</h2>
      <span class="tools">
        <select bind:value={arch} aria-label={t("lib.ck.arch")}>
          <option value="">{t("lib.ck.auto")}</option>
          {#each FAMILY_IDS as id}<option value={id}>{famName(id)}</option>{/each}
        </select>
        <button class="btn" onclick={importCkpt} disabled={busy}>{t("lib.ck.add")}</button>
      </span>
    </div>
    <p class="muted lead">{t("lib.ck.lead")}</p>
    {#if ckpts.length}
      <table>
        <thead><tr><th>{t("lib.ck.file")}</th><th>{t("lib.ck.arch")}</th><th>{t("lib.size")}</th><th></th></tr></thead>
        <tbody>{#each ckpts as c (c.kind + c.file)}<tr>
          <td>{c.file}</td>
          <td><select class="small" aria-label={t("lib.ck.assign")} value={c.family} onchange={(ev) => assign(c, (ev.currentTarget as HTMLSelectElement).value)}>
              {#if !c.family}<option value="">{c.detected ? t("lib.ck.guess", { arch: famName(c.detected) }) : t("lib.ck.unknown")}</option>{/if}
              {#each FAMILY_IDS as id}<option value={id}>{famName(id)}</option>{/each}
            </select></td>
          <td class="num">{gb(c.size)}</td>
          <td class="act"><button class="btn quiet" onclick={() => removeCkpt(c)}>{t("lib.remove")}</button></td>
        </tr>{/each}</tbody>
      </table>
    {:else}<p class="muted">{t("lib.ck.empty")}</p>{/if}
  </section>

  <section>
    <div class="bar"><h2>LoRAs</h2><button class="btn" onclick={importLora}>{t("lib.add")}</button></div>
    {#if app.loras.length}
      <table>
        <thead><tr><th>LoRA</th><th>{t("lib.size")}</th><th></th></tr></thead>
        <tbody>{#each app.loras as [n, s]}<tr><td>{n}</td><td class="num">{gb(s)}</td><td class="act"><button class="btn quiet" onclick={() => remove(n)}>{t("lib.remove")}</button></td></tr>{/each}</tbody>
      </table>
    {:else}<p class="muted">{t("lib.empty")}</p>{/if}
  </section>
  {#if msg}<p class="note">{msg}</p>{/if}
</div>

<style>
  .lib { overflow: auto; padding: 24px 32px 40px; max-width: 980px; }
  header { display: flex; align-items: center; justify-content: space-between; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; }
  section { margin-top: 22px; }
  .bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .tools { display: flex; gap: 8px; align-items: center; }
  .lead { max-width: 68ch; margin: 6px 0 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-size: 11px; letter-spacing: .07em; text-transform: uppercase; color: var(--nr-text); padding: 6px 8px; border-bottom: 1px solid var(--nr); }
  td { padding: 9px 8px; border-bottom: 1px solid var(--rule); word-break: break-all; }
  select.small { font-size: 12px; padding-top: 3px; padding-bottom: 3px; }
  .act { text-align: right; }
  .note { color: var(--nr-text); font-weight: 600; margin-top: 16px; }
</style>
