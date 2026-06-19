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
    assert "width:100vw;height:100vh;object-fit:cover;" in html
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
