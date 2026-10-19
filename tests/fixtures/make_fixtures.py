"""Generate the EPUB fixtures used by the end-to-end tests.

Run from the repository root:

    F:\\python313\\python.exe tests/fixtures/make_fixtures.py

The script is idempotent: it rewrites the ``*.epub`` files next to itself.
Fixtures contain only generated text/CSS and a 1x1 PNG; no third-party font
files are embedded (plan v1.0.1, Q5).
"""

from __future__ import annotations

import base64
from pathlib import Path

from ebooklib import epub

FIXTURE_DIR = Path(__file__).resolve().parent

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

UNDERLINE_CSS = """
body { font-family: "Segoe UI", sans-serif; }
a, a:link, a:visited { color: #06c; text-decoration: underline; }
.toc-list li { margin: 0.6em 0; }
"""


def _new_book(identifier: str, title: str, language: str = "en") -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language(language)
    book.add_author("Fixture Author")
    return book


def _add_style(book: epub.EpubBook, css: str = UNDERLINE_CSS) -> epub.EpubItem:
    style = epub.EpubItem(
        uid="style_main",
        file_name="style/main.css",
        media_type="text/css",
        content=css.encode("utf-8"),
    )
    book.add_item(style)
    return style


def _add_ncx_nav(book: epub.EpubBook) -> None:
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())


def _write(book: epub.EpubBook, name: str) -> Path:
    target = FIXTURE_DIR / name
    epub.write_epub(str(target), book)
    return target


def build_basic() -> Path:
    """3 chapters + a TOC page in the spine + one PNG image."""
    book = _new_book("fixture-basic", "Basic Fixture Book")
    style = _add_style(book)

    chapters = []
    for index, (title, marker) in enumerate(
        [("Chapter One: Alpha", "alpha"), ("Chapter Two: Beta", "beta"), ("Chapter Three: Gamma", "gamma")],
        start=1,
    ):
        chapter = epub.EpubHtml(
            title=title,
            file_name=f"chapter{index}.xhtml",
            lang="en",
        )
        chapter.content = f"""<html><head><title>{title}</title></head><body>
<h1>{title}</h1>
<p>This is the {marker} chapter of the basic fixture.</p>
<img src="images/pixel.png" alt="pixel"/>
</body></html>"""
        chapter.add_item(style)
        book.add_item(chapter)
        chapters.append(chapter)

    toc_page = epub.EpubHtml(title="Table of Contents", file_name="toc.xhtml", lang="en")
    toc_page.content = """<html><head><title>Table of Contents</title></head><body>
<h1>Table of Contents</h1>
<ol class="toc-list">
  <li><a href="chapter1.xhtml">Chapter One: Alpha</a></li>
  <li><a href="chapter2.xhtml">Chapter Two: Beta</a></li>
  <li><a href="chapter3.xhtml">Chapter Three: Gamma</a></li>
</ol>
</body></html>"""
    toc_page.add_item(style)
    book.add_item(toc_page)

    image = epub.EpubImage()
    image.file_name = "images/pixel.png"
    image.media_type = "image/png"
    image.content = PNG_BYTES
    book.add_item(image)

    book.toc = [epub.Link("toc.xhtml", "Table of Contents", "toc")] + [
        epub.Link(ch.file_name, ch.title, ch.file_name) for ch in chapters
    ]
    book.spine = ["nav", toc_page, *chapters]
    _add_ncx_nav(book)
    return _write(book, "basic.epub")


def build_cjk() -> Path:
    """20 Chinese chapters; each has h2/h3 subsections and a fragment TOC."""
    book = _new_book("fixture-cjk", "中文测试书", language="zh-CN")
    style = _add_style(book)

    chapters = []
    toc_nodes = []
    for index in range(1, 21):
        title = f"第{index}章 测试标题{index}"
        sections_html = []
        child_links = []
        for section in range(1, 3):
            heading_id = f"cjk{index:02d}-s{section}"
            sections_html.append(f'<h2 id="{heading_id}">第{index}章第{section}节</h2>')
            sections_html.append(f"<p>这是第{index}章第{section}节的正文，用于验证中文排版与书签层级。{'内容' * 30}</p>")
            sections_html.append(f"<h3>第{index}章第{section}节小节</h3>")
            sections_html.append(f"<p>小节正文，重复字符以增加页面高度。{'小节' * 40}</p>")
            child_links.append(
                epub.Link(
                    f"cjk{index:02d}.xhtml#{heading_id}",
                    f"第{index}章第{section}节",
                    heading_id,
                )
            )
        chapter = epub.EpubHtml(title=title, file_name=f"cjk{index:02d}.xhtml", lang="zh-CN")
        chapter.content = (
            "<html><head><title>%s</title></head><body><h1>%s</h1>%s</body></html>"
            % (title, title, "".join(sections_html))
        )
        chapter.add_item(style)
        book.add_item(chapter)
        chapters.append(chapter)
        section = epub.Section(title, chapter.file_name)
        toc_nodes.append((section, child_links))

    book.toc = toc_nodes
    book.spine = ["nav", *chapters]
    _add_ncx_nav(book)
    return _write(book, "cjk.epub")


