"""E2E: EPUB ``@page`` rules must not erase the A4 print margins (v1.1.1).

The ``zeromargin.epub`` fixture declares ``@page { margin: 0 }`` in both its
linked stylesheet and (chapter 2) an inline ``<style>`` block, the way
InDesign EPUB exports do. Before v1.1.1 those rules won the cascade and body
text ran to the paper edge.
"""
from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    body_pages,
    convert_epub,
    find_page_with_text,
    pdf_doc,
    text_page_margins,
)

pytestmark = pytest.mark.e2e

MIN_MARGIN_PT = 40.0


def _assert_body_margins(doc, label: str) -> int:
    checked = 0
    for index, page in body_pages(doc):
        margins = text_page_margins(page)
        assert margins is not None, f"{label} page {index + 1} has no text blocks"
        left, _top, right, _bottom = margins
        assert left >= MIN_MARGIN_PT, (
            f"{label} page {index + 1}: left margin {left:.1f}pt "
            f"(expected >= {MIN_MARGIN_PT}pt)"
        )
        assert right >= MIN_MARGIN_PT, (
            f"{label} page {index + 1}: right margin {right:.1f}pt "
            f"(expected >= {MIN_MARGIN_PT}pt)"
        )
        checked += 1
    assert checked >= 2, f"{label}: expected several body pages, got {checked}"
    return checked


def test_epub_at_page_margin_zero_keeps_print_margins(tmp_path):
    pdf = convert_epub("zeromargin.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        _assert_body_margins(doc, "zeromargin.epub")
    finally:
        doc.close()


def test_inline_style_at_page_margin_zero_keeps_print_margins(tmp_path):
    pdf = convert_epub("zeromargin.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        index = find_page_with_text(doc, "Zero Margin Chapter 2")
        assert index is not None, "chapter 2 page not found"
        margins = text_page_margins(doc[index])
        assert margins is not None
        left, top, right, bottom = margins
        assert left >= MIN_MARGIN_PT and right >= MIN_MARGIN_PT, (
            f"inline @page leak: left={left:.1f}pt right={right:.1f}pt "
            f"top={top:.1f}pt bottom={bottom:.1f}pt"
        )
    finally:
        doc.close()
