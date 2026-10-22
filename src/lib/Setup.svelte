<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { app, saveCfg, refreshModels, setPlugins, inTauri, type PluginInfo } from "./store.svelte";
  import { t, num, prefs, applyPrefs, LANGS, type Theme, type Palette, type Key } from "./i18n.svelte";

  let report = $state("");
  let msg = $state("");
  let mcp = $state<any>(null);
  const gb = (b: number) => num(b / 1e9) + " GB";
  const needed = $derived(app.catalog.filter((c) => (c.kind === "required" || c.kind === "recommended") && (!c.group || c.id === app.cfg?.base_model)));
  const THEMES: Theme[] = ["system", "light", "dark"];
  const PALETTES: Palette[] = ["fumika", "terra"];
  const APP_VERSION = "0.1.0";   // same as package.json / Cargo.toml / splash

  // plugin choice: edited locally, saved with one button (switching on downloads nothing yet - the model list just grows)
  let sel = $state<string[]>([]);
  let dirty = $state(false);
  let ask = $state<PluginInfo | null>(null);   // a plugin with non-commercial model licences waiting for an explicit OK
  let askAdd = $state<string[]>([]);            // what gets switched on with it (its model families)
  let askAt = $state("");                        // the card that was clicked: the licence question opens right below it
  let blocked = $state("");
  $effect(() => { if (!dirty) sel = app.plugins.filter((p) => p.enabled).map((p) => p.id); });
  const byId = (id: string) => app.plugins.find((p) => p.id === id);
  /** the plugin plus the families it needs (same rule as plugins_set in the core) */
  function withNeeds(id: string, have: string[]): string[] {
    const out = [id], p = byId(id);
    for (const r of p?.requires ?? []) if (!have.includes(r) && byId(r)) out.push(r);
    const one = p?.requires_one ?? [];
    if (one.length && !one.some((r) => have.includes(r))) out.push(one[0]);
    return out;
  }
  /** who still needs this plugin (a family cannot be switched off under a workspace that uses it) */
  function neededBy(id: string, have: string[]): string[] {
    return have.filter((o) => o !== id).map(byId).filter((o): o is PluginInfo => !!o).filter((o) =>
      (o.requires ?? []).includes(id) || ((o.requires_one ?? []).includes(id) && !(o.requires_one ?? []).some((r) => r !== id && have.includes(r))))
      .map((o) => o.name);
  }
  function toggle(p: PluginInfo) {
    blocked = "";
    if (sel.includes(p.id)) {
      const by = neededBy(p.id, sel);
      if (by.length) { blocked = t("plg.needed", { name: p.name, list: by.join(", ") }); return; }
      sel = sel.filter((x) => x !== p.id); dirty = true; return;
    }
    const add = withNeeds(p.id, sel);
    const nc = add.map(byId).find((x) => x?.noncommercial_models.length);
    if (nc) { ask = nc; askAdd = add; askAt = p.id; return; }
    sel = [...sel, ...add]; dirty = true;
  }
  function accept() { if (ask) { sel = [...new Set([...sel, ...askAdd])]; dirty = true; ask = null; askAdd = []; } }
  // grouped list: model families first, then the areas that use them
  const GROUPS: [string, (p: PluginInfo) => boolean][] = [["family", (p) => p.kinds.includes("family")],
    ["generate", (p) => !p.kinds.includes("family") && p.kinds.includes("generate")], ["train", (p) => p.kinds.includes("train")],
    ["tool", (p) => !p.kinds.some((k) => ["family", "generate", "train"].includes(k))]];
  const licOf = (p: PluginInfo) => p.models.find((m) => m.license_noncommercial);
  async function savePlugins() {
    try { const done = await setPlugins(sel); dirty = false; msg = done.length ? t("plg.savedNodes", { list: done.join(", ") }) : t("plg.saved"); }
    catch (e) { msg = String(e); }
  }
  /** the licence question is visible at once, without scrolling */
  function reveal(el: HTMLElement) { el.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
  function readLicense(url: string) { if (url && inTauri()) openUrl(url); }

  async function check(dir: string) {
    if (!dir || !app.cfg) return;
    const r: any = await invoke("system_check", { dir });
    const g = r.gpus.map((x: any) => `${x.name} (${(x.vram_mb / 1024).toFixed(0)} GB)`).join(", ") || t("setup.noGpu");
    report = t("setup.report", { gpu: g, free: r.free_gb?.toFixed(0) ?? "?", verdict: r.verdict });
    if (!app.cfg.install_dir) app.cfg.base_model = r.recommended_base;
    app.cfg.install_dir = dir; await saveCfg(); await refreshModels();
  }
  async function pick() { const d = await open({ directory: true }); if (typeof d === "string") await check(d); }
  async function downloadAll() { for (const it of needed) if (!it.installed && it.url) invoke("download", { id: it.id }).catch((e) => (app.progress[it.id] = String(e))); }
  // models without a public download yet (local test files such as CharRef): the user picks the file on this PC - also later, to swap it
  async function addLocal(id: string, file: string) {
    const ext = file.split(".").pop() ?? "";
    const f = await open({ filters: [{ name: file, extensions: [ext] }] });
    if (typeof f !== "string") return;
    try { await invoke("import_model", { id, path: f }); await refreshModels(); } catch (e) { app.progress[id] = String(e); }
  }
  // extracting the 2 GB engine archive takes minutes: show it at the button, not only in the note at the page end
  let installing = $state(false), installMsg = $state("");
  async function install() {
    installing = true; installMsg = t("setup.installing");
    try { installMsg = t("setup.installedMsg", { list: (await invoke<string[]>("install_comfy")).join(", ") }); } catch (e) { installMsg = String(e); }
    installing = false; refreshModels();
  }
  async function loadMcp() { try { mcp = await invoke("mcp_info"); } catch { mcp = null; } }
  async function toggleMcp(e: Event) { if (!app.cfg) return; app.cfg.mcp_enabled = (e.target as HTMLInputElement).checked; await saveCfg(); msg = t("mcp.saved"); loadMcp(); }
  async function copyMcp() { await navigator.clipboard.writeText(JSON.stringify(mcp.mcp_json, null, 2)); msg = t("mcp.copied"); }
  $effect(() => { loadMcp(); });

  // guided first start: four steps, each done when its state is there; the first open one is the current step
  const extra = $derived(app.catalog.filter((c) => !needed.includes(c)));
  const left = $derived(needed.filter((c) => !c.installed));
  const leftBytes = $derived(left.reduce((a, c) => a + Math.max(0, c.size - (c.partial_bytes ?? 0)), 0));
  const steps = $derived([
    { id: "plugins", done: app.pluginsChosen && !dirty, status: app.pluginsChosen && !dirty ? t("step.pluginsDone", { n: sel.length }) : t("step.pluginsTodo") },
    { id: "folder", done: !!app.cfg?.install_dir, status: app.cfg?.install_dir || t("step.folderTodo") },
    { id: "models", done: !!app.cfg?.install_dir && needed.length > 0 && !left.length,
      status: !app.cfg?.install_dir ? t("step.after", { n: 2 }) : left.length ? t("step.modelsTodo", { n: left.length, size: gb(leftBytes) }) : t("step.modelsDone", { n: needed.length }) },
    { id: "engine", done: app.server.installed,
      status: app.server.running ? t("step.engineRunning") : app.server.installed ? t("step.engineReady") : t("step.engineTodo") },
  ]);
  const current = $derived(steps.findIndex((x) => !x.done));
  const go = (id: string) => document.getElementById(`step-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
</script>

{#snippet rows(list: typeof app.catalog)}
  <table>
    <thead><tr><th>{t("setup.file")}</th><th>{t("setup.size")}</th><th>{t("setup.state")}</th><th></th></tr></thead>
    <tbody>
      {#each list as c (c.id)}
        <tr>
          <td>{c.name}<div class="muted small"><span class="need {c.kind}">{t(`setup.kind.${c.kind}` as Key)}</span>{#if c.note} · {c.note}{/if}{#if c.license} · {c.license}{/if}{#if !c.url && !c.installed} · {t("setup.localNote")}{/if}</div></td>
          <td class="num">{gb(c.size)}</td>
          <td>{c.installed ? t("setup.installed") : c.partial_bytes ? t("setup.partial", { size: gb(c.partial_bytes) }) : t("setup.missing")} <span class="muted small">{app.progress[c.id] ?? ""}</span></td>
          <td class="act">{#if !c.url}<button class="btn quiet" onclick={() => addLocal(c.id, c.file)}>{t(c.installed ? "setup.replace" : "setup.local")}</button>{:else if !c.installed}<button class="btn quiet" onclick={() => invoke("download", { id: c.id })}>{t("setup.dl")}</button>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<div class="setup">
  <h1>{t("setup.title")}</h1>
  <p class="muted lead">{t("setup.lead")}</p>

  <ol class="steps" aria-label={t("step.aria")}>
    {#each steps as st, i}
      <li class:done={st.done} class:cur={i === current}>
        <button onclick={() => go(st.id)}>
          <span class="dot" aria-hidden="true">{st.done ? "✓" : i + 1}</span>
          <span class="st"><b>{t(`step.${st.id}` as Key)}</b><small>{st.status}</small></span>
        </button>
      </li>
    {/each}
  </ol>
  {#if current === -1}
    <p class="ready">{t("step.allDone")} <button class="btn primary" onclick={() => (app.section = "project")}>{t("step.toProject")}</button></p>
  {/if}

  <section class="plugins step" id="step-plugins" class:cur={current === 0}>
    <h2><span class="n">1</span>{t("plg.title")}</h2>
    <p class="muted">{t(app.pluginsChosen ? "plg.lead" : "plg.first")}</p>
    {#each GROUPS as [g, test]}
    {#if app.plugins.some(test)}
    <h3 class="group">{t(`plg.group.${g}` as Key)}</h3>
    <div class="cards">
      {#each app.plugins.filter(test) as p (p.id)}
        <label class="card" class:on={sel.includes(p.id)}>
          <input type="checkbox" checked={sel.includes(p.id)} onchange={(e) => { (e.target as HTMLInputElement).checked = sel.includes(p.id); toggle(p); }} />
          <span class="pname">{p.name} <small>{p.version}</small></span>
          <span class="kind">{p.kinds.map((k) => t(`plg.kind.${k}` as Key)).join(" · ")} · {p.family}</span>
          {#if p.description}<span class="desc">{p.description}</span>{/if}
          <span class="meta">{t("plg.download", { size: gb(p.download_bytes) })} · {p.license}{#if p.noncommercial_models.length} · <b class="nc">{t("plg.nc")}</b>{/if}</span>
          {#if p.requires?.length || p.requires_one?.length}<span class="meta">{t(p.requires?.length ? "plg.uses" : "plg.usesOne", { list: [...(p.requires ?? []), ...(p.requires_one ?? [])].map((r) => byId(r)?.name ?? r).join(p.requires?.length ? ", " : " / ") })}</span>{/if}
        </label>
        {#if ask && askAt === p.id}
          {@const m = licOf(ask)}
          <div class="ask inline" role="alertdialog" aria-labelledby="ask-title" use:reveal>
            <p id="ask-title"><b>{ask.name}</b> · {t("plg.ncAsk", { lic: m?.license ?? "", models: ask.noncommercial_models.join(", ") })}</p>
            <div class="row">
              <button class="btn primary" onclick={accept}>{t("plg.accept")}</button>
              {#if m?.license_url}<button class="btn quiet" onclick={() => readLicense(m.license_url)}>{t("plg.read")}</button>{/if}
              <button class="btn quiet" onclick={() => (ask = null)}>{t("plg.cancel")}</button>
            </div>
          </div>
        {/if}
      {/each}
    </div>
    {/if}
    {/each}
    {#if blocked}<p class="warn">{blocked}</p>{/if}
    <div class="row"><button class="btn primary" onclick={savePlugins} disabled={!dirty && app.pluginsChosen}>{t("plg.save")}</button></div>
  </section>

  <section class="step" id="step-folder" class:cur={current === 1}>
    <h2><span class="n">2</span>{t("setup.dir")}</h2>
    <p class="muted">{t("step.folderLead")}</p>
    <div class="row"><input value={app.cfg?.install_dir ?? ""} onchange={(e) => check((e.target as HTMLInputElement).value.trim())} placeholder={t("setup.dirPh")} /><button class="btn" onclick={pick}>{t("setup.pick")}</button></div>
    {#if report}<p class="muted">{report}</p>{/if}
  </section>

  <section class="step" id="step-models" class:cur={current === 2} class:wait={!app.cfg?.install_dir}>
    <h2><span class="n">3</span>{t("setup.models")}</h2>
    <p class="muted">{app.cfg?.install_dir ? t("step.modelsLead") : t("setup.noModels")}</p>
    {#if app.cfg?.install_dir}
      <div class="row"><button class="btn primary" onclick={downloadAll} disabled={!left.length}>{t("setup.dlAll")}</button>
        <span class="muted small">{steps[2].status}</span></div>
      {@render rows(needed)}
      {#if extra.length}
        <details class="extra">
          <summary>{t("step.extra", { n: extra.length })}</summary>
          {@render rows(extra)}
        </details>
      {/if}
    {/if}
  </section>

  <section class="step" id="step-engine" class:cur={current === 3} class:wait={current !== -1 && current < 3}>
    <h2><span class="n">4</span>{t("step.engine")}</h2>
    <p class="muted">{t("step.engineLead")}</p>
    <div class="row"><button class="btn" class:primary={!app.server.installed} disabled={installing} onclick={install}>{t(installing ? "setup.installingBtn" : "setup.install")}</button>
      <button class="btn" class:primary={app.server.installed && !app.server.running} onclick={() => invoke("server_start")}>{t("setup.start")}</button>
      <span class="muted small">{steps[3].status}</span></div>
    {#if installMsg}<p class="note" role="status">{installMsg}</p>{/if}
    {#if app.server.installed && !app.server.version_ok}<p class="note">{t("setup.engineOld", { v: app.server.version ?? "?" })}</p>{/if}
    {#if app.server.log_tail}<pre>{app.server.log_tail}</pre>{/if}
  </section>

  <h2 class="more">{t("step.more")}</h2>
  <section>
    <h2>{t("setup.look")}</h2>
    <div class="prefs">
      <label for="lang">{t("setup.lang")}</label>
      <select id="lang" bind:value={prefs.lang} onchange={applyPrefs}>{#each LANGS as [id, name]}<option value={id}>{name}</option>{/each}</select>
      <span id="theme-label">{t("setup.theme")}</span>
      <div class="seg" role="radiogroup" aria-labelledby="theme-label">
        {#each THEMES as th}
          <button role="radio" aria-checked={prefs.theme === th} class:on={prefs.theme === th} onclick={() => { prefs.theme = th; applyPrefs(); }}>{t(`theme.${th}`)}</button>
        {/each}
      </div>
      <span id="palette-label">{t("setup.palette")}</span>
      <div class="seg" role="radiogroup" aria-labelledby="palette-label">
        {#each PALETTES as pa}
          <button role="radio" aria-checked={prefs.palette === pa} class:on={prefs.palette === pa} onclick={() => { prefs.palette = pa; applyPrefs(); }}><i class="sw {pa}"></i>{t(`palette.${pa}`)}</button>
        {/each}
      </div>
      <label for="strip">{t("setup.strip")}</label>
      <label class="expert"><input id="strip" type="checkbox" checked={!!app.cfg?.export_strip_prompt}
        onchange={(e) => { if (app.cfg) { app.cfg.export_strip_prompt = (e.target as HTMLInputElement).checked; saveCfg(); } }} /> {t("setup.stripHint")}</label>
      <label for="expert">{t("setup.expert")}</label>
      <label class="expert"><input id="expert" type="checkbox" bind:checked={prefs.expert} onchange={applyPrefs} /> {t("setup.expertHint")}</label>
    </div>
  </section>

  <section>
    <h2>{t("mcp.title")}</h2>
    <p class="muted">{t("mcp.lead")}</p>
    <label class="check"><input type="checkbox" checked={app.cfg?.mcp_enabled} onchange={toggleMcp} /> {t("mcp.enable")}</label>
    {#if mcp}<pre>{JSON.stringify(mcp.mcp_json, null, 2)}</pre><button class="btn quiet" onclick={copyMcp}>{t("mcp.copy")}</button>{/if}
  </section>

  <!-- authorship: the licence requires this notice to stay in every copy -->
  <section class="about">
    <h2>{t("about.title")}</h2>
    <p><b>Fumika</b> {APP_VERSION} · {t("about.by", { who: "7err4" })} · <span class="code">github.com/7err4</span></p>
    <p class="muted">{t("about.license")}</p>
    <p class="muted">Copyright (c) 2026 7err4. {t("about.notice")}</p>
  </section>
  {#if msg}<p class="note">{msg}</p>{/if}
</div>

<style>
  .setup { overflow: auto; padding: 28px 40px 48px; max-width: 980px; }
  h1 { font-size: 24px; }
  .lead { max-width: 68ch; margin: 6px 0 8px; }
  section { margin-top: 30px; padding-top: 18px; border-top: 1px dashed var(--nr); }
  h2 { font-size: 16px; margin-bottom: 10px; }
  .prefs { display: grid; grid-template-columns: auto minmax(180px, 240px); gap: 10px 18px; align-items: center; justify-content: start; }
  .prefs label, .prefs > span { font-size: 13px; font-weight: 600; color: var(--ink-2); }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius); padding: 2px; background: var(--sheet); }
  .seg button { flex: 1; border: 0; background: none; padding: 6px 12px; border-radius: 3px; color: var(--ink-2); font-weight: 500; font-size: 13px; cursor: pointer; }
  .seg button:hover { background: var(--nr-wash); }
  .seg button.on { background: var(--nr-tint); color: var(--ink); font-weight: 600; }
  /* palette swatches show the scheme itself, whatever palette is active */
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 7px; vertical-align: -1px; }
  .sw.fumika { background: #6fb3e8; box-shadow: 0 0 0 1px #1f6aa8; }
  .sw.terra { background: #e0505f; box-shadow: 0 0 0 1px #f2a7bb; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin: 12px 0; }
  .card { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 12px 14px 12px 40px; border: 1px solid var(--rule);
    border-radius: var(--radius); background: var(--sheet); cursor: pointer; }
  .card:hover { border-color: var(--nr); }
  .card.on { border-color: var(--nr); box-shadow: inset 0 0 0 1px var(--nr); }
  .card input { position: absolute; left: 14px; top: 14px; }
  .pname { font-weight: 700; } .pname small { font-weight: 500; color: var(--ink-3); }
  .expert { display: flex; gap: 8px; align-items: center; font-weight: 500; }
  .group { font-size: 13px; font-weight: 700; color: var(--ink-2); margin: 14px 0 6px; letter-spacing: .02em; }
  .warn { color: var(--pencil); font-weight: 600; font-size: 13px; }
  .need { font-weight: 600; }
  .need.required { color: var(--nr-text); }
  .kind { font-size: 12.5px; color: var(--nr-text); font-weight: 600; }
  .desc { font-size: 13px; color: var(--ink-2); }
  .meta { font-size: 12px; color: var(--ink-3); }
  .nc { color: var(--pencil); font-weight: 600; }
  .ask { border: 1px solid var(--pencil); background: var(--pencil-wash); border-radius: var(--radius); padding: 12px 14px; max-width: 72ch; }
  .ask p { margin: 0 0 4px; }
  .ask.inline { grid-column: 1 / -1; max-width: none; }
  .about p { margin: 4px 0; max-width: 72ch; }
  .about .code { font-variant-numeric: tabular-nums; color: var(--nr-text); }
  .row { display: flex; gap: 8px; align-items: center; margin: 12px 0; flex-wrap: wrap; }
  .row input { flex: 1; min-width: 320px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-size: 11px; letter-spacing: .07em; text-transform: uppercase; color: var(--nr-text); padding: 6px 8px; border-bottom: 1px solid var(--nr); }
  td { padding: 9px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
  .num { white-space: nowrap; }
  .act { text-align: right; }
  .small { font-size: 12px; }
  pre { background: var(--sheet); border: 1px solid var(--rule); border-radius: var(--radius); padding: 12px; font-size: 12px; overflow: auto; max-height: 220px; }
  .check { display: flex; gap: 8px; align-items: center; margin: 8px 0; }
  .note { color: var(--nr-text); font-weight: 600; }
  /* guided steps */
  .steps { list-style: none; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; padding: 0; margin: 18px 0 4px; }
  .steps button { display: flex; gap: 10px; align-items: flex-start; width: 100%; text-align: left; padding: 10px 12px; border: 1px solid var(--rule);
    border-radius: var(--radius); background: var(--sheet); color: var(--ink); cursor: pointer; font: inherit; }
  .steps button:hover { border-color: var(--nr); }
  .steps .cur button { border-color: var(--nr); box-shadow: inset 0 0 0 1px var(--nr); }
  .dot { flex: none; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 700;
    border: 1.5px solid var(--ink-3); color: var(--ink-2); }
  .cur .dot { border-color: var(--nr); color: var(--nr-text); }
  .done .dot { background: var(--nr); border-color: var(--nr); color: var(--sheet); }
  .st { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .st b { font-size: 13px; }
  .st small { font-size: 12px; color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ready { display: flex; gap: 12px; align-items: center; font-weight: 600; color: var(--nr-text); }
  h2 .n { display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: 8px; border-radius: 50%; font-size: 12px;
    background: var(--nr-wash); color: var(--nr-text); vertical-align: 1px; }
  .step.cur h2 .n { background: var(--nr); color: var(--sheet); }
  .step.wait { opacity: .6; }
  .extra { margin-top: 14px; }
  .extra summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
  .more { margin-top: 40px; font-size: 13px; letter-spacing: .07em; text-transform: uppercase; color: var(--ink-3); }
  @media (max-width: 760px) { .steps { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
