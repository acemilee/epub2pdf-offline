"""Font embedding for msedge-produced PDFs.

msedge --headless --print-to-pdf creates CID/Type0 font dictionaries with
proper ToUnicode CMaps but **no embedded FontFile2 stream**. This works
on Windows viewers that can resolve the system font by name, but
produces mojibake on any viewer that can't find the font.

This module walks every page's content stream, collects character codes
used by each font, subsets the matching Windows system font while
preserving glyph IDs, and patches the existing PDF font descriptor so it
carries an embedded ``/FontFile2`` stream.

The fix is intentionally non-invasive: the original font dictionaries,
widths, ToUnicode CMaps, encodings, CIDToGIDMap, and content streams stay
unchanged. Only the missing font-file stream is added.
"""
from __future__ import annotations

import io
import os
import re
import time
from pathlib import Path
from typing import Optional

import pikepdf
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTCollection, TTFont


# ---------- Windows font resolution ----------

_WIN_FONT_DIRS = [
    r"C:\Windows\Fonts",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"),
]

# Map mso/sans/serif families to TTF files on a default Windows install.
# Italic / bold variants share the same TTF but have different font names
# in their ``name`` table; we load the same file and let fontTools pick
# the right glyphs via the OS/2 and cmap tables.
_FONT_FILE_HINTS: dict[str, list[str]] = {
    "SegoeUI":              ["segoeui.ttf"],
    "SegoeUI-Bold":         ["segoeui.ttf", "segoeuib.ttf"],
    "SegoeUI-Italic":       ["segoeuii.ttf", "segoeui.ttf"],
    "SegoeUI-BoldItalic":   ["segoeuiz.ttf", "segoeui.ttf"],
    "SegoeUI-Semibold":     ["segoeuisb.ttf", "segoeui.ttf"],
    "SegoeUI-SemiboldItalic": ["segoeuisbi.ttf", "segoeui.ttf"],
    "SegoeUI-Light":        ["segoeuil.ttf"],
    "SegoeUI-Symbol":       ["seguisym.ttf"],
    "MicrosoftYaHei":       ["msyh.ttc"],          # TTC, font index 0
    "MicrosoftYaHei-Bold":  ["msyhbd.ttc", "msyh.ttc"],
    "MicrosoftYaHeiUI":     ["msyh.ttc"],
    "MicrosoftYaHeiUI-Bold":["msyhbd.ttc", "msyh.ttc"],
    "SimSun":               ["simsun.ttc"],
    "NSimSun":              ["simsun.ttc"],
    "Arial":                ["arial.ttf"],
    "Arial-Bold":           ["arialbd.ttf", "arial.ttf"],
    "Arial-Italic":         ["ariali.ttf", "arial.ttf"],
    "Arial-BoldItalic":     ["arialbi.ttf", "arial.ttf"],
    "Calibri":              ["calibri.ttf"],
    "Calibri-Bold":         ["calibrib.ttf", "calibri.ttf"],
    "Calibri-Italic":       ["calibrii.ttf", "calibri.ttf"],
    "Calibri-BoldItalic":   ["calibriz.ttf", "calibri.ttf"],
    "TimesNewRoman":        ["times.ttf"],
    "CourierNew":           ["cour.ttf"],
    "Cambria":              ["cambria.ttc"],
    "Consolas":             ["consola.ttf"],
    "CascadiaCode":         ["cascadia code.ttf", "CascadiaCode.ttf"],
    "CascadiaMono":         ["cascadia mono.ttf", "CascadiaMono.ttf"],
    "CascadiaMono-Regular": ["cascadia mono.ttf", "CascadiaMono.ttf"],
}


def find_system_font(family: str) -> Optional[Path]:
    """Locate a TTF/TTC for the given font family name."""
    hints = _FONT_FILE_HINTS.get(family) or _guess_from_family(family)
    if not hints:
        return None
    for d in _WIN_FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for name in hints:
            p = Path(d) / name
            if p.is_file():
                return p
    return None


