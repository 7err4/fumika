// Scenes: consecutive pages with a shared place / time / light and a cast. Per character an outfit as an item list; per panel
// the user ticks what changes ("takes off: denim jacket" -> "hangs over the chair"). Before a page is drawn, the app writes the
// setting and the current clothing state into every panel description (tested 21 Oct: research_moss/bubble_scene_test.py scene,
// correct in all variants). The stored story text is never changed by this, so the node / MCP format stays the same.
// Pure functions: tests/scene.test.ts runs them with `node --test`.
import { charNames, parsePage, panelCast, serialisePage } from "./story.ts";

/** one piece of clothing. name = label in the app (any language), wording = English words for the prompt,
 *  frozen = wording read from the first drawn page (freeze the look) - wins over wording while set */
export interface Item { id: string; name: string; wording: string; start: "on" | "off"; frozen?: string }
/** look = the character's description for this scene without clothes ("" = the one from the character list) */
export interface CastEntry { name: string; look: string; items: Item[] }
export interface Change { page: number; panel: number; char: string; item: string; to: "on" | "off"; where: string }
export interface Scene { id: string; name: string; from: number; to: number; place: string; time: string; light: string;
  cast: CastEntry[]; changes: Change[]; /** page the look was frozen from */ frozenFrom?: number }

export const sceneOf = (scenes: Scene[], page: number) => scenes.find((s) => s.from <= page && page <= s.to);
export const words = (it: Item) => (it.frozen || it.wording || it.name).trim();
const before = (a: { page: number; panel: number }, b: { page: number; panel: number }) => a.page < b.page || (a.page === b.page && a.panel < b.panel);

function list(xs: string[]): string {
  return xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1];
}

/** state of one character's items right after panel (page, panel): on / off + where an item that is off ended up */
export function itemState(s: Scene, c: CastEntry, page: number, panel: number): Map<string, { on: boolean; where: string }> {
  const st = new Map(c.items.map((it) => [it.id, { on: it.start === "on", where: "" }]));
  const at = { page, panel };
  for (const ch of [...s.changes].sort((a, b) => a.page - b.page || a.panel - b.panel)) {
    if (ch.char !== c.name || !st.has(ch.item) || before(at, ch)) continue;
    st.set(ch.item, { on: ch.to === "on", where: ch.to === "off" ? ch.where.trim() : "" });
  }
  return st;
}

/** the clothing sentence of one character on one panel, e.g. "Fumika takes off the denim jacket; the denim jacket hangs over
 *  the chair. Fumika still wears the patterned scarf and the white shirt." */
export function clothingSentence(s: Scene, c: CastEntry, page: number, panel: number): string {
  if (!c.items.length) return "";
  const st = itemState(s, c, page, panel);
  const byId = new Map(c.items.map((it) => [it.id, it]));
  const now = s.changes.filter((ch) => ch.char === c.name && ch.page === page && ch.panel === panel && byId.has(ch.item));
  const out: string[] = [];
  for (const ch of now) {
    const w = words(byId.get(ch.item)!);
    out.push(ch.to === "off" ? `${c.name} takes off the ${w}` + (ch.where.trim() ? `; the ${w} ${ch.where.trim()}` : "") : `${c.name} puts on the ${w}`);
  }
  const changed = new Set(now.map((ch) => ch.item));
  const worn = c.items.filter((it) => st.get(it.id)!.on && !changed.has(it.id)).map((it) => "the " + words(it));
  const away = c.items.filter((it) => !st.get(it.id)!.on && st.get(it.id)!.where && !changed.has(it.id)).map((it) => `the ${words(it)} ${st.get(it.id)!.where}`);
  if (worn.length) out.push(`${c.name} ${now.length ? "still wears" : "wears"} ${list(worn)}` + (away.length ? "; " + list(away) : ""));
  else if (away.length) out.push(list(away).replace(/^t/, "T"));
  return out.map((x) => x.replace(/^./, (m) => m.toUpperCase()) + ".").join(" ");
}

export function settingSentence(s: Scene): string {
  const parts = [s.place, s.time, s.light].map((x) => x.trim()).filter(Boolean);
  return parts.length ? `Setting: ${parts.join(", ")}.` : "";
}

/** what the engine gets for one page: the page text with setting + clothing state in every panel, and the character list
 *  with the scene looks. Pages outside a scene come back unchanged. */
export function scenePage(text: string, page: number, scenes: Scene[], characters: string): { page: string; characters: string } {
  const s = sceneOf(scenes, page);
  if (!s) return { page: text, characters };
  const names = charNames(characters);
  const panels = parsePage(text, names).map((p, k) => {
    const cast = panelCast(p, names);
    const add = [settingSentence(s), ...s.cast.filter((c) => cast.includes(c.name)).map((c) => clothingSentence(s, c, page, k))].filter(Boolean);
    return add.length ? { ...p, what: [p.what.replace(/[\s.]+$/, "") + (p.what.trim() ? "." : ""), ...add].join(" ").trim() } : p;
  });
  const looks = new Map(s.cast.filter((c) => c.look.trim()).map((c) => [c.name, c.look.trim()]));
  const chars = characters.split("\n").map((l) => {
    const i = l.indexOf(":"), n = i < 0 ? "" : l.slice(0, i).trim();
    return looks.has(n) ? `${n}: ${looks.get(n)}` : l;
  }).join("\n");
  return { page: serialisePage(panels), characters: chars };
}

// the editor moved / deleted a panel: the ticked changes move with it
export function movePanel(scenes: Scene[], page: number, i: number, j: number) {
  for (const ch of sceneOf(scenes, page)?.changes ?? []) {
    if (ch.page !== page) continue;
    if (ch.panel === i) ch.panel = j; else if (ch.panel === j) ch.panel = i;
  }
}
export function removePanel(scenes: Scene[], page: number, i: number) {
  const s = sceneOf(scenes, page);
  if (!s) return;
  s.changes = s.changes.filter((ch) => !(ch.page === page && ch.panel === i));
  for (const ch of s.changes) if (ch.page === page && ch.panel > i) ch.panel--;
}

/** tick / untick a change of one item on one panel (only one change per item and panel) */
export function toggleChange(s: Scene, c: CastEntry, item: string, page: number, panel: number, where = "") {
  const k = s.changes.findIndex((ch) => ch.char === c.name && ch.item === item && ch.page === page && ch.panel === panel);
  if (k >= 0) { s.changes.splice(k, 1); return; }
  const prev = itemState(s, c, page, panel).get(item);
  s.changes.push({ page, panel, char: c.name, item, to: prev?.on ? "off" : "on", where });
}

export const newId = () => Math.random().toString(36).slice(2, 10);
