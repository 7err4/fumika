// Page rendering: one easy-page graph per page goes into the persistent Rust render queue (queue_add, job-update events);
// images come through the comfyimg URI scheme. The webview never talks to ComfyUI directly, so ComfyUI keeps its origin
// check (no --enable-cors-header).
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/** variables of the MOSS Doujin plugin's "page" workflow (plugins/moss-doujin/workflows/page.json, rendered in Rust) */
export interface PageJob {
  style: string; characters: string; page: string; lora: string; base_model: string; sft_look: string;
  reference: string; reference_lora: string; reference_character: string; reading_direction: string; quality: boolean; seed: number; prefix: string;
  // expert mode (expert.ts pageVars); left out = the workflow defaults
  versions?: number; lora_strength?: number; sft_strength?: number; reference_strength?: number; sampler?: string; scheduler?: string;
  steps?: number; cfg?: number; slg_layers?: string; negative?: string; loras?: string;
}

// custom URI schemes are served as http://<scheme>.localhost on Windows (and Android), <scheme>://localhost elsewhere
const IMG_BASE = navigator.userAgent.includes("Windows") ? "http://comfyimg.localhost" : "comfyimg://localhost";
export const viewUrl = (im: { filename: string; subfolder: string; type: string }) =>
  `${IMG_BASE}/view?filename=${encodeURIComponent(im.filename)}&subfolder=${encodeURIComponent(im.subfolder)}&type=${im.type}`;

/** a reference picture in ComfyUI/input ("fumika_refs/x.png") as a viewable URL */
export const inputUrl = (name: string) => {
  const i = name.lastIndexOf("/");
  return viewUrl({ filename: name.slice(i + 1), subfolder: i < 0 ? "" : name.slice(0, i), type: "input" });
};

export interface Job { id: string; project: string; label: string; state: "queued" | "running" | "done" | "failed" | "cancelled";
  outputs: any; error: string | null }

/** best + alternative versions of a finished page job (graph nodes 2 = best, 3 = versions) */
export function pageImages(job: Job): { best: string; versions: string[] } {
  return { best: viewUrl(job.outputs["2"].images[0]), versions: (job.outputs["3"]?.images ?? []).map(viewUrl) };
}

/** Queue one page in the persistent render queue (survives app restarts) and wait for it. */
export async function renderPage(j: PageJob, project: string, label: string, onQueued?: (jobId: string) => void,
  signal?: AbortSignal): Promise<{ best: string; versions: string[] }> {
  const id = await invoke<string>("queue_workflow", { project, label, plugin: "moss-doujin", workflow: "page", vars: j });
  onQueued?.(id);
  return waitFor(id, signal);
}

/** Resolve when the queued job finishes (also for jobs queued before an app restart). */
export function waitFor(id: string, signal?: AbortSignal): Promise<{ best: string; versions: string[] }> {
  return waitJob(id, signal).then(pageImages);
}

/** Resolve with the finished job (its ComfyUI history outputs), reject when it fails or is cancelled. */
export function waitJob(id: string, signal?: AbortSignal): Promise<Job> {
  return new Promise((resolve, reject) => {
    let stop = () => {};
    const settle = (job: Job) => {
      if (job.state === "done") { stop(); resolve(job); }
      else if (job.state === "failed" || job.state === "cancelled") { stop(); reject(new Error(job.error ?? job.state)); }
    };
    listen<Job>("job-update", (ev) => { if (ev.payload.id === id) settle(ev.payload); }).then((un) => {
      stop = un;
      invoke<Job[]>("queue_list", {}).then((all) => { const j = all.find((x) => x.id === id); if (j) settle(j); });
    });
    signal?.addEventListener("abort", () => { invoke("queue_cancel", { id }); });
  });
}

/** cancel every queued / running job of a project */
export async function cancelProject(project: string) {
  const jobs = await invoke<Job[]>("queue_list", { project });
  await Promise.all(jobs.filter((j) => j.state === "queued" || j.state === "running").map((j) => invoke("queue_cancel", { id: j.id })));
}

/** split a story into page blocks (empty line = new page) */
export function splitPages(story: string): string[] {
  return story.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
}

// sample images of training runs: trainimg URI scheme, only files below models/loras/<family>_training
const TRAIN_BASE = navigator.userAgent.includes("Windows") ? "http://trainimg.localhost" : "trainimg://localhost";
export const trainImgUrl = (rel: string) => `${TRAIN_BASE}/img?path=${encodeURIComponent(rel)}`;
