---
name: Fumika
description: A manuscript board for turning a story into a finished comic book, locally.
colors:
  board: "#f6f7f8"
  sheet: "#ffffff"
  ink: "#151515"
  ink-2: "#3b3d40"
  ink-3: "#5c6066"
  nr: "#6fb3e8"
  nr-text: "#1f6aa8"
  nr-tint: "#c9dceb"
  nr-wash: "#e8f1f8"
  pencil: "#c7392c"
  pencil-wash: "#fbe9e7"
  ok: "#2f7d4f"
  rule: "#d5dde4"
typography:
  display:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 700
  title:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 700
  body:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  body-sm:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  sheet-label:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
  label:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.07em"
rounded:
  sheet: "0px"
  control: "5px"
  pill: "99px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "14px"
  lg: "20px"
  xl: "28px"
components:
  button:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  button-hover:
    backgroundColor: "{colors.nr-wash}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  button-quiet:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "8px 15px"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  rail-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  rail-item-active:
    backgroundColor: "{colors.nr-tint}"
    textColor: "{colors.ink}"
  chip-character:
    textColor: "{colors.nr-text}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  page-trim:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.sheet}"
  error-note:
    backgroundColor: "{colors.pencil-wash}"
    textColor: "{colors.pencil}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
---

# Design System: Fumika

## Overview

**Creative North Star: "The Manuscript Board"**

The app is the drawing desk. Every page of the book sits on a bright manuscript board inside its own trim frame, and everything that is tool rather than art is drawn in non-repro blue: trim corner marks, panel guides, selection, rules between regions, labels, queue positions. Ink black is reserved for type and for finished art; red pencil appears only where something went wrong. The chrome is deliberately quieter than the pages so a book of finished, inked sheets reads as the loudest thing on screen.

Density is that of a working desk, not a dashboard: a 232px rail, a sheet of page cells on an auto-fill grid, and a 312px inspector, all on the same board ground with hairline rules between them. Render state is drawn as manuscript marks rather than badges: an open page is an empty dashed trim, a waiting page carries a blue wash in its panel guides, a drawing page fills its panels with blue hatching, a finished page inks in. The world refuses the dark neutral chrome plus thumbnail grid plus inspector that every image tool ships, and it refuses anything that looks like ComfyUI.

The build landed one detail differently from the direction contract: red pencil shipped as #C7392C (5.2:1 on board) instead of the planned #E0483A, so error text stays legible. The shipped value is canonical.

**Key Characteristics:**
- Bright board ground, white sheets, ink for type and art only.
- Non-repro blue for every tool mark; a separate darker blue for any blue text.
- Red pencil exclusively for errors and rejections.
- Hairline 1px rules; dashed blue rules for structural seams and pending/empty states.
- One sans family (Libre Franklin), tabular numerals everywhere.
- Flat at rest; the only lift is a finished page shown alone in the reader.

## Colors

A near-white paper palette with one tool colour (non-repro blue), one ink, and one alarm colour.

### Primary
- **Non-Repro Blue** (nr): the colour of every tool mark. Trim corner marks, page trims of unfinished pages, dashed panel guides, the dashed seams under the top bar and above the rail foot, selection outlines, focus rings, table header rules. Lines and marks only, never text.
- **Blue-Pencil Text** (nr-text): the text form of non-repro blue (5.6:1 on board). Page codes and states under each cell, margin notes, uppercase labels, queue positions, the "Studio" half of the app mark, the caret, inline links, character chips.
- **Blue Tint** (nr-tint): active rail item fill, running-panel hatching, text selection, scrollbar thumb, dotted queue-row rules.
- **Blue Wash** (nr-wash): hover fill for buttons and rail items, waiting-panel fill, focus halo around fields, inline code chips.

### Secondary
- **Red Pencil** (pencil): errors and rejections only. The trim and panel guides of a failed page, its status label ("4 Unsinnstexte"), failed queue states, inspector error notes.
- **Red Pencil Wash** (pencil-wash): fill behind inspector error notes, never alone.

### Tertiary
- **Engine Green** (ok): the single status dot for "Engine bereit" at the rail foot. It does not appear anywhere else.

