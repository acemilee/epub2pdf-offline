import shutil
from pathlib import Path

from epub2pdf.core import normalizer
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

    html_path = normalize(book, str(work_dir)).html_path
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

    html_path = normalize(book, str(work_dir)).html_path
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

    html_path = normalize(book, str(work_dir)).html_path
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert 'src="assets/dup.jpg"' in rendered
    assert 'src="assets/dup_1.jpg"' in rendered


def test_normalize_places_anchor_after_first_heading_to_keep_outline_title_clean():
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

    html_path = normalize(book, str(work_dir)).html_path
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "<section class=\"chapter\" id=\"ch1\"" in rendered
    # The marker must be a sibling *after* the heading so Chromium's PDF
    # outline generator sees only the clean heading text.
    assert "<h1>Chapter One</h1>" in rendered
    assert "</h1><span class=\"epub-anchor\"" in rendered
    assert "EPBPFANCHOR_ch1_EPBPFANCHOR_END</span>" in rendered
    assert "<h1>Chapter One<span" not in rendered
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

    html_path = normalize(book, str(work_dir)).html_path
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "table, figure, blockquote {" in rendered
    assert "table, figure, blockquote, pre {" not in rendered
    assert "line-height: 1.5;" in rendered
    assert "line-height: 1.2;" in rendered
    assert "page-break-inside: auto;" in rendered
    assert "break-inside: auto;" in rendered
    assert "<pre>line 1" in rendered


def test_normalize_removes_link_underline_and_link_color_from_epub_anchor_styles():
    """Printed pages contain EPUB nav/TOC pages whose <a> elements would keep
    the browser's default link underline + blue color. Those links are not
    clickable in the generated PDF, so the print styles must neutralize them,
    and the rule must win over EPUB-provided CSS (which may set underline)."""
    chapter_html = (
        "<html><body>"
        '<nav epub:type="toc"><h1>Contents</h1>'
        '<ol><li><a href="ch2.xhtml">Chapter Two</a></li></ol></nav>'
        "</body></html>"
    )
    book = EpubBook(
        title="TOC sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="nav",
                href="Text/nav.xhtml",
                title="Table of Contents",
                content_html=chapter_html,
                is_nav=True,
            )
        ],
        images={},
        fonts={},
        styles={"style.css": b"a { text-decoration: underline; color: #06c; }"},
        cover_image=None,
        toc=[],
    )

    work_dir = Path("tests_tmp/normalizer_toc_links")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    html_path = normalize(book, str(work_dir)).html_path
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "text-decoration: none !important" in rendered
    assert "color: inherit !important" in rendered
    # The neutralizing rule must come after the inlined EPUB stylesheet.
    epub_rule = rendered.index("a { text-decoration: underline; color: #06c; }")
    neutralizer = rendered.index("text-decoration: none !important")
    assert neutralizer > epub_rule


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

    html_path = normalize(book, str(work_dir)).html_path
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "\u00a0" not in rendered
    assert "\u00c2" not in rendered
    assert "rich. " in rendered
    assert "17.   Relative strength" in rendered
    assert "legacy   artifact" in rendered

def test_normalize_skips_synthetic_title_when_heading_differs_only_by_whitespace():
    chapter_html = (
        "<html><body>"
        '<h3><span>Chapter One</span><a href="#n1">*</a></h3><p>Body.</p>'
        "</body></html>"
    )
    book = EpubBook(
        title="Whitespace sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="Text/ch1.xhtml",
                title="Chapter One *",
                content_html=chapter_html,
            )
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )
    work_dir = Path("tests_tmp/normalizer_synthetic_whitespace")
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    rendered = Path(normalize(book, str(work_dir)).html_path).read_text(encoding="utf-8")

    assert "chapter-title synthetic" not in rendered

def test_concat_css_drops_misplaced_charset_rules():
    css = normalizer._concat_css(
        {
            "a.css": b'@charset "utf-8";\nbody{color:red}',
            "b.css": b'@charset "iso-8859-1";\np{color:blue}',
        }
    )

    assert "@charset" not in css.lower()
    assert "color:red" in css
    assert "color:blue" in css


