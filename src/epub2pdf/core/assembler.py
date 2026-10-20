"""Layer 4: PDF Assembler.

Reads the raw PDF produced by msedge, enriches it with:
  - PDF metadata (Title / Author / Producer)
  - A cover page prepended (if a cover image is available)
  - PDF outline (bookmarks) keyed to each chapter
  - Embedded font files for every Type0 font (msedge --print-to-pdf
    creates font dicts that *reference* system fonts but never embed
    the FontFile2 stream, which causes mojibake on any viewer that
    doesn't have Segoe UI / Microsoft YaHei installed)

Bookmark strategy: the renderer asks Chromium for a real PDF outline
(``generateDocumentOutline``); the assembler copies that outline into the final
PDF, preserving heading levels and shifting page numbers past the cover page.
When the raw PDF has no outline (CLI fallback path), the assembler falls back
to locating the invisible ``EPBPFANCHOR_<chapter_id>`` markers embedded by the
normalizer and building a flat outline from them.
"""
from __future__ import annotations

from io import BytesIO
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

import pypdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    RectangleObject,
)

from .normalizer import ANCHOR_PREFIX, ANCHOR_SUFFIX, END_MARKER
from .parser import EpubBook


def _spaced_literal(text: str) -> str:
    """Regex matching ``text`` when Chromium inserts whitespace between glyphs.

    Extracted page text from ``--print-to-pdf`` output can contain the anchor
    marker as ``E P B P F A N C H O R _ …``; the regex must tolerate that.
    """
    return r"\s*".join(re.escape(char) for char in text)


# Same markers as in normalizer. Keep these in sync.
ANCHOR_RE = re.compile(
    _spaced_literal(ANCHOR_PREFIX) + r"([\s\S]{0,200}?)" + _spaced_literal(ANCHOR_SUFFIX)
)
END_MARKER_RE = re.compile(_spaced_literal(END_MARKER))

# Used to pick a built-in CJK font for running heads / labels.
_CJK_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]")
A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378


def _package_version() -> str:
    """Return the package version without importing it eagerly (avoids cycles)."""
    from .. import __version__

    return __version__


# ---------- Errors ----------

class AssembleError(Exception):
    """Failure during PDF post-processing."""


def _rmtree_retry(path: str | Path, attempts: int = 10, delay: float = 0.2) -> None:
    """Remove a temporary tree, retrying around short Windows file locks."""
    target = Path(path)
    for _ in range(attempts):
        shutil.rmtree(target, ignore_errors=True)
        if not target.exists():
            return
        time.sleep(delay)


# ---------- Cover page PDF ----------

