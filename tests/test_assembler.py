import shutil
from pathlib import Path

import pytest

from epub2pdf.core import assembler
from epub2pdf.core.parser import EpubChapter


def test_make_cover_pdf_uses_body_page_size_and_cover_fit(monkeypatch):
    work_dir = Path("tests_tmp/assembler_cover").resolve()
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    commands = []

    def fake_find_msedge():
        return "msedge.exe"

    class FakeProc:
        returncode = 0

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        out_arg = next(part for part in cmd if part.startswith("--print-to-pdf="))
        Path(out_arg.split("=", 1)[1]).write_bytes(b"%PDF fake")
        return FakeProc()

    monkeypatch.setattr("epub2pdf.core.renderer.find_msedge", fake_find_msedge)
    monkeypatch.setattr("subprocess.run", fake_run)

    image_path = work_dir / "cover.jpg"
    image_path.write_bytes(b"\xff\xd8\xfffake")

    cover_pdf = assembler._make_cover_pdf(
        str(image_path),
        str(work_dir),
        page_size=(612.0, 792.0),
    )

    assert cover_pdf == str(work_dir / "cover.pdf")
    html = (work_dir / "_cover.html").read_text(encoding="utf-8")
    assert "@page{size:8.500000in 11.000000in;margin:0;}" in html
    assert "object-fit:contain;" in html
    assert "max-width:100%;max-height:100%" in html
    assert commands
    profile_args = [
        part for part in commands[0] if part.startswith("--user-data-dir=")
    ]
    assert len(profile_args) == 1
    profile_dir = Path(profile_args[0].split("=", 1)[1])
    assert profile_dir.parent == work_dir
    assert profile_dir.name.startswith(".epub2pdf-edge-")
    assert not profile_dir.exists()