def _guess_from_family(family: str) -> list[str]:
    """Best-effort guess at a TTF filename from a family name."""
    base = re.sub(r"[^A-Za-z0-9]+", "", family).lower()
    return [f"{base}.ttf", f"{base}.ttc"]


# ---------- Subsetting ----------

def subset_font_to_bytes(
    font_path: Path,
    gids: set[int],
) -> Optional[bytes]:
    """Subset ``font_path`` to keep only glyphs whose IDs are in ``gids``,
    preserving GID order so the PDF's content stream (which references
    these GIDs via /Identity-H) still renders correctly.

    Returns the serialized TTF bytes, or None on failure.
    """
    try:
        tt = _open_ttfont(font_path)
    except Exception:
        return None

    # Normalize GIDs: ensure 0 (notdef) is always kept
    keep = set(gids) | {0}
    keep.discard(None)
    # fontTools subsetter uses glyph names internally; map GID → name
    name_for_gid = {g: tt.getGlyphName(g) for g in keep if g < len(tt.getGlyphOrder())}

    try:
        options = Options()
        options.layout_features = []            # drop OpenType features
        options.name_IDs = []                   # drop name table IDs we don't need
        options.notdef_glyph = ".notdef"
        options.notdef_outline = True
        options.recalc_bounds = False
        options.retain_gids = True              # ← critical: preserve GIDs
        options.passthrough_tables = False
        options.flavor = None
        subsetter = Subsetter(options=options)
        subsetter.populate(glyphs=set(name_for_gid.values()))
        subsetter.subset(tt)
    except Exception:
        return None

    buf = io.BytesIO()
    try:
        tt.save(buf)
    except Exception:
        return None
    return buf.getvalue()


def _open_ttfont(font_path: Path) -> TTFont:
    """Open either a TTF or the first face in a TTC collection."""
    if font_path.suffix.lower() == ".ttc":
        collection = TTCollection(str(font_path))
        if not collection.fonts:
            raise ValueError(f"empty TTC collection: {font_path}")
        return collection.fonts[0]
    return TTFont(str(font_path))


# ---------- GID extraction from content stream ----------

def collect_gids_for_font(page, font_resource_name: str) -> set[int]:
    """Walk the page's content stream(s) and collect every GID that the
    given font emits via Tj / TJ / ' / " operators.

    CID/Identity-H: each character code in the stream equals a 16-bit
    GID directly. We pull them out as integers.
    """
    gids: set[int] = set()
    try:
        contents = page.get_contents()
    except Exception:
        return gids
    if contents is None:
        return gids

    # contents may be a single stream or a list of streams
    streams = contents if isinstance(contents, list) else [contents]

    # Patterns that introduce text:
    #   (string) Tj         hex/regular string literal
    #   <hex> Tj
    #   [array] TJ          inline arrays
    #   '   (string)'       (move + show)
    #   "                   ditto, with aw/ac
    # We focus on Tj and TJ; they cover >99% of generated content.
    str_lit_re = re.compile(rb"\((?:\\.|[^()\\])*\)\s*Tj")
    hex_lit_re = re.compile(rb"<[0-9A-Fa-f]+>\s*Tj")
    tj_arr_re = re.compile(rb"\[(.*?)\]\s*TJ", re.DOTALL)

    for s in streams:
        try:
            data = s.get_data() or b""
        except Exception:
            continue
        if not data:
            continue

        # Decode regular string literals — extract \xxx octal escapes too
        for m in str_lit_re.finditer(data):
            raw = m.group(0)
            inner = raw[1: raw.rfind(b")")]
            gids.update(_decode_pdf_string_gids(inner))

        # Hex strings — pairs of hex digits = bytes
        for m in hex_lit_re.finditer(data):
            raw = m.group(0)
            inner = raw[1: raw.rfind(b">")]
            try:
                decoded = bytes.fromhex(inner.decode("ascii"))
            except Exception:
                continue
            gids.update(_bytes_to_gids(decoded))

        # TJ arrays — alternating strings and numbers; only strings count
        for m in tj_arr_re.finditer(data):
            inner = m.group(1)
            # Find every parenthesised string OR hex string inside
            for sm in re.finditer(rb"\((?:\\.|[^()\\])*\)", inner):
                gids.update(_decode_pdf_string_gids(sm.group(0)[1:-1]))
            for hm in re.finditer(rb"<[0-9A-Fa-f]+>", inner):
                try:
                    decoded = bytes.fromhex(hm.group(0)[1:-1].decode("ascii"))
                except Exception:
                    continue
                gids.update(_bytes_to_gids(decoded))

    return gids


