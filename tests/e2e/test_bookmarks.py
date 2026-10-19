"""Bookmark (PDF outline) end-to-end assertions."""

from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    convert_epub,
    find_heading_page,
    find_page_with_text,
    outline_depth,
    outline_entries,
    outline_titles,
    pdf_doc,
)

pytestmark = pytest.mark.e2e

ANCHOR_MARKER = "EPBPFANCHOR"


def test_basic_outline_titles_are_clean_and_pages_match_toc(tmp_path):
    pdf = convert_epub("basic.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
        assert entries, "expected a PDF outline"
        titles = outline_titles(doc)
        assert not any(ANCHOR_MARKER in title for title in titles)

        # The TOC entry points at the page containing its heading.
        toc_entries = [entry for entry in entries if "Table of Contents" in entry[1]]
        assert toc_entries, entries
        assert toc_entries[0][2] - 1 == find_heading_page(doc, "Table of Contents")

        # Every chapter entry points at the page whose text contains the title.
        chapter_titles = ["Chapter One: Alpha", "Chapter Two: Beta", "Chapter Three: Gamma"]
        for chapter_title in chapter_titles:
            matching = [entry for entry in entries if chapter_title in entry[1]]
            assert matching, f"missing bookmark for {chapter_title}"
            assert matching[0][2] - 1 == find_heading_page(doc, chapter_title)


def test_cjk_outline_keeps_heading_levels(tmp_path):
    pdf = convert_epub("cjk.epub", tmp_path, timeout=120)

    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
        titles = outline_titles(doc)
        assert outline_depth(doc) >= 3, f"expected nested bookmarks, got {entries[:5]}"
        assert not any(ANCHOR_MARKER in title for title in titles)

        for chapter in range(1, 21):
            expected = f"第{chapter}章 测试标题{chapter}"
            matching = [entry for entry in entries if expected == entry[1]]
            assert matching, f"missing bookmark for {expected}"
            page = matching[0][2] - 1
            assert expected in doc[page].get_text()


def test_outline_falls_back_to_flat_anchors_when_cdp_is_unavailable(tmp_path, monkeypatch):
    from epub2pdf.core import renderer

    def fail_cdp(*args, **kwargs):
        raise RuntimeError("CDP disabled for test")

    monkeypatch.setattr(renderer, "_cdp_print_to_pdf", fail_cdp)

    pdf = convert_epub("basic.epub", tmp_path, timeout=120)

    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
        assert entries, "expected a fallback outline"
        assert all(level == 1 for level, _, _ in entries), entries
        titles = outline_titles(doc)
        assert not any(ANCHOR_MARKER in title for title in titles)
        chapter_titles = {"Chapter One: Alpha", "Chapter Two: Beta", "Chapter Three: Gamma"}
        assert chapter_titles.issubset(set(titles)), titles

