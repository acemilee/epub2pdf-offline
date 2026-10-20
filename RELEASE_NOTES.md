# EPUB2PDF v1.1.2

Reading-experience release. The PDF now adopts the book's own trim size instead
of always printing on A4, and the GUI gains an explicit start step with page-size
and font-size choices.

## Breaking change

- **Default page size is no longer A4.** With no options, the page ratio is
  derived from the cover and the page height defaults to 9.25in; A4 is only a
  fallback for books without a usable cover. Choose `--page-size A4` (CLI) or
  **页面尺寸: A4** (GUI) to reproduce the v1.1.1 geometry exactly.

## Highlights

- **Trim size from the cover**: the cover's aspect ratio is read without any new
  runtime dependency (PNG/JPEG/GIF/WebP/BMP/SVG headers) and used to size the
  page. Covers are printed full-bleed like a real book; invalid ratios
  (banners, screenshots outside 0.58–0.86) fall back to A4 with a warning.
- **Typography follows the page**: body font size targets 40 characters per
  line (clamped to 9–13 pt), margins are 11.5% of the width, top 8% and bottom
  9% of the height, and CJK books use 1.55 line-height (Latin 1.40). The
  generated TOC page and its clickable rows scale with the same metrics.
- **Explicit page sizes**: `--page-size A4|Letter|B5|6x9|7x10` and
  `--page-height-pt` (auto mode height, default 666 pt).
- **Font scale**: `--font-scale auto|compact|normal|loose` and the matching GUI
  selector (compact −8%, loose +10%).
- **GUI starts on demand**: dropping files now queues them as 等待开始; choose
  page size and font size, then press **开始转换**. Options persist between
  launches and are locked while a conversion is running; pending rows can be
  removed before starting.
- **More EPUBs convert**: books whose package manifest points at a missing
  navigation file (e.g. `toc01.xhtml` while the archive stores `toc01.html`,
  common in InDesign exports) are repaired on a temporary copy instead of
  failing, and TOC hrefs are matched extension-insensitively.

## Compatibility

- `--page-size A4` output matches v1.1.1 (595.28 × 841.89 pt, 18/16/20/16 mm
  margins, 11 pt body).
- Auto-mode page counts differ from v1.1.1 because the page is narrower; this is
  expected. Text size is still ultimately constrained by the EPUB's own CSS.
- The EPUB format does not store an absolute trim size, so 9.25in height is a
  deliberate default; adjust it with `--page-height-pt`.

# EPUB2PDF v1.1.1

Bug-fix release. EPUB stylesheets that declare their own page box no longer
erase the converter's A4 margins.

## Fixes

- **Print margins are authoritative again**: InDesign-style EPUB exports ship
  `@page { margin: 0 }` for readers that draw their own margins. Those rules
  used to be inlined after the print stylesheet and won the cascade, so body
  text ran to the paper edge (reported for *Systematic Trading*: 193 of 197
  body pages had a left margin under 10 pt). The converter now strips every
  `@page` at-rule from EPUB CSS — including inline `<style>` blocks and nested
  margin boxes — and re-declares its A4 page box last as a guard. Both the CDP
  and the CLI rendering paths are covered.
- **Known limitation removed**: the "body text may touch the page edge for
  EPUBs with a custom `@page` rule" note no longer applies.

## Compatibility

- Books whose EPUB CSS did not declare `@page` render exactly as before.
- Books that did declare it now paginate with normal margins, so their page
  counts may differ from v1.1.0 output; bookmarks, generated TOC page numbers
  and internal links are recomputed from the new pagination.
- Text size is still determined by the EPUB's own CSS (only the root font size
  is set by the converter); this release does not normalise small fonts.

# EPUB2PDF v1.1.0

Reading-experience release. Every generated PDF now starts with a real,
page-numbered table of contents, and cover formats are detected from the image
content instead of the file extension.

## Highlights

- **Generated table of contents**: a printable TOC page is inserted after the
  cover. Rows show dotted leaders and the final PDF page number, and each row is
  clickable. On the 7-volume, 416-chapter reference book this produced 12 TOC
  pages with ~410 rows whose numbers matched the body pages.
- **Bookmarks from one source**: `--outline-source chromium` (default) keeps the
  full `h1`–`h6` nesting copied from Chromium's outline (708 bookmarks, 5 levels
  on the reference book). `--outline-source ncx` builds bookmarks from the EPUB
  navigation document instead (410 bookmarks, 3 levels on the same book).
- **Cover format sniffing**: covers are recognised by magic bytes (PNG, JPEG,
  GIF, WebP, BMP, SVG, AVIF, ICO) rather than by extension, so SVG/AVIF covers
  are no longer blank. TIFF covers are skipped with a warning because Edge
  cannot render them.
- **Nested EPUB navigation is preserved**: the parser now walks nested
  `(Section, [Link, …])` tuples inside a volume, so the generated TOC lists the
  chapters inside each volume instead of only the volume headings.
