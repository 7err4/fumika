<script lang="ts">
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { app, boot, inTauri } from "./lib/store.svelte";
  import TitleBar from "./lib/TitleBar.svelte";
  import Rail from "./lib/Rail.svelte";
  import Workspace from "./lib/Workspace.svelte";
  import Setup from "./lib/Setup.svelte";
  import CloseHint from "./lib/CloseHint.svelte";
  import Reader from "./lib/Reader.svelte";
  import QueueView from "./lib/QueueView.svelte";
  import Library from "./lib/Library.svelte";
  import Later from "./lib/Later.svelte";
  import Trainer from "./lib/Trainer.svelte";
  import AssetStudio from "./lib/AssetStudio.svelte";
  import ImageStudio from "./lib/ImageStudio.svelte";
  import Lightbox from "./lib/Lightbox.svelte";
  import { resumeAssets } from "./lib/assets.svelte";
  import { initImages, resumeImages } from "./lib/images.svelte";
  import { t } from "./lib/i18n.svelte";

  // the main window starts hidden behind the splash; show it once the first state is loaded
  onMount(() => { boot().then(() => { if (inTauri()) { resumeAssets(); initImages(); resumeImages(); } }).catch(console.error).finally(() => { if (inTauri()) invoke("app_ready"); }); });
</script>

<TitleBar />
<div class="shell">
  <Rail />
  <div class="content">
    {#if app.section === "project"}<Workspace />
    {:else if app.section === "reader"}<Reader />
    {:else if app.section === "queue"}<QueueView />
    {:else if app.section === "library"}<Library />
    {:else if app.section === "setup"}<Setup />
    {:else if app.section === "assets"}<AssetStudio />
    {:else if app.section === "image"}<ImageStudio />
    {:else if app.section === "trainer"}<Trainer />
    {:else}
      <Later title={t("nav.trainer")} text={t("later.trainer")} />
    {/if}
  </div>
</div>
<Lightbox />
<CloseHint />

<style>
  :global(#app) { display: flex; flex-direction: column; }
  .shell { flex: 1; min-height: 0; display: grid; grid-template-columns: var(--rail) 1fr; }
  .content { min-width: 0; min-height: 0; display: flex; flex-direction: column; }
</style>