def _guess_image_ext(data: bytes, filename: str = "") -> str:
    """Return a file extension (including dot) based on magic bytes.

    Chromium sniffs the payload, so a wrong extension only matters for formats
    it cannot decode at all (SVG/AVIF/TIFF used to be written as ``.jpg`` and
    rendered blank).  TIFF is detected so the caller can warn and skip instead
    of silently producing an empty cover page.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return ".tiff"
    if data.startswith(b"\x00\x00\x01\x00"):
        return ".ico"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return ".avif"
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return ".svg"
    if filename:
        suffix = os.path.splitext(filename)[1].lower()
        if suffix in {
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
            ".svg", ".avif", ".ico", ".tiff", ".tif",
        }:
            return suffix
    return ".jpg"


def _make_cover_pdf(
    cover_image_path: str,
    work_dir: str,
    page_size: tuple[float, float] = (A4_WIDTH_PT, A4_HEIGHT_PT),
    timeout: int = 60,
    fill: str = "contain",
) -> Optional[str]:
    """Render the cover image into a one-page PDF using msedge headless.

    ``fill="contain"`` letterboxes the cover (A4 compatibility mode);
    ``fill="cover"`` fills the whole page like a real book cover, which is what
    the auto trim-size layout wants.

    Returns the path to the generated cover PDF, or None on failure.
    """
    if not cover_image_path or not os.path.isfile(cover_image_path):
        return None
    out_pdf = os.path.join(work_dir, "cover.pdf")
    file_url = Path(cover_image_path).as_uri()
    width_pt, height_pt = page_size
    width_in = width_pt / 72.0
    height_in = height_pt / 72.0

    if fill == "cover":
        img_css = "display:block;width:100%;height:100%;object-fit:cover;"
    else:
        img_css = (
            "display:block;max-width:100%;max-height:100%;width:auto;height:auto;"
            "object-fit:contain;"
        )

    html_path = os.path.join(work_dir, "_cover.html")
    Path(html_path).write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>@page{{size:{width_in:.6f}in {height_in:.6f}in;margin:0;}}"
        "html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}"
        "body{display:flex;align-items:center;justify-content:center;background:#fff;}"
        f"img{{{img_css}}}"
        "</style></head><body>"
        f"<img src='{file_url}'>"
        "</body></html>",
        encoding="utf-8",
    )

    # Import here to avoid circular import
    from .renderer import find_msedge

    edge = find_msedge()
    if not edge:
        return None

    import subprocess
    user_data_dir = Path(work_dir) / f".epub2pdf-edge-{uuid.uuid4().hex}"
    cmd = [
        edge, "--headless=new", "--disable-gpu",
        "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={user_data_dir}",
        "--no-pdf-header-footer", "--no-margins",
        f"--print-to-pdf={out_pdf}",
        Path(html_path).as_uri(),
    ]
    try:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        for _ in range(30):
            if os.path.isfile(out_pdf):
                break
            time.sleep(0.2)
        if not os.path.isfile(out_pdf):
            return None
        return out_pdf
    finally:
        _rmtree_retry(user_data_dir)


# ---------- Outline (bookmarks) ----------

def _page_texts(reader: PdfReader, pdf_path: str | None = None) -> list[str]:
    """Extract every page's text once; all later passes share this list.

    PyMuPDF is ~50x faster than pypdf at text extraction on large books and is
    used when available; pypdf remains the fallback so the dependency stays
    optional.
    """
    if pdf_path:
        try:
            import fitz  # PyMuPDF

            with fitz.open(pdf_path) as doc:
                return [page.get_text() or "" for page in doc]
        except Exception:
            pass
    texts: list[str] = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    return texts


def _build_page_index(page_texts: list[str]) -> dict[str, int]:
    """One pass over all page texts: ``{anchor_id: first_page_index}``.

    Matches both chapter anchors (``EPBPFANCHOR_<chapter id>_...``) and TOC
    anchors (``EPBPFANCHOR_EPBPFTOC_<n>_...``); the same regex is reused so
    there is exactly one marker format in the rendered PDF.
    """
    index: dict[str, int] = {}
    for page_index, text in enumerate(page_texts):
        for match in ANCHOR_RE.finditer(text):
            anchor_id = re.sub(r"\s+", "", match.group(1))
            index.setdefault(anchor_id, page_index)
    return index


def _find_anchor_pages(
    reader: PdfReader,
    anchor_ids: set[str],
    page_texts: list[str] | None = None,
) -> dict[str, int]:
    """Walk page text and return ``{anchor_id: page_index}``.

    Pages are 0-indexed within ``reader.pages``. If a marker isn't found
    (e.g. it was clipped or reformatted by the print engine), it is
    simply omitted from the result.  Chromium sometimes extracts the marker
    with spaces between every character, so the matched id is whitespace
    stripped before comparison.
    """
    if not anchor_ids:
        return {}
    texts = page_texts if page_texts is not None else _page_texts(reader)
    index = _build_page_index(texts)
    return {aid: index[aid] for aid in anchor_ids if aid in index}


def _validate_render_integrity(
    reader: PdfReader,
    book: EpubBook,
    page_texts: list[str] | None = None,
) -> None:
    body_chapters = [ch for ch in book.chapters if not ch.is_cover_only]
    if not body_chapters:
        return

    texts = page_texts if page_texts is not None else _page_texts(reader)
    expected_ids = {ch.id for ch in body_chapters}
    found_ids = set(_find_anchor_pages(reader, expected_ids, page_texts=texts))
    missing = [ch.id for ch in body_chapters if ch.id not in found_ids]
    missing_end = not END_MARKER_RE.search("\n".join(texts))

    if missing_end:
        raise AssembleError(
            "rendered PDF is incomplete; missing document end marker"
        )

    if missing:
        import sys
        print(
            "[assembler] WARNING: rendered PDF is missing chapter anchors: "
            + ", ".join(missing[:10])
            + (" ..." if len(missing) > 10 else ""),
            file=sys.stderr,
        )


def _dedupe_title(title: str) -> str:
    """Collapse an exactly repeated title (``FooFoo`` -> ``Foo``).

    Chromium's ``generateDocumentOutline`` emits the heading text twice for some
    paginated layouts (observed with ``page-break-before`` chapters).  The
    repetition is always exact, so collapsing an exact doubled string restores
    the intended bookmark title.
    """
    length = len(title)
    if length >= 4 and length % 2 == 0:
        half = length // 2
        if title[:half] == title[half:]:
            return title[:half]
    return title


def _copy_outline(
    writer: PdfWriter,
    raw_reader: PdfReader,
    page_offset: int,
) -> int:
    """Copy the raw PDF outline into ``writer``, shifting pages by ``page_offset``.

    Returns the number of outline entries added (0 when the raw PDF has none).
    """
    try:
        entries = raw_reader.outline
    except Exception:
        return 0
    if not entries:
        return 0

    count = 0

    def walk(items, parent) -> None:
        nonlocal count
        last_item = None
        for item in items:
            if isinstance(item, list):
                if last_item is not None:
                    walk(item, last_item)
                continue
            try:
                title = _dedupe_title(str(item.title).strip())
                page = raw_reader.get_destination_page_number(item)
            except Exception:
                last_item = None
                continue
            if not title or page is None or page < 0:
                last_item = None
                continue
            try:
                last_item = writer.add_outline_item(
                    title,
                    page + page_offset,
                    parent=parent,
                )
            except Exception:
                last_item = None
                continue
            count += 1

    walk(entries, None)
    return count


def _build_outline_from_toc(
    writer: PdfWriter,
    toc_anchors,
    anchor_page_index: dict[str, int],
    page_offset: int = 0,
) -> int:
    """Build a nested outline from TOC entries (``outline_source="ncx"``).

    Entry levels come from the EPUB TOC depth; unresolvable entries are
    skipped rather than guessed.  Returns the number of entries added.
    """
    count = 0
    stack: list[tuple[int, object]] = []
    for entry in toc_anchors or ():
        raw_page = anchor_page_index.get(entry.anchor_id)
        title = _dedupe_title(str(entry.title or "").strip())
        if raw_page is None or not title:
            continue
        level = max(0, int(entry.level))
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        try:
            item = writer.add_outline_item(
                title, raw_page + page_offset, parent=parent
            )
        except Exception:
            continue
        stack.append((level, item))
        count += 1
    return count


def _add_outline(
    writer: PdfWriter,
    raw_reader: PdfReader,
    book: EpubBook,
    cover_offset: int = 0,
    page_texts: list[str] | None = None,
) -> None:
    """Fallback flat outline built from the invisible chapter anchors.

    Used only when the raw PDF has no Chromium-generated outline (the CLI
    fallback renderer).  Each entry points to the page where the chapter's
    anchor marker first appears.
    """
    body_chapters = [ch for ch in book.chapters if not ch.is_cover_only]
    if not body_chapters:
        return

    anchor_ids = {ch.id for ch in body_chapters}
    anchor_pages = _find_anchor_pages(raw_reader, anchor_ids, page_texts=page_texts)

    added = 0
    for ch in body_chapters:
        if ch.id not in anchor_pages:
            continue
        page_idx = anchor_pages[ch.id] + cover_offset
        try:
            writer.add_outline_item(ch.title, page_idx)
            added += 1
        except Exception:
            continue

    if added == 0 and body_chapters:
        # Fallback: add a single outline item at the first body page so
        # users at least get a "Contents" entry.
        try:
            writer.add_outline_item("Contents", cover_offset)
        except Exception:
            pass

_SPARSE_OUTLINE_RATIO = 0.35


def _flatten_outline_titles(items) -> set[str]:
    """Collect every bookmark title from pypdf's nested outline structure."""
    titles: set[str] = set()

    def walk(nodes) -> None:
        for node in nodes or ():
            if isinstance(node, list):
                walk(node)
                continue
            title = getattr(node, "title", None)
            if title:
                titles.add(str(title).strip())

    try:
        walk(items)
    except Exception:
        return titles
    return titles


