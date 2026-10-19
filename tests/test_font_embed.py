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

def _make_type0_pdf(path, contents: list[bytes], *, embed_existing: bool = False):
    pdf = pikepdf.Pdf.new()
    descriptor_kwargs = dict(Type=pikepdf.Name("/FontDescriptor"), Flags=32)
    if embed_existing:
        descriptor_kwargs["FontFile2"] = pdf.make_stream(b"FAKE-EXISTING")
    descriptor = pdf.make_indirect(pikepdf.Dictionary(**descriptor_kwargs))
    cid_font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/CIDFontType2"),
            BaseFont=pikepdf.Name("/FakeFont"),
            FontDescriptor=descriptor,
        )
    )
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Font"),
            Subtype=pikepdf.Name("/Type0"),
            BaseFont=pikepdf.Name("/FakeFont"),
            Encoding=pikepdf.Name("/Identity-H"),
            DescendantFonts=pikepdf.Array([cid_font]),
        )
    )
    for content in contents:
        page = pdf.add_blank_page(page_size=(200, 200))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(content)
    pdf.save(str(path))


def test_embed_missing_fonts_uses_gid_union_across_pages(monkeypatch, tmp_path):
    from epub2pdf.core import font_embed

    input_pdf = tmp_path / "union_in.pdf"
    output_pdf = tmp_path / "union_out.pdf"
    _make_type0_pdf(
        input_pdf,
        [b"BT /F1 12 Tf <0005> Tj ET", b"BT /F1 12 Tf <0064> Tj ET"],
    )

    captured: list[set[int]] = []
    monkeypatch.setattr(font_embed, "find_system_font", lambda family: tmp_path / "fake.ttf")
    monkeypatch.setattr(
        font_embed,
        "subset_font_to_bytes",
        lambda path, gids: captured.append(set(gids)) or b"FAKE-SUBSET",
    )

    stats = font_embed.embed_missing_fonts(str(input_pdf), str(output_pdf))

    assert captured, stats
    assert captured[0] == {5, 100}, captured
    with pikepdf.open(str(output_pdf)) as pdf:
        descriptor = pdf.pages[0].Resources.Font.F1.DescendantFonts[0].FontDescriptor
        assert bytes(descriptor.FontFile2.read_bytes()) == b"FAKE-SUBSET"


def test_embed_missing_fonts_skips_fonts_with_existing_fontfile(monkeypatch, tmp_path):
    from epub2pdf.core import font_embed

    input_pdf = tmp_path / "existing_in.pdf"
    output_pdf = tmp_path / "existing_out.pdf"
    _make_type0_pdf(input_pdf, [b"BT /F1 12 Tf <0005> Tj ET"], embed_existing=True)

    captured: list[set[int]] = []
    monkeypatch.setattr(
        font_embed,
        "subset_font_to_bytes",
        lambda path, gids: captured.append(set(gids)) or b"SHOULD-NOT-BE-USED",
    )

    stats = font_embed.embed_missing_fonts(str(input_pdf), str(output_pdf))

    assert not captured, stats
    assert any(value == "already-embedded" for value in stats.values()), stats


def test_find_system_font_maps_postscript_names():
    from epub2pdf.core import font_embed

    for family in ("ArialMT", "TimesNewRomanPSMT", "CourierNewPSMT", "Arial-BoldMT"):
        path = font_embed.find_system_font(family)
        assert path is not None and path.is_file(), family
