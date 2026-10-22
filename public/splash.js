// Splash: same language + theme as the app (prefs saved by src/lib/i18n.svelte.ts under the same origin).
(function () {
  var p = {};
  try { p = JSON.parse(localStorage.getItem("fumika-prefs") || "{}"); } catch (e) { /* defaults */ }
  if (p.theme === "light" || p.theme === "dark") document.documentElement.dataset.theme = p.theme;
  if (p.palette === "terra") document.documentElement.dataset.palette = p.palette;
  if (p.lang === "de") {
    document.documentElement.lang = "de";
    document.addEventListener("DOMContentLoaded", function () {
      document.getElementById("tag").textContent = "Ganze Manga-Seiten aus einer Geschichte.";
      document.getElementById("status").textContent = "Arbeitsfläche wird geöffnet …";
    });
  }
})();
