from pathlib import Path
import shutil

import pytest

from epub2pdf import cli
from epub2pdf.core.parser import EpubBook, EpubChapter


def _work_dir(name: str) -> Path:
    path = Path("tests_tmp") / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_convert_passes_total_timeout_to_render_and_assemble(monkeypatch):
    tmp_path = _work_dir("cli_timeout_passes")
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")
    output_path = tmp_path / "book.pdf"
    calls = {}

    book = EpubBook(
        title="Timeout sample",
        author="Tester",
        language="en",
        chapters=[
            EpubChapter(
                id="ch1",
                href="chapter.xhtml",
                title="Chapter",
                content_html="<html><body><p>Hello</p></body></html>",
            )
        ],
        images={},
        fonts={},
        styles={},
        cover_image=None,
        toc=[],
    )

    monkeypatch.setattr(cli.parser, "parse", lambda _: book)

    def fake_normalize(parsed_book, work_dir):
        path = Path(work_dir) / "book.html"
        path.write_text("<html><body>Hello</body></html>", encoding="utf-8")
        return str(path)

    def fake_render(html_path, pdf_path, *, timeout, cancel_check=None):
        calls["render_timeout"] = timeout
        Path(pdf_path).write_bytes(b"%PDF fake")

    def fake_assemble(**kwargs):
        calls["deadline"] = kwargs["deadline"]
        Path(kwargs["output_pdf_path"]).write_bytes(b"%PDF final")
        return 1

    monkeypatch.setattr(cli.normalizer, "normalize", fake_normalize)
    monkeypatch.setattr(cli.renderer, "render", fake_render)
    monkeypatch.setattr(cli.assembler, "assemble", fake_assemble)

    result = cli.convert(
        str(epub_path),
        str(output_path),
        timeout=90,
        quiet=True,
        temp_dir=str(tmp_path / "tmp"),
    )

    assert result == str(output_path.resolve())
    assert 1 <= calls["render_timeout"] <= 90
    assert calls["deadline"] is not None


def test_convert_raises_when_timeout_already_elapsed(monkeypatch):
    tmp_path = _work_dir("cli_timeout_elapsed")
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")

    times = iter([100.0, 100.0, 191.0])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))

    with pytest.raises(cli.ConversionTimeout):
        cli.convert(
            str(epub_path),
            timeout=90,
            quiet=True,
            temp_dir=str(tmp_path / "tmp"),
        )
