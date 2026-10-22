// Page text <-> panel cards for the story editor. The story text stays the storage format (MOSS Doujin node, MCP); this module
// reads it the same way as the node's story.py (parse_page / split_speaker) and writes it back, so both views stay in sync.
// Pure functions without Svelte or Tauri imports: tests/story.test.ts runs them with `node --test`.

export type Kind = "speech" | "sfx" | "narration" | "title" | "subtitle";
export const KINDS: Kind[] = ["speech", "sfx", "narration", "title", "subtitle"];
/** one text on a panel. who: speakers of a speech bubble (two or more = said together); joined: hangs under the speaker's previous bubble */
export interface TextItem { kind: Kind; text: string; who: string[]; joined: boolean }
export interface Panel { what: string; texts: TextItem[] }
/** the node's layouts go up to five panels */
export const MAX_PANELS = 5;

const PREFIX: Record<Exclude<Kind, "speech">, string> = { sfx: "!", narration: ">", title: "#", subtitle: "##" };

/** names of the character list ("Name: description" per line, both parts needed - same rule as the node) */
export function charNames(characters: string): string[] {
  return characters.split("\n").map((l) => {
    const i = l.indexOf(":");
    return i < 0 || !l.slice(0, i).trim() || !l.slice(i + 1).trim() ? "" : l.slice(0, i).trim();
  }).filter(Boolean);
}

/** '+Fumika & Sora: text' -> speakers, joined, text. Only names from the list count, so "Note: ..." stays plain text. */
export function splitSpeaker(t: string, names: string[]): { who: string[]; joined: boolean; text: string } {
  const m = /^(\+)?\s*([^:\n]{1,80}?)\s*:\s*([\s\S]+)$/.exec(t);
  if (!m) return { who: [], joined: false, text: t };
  const low = new Map(names.map((n) => [n.toLowerCase(), n]));
  const who = m[2].split("&").map((w) => low.get(w.trim().toLowerCase()));
  if (!who.length || who.some((w) => w === undefined)) return { who: [], joined: false, text: t };
  return { who: [...new Set(who as string[])], joined: !!m[1], text: m[3].trim() };
}

export function parseItem(raw: string, names: string[]): TextItem {
  const t = raw.trim();
  const kind: Kind = t.startsWith("!") ? "sfx" : t.startsWith("##") ? "subtitle" : t.startsWith("#") ? "title" : t.startsWith(">") ? "narration" : "speech";
  if (kind === "speech") { const s = splitSpeaker(t, names); return { kind, ...s }; }
  const text = kind === "narration" ? t.slice(1).trim() : t.replace(/^[!#]+/, "").trim();
  return { kind, text, who: [], joined: false };
}

/** one page block (one line per panel: what happens | text | text) -> cards */
export function parsePage(text: string, names: string[]): Panel[] {
  return text.split("\n").filter((l) => l.trim()).map((l) => {
    const [what, ...rest] = l.split("|").map((p) => p.trim());
    return { what, texts: rest.filter(Boolean).map((r) => parseItem(r, names)) };
  });
}

/** text typed into a card field: no line breaks and no "|" (they would split panels / texts) */
export const clean = (s: string) => s.replace(/[\r\n]+/g, " ").replace(/\|/g, "/").trim();

export function itemText(it: TextItem): string {
  const text = clean(it.text);
  if (it.kind !== "speech") return PREFIX[it.kind] + text;
  // a speech bubble whose own text starts like a marker would turn into another kind on the next read
  const safe = text.replace(/^[!#>+]+\s*/, "");
  if (!it.who.length) return safe;
  return (it.joined && it.who.length === 1 ? "+" : "") + it.who.join(" & ") + ": " + safe;
}

/** cards -> page block. Cards without any content are dropped (an empty line is no panel for the node). */
export function serialisePage(panels: Panel[]): string {
  return panels.map((p) => [clean(p.what), ...p.texts.filter((t) => clean(t.text)).map(itemText)].join(" | "))
    .filter((l) => l.replace(/[\s|]/g, "")).join("\n");
}

// panel kinds marked in "what happens" (tested 22 Oct, research_moss/scene_mark_test.py): a daydream by its cloud-shaped border
// 3/3 with the page style kept; a flashback by sepia in that panel 3/3 (black gutters were ignored 0/3)
export type Mood = "normal" | "dream" | "flashback";
export const MOODS: Mood[] = ["normal", "dream", "flashback"];
const MOOD_TEXT: Record<Exclude<Mood, "normal">, string> = {
  dream: "A daydream, drawn inside a cloud-shaped panel border with a wavy edge (only the border shape marks it as a dream), same colours and art style as the other panels: ",
  flashback: "Flashback in muted sepia colours: ",
};
export function moodOf(what: string): Mood {
  return what.startsWith(MOOD_TEXT.dream.trim()) ? "dream" : what.startsWith(MOOD_TEXT.flashback.trim()) ? "flashback" : "normal";
}
export function setMood(what: string, m: Mood): string {
  const cur = moodOf(what);
  const rest = cur === "normal" ? what : what.slice(MOOD_TEXT[cur].trim().length).trim();
  return m === "normal" ? rest : MOOD_TEXT[m] + rest;
}
/** "what happens" without the mood wording (what the card shows in its text field) */
export const plainWhat = (what: string) => setMood(what, "normal");

/** characters of a card: speakers plus names mentioned in "what happens", in the order the node would use them */
export function panelCast(p: Panel, names: string[]): string[] {
  const esc = (n: string) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const hits: [number, string][] = [];
  let what = p.what;
  for (const n of [...names].sort((a, b) => b.length - a.length)) {   // longest first: "Casual Fumika" before "Fumika"
    const re = new RegExp(`(?<![\\w@])\\b${esc(n)}\\b`, "g");
    what = what.replace(re, (m, off: number) => { hits.push([off, n]); return "@".repeat(m.length); });
  }
  const mentioned = hits.sort((a, b) => a[0] - b[0]).map((h) => h[1]);
  return [...new Set([...p.texts.flatMap((t) => t.who), ...mentioned])];
}
