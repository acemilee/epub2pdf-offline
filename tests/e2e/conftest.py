"""Shared helpers for end-to-end conversion tests (plan v1.0.1, §3.4)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz", reason="PyMuPDF is required for E2E tests")

from epub2pdf import cli  # noqa: E402
from epub2pdf.core.renderer import find_msedge  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def require_edge():
    if find_msedge() is None:
        pytest.skip("Microsoft Edge is required for E2E tests")


def convert_epub(
    name: str,
    tmp_path: Path,
    *,
    timeout: int = 180,
    **kwargs,
) -> Path:
    """Convert a fixture EPUB into ``tmp_path`` and return the PDF path."""
    source = FIXTURES / name
    assert source.exists(), f"missing fixture: {source}"
    output = tmp_path / f"{Path(name).stem}.pdf"
    result = cli.convert(str(source), str(output), quiet=True, timeout=timeout, **kwargs)
    pdf = Path(result)
    assert pdf.exists(), "conversion did not produce a PDF"
    return pdf


def pdf_doc(pdf_path: Path):
    return fitz.open(str(pdf_path))


def page_texts(doc) -> list[str]:
    return [page.get_text() for page in doc]


def outline_entries(doc) -> list[tuple[int, str, int]]:
    """Return ``[(level, title, page), ...]`` (1-based page numbers)."""
    return [(int(level), str(title), int(page)) for level, title, page in doc.get_toc()]


def outline_titles(doc) -> list[str]:
    return [title for _, title, _ in outline_entries(doc)]


def outline_depth(doc) -> int:
    entries = outline_entries(doc)
    return max((level for level, _, _ in entries), default=0)


def underline_count(page) -> int:
    """Count horizontal line-like drawings (link underlines) on a page."""
    count = 0
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) <= 0.6 and abs(p2.x - p1.x) > 2:
                    count += 1
            elif item[0] == "re":
                rect = item[1]
                if rect.height <= 1.5 and rect.width > 2:
                    count += 1
    return count


def find_page_with_text(doc, needle: str) -> int | None:
    for index, page in enumerate(doc):
        if needle in page.get_text():
            return index
    return None


def find_heading_page(doc, heading: str) -> int | None:
    """Return the first page whose text starts with ``heading``."""
    for index, page in enumerate(doc):
        text = page.get_text().strip()
        if text.startswith(heading):
            return index
    return None


def assert_no_missing_anchors(stderr: str) -> None:
    assert "missing chapter anchors" not in stderr, stderr


def type0_font_embedding_problems(pdf_path: Path) -> list[str]:
    """Return human-readable problems for Type0 fonts missing embedded font files."""
    import pikepdf

    problems: list[str] = []
    with pikepdf.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            resources = page.get("/Resources", {})
            fonts = resources.get("/Font", {}) if resources else {}
            for name, font in fonts.items():
                if str(font.get("/Subtype")) != "/Type0":
                    continue
                base = str(font.get("/BaseFont", "?"))
                descendants = font.get("/DescendantFonts", [])
                if not descendants:
                    problems.append(f"page {page_index}: {name} {base} has no descendant font")
                    continue
                descriptor = descendants[0].get("/FontDescriptor")
                if descriptor is None:
                    problems.append(f"page {page_index}: {name} {base} has no FontDescriptor")
                    continue
                if not any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")):
                    problems.append(f"page {page_index}: {name} {base} has no FontFile*")
    return problems


def assert_type0_fonts_embedded(pdf_path: Path) -> None:
    problems = type0_font_embedding_problems(pdf_path)
    assert not problems, "\n".join(problems)


def copy_fixture(name: str, tmp_path: Path) -> Path:
    target = tmp_path / name
    shutil.copyfile(FIXTURES / name, target)
    return target
