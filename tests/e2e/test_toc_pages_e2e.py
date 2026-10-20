"""End-to-end tests for the generated table-of-contents pages."""
from __future__ import annotations

import pymupdf
import pytest

from conftest import (  # type: ignore[import-not-found]
    convert_epub,
    find_heading_page,
    outline_entries,
    pdf_doc,
)

pytestmark = pytest.mark.e2e


def _generated_toc_page(doc):
    """Return the 0-based index of the generated TOC page, or None.

    The generated page is the only page that has a Contents heading but no
    invisible ``EPBPFANCHOR`` marker (the EPUB nav page keeps its markers).
    """
    for index in range(doc.page_count):
        text = doc[index].get_text()
        if ("Contents" in text or "目录" in text) and "EPBPFANCHOR" not in text:
            return index
    return None


def test_generated_toc_page_has_page_numbers_matching_outline(tmp_path):
    pdf = convert_epub("basic.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
        assert entries
        toc_index = _generated_toc_page(doc)
        assert toc_index is not None
        toc_text = doc[toc_index].get_text()
        for title in ("Chapter One: Alpha", "Chapter Two: Beta"):
            assert title in toc_text

        # Displayed numbers are 1-based final page numbers of the headings.
        alpha = next(e for e in entries if "Alpha" in e[1])
        assert str(alpha[2]) in toc_text
        assert find_heading_page(doc, "Chapter One: Alpha") == alpha[2] - 1


def _text_line_rects(page):
    rects = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            rects.append(pymupdf.Rect(line["bbox"]))
    return rects


def test_dot_leaders_do_not_run_under_titles(tmp_path):
    """Dot leaders must start after the title text, not beneath it."""
    pdf = convert_epub("basic.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        toc_index = _generated_toc_page(doc)
        assert toc_index is not None
        page = doc[toc_index]
        dots = [d["rect"] for d in page.get_drawings() if d["rect"].height <= 1.0]
        assert dots, "TOC page should draw dot leaders"
        offenders = []
        for dot in dots:
            for line in _text_line_rects(page):
                vertically_inside = dot.y0 >= line.y0 - 0.6 and dot.y1 <= line.y1 + 0.6
                horizontally_inside = dot.x0 < line.x1 - 0.6 and dot.x1 > line.x0 + 0.6
                if vertically_inside and horizontally_inside:
                    offenders.append((dot, line))
                    break
        assert not offenders, f"{len(offenders)} leader dots overlap title text"


def test_generated_toc_rows_are_clickable(tmp_path):
    pdf = convert_epub("basic.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        toc_index = _generated_toc_page(doc)
        assert toc_index is not None
        targets = set()
        for link in doc[toc_index].get_links():
            page = link.get("page")
            if isinstance(page, str) and page.isdigit():
                targets.add(int(page) - 1)  # PyMuPDF reports 1-based pages
            elif isinstance(page, int) and page >= 0:
                targets.add(page)
        assert len(targets) >= 2

        # Every TOC row with a resolved destination points at its heading page.
        outline_pages = {entry[2] - 1 for entry in outline_entries(doc)}
        assert targets <= outline_pages
        for title in ("Chapter One: Alpha", "Chapter Two: Beta"):
            heading_page = find_heading_page(doc, title)
            assert heading_page in targets