def collect_gids_for_font_from_content(data: bytes) -> set[int]:
    """Collect GIDs from a decoded PDF content stream.

    This deliberately scans all text-showing strings on the page. It is a
    superset when several fonts share a page, but retaining extra GIDs is
    harmless and far safer than producing an under-subsetted embedded font.
    """
    gids: set[int] = set()
    if not data:
        return gids

    str_lit_re = re.compile(rb"\((?:\\.|[^()\\])*\)\s*Tj")
    hex_lit_re = re.compile(rb"<[0-9A-Fa-f]+>\s*Tj")
    tj_arr_re = re.compile(rb"\[(.*?)\]\s*TJ", re.DOTALL)

    for m in str_lit_re.finditer(data):
        raw = m.group(0)
        inner = raw[1: raw.rfind(b")")]
        gids.update(_decode_pdf_string_gids(inner))

    for m in hex_lit_re.finditer(data):
        raw = m.group(0)
        inner = raw[1: raw.rfind(b">")]
        try:
            decoded = bytes.fromhex(inner.decode("ascii"))
        except Exception:
            continue
        gids.update(_bytes_to_gids(decoded))

    for m in tj_arr_re.finditer(data):
        inner = m.group(1)
        for sm in re.finditer(rb"\((?:\\.|[^()\\])*\)", inner):
            gids.update(_decode_pdf_string_gids(sm.group(0)[1:-1]))
        for hm in re.finditer(rb"<[0-9A-Fa-f]+>", inner):
            try:
                decoded = bytes.fromhex(hm.group(0)[1:-1].decode("ascii"))
            except Exception:
                continue
            gids.update(_bytes_to_gids(decoded))

    return gids


def _decode_pdf_string_gids(raw: bytes) -> set[int]:
    """Decode a PDF literal-string body (between parens) into GIDs."""
    out: set[int] = set()
    i = 0
    while i < len(raw):
        b = raw[i:i + 1]
        if b == b"\\":
            if i + 1 >= len(raw):
                break
            nxt = raw[i + 1:i + 2]
            if nxt in b"nrtbf()\\":
                # Single-byte escapes — emit one byte
                mapping = {b"n": b"\n", b"r": b"\r", b"t": b"\t",
                           b"b": b"\x08", b"f": b"\x0c",
                           b"(": b"(", b")": b")", b"\\": b"\\"}
                out.update(_bytes_to_gids(mapping[nxt]))
                i += 2
                continue
            if nxt.isdigit():
                # Octal escape \ddd (1-3 digits)
                j = i + 1
                while j < len(raw) and j < i + 4 and raw[j:j + 1].isdigit():
                    j += 1
                oct_s = raw[i + 1:j].decode("ascii", errors="ignore")
                try:
                    val = int(oct_s, 8) & 0xFF
                    out.update(_bytes_to_gids(bytes([val])))
                except Exception:
                    pass
                i = j
                continue
            # Unknown escape — skip
            i += 2
            continue
        # Regular byte
        out.update(_bytes_to_gids(b))
        i += 1
    return out


