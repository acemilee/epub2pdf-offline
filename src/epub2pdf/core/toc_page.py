"""Generated table-of-contents pages for the final PDF.

The EPUB already ships a navigation page (kept as-is), but readers expect a
classic paginated table of contents with a right-aligned page number.  This
module builds that page as HTML, renders it with the same headless-Chromium
pipeline used for the body, and returns the geometry needed to add clickable
link annotations in the assembler.  Titles that do not fit on one line wrap onto
a second line (the row grows) instead of being truncated.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Mapping, Sequence

from .normalizer import TocAnchor

MM_TO_PT = 72.0 / 25.4

LEFT_MARGIN_MM = 16.0
RIGHT_MARGIN_MM = 16.0
TOP_MARGIN_MM = 18.0
BOTTOM_MARGIN_MM = 20.0
TITLE_BLOCK_PT = 52.0
ROW_HEIGHT_PT = 20.0
PAGE_NUMBER_WIDTH_PT = 46.0
ENTRY_FONT_PT = 10.5
TITLE_FONT_PT = 20.0
INDENT_PER_LEVEL_PT = 14.0
MAX_LEVEL_INDENT = 4
# A native table of contents wraps a too-long title onto a second line instead
# of truncating it with an ellipsis.  Two lines is the practical limit.
MAX_TITLE_LINES = 2


def _mm(value: float) -> float:
    return value * MM_TO_PT


@dataclass(frozen=True)
class TocLink:
    """One clickable TOC row: page-local rect plus destination page."""

    toc_page_index: int  # 0-based page index inside the TOC page run
    rect: tuple[float, float, float, float]  # PDF user space (x1, y1, x2, y2)
    target_page_index: int  # 0-based page index in the final PDF


@dataclass(frozen=True)
class TocRenderResult:
    page_count: int
    page_numbers: Mapping[str, int]
    links: tuple[TocLink, ...]


def entries_per_page(
    page_height_pt: float,
    *,
    scale: float = 1.0,
    top_margin_pt: float | None = None,
    bottom_margin_pt: float | None = None,
) -> int:
    """How many rows fit on one TOC page."""
    top_margin = _mm(TOP_MARGIN_MM) if top_margin_pt is None else top_margin_pt
    bottom_margin = _mm(BOTTOM_MARGIN_MM) if bottom_margin_pt is None else bottom_margin_pt
    usable = (
        page_height_pt
        - top_margin
        - bottom_margin
        - TITLE_BLOCK_PT * scale
    )
    return max(1, int(usable // (ROW_HEIGHT_PT * scale)))


def toc_title_for_language(language: str) -> str:
    lang = (language or "").strip().lower()
    return "目录" if lang.startswith("zh") else "Contents"


@dataclass(frozen=True)
class _TocRow:
    """Placement of one TOC entry on its page (measured from the page top)."""

    entry_index: int
    page_index: int
    top_pt: float
    height_pt: float
    lines: int


def _char_width_pt(char: str, font_pt: float) -> float:
    """Approximate advance width of one character (no font metrics needed).

    Chromium does the actual wrapping; this estimate only has to be close
    enough to reserve one or two lines for a row.
    """
    code = ord(char)
    if code >= 0x2E80:  # CJK, fullwidth punctuation
        return font_pt
    if char == " ":
        return 0.28 * font_pt
    if char in ".,:;'`|!ilI[](){}\"":
        return 0.28 * font_pt
    if char in "mwMW@%":
        return 0.85 * font_pt
    if char.isupper():
        return 0.64 * font_pt
    return 0.52 * font_pt


def _text_width_pt(text: str, font_pt: float) -> float:
    return sum(_char_width_pt(ch, font_pt) for ch in text)


def _title_lines(title: str, available_pt: float, font_pt: float) -> int:
    """How many lines (1 or 2) a title needs in the given column."""
    if available_pt <= 0:
        return MAX_TITLE_LINES
    # 5% safety margin: if the estimate is slightly short, the browser's own
    # wrap would land on the next line and clip the second line.
    estimated = _text_width_pt(title, font_pt) * 1.05
    if estimated <= available_pt:
        return 1
    return min(MAX_TITLE_LINES, max(2, math.ceil(estimated / available_pt)))


def _layout_rows(
    entries: Sequence[TocAnchor],
    *,
    page_width_pt: float,
    page_height_pt: float,
    scale: float = 1.0,
    left_margin_pt: float | None = None,
    right_margin_pt: float | None = None,
    top_margin_pt: float | None = None,
    bottom_margin_pt: float | None = None,
) -> tuple[list[_TocRow], int]:
    """Place entries on pages, growing rows that wrap onto a second line."""
    left = _mm(LEFT_MARGIN_MM) if left_margin_pt is None else left_margin_pt
    right = _mm(RIGHT_MARGIN_MM) if right_margin_pt is None else right_margin_pt
    top_margin = _mm(TOP_MARGIN_MM) if top_margin_pt is None else top_margin_pt
    bottom_margin = _mm(BOTTOM_MARGIN_MM) if bottom_margin_pt is None else bottom_margin_pt
    row_height = ROW_HEIGHT_PT * scale
    entry_font = ENTRY_FONT_PT * scale
    number_width = PAGE_NUMBER_WIDTH_PT * scale
    indent_step = INDENT_PER_LEVEL_PT * scale
    gap = 8.0 * scale
    content_width = max(40.0, page_width_pt - left - right)
    start_top = top_margin + TITLE_BLOCK_PT * scale
    limit = page_height_pt - bottom_margin

    rows: list[_TocRow] = []
    page_index = 0
    top = start_top
    for index, entry in enumerate(entries):
        indent = min(entry.level, MAX_LEVEL_INDENT) * indent_step
        available = content_width - indent - number_width - gap
        lines = _title_lines(entry.title, available, entry_font)
        height = row_height * lines
        if top + height > limit + 0.01 and top > start_top + 0.01:
            page_index += 1
            top = start_top
        height = min(height, limit - start_top)
        rows.append(_TocRow(index, page_index, top, height, lines))
        top += height
    page_count = rows[-1].page_index + 1 if rows else 1
    return rows, page_count


def _row_geometry(
    index: int,
    per_page: int,
    page_height_pt: float,
    *,
    scale: float = 1.0,
    top_margin_pt: float | None = None,
) -> tuple[int, float]:
    """Return ``(page_index, top_pt_from_page_top)`` for entry ``index``."""
    page_index = index // per_page
    row = index % per_page
    top_margin = _mm(TOP_MARGIN_MM) if top_margin_pt is None else top_margin_pt
    top = top_margin + TITLE_BLOCK_PT * scale + row * ROW_HEIGHT_PT * scale
    return page_index, top


def _link_rect(
    top_pt: float,
    page_width_pt: float,
    page_height_pt: float,
    *,
    scale: float = 1.0,
    left_margin_pt: float | None = None,
    right_margin_pt: float | None = None,
    row_height_pt: float | None = None,
) -> tuple[float, float, float, float]:
    """PDF-space rect covering one row, measured from the page top."""
    left = _mm(LEFT_MARGIN_MM) if left_margin_pt is None else left_margin_pt
    right = _mm(RIGHT_MARGIN_MM) if right_margin_pt is None else right_margin_pt
    row_height = ROW_HEIGHT_PT * scale if row_height_pt is None else row_height_pt
    x1 = left
    x2 = page_width_pt - right
    y_top = page_height_pt - top_pt - 2.0
    y_bottom = page_height_pt - top_pt - row_height + 2.0
    return (x1, y_bottom, x2, y_top)


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_toc_html(
    entries: Sequence[TocAnchor],
    page_numbers: Mapping[str, int],
    *,
    page_width_pt: float,
    page_height_pt: float,
    title: str,
    scale: float = 1.0,
    left_margin_pt: float | None = None,
    right_margin_pt: float | None = None,
    top_margin_pt: float | None = None,
    bottom_margin_pt: float | None = None,
) -> str:
    """Build the absolute-positioned TOC HTML (one ``.page`` per sheet)."""
    rows, page_count = _layout_rows(
        entries,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        scale=scale,
        left_margin_pt=left_margin_pt,
        right_margin_pt=right_margin_pt,
        top_margin_pt=top_margin_pt,
        bottom_margin_pt=bottom_margin_pt,
    )
    left = _mm(LEFT_MARGIN_MM) if left_margin_pt is None else left_margin_pt
    right = _mm(RIGHT_MARGIN_MM) if right_margin_pt is None else right_margin_pt
    top_margin = _mm(TOP_MARGIN_MM) if top_margin_pt is None else top_margin_pt
    row_height = ROW_HEIGHT_PT * scale
    number_width = PAGE_NUMBER_WIDTH_PT * scale
    entry_font = ENTRY_FONT_PT * scale
    title_font = TITLE_FONT_PT * scale
    indent_step = INDENT_PER_LEVEL_PT * scale
    content_width = max(40.0, page_width_pt - left - right)
    parts: list[str] = []

    page_start = (
        f"<div class=\"page\">"
        f"<div class=\"toc-title\" style=\"top:{top_margin:.2f}pt;\">"
        f"{_html_escape(title)}</div>"
    )
    for page_index in range(page_count):
        parts.append(page_start)
        for row in rows:
            if row.page_index != page_index:
                continue
            entry = entries[row.entry_index]
            indent = min(entry.level, MAX_LEVEL_INDENT) * indent_step
            page_number = page_numbers.get(entry.anchor_id)
            number_text = "" if page_number is None else str(page_number)
            parts.append(
                f"<div class=\"row\" style=\"top:{row.top_pt:.2f}pt;"
                f"height:{row.height_pt:.2f}pt;\">"
                f"<div class=\"t\" style=\"padding-left:{indent:.2f}pt;"
                f"font-size:{entry_font:.2f}pt;line-height:{row_height:.2f}pt;"
                f"-webkit-line-clamp:{row.lines};max-height:{row.height_pt:.2f}pt;\">"
                f"{_html_escape(entry.title)}</div>"
                f"<div class=\"n\" style=\"font-size:{entry_font:.2f}pt;"
                f"line-height:{row_height:.2f}pt;\">{number_text}</div>"
                f"</div>"
            )
        parts.append("</div>")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{_html_escape(title)}</title>
<style>
@page {{ size: {page_width_pt:.2f}pt {page_height_pt:.2f}pt; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI','Microsoft YaHei','PingFang SC','Noto Sans CJK SC',Arial,sans-serif; color:#000; }}
.page {{ position: relative; width: {page_width_pt:.2f}pt; height: {page_height_pt:.2f}pt;
        overflow: hidden; page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.toc-title {{ position: absolute; left: 0; width: {page_width_pt:.2f}pt;
             text-align: center; font-size: {title_font:.2f}pt; font-weight: 700;
             letter-spacing: 0.08em; }}
.row {{ position: absolute; left: {left:.2f}pt; width: {content_width:.2f}pt;
       display: flex; align-items: flex-start; overflow: hidden; }}
.t {{ flex: 1 1 auto; min-width: 0; padding-right: {8.0 * scale:.2f}pt;
     display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden;
     white-space: normal; overflow-wrap: anywhere; text-decoration: none;
     color: #000; }}
.n {{ flex: 0 0 {number_width:.2f}pt; text-align: right; align-self: flex-start;
     font-variant-numeric: tabular-nums; color: #000; }}
</style>
</head>
<body>
{''.join(parts)}
</body>
</html>
"""
    return html