def build_fontsplit() -> Path:
    """One long chapter whose character set grows across pages (font subset union)."""
    book = _new_book("fixture-fontsplit", "Font Split Fixture")
    style = _add_style(book)

    paragraphs = []
    for start in range(0x4E00, 0x4E00 + 240):
        paragraphs.append(f"<p>{chr(start)} 字符测试 {start:04X} ascii sample text</p>")
    chapter = epub.EpubHtml(title="Font Split Chapter", file_name="fontsplit.xhtml", lang="zh-CN")
    chapter.content = (
        "<html><head><title>Font Split Chapter</title></head><body>"
        "<h1>Font Split Chapter</h1>%s</body></html>" % "".join(paragraphs)
    )
    chapter.add_item(style)
    book.add_item(chapter)

    book.toc = [epub.Link(chapter.file_name, chapter.title, "fontsplit")]
    book.spine = ["nav", chapter]
    _add_ncx_nav(book)
    return _write(book, "fontsplit.epub")


SVG_COVER = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450">
  <rect width="300" height="450" fill="#cc2222"/>
  <rect x="30" y="30" width="240" height="390" fill="#2266cc"/>
  <text x="150" y="230" font-size="28" text-anchor="middle" fill="#ffffff">SVG Cover</text>
</svg>
"""

# An InDesign-style stylesheet: declares zero page margins (and a margin box)
# which would otherwise override the converter's print @page rules.
ZEROMARGIN_CSS = """
@page { margin: 0px 0px 0px 0px; @top-center { content: "running header"; } }
@page :first { margin: 0px; }
body { font-family: "Segoe UI", sans-serif; margin: 0; padding: 0; }
p { margin: 0 0 0.6em 0; }
"""


def build_zeromargin() -> Path:
    """Book whose CSS declares ``@page { margin: 0 }`` (v1.1.1 regression)."""
    book = _new_book("fixture-zeromargin", "Zero Margin Fixture")
    style = _add_style(book, ZEROMARGIN_CSS)

    chapters = []
    for index in range(1, 4):
        title = f"Zero Margin Chapter {index}"
        inline_style = (
            "<style>@page { margin: 0; }</style>" if index == 2 else ""
        )
        chapter = epub.EpubHtml(
            title=title, file_name=f"zero{index}.xhtml", lang="en"
        )
        chapter.content = (
            "<html><head><title>%s</title>%s</head><body>"
            "<h1>%s</h1>%s</body></html>"
            % (
                title,
                inline_style,
                title,
                "".join(
                    f"<p>Body line {n} for the zero-margin regression fixture. "
                    "The converter must restore its A4 print margins.</p>"
                    for n in range(1, 8)
                ),
            )
        )
        chapter.add_item(style)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = [epub.Link(ch.file_name, ch.title, ch.file_name) for ch in chapters]
    book.spine = ["nav", *chapters]
    _add_ncx_nav(book)
    return _write(book, "zeromargin.epub")


def build_svgcover() -> Path:
    """Book whose cover image is SVG (regression for the blank-cover bug)."""
    book = _new_book("fixture-svgcover", "SVG Cover Fixture")
    style = _add_style(book)
    chapter = epub.EpubHtml(title="One Chapter", file_name="only.xhtml", lang="en")
    chapter.content = (
        "<html><head><title>One Chapter</title></head><body>"
        "<h1>One Chapter</h1><p>body text</p></body></html>"
    )
    chapter.add_item(style)
    book.add_item(chapter)
    book.set_cover("cover.svg", SVG_COVER, create_page=True)
    book.toc = [epub.Link(chapter.file_name, chapter.title, "only")]
    book.spine = ["nav", chapter]
    _add_ncx_nav(book)
    return _write(book, "svgcover.epub")


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for builder in (
        build_basic,
        build_cjk,
        build_fontsplit,
        build_svgcover,
        build_zeromargin,
    ):
        path = builder()
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