def test_assemble_uses_unique_cover_work_dir(monkeypatch):
    work_dir = Path("tests_tmp/assembler_cover_isolation").resolve()
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    render_work_dir = work_dir / "render_work"
    output_dir = work_dir / "output"
    render_work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf = render_work_dir / "raw.pdf"
    output_pdf = output_dir / "final.pdf"
    raw_pdf.write_bytes(b"%PDF fake")
    cover_work_dirs = []

    class FakeBox:
        width = 612.0
        height = 792.0

    class FakePage:
        mediabox = FakeBox()

        def extract_text(self):
            return ""

    class FakeReader:
        def __init__(self, path):
            self.path = str(path)
            self.pages = [FakePage()]
            self.metadata = {}

    class FakeWriter:
        def __init__(self):
            self.pages = []

        def add_page(self, page):
            self.pages.append(page)

        def add_metadata(self, info):
            pass

        def write(self, handle):
            handle.write(b"%PDF intermediate")

    def fake_make_cover_pdf(cover_image_path, cover_work_dir, **kwargs):
        cover_work_dirs.append(Path(cover_work_dir))
        assert Path(cover_image_path).parent == Path(cover_work_dir)
        cover_pdf = Path(cover_work_dir) / "cover.pdf"
        cover_pdf.write_bytes(b"%PDF cover")
        return str(cover_pdf)

    monkeypatch.setattr(assembler, "PdfReader", FakeReader)
    monkeypatch.setattr(assembler, "PdfWriter", FakeWriter)
    monkeypatch.setattr(assembler, "_make_cover_pdf", fake_make_cover_pdf)
    def fake_embed_missing_fonts(intermediate, output, deadline=None):
        Path(output).write_bytes(Path(intermediate).read_bytes())
        return {}

    monkeypatch.setattr(
        "epub2pdf.core.font_embed.embed_missing_fonts",
        fake_embed_missing_fonts,
    )

    book = assembler.EpubBook(
        title="Book",
        author="Author",
        language="en",
        chapters=[],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    assembler.assemble(
        str(raw_pdf),
        str(output_pdf),
        book,
        cover_image_bytes=b"\xff\xd8\xffcover",
    )

    assert cover_work_dirs
    assert cover_work_dirs[0].parent == render_work_dir
    assert cover_work_dirs[0].name.startswith("cover-")
    assert not list(output_dir.glob("cover-*"))
    assert not list(output_dir.glob(".epub2pdf-cover-*"))
    assert not (render_work_dir / "_cover_image.jpg").exists()
    assert not (render_work_dir / "_cover.html").exists()
    assert not (render_work_dir / "cover.pdf").exists()


def test_rmtree_retry_retries_until_tree_is_removed(monkeypatch):
    attempts = {"count": 0}
    target = Path("tests_tmp/rmtree_retry").resolve()

    def fake_rmtree(path, ignore_errors=True):
        attempts["count"] += 1

    monkeypatch.setattr(assembler.shutil, "rmtree", fake_rmtree)
    monkeypatch.setattr(assembler.Path, "exists", lambda self: attempts["count"] < 3)
    monkeypatch.setattr(assembler.time, "sleep", lambda _: None)

    assembler._rmtree_retry(target)

    assert attempts["count"] == 3


def test_assemble_warns_when_rendered_pdf_misses_chapter_anchor(monkeypatch, capsys):
    work_dir = Path("tests_tmp/assembler_integrity").resolve()
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf = work_dir / "raw.pdf"
    output_pdf = work_dir / "final.pdf"
    raw_pdf.write_bytes(b"%PDF fake")

    class FakePage:
        mediabox = type("Box", (), {"width": 612.0, "height": 792.0})()

        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakeReader:
        def __init__(self, path):
            self.pages = [
                FakePage("EPBPFANCHOR_ch1_EPBPFANCHOR_END body"),
                FakePage("EPBPFEND_DOCUMENT"),
            ]
            self.metadata = {}

    class FakeWriter:
        def __init__(self):
            self.pages = []

        def add_page(self, page):
            self.pages.append(page)

        def add_metadata(self, info):
            pass

        def write(self, handle):
            handle.write(b"%PDF intermediate")

    monkeypatch.setattr(assembler, "PdfReader", FakeReader)
    monkeypatch.setattr(assembler, "PdfWriter", FakeWriter)

    book = assembler.EpubBook(
        title="Book",
        author="Author",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="ch1.xhtml",
                title="Chapter 1",
                content_html="<p>one</p>",
            ),
            EpubChapter(
                id="ch2",
                href="ch2.xhtml",
                title="Chapter 2",
                content_html="<p>two</p>",
            ),
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    def fake_embed_missing_fonts(intermediate, output, deadline=None):
        Path(output).write_bytes(Path(intermediate).read_bytes())
        return {}

    monkeypatch.setattr(
        "epub2pdf.core.font_embed.embed_missing_fonts",
        fake_embed_missing_fonts,
    )

    assembler.assemble(str(raw_pdf), str(output_pdf), book)

    captured = capsys.readouterr()
    assert "WARNING: rendered PDF is missing chapter anchors" in captured.err
    assert "ch2" in captured.err


def test_assemble_fails_when_rendered_pdf_misses_end_marker(monkeypatch):
    work_dir = Path("tests_tmp/assembler_integrity_end").resolve()
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf = work_dir / "raw.pdf"
    output_pdf = work_dir / "final.pdf"
    raw_pdf.write_bytes(b"%PDF fake")

    class FakePage:
        mediabox = type("Box", (), {"width": 612.0, "height": 792.0})()

        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakeReader:
        def __init__(self, path):
            self.pages = [FakePage("EPBPFANCHOR_ch1_EPBPFANCHOR_END body")]
            self.metadata = {}

    monkeypatch.setattr(assembler, "PdfReader", FakeReader)

    book = assembler.EpubBook(
        title="Book",
        author="Author",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="ch1.xhtml",
                title="Chapter 1",
                content_html="<p>one</p>",
            ),
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    with pytest.raises(assembler.AssembleError) as exc:
        assembler.assemble(str(raw_pdf), str(output_pdf), book)

    assert "rendered PDF is incomplete" in str(exc.value)
    assert "document end marker" in str(exc.value)

def test_anchor_matching_tolerates_spaces_between_characters():
    class FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class FakeReader:
        pages = [
            FakePage("intro"),
            FakePage("E P B P F A N C H O R _ c h 0 1 _ E P B P F A N C H O R _ E N D body"),
        ]

    found = assembler._find_anchor_pages(FakeReader(), {"ch01"})
    assert found == {"ch01": 1}


def test_end_marker_matching_tolerates_spaces_between_characters():
    assert assembler.END_MARKER_RE.search("E P B P F E N D _ D O C U M E N T")


def test_copy_outline_preserves_nesting_and_offsets_pages():
    from io import BytesIO
    from pypdf import PdfReader as RealReader, PdfWriter as RealWriter

    raw_writer = RealWriter()
    for _ in range(3):
        raw_writer.add_blank_page(width=200, height=200)
    top = raw_writer.add_outline_item("Top", 1)
    raw_writer.add_outline_item("Child", 2, parent=top)
    raw_buffer = BytesIO()
    raw_writer.write(raw_buffer)
    raw_buffer.seek(0)
    raw_reader = RealReader(raw_buffer)

    final_writer = RealWriter()
    final_writer.add_blank_page(width=200, height=200)  # cover page
    for _ in range(3):  # body pages copied from the raw PDF
        final_writer.add_blank_page(width=200, height=200)
    count = assembler._copy_outline(final_writer, raw_reader, page_offset=1)
    assert count == 2

    final_buffer = BytesIO()
    final_writer.write(final_buffer)
    final_buffer.seek(0)
    final_reader = RealReader(final_buffer)
    entries = []
    def walk(items, level):
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
            else:
                entries.append((level, item.title, final_reader.get_destination_page_number(item)))
    walk(final_reader.outline, 1)
    assert [(lvl, title) for lvl, title, _ in entries] == [(1, "Top"), (2, "Child")]
    # cover occupies page 0, so raw page 1 -> final page 2, raw page 2 -> final page 3
    assert [page for _, _, page in entries] == [2, 3]

def test_dedupe_title_collapses_exactly_repeated_chromium_titles():
    assert assembler._dedupe_title("Chapter OneChapter One") == "Chapter One"
    assert assembler._dedupe_title("中国社会各阶级的分析 *中国社会各阶级的分析 *") == "中国社会各阶级的分析 *"
    assert assembler._dedupe_title("AlphaBeta") == "AlphaBeta"
    assert assembler._dedupe_title("哈哈哈") == "哈哈哈"

@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\x89PNG\r\n\x1a\nrest", ".png"),
        (b"\xff\xd8\xffrest", ".jpg"),
        (b"GIF89arest", ".gif"),
        (b"RIFF\0\0\0\0WEBPrest", ".webp"),
        (b"BMrest", ".bmp"),
        (b"II*\x00rest", ".tiff"),
        (b"MM\x00*rest", ".tiff"),
        (b"\x00\x00\x01\x00rest", ".ico"),
        (b"\x00\x00\x00\x18ftypavifrest", ".avif"),
        (b"\x00\x00\x00\x18ftypavisrest", ".avif"),
        (b"<?xml version=\"1.0\"?><svg xmlns=\"http://www.w3.org/2000/svg\"/>", ".svg"),
        (b"\xef\xbb\xbf  <svg xmlns=\"http://www.w3.org/2000/svg\"/>", ".svg"),
    ],
)
def test_guess_image_ext_detects_magic_bytes(data, expected):
    assert assembler._guess_image_ext(data) == expected


