"""Unit tests for the generated table-of-contents pages."""
from __future__ import annotations

import re

import pytest

from epub2pdf.core.normalizer import TocAnchor
from epub2pdf.core import toc_page


def _anchor(anchor_id: str, title: str, level: int = 0) -> TocAnchor:
    return TocAnchor(
        title=title,
        level=level,
        href=f"chapter.xhtml#{anchor_id}",
        fragment=anchor_id,
        anchor_id=anchor_id,
    )


A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378


def test_entries_per_page_fits_a4_rows():
    per_page = toc_page.entries_per_page(A4_HEIGHT_PT)
    assert per_page == 34
    assert per_page * toc_page.ROW_HEIGHT_PT <= (
        A4_HEIGHT_PT
        - toc_page._mm(toc_page.TOP_MARGIN_MM)
        - toc_page._mm(toc_page.BOTTOM_MARGIN_MM)
        - toc_page.TITLE_BLOCK_PT
    )


def test_toc_title_is_localized():
    assert toc_page.toc_title_for_language("zh-CN") == "目录"
    assert toc_page.toc_title_for_language("zh") == "目录"
    assert toc_page.toc_title_for_language("en") == "Contents"
    assert toc_page.toc_title_for_language("") == "Contents"


def test_build_toc_html_has_one_row_per_entry_with_page_numbers():
    entries = [
        _anchor("EPBPFTOC_1", "Chapter One", 0),
        _anchor("EPBPFTOC_2", "Section One", 1),
        _anchor("EPBPFTOC_3", "Chapter Two", 0),
    ]
    numbers = {
        "EPBPFTOC_1": 5,
        "EPBPFTOC_2": 6,
        "EPBPFTOC_3": 9,
    }
    html = toc_page.build_toc_html(
        entries,
        numbers,
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
        title="Contents",
    )
    assert html.count('class="row"') == 3
    assert ">Chapter One<" in html
    assert ">Section One<" in html
    assert ">5<" in html and ">6<" in html and ">9<" in html
    # Clean native-looking TOC: no dotted/dashed leader lines at all.
    assert "leader" not in html
    assert "dotted" not in html
    assert "text-decoration: underline" not in html


def test_rows_are_title_and_page_number_without_leader_lines():
    """No leader lines: the gap between title and page number stays empty."""
    entries = [_anchor("EPBPFTOC_1", "Chapter One", 0)]
    html = toc_page.build_toc_html(
        entries,
        {"EPBPFTOC_1": 5},
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
        title="Contents",
    )
    assert "display: flex" in html
    assert 'class="t"' in html and 'class="n"' in html
    assert html.index('class="t"') < html.index('class="n"')


def test_build_toc_html_paginates_after_rows_per_page():
    entries = [
        _anchor(f"EPBPFTOC_{i}", f"Chapter {i}", 0)
        for i in range(toc_page.entries_per_page(A4_HEIGHT_PT) + 2)
    ]
    html = toc_page.build_toc_html(
        entries,
        {},
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
        title="Contents",
    )
    assert html.count('class="page"') == 2
    assert html.count('class="toc-title"') == 2


def test_rows_beyond_first_page_are_positioned_on_their_own_page():
    per_page = toc_page.entries_per_page(A4_HEIGHT_PT)
    page_index, top = toc_page._row_geometry(per_page, per_page, A4_HEIGHT_PT)
    assert page_index == 1
    first_page, first_top = toc_page._row_geometry(0, per_page, A4_HEIGHT_PT)
    assert first_page == 0
    assert top == first_top


def test_long_title_grows_its_row_to_two_lines():
    long_title = "Chapter One: " + "A Very Long Chapter Title " * 6
    entries = [
        _anchor("EPBPFTOC_1", long_title, 0),
        _anchor("EPBPFTOC_2", "Chapter Two", 0),
    ]
    rows, _pages = toc_page._layout_rows(
        entries,
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
    )
    assert rows[0].lines == 2
    assert rows[0].height_pt == pytest.approx(2 * toc_page.ROW_HEIGHT_PT)
    # The following row starts after the grown row, not on top of it.
    assert rows[1].top_pt == pytest.approx(rows[0].top_pt + rows[0].height_pt)
    html = toc_page.build_toc_html(
        entries,
        {"EPBPFTOC_1": 5, "EPBPFTOC_2": 9},
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
        title="Contents",
    )
    assert "-webkit-line-clamp:2" in html
    assert "text-overflow: ellipsis" not in html


def test_short_titles_keep_one_line_per_row():
    entries = [_anchor(f"EPBPFTOC_{i}", f"Chapter {i}", 0) for i in range(5)]
    rows, _pages = toc_page._layout_rows(
        entries,
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
    )
    assert [row.lines for row in rows] == [1, 1, 1, 1, 1]
    assert all(row.height_pt == toc_page.ROW_HEIGHT_PT for row in rows)


def test_long_titles_still_paginate_within_the_bottom_margin():
    entries = [
        _anchor("EPBPFTOC_" + str(i), "A Very Long Chapter Title " * 6, 0)
        for i in range(60)
    ]
    rows, pages = toc_page._layout_rows(
        entries,
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
    )
    assert pages > 1
    bottom_limit = A4_HEIGHT_PT - toc_page._mm(toc_page.BOTTOM_MARGIN_MM)
    for row in rows:
        assert row.top_pt + row.height_pt <= bottom_limit + 0.01
    # Rows never overlap each other on the same page.
    for first, second in zip(rows, rows[1:]):
        if first.page_index == second.page_index:
            assert second.top_pt >= first.top_pt + first.height_pt - 0.01
