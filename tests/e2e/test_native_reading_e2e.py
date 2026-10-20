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


def top_words(page, limit: float = 40.0) -> list[str]:
    """Visible words drawn above ``limit`` pt; ignores anchor markers."""
    return [
        w[4]
        for w in page.get_text("words")
        if w[1] < limit and "EPBPFANCHOR" not in w[4]
    ]


def test_body_pages_carry_running_headers(tmp_path):
    pdf = convert_epub("longchapter.epub", tmp_path)
    doc = pdf_doc(pdf)
    try:
        assert doc.page_count >= 4
        headers = [" ".join(top_words(doc[i])) for i in range(doc.page_count)]
    finally:
        doc.close()
    assert headers[0] == ""  # generated TOC page stays clean
    # Index 1 is a title/nav page whose content sits at the very top; from
    # index 2 on, only the stamped running head should appear there.  The head
    # is mirrored: even physical pages carry the book title, odd pages the
    # chapter title (the chapter opener is left blank).
    assert any("Long Chapter Fixture" in text for text in headers[2:]), headers
    for index in range(3, len(headers)):
        physical = index + 1
        if physical % 2 == 0:
            assert "Long Chapter Fixture" in headers[index], (index, headers)
        else:
            assert "Chapter One" in headers[index], (index, headers)
    assert all("EPBPFANCHOR" not in text for text in headers)


def test_running_headers_can_be_disabled(tmp_path):
    pdf = convert_epub("longchapter.epub", tmp_path, running_headers=False)
    doc = pdf_doc(pdf)
    try:
        tops = [" ".join(top_words(doc[i])) for i in range(2, doc.page_count)]
    finally:
        doc.close()
    assert all(text == "" for text in tops), tops
