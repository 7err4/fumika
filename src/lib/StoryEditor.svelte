<script lang="ts">
  // Page editor: panel cards over the same page text the node reads (story.ts parses and writes it back), or the raw text.
  import { untrack } from "svelte";
  import { ChevronUp, ChevronDown, Trash2, Plus, X } from "lucide-svelte";
  import { app, setPageText, save } from "./store.svelte";
  import { t, type Key } from "./i18n.svelte";
  import { charNames, parsePage, serialisePage, panelCast, KINDS, MAX_PANELS, MOODS, moodOf, setMood, plainWhat, type Mood, type Panel,
    type TextItem } from "./story";
  import { sceneOf, itemState, toggleChange, movePanel, removePanel as dropSceneChanges, type CastEntry } from "./scene";

  const VIEW_KEY = "fumika-editor-view";
  let view = $state<"cards" | "text">((() => { try { return localStorage.getItem(VIEW_KEY) === "text" ? "text" : "cards"; } catch { return "cards"; } })());
  const setView = (v: "cards" | "text") => { view = v; try { localStorage.setItem(VIEW_KEY, v); } catch { /* per-viewer convenience only */ } };

  const page = $derived(app.pages[app.selected]);
  const names = $derived(charNames(app.characters));
  const scene = $derived(sceneOf(app.scenes, app.selected));
  // scene cast on a card with an outfit list: their items can be ticked as "changes here"
  const dressed = (p: Panel) => (scene?.cast ?? []).filter((c) => c.items.length && panelCast(p, names).includes(c.name));
  const changeAt = (c: CastEntry, item: string, k: number) =>
    scene?.changes.find((ch) => ch.char === c.name && ch.item === item && ch.page === app.selected && ch.panel === k);
  const offHere = (c: CastEntry, k: number) =>
    (scene?.changes ?? []).filter((ch) => ch.char === c.name && ch.page === app.selected && ch.panel === k && ch.to === "off");
  const itemName = (c: CastEntry, id: string) => { const it = c.items.find((x) => x.id === id); return it?.name || it?.wording || ""; };
  let cards = $state<Panel[]>([]);
  let draft = $state("");
  // the page + text this editor wrote last: re-reading it would drop a freshly added, still empty card
  let written = { sel: -1, text: "", names: "" };
  $effect(() => {
    const txt = page?.text ?? "", sel = app.selected, n = names;
    untrack(() => {
      if (sel === written.sel && txt === written.text && n.join("|") === written.names) return;
      cards = parsePage(txt, n); draft = txt; written = { sel, text: txt, names: n.join("|") };
    });
  });

  function commit() {
    // joined bubbles lose their partner when the one above changes speaker or goes away
    for (const p of cards) p.texts.forEach((it, k) => { if (it.joined && !canJoin(p, k)) it.joined = false; });
    const txt = serialisePage(cards);
    if (!txt || !page || txt === page.text) return;   // an all-empty page would delete the page
    written = { sel: app.selected, text: txt, names: names.join("|") }; draft = txt;
    setPageText(app.selected, txt);
  }
  function commitDraft() {
    if (page && draft.trim() && draft.trim() !== page.text) setPageText(app.selected, draft);   // the effect re-reads the cards
  }

  // speaker choices: nobody, each character, each pair ("together"), plus a group the text already uses
  const speakerOpts = (it: TextItem) => {
    const pairs = names.flatMap((a, i) => names.slice(i + 1).map((b) => `${a} & ${b}`));
    const cur = it.who.join(" & ");
    return [...new Set(["", ...names, ...pairs, ...(cur ? [cur] : [])])];
  };
  const setSpeaker = (it: TextItem, v: string) => { it.who = v ? v.split(" & ") : []; if (it.who.length !== 1) it.joined = false; commit(); };
  // "joined" only where the node can join: right after a bubble of the same single speaker
  const canJoin = (p: Panel, k: number) => {
    const it = p.texts[k], prev = p.texts[k - 1];
    return it.kind === "speech" && it.who.length === 1 && prev?.kind === "speech" && prev.who.length === 1 && prev.who[0] === it.who[0];
  };
  const setKind = (p: Panel, k: number, v: string) => {
    const it = p.texts[k]; it.kind = v as TextItem["kind"];
    if (it.kind !== "speech") { it.who = []; it.joined = false; }
    commit();
  };

  function move(i: number, d: -1 | 1) {
    const j = i + d;
    if (j < 0 || j >= cards.length) return;
    [cards[i], cards[j]] = [cards[j], cards[i]];
    movePanel(app.scenes, app.selected, i, j);
    commit();
  }
  function removePanel(i: number) { if (cards.length > 1) { cards.splice(i, 1); dropSceneChanges(app.scenes, app.selected, i); commit(); } }
  function addPanel() { if (cards.length < MAX_PANELS) cards.push({ what: "", texts: [{ kind: "speech", text: "", who: [], joined: false }] }); }
  function addText(p: Panel) { p.texts.push({ kind: "speech", text: "", who: [], joined: false }); }
  function removeText(p: Panel, k: number) { p.texts.splice(k, 1); commit(); }
