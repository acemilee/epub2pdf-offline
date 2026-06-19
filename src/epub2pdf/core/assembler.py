"""Layer 4: PDF Assembler.

Reads the raw PDF produced by msedge, enriches it with:
  - PDF metadata (Title / Author / Producer)
  - A cover page prepended (if a cover image is available)
  - PDF outline (bookmarks) keyed to each chapter
  - Embedded font files for every Type0 font (msedge --print-to-pdf
    creates font dicts that *reference* system fonts but never embed
    the FontFile2 stream, which causes mojibake on any viewer that
    doesn't have Segoe UI / Microsoft YaHei installed)

Bookmark strategy: the normalizer injects an invisible span with a
unique marker ``EPBPFANCHOR_<chapter_id>`` at the top of every chapter.
The assembler's ``_find_anchor_pages`` walks the rendered PDF text
stream and locates which page each marker lands on, then calls
``writer.add_outline_item`` to register a top-level entry.
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
    DecodedStreamObject,
    NameObject,
    RectangleObject,
)

from .normalizer import ANCHOR_SUFFIX, END_MARKER
from .parser import EpubBook

# Same prefix as in normalizer. Keep these in sync.
ANCHOR_RE = re.compile(
    r"EPBPFANCHOR_(.*?)" + re.escape(ANCHOR_SUFFIX)
)
A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378


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

def _guess_image_ext(data: bytes) -> str:
    """Return a file extension (including dot) based on magic bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    # Fall back to original filename hint if it has one
    return ".jpg"


def _make_cover_pdf(
    cover_image_path: str,
    work_dir: str,
    page_size: tuple[float, float] = (A4_WIDTH_PT, A4_HEIGHT_PT),
    timeout: int = 60,
) -> Optional[str]:
    """Render the cover image into a one-page PDF using msedge headless.

    Returns the path to the generated cover PDF, or None on failure.
    """
    if not cover_image_path or not os.path.isfile(cover_image_path):
        return None
    out_pdf = os.path.join(work_dir, "cover.pdf")
    file_url = Path(cover_image_path).as_uri()
    width_pt, height_pt = page_size
    width_in = width_pt / 72.0
    height_in = height_pt / 72.0

    # Use a minimal A4 HTML page that fills the page with the cover image.
    html_path = os.path.join(work_dir, "_cover.html")
    Path(html_path).write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>@page{{size:{width_in:.6f}in {height_in:.6f}in;margin:0;}}"
        "html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;}"
        "body{display:block;}"
        "img{display:block;width:100vw;height:100vh;object-fit:cover;"
        "object-position:center center;}"
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

def _find_anchor_pages(reader: PdfReader, anchor_ids: set[str]) -> dict[str, int]:
    """Walk every page's text and return ``{anchor_id: page_index}``.

    Pages are 0-indexed within ``reader.pages``. If a marker isn't found
    (e.g. it was clipped or reformatted by the print engine), it is
    simply omitted from the result.
    """
    if not anchor_ids:
        return {}
    found: dict[str, int] = {}
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        for m in ANCHOR_RE.finditer(text):
            cid = m.group(1)
            if cid in anchor_ids and cid not in found:
                found[cid] = i
        if len(found) == len(anchor_ids):
            break  # all anchors located
    return found


def _extract_pdf_text(reader: PdfReader) -> str:
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts)


def _validate_render_integrity(reader: PdfReader, book: EpubBook) -> None:
    body_chapters = [ch for ch in book.chapters if not ch.is_cover_only]
    if not body_chapters:
        return

    expected_ids = {ch.id for ch in body_chapters}
    found_ids = set(_find_anchor_pages(reader, expected_ids))
    missing = [ch.id for ch in body_chapters if ch.id not in found_ids]
    text = _extract_pdf_text(reader)
    missing_end = END_MARKER not in text

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


def _add_outline(
    writer: PdfWriter,
    raw_reader: PdfReader,
    book: EpubBook,
    cover_offset: int = 0,
) -> None:
    """Build a flat outline: top-level chapter entries, no nesting.

    Each chapter's title points to the page where its anchor marker
    first appears in ``raw_reader`` (offset by ``cover_offset``).
    """
    body_chapters = [ch for ch in book.chapters if not ch.is_cover_only]
    if not body_chapters:
        return

    anchor_ids = {ch.id for ch in body_chapters}
    anchor_pages = _find_anchor_pages(raw_reader, anchor_ids)

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

def assemble(
    raw_pdf_path: str,
    output_pdf_path: str,
    book: EpubBook,
    cover_image_bytes: Optional[bytes] = None,
    deadline: float | None = None,
) -> int:
    """Post-process the msedge-produced PDF.

    Args:
        raw_pdf_path: Path to the PDF written by ``renderer.render``.
        output_pdf_path: Final output PDF path.
        book: The parsed ``EpubBook`` (for metadata + chapters + toc).
        cover_image_bytes: Raw bytes of the cover image, or None.

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
    _validate_render_integrity(reader, book)

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
        ext = _guess_image_ext(cover_bytes)
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
            )
            if cover_pdf and os.path.isfile(cover_pdf):
                cover_reader = PdfReader(BytesIO(Path(cover_pdf).read_bytes()))
                cover_pages = list(cover_reader.pages)
            else:
                print(f"[assembler] WARNING: cover PDF not produced for {cover_path}",
                      file=__import__("sys").stderr)
        finally:
            _rmtree_retry(cover_work)

    # Add pages in order: cover first (if any), then body
    check_timeout()
    for p in cover_pages:
        writer.add_page(p)
    for p in reader.pages:
        writer.add_page(p)

    # --- Outline (bookmarks) ---
    check_timeout()
    cover_offset = len(cover_pages)
    _add_outline(writer, reader, book, cover_offset=cover_offset)

    # --- Metadata ---
    check_timeout()
    try:
        producer = "epub2pdf/1.0.0 (msedge headless)"
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
    except Exception as e:
        # Metadata failure should not abort the whole conversion
        pass

    # --- Write intermediate, then run font embedding pass ---
    # pypdf's append_pages_from_reader doesn't expose every font dict
    # cleanly, so we run the embed pass on the just-written file.
    check_timeout()
    intermediate = output_pdf_path + ".fonts.tmp"
    try:
        with open(intermediate, "wb") as f:
            writer.write(f)
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