def test_sanitize_epub_css_removes_at_page_rules_only():
    css = """
    @page { margin: 0px 0px 0px 0px; @top-center { content: "running"; } }
    @page :first { margin: 0px; }
    @media print { @page { margin: 0 } }
    @font-face { font-family: X; src: url(fonts/x.ttf); }
    body { margin: 0; color: red; }
    """
    cleaned = normalizer._sanitize_epub_css(css)

    assert "@page" not in cleaned
    assert "@font-face" in cleaned
    assert "body { margin: 0; color: red; }" in cleaned


def test_concat_css_strips_epub_at_page_from_stylesheets():
    css = normalizer._concat_css(
        {"style.css": b"@page { margin: 0 } body { color: red }"}
    )

    assert "@page" not in css
    assert "color: red" in css


def test_post_epub_css_redeclares_print_page_box():
    # The last stylesheet on the page must restore our page box even if an
    # EPUB rule slips through the sanitizer (v1.1.1; v1.1.2 emits it in pt
    # for the computed layout).
    assert "@page" in normalizer.POST_EPUB_CSS
    assert "595.28pt 841.89pt" in normalizer.POST_EPUB_CSS
    # 18mm top / 16mm right / 20mm bottom / 16mm left, expressed in points.
    assert "51.02pt 45.35pt 56.69pt 45.35pt" in normalizer.POST_EPUB_CSS


def test_resolve_toc_chapter_tolerates_html_vs_xhtml_extension():
    book = EpubBook(
        title="Ext mismatch",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(id="c1", href="Text/chapter1.xhtml", title="One", content_html="<p>1</p>"),
            EpubChapter(id="c2", href="Text/chapter2.xhtml", title="Two", content_html="<p>2</p>"),
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    assert normalizer._resolve_toc_chapter(book, "Text/chapter1.html").id == "c1"
    assert normalizer._resolve_toc_chapter(book, "chapter2.html").id == "c2"
    assert normalizer._resolve_toc_chapter(book, "chapter9.html") is None



def test_length_to_pt_converts_css_units():
    to_pt = normalizer._length_to_pt
    assert to_pt("11pt", 11.0) == 11.0
    assert to_pt("16px", 11.0) == 12.0
    assert to_pt("0.71em", 11.0) == 7.81
    assert to_pt("95%", 11.0) == 10.45
    assert to_pt("inherit", 11.0) is None
    assert to_pt("calc(1em + 1px)", 11.0) is None


def test_normalize_font_sizes_lifts_undersized_declarations_only():
    css = (
        "p{font-size:0.71em}"
        "h2{font-size:1.4em}"
        ".pt{font-size:12pt}"
        ".px{font-size:8.5px !important}"
    )
    out = normalizer._normalize_font_sizes(css)

    assert "p{font-size:9pt}" in out
    assert "font-size:8.5px !important" not in out
    assert "font-size:9pt !important" in out
    assert "h2{font-size:1.4em}" in out
    assert ".pt{font-size:12pt}" in out


def test_normalize_font_sizes_keeps_keywords_and_functions():
    css = "p{font-size:inherit}.x{font-size:calc(1em + 1px)}"
    assert normalizer._normalize_font_sizes(css) == css


def test_sanitize_epub_css_lifts_font_sizes_against_layout_root():
    css = "@page{margin:0} p{font-size:0.7em}"
    out = normalizer._sanitize_epub_css(css)
    assert "@page" not in out
    assert "font-size:9pt" in out


def test_clamp_px_widths_only_clamps_columns_wider_than_the_page():
    clamp = normalizer._clamp_px_widths
    assert clamp("div{width:100px}", 341.0) == "div{width:100px}"
    assert "width:min(600px, 100%)" in clamp("div{width:600px}", 341.0)
    assert "min-width:0" in clamp("td{min-width:600px}", 341.0)
    assert "max-width:min(500px, 100%)" in clamp("p{max-width:500px}", 341.0)


def test_rewrite_relative_paths_clamps_inline_px_widths():
    from epub2pdf.core import layout as layout_module

    narrow = layout_module.compute_layout(cover_size=(300, 450))
    html = '<div style="width:600px"><p>text</p></div>'
    out = normalizer._rewrite_relative_paths(
        html, "", "assets", {}, {}, narrow
    )

    assert "width:min(600px, 100%)" in out
    assert 'width="600px"' not in out
