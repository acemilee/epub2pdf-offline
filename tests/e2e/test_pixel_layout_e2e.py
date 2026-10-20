"""EPUB absolute-pixel adaptation: fixed-width boxes must fit the column."""

import pytest

from conftest import convert_epub, pdf_doc  # type: ignore[import-not-found]

pytestmark = pytest.mark.e2e


def _max_text_right_edge(doc) -> float:
    right = 0.0
    for page in list(doc)[2:]:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    right = max(right, span["bbox"][2])
    return right


def test_fixed_pixel_width_containers_stay_inside_the_text_column(tmp_path):
    pdf = convert_epub("pxlayout.epub", tmp_path)

    with pdf_doc(pdf) as doc:
        page_width = doc[0].rect.width
        right_edge = _max_text_right_edge(doc)

    # auto layout keeps a 11.5% right margin => text must end by 88.5% W.
    assert right_edge <= page_width * 0.90, (
        f"text runs to {right_edge:.1f}pt on a {page_width:.1f}pt page"
    )
