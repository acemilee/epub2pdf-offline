"""E2E: SVG cover renders as a real image page (M5 regression)."""
from __future__ import annotations

import pytest

from conftest import convert_epub, pdf_doc  # type: ignore[import-not-found]

pytestmark = pytest.mark.e2e


def test_svg_cover_is_rendered_as_non_blank_first_page(tmp_path):
    pdf = convert_epub("svgcover.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        assert doc.page_count >= 3  # cover + generated TOC + 1 body page
        pixmap = doc[0].get_pixmap(dpi=24)
        samples = pixmap.samples
        # The SVG cover is blue/red: plenty of clearly non-white pixels.
        non_white = sum(1 for value in samples[::3] if value < 220)
        assert non_white > len(range(0, len(samples), 3)) // 10
        # Second page is the generated TOC, third is body.
        assert "EPBPFANCHOR" not in doc[0].get_text()
        assert "EPBPFANCHOR" in doc[2].get_text()
