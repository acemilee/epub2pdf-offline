from pathlib import Path

import pytest

from epub2pdf import cli
from epub2pdf.core import renderer
from epub2pdf.core.parser import EpubBook, EpubChapter


def test_renderer_cancellation_becomes_conversion_cancelled(monkeypatch, tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")
    book = EpubBook(
        title="Cancel sample",
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

    def fake_normalize(_book, work_dir):
        path = Path(work_dir) / "book.html"
        path.write_text("<html><body>Hello</body></html>", encoding="utf-8")
        return cli.normalizer.NormalizeResult(html_path=str(path))

    def fake_render(html_path, pdf_path, *, timeout, cancel_check=None):
        raise renderer.RendererCancelled("render cancelled by user")

    monkeypatch.setattr(cli.normalizer, "normalize", fake_normalize)
    monkeypatch.setattr(cli.renderer, "render", fake_render)

    with pytest.raises(cli.ConversionCancelled):
        cli.convert(
            str(epub_path),
            quiet=True,
            temp_dir=str(tmp_path / "tmp"),
        )


def test_main_returns_130_on_cancellation(monkeypatch, tmp_path):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")

    def fake_convert(*args, **kwargs):
        raise cli.ConversionCancelled("cancelled by user")

    monkeypatch.setattr(cli, "convert", fake_convert)
    assert cli.main([str(epub_path)]) == 130


def test_main_returns_1_with_hint_on_unexpected_error(monkeypatch, tmp_path, capsys):
    epub_path = tmp_path / "book.epub"
    epub_path.write_bytes(b"fake")

    def fake_convert(*args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(cli, "convert", fake_convert)
    assert cli.main([str(epub_path)]) == 1
    err = capsys.readouterr().err
    assert "disk on fire" in err
    assert "--debug" in err