### Neutral
- **Manuscript Board** (board): the app ground behind rail, sheet and inspector alike.
- **Sheet White** (sheet): page trims, fields, default buttons, version thumbnails, code blocks.
- **Ink** (ink): primary text, the primary button, finished-page trims and inked panel boxes, the best-version frame, checkbox accent.
- **Ink 2** (ink-2): secondary text and form labels (10.6:1).
- **Ink 3** (ink-3): quiet text, placeholders, counts, engine detail lines (6.1:1).
- **Hairline Rule** (rule): pane dividers, field strokes, quiet button strokes, table row rules.

### Named Rules
**The Non-Repro Rule.** If a mark is tool rather than art, it is blue; if it is text, it uses the darker Blue-Pencil Text, never the line blue. The line blue on text fails contrast.

**The Red Pencil Rule.** Red appears only when something failed or was rejected. Never for emphasis, destructive buttons, or decoration.

**The Ink Is Earned Rule.** Ink on a page frame means finished. Unfinished pages never take an ink trim; the primary action is the only ink-filled control.

## Typography

**Display Font:** Libre Franklin (with system-ui, sans-serif), weights 400/500/600/700 via @fontsource
**Body Font:** Libre Franklin
**Label/Mono Font:** none distinct; code chips inherit Libre Franklin

**Character:** A single plain grotesque doing all the work: firm 700 titles, calm 400 body, 600 for every label and status. Tabular numerals are on globally so times, counts and VRAM figures never jitter.

### Hierarchy
- **Display** (700, 24px, -0.01em): the editable project title in the workspace top bar and the Setup page title.
- **Headline** (700, 22px): page titles of Queue and Library.
- **Title** (700, 17px; 16px for Setup sections; 18px reader title): inspector "Seite N", section heads.
- **Body** (400, 14px, 1.45): default UI text; long help copy capped at 60-68ch.
- **Body small** (400-600, 13px): buttons (600), tables, fields in the inspector, top-bar summary.
- **Sheet label** (600, 12px): page code and state under each cell; margin notes run at 11.5px 400.
- **Label** (600, 11px, 0.07em, uppercase, Blue-Pencil Text): field-group labels in the inspector and rail ("Panels", "Queue", "Buch", "Projekt") and table column headers.

### Named Rules
**The Label Is A Field Rule.** The uppercase blue label names a field group, list or table column directly beneath it. It never sits above a page title as a decorative kicker.

## Layout

A three-pane desk shell: rail (232px, 196px below 1180px) | content (fluid) | inspector (312px, 264px below 1180px), separated by 1px hairline rules, all on the board ground. The workspace top bar holds the project title, a one-line summary ("6 pages · 2 done · … · ≈ 3 min left") and actions on the right, closed by a dashed blue seam.

The sheet is a CSS auto-fill grid of page cells (min 128px, 116px below 1180px; gaps 22px rows / 24px columns, 18/14 below 1180px). That yields five columns at 1400x900 and three at 1000x700. Each cell is 3:4.7, with its trim inset 9px and a 47px foot for the code/state line and the margin note. The "+ Seite" cell follows the last page.

Spacing rhythm: 6-8px inside groups, 14px rail gutters, 20px pane padding, 28-32px around the sheet and page views; Setup and Library cap at 980px wide. Window minimum is 1000x700.

## Elevation & Depth

