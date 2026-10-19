"""Smoke-level end-to-end assertions shared by all fixtures."""

from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    assert_no_missing_anchors,
    convert_epub,
    find_page_with_text,
    outline_entries,
    page_texts,
    pdf_doc,
    underline_count,
)

pytestmark = pytest.mark.e2e


def test_basic_epub_renders_pages_marker_and_no_underlines(tmp_path, capsys):
    pdf = convert_epub("basic.epub", tmp_path)
    stderr = capsys.readouterr().err

    with pdf_doc(pdf) as doc:
        assert doc.page_count >= 4
        texts = page_texts(doc)
        assert any("EPBPFEND_DOCUMENT" in text for text in texts)

        toc_page = find_page_with_text(doc, "Table of Contents")
        assert toc_page is not None
        assert underline_count(doc[toc_page]) == 0

        assert any(len(page.get_images()) >= 1 for page in doc)

        entries = outline_entries(doc)
        assert entries, "expected PDF bookmarks"
        assert all(page >= 1 for _, _, page in entries)

    assert_no_missing_anchors(stderr)
