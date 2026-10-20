"""Print layout computation for the generated PDF (plan v1.1.2).

The EPUB format does not record an absolute trim size, but its cover image is
almost always a faithful miniature of the printed book. ``compute_layout``
therefore derives the page *ratio* from the cover (height stays a sane default
of 9.25in) and scales the typographic metrics with the resulting page width:
font size, margins, and TOC geometry. The result is a PDF that reads like the
original book instead of "everything squeezed onto A4".

Everything here is dependency-free: image sizes are parsed from PNG/JPEG/GIF/
WebP/SVG headers, so no Pillow runtime dependency is introduced.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Optional, Tuple


PT_PER_IN = 72.0
MM_TO_PT = PT_PER_IN / 25.4

#: A4, kept byte-for-byte identical to the v1.1.1 print geometry.
A4_WIDTH_PT = 595.275590551
A4_HEIGHT_PT = 841.88976378

#: Default page height for auto layouts. 9.25in (666pt) sits inside the range
#: of common trade hardbacks/paperbacks; combined with the cover ratio this
#: reproduces 6x9, 7x10, and similar trim sizes within a millimetre.
DEFAULT_PAGE_HEIGHT_PT = 9.25 * PT_PER_IN

#: Cover ratios outside this range are treated as "not a book cover" (banners,
#: square images, screenshots) and fall back to A4.
RATIO_MIN = 0.58
RATIO_MAX = 0.86

MIN_FONT_PT = 9.0
MAX_FONT_PT = 13.0
CHARS_PER_LINE = 40.0

_LINE_HEIGHT_CJK = 1.55
_LINE_HEIGHT_LATIN = 1.40
_LINE_HEIGHT_A4 = 1.5

#: Relative margins of the auto layout, as a fraction of page width/height.
MARGIN_LEFT_RATIO = 0.115
MARGIN_RIGHT_RATIO = 0.115
MARGIN_TOP_RATIO = 0.08
MARGIN_BOTTOM_RATIO = 0.09

FONT_SCALES = {
    "auto": 1.0,  # follow the computed 40-chars-per-line size
    "compact": 0.92,
    "normal": 1.0,
    "loose": 1.10,
}

PAGE_SIZE_PRESETS: dict[str, Tuple[float, float]] = {
    "A4": (A4_WIDTH_PT, A4_HEIGHT_PT),
    "LETTER": (612.0, 792.0),
    "B5": (176.0 * MM_TO_PT, 250.0 * MM_TO_PT),
    "6X9": (6.0 * PT_PER_IN, 9.0 * PT_PER_IN),
    "7X10": (7.0 * PT_PER_IN, 10.0 * PT_PER_IN),
}

_CJK_LANG_PREFIXES = ("zh", "ja", "ko")


class LayoutError(ValueError):
    """Raised for an invalid explicit page size / font scale."""


@dataclass(frozen=True)
class Layout:
    """Computed print geometry and typography."""

    page_width_pt: float
    page_height_pt: float
    margin_left_pt: float
    margin_right_pt: float
    margin_top_pt: float
    margin_bottom_pt: float
    font_size_pt: float
    line_height: float
    toc_scale: float
    cover_fill: str  # "cover" (full bleed) or "contain" (letterboxed)
    mode: str  # "auto" | "explicit"
    source: str  # e.g. "auto:790x990", "A4", "A4-fallback"
    warning: Optional[str] = None

    @property
    def text_width_pt(self) -> float:
        return self.page_width_pt - self.margin_left_pt - self.margin_right_pt

    @property
    def css_page_size(self) -> str:
        return f"{self.page_width_pt:.2f}pt {self.page_height_pt:.2f}pt"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _is_cjk(language: str) -> bool:
    lang = (language or "").strip().lower()
    return any(lang.startswith(prefix) for prefix in _CJK_LANG_PREFIXES)


# ---------- image dimension sniffing ----------


def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    pos = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while pos + 9 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if marker in sof_markers:
            height = struct.unpack(">H", data[pos + 5 : pos + 7])[0]
            width = struct.unpack(">H", data[pos + 7 : pos + 9])[0]
            return int(width), int(height)
        pos += 2 + length
    return None


def _gif_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return int(width), int(height)


def _webp_size(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    fourcc = data[12:16]
    if fourcc == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if fourcc == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if fourcc == b"VP8L" and data[20:21] == b"\x2f":
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def _svg_size(data: bytes) -> Optional[Tuple[int, int]]:
    head = data[:4096].decode("utf-8", errors="ignore")
    # Skip an optional XML declaration / doctype before the root <svg> element.
    start = head.lower().find("<svg")
    if start < 0:
        return None
    end = head.find(">", start)
    root = head[start:end + 1] if end >= 0 else head[start:]

    def _length(value: str) -> Optional[float]:
        value = value.strip()
        match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(px)?$", value, re.IGNORECASE)
        return float(match.group(1)) if match else None

    width = height = None
    match = re.search(r'\bwidth\s*=\s*["\']([^"\']+)["\']', root)
    if match:
        width = _length(match.group(1))
    match = re.search(r'\bheight\s*=\s*["\']([^"\']+)["\']', root)
    if match:
        height = _length(match.group(1))
    if width and height:
        return int(round(width)), int(round(height))
    match = re.search(r'\bviewBox\s*=\s*["\']([^"\']+)["\']', root)
    if match:
        parts = re.split(r"[,\s]+", match.group(1).strip())
        if len(parts) == 4:
            try:
                vb_w, vb_h = float(parts[2]), float(parts[3])
            except ValueError:
                return None
            if vb_w > 0 and vb_h > 0:
                return int(round(vb_w)), int(round(vb_h))
    return None


def image_dimensions(data: Optional[bytes]) -> Optional[Tuple[int, int]]:
    """Return ``(width, height)`` in pixels for a supported image, else None."""
    if not data:
        return None
    for sniffer in (_png_size, _jpeg_size, _gif_size, _webp_size, _svg_size):
        try:
            size = sniffer(data)
        except (struct.error, IndexError, ValueError):
            size = None
        if size and size[0] > 0 and size[1] > 0:
            return size
    return None


# ---------- layout construction ----------


def _a4_layout(*, mode: str, source: str, warning: Optional[str] = None) -> Layout:
    margin_lr = 16.0 * MM_TO_PT
    margin_top = 18.0 * MM_TO_PT
    margin_bottom = 20.0 * MM_TO_PT
    return Layout(
        page_width_pt=A4_WIDTH_PT,
        page_height_pt=A4_HEIGHT_PT,
        margin_left_pt=round(margin_lr, 3),
        margin_right_pt=round(margin_lr, 3),
        margin_top_pt=round(margin_top, 3),
        margin_bottom_pt=round(margin_bottom, 3),
        font_size_pt=11.0,
        line_height=_LINE_HEIGHT_A4,
        toc_scale=1.0,
        cover_fill="contain",
        mode=mode,
        source=source,
        warning=warning,
    )


def _scaled_layout(
    width_pt: float,
    height_pt: float,
    *,
    font_scale: str,
    language: str,
    mode: str,
    source: str,
    cover_fill: str,
) -> Layout:
    if font_scale not in FONT_SCALES:
        raise LayoutError(
            f"unknown font scale: {font_scale!r} (expected one of {', '.join(FONT_SCALES)})"
        )
    margin_left = round(MARGIN_LEFT_RATIO * width_pt, 2)
    margin_right = round(MARGIN_RIGHT_RATIO * width_pt, 2)
    margin_top = round(MARGIN_TOP_RATIO * height_pt, 2)
    margin_bottom = round(MARGIN_BOTTOM_RATIO * height_pt, 2)
    text_width = width_pt - margin_left - margin_right
    base_font = text_width / CHARS_PER_LINE
    font_size = round(_clamp(base_font * FONT_SCALES[font_scale], MIN_FONT_PT, MAX_FONT_PT), 2)
    return Layout(
        page_width_pt=round(width_pt, 2),
        page_height_pt=round(height_pt, 2),
        margin_left_pt=margin_left,
        margin_right_pt=margin_right,
        margin_top_pt=margin_top,
        margin_bottom_pt=margin_bottom,
        font_size_pt=font_size,
        line_height=_LINE_HEIGHT_CJK if _is_cjk(language) else _LINE_HEIGHT_LATIN,
        toc_scale=round(font_size / 11.0, 4),
        cover_fill=cover_fill,
        mode=mode,
        source=source,
    )


def compute_layout(
    *,
    cover_size: Optional[Tuple[int, int]] = None,
    cover_bytes: Optional[bytes] = None,
    page_size: str = "auto",
    page_height_pt: Optional[float] = None,
    font_scale: str = "auto",
    language: str = "",
) -> Layout:
    """Compute the print layout for one book.

    ``page_size="auto"`` (default) derives the page ratio from the cover and
    falls back to A4 when no usable cover exists. Any key of
    :data:`PAGE_SIZE_PRESETS` requests an explicit page size; ``A4`` keeps the
    exact v1.1.1 geometry/typography for backward compatibility.
    """
    if cover_size is None and cover_bytes is not None:
        cover_size = image_dimensions(cover_bytes)

    requested = (page_size or "auto").strip()
    if requested.lower() == "auto":
        ratio = None
        if cover_size and cover_size[0] > 0 and cover_size[1] > 0:
            ratio = cover_size[0] / cover_size[1]
        height_pt = float(page_height_pt or DEFAULT_PAGE_HEIGHT_PT)
        if ratio is not None and RATIO_MIN <= ratio <= RATIO_MAX:
            width_pt = height_pt * ratio
            return _scaled_layout(
                width_pt,
                height_pt,
                font_scale=font_scale,
                language=language,
                mode="auto",
                source=f"auto:{cover_size[0]}x{cover_size[1]}",
                cover_fill="cover",
            )
        reason = (
            "no usable cover image"
            if ratio is None
            else f"cover ratio {ratio:.3f} outside {RATIO_MIN:.2f}-{RATIO_MAX:.2f}"
        )
        return _a4_layout(
            mode="auto",
            source="A4-fallback",
            warning=f"page size auto fallback to A4: {reason}",
        )

    preset = PAGE_SIZE_PRESETS.get(requested.upper())
    if preset is None:
        raise LayoutError(
            f"unknown page size: {page_size!r} (expected auto, {', '.join(PAGE_SIZE_PRESETS)})"
        )
    if requested.upper() == "A4":
        return _a4_layout(mode="explicit", source="A4")
    width_pt, height_pt = preset
    return _scaled_layout(
        width_pt,
        height_pt,
        font_scale=font_scale,
        language=language,
        mode="explicit",
        source=requested.upper(),
        cover_fill="contain",
    )


def layout_for_book(book, *, page_size: str = "auto", page_height_pt: Optional[float] = None,
                    font_scale: str = "auto") -> Layout:
    """Convenience wrapper: compute a layout from a parsed :class:`EpubBook`."""
    return compute_layout(
        cover_bytes=getattr(book, "cover_bytes", None),
        page_size=page_size,
        page_height_pt=page_height_pt,
        font_scale=font_scale,
        language=getattr(book, "language", "") or "",
    )


#: The legacy A4 layout, handy for tests/back-compat imports.
A4_LAYOUT = _a4_layout(mode="explicit", source="A4")
