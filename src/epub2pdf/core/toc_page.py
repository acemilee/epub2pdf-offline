"""Generated table-of-contents pages for the final PDF.

The EPUB already ships a navigation page (kept as-is), but readers expect a
classic paginated table of contents with a right-aligned page number and dot
leaders.  This module builds that page as HTML, renders it with the same
headless-Chromium pipeline used for the body, and returns the geometry needed
to add clickable link annotations in the assembler.
"""
from __future__ import annotations

from dataclasses import dataclass
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


def entries_per_page(page_height_pt: float) -> int:
    """How many rows fit on one TOC page."""
    usable = (
        page_height_pt
        - _mm(TOP_MARGIN_MM)
        - _mm(BOTTOM_MARGIN_MM)
        - TITLE_BLOCK_PT
    )
    return max(1, int(usable // ROW_HEIGHT_PT))


def toc_title_for_language(language: str) -> str:
    lang = (language or "").strip().lower()
    return "目录" if lang.startswith("zh") else "Contents"


def _row_geometry(
    index: int,
    per_page: int,
    page_height_pt: float,
) -> tuple[int, float]:
    """Return ``(page_index, top_pt_from_page_top)`` for entry ``index``."""
    page_index = index // per_page
    row = index % per_page
    top = _mm(TOP_MARGIN_MM) + TITLE_BLOCK_PT + row * ROW_HEIGHT_PT
    return page_index, top


def _link_rect(
    top_pt: float,
    page_width_pt: float,
    page_height_pt: float,
) -> tuple[float, float, float, float]:
    """PDF-space rect covering one row, measured from the page top."""
    x1 = _mm(LEFT_MARGIN_MM)
    x2 = page_width_pt - _mm(RIGHT_MARGIN_MM)
    y_top = page_height_pt - top_pt - 2.0
    y_bottom = page_height_pt - top_pt - ROW_HEIGHT_PT + 2.0
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
) -> str:
    """Build the absolute-positioned TOC HTML (one ``.page`` per sheet)."""
    per_page = entries_per_page(page_height_pt)
    page_count = max(1, (len(entries) + per_page - 1) // per_page)
    left = _mm(LEFT_MARGIN_MM)
    right = page_width_pt - _mm(RIGHT_MARGIN_MM)
    number_width = PAGE_NUMBER_WIDTH_PT
    parts: list[str] = []

    page_start = (
        f"<div class=\"page\">"
        f"<div class=\"toc-title\" style=\"top:{_mm(TOP_MARGIN_MM):.2f}pt;\">"
        f"{_html_escape(title)}</div>"
    )
    for page_index in range(page_count):
        parts.append(page_start)
        for index in range(page_index * per_page, min((page_index + 1) * per_page, len(entries))):
            entry = entries[index]
            _, top = _row_geometry(index, per_page, page_height_pt)
            indent = min(entry.level, MAX_LEVEL_INDENT) * INDENT_PER_LEVEL_PT
            text_left = left + indent
            number_left = right - number_width
            title_right = number_left - 10.0
            title_width = max(20.0, title_right - text_left)
            page_number = page_numbers.get(entry.anchor_id)
            number_text = "" if page_number is None else str(page_number)
            row_top = top + 4.0
            parts.append(
                f"<div class=\"row\">"
                f"<div class=\"t\" style=\"left:{text_left:.2f}pt;top:{row_top:.2f}pt;"
                f"width:{title_width:.2f}pt;\">{_html_escape(entry.title)}</div>"
                f"<div class=\"leader\" style=\"left:{text_left:.2f}pt;"
                f"width:{title_width:.2f}pt;top:{row_top + ROW_HEIGHT_PT - 6.0:.2f}pt;\"></div>"
                f"<div class=\"n\" style=\"left:{number_left:.2f}pt;top:{row_top:.2f}pt;"
                f"width:{number_width:.2f}pt;\">{number_text}</div>"
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
             text-align: center; font-size: {TITLE_FONT_PT:.1f}pt; font-weight: 700;
             letter-spacing: 0.08em; }}
.row {{ position: absolute; left: 0; top: 0; width: {page_width_pt:.2f}pt;
       height: {ROW_HEIGHT_PT:.2f}pt; }}
.t {{ position: absolute; font-size: {ENTRY_FONT_PT:.2f}pt; line-height: {ROW_HEIGHT_PT - 4:.2f}pt;
     white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
     text-decoration: none; color: #000; }}
.leader {{ position: absolute; border-bottom: 0.75pt dotted #8a8a8a; height: 0; }}
.n {{ position: absolute; font-size: {ENTRY_FONT_PT:.2f}pt; line-height: {ROW_HEIGHT_PT - 4:.2f}pt;
     text-align: right; font-variant-numeric: tabular-nums; color: #000; }}
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

    per_page = entries_per_page(page_height_pt)
    page_count = max(1, (len(entries) + per_page - 1) // per_page)
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
    for index, entry in enumerate(entries):
        raw_page = anchor_page_index.get(entry.anchor_id)
        if raw_page is None:
            continue
        toc_page_index, top = _row_geometry(index, per_page, page_height_pt)
        links.append(
            TocLink(
                toc_page_index=toc_page_index,
                rect=_link_rect(top, page_width_pt, page_height_pt),
                # Body pages come after cover + TOC pages.
                target_page_index=raw_page + cover_pages + page_count,
            )
        )
    return TocRenderResult(page_count, last_numbers, tuple(links))
