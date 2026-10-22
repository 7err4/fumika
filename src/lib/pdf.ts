// Export the finished pages of the current project as one PDF (page size 1024x1536 px, the render size).
// The PDF is marked as AI-generated (EU AI Act Art. 50(2)) like the rendered PNGs: XMP with the IPTC digital source type
// trainedAlgorithmicMedia plus the document properties.
import { jsPDF } from "jspdf";
import { getVersion } from "@tauri-apps/api/app";
import { app } from "./store.svelte";

const SOURCE_TYPE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia";
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** complete XMP packet for jsPDF's addMetadata(…, true) */
export function aiXmp(tool: string, title: string): string {
  return `<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">`
    + `<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" xmlns:dc="http://purl.org/dc/elements/1.1/" `
    + `xmlns:xmp="http://ns.adobe.com/xap/1.0/" Iptc4xmpExt:DigitalSourceType="${SOURCE_TYPE}" xmp:CreatorTool="${esc(tool)}">`
    + `<dc:title><rdf:Alt><rdf:li xml:lang="x-default">${esc(title)}</rdf:li></rdf:Alt></dc:title>`
    + `<dc:description><rdf:Alt><rdf:li xml:lang="x-default">AI-generated images (${esc(tool)})</rdf:li></rdf:Alt></dc:description>`
    + `</rdf:Description></rdf:RDF></x:xmpmeta>`;
}

export async function exportPdf() {
  const done = [...(app.cover?.best ? [app.cover] : []), ...app.pages.filter((p) => p.best)];   // the chapter cover first
  if (!done.length) return;
  const tool = `Fumika ${await getVersion().catch(() => "")}`.trim(), title = [app.title || "doujin", app.chapterTitle].filter(Boolean).join(" - ");
  const pdf = new jsPDF({ unit: "px", format: [1024, 1536], hotfixes: ["px_scaling"] });
  pdf.setDocumentProperties({ title, creator: tool, subject: `AI-generated images (${tool})`, keywords: "AI-generated, trainedAlgorithmicMedia" });
  pdf.addMetadata(aiXmp(tool, title), true);
  for (let i = 0; i < done.length; i++) {
    const blob = await (await fetch(done[i].best!)).blob();
    const url = await new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(r.result as string); r.readAsDataURL(blob); });
    if (i) pdf.addPage([1024, 1536]);
    pdf.addImage(url, "PNG", 0, 0, 1024, 1536);
  }
  pdf.save(title + ".pdf");
}
