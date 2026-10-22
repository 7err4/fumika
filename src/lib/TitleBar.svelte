<script lang="ts">
  // Own title bar (the window has no OS decorations): continues the board instead of a black system strip.
  // The whole bar is a drag region (double-click maximizes); the three window buttons sit at the right like on Windows.
  import { onMount } from "svelte";
  import { Minus, Square, Copy, X } from "lucide-svelte";
  import { app, inTauri } from "./store.svelte";
  import { t, type Key } from "./i18n.svelte";

  let maximized = $state(false);
  let win: any = null;
  const where = $derived(app.section === "project" ? `${app.title} · ${app.chapterTitle}` : t(`nav.${app.section}` as Key));

  onMount(() => {
    if (!inTauri()) return;
    let off = () => {};
    import("@tauri-apps/api/window").then(async ({ getCurrentWindow }) => {
      win = getCurrentWindow();
      maximized = await win.isMaximized();
      off = await win.onResized(async () => { maximized = await win.isMaximized(); });
    });
    return () => off();
  });
</script>

<header class="bar" data-tauri-drag-region>
  <div class="mark" data-tauri-drag-region><img src="/app-icon.png" alt="" width="18" height="18" /><span>Fumika</span></div>
  <div class="where" data-tauri-drag-region>{where}</div>
  <div class="ctl">
    <button onclick={() => win?.minimize()} aria-label={t("win.min")} title={t("win.min")}><Minus size={15} strokeWidth={1.5} /></button>
    <button onclick={() => win?.toggleMaximize()} aria-label={t(maximized ? "win.restore" : "win.max")} title={t(maximized ? "win.restore" : "win.max")}>
      {#if maximized}<Copy size={12} strokeWidth={1.5} />{:else}<Square size={12} strokeWidth={1.5} />{/if}
    </button>
    <button class="close" onclick={() => win?.close()} aria-label={t("win.close")} title={t("win.close")}><X size={16} strokeWidth={1.5} /></button>
  </div>
</header>

<style>
  .bar { height: 38px; display: grid; grid-template-columns: var(--rail) 1fr auto; align-items: center; background: var(--board);
    border-bottom: 1px solid var(--rule); user-select: none; }
  .mark { display: flex; align-items: center; gap: 9px; padding-left: 16px; font-weight: 700; font-size: 13px; letter-spacing: -.005em; }
  .mark img { border-radius: 4px; }   /* drawn head, 64 px source: sharp on high-DPI screens */
  .mark > * { pointer-events: none; } /* drag regions only count on the element itself */
  .where { font-size: 12.5px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-left: 28px; }
  .ctl { display: flex; height: 100%; }
  .ctl button { width: 46px; height: 100%; border: 0; background: none; color: var(--ink-2); display: grid; place-items: center; cursor: default;
    transition: background .12s ease-out, color .12s ease-out; }
  .ctl button:hover { background: var(--nr-wash); color: var(--ink); }
  .ctl .close:hover { background: var(--pencil); color: #fff; }
  .ctl button:focus-visible { outline-offset: -2px; }
</style>
