// Expert settings of a project: "auto" / 0 / "" = the tested recipe (moss-doujin expert.py). Only sent while expert mode is on.
// Pure module (tests/expert.test.ts).

export interface Adv {
  sampler: string; scheduler: string; steps: number; cfg: number; slg: string; negative: string;
  /** fixed seed (0 = new random seed for every draw) */ seed: number;
  loraStrength: number; sftStrength: number; refStrength: number; versions: number;
}
export const RECOMMENDED: Adv = { sampler: "auto", scheduler: "auto", steps: 0, cfg: 0, slg: "auto", negative: "", seed: 0,
  loraStrength: 1.0, sftStrength: 1.5, refStrength: 1.0, versions: 3 };
// names that ComfyUI 0.42's KSampler knows (a wrong name would fail the job at validation)
export const SAMPLERS = ["auto", "euler", "euler_ancestral", "heun", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde", "uni_pc", "res_multistep", "ddim", "lcm"];
export const SCHEDULERS = ["auto", "simple", "sgm_uniform", "normal", "karras", "exponential", "beta", "linear_quadratic", "kl_optimal"];

export const adv = (a?: Partial<Adv>): Adv => ({ ...RECOMMENDED, ...(a ?? {}) });
/** settings that differ from the recommendation (marked in the UI, so a deliberate "steps 12" is visible later) */
export const changed = (a: Adv) => (Object.keys(RECOMMENDED) as (keyof Adv)[]).filter((k) => a[k] !== RECOMMENDED[k]);

/** what "auto" means for the current speed - shown next to the fields */
export function autoHint(k: keyof Adv, quality: boolean): string {
  return ({ sampler: "euler", scheduler: quality ? "sgm_uniform" : "simple", steps: quality ? "50" : "8", cfg: quality ? "3" : "1",
    slg: quality ? "22" : "off", negative: quality ? "extra speech bubbles, gibberish text, watermark" : "-" } as Partial<Record<keyof Adv, string>>)[k] ?? "";
}

/** workflow variables of the page job. Expert mode off -> nothing overridden (the tested defaults, seed random).
 *  A fixed seed stays reproducible per page: seed + 1000 * page index (like the book node). */
export function pageVars(a: Adv, on: boolean, random: () => number, page = 0) {
  if (!on) return { seed: random(), versions: RECOMMENDED.versions, lora_strength: RECOMMENDED.loraStrength,
    sft_strength: RECOMMENDED.sftStrength, reference_strength: RECOMMENDED.refStrength };
  return { seed: a.seed > 0 ? a.seed + 1000 * page : random(), versions: Math.max(1, Math.min(8, Math.round(a.versions))),
    sampler: a.sampler, scheduler: a.scheduler, steps: Math.max(0, Math.round(a.steps)), cfg: Math.max(0, a.cfg),
    slg_layers: a.slg.trim() || "auto", negative: a.negative.trim() || "auto",
    lora_strength: a.loraStrength, sft_strength: a.sftStrength, reference_strength: a.refStrength };
}