def test_guess_image_ext_falls_back_to_jpg_for_unknown_bytes():
    assert assembler._guess_image_ext(b"not-an-image") == ".jpg"

def _toc_anchor(anchor_id, title, level, href="chapter.xhtml"):
    from epub2pdf.core.normalizer import TocAnchor

    return TocAnchor(
        title=title,
        level=level,
        href=href,
        fragment="",
        anchor_id=anchor_id,
    )


class _FakeOutlineWriter:
    def __init__(self):
        self.calls = []

    def add_outline_item(self, title, page, parent=None):
        item = object()
        self.calls.append((title, page, parent, item))
        return item


def test_build_outline_from_toc_uses_levels_and_page_offset():
    writer = _FakeOutlineWriter()
    anchors = (
        _toc_anchor("A", "Chapter One", 0),
        _toc_anchor("B", "Section 1.1", 1),
        _toc_anchor("C", "Sub 1.1.1", 2),
        _toc_anchor("D", "Section 1.2", 1),
        _toc_anchor("E", "Chapter Two", 0),
    )
    anchor_pages = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

    count = assembler._build_outline_from_toc(
        writer, anchors, anchor_pages, page_offset=2
    )

    assert count == 5
    titles = [call[0] for call in writer.calls]
    pages = [call[1] for call in writer.calls]
    parents = [call[2] for call in writer.calls]
    items = [call[3] for call in writer.calls]
    assert titles == ["Chapter One", "Section 1.1", "Sub 1.1.1", "Section 1.2", "Chapter Two"]
    assert pages == [2, 3, 4, 5, 6]
    assert parents[0] is None
    assert parents[1] is items[0]
    assert parents[2] is items[1]
    assert parents[3] is items[0]
    assert parents[4] is None


def test_build_outline_from_toc_skips_unresolved_anchors():
    writer = _FakeOutlineWriter()
    anchors = (_toc_anchor("A", "Chapter One", 0), _toc_anchor("Z", "Missing", 0))
    count = assembler._build_outline_from_toc(writer, anchors, {"A": 0})
    assert count == 1
    assert [call[0] for call in writer.calls] == ["Chapter One"]

def test_stamp_page_numbers_skips_cover_and_numbers_the_rest(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=400, height=600)
    pdf = tmp_path / "plain.pdf"
    doc.save(str(pdf))
    doc.close()

    stamped = assembler._stamp_page_numbers(str(pdf), skip_pages=1)
    assert stamped == 2

    opened = fitz.open(str(pdf))
    try:
        assert opened[0].get_text().strip() == ""
        assert "2" in opened[1].get_text()
        assert "3" in opened[2].get_text()
    finally:
        opened.close()


def test_flatten_outline_titles_walks_nested_entries():
    class _Item:
        def __init__(self, title):
            self.title = title

    items = [_Item("A"), [_Item("B"), _Item("C")]]
    assert assembler._flatten_outline_titles(items) == {"A", "B", "C"}
