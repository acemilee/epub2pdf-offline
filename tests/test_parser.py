import re
import shutil
import zipfile
from pathlib import Path

from epub2pdf.core import parser
from epub2pdf.core.normalizer import normalize


def _write_epub_with_svg_cover(path: Path) -> None:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:test:svg-cover</dc:identifier>
    <dc:title>SVG Cover Book</dc:title>
    <dc:creator>Tester</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="cover_xhtml" href="text/cover.xhtml" media-type="application/xhtml+xml" properties="svg"/>
    <item id="title_page_xhtml" href="text/title.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter_1" href="text/ch001.xhtml" media-type="application/xhtml+xml"/>
    <item id="file0_jpg" href="media/file0.jpg" media-type="image/jpeg" properties="cover-image"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="cover_xhtml"/>
    <itemref idref="title_page_xhtml"/>
    <itemref idref="nav"/>
    <itemref idref="chapter_1"/>
  </spine>
  <guide>
    <reference type="cover" title="Cover" href="text/cover.xhtml"/>
  </guide>
</package>
"""
    ncx = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:test:svg-cover"/></head>
  <docTitle><text>SVG Cover Book</text></docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>Chapter One</text></navLabel>
      <content src="text/ch001.xhtml"/>
    </navPoint>
  </navMap>
</ncx>
"""
    cover = """<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <div id="cover-image">
      <svg xmlns="http://www.w3.org/2000/svg"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           viewBox="0 0 600 900">
        <image width="600" height="900" xlink:href="../media/file0.jpg"/>
      </svg>
    </div>
  </body>
</html>
"""
    nav = """<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc" id="toc"><h1>Contents</h1><ol><li><a href="text/ch001.xhtml">Chapter One</a></li></ol></nav>
  </body>
</html>
"""
    title = """<html xmlns="http://www.w3.org/1999/xhtml"><body><section><h1>SVG Cover Book</h1><p>By Tester</p></section></body></html>"""
    chapter = """<html xmlns="http://www.w3.org/1999/xhtml"><body><section><h1>Chapter One</h1><p>Hello text.</p></section></body></html>"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("EPUB/content.opf", opf)
        zf.writestr("EPUB/toc.ncx", ncx)
        zf.writestr("EPUB/text/cover.xhtml", cover)
        zf.writestr("EPUB/text/title.xhtml", title)
        zf.writestr("EPUB/text/ch001.xhtml", chapter)
        zf.writestr("EPUB/nav.xhtml", nav)
        zf.writestr("EPUB/media/file0.jpg", b"\xff\xd8\xfffake-cover")


def test_parse_detects_svg_cover_nav_and_cover_image_bytes():
    work_dir = Path("tests_tmp/parser_svg_cover")
    shutil.rmtree(work_dir, ignore_errors=True)
    epub_path = work_dir / "book.epub"
    _write_epub_with_svg_cover(epub_path)

    book = parser.parse(str(epub_path))

    assert book.cover_image == "media/file0.jpg"
    assert book.cover_bytes == b"\xff\xd8\xfffake-cover"
    assert "media/file0.jpg" in book.images
    assert book.chapters[0].id == "cover_xhtml"
    assert book.chapters[0].is_cover_only is True
    assert book.chapters[2].id == "nav"
    assert book.chapters[2].is_nav is True


def test_normalize_skips_svg_cover_and_does_not_render_internal_or_duplicate_titles():
    work_dir = Path("tests_tmp/parser_svg_cover_normalize")
    shutil.rmtree(work_dir, ignore_errors=True)
    epub_path = work_dir / "book.epub"
    _write_epub_with_svg_cover(epub_path)
    book = parser.parse(str(epub_path))

    html_path = normalize(book, str(work_dir / "work")).html_path
    rendered = Path(html_path).read_text(encoding="utf-8")

    assert "cover_xhtml" not in rendered
    assert 'class="chapter-title synthetic">Chapter One</h1>' not in rendered
    assert rendered.count("<h1>Chapter One") == 1
    assert re.search(r'<h1>Chapter One</h1>\s*<span class="epub-anchor"', rendered)
    assert "EPBPFANCHOR_chapter_1_EPBPFANCHOR_END" in rendered
    assert '<section class="chapter" id="nav"' in rendered
    assert rendered.count("<h1>Contents") == 1
    assert "EPBPFANCHOR_nav_EPBPFANCHOR_END" in rendered



def test_extract_title_uses_first_heading_in_document_order_even_h3():
    html = "<html><body><h3>Chapter Three</h3><h1>Later H1</h1></body></html>"
    assert parser._extract_title_from_xhtml(html) == "Chapter Three"


def test_extract_title_falls_back_to_html_title_when_no_heading():
    html = "<html><head><title>Chapter Title</title></head><body><p>text</p></body></html>"
    assert parser._extract_title_from_xhtml(html) == "Chapter Title"