def _supplement_outline(
    writer: PdfWriter,
    raw_reader: PdfReader,
    book: EpubBook,
    page_texts: list[str],
    page_offset: int,
) -> int:
    """Add chapter bookmarks when Chromium's outline is suspiciously sparse.

    Some EPUBs simulate headings with ``<p class="PartStart">`` instead of
    ``h1``-``h6``; Chromium then emits only one or two bookmarks for the whole
    book.  The invisible chapter anchors still know where every chapter
    starts, so those chapters are appended as flat top-level entries.
    """
    body_chapters = [
        ch for ch in book.chapters if not ch.is_cover_only and not ch.is_nav
    ]
    if len(body_chapters) < 3:
        return 0
    existing = _flatten_outline_titles(getattr(writer, "outline", None))
    if len(existing) >= max(3, int(len(body_chapters) * _SPARSE_OUTLINE_RATIO)):
        return 0

    anchor_ids = {ch.id for ch in body_chapters}
    anchor_pages = _find_anchor_pages(raw_reader, anchor_ids, page_texts=page_texts)
    added = 0
    for ch in body_chapters:
        title = _dedupe_title(str(ch.title or "").strip())
        if not title or title in existing:
            continue
        page = anchor_pages.get(ch.id)
        if page is None:
            continue
        try:
            writer.add_outline_item(title, page + page_offset)
        except Exception:
            continue
        existing.add(title)
        added += 1
    return added


