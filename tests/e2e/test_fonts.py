"""Font embedding end-to-end tests (plan v1.0.1, T4.3 / T5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import (
    assert_type0_fonts_embedded,
    convert_epub,
    pdf_doc,
)

pytest.importorskip("ebooklib")
pytest.importorskip("pikepdf")
pytest.importorskip("fontTools")

from ebooklib import epub  # noqa: E402
import pikepdf  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

from epub2pdf.core.font_embed import collect_gids_for_font_pikepdf  # noqa: E402
from epub2pdf.core.normalizer import normalize  # noqa: E402
from epub2pdf.core.parser import parse  # noqa: E402
from epub2pdf.core.renderer import render  # noqa: E402

pytestmark = pytest.mark.e2e

WIN_FONT = Path(r"C:\Windows\Fonts\segoeui.ttf")


def _embedded_webfont_epub(tmp_path: Path) -> Path:
    """EPUB with a webfont referenced through CSS ``@font-face``."""
    book = epub.EpubBook()
    book.set_identifier("fixture-webfont")
    book.set_title("Webfont Fixture")
    book.set_language("en")
    book.add_author("Fixture Author")

    style = epub.EpubItem(
        uid="style_main",
        file_name="OEBPS/style/main.css",
        media_type="text/css",
        content=(
            b'@font-face { font-family: "FixtureWebFont"; '
            b'src: url("../fonts/web.ttf") format("truetype"); }\n'
            b'body { font-family: "FixtureWebFont", serif; }\n'
        ),
    )
    book.add_item(style)

    font = epub.EpubItem(
        uid="font_web",
        file_name="OEBPS/fonts/web.ttf",
        media_type="application/font-sfnt",
        content=WIN_FONT.read_bytes(),
    )
    book.add_item(font)

    chapter = epub.EpubHtml(title="Webfont Chapter", file_name="OEBPS/ch1.xhtml", lang="en")
    chapter.content = (
        "<html><head><title>Webfont Chapter</title></head><body>"
        "<h1>Webfont Chapter</h1>"
        "<p>Body text rendered with the embedded webfont.</p>"
        "</body></html>"
    )
    chapter.add_item(style)
    book.add_item(chapter)

    book.toc = [epub.Link(chapter.file_name, chapter.title, "ch1")]
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    target = tmp_path / "webfont.epub"
    epub.write_epub(str(target), book)
    return target


def _type0_fontfiles(pdf_path: Path) -> list[bytes]:
    """Return the embedded ``/FontFile2`` streams of all Type0 fonts."""
    blobs: list[bytes] = []
    with pikepdf.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            resources = page.get("/Resources", {})
            fonts = resources.get("/Font", {}) if resources else {}
            for font in fonts.values():
                if str(font.get("/Subtype")) != "/Type0":
                    continue
                descendants = font.get("/DescendantFonts", [])
                if not descendants:
                    continue
                descriptor = descendants[0].get("/FontDescriptor")
                if descriptor is None:
                    continue
                stream = descriptor.get("/FontFile2")
                if stream is not None:
                    blobs.append(bytes(stream.read_bytes()))
    return blobs


def test_epub_embedded_font_is_used_by_chromium(tmp_path):
    """A CSS ``@font-face`` webfont must reach Chromium, which embeds it itself.

    Chromium only embeds *webfonts* in print-to-pdf output; system fonts are
    left unembedded (that is what our font_embed pass patches). So a raw
    render containing at least one ``/FontFile2`` proves the EPUB font loaded.
    """
    if not WIN_FONT.is_file():
        pytest.skip(f"test webfont missing: {WIN_FONT}")

    epub_path = _embedded_webfont_epub(tmp_path)
    book = parse(str(epub_path))
    html_path = normalize(book, str(tmp_path / "work")).html_path

    html = Path(html_path).read_text(encoding="utf-8")
    assert "fonts/web.ttf" in html
    assert "../fonts/web.ttf" not in html

    raw_pdf = tmp_path / "raw.pdf"
    render(html_path, str(raw_pdf), timeout=120)

    assert _type0_fontfiles(raw_pdf), "Chromium did not load/embed the EPUB webfont"


def test_fontsplit_epub_embeds_gid_union_across_pages(tmp_path):
    """The embedded subset must cover glyphs first used on later pages."""
    pdf = convert_epub("fontsplit.epub", tmp_path)
    assert_type0_fonts_embedded(pdf)

    with pikepdf.open(str(pdf)) as document:
        union_by_font: dict[str, set[int]] = {}
        embedded_by_font: dict[str, bytes] = {}
        for page in document.pages:
            resources = page.get("/Resources", {})
            fonts = resources.get("/Font", {}) if resources else {}
            for name, font in fonts.items():
                if str(font.get("/Subtype")) != "/Type0":
                    continue
                base = str(font.get("/BaseFont", "?"))
                union_by_font.setdefault(base, set()).update(
                    collect_gids_for_font_pikepdf(page, name)
                )
                descriptor = font["/DescendantFonts"][0].get("/FontDescriptor")
                if descriptor is not None and descriptor.get("/FontFile2") is not None:
                    embedded_by_font[base] = bytes(descriptor.FontFile2.read_bytes())

    assert union_by_font
    # The subset with retain_gids keeps GID order, so its glyph count must
    # reach the highest GID used across the whole document.
    with pikepdf.open(str(pdf)) as document:
        for page in document.pages:
            fonts = (page.get("/Resources", {}) or {}).get("/Font", {})
            for name, font in fonts.items():
                if str(font.get("/Subtype")) != "/Type0":
                    continue
                base = str(font.get("/BaseFont", "?"))
                descriptor = font["/DescendantFonts"][0].get("/FontDescriptor")
                stream = descriptor.get("/FontFile2") if descriptor is not None else None
                if stream is None:
                    continue
                from io import BytesIO

                tt = TTFont(BytesIO(bytes(stream.read_bytes())))
                assert tt["maxp"].numGlyphs >= max(union_by_font[base]) + 1, (
                    base,
                    tt["maxp"].numGlyphs,
                    max(union_by_font[base]),
                )
                break
            else:
                continue
            break
