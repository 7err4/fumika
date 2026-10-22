<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { app, inTauri, refreshJobs, type Gate } from "./store.svelte";
  import { t, jobLabel, type Key } from "./i18n.svelte";

  const jobs = $derived([...app.jobs].reverse());
  async function cancel(id: string) { await invoke("queue_cancel", { id }); refreshJobs(); }
  async function retry(id: string) { await invoke("queue_retry", { id }); refreshJobs(); }
  async function override(on: boolean) {
    if (inTauri()) app.gate = await invoke<Gate>("queue_override", { on });
    else app.gate = { ...app.gate, overridden: on, paused: !on };
  }
</script>

<div class="q">
  <header><h1>{t("nav.queue")}</h1><span class="muted">{t("queue.sub")}</span></header>
  {#if app.gate.training}
    <div class="gate" class:over={app.gate.overridden} role="status">
      <p><b>{app.gate.overridden ? t("gate.overridden") : t("gate.paused")}</b> · {t("gate.banner", { what: app.gate.training })}</p>
      <button class="btn quiet" onclick={() => override(!app.gate.overridden)}>{app.gate.overridden ? t("gate.wait") : t("gate.override")}</button>
    </div>
  {/if}
  {#if jobs.length}
    <table>
      <thead><tr><th>{t("queue.project")}</th><th>{t("queue.job")}</th><th>{t("queue.state")}</th><th>{t("queue.attempts")}</th><th></th></tr></thead>
      <tbody>
        {#each jobs as j (j.id)}
          <tr class={j.state}>
            <td>{j.project}</td><td>{jobLabel(j.label)}</td>
            <td><span class="st">{t(`state.${j.state}` as Key)}</span>{#if j.error}<div class="err">{j.error}</div>{/if}</td>
            <td class="num">{(j as any).attempts ?? ""}</td>
            <td class="act">
              {#if j.state === "queued" || j.state === "running"}<button class="btn quiet" onclick={() => cancel(j.id)}>{t("queue.cancel")}</button>{/if}
              {#if j.state === "failed" || j.state === "cancelled"}<button class="btn quiet" onclick={() => retry(j.id)}>{t("queue.retry")}</button>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="muted empty">{t("queue.empty")}</p>
  {/if}
</div>

<style>
  .q { overflow: auto; padding: 24px 32px 40px; }
  header { display: flex; align-items: baseline; gap: 14px; margin-bottom: 18px; }
  h1 { font-size: 22px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-size: 11px; letter-spacing: .07em; text-transform: uppercase; color: var(--nr-text); padding: 6px 8px; border-bottom: 1px solid var(--nr); }
  td { padding: 10px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
  .st { font-weight: 600; }
  .queued .st { color: var(--nr-text); }
  .running .st { color: var(--ink); }
  .failed .st, .err { color: var(--pencil); }
  .cancelled .st { color: var(--ink-3); text-decoration: line-through; }
  .err { font-size: 12px; margin-top: 3px; }
  .act { text-align: right; }
  .empty { max-width: 60ch; }
  /* a training holds the queue: a blue margin note across the table, not an error */
  .gate { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 0 0 16px; padding: 10px 12px;
    border: 1px dashed var(--nr); background: var(--nr-wash); font-size: 13px; }
  .gate p { margin: 0; max-width: 80ch; color: var(--ink-2); }
  .gate b { color: var(--nr-text); }
  .gate.over { background: var(--sheet); }
</style>
