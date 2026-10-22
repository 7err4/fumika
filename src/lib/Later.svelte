<script lang="ts">
  import { t } from "./i18n.svelte";
  let { title, text }: { title: string; text: string } = $props();
</script>

<div class="later">
  <div class="sheet"><span class="g"></span><span class="g"></span><span class="g"></span></div>
  <h1>{title}</h1>
  <p class="muted">{text}</p>
  <p class="tag">{t("later.tag")}</p>
</div>

<style>
  .later { margin: auto; max-width: 52ch; text-align: center; padding: 40px; }
  .sheet { width: 120px; aspect-ratio: 3 / 4.25; margin: 0 auto 22px; border: 1px dashed var(--nr); padding: 10px; display: grid; grid-template-rows: 1fr 1.2fr 1fr; gap: 6px; }
  .g { border: 1px dashed var(--nr); }
  h1 { font-size: 20px; margin-bottom: 8px; }
  .tag { color: var(--nr-text); font-weight: 600; font-size: 12.5px; }
</style>
