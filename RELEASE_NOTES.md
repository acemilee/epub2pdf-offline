# EPUB2PDF v1.1.6

Reading-feel release: continuation pages now carry a quiet running head (book or
chapter title), the last missing piece of "typeset book" furniture for the body
pages.

## Added

- **Running headers.** A small grey running head is stamped in the top margin of
  continuation pages, using the chapter title from the same anchors as the
  bookmarks (falling back to the book title). Chapter-opening pages already show
  their title in large type, so they are left clean; fixed-layout and scanned
  pages whose content reaches the top edge are skipped automatically. Disable
  with `--no-running-headers` or `running_headers=False`.

## Verification

- Unit + e2e suite green (real Edge). New fixture `longchapter.epub` (one
  multi-page chapter) asserts that continuation pages carry the head, the
  chapter opener and generated TOC page do not, and `--no-running-headers`
  removes it everywhere. Unit tests cover book-title fallback, per-page chapter
  labels and CJK titles.
- Real books: Systematic Trading (330 pages) has running heads on 297 pages; the
  33 bare pages are chapter openers. `Advances in Financial Machine Learning`
  (fixed-layout scan) gets no heads because its content reaches the page edge.

# EPUB2PDF v1.1.5

Reading-feel release: body pages now carry page numbers, sparse bookmarks are
topped up from chapter anchors, and the PDF declares its language the way a
native publication does.

## Added

- **Page numbers.** A centered number is drawn in the bottom margin of every
  page (the cover stays clean), using the physical page index so it matches the
  generated table of contents and bookmark destinations. Disable with
  `--no-page-numbers` or `page_numbers=False`.
- **Bookmark top-up for books without real headings.** EPUBs that fake headings
  with `<p class="PartStart">` used to produce only one or two PDF bookmarks.
  When the Chromium outline is suspiciously sparse, chapter anchors now add flat
  chapter-level bookmarks (e.g. Advances in Financial Machine Learning went from
  2 to 6 entries where the source has 7 spine chunks).
- **Document language metadata.** The PDF catalog now carries `/Lang` from the
  EPUB's `dc:language`, and `/ViewerPreferences /DisplayDocTitle` asks viewers to
  title the window with the book name instead of the file name.

## Verification

- Unit + e2e suite green (real Edge); new fixture `partialheads.epub` covers the
  sparse-outline path; new e2e tests assert footer numbers equal the page index,
  that `--no-page-numbers` removes them, and that the sparse outline is topped up.
- Real books: Systematic Trading (330 pages, auto 471.3×666pt) shows `2…330` in
  the footer and keeps its 305 nested bookmarks; Advances keeps all 266 pages and
  now exposes 6 chapter bookmarks instead of 2. `basic.epub` output verifies
  `/Lang en` and `DisplayDocTitle true` survive the font-embedding pass.

# EPUB2PDF v1.1.4

Reading-quality release: the generated TOC is now completely rule-free, undersized
EPUB fonts are lifted to a readable floor, and fixed-pixel EPUB layouts are clamped
to the printable column.

## Changed

- **No more rules on the table-of-contents page.** v1.1.3 only moved the dotted
  leader; the rule itself still looked like an underline in many viewers. The TOC
  row is now a plain flex row: title (`flex:1`, ellipsis) + right-aligned page
  number, with no decorative strokes at all.
- **Font-size normalization.** Any `font-size` in the EPUB CSS (stylesheets and
  inline `<style>` blocks) that resolves below **9pt** is rewritten to an absolute
  `9pt`. This covers nested `em` chains, `%`, `rem`, `px` and `small`-ish values
  produced by InDesign/Word exports. Deliberately larger display type is untouched.
- **Absolute-pixel layout adaptation.** `width` / `max-width` / `min-width`
  declarations in px that are wider than the printable text column are wrapped in
  `min(<px>, 100%)` (or zeroed for `min-width`), for both stylesheets and inline
  `style="..."` attributes. Fixed 500–600px boxes no longer run past the margin on
  narrow auto-sized pages.

## Verification

- 120 tests (24 real-Edge e2e) pass; new fixtures `tinyfont.epub` and
  `pxlayout.epub` cover the font floor and the px clamp.
- Real books with default auto layout: dominant visible body font 8.9pt
  (Systematic Trading, was 8.0pt), 8.9pt (Spec-Driven AI Engineering, was mostly
  7.5–8.5pt), 9.1pt (CJK book); visible text below 9pt is now under 0.6%.
- Generated PDFs keep their page geometry, bookmarks, TOC page numbers and link
  annotations.

## Known limitations

- Scanned/fixed-layout EPUBs (for example *Advances in Financial Machine Learning*)
  are still reflowed; their text layer is positioned by `transform: scale()` and
  keeps its original tiny font size. They are image-based pages, so the visible text
  comes from the scan.

## Compatibility

- CLI/GUI options, page-size defaults (`auto`), outline sources and output naming
  are unchanged from v1.1.3.

# EPUB2PDF v1.1.3

Historical bug-fix: the TOC dotted leader was moved out from under the title text
(flex row). Superseded by v1.1.4, which removes the rule entirely.

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
