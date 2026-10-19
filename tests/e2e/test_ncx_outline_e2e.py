"""E2E: NCX-sourced bookmarks (M3, opt-in via outline_source="ncx")."""
from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    convert_epub,
    outline_depth,
    outline_entries,
    pdf_doc,
)

pytestmark = pytest.mark.e2e


def test_ncx_outline_matches_toc_tree_and_pages(tmp_path):
    pdf = convert_epub("cjk.epub", tmp_path, outline_source="ncx")

    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
        # 20 chapters + 2 sections each = 60 entries from the EPUB TOC.
        assert len(entries) == 60
        assert outline_depth(doc) == 2  # chapter level + section level
        titles = [title for _, title, _ in entries]
        assert "第1章 测试标题1" in titles
        assert "第1章第1节" in titles
        assert all("EPBPFANCHOR" not in title for title in titles)

        # Chapter bookmarks point at the page whose text starts with the h1.
        chapter_entries = [
            (title, page) for _, title, page in entries if title.startswith("第1章 测试标题1")
        ]
        assert chapter_entries
        title, page = chapter_entries[0]
        assert doc[page - 1].get_text().lstrip().startswith(title)


def test_default_outline_source_stays_chromium(tmp_path):
    pdf = convert_epub("cjk.epub", tmp_path)
    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
        # Chromium outline includes the book title row (TOC-derived does not).
        assert any(title == "中文测试书" for _, title, _ in entries)
