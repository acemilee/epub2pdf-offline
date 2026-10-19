"""Command-line entry point for epub2pdf MVP.

Usage::

    python -m epub2pdf input.epub [-o output.pdf] [--keep-temp] [--no-cover]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Allow running both as `python -m epub2pdf` and as a flat script.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from epub2pdf.core import parser, normalizer, renderer, assembler
else:
    from .core import parser, normalizer, renderer, assembler


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def convert(
    input_path: str,
    output_path: str | None = None,
    *,
    keep_temp: bool = False,
    with_cover: bool = True,
    temp_dir: str | None = None,
    quiet: bool = False,
    timeout: int | None = None,
    progress_cb=None,
    cancel_check=None,
) -> str:
    """Convert one .epub to .pdf. Returns the output path.

    Args:
        progress_cb: Optional callable ``cb(stage: str, percent: int)``.
            ``stage`` is one of: queued, parsing, normalizing, rendering,
            assembling, done, failed. ``percent`` is 0-100.
        cancel_check: Optional callable ``cb() -> bool``. Polled between
            stages and during rendering. If it returns True, raise
            ``ConversionCancelled``.
        timeout: Optional total conversion timeout in seconds. When set,
            the remaining time is passed down to subprocess-based stages.
    """
    def emit(stage, percent):
        if progress_cb:
            try:
                progress_cb(stage, percent)
            except Exception:
                pass

    timeout = timeout if timeout and timeout > 0 else None
    deadline = time.monotonic() + timeout if timeout is not None else None

    def check_cancel():
        if cancel_check and cancel_check():
            raise ConversionCancelled("cancelled by user")
        if deadline is not None and time.monotonic() >= deadline:
            raise ConversionTimeout(f"conversion timed out after {timeout}s")

    def remaining_timeout(default: int) -> int:
        check_cancel()
        if deadline is None:
            return default
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            raise ConversionTimeout(f"conversion timed out after {timeout}s")
        return max(1, min(default, remaining))

    in_path = Path(input_path).resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"input not found: {input_path}")

    if output_path:
        out_path = Path(output_path).resolve()
    else:
        out_path = in_path.with_suffix(".pdf")

    log = (lambda *a, **k: None) if quiet else print
    log(f"input  : {in_path}")
    log(f"output : {out_path}")
    log(f"size   : {_human_size(in_path.stat().st_size)}")

    own_temp = temp_dir is None
    work_root = temp_dir or tempfile.mkdtemp(prefix="epub2pdf_")
    work_dir = os.path.join(work_root, "work")
    os.makedirs(work_dir, exist_ok=True)

    started = time.time()
    timings: dict[str, float] = {}
    stage_started = time.monotonic()

    try:
        check_cancel()
        emit("parsing", 5)

        # ----- Parse -----
        log("[1/4] parsing EPUB ...")
        try:
            book = parser.parse(str(in_path))
        except parser.EpubEncryptedError as e:
            raise RuntimeError(f"DRM-protected: {e}") from e
        except parser.EpubParseError as e:
            raise RuntimeError(f"parse failed: {e}") from e
        log(f"       title={book.title!r}  author={book.author!r}")
        log(f"       chapters={len(book.chapters)}  "
            f"images={len(book.images)}  fonts={len(book.fonts)}  "
            f"css={len(book.styles)}")
        if book.cover_image:
            log(f"       cover  = {book.cover_image}")

        emit("parsing", 25)
        timings["parse"] = time.monotonic() - stage_started

        check_cancel()
        stage_started = time.monotonic()
        # ----- Normalize -----
        log("[2/4] normalizing content ...")
        html_path = normalizer.normalize(book, work_dir)
        html_size = os.path.getsize(html_path)
        log(f"       html = {html_path}  ({_human_size(html_size)})")

        emit("normalizing", 35)
        timings["normalize"] = time.monotonic() - stage_started

        check_cancel()
        stage_started = time.monotonic()
        # ----- Render -----
        log("[3/4] rendering PDF via msedge headless ...")
        raw_pdf = os.path.join(work_dir, "raw.pdf")
        try:
            renderer.render(
                html_path,
                raw_pdf,
                timeout=remaining_timeout(300),
                cancel_check=lambda: bool(cancel_check and cancel_check()),
            )
        except renderer.RendererCancelled as e:
            raise ConversionCancelled("cancelled by user") from e
        log(f"       pdf  = {raw_pdf}  ({_human_size(os.path.getsize(raw_pdf))})")

        emit("rendering", 80)
        timings["render"] = time.monotonic() - stage_started

        check_cancel()
        stage_started = time.monotonic()
        # ----- Assemble -----
        log("[4/4] assembling final PDF ...")
        cover_bytes = None
        if with_cover:
            cover_bytes = book.cover_bytes
            if cover_bytes is None and book.cover_image:
                cover_bytes = book.images.get(book.cover_image)
                if cover_bytes is None:
                    cover_bytes = book.images.get(
                        os.path.basename(book.cover_image)
                    )
        page_count = assembler.assemble(
            raw_pdf_path=raw_pdf,
            output_pdf_path=str(out_path),
            book=book,
            cover_image_bytes=cover_bytes,
            deadline=deadline,
        )
        timings["assemble"] = time.monotonic() - stage_started
        elapsed = time.time() - started
        stage_summary = "  ".join(f"{k}={v:.2f}s" for k, v in timings.items())
        log(f"       stages: {stage_summary}")
        log(f"       done.  pages={page_count}  time={elapsed:.1f}s  "
            f"size={_human_size(out_path.stat().st_size)}")
        emit("done", 100)
        return str(out_path)

    finally:
        if not keep_temp and own_temp:
            shutil.rmtree(work_root, ignore_errors=True)


class ConversionCancelled(Exception):
    """Raised when ``cancel_check`` returns True during conversion."""


class ConversionTimeout(RuntimeError):
    """Raised when conversion exceeds the configured total timeout."""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="epub2pdf",
        description="Offline EPUB → PDF converter (msedge headless)",
    )
    ap.add_argument("input", help="path to input .epub file")
    ap.add_argument("-o", "--output", help="output .pdf path (default: input.pdf)")
    ap.add_argument("--keep-temp", action="store_true",
                    help="keep intermediate work directory")
    ap.add_argument("--no-cover", action="store_true",
                    help="skip cover page insertion")
    ap.add_argument("--quiet", action="store_true", help="suppress progress output")
    ap.add_argument("--timeout", type=int, default=0,
                    help="total conversion timeout in seconds (0 = no total timeout)")
    ap.add_argument("--debug", action="store_true",
                    help="show a full traceback on error")
    args = ap.parse_args(argv)

    try:
        convert(
            args.input,
            args.output,
            keep_temp=args.keep_temp,
            with_cover=not args.no_cover,
            quiet=args.quiet,
            timeout=args.timeout or None,
        )
        return 0
    except ConversionCancelled:
        print("cancelled", file=sys.stderr)
        return 130
    except (FileNotFoundError, RuntimeError, renderer.RendererError,
            assembler.AssembleError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # defensive: never crash with a bare traceback
        if args.debug:
            import traceback
            traceback.print_exc()
        print(f"ERROR: {e} (run with --debug for a traceback)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
