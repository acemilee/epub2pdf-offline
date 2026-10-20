"""Native-reading polish: page numbers and bookmark fallbacks (v1.1.5)."""

from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    convert_epub,
    outline_titles,
    pdf_doc,
)

pytestmark = pytest.mark.e2e


def footer_digits(page) -> list[str]:
    """Return digit-only words drawn in the bottom 10% of the page."""
    height = page.rect.height
    words = page.get_text("words")
    return [
        word[4].strip()
        for word in words
        if word[1] > height * 0.9 and word[4].strip().isdigit()
    ]


def test_page_numbers_match_the_physical_page_index(tmp_path):
    pdf = convert_epub("basic.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        assert doc.page_count >= 4
        for index, page in enumerate(doc):
            assert footer_digits(page) == [str(index + 1)], (index, page.get_text())
    finally:
        doc.close()


def test_page_numbers_can_be_disabled(tmp_path):
    pdf = convert_epub("basic.epub", tmp_path, page_numbers=False)
    doc = pdf_doc(pdf)
    try:
        for index, page in enumerate(doc):
            assert footer_digits(page) == [], index
    finally:
        doc.close()


def test_sparse_headings_book_gets_chapter_bookmarks(tmp_path):
    pdf = convert_epub("partialheads.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        titles = outline_titles(doc)
    finally:
        doc.close()
    # Chromium only sees the single real <h1>; the assembler must add the rest.
    assert len(titles) >= 12, titles
    assert "Part 7: Chapter Title" in titles
