"""Typography normalization: undersized EPUB CSS must not reach the PDF."""

import pytest

from conftest import (  # type: ignore[import-not-found]
    body_font_sizes,
    convert_epub,
    dominant_body_font_size,
    pdf_doc,
)

pytestmark = pytest.mark.e2e


def test_nested_small_fonts_are_lifted_to_the_readable_floor(tmp_path):
    pdf = convert_epub("tinyfont.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        sizes = body_font_sizes(doc)
        dominant = dominant_body_font_size(doc)

    assert sizes, "no visible body text found"
    # 0.76em paragraphs and 0.76*0.71em notes would be 8.4pt / 5.9pt without
    # normalization; every visible body span must now clear the 9pt floor.
    assert min(sizes) >= 8.8, f"smallest visible body font is {min(sizes)}pt"
    assert dominant >= 8.8, f"dominant body font is {dominant}pt"
