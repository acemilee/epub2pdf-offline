import shutil
from pathlib import Path

from epub2pdf.core.normalizer import normalize
from epub2pdf.core.parser import EpubBook, EpubChapter


def test_normalize_preserves_unicode_text():
    chapter_html = (
        "<!DOCTYPE html><html><body>"
        "<p>It’s © 中文</p>"
        '<img src="../Images/pic.png">'
        "</body></html>"
    )
    book = EpubBook(
        title="Unicode sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="Text/ch1.xhtml",
                title="Chapter",
                content_html=chapter_html,
            )
        ],
        images={"Images/pic.png": b"not-a-real-image"},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_unicode")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir))
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "It’s © 中文" in rendered
    assert "Itâ" not in rendered
    assert "Â©" not in rendered
    assert "ä¸" not in rendered
    assert 'src="assets/pic.png"' in rendered
    assert "EPBPFEND_" in rendered


def test_normalize_rewrites_xhtml_image_paths_with_xml_declaration():
    chapter_html = (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<body><div><img src=\"rsrc2Y.jpg\" alt=\"\"/></div></body>"
        "</html>"
    )
    book = EpubBook(
        title="Image sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="OEBPS/part0001.xhtml",
                title="Chapter",
                content_html=chapter_html,
            )
        ],
        images={"OEBPS/rsrc2Y.jpg": b"not-a-real-image"},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_xhtml_image")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir))
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert 'src="assets/rsrc2Y.jpg"' in rendered


def test_normalize_uses_asset_map_for_duplicate_image_basenames():
    chapter_html = (
        "<html><body>"
        '<img src="../Images/dup.jpg">'
        '<img src="../Other/dup.jpg">'
        "</body></html>"
    )
    book = EpubBook(
        title="Duplicate basename sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="Text/ch1.xhtml",
                title="Chapter",
                content_html=chapter_html,
            )
        ],
        images={
            "Images/dup.jpg": b"image-one",
            "Other/dup.jpg": b"image-two",
        },
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_duplicate_assets")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir))
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert 'src="assets/dup.jpg"' in rendered
    assert 'src="assets/dup_1.jpg"' in rendered


def test_normalize_places_anchor_inside_first_heading_to_avoid_blank_bookmark_page():
    chapter_html = (
        "<html><body>"
        '<section class="level1"><h1>Chapter One</h1><p>Body.</p></section>'
        "</body></html>"
    )
    book = EpubBook(
        title="Anchor sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="Text/ch1.xhtml",
                title="Chapter One",
                content_html=chapter_html,
            )
        ],
        images={},
        fonts={},
        styles={
            "style.css": b"h1 { page-break-before: always; }",
        },
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_anchor_heading")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir))
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "<section class=\"chapter\" id=\"ch1\"" in rendered
    assert "<h1>Chapter One<span class=\"epub-anchor\"" in rendered
    assert "EPBPFANCHOR_ch1_EPBPFANCHOR_END</span></h1>" in rendered
    assert "h1 { page-break-before: always; }" in rendered
    assert ".chapter h1:first-child" in rendered
    chapter_start = rendered.index('<section class="chapter" id="ch1"')
    heading_start = rendered.index("<h1>", chapter_start)
    assert "EPBPFANCHOR_ch1" not in rendered[chapter_start:heading_start]


def test_normalize_allows_pre_blocks_to_split_across_pages():
    chapter_html = (
        "<html><body>"
        '<p class="content-b">代码4-1 基于PyTorch框架的ResNet-18</p>'
        "<pre>line 1\nline 2\nline 3</pre>"
        "</body></html>"
    )
    book = EpubBook(
        title="Code sample",
        author="Tester",
        language="zh",
        chapters=[
            EpubChapter(
                id="ch1",
                href="Text/ch1.xhtml",
                title="Code Chapter",
                content_html=chapter_html,
            )
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_pre_split")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir))
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "table, figure, blockquote {" in rendered
    assert "table, figure, blockquote, pre {" not in rendered
    assert "line-height: 1.5;" in rendered
    assert "line-height: 1.2;" in rendered
    assert "page-break-inside: auto;" in rendered
    assert "break-inside: auto;" in rendered
    assert "<pre>line 1" in rendered


def test_normalize_replaces_nbsp_artifacts_with_regular_spaces():
    chapter_html = (
        "<html><body>"
        "<p>rich.\u00a0</p>"
        "<p>17.&nbsp;&nbsp; Relative strength</p>"
        "<p>legacy \u00c2\u00a0 artifact</p>"
        "</body></html>"
    )
    book = EpubBook(
        title="NBSP sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="Text/ch1.xhtml",
                title="Chapter",
                content_html=chapter_html,
            )
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_nbsp")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir))
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "\u00a0" not in rendered
    assert "\u00c2" not in rendered
    assert "rich. " in rendered
    assert "17.   Relative strength" in rendered
    assert "legacy   artifact" in rendered
