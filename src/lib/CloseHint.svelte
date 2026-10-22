<script lang="ts">
  // First close of the window: Fumika keeps running in the tray (the queue renders on) - say so once, offer to quit instead.
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { inTauri } from "./store.svelte";
  import { t } from "./i18n.svelte";

  let open = $state(false), remember = $state(true);
  $effect(() => {
    if (!inTauri()) return;
    const un = listen("close-asked", () => { open = true; });
    return () => { un.then((f) => f()); };
  });
  async function choose(choice: "tray" | "quit") {
    open = false;
    await invoke("close_choice", { choice, remember }).catch(() => {});
  }
</script>

{#if open}
  <div class="veil">
    <div class="box" role="alertdialog" aria-modal="true" aria-labelledby="close-title" aria-describedby="close-text">
      <h2 id="close-title">{t("close.title")}</h2>
      <p id="close-text">{t("close.text")}</p>
      <p class="how">{t("close.how")}</p>
      <label class="check"><input type="checkbox" bind:checked={remember} /> {t("close.remember")}</label>
      <div class="row">
        <button class="btn primary" onclick={() => choose("tray")}>{t("close.tray")}</button>
        <button class="btn" onclick={() => choose("quit")}>{t("close.quit")}</button>
        <button class="btn quiet" onclick={() => (open = false)}>{t("close.cancel")}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .veil { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: rgba(0, 0, 0, .45); }
  .box { width: min(480px, calc(100vw - 32px)); background: var(--sheet); border: 1px solid var(--nr); border-radius: var(--radius);
    box-shadow: var(--lift); padding: 20px 22px 16px; }
  h2 { font-size: 16px; margin: 0 0 8px; }
  p { margin: 0 0 8px; color: var(--ink-2); font-size: 13.5px; }
  .how { color: var(--nr-text); font-weight: 600; }
  .check { display: flex; gap: 8px; align-items: center; font-size: 13px; margin: 10px 0 4px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
