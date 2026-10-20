"""Unit tests for print layout computation (plan v1.1.2, T0.3/M2)."""

from __future__ import annotations

import struct
import zlib

from epub2pdf.core.layout import compute_layout


def _png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def test_image_dimensions_reads_png_header():
    from epub2pdf.core.layout import image_dimensions

    assert image_dimensions(_png(345, 500)) == (345, 500)


def test_auto_layout_uses_cover_ratio():
    layout = compute_layout(cover_size=(790, 990), page_height_pt=666)
    assert abs(layout.page_width_pt / layout.page_height_pt - 790 / 990) < 0.01
    assert abs(layout.page_height_pt - 666) < 0.01


def test_page_height_changes_nothing_about_ratio():
    a = compute_layout(cover_size=(790, 990), page_height_pt=666)
    b = compute_layout(cover_size=(790, 990), page_height_pt=600)
    assert abs(a.page_width_pt / a.page_height_pt - b.page_width_pt / b.page_height_pt) < 0.01


def test_svg_size_skips_xml_declaration():
    from epub2pdf.core.layout import image_dimensions

    svg = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450"></svg>'
    )
    assert image_dimensions(svg) == (300, 450)


def test_auto_layout_makes_cover_full_bleed_and_scales_font():
    layout = compute_layout(cover_size=(300, 450), page_height_pt=666, language="en")
    assert layout.cover_fill == "cover"
    assert layout.mode == "auto"
    assert abs(layout.page_width_pt / layout.page_height_pt - 300 / 450) < 0.01
    assert layout.font_size_pt < 11.0
    assert layout.source.startswith("auto:")


def test_auto_without_cover_falls_back_to_a4_with_warning():
    layout = compute_layout(page_height_pt=666)
    assert layout.source == "A4-fallback"
    assert layout.cover_fill == "contain"
    assert abs(layout.page_width_pt - 595.2756) < 0.01
    assert layout.warning


def test_explicit_a4_keeps_v111_geometry():
    layout = compute_layout(cover_size=(300, 450), page_size="A4")
    assert layout.source == "A4"
    assert layout.mode == "explicit"
    assert layout.cover_fill == "contain"
    assert abs(layout.font_size_pt - 11.0) < 0.001
    assert abs(layout.margin_left_pt - 45.354) < 0.01


def test_font_scale_compact_is_smaller_than_loose():
    compact = compute_layout(cover_size=(790, 990), font_scale="compact")
    loose = compute_layout(cover_size=(790, 990), font_scale="loose")
    assert compact.font_size_pt < loose.font_size_pt


def test_cover_ratio_outside_range_falls_back_to_a4_with_warning():
    # Banners/screenshots are not book covers; a 0.95 ratio must not be used.
    layout = compute_layout(cover_size=(950, 1000), page_height_pt=666)
    assert layout.source == "A4-fallback"
    assert "outside" in (layout.warning or "")
    assert abs(layout.page_width_pt - 595.2756) < 0.01


def test_unknown_page_size_and_font_scale_raise():
    import pytest

    from epub2pdf.core.layout import LayoutError

    with pytest.raises(LayoutError):
        compute_layout(page_size="A0")
    with pytest.raises(LayoutError):
        compute_layout(cover_size=(300, 450), font_scale="huge")


def test_text_width_is_about_40_chars_wide():
    for size in ((300, 450), (500, 750), (790, 990)):
        layout = compute_layout(cover_size=size, language="en")
        # Narrow pages clamp the font at 9pt, so allow a little slack.
        assert 36.5 < layout.text_width_pt / layout.font_size_pt < 42


def test_line_height_depends_on_language():
    latin = compute_layout(cover_size=(790, 990), language="en")
    cjk = compute_layout(cover_size=(790, 990), language="zh-CN")
    assert abs(latin.line_height - 1.40) < 0.001
    assert abs(cjk.line_height - 1.55) < 0.001

def test_metrics_stay_proportional_across_page_widths():
    narrow = compute_layout(cover_size=(790, 990), language="en")
    wide = compute_layout(cover_size=(1086, 1448), language="en")
    for layout in (narrow, wide):
        assert 39.5 < layout.text_width_pt / layout.font_size_pt < 40.5
        assert abs(layout.margin_left_pt / layout.page_width_pt - 0.115) < 0.001
        assert abs(layout.margin_top_pt / layout.page_height_pt - 0.08) < 0.001
        assert abs(layout.margin_bottom_pt / layout.page_height_pt - 0.09) < 0.001
    # Page width (derived from the cover ratio) drives font size.
    assert narrow.page_width_pt > wide.page_width_pt
    assert narrow.font_size_pt > wide.font_size_pt
    assert narrow.text_width_pt > wide.text_width_pt
