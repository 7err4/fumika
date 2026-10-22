// Model families: file assignment, presets (applied, never forced), LoRA list encoding.
import { test } from "node:test";
import assert from "node:assert/strict";
import { familyOf, filesFor, helperLora, applyPreset, lorasJson, recommendedPresets, FAMILIES, setFamilies } from "../src/lib/families.ts";

test("files are assigned to their architecture by name", () => {
  assert.equal(familyOf("moss_image_base_bf16.safetensors"), "moss");
  assert.equal(familyOf("kromoss_bf16.safetensors"), "moss");
  assert.equal(familyOf("anima-base-v1.0.safetensors"), "anima");
  assert.equal(familyOf("anima-2.9b\\anima29.safetensors"), "anima");
  assert.equal(familyOf("myMix_v3.safetensors"), "");
  assert.equal(familyOf("sdxl\\myMix_v3.safetensors"), "sdxl");   // filed by the library: the folder decides
  assert.equal(familyOf("moss/anima_style_mix.safetensors"), "moss");
  // SDXL before Anima: "animagine-xl" contains "anima"
  assert.equal(familyOf("animagine-xl-4.0.safetensors"), "sdxl");
  assert.equal(familyOf("Illustrious-XL-v2.0.safetensors"), "sdxl");
  assert.equal(familyOf("waiIllustriousMix_v140.safetensors"), "sdxl");
  assert.equal(familyOf("hassakuAnima_v1Style.safetensors"), "anima");
  const all = ["anima-base-v1.0.safetensors", "kromoss_bf16.safetensors", "myMix_v3.safetensors", "moss_image_base_bf16.safetensors"];
  assert.deepEqual(filesFor(all, "moss").map((x) => [x.file, x.known]),
    [["kromoss_bf16.safetensors", true], ["moss_image_base_bf16.safetensors", true], ["myMix_v3.safetensors", false]]);
  assert.deepEqual(filesFor(all, "anima").map((x) => x.file), ["anima-base-v1.0.safetensors", "myMix_v3.safetensors"]);
  assert.ok(helperLora("kromoss_8steps_dmd_lora.safetensors") && helperLora("moss_image_sft_look_lora.safetensors") && !helperLora("fumika_v1.safetensors"));
});

test("presets go into the fields once and keep what the user wrote", () => {
  const q = recommendedPresets().find((p) => p.id === "anima-quality")!;
  const r = applyPreset(q, "1girl, park", "");
  assert.equal(r.prompt, "masterpiece, best quality, score_7, newest, 1girl, park");
  assert.ok(r.negative.startsWith("worst quality"));
  assert.equal(applyPreset(q, r.prompt, "my negative").prompt, r.prompt, "not added twice");
  const noNeg = { ...q, negative: "" };
  assert.equal(applyPreset(noNeg, "x", "kept").negative, "kept");
});

test("no architecture forces a negative prompt; presets are only offered", () => {
  for (const f of Object.values(FAMILIES)) assert.ok(!("negative" in f));
  assert.ok(recommendedPresets().every((p) => p.builtin));
});

test("families come from the switched-on family plugins", () => {
  const sdxl = FAMILIES.sdxl;
  setFamilies([sdxl]);
  assert.deepEqual(Object.keys(FAMILIES), ["sdxl"]);
  assert.equal(familyOf("anima-base-v1.0.safetensors"), "", "Anima switched off: its files are unknown");
  assert.deepEqual(recommendedPresets().map((p) => p.family), ["sdxl", "sdxl"]);
  setFamilies([]);   // nothing switched on: keep what there is
  assert.deepEqual(Object.keys(FAMILIES), ["sdxl"]);
});

test("LoRA list for the stack node", () => {
  assert.equal(lorasJson([{ name: "a.safetensors", strength: 0.8 }, { name: "none", strength: 1 }, { name: "b", strength: 0 }, { name: "", strength: 1 }]),
    '[{"name":"a.safetensors","strength":0.8}]');
  assert.equal(lorasJson([{ name: "a", strength: 1 }], 0.4), '[{"name":"a","strength":0.4}]');
});