def _stamp_page_numbers(
    pdf_path: str,
    *,
    skip_pages: int = 0,
    layout=None,
    deadline: float | None = None,
) -> int:
    """Draw a centered page number in the bottom margin of every page.

    The cover is left unnumbered.  Numbers are the physical PDF page index so
    they stay consistent with the generated table of contents and bookmarks.
    Uses PyMuPDF (already a runtime dependency) and its built-in Helvetica.
    """
    try:
        import fitz  # PyMuPDF
    except ModuleNotFoundError:
        return 0
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return 0

    base_font = float(getattr(layout, "font_size_pt", 11.0) or 11.0)
    font_size = max(7.0, min(9.0, round(base_font * 0.82, 1)))
    bottom_margin = float(getattr(layout, "margin_bottom_pt", 56.7) or 56.7)
    stamped = 0
    try:
        for index in range(max(0, skip_pages), doc.page_count):
            if deadline is not None and time.monotonic() >= deadline:
                raise AssembleError("conversion timed out during page numbering")
            page = doc[index]
            label = str(index + 1)
            try:
                text_width = fitz.get_text_length(
                    label, fontname="helv", fontsize=font_size
                )
            except Exception:
                text_width = font_size * 0.55 * len(label)
            x = (page.rect.width - text_width) / 2.0
            y = page.rect.height - bottom_margin / 2.0 + font_size * 0.35
            try:
                page.insert_text(
                    (x, y),
                    label,
                    fontname="helv",
                    fontsize=font_size,
                    color=(0.35, 0.35, 0.35),
                )
            except Exception:
                continue
            stamped += 1
        if stamped:
            doc.saveIncr()
    finally:
        doc.close()
    return stamped