</script>

<div class="edhead">
  <span class="label">{t("insp.panels")}</span>
  <div class="seg" role="tablist" aria-label={t("ed.view")}>
    <button role="tab" aria-selected={view === "cards"} class:on={view === "cards"} onclick={() => setView("cards")}>{t("ed.cards")}</button>
    <button role="tab" aria-selected={view === "text"} class:on={view === "text"} onclick={() => setView("text")}>{t("ed.text")}</button>
  </div>
</div>

{#if view === "text"}
  <p class="help">{t("insp.help")} <code>{t("insp.helpCode")}</code></p>
  <textarea id="pagetext" rows="7" bind:value={draft} onblur={commitDraft} aria-label={t("insp.panels")}></textarea>
{:else}
  <ol class="cards">
    {#each cards as p, i}
      <li class="card">
        <div class="ctop">
          <span class="pn">{t("ed.panel", { n: i + 1 })}</span>
          <select class="mood" class:on={moodOf(p.what) !== "normal"} value={moodOf(p.what)} aria-label={t("ed.mood")} title={t("ed.moodHint")}
            onchange={(e) => { p.what = setMood(p.what, e.currentTarget.value as Mood); commit(); }}>
            {#each MOODS as m}<option value={m}>{t(`ed.mood.${m}` as Key)}</option>{/each}
          </select>
          <span class="tools">
            <button class="icon" onclick={() => move(i, -1)} disabled={i === 0} aria-label={t("ed.up")} title={t("ed.up")}><ChevronUp size={15} /></button>
            <button class="icon" onclick={() => move(i, 1)} disabled={i === cards.length - 1} aria-label={t("ed.down")} title={t("ed.down")}><ChevronDown size={15} /></button>
            <button class="icon" onclick={() => removePanel(i)} disabled={cards.length < 2} aria-label={t("ed.del")} title={t("ed.del")}><Trash2 size={14} /></button>
          </span>
        </div>
        <textarea rows="2" value={plainWhat(p.what)} onchange={(e) => { p.what = setMood(e.currentTarget.value, moodOf(p.what)); commit(); }}
          placeholder={t("ed.what")} aria-label={t("ed.what")}></textarea>
        {#if panelCast(p, names).length}<p class="chips">{#each panelCast(p, names) as n}<span>{n}</span>{/each}</p>{/if}
        {#if scene}
          {#each dressed(p) as c (c.name)}
            <div class="clothes" role="group" aria-label={t("ed.clothes", { name: c.name })}>
              <span class="cn">{c.name}</span>
              {#each c.items as it (it.id)}
                {@const ch = changeAt(c, it.id, i)}
                <button class="cl" class:on={itemState(scene, c, app.selected, i).get(it.id)?.on} class:ch={!!ch}
                  onclick={() => { toggleChange(scene, c, it.id, app.selected, i); save(); }}
                  title={t(ch ? "ed.clothesUndo" : "ed.clothesHint")}>{ch ? (ch.to === "off" ? "↓ " : "↑ ") : ""}{it.name || it.wording}</button>
              {/each}
            </div>
            {#each offHere(c, i) as ch}
              <input class="where" bind:value={ch.where} onchange={save} placeholder={t("ed.where", { item: itemName(c, ch.item) })} aria-label={t("ed.where", { item: itemName(c, ch.item) })} />
            {/each}
          {/each}
        {/if}
        {#each p.texts as it, k}
          <div class="item">
            <div class="irow">
              <select value={it.kind} onchange={(e) => setKind(p, k, e.currentTarget.value)} aria-label={t("ed.kind")}>
                {#each KINDS as kd}<option value={kd}>{t(`ed.kind.${kd}` as Key)}</option>{/each}
              </select>
              {#if it.kind === "speech"}
                <select value={it.who.join(" & ")} onchange={(e) => setSpeaker(it, e.currentTarget.value)} aria-label={t("ed.speaker")}>
                  {#each speakerOpts(it) as o}<option value={o}>{o || t("ed.nobody")}</option>{/each}
                </select>
              {/if}
              <button class="icon" onclick={() => removeText(p, k)} aria-label={t("ed.delText")} title={t("ed.delText")}><X size={14} /></button>
            </div>
            <input bind:value={it.text} onchange={commit} placeholder={t("ed.textPh")} aria-label={t("ed.textPh")} />
            {#if canJoin(p, k)}
              <label class="join"><input type="checkbox" bind:checked={it.joined} onchange={commit} /> {t("ed.joined")}</label>
            {/if}
          </div>
        {/each}
        <button class="add" onclick={() => addText(p)}><Plus size={13} /> {t("ed.addText")}</button>
      </li>
    {/each}
  </ol>
  <button class="btn quiet addp" onclick={addPanel} disabled={cards.length >= MAX_PANELS}><Plus size={14} /> {t("ed.addPanel")}</button>
  {#if cards.length >= MAX_PANELS}<p class="help">{t("ed.max")}</p>{/if}
{/if}

<style>
  .edhead { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
  .label { font-size: 12.5px; font-weight: 600; color: var(--ink-2); }
  .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: var(--radius); overflow: hidden; }
  .seg button { border: 0; background: transparent; padding: 3px 10px; font-size: 12px; color: var(--ink-2); cursor: pointer; }
  .seg button.on { background: var(--nr-wash); color: var(--nr-text); font-weight: 600; }
  .help { margin: -2px 0 2px; font-size: 12px; color: var(--ink-3); }
  .help code { white-space: nowrap; font-family: inherit; color: var(--ink-2); background: var(--nr-wash); padding: 1px 5px; border-radius: 3px; }
  textarea, select, input:not([type="checkbox"]) { width: 100%; font-size: 13px; }
  .cards { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .card { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 6px; }
  .card textarea { field-sizing: content; min-height: 3.2em; max-height: 12em; resize: vertical; }
  .ctop { display: flex; align-items: center; justify-content: space-between; }
  .pn { font-size: 12px; font-weight: 700; color: var(--nr-text); letter-spacing: .02em; }
  .tools { display: inline-flex; gap: 2px; }
  .mood { width: auto !important; margin: 0 auto 0 8px; font-size: 11.5px !important; padding: 1px 4px; border: 1px solid transparent; background: transparent; color: var(--ink-3); }
  .mood.on { border-color: var(--nr-text); color: var(--nr-text); font-weight: 600; background: var(--nr-wash); }
  .icon { border: 0; background: transparent; color: var(--ink-3); padding: 3px; border-radius: 3px; cursor: pointer; display: inline-flex; }
  .icon:hover:not(:disabled) { background: var(--nr-wash); color: var(--ink); }
  .icon:disabled { opacity: .35; cursor: default; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 0; }
  .chips span { font-size: 11.5px; padding: 1px 7px; border: 1px solid var(--nr); border-radius: 99px; color: var(--nr-text); font-weight: 600; }
  .clothes { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .cn { font-size: 11.5px; font-weight: 600; color: var(--ink-3); margin-right: 2px; }
  .cl { font-size: 11.5px; padding: 1px 8px; border-radius: 99px; border: 1px dashed var(--ink-3); background: transparent; color: var(--ink-3); cursor: pointer; }
  .cl.on { border-style: solid; border-color: var(--ink-2); color: var(--ink); }
  .cl.ch { border: 1.5px solid var(--nr-text); background: var(--nr-wash); color: var(--nr-text); font-weight: 600; }
  .where { font-size: 12px !important; }
  .item { border-top: 1px dotted var(--nr-tint); padding-top: 6px; display: flex; flex-direction: column; gap: 4px; }
  .irow { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr) auto; gap: 4px; align-items: center; }
  .irow:not(:has(select + select)) { grid-template-columns: minmax(0, 1fr) auto; }
  .join { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--ink-2); font-weight: 500; }
  .add { align-self: flex-start; border: 0; background: transparent; color: var(--nr-text); font-size: 12px; font-weight: 600; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; padding: 2px 0; }
  .addp { align-self: flex-start; display: inline-flex; align-items: center; gap: 6px; }
</style>
