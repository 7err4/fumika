// Every language file has every English key, keeps the {placeholders} and the [one, other] pairs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../src/lib/i18n.svelte.ts", import.meta.url), "utf8");
const body = src.slice(src.indexOf("const en = {") + "const en = ".length, src.indexOf("} satisfies Record<string, Entry>;") + 1);
const en: Record<string, string | string[]> = new Function(`return (${body});`)();
const LANGS = ["fr", "it", "es", "es-419", "pt-BR", "ja", "ko", "zh-Hans", "zh-Hant"];
const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");

for (const lang of LANGS) {
  test(`${lang}: complete, same placeholders and plural pairs`, async () => {
    const d: Record<string, string | string[]> = (await import(`../src/lib/i18n/${lang}.ts`)).default;
    const missing = Object.keys(en).filter((k) => !(k in d));
    assert.deepEqual(missing, [], `${lang} misses ${missing.length} keys`);
    assert.deepEqual(Object.keys(d).filter((k) => !(k in en)), [], `${lang} has keys English does not have`);
    for (const [k, v] of Object.entries(en)) {
      const tr = d[k];
      assert.equal(Array.isArray(tr), Array.isArray(v), `${lang} ${k}: plural pair`);
      const pairs = Array.isArray(v) ? v.map((x, i) => [x, (tr as string[])[i]]) : [[v, tr as string]];
      for (const [a, b] of pairs) {
        assert.ok(typeof b === "string" && b.trim(), `${lang} ${k}: empty`);
        // a plural form may drop {n} (e.g. "one page"), the "other" form and plain strings keep all placeholders
        if (!Array.isArray(v) || a === v[1]) assert.equal(holes(b), holes(a), `${lang} ${k}: placeholders`);
      }
    }
  });
}