def render_toc_pdf(
    entries: Sequence[TocAnchor],
    anchor_page_index: Mapping[str, int],
    *,
    page_width_pt: float,
    page_height_pt: float,
    title: str,
    work_dir: str,
    timeout: int = 120,
    cover_pages: int = 0,
    scale: float = 1.0,
    left_margin_pt: float | None = None,
    right_margin_pt: float | None = None,
    top_margin_pt: float | None = None,
    bottom_margin_pt: float | None = None,
) -> TocRenderResult:
    """Render the TOC pages and compute page numbers + link geometry.

    ``anchor_page_index`` maps ``anchor_id`` to the raw body PDF page index
    (0-based).  Page numbers shown to the reader are 1-based and include the
    cover page and the TOC pages themselves, which is why the layout is
    rendered iteratively until the page count is stable.
    """
    from . import renderer  # local import avoids a cycle at module load

    if not entries:
        return TocRenderResult(0, {}, ())

    rows, page_count = _layout_rows(
        entries,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        scale=scale,
        left_margin_pt=left_margin_pt,
        right_margin_pt=right_margin_pt,
        top_margin_pt=top_margin_pt,
        bottom_margin_pt=bottom_margin_pt,
    )
    html_path = os.path.join(work_dir, "toc.html")
    pdf_path = os.path.join(work_dir, "toc.pdf")
    last_numbers: dict[str, int] = {}
    last_html = ""

    for _ in range(3):
        numbers: dict[str, int] = {}
        for entry in entries:
            raw_page = anchor_page_index.get(entry.anchor_id)
            if raw_page is not None:
                numbers[entry.anchor_id] = raw_page + 1 + cover_pages + page_count
        last_numbers = numbers
        last_html = build_toc_html(
            entries,
            numbers,
            page_width_pt=page_width_pt,
            page_height_pt=page_height_pt,
            title=title,
            scale=scale,
            left_margin_pt=left_margin_pt,
            right_margin_pt=right_margin_pt,
            top_margin_pt=top_margin_pt,
            bottom_margin_pt=bottom_margin_pt,
        )
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(last_html)
        renderer.render(html_path, pdf_path, timeout=timeout)
        from pypdf import PdfReader

        rendered_pages = len(PdfReader(pdf_path).pages)
        if rendered_pages == page_count:
            break
        page_count = rendered_pages

    links: list[TocLink] = []
    for row in rows:
        entry = entries[row.entry_index]
        raw_page = anchor_page_index.get(entry.anchor_id)
        if raw_page is None:
            continue
        links.append(
            TocLink(
                toc_page_index=row.page_index,
                rect=_link_rect(
                    row.top_pt,
                    page_width_pt,
                    page_height_pt,
                    scale=scale,
                    left_margin_pt=left_margin_pt,
                    right_margin_pt=right_margin_pt,
                    row_height_pt=row.height_pt,
                ),
                # Body pages come after cover + TOC pages.
                target_page_index=raw_page + cover_pages + page_count,
            )
        )
    return TocRenderResult(page_count, last_numbers, tuple(links))
