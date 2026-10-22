// Expert settings: off = the tested defaults, on = overrides; changed() marks what differs from the recommendation.
import { test } from "node:test";
import assert from "node:assert/strict";
import { adv, changed, pageVars, autoHint, RECOMMENDED } from "../src/lib/expert.ts";

const rnd = () => 42;

test("expert mode off sends the tested defaults, whatever the project holds", () => {
  const a = adv({ steps: 12, sampler: "dpmpp_2m", seed: 7 });
  assert.deepEqual(pageVars(a, false, rnd), { seed: 42, versions: 3, lora_strength: 1, sft_strength: 1.5, reference_strength: 1 });
});

test("expert mode on sends the overrides; empty = auto", () => {
  const v = pageVars(adv({ steps: 12, cfg: 4.5, sampler: "dpmpp_2m", slg: " ", negative: "", seed: 7, versions: 12 }), true, rnd, 2);
  assert.equal(v.seed, 2007);              // fixed seed, reproducible per page
  assert.equal(v.versions, 8);             // clamped to the node's range
  assert.deepEqual([v.steps, v.cfg, v.sampler, v.scheduler, v.slg_layers, v.negative], [12, 4.5, "dpmpp_2m", "auto", "auto", "auto"]);
  assert.equal(pageVars(adv(), true, rnd).seed, 42);   // seed 0 = random
});

test("changed() lists only what differs from the recommendation", () => {
  assert.deepEqual(changed(adv()), []);
  assert.deepEqual(changed(adv({ steps: 12, sftStrength: 1.2 })), ["steps", "sftStrength"]);
  assert.deepEqual(adv({}), RECOMMENDED);
  assert.equal(autoHint("steps", true), "50");
  assert.equal(autoHint("scheduler", false), "simple");
});
