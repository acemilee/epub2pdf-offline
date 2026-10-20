"""Books whose headings are styled paragraphs should still get rich bookmarks.

Chromium's ``generateDocumentOutline`` only understands real ``h1``–``h6``
elements.  InDesign-style EPUBs often hide their chapter titles in
``<p class="PartStart">`` while the EPUB navigation document still carries the
full hierarchy.  The assembler should fall back to the EPUB navigation in that
case instead of emitting one flat entry per chapter.
"""

from __future__ import annotations

import pytest

from conftest import convert_epub, outline_entries, pdf_doc

pytestmark = pytest.mark.e2e


def test_sparse_chromium_outline_falls_back_to_epub_navigation(tmp_path, require_edge):
    pdf_path = convert_epub("partialnested.epub", tmp_path)

    with pdf_doc(pdf_path) as doc:
        entries = outline_entries(doc)

    titles = [title for _level, title, _page in entries]
    # 5 chapters + 3 sections each.
    assert len(entries) >= 15, f"expected the EPUB navigation outline, got {titles}"
    assert "Chapter 3: Styled Heading" in titles
    assert "Section 3.2" in titles
    # Nested entries keep their hierarchy instead of one flat list.
    assert max(level for level, _title, _page in entries) >= 2, titles
