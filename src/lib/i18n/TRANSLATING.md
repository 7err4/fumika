# Translating Fumika

The English dictionary (`const en = { … }` in `../i18n.svelte.ts`) is the source. German (`const de`) is a finished
translation you can use to understand the meaning of short labels. Each language file here exports a
`Partial<Record<Key, Entry>>`; a missing key falls back to English.

Rules:
- Translate every key of `en`, same key names, same order. Keep the file's header lines and the `export default d;`.
- Entries are either a string or a pair `[one, other]` (singular / plural picked by `n === 1`). Keep pairs as pairs; languages
  without plural forms (ja, ko, zh) repeat the same text in both slots.
- Keep every `{placeholder}` exactly (`{n}`, `{name}`, `{size}` …), but move it where the grammar needs it.
- Keep product, model and file names untranslated: Fumika, Sora, Terra, ComfyUI, MOSS-Image, Anima, SDXL, Illustrious, Pony,
  Kromoss, CharRef, LoRA, LyCORIS, Qwen, Real-ESRGAN, SeedVR2, BiRefNet, WD tagger, MCP, GPU, VRAM, CFG, JSON, PDF, CBZ, sampler /
  scheduler names, file names and paths, `Choose file` style button labels are translated normally.
- Technical terms that users see in the official ComfyUI / A1111 localisations of the language may stay English (e.g. "Seed",
  "Sampler", "Prompt" are common in Japanese UIs as シード / サンプラー / プロンプト - use the usual local form).
- Tone: friendly and short like the English. Address the user as: fr "vous", it "tu", es / es-419 "tú", pt-BR "você",
  ja polite (です・ます) but concise UI style, ko polite UI style (합니다/해요 where natural), zh neutral.
- es = Spain Spanish, es-419 = Latin American Spanish (e.g. "computadora" not "ordenador", "archivo", "descargar").
  zh-Hans = Simplified (mainland), zh-Hant = Traditional (Taiwan wording, e.g. 檔案, 資料夾, 影像).
- Manga / comic vocabulary: use what the local manga community uses (ja: コマ for panel, 吹き出し for speech bubble; ko: 컷, 말풍선;
  zh: 分镜/格 – pick one and stay consistent, 对话框 for speech bubble).
- Escape quotes properly for a TypeScript string literal; keep `\n` sequences.