- **GUI**: a new **打开输出目录** toolbar button opens the current output folder
  (it reports when the folder does not exist yet).
- **Faster large-book assembly**: page text used to be extracted with pypdf's
  pure-Python parser (about 4 minutes on the reference book). The assembler now
  uses PyMuPDF for text extraction when available (pypdf stays as a fallback),
  cutting assembly from ~270 s to ~23 s and whole-book conversion to under a
  minute on the same machine.
- **Cover page refinement**: generated cover pages use `object-fit: contain`
  (scaled to fit, never cropped).

## Compatibility

- Windows 10/11 with Microsoft Edge installed.
- Python 3.11+ when running from source.

## Known limitations

- Generated TOC rows come from the EPUB navigation entries that resolve to a
  rendered chapter; books whose navigation only lists volumes will list only
  volumes.
- TIFF covers are skipped.
- NCX bookmarks are flatter than Chromium bookmarks on books with deep heading
  structures.
- Fixed-layout EPUBs (comics, magazines) are still rendered reflowably.
- DRM-protected EPUBs are not supported.

## Release Assets

- `EpubToPdf-v1.1.0-windows-x64.zip`: Windows app package. Extract the archive
  and run `EpubToPdf.exe`.
- Source archive generated from the `v1.1.0` Git tag.

---

# EPUB2PDF v1.0.1

Reading-experience and reliability release. Existing v1.0 users should upgrade:
generated PDFs now keep nested bookmarks, keep embedded webfonts, and no longer
show underlined table-of-contents links.

## Highlights

- **Native-looking table of contents**: EPUB stylesheet rules that underlined
  links (common in the EPUB's own TOC page) are overridden when the TOC page is
  rendered, so generated PDFs no longer show blue underlined entries. The
  original EPUB file is not modified.
- **Nested PDF bookmarks**: bookmarks are generated by Chromium itself
  (`Page.printToPDF` with `generateDocumentOutline`), following the document's
  `h1`–`h6` hierarchy. A 400-chapter book produces ~700 bookmarks across 5
  levels instead of the previous flat, mostly-missing list.
- **Faster large-book conversion**: the anchor-based fallback re-reads every
  page once instead of three times; the same 400-chapter book dropped from
  ~296 s to ~63 s.
- **Better font embedding**: all glyphs used anywhere in the book are embedded
  per font (previously only the first page that used a font was captured, so
  later pages could lose characters), and EPUB-embedded webfonts are now
  registered with the browser and embedded too.
- **PostScript font-name aliases** (`ArialMT`, `TimesNewRomanPSMT`, …) are
  resolved to the installed Windows fonts, so those fonts are embedded instead
  of being reported as missing.
- **Cover pages are no longer cropped**: the cover is scaled down
  proportionally and centred on a white page.
- **Parser fix**: chapter titles are taken from the first `h1`–`h6` heading in
  the document (previously only `h1`/`h2` were considered, so many chapters fell
  back to file names in the UI/logs).
- **Robustness**: cancelling now interrupts the browser instead of waiting for
  the current stage; unexpected errors produce a friendly message (`--debug`
  shows the traceback); conversion prints a per-stage timing summary;
  `@charset` rules are stripped when stylesheets are inlined.

## Compatibility

- Windows 10/11 with Microsoft Edge installed.
- Python 3.11+ when running from source.
- If Edge's DevTools endpoint is unavailable, conversion falls back to the
  classic `--print-to-pdf` CLI; that path still produces a flat
  chapter-level outline, plus a warning that the nested outline is unavailable.

## Known limitations

- Fixed-layout EPUBs (comics, magazines) are still rendered reflowably.
- The EPUB's own navigation page is kept as a content page; it is not
  regenerated.
- DRM-protected EPUBs are not supported.
- PDF outline entries come from rendered headings only; the EPUB NCX tree is
  not mapped one-to-one.

## Release Assets

- `EpubToPdf-v1.0.1-windows-x64.zip`: Windows app package. Extract the archive
  and run `EpubToPdf.exe`.
- Source archive generated from the `v1.0.1` Git tag.

---

# EPUB2PDF v1.0

Initial public release.

## Highlights

- Windows GUI with drag-and-drop EPUB conversion.
- CLI conversion mode for one-off or scripted usage.
- Local Microsoft Edge headless rendering.
- Cover page extraction and PDF insertion.
- PDF bookmarks with corrected target pages.
- CJK/Latin font embedding repair pass for viewer portability.
- Print CSS normalization for Chinese text, code blocks and pagination.

## Release Assets

- `EpubToPdf-v1.0-windows-x64.zip`: Windows app package. Extract the archive
  and run `EpubToPdf.exe`.
- Source archive generated from the `v1.0` Git tag.

## Notes

- Microsoft Edge must be installed on the target Windows machine.
- DRM-protected EPUB files are not supported.
- Public release packages do not include sample books or generated PDFs.
