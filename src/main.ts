import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";
import { t } from "./lib/i18n.svelte";
import { app } from "./lib/store.svelte";

// no browser context menu (Back / Reload / Inspect) in a desktop app; text fields keep cut / copy / paste.
// Ctrl + right click still opens it, for devtools.
document.addEventListener("contextmenu", (e) => {
  const el = e.target as HTMLElement;
  if (!e.ctrlKey && !el.closest("input, textarea, [contenteditable]")) e.preventDefault();
});

// a picture whose file is gone (deleted output, moved engine, old project) shows a placeholder instead of a broken icon;
// pages and versions can be drawn again from the inspector
document.addEventListener("error", (e) => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || img.dataset.missing) return;
  // engine pictures (comfyimg://) fail while ComfyUI starts or is stopped: wait for it instead of calling them missing
  if (img.src.startsWith("comfyimg:") || img.src.includes("comfyimg.localhost")) {
    if (!app.server.running) { img.dataset.retry = img.src; return; }
  }
  img.dataset.missing = "1";
  img.dataset.retry = img.src;
  const text = t("img.missing").replace(/&/g, "&amp;").replace(/</g, "&lt;");
  img.title = t("img.missingTip", { btn: t("insp.redraw") });
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360" viewBox="0 0 240 360"><rect x="4" y="4" width="232" height="352" rx="6" fill="#8881" stroke="#8888" stroke-width="2" stroke-dasharray="8 6"/><text x="120" y="184" text-anchor="middle" font-family="system-ui, sans-serif" font-size="15" fill="#888">${text}</text></svg>`);
}, true);
// a new picture in the same element clears the marks
document.addEventListener("load", (e) => {
  const img = e.target;
  if (img instanceof HTMLImageElement && !img.src.startsWith("data:")) { delete img.dataset.missing; delete img.dataset.retry; }
}, true);
// the engine came up: load the waiting pictures (and the "missing" ones once more) from their own address again
let wasRunning = false;
setInterval(() => {
  if (app.server.running && !wasRunning) {
    for (const img of document.querySelectorAll<HTMLImageElement>("img[data-retry]")) {
      const src = img.dataset.retry!;
      delete img.dataset.retry; delete img.dataset.missing;
      img.src = src + (src.includes("?") ? "&" : "?") + "r=" + Date.now();
    }
  }
  wasRunning = app.server.running;
}, 1500);

export default mount(App, { target: document.getElementById("app")! });
