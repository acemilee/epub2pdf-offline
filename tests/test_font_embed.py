import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("pikepdf")

import pikepdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epub2pdf.core.font_embed import collect_gids_for_font_pikepdf


def test_collect_gids_for_font_pikepdf_reads_decoded_content_stream():
    work_dir = Path("tests_tmp/font_embed").resolve()
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = work_dir / "content.pdf"
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary())
    page.Contents = pdf.make_stream(
        b"BT\n"
        b"/F1 12 Tf\n"
        b"<00410042> Tj\n"
        b"[(\\000C) 10 <0044>] TJ\n"
        b"ET\n"
    )
    with pdf_path.open("wb") as f:
        pdf.save(f)

    with pikepdf.open(pdf_path) as reopened:
        gids = collect_gids_for_font_pikepdf(reopened.pages[0], "/F1")

    assert {65, 66, 67, 68}.issubset(gids)