Flat. Depth is conveyed by paper on board (white sheet against #F6F7F8), by line weight and by line style (solid, dashed, dotted), not by shadow. Selection is a 2px blue outline offset 4px around the trim; focus is a 2px blue outline offset 2px, or for fields a blue border plus a 3px blue-wash halo.

### Shadow Vocabulary
- **Reader sheet** (`box-shadow: 0 6px 28px rgba(21, 21, 21, .12)`): only on a finished page shown alone in the reader, the one place a sheet is lifted off the desk.

### Named Rules
**The Paper Not Plastic Rule.** No shadows on chrome, cards, buttons or the page grid. A sheet earns lift only when it is being read.

## Shapes

Two corner languages. Paper is square: page trims, panel guides, version thumbnails and empty-state sheets have 0 radius, like cut paper. Controls are gently rounded (5px): buttons, fields, rail items, error notes. Character chips are full pills. Trim corner marks are 14px L-shapes in 1px blue at the top-left and bottom-right of each cell. Rules are 1px; inked panel boxes on finished pages are 2px ink; the best version is framed in 2px ink.

## Components

### Buttons
Plain and firm: a stroked label button, never a coloured pill.
- **Shape:** gently rounded (5px), 1px stroke, 8px 15px padding, 13px 600, 7px gap to a 14-15px Lucide icon.
- **Default:** sheet fill, ink stroke and text.
- **Primary:** ink fill, sheet text ("Buch rendern"). One per view.
- **Quiet:** hairline stroke, Ink 2 text (PDF, Neu zeichnen, row actions).
- **Hover / Focus:** default and quiet go to blue wash; primary deepens slightly; 0.15s ease-out. Focus is the global 2px blue outline. Disabled is 45% opacity.

### Chips
- **Style:** character names detected in the page script, 12px 600 Blue-Pencil Text, 1px blue stroke, pill radius, no fill.
- **State:** display only; no selected state.

### Inputs / Fields
- **Style:** sheet fill, 1px hairline stroke, 5px radius, 8px 10px padding, blue caret. Selects carry an inline blue chevron. Checkboxes take the ink accent.
- **Focus:** stroke turns line blue with a 3px blue-wash halo; no outline.
- **Inline title field:** the project title is a transparent 24px 700 input that shows a hairline only on hover.

### Navigation
- **Rail:** app mark ("MOSS Doujin" ink + "Studio" blue, 15px 700), then six section items with 17px Lucide icons at 1.75 stroke, 500 Ink 2. Hover is blue wash; active is blue tint with ink 600 text. A queue count sits right-aligned in blue 700. A "Projekt" label heads the project list. The foot holds Setup and the engine block behind a dashed blue seam: status dot (green when ready, hollow otherwise), VRAM line and the currently drawing job in 11.5px Ink 3.

### Tables
- **Style:** full width, 13px. Column headers use the uppercase blue label over a 1px line-blue rule; rows are separated by hairline rules; actions right-aligned as quiet buttons. Failed states in red pencil, cancelled struck through in Ink 3.

### Page Cell (signature)
The page as a manuscript sheet whose marks show its render state.
- **Open:** transparent dashed trim, dashed blue panel guides.
- **Waiting:** solid blue trim, panel guides washed blue, label "#N wartet".
- **Drawing:** panels fill one after another with 45-degree blue-tint hatching (2px / 7px) revealed by clip-path. The fill follows the real sampler steps from ComfyUI's websocket across all versions of the page; the label reads "v2 · 31/50" (version · step). Only before the first step arrives does it fall back to a time estimate labelled "≈ N %".
- **Done:** trim inks in from line blue to ink over 0.9s (cubic-bezier(.16, 1, .3, 1)), then stays ink; panel boxes 2px ink or the best version's image fills the trim. Label shows render time and version count.
- **Error:** trim, guides and status in red pencil.
- **Selected / Hover:** 2px blue outline offset 4px; hover darkens the trim stroke to Blue-Pencil Text.
- **Margin note:** under the code/state line, a blue 11.5px note of the characters on the page and the LoRA drawing it.
- Panel guide layouts follow the script, one line per panel, 1-5 panels. Reduced motion removes the ink animation and hatching transition.

### Inspector
Page header with title and a quiet redraw button; a "Panels" label, one-line help with an inline wash code chip, the script textarea, character chips, a red-pencil error note when present; a three-up version strip with the best framed in ink; the live queue list (blue position and state columns, dotted blue-tint rules, the running row in ink 600); and the book settings pinned to the bottom behind a dashed blue seam.

## Window Shell

- **Title bar:** the window has no OS decorations. A 38px bar on the board ground continues the rail (mark with the app icon in the rail column, current project or section in quiet text, three 46px window buttons at the right; close hovers in red pencil). The whole bar is a drag region; double-click maximizes.
- **Splash:** a 540x300 board card (always on top, no taskbar entry) shown while the UI boots (at least 1.6 s, at most 12 s): Fumika's pencil sketch inks in diagonally into the finished ink art on a white manuscript sheet with blue trim marks (`public/splash/sketch.webp` -> `ink.webp`, 1.6 s mask sweep; reduced motion shows the ink art directly), wordmark, tagline, status line over a dashed blue seam. Same tokens, language and theme as the app.
- **Icon:** Fumika in two drawings for two size ranges (`src-tauri/icons/make_icon_head.py`). From 48 px up (Explorer, macOS
  `.icns`, store logos): her drawn head on a paper-white rounded tile with an ink rim and a soft shadow, laid out in Apple's macOS
  grid (824 px body on 1024, radius 185) so the Mac build gets a proper icon. At 16 / 24 / 32 px (taskbar, title bar, tray): the
  pixel head below. The macOS menu bar later takes `tray-macTemplate(@2x).png` (black + alpha template image). The former
  manuscript-tile icon stays reproducible with `make_icon.py`. Tray icon: Fumika's head as hand-placed 16x16 pixel art (black hair, light-blue streak and eyes, white collar with the black ribbon) with a grey 1 px outline for dark taskbars, shipped at exact 2x (`src-tauri/icons/make_tray_head.py`); the former tile motif stays as an option (`make_tray_tile.py`). The title bar mark and the favicon use the same head
(`public/favicon.png` = `tray.png`, drawn pixelated); the former tile favicon is kept as `src-tauri/icons/favicon-tile.png`. The X sends the window to the tray (rendering continues); only Quit in the tray menu ends the app. No browser context menu outside text fields; WebView2 runs with `--lang=en-US`. The tray tooltip shows the drawing step.

## Dark Theme

The same board after hours, a lightbox desk: board #121416, sheet #1B1E21, ink #ECEDEE, non-repro blue #4F8FC4 for lines and #8EC3EE for blue text, red pencil #F07A6C. Follows the OS by default; Setup offers System / Light / Dark. Tokens are redefined on `:root` under `prefers-color-scheme: dark` (unless `data-theme="light"`) and under `data-theme="dark"`; components use only tokens (`--ink-hover`, `--lift`, `--chev` exist so no component hard-codes a colour).

## Plugins

Everything model-specific comes from a plugin (`src-tauri/resources/plugins/<id>/plugin.json`: models, ComfyUI node packs,
workflow templates, app areas). Setup shows one card per plugin (name, version, kind · model family, download size, licence);
the navigation shows only the areas of the switched-on plugins ("comic": Project, Read, Library, Templates; "trainer": Trainer;
Queue always). A plugin whose models carry a non-commercial licence asks for an explicit OK in a red-pencil box before it
switches on. At first start (no choice saved yet) the app opens on Setup.

## Colour Schemes

Two palettes named after the two mascots, each in light and dark (Setup → Colour scheme, `data-palette` on `:root`, saved with the other prefs). The names carry no content label:

- **Fumika** (default): the board above. Non-repro blue is the accent; Fumika, the mangaka mascot of the release (black ink hair with a light-blue streak), shares it.
- **Terra** (`data-palette="terra"`): after Terra, the 7err4 avatar girl (mascot of the plugins). The accent tokens (`--nr*`) take her red eyes (#E0505F lines, #B0202F text light / #FF8593 dark), the tint her pink inner ears (#F6CDD6), the dark board her black hoodie (#121116) and the rules a trace of her navy hair (#2C2A39). Because red is the accent here, the red pencil (`--pencil`, errors) turns amber (#B45309 light 4.6:1 / #F0A35C dark 9.0:1). The splash reads the same pref.

## Language

English is the primary UI language; German is an optional translation (Setup → Language). Strings live in `src/lib/i18n.svelte.ts`; missing keys fall back to English. Prompts, page scripts and job labels stay English data ("Page 4") and are localized only for display.

## Do's and Don'ts

### Do:
- **Do** draw every tool mark (trims, guides, seams, selection, focus) in line blue (nr) and every blue word in Blue-Pencil Text (nr-text).
- **Do** show render state through the page cell's own marks: dashed trim, blue wash, blue hatching, ink.
- **Do** label any estimated progress with "≈"; only show precise progress when the engine reports it.
- **Do** use dashed blue 1px seams for structural breaks inside a pane (under the top bar, above pinned groups, between Setup sections) and solid hairline rules between panes and rows.
- **Do** keep page trims and panel guides square (0 radius) and controls at 5px.
- **Do** keep one ink-filled primary button per view.

### Don't:
- **Don't** use red pencil for anything but errors and rejections.
- **Don't** set text in line blue (#6FB3E8); it fails contrast on the board.
- **Don't** give an unfinished page an ink trim.
- **Don't** add shadows to chrome, buttons or the page grid; the reader sheet is the only lifted surface.
- **Don't** move to dark neutral chrome or node-graph visuals; the app must not read as an AI dashboard or ComfyUI.
- **Don't** put an uppercase label above a page title as a kicker; labels name the field group beneath them.
