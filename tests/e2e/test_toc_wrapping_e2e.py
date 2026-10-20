"""Long TOC entries wrap onto a second line instead of being truncated."""

from __future__ import annotations

import pytest

from conftest import convert_epub, outline_titles, page_texts, pdf_doc

pytestmark = pytest.mark.e2e

LONG_TITLE = (
    "Chapter One: A Very Long Chapter Title That Does Not Fit "
    "On A Single Table Of Contents Line And Must Wrap"
)


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_toc_wraps_long_title_instead_of_truncating(tmp_path, require_edge):
    pdf_path = convert_epub("longtoc.epub", tmp_path)

    with pdf_doc(pdf_path) as doc:
        texts = page_texts(doc)
        toc_titles = outline_titles(doc)

    toc_page = next(text for text in texts if "Contents" in text and "EPBPFANCHOR" not in text)
    normalized = _squash(toc_page)
    assert _squash(LONG_TITLE) in normalized, toc_page
    assert "…" not in normalized
    # The bookmark keeps the full title too.
    assert any(_squash(title) == _squash(LONG_TITLE) for title in toc_titles)
