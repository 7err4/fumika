// Story editor round trip: cards -> text -> cards must be lossless, text -> cards -> text must keep what the node reads.
// Run: node --test tests/   (Node >= 23 strips the types itself, no extra packages)
import { test } from "node:test";
import assert from "node:assert/strict";
import { charNames, parsePage, serialisePage, splitSpeaker, panelCast, type Panel } from "../src/lib/story.ts";

const CHARS = "Fumika: an adult manga artist\nSora: her editor\nCasual Fumika: Fumika in a hoodie\nnot a character line";
const N = charNames(CHARS);

test("character names like the node", () => {
  assert.deepEqual(N, ["Fumika", "Sora", "Casual Fumika"]);
});

test("speaker syntax", () => {
  assert.deepEqual(splitSpeaker("Fumika: Seven pages?!", N), { who: ["Fumika"], joined: false, text: "Seven pages?!" });
  assert.deepEqual(splitSpeaker("+fumika: By TOMORROW?!", N), { who: ["Fumika"], joined: true, text: "By TOMORROW?!" });
  assert.deepEqual(splitSpeaker("Fumika & Sora: DEADLINE!!", N), { who: ["Fumika", "Sora"], joined: false, text: "DEADLINE!!" });
  assert.deepEqual(splitSpeaker("Note: buy ink", N).who, []);
  assert.deepEqual(splitSpeaker("Time is 3:00", N).who, []);
});

const PAGE = [
  "Fumika grins at the viewer holding up a dip pen | #DEADLINE! | ##by Fumika",
  "Tokyo at night | >Tokyo, 2 a.m. | !BZZT | Nothing...",
  "Sora and Fumika in the studio | Fumika: Seven pages?! | +Fumika: By TOMORROW?! | Sora: You promised.",
  "Both shout | Fumika & Sora: DEADLINE!!",
  "Casual Fumika walks out | Note: this stays plain text",
].join("\n");

test("text -> cards -> text keeps the page", () => {
  assert.equal(serialisePage(parsePage(PAGE, N)), PAGE);
});

test("text -> cards reads the kinds and speakers", () => {
  const p = parsePage(PAGE, N);
  assert.equal(p.length, 5);
  assert.deepEqual(p[0].texts.map((t) => [t.kind, t.text]), [["title", "DEADLINE!"], ["subtitle", "by Fumika"]]);
  assert.deepEqual(p[1].texts.map((t) => t.kind), ["narration", "sfx", "speech"]);
  assert.deepEqual(p[2].texts.map((t) => [t.who, t.joined]), [[["Fumika"], false], [["Fumika"], true], [["Sora"], false]]);
  assert.deepEqual(p[3].texts[0].who, ["Fumika", "Sora"]);
  assert.deepEqual(p[4].texts[0], { kind: "speech", text: "Note: this stays plain text", who: [], joined: false });
});

test("old stories keep working and are normalised only in spacing / name case", () => {
  const old = "Fumika at her desk|Nothing...|  !BZZT\n\n  Close-up |  fumika: hi there  ";
  assert.equal(serialisePage(parsePage(old, N)), "Fumika at her desk | Nothing... | !BZZT\nClose-up | Fumika: hi there");
});

test("cards -> text -> cards is lossless", () => {
  const cards: Panel[] = [
    { what: "Sora hands Fumika the pages", texts: [
      { kind: "narration", text: "Next morning", who: [], joined: false },
      { kind: "speech", text: "Done?", who: ["Sora"], joined: false },
      { kind: "speech", text: "Done!", who: ["Fumika"], joined: false },
      { kind: "speech", text: "Mostly.", who: ["Fumika"], joined: true },
    ] },
    { what: "Close-up", texts: [{ kind: "sfx", text: "BAM", who: [], joined: false }, { kind: "speech", text: "...", who: [], joined: false }] },
    { what: "", texts: [{ kind: "speech", text: "Hooray", who: ["Fumika", "Sora"], joined: false }] },
    { what: "Cover", texts: [{ kind: "title", text: "THE END", who: [], joined: false }, { kind: "subtitle", text: "by Fumika", who: [], joined: false }] },
  ];
  assert.deepEqual(parsePage(serialisePage(cards), N), cards);
});

test("card fields cannot break the format", () => {
  const cards: Panel[] = [{ what: "A | B\nC", texts: [{ kind: "speech", text: "!not a sound", who: [], joined: false },
    { kind: "speech", text: "#not a title", who: ["Sora"], joined: false }, { kind: "speech", text: "  ", who: [], joined: false }] }];
  const text = serialisePage(cards);
  assert.equal(text, "A / B C | not a sound | Sora: not a title");
  const back = parsePage(text, N);
  assert.equal(back.length, 1);
  assert.deepEqual(back[0].texts.map((t) => t.kind), ["speech", "speech"]);
});

test("empty cards are dropped", () => {
  assert.equal(serialisePage([{ what: "", texts: [] }, { what: "A", texts: [] }, { what: " ", texts: [{ kind: "speech", text: "", who: [], joined: false }] }]), "A");
});

test("cast of a card: speakers first, then mentions, longest names win", () => {
  const p = parsePage("Casual Fumika waves at Sora | Sora: Morning!", N)[0];
  assert.deepEqual(panelCast(p, N), ["Sora", "Casual Fumika"]);
});

test("panel moods live in the panel text and come off again", async () => {
  const { moodOf, setMood, plainWhat } = await import("../src/lib/story.ts");
  const d = setMood("Fumika on a stage", "dream");
  assert.equal(moodOf(d), "dream");
  assert.ok(d.includes("cloud-shaped panel border") && d.endsWith(": Fumika on a stage"));
  assert.equal(plainWhat(d), "Fumika on a stage");
  const f = setMood(d, "flashback");
  assert.equal(f, "Flashback in muted sepia colours: Fumika on a stage");
  assert.equal(setMood(f, "normal"), "Fumika on a stage");
  assert.equal(moodOf("Fumika at her desk"), "normal");
  // survives the round trip through the page text
  const back = parsePage(serialisePage([{ what: f, texts: [] }]), N)[0].what;
  assert.equal(moodOf(back), "flashback");
});
