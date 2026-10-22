// Before a release build: remove Python caches from the bundled plugins so they never end up in the installer.
import { readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src-tauri/resources/plugins/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
let n = 0;
function walk(d) {
  for (const e of readdirSync(d)) {
    const p = join(d, e);
    if (!statSync(p).isDirectory()) { if (e.endsWith(".pyc")) { rmSync(p); n++; } continue; }
    if (e === "__pycache__" || e === ".pytest_cache") { rmSync(p, { recursive: true, force: true }); n++; continue; }
    walk(p);
  }
}
walk(decodeURIComponent(root));
console.log(`clean-resources: removed ${n} cache folder(s) / file(s)`);
