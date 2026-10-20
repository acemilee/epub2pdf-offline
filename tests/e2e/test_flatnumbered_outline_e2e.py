"""Flat EPUB navigation with numbered titles must become a nested outline."""

from __future__ import annotations

import pytest

from conftest import (  # type: ignore[import-not-found]
    convert_epub,
    outline_entries,
    pdf_doc,
)

pytestmark = pytest.mark.e2e


def test_flat_numbered_navigation_is_nested_into_bookmarks(tmp_path):
    pdf = convert_epub("flatnumbered.epub", tmp_path)
    with pdf_doc(pdf) as doc:
        entries = outline_entries(doc)
    titles = [title for _, title, _ in entries]
    assert titles == [
        "1 Introduction",
        "1.1 Motivation",
        "1.1.1 Details",
        "2 Methods",
        "2.1 Setup",
    ], f"unexpected bookmark titles: {titles}"
    levels = {title: level for level, title, _ in entries}
    assert levels["1 Introduction"] == 1
    assert levels["1.1 Motivation"] == 2
    assert levels["1.1.1 Details"] == 3
    assert levels["2 Methods"] == 1
    assert levels["2.1 Setup"] == 2
    pages = {title: page for _, title, page in entries}
    # Every section lives in a later chapter, so page numbers must increase.
    assert pages["1 Introduction"] < pages["1.1 Motivation"] < pages["1.1.1 Details"]
    assert pages["2 Methods"] < pages["2.1 Setup"]