def _stamp_running_headers(
    pdf_path: str,
    *,
    book_title: str = "",
    chapter_pages: dict[int, str] | None = None,
    skip_pages: int = 0,
    layout=None,
    deadline: float | None = None,
) -> int:
    """Draw a small centered running head in the top margin.

    Paper books carry a running head (book or chapter title); adding a quiet
    grey one is what makes a generated PDF feel typeset instead of printed
    from a browser.  Chapter titles come from the same anchors used for the
    bookmarks, so the header always agrees with the navigation.

    Pages whose content already reaches the top margin (fixed-layout or
    scanned books) are skipped to avoid painting over content.
    """
    try:
        import fitz  # PyMuPDF
    except ModuleNotFoundError:
        return 0
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return 0

    chapter_pages = dict(chapter_pages or {})
    base_font = float(getattr(layout, "font_size_pt", 11.0) or 11.0)
    font_size = max(6.5, min(8.0, round(base_font * 0.72, 1)))
    top_margin = float(getattr(layout, "margin_top_pt", 51.0) or 51.0)
    width_limit = float(getattr(layout, "text_width_pt", 0.0) or 0.0)
    if width_limit <= 0 and doc.page_count:
        width_limit = max(120.0, float(doc[0].rect.width) - 2.0 * top_margin)
    y = max(font_size + 2.0, top_margin / 2.0 + font_size * 0.35)
    stamped = 0
    try:
        for index in range(max(0, skip_pages), doc.page_count):
            if deadline is not None and time.monotonic() >= deadline:
                raise AssembleError("conversion timed out during running headers")
            label = chapter_pages.get(index - skip_pages) or book_title or ""
            label = label.strip()
            if not label:
                continue
            page = doc[index]
            try:
                blocks = [
                    b for b in page.get_text("blocks")
                    if "EPBPFANCHOR" not in str(b[4])
                ]
                content_top = min((b[1] for b in blocks), default=page.rect.height)
            except Exception:
                content_top = page.rect.height
            if content_top < y + font_size:
                continue
            # Chapter opening pages already show the title in large type; a
            # running head there would duplicate it (paper books omit it too).
            heading_text, heading_size = _top_heading(page)
            if (
                heading_text
                and heading_size >= base_font * 1.12
                and _label_matches_heading(label, heading_text)
            ):
                continue
            fontname = "china-s" if _CJK_RE.search(label) else "helv"
            text = _fit_running_head(fitz, label, fontname, font_size, width_limit)
            if not text:
                continue
            try:
                text_width = fitz.get_text_length(
                    text, fontname=fontname, fontsize=font_size
                )
            except Exception:
                text_width = font_size * 0.55 * len(text)
            x = (page.rect.width - text_width) / 2.0
            try:
                page.insert_text(
                    (x, y),
                    text,
                    fontname=fontname,
                    fontsize=font_size,
                    color=(0.45, 0.45, 0.45),
                )
            except Exception:
                continue
            stamped += 1
        if stamped:
            doc.saveIncr()
    finally:
        doc.close()
    return stamped


def _dict_block_text(block) -> str:
    """Plain text of a PyMuPDF ``get_text('dict')`` block."""
    return " ".join(
        "".join(span.get("text", "") for span in line.get("spans", []))
        for line in block.get("lines", [])
    )


def _top_heading(page) -> tuple[str, float]:
    """Return the text and font size of the topmost text block."""
    try:
        blocks = [
            b for b in page.get_text("dict").get("blocks", [])
            if b.get("lines") and "EPBPFANCHOR" not in _dict_block_text(b)
        ]
    except Exception:
        return "", 0.0
    if not blocks:
        return "", 0.0
    blocks.sort(key=lambda b: b["bbox"][1])
    first = blocks[0]
    text = _dict_block_text(first).strip()
    size = max(
        (float(span.get("size", 0.0) or 0.0)
         for line in first["lines"] for span in line.get("spans", [])),
        default=0.0,
    )
    return text, size


