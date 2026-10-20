"""End-to-end tests for the v1.1.2 auto trim-size / typography layout.

The cover ratio drives the page size; the cover is full-bleed; margins and
font size scale with the page width; explicit page sizes keep their geometry.
"""

from __future__ import annotations

import statistics

import pytest

from conftest import (  # type: ignore[import-not-found]
    body_font_sizes,
    convert_epub,
    dominant_body_font_size,
    pdf_doc,
    text_page_margins,
)

A4_WIDTH = 595.276
A4_HEIGHT = 841.89


def _colored_pixel(page) -> bool:
    pix = page.get_pixmap(dpi=30)
    for x, y in ((2, 2), (pix.width - 3, 2), (2, pix.height - 3)):
        if pix.pixel(x, y)[:3] != (255, 255, 255):
            return True
    return False


@pytest.mark.e2e
def test_auto_layout_uses_cover_ratio_and_full_bleed_cover(tmp_path):
    pdf = convert_epub("svgcover.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        first = doc[0]
        ratio = first.rect.width / first.rect.height
        assert abs(ratio - 300 / 450) < 0.02, first.rect
        assert abs(first.rect.height - 666) < 1.0
        # The cover fills the page instead of being letterboxed on A4.
        assert _colored_pixel(first)
        assert "EPBPFANCHOR" not in first.get_text()

        # Body pages keep proportional margins and a smaller body font.
        page = doc[3]
        margins = text_page_margins(page)
        assert margins is not None
        left, top, right, _bottom = margins
        assert left > 30 and top > 30 and right > 30, margins
        assert 8.0 < dominant_body_font_size(doc) < 10.5
    finally:
        doc.close()


@pytest.mark.e2e
def test_auto_without_cover_falls_back_to_a4(tmp_path):
    pdf = convert_epub("basic.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        assert abs(doc[0].rect.width - A4_WIDTH) < 1.0
        assert abs(doc[0].rect.height - A4_HEIGHT) < 1.0
        assert abs(dominant_body_font_size(doc) - 11.0) < 0.6
    finally:
        doc.close()


@pytest.mark.e2e
def test_explicit_a4_keeps_legacy_geometry(tmp_path):
    pdf = convert_epub("svgcover.epub", tmp_path, page_size="A4")
    doc = pdf_doc(pdf)
    try:
        assert abs(doc[0].rect.width - A4_WIDTH) < 1.0
        assert abs(doc[0].rect.height - A4_HEIGHT) < 1.0
        assert abs(dominant_body_font_size(doc) - 11.0) < 0.6
    finally:
        doc.close()


@pytest.mark.e2e
def test_explicit_6x9_scales_toc_and_body(tmp_path):
    pdf = convert_epub("cjk.epub", tmp_path, page_size="6x9")
    doc = pdf_doc(pdf)
    try:
        for page in doc:
            assert abs(page.rect.width - 432) < 1.0
            assert abs(page.rect.height - 648) < 1.0
        assert doc.get_toc()
        assert 8.0 < dominant_body_font_size(doc) < 11.5
    finally:
        doc.close()


@pytest.mark.e2e
def test_font_scale_loose_is_larger_than_compact(tmp_path):
    compact_dir = tmp_path / "compact"
    loose_dir = tmp_path / "loose"
    compact_dir.mkdir()
    loose_dir.mkdir()
    compact = convert_epub(
        "cjk.epub", compact_dir, page_size="6x9", font_scale="compact"
    )
    loose = convert_epub(
        "cjk.epub", loose_dir, page_size="6x9", font_scale="loose"
    )
    compact_doc = pdf_doc(compact)
    loose_doc = pdf_doc(loose)
    try:
        compact_size = dominant_body_font_size(compact_doc)
        loose_size = dominant_body_font_size(loose_doc)
        assert loose_size > compact_size
    finally:
        compact_doc.close()
        loose_doc.close()

@pytest.mark.e2e
def test_generated_toc_page_uses_body_page_size(tmp_path):
    pdf = convert_epub("svgcover.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        body_rect = doc[2].rect
        toc_pages = [
            page for page in doc if "Contents" in page.get_text() and page.get_links()
        ]
        assert toc_pages, "expected a generated TOC page with clickable rows"
        for page in toc_pages:
            assert abs(page.rect.width - body_rect.width) < 0.5
            assert abs(page.rect.height - body_rect.height) < 0.5
    finally:
        doc.close()


@pytest.mark.e2e
def test_explicit_a4_cover_is_still_letterboxed(tmp_path):
    pdf = convert_epub("svgcover.epub", tmp_path, page_size="A4")
    doc = pdf_doc(pdf)
    try:
        first = doc[0]
        pix = first.get_pixmap(dpi=30)
        corners = [
            pix.pixel(2, 2)[:3],
            pix.pixel(pix.width - 3, 2)[:3],
            pix.pixel(2, pix.height - 3)[:3],
            pix.pixel(pix.width - 3, pix.height - 3)[:3],
        ]
        assert all(pixel == (255, 255, 255) for pixel in corners), corners
        assert pix.pixel(pix.width // 2, pix.height // 2)[:3] != (255, 255, 255)
    finally:
        doc.close()
