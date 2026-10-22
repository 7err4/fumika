// CBZ export of the open chapter (cbz.rs writes the archive): the cover first, then the chosen version of every finished page,
// plus ComicInfo.xml so comic readers (Komga, Kavita, YACReader, Mihon ...) sort it into the series and know the reading direction.
import { invoke } from "@tauri-apps/api/core";
import { save as saveDialog } from "@tauri-apps/plugin-dialog";
import { app } from "./store.svelte";
import { prefs } from "./i18n.svelte";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** the chapter's pictures in reading order: its cover (if drawn) and the finished pages */
export const chapterImages = () => [...(app.cover?.best ? [app.cover.best] : []), ...app.pages.filter((p) => p.best).map((p) => p.best!)];

export function comicInfo(pages: number): string {
  const meta = app.seriesList.find((s) => s.id === app.seriesId);
  const n = (meta?.chapters.findIndex((c) => c.id === app.chapterId) ?? 0) + 1;
  const tags = [
    `<Title>${esc(app.chapterTitle)}</Title>`, `<Series>${esc(app.title)}</Series>`, `<Number>${n}</Number>`,
    meta ? `<Count>${meta.chapters.length}</Count>` : "", `<PageCount>${pages}</PageCount>`,
    `<LanguageISO>${prefs.lang.split("-")[0]}</LanguageISO>`, `<Manga>${app.direction === "rtl" ? "YesAndRightToLeft" : "No"}</Manga>`,
    `<Notes>AI-generated images (Fumika)</Notes>`,
    app.cover?.best ? `<Pages><Page Image="0" Type="FrontCover" /></Pages>` : "",
  ].filter(Boolean);
  return `<?xml version="1.0" encoding="utf-8"?>\n<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n  ${tags.join("\n  ")}\n</ComicInfo>\n`;
}

/** ask where, write the .cbz; returns the page count (0 = cancelled) */
export async function exportCbz(): Promise<number> {
  const pages = chapterImages();
  if (!pages.length) return 0;
  const name = `${app.title || "comic"} - ${app.chapterTitle || "1"}`.replace(/[\\/:*?"<>|]+/g, " ").trim();
  const dest = await saveDialog({ defaultPath: `${name}.cbz`, filters: [{ name: "Comic Book Archive", extensions: ["cbz"] }] });
  if (!dest) return 0;
  return invoke<number>("export_cbz", { dest, pages, comicInfo: comicInfo(pages.length) });
}
