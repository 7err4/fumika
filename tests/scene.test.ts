// Scene state writer: setting + clothing state in every panel (wording as tested 21 Oct), looks per scene, panel moves.
// Run: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { scenePage, clothingSentence, toggleChange, movePanel, removePanel, sceneOf, type Scene } from "../src/lib/scene.ts";

const CHARS = "Fumika: an adult manga artist, black ponytail, white shirt, black skirt\nSora: her editor, short silver hair, glasses";
const scene = (): Scene => ({
  id: "s1", name: "Studio evening", from: 1, to: 3, place: "her small manga studio", time: "evening", light: "warm desk lamp light",
  cast: [{ name: "Fumika", look: "an adult manga artist, black ponytail", items: [
    { id: "j", name: "Jacke", wording: "denim jacket", start: "on" },
    { id: "s", name: "Schal", wording: "patterned scarf", start: "on", frozen: "grey checkered scarf" },
    { id: "w", name: "Hemd", wording: "white shirt", start: "on" },
    { id: "c", name: "Mütze", wording: "red beanie", start: "off" },
  ] }],
  changes: [{ page: 2, panel: 0, char: "Fumika", item: "j", to: "off", where: "hangs over the chair" }],
});

test("pages outside the scene are untouched", () => {
  const r = scenePage("Fumika at her desk | Hi", 0, [scene()], CHARS);
  assert.deepEqual(r, { page: "Fumika at her desk | Hi", characters: CHARS });
});

test("before the change: setting + everything worn, frozen wording wins", () => {
  const r = scenePage("Fumika walks into the studio, full body | Home!", 1, [scene()], CHARS);
  assert.equal(r.page, "Fumika walks into the studio, full body. Setting: her small manga studio, evening, warm desk lamp light. " +
    "Fumika wears the denim jacket, the grey checkered scarf and the white shirt. | Home!");
  // the scene look replaces her description (no clothes in it), Sora keeps hers
  assert.equal(r.characters, "Fumika: an adult manga artist, black ponytail\nSora: her editor, short silver hair, glasses");
});

test("the panel of the change and the panels after it", () => {
  const r = scenePage("Fumika takes off her jacket\nFumika sits down at her desk", 2, [scene()], CHARS).page.split("\n");
  assert.ok(r[0].endsWith("Fumika takes off the denim jacket; the denim jacket hangs over the chair. Fumika still wears the grey checkered scarf and the white shirt."), r[0]);
  assert.ok(r[1].endsWith("Fumika wears the grey checkered scarf and the white shirt; the denim jacket hangs over the chair."), r[1]);
  const p3 = scenePage("Close-up of Fumika concentrating", 3, [scene()], CHARS).page;
  assert.ok(p3.endsWith("Fumika wears the grey checkered scarf and the white shirt; the denim jacket hangs over the chair."), p3);
});

test("only characters on the panel get a clothing sentence", () => {
  const r = scenePage("Sora reads the pages | Sora: Hm.", 1, [scene()], CHARS).page;
  assert.equal(r, "Sora reads the pages. Setting: her small manga studio, evening, warm desk lamp light. | Sora: Hm.");
});

test("a speaker counts as on the panel", () => {
  const r = scenePage("Close-up, panicking | Fumika: Seven pages?!", 1, [scene()], CHARS).page;
  assert.match(r, /Fumika wears the denim jacket/);
});

test("toggle: off, then on again; an item that starts off is put on", () => {
  const s = scene(), c = s.cast[0];
  toggleChange(s, c, "c", 3, 0);
  assert.equal(s.changes.at(-1)!.to, "on");
  assert.match(clothingSentence(s, c, 3, 0), /^Fumika puts on the red beanie\. Fumika still wears/);
  assert.match(clothingSentence(s, c, 3, 1), /wears the grey checkered scarf, the white shirt and the red beanie/);
  toggleChange(s, c, "j", 3, 1);   // jacket is off since page 2 -> putting it back on
  assert.equal(s.changes.at(-1)!.to, "on");
  toggleChange(s, c, "j", 3, 1);   // untick
  assert.equal(s.changes.filter((x) => x.item === "j").length, 1);
});

test("moving / deleting panels carries the changes", () => {
  const sc = [scene()];
  movePanel(sc, 2, 0, 1);
  assert.equal(sc[0].changes[0].panel, 1);
  sc[0].changes.push({ page: 2, panel: 2, char: "Fumika", item: "w", to: "off", where: "" });
  removePanel(sc, 2, 1);
  assert.deepEqual(sc[0].changes.map((x) => [x.item, x.panel]), [["w", 1]]);
  assert.equal(sceneOf(sc, 4), undefined);
});

test("nothing worn but something put aside", () => {
  const s = scene(); const c = s.cast[0];
  c.items = [c.items[0]];
  assert.equal(clothingSentence(s, c, 3, 0), "The denim jacket hangs over the chair.");
});
