"""E2E: generated TOC covers fragment-level TOC entries (cjk.epub)."""
from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    convert_epub,
    outline_entries,
    pdf_doc,
)

pytestmark = pytest.mark.e2e


def _toc_text(doc) -> str:
    texts = []
    for index in range(doc.page_count):
        text = doc[index].get_text()
        if "EPBPFANCHOR" in text:
            break
        texts.append(text)
    return "\n".join(texts)


def _body_page_containing(doc, needle: str) -> int | None:
    first_body = None
    for index in range(doc.page_count):
        if "EPBPFANCHOR" in doc[index].get_text():
            first_body = index
            break
    if first_body is None:
        return None
    for index in range(first_body, doc.page_count):
        if needle in doc[index].get_text():
            return index
    return None


def test_generated_toc_includes_fragment_sections_with_page_numbers(tmp_path):
    pdf = convert_epub("cjk.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        toc_text = _toc_text(doc)
        assert "目录" in toc_text
        for section_title in ("第1章第1节", "第1章第2节", "第2章第1节"):
            assert section_title in toc_text

        for section_title in ("第1章第1节", "第2章第2节"):
            body_page = _body_page_containing(doc, section_title)
            assert body_page is not None
            # Displayed 1-based page number must be the page holding the h2.
            assert str(body_page + 1) in toc_text

        # Outline still carries every chapter (21 entries incl. the book title).
        assert len(outline_entries(doc)) >= 21
