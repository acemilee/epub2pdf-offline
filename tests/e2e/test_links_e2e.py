"""Body cross-reference links should read like print, not like a web page.

EPUB exporters (InDesign, Word) commonly wrap link text in a coloured,
underlined ``span`` (for example ``span.URL``), so hiding the anchor's own
color is not enough: the child span keeps its blue ink and underline.  These
tests pin the "native print" behaviour while keeping the links clickable.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

from conftest import convert_epub, pdf_doc

BLUE = 0x0000FF


def _blue_span_count(page) -> int:
    total = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("color", 0) == BLUE:
                    total += 1
    return total


def test_body_links_lose_web_colour_but_stay_clickable(tmp_path):
    doc = pdf_doc(convert_epub("links.epub", tmp_path))
    pages = [page for page in doc if "Chapter One: Links" in page.get_text()]
    assert pages, "chapter one page not found"
    page = pages[-1]

    assert _blue_span_count(page) == 0, "link text is still web-blue"

    links = [link for link in page.get_links() if link.get("page") is not None]
    assert len(links) >= 2, f"expected clickable cross references, got {page.get_links()}"
    for link in links:
        assert int(link["page"]) > page.number + 1, f"link points backwards: {link}"
    assert "Chapter Two" in page.get_text()


def test_plain_body_text_keeps_its_ink(tmp_path):
    doc = pdf_doc(convert_epub("links.epub", tmp_path))
    page = next(page for page in doc if "Body text for chapter two" in page.get_text())
    colors = set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                colors.add(span.get("color", 0))
    assert BLUE not in colors