def _label_matches_heading(label: str, heading: str) -> bool:
    """True when a running-head label is already the visible heading."""
    def squash(text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    wanted = squash(label)
    return bool(wanted) and squash(heading).startswith(wanted)


def _fit_running_head(fitz, label: str, fontname: str, font_size: float,
                      limit_pt: float) -> str:
    """Trim a running head with an ellipsis so it fits the text column."""

    def measure(text: str) -> float:
        try:
            return fitz.get_text_length(text, fontname=fontname, fontsize=font_size)
        except Exception:
            return font_size * 0.55 * len(text)

    if measure(label) <= limit_pt:
        return label
    trimmed = label
    while trimmed and measure(trimmed + "…") > limit_pt:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else ""


def assemble(
    raw_pdf_path: str,
    output_pdf_path: str,
    book: EpubBook,
    cover_image_bytes: Optional[bytes] = None,
    deadline: float | None = None,
    toc_anchors: tuple = (),
    toc_page_title: str | None = None,
    outline_source: str = "chromium",
    layout=None,
    page_numbers: bool = True,
    running_headers: bool = True,
) -> int:
    """Post-process the msedge-produced PDF.

    Args:
        raw_pdf_path: Path to the PDF written by ``renderer.render``.
        output_pdf_path: Final output PDF path.
        book: The parsed ``EpubBook`` (for metadata + chapters + toc).
        cover_image_bytes: Raw bytes of the cover image, or None.
        toc_anchors: TOC entries (``normalizer.TocAnchor``) for the generated
            table-of-contents pages.  Empty disables the generated TOC.
        toc_page_title: Heading for the generated TOC page; defaults to a
            localized "目录" / "Contents".
        layout: ``layout.Layout`` used for the body; drives cover fill mode and
            TOC scaling.  None keeps the A4/v1.1.1 behaviour.
        page_numbers: Draw physical page numbers in the bottom margin (the
            cover page is left unnumbered).  Default True.

    Returns:
        Page count of the final PDF.
    """
    def check_timeout() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise AssembleError("conversion timed out during PDF assembly")

    def remaining_timeout(default: int) -> int:
        check_timeout()
        if deadline is None:
            return default
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise AssembleError("conversion timed out during PDF assembly")
        return max(1, min(default, remaining))

    check_timeout()
    if not os.path.isfile(raw_pdf_path):
        raise AssembleError(f"raw PDF not found: {raw_pdf_path}")

    Path(os.path.dirname(output_pdf_path) or ".").mkdir(parents=True, exist_ok=True)

    try:
        reader = PdfReader(raw_pdf_path)
    except Exception as e:
        raise AssembleError(f"failed to read raw PDF: {e}") from e
    page_texts = _page_texts(reader, raw_pdf_path)
    _validate_render_integrity(reader, book, page_texts=page_texts)

    writer = PdfWriter()

    # --- Cover page (optional) ---
    # Prefer pre-extracted cover_bytes from parser; fall back to lookup.
    check_timeout()
    cover_bytes = cover_image_bytes
    if cover_bytes is None and book.cover_image:
        cover_basename = os.path.basename(book.cover_image)
        cover_bytes = book.images.get(book.cover_image) \
                      or book.images.get(cover_basename)

    cover_pages: list = []
    if cover_bytes:
        work_dir = os.path.dirname(raw_pdf_path) or "."
        cover_work = os.path.join(work_dir, f"cover-{uuid.uuid4().hex}")
        Path(cover_work).mkdir(parents=True, exist_ok=True)
        # Pick extension based on magic bytes (msedge needs the right mime)
        ext = _guess_image_ext(cover_bytes, book.cover_image or "")
        if ext in (".tiff", ".tif"):
            import sys
            print(
                "[assembler] WARNING: TIFF cover is not supported by Edge; "
                "cover page skipped (convert the cover to PNG/JPEG)",
                file=sys.stderr,
            )
            cover_bytes = None
        cover_stem = "_cover_image"
        cover_path = os.path.join(cover_work, cover_stem + ext)
        try:
            Path(cover_path).write_bytes(cover_bytes)
            body_page_size = (A4_WIDTH_PT, A4_HEIGHT_PT)
            if len(reader.pages) > 0:
                try:
                    box = reader.pages[0].mediabox
                    body_page_size = (float(box.width), float(box.height))
                except Exception:
                    pass
            cover_pdf = _make_cover_pdf(
                cover_path,
                cover_work,
                page_size=body_page_size,
                timeout=remaining_timeout(60),
                fill=(layout.cover_fill if layout is not None else "contain"),
            )
            if cover_pdf and os.path.isfile(cover_pdf):
                cover_reader = PdfReader(BytesIO(Path(cover_pdf).read_bytes()))
                cover_pages = list(cover_reader.pages)
            else:
                print(f"[assembler] WARNING: cover PDF not produced for {cover_path}",
                      file=__import__("sys").stderr)
        finally:
            _rmtree_retry(cover_work)

    # --- Generated table-of-contents pages (optional) ---
    # Rendered with the same headless-Chromium pipeline as the body so the
    # typography matches; page numbers are resolved from the invisible TOC
    # anchors in the raw body PDF.
    toc_pages: list = []
    toc_link_specs: tuple = ()
    if toc_anchors:
        check_timeout()
        toc_work = os.path.join(
            os.path.dirname(raw_pdf_path) or ".", f"toc-{uuid.uuid4().hex}"
        )
        Path(toc_work).mkdir(parents=True, exist_ok=True)
        try:
            from . import toc_page

            body_page_size = (A4_WIDTH_PT, A4_HEIGHT_PT)
            if len(reader.pages) > 0:
                try:
                    box = reader.pages[0].mediabox
                    body_page_size = (float(box.width), float(box.height))
                except Exception:
                    pass
            title = toc_page_title or toc_page.toc_title_for_language(
                book.language
            )
            toc_result = toc_page.render_toc_pdf(
                toc_anchors,
                _build_page_index(page_texts),
                page_width_pt=body_page_size[0],
                page_height_pt=body_page_size[1],
                title=title,
                work_dir=toc_work,
                timeout=remaining_timeout(180),
                cover_pages=len(cover_pages),
                scale=(layout.toc_scale if layout is not None else 1.0),
                left_margin_pt=(layout.margin_left_pt if layout is not None else None),
                right_margin_pt=(layout.margin_right_pt if layout is not None else None),
                top_margin_pt=(layout.margin_top_pt if layout is not None else None),
                bottom_margin_pt=(layout.margin_bottom_pt if layout is not None else None),
            )
            if toc_result.page_count:
                toc_pdf = os.path.join(toc_work, "toc.pdf")
                toc_reader = PdfReader(BytesIO(Path(toc_pdf).read_bytes()))
                toc_pages = list(toc_reader.pages)
                toc_link_specs = toc_result.links
        except AssembleError:
            raise
        except Exception as e:
            import sys
            print(
                f"[assembler] WARNING: generated table of contents skipped: {e}",
                file=sys.stderr,
            )
            toc_pages = []
            toc_link_specs = ()
        finally:
            _rmtree_retry(toc_work)

    # Add pages in order: cover, generated TOC, then body
    check_timeout()
    for p in cover_pages:
        writer.add_page(p)
    toc_writer_pages = []
    for p in toc_pages:
        toc_page = writer.add_page(p)
        # Drop the placeholder links Chromium generated for the local
        # toc.xhtml file; real page destinations are added below.
        if toc_page.get(NameObject("/Annots")) is not None:
            toc_page[NameObject("/Annots")] = ArrayObject()
        toc_writer_pages.append(toc_page)
    for p in reader.pages:
        writer.add_page(p)

    # --- Outline (bookmarks) ---
    # Prefer the outline Chromium generated from the document headings; it
    # keeps heading levels and page numbers accurate. Fall back to the flat
    # anchor-based outline when the CLI renderer produced no outline.
    check_timeout()
    page_offset = len(cover_pages) + len(toc_pages)
    anchor_page_index = _build_page_index(page_texts)
    outline_count = 0
    if outline_source == "ncx" and toc_anchors:
        outline_count = _build_outline_from_toc(
            writer,
            toc_anchors,
            anchor_page_index,
            page_offset=page_offset,
        )
    else:
        try:
            outline_count = _copy_outline(writer, reader, page_offset)
        except Exception:
            outline_count = 0
    if outline_count == 0:
        _add_outline(
            writer,
            reader,
            book,
            cover_offset=page_offset,
            page_texts=page_texts,
        )
    elif outline_source != "ncx":
        # Chromium produced *some* outline, but it may be too sparse for books
        # whose "headings" are styled paragraphs.  Top up with chapter anchors.
        try:
            outline_count += _supplement_outline(
                writer, reader, book, page_texts, page_offset
            )
        except Exception:
            pass

    # --- Clickable TOC rows ---
    if toc_pages and toc_link_specs:
        # pypdf's Link annotation stores the destination as an integer page
        # number; PDF readers expect an explicit page *reference* here, so the
        # annotation is appended by hand (add_annotation rewrites /Dest).
        from pypdf.generic import (
            ArrayObject,
            DictionaryObject,
            NumberObject,
            RectangleObject,
        )

        base = len(cover_pages)
        for spec in toc_link_specs:
            try:
                page = toc_writer_pages[spec.toc_page_index]
                target_ref = writer.pages[spec.target_page_index].indirect_reference
                annotation = DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Annot"),
                        NameObject("/Subtype"): NameObject("/Link"),
                        NameObject("/Rect"): RectangleObject(spec.rect),
                        NameObject("/Border"): ArrayObject([NumberObject(0)] * 3),
                        NameObject("/P"): page.indirect_reference,
                        NameObject("/Dest"): ArrayObject(
                            [target_ref, NameObject("/Fit")]
                        ),
                    }
                )
                ref = writer._add_object(annotation)
                annots = page.get(NameObject("/Annots"))
                if annots is None:
                    page[NameObject("/Annots")] = ArrayObject([ref])
                else:
                    annots.append(ref)
            except Exception:
                continue

    # --- Metadata ---
    check_timeout()
    try:
        producer = f"epub2pdf/{_package_version()} (msedge headless)"
        info = {
            NameObject("/Title"): book.title,
            NameObject("/Author"): book.author,
            NameObject("/Producer"): producer,
            NameObject("/Creator"): producer,
        }
        # Preserve any existing metadata from msedge
        if reader.metadata:
            for k, v in reader.metadata.items():
                if k not in info:
                    info[k] = v
        writer.add_metadata(info)
        # Native PDFs carry the document language and ask viewers to show the
        # title in their window chrome instead of the file name.
        try:
            from pypdf.generic import BooleanObject, TextStringObject

            if book.language:
                writer._root_object.update(
                    {NameObject("/Lang"): TextStringObject(book.language)}
                )
            writer._root_object.update(
                {
                    NameObject("/ViewerPreferences"): DictionaryObject(
                        {NameObject("/DisplayDocTitle"): BooleanObject(True)}
                    )
                }
            )
        except Exception:
            pass
    except Exception as e:
        # Metadata failure should not abort the whole conversion
        import sys
        print(f"[assembler] WARNING: could not write PDF metadata: {e}",
              file=sys.stderr)

    # --- Write intermediate, then run font embedding pass ---
    # pypdf's append_pages_from_reader doesn't expose every font dict
    # cleanly, so we run the embed pass on the just-written file.
    check_timeout()
    intermediate = output_pdf_path + ".fonts.tmp"
    chapter_pages: dict[int, str] = {}
    if running_headers:
        # Fallback titles are file names / manifest ids; never show those in a
        # running head.  Those chapters simply inherit the book title.
        chapter_titles = {
            ch.id: ch.title
            for ch in book.chapters
            if not ch.is_cover_only and not ch.title_is_fallback
        }
        for anchor_id, page_index in anchor_page_index.items():
            title = chapter_titles.get(anchor_id)
            if title:
                chapter_pages.setdefault(page_index, title)
    try:
        with open(intermediate, "wb") as f:
            writer.write(f)
        if page_numbers:
            _stamp_page_numbers(
                intermediate,
                skip_pages=len(cover_pages),
                layout=layout,
                deadline=deadline,
            )
        if running_headers and chapter_pages:
            _stamp_running_headers(
                intermediate,
                book_title=book.title,
                chapter_pages=chapter_pages,
                skip_pages=page_offset,
                layout=layout,
                deadline=deadline,
            )
        try:
            from .font_embed import embed_missing_fonts
        except ModuleNotFoundError as e:
            if e.name == "pikepdf":
                raise AssembleError(
                    "pikepdf is required to embed PDF fonts; install it with "
                    "`pip install pikepdf`"
                ) from e
            raise
        try:
            embed_stats = embed_missing_fonts(intermediate, output_pdf_path, deadline=deadline)
        except TimeoutError as e:
            raise AssembleError(str(e)) from e
    finally:
        try:
            if os.path.isfile(intermediate):
                os.remove(intermediate)
        except OSError:
            pass

    # Surface embed failures as a non-fatal warning
    missing = [fam for fam, st in embed_stats.items()
               if st.startswith("no-system-font")]
    if missing:
        import sys
        print(f"[assembler] WARNING: no system font found for: {missing}",
              file=sys.stderr)

    return len(writer.pages)