def _bytes_to_gids(data: bytes) -> set[int]:
    """Convert raw bytes to GIDs assuming /Identity-H (UTF-16BE bytes)."""
    out: set[int] = set()
    # Identity-H: each pair of bytes is a 16-bit GID. If length is odd,
    # the trailing byte is treated as a single-byte GID (<256).
    if len(data) >= 2 and len(data) % 2 == 0:
        for i in range(0, len(data), 2):
            g = (data[i] << 8) | data[i + 1]
            if g > 0:
                out.add(g)
    else:
        for b in data:
            if b:
                out.add(b)
    return out


def collect_gids_for_font_pikepdf(page, font_resource_name: str) -> set[int]:
    """Same as ``collect_gids_for_font`` but takes a pikepdf.Page and a
    bare font key (without the leading '/')."""
    contents = page.get("/Contents")
    if contents is None:
        return set()

    data_parts: list[bytes] = []
    streams = contents if isinstance(contents, pikepdf.Array) else [contents]
    for stream in streams:
        try:
            data_parts.append(stream.read_bytes())
        except Exception:
            continue

    return collect_gids_for_font_from_content(b"\n".join(data_parts))


# ---------- PDF patching (pikepdf) ----------

def _family_from_basefont(basefont: str) -> str:
    """``/AAAAAA+SegoeUI-Bold`` → ``SegoeUI-Bold``."""
    s = basefont.lstrip("/")
    if "+" in s:
        s = s.split("+", 1)[1]
    return s


def embed_missing_fonts(input_pdf: str, output_pdf: str, deadline: float | None = None) -> dict:
    """Walk ``input_pdf`` and embed font files into every Type0 font that
    currently lacks a ``/FontFile2`` stream.

    Returns a stats dict: {family: status}.
    """
    def check_timeout() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("conversion timed out during font embedding")

    stats: dict[str, str] = {}
    font_cache: dict[str, Optional[bytes]] = {}

    def _get_subset(family: str, gids: set[int]) -> Optional[bytes]:
        if family in font_cache:
            return font_cache[family]
        path = find_system_font(family)
        if path is None:
            font_cache[family] = None
            return None
        data = subset_font_to_bytes(path, gids)
        font_cache[family] = data
        return data

    with pikepdf.open(input_pdf) as pdf:
        for page in pdf.pages:
            check_timeout()
            try:
                font_dict = page.Resources.get("/Font")
            except (AttributeError, KeyError):
                continue
            if font_dict is None:
                continue

            for font_key in list(font_dict.keys()):
                check_timeout()
                font_ref = font_dict[font_key]
                try:
                    font_obj = font_ref
                except Exception:
                    continue
                if str(font_obj.get("/Subtype")) != "/Type0":
                    continue

                basefont = str(font_obj.get("/BaseFont", ""))
                family = _family_from_basefont(basefont)

                desc_list = font_obj.get("/DescendantFonts")
                if not desc_list:
                    continue

                desc = desc_list[0]
                font_descriptor = desc.get("/FontDescriptor")
                if font_descriptor is None:
                    font_descriptor = pikepdf.Dictionary(
                        Type=pikepdf.Name("/FontDescriptor"),
                        FontName=pikepdf.Name(basefont),
                        Flags=32,
                    )
                    desc.FontDescriptor = font_descriptor
                if font_descriptor.get("/FontFile2") or font_descriptor.get("/FontFile3"):
                    stats[family] = "already-embedded"
                    continue

                gids = collect_gids_for_font_pikepdf(page, font_key)
                if not gids:
                    stats[family] = "no-gids"
                    continue

                subset_bytes = _get_subset(family, gids)
                if subset_bytes is None:
                    stats[family] = "no-system-font"
                    continue

                font_descriptor.FontFile2 = pdf.make_stream(subset_bytes)
                stats[family] = (
                    f"embedded ({len(subset_bytes)} bytes, {len(gids)} gids)"
                )

        pdf.save(output_pdf)
    return stats
