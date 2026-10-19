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
    "TimesNewRoman-Bold":   ["timesbd.ttf", "times.ttf"],
    "TimesNewRoman-Italic": ["timesi.ttf", "times.ttf"],
    "TimesNewRoman-BoldItalic": ["timesbi.ttf", "times.ttf"],
    "CourierNew":           ["cour.ttf"],
    "CourierNew-Bold":      ["courbd.ttf", "cour.ttf"],
    "CourierNew-Italic":    ["couri.ttf", "cour.ttf"],
    "CourierNew-BoldItalic": ["courbi.ttf", "cour.ttf"],
    "Cambria":              ["cambria.ttc"],
    "Consolas":             ["consola.ttf"],
    "CascadiaCode":         ["cascadia code.ttf", "CascadiaCode.ttf"],
    "CascadiaMono":         ["cascadia mono.ttf", "CascadiaMono.ttf"],
    "CascadiaMono-Regular": ["cascadia mono.ttf", "CascadiaMono.ttf"],
}


# PostScript-style family names Chromium/Edge emits in /BaseFont but which do
# not match the friendly family names used by ``_FONT_FILE_HINTS``.
_PS_NAME_ALIASES: dict[str, str] = {
    "ArialMT": "Arial",
    "Arial-BoldMT": "Arial-Bold",
    "Arial-ItalicMT": "Arial-Italic",
    "Arial-BoldItalicMT": "Arial-BoldItalic",
    "TimesNewRomanPSMT": "TimesNewRoman",
    "TimesNewRomanPS-BoldMT": "TimesNewRoman-Bold",
    "TimesNewRomanPS-ItalicMT": "TimesNewRoman-Italic",
    "TimesNewRomanPS-BoldItalicMT": "TimesNewRoman-BoldItalic",
    "CourierNewPSMT": "CourierNew",
    "CourierNewPS-BoldMT": "CourierNew-Bold",
    "CourierNewPS-ItalicMT": "CourierNew-Italic",
    "CourierNewPS-BoldItalicMT": "CourierNew-BoldItalic",
}


def find_system_font(family: str) -> Optional[Path]:
    """Locate a TTF/TTC for the given font family name."""
    family = _PS_NAME_ALIASES.get(family, family)
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


_TF_RE = re.compile(rb"/([^\s/\[\]<>(){}]+)\s+[-+]?[\d.]+\s+Tf")
_SHOW_PATTERNS = (
    re.compile(rb"\((?:\\.|[^()\\])*\)\s*Tj"),
    re.compile(rb"<[0-9A-Fa-f]+>\s*Tj"),
    re.compile(rb"\[(.*?)\]\s*TJ", re.DOTALL),
)


def _gids_for_show_token(token: bytes) -> set[int]:
    """Decode the GIDs of a single text-showing operator token."""
    if token.startswith(b"<"):
        inner = token[1: token.rfind(b">")]
        try:
            return _bytes_to_gids(bytes.fromhex(inner.decode("ascii")))
        except Exception:
            return set()
    if token.startswith(b"["):
        gids: set[int] = set()
        inner = token[1:]
        for sm in re.finditer(rb"\((?:\\.|[^()\\])*\)", inner):
            gids.update(_decode_pdf_string_gids(sm.group(0)[1:-1]))
        for hm in re.finditer(rb"<[0-9A-Fa-f]+>", inner):
            try:
                gids.update(_bytes_to_gids(bytes.fromhex(hm.group(0)[1:-1].decode("ascii"))))
            except Exception:
                continue
        return gids
    inner = token[1: token.rfind(b")")]
    return _decode_pdf_string_gids(inner)


def _collect_gids_by_font_from_content(data: bytes) -> dict[str | None, set[int]]:
    """Map each font resource name (without the leading ``/``) to its GIDs.

    The ``Tf`` operator switches the active font, so a content stream is
    scanned as an ordered event list: each text-showing operator is credited
    to the font that was selected at that point. GIDs seen before any ``Tf``
    are stored under ``None`` and treated as a safe superset by callers.
    """
    if not data:
        return {}

    events: list[tuple[int, str, object]] = []
    for match in _TF_RE.finditer(data):
        events.append((match.start(), "tf", match.group(1).decode("latin-1")))
    for pattern in _SHOW_PATTERNS:
        for match in pattern.finditer(data):
            events.append((match.start(), "show", _gids_for_show_token(match.group(0))))
    events.sort(key=lambda event: event[0])

    current: str | None = None
    result: dict[str | None, set[int]] = {}
    for _position, kind, payload in events:
        if kind == "tf":
            current = str(payload)
        else:
            result.setdefault(current, set()).update(payload)  # type: ignore[arg-type]
    return result


def collect_gids_by_font_resource(page) -> dict[str | None, set[int]]:
    """Collect per-font GIDs from a pikepdf page's content streams."""
    contents = page.get("/Contents")
    if contents is None:
        return {}
    data_parts: list[bytes] = []
    streams = contents if isinstance(contents, pikepdf.Array) else [contents]
    for stream in streams:
        try:
            data_parts.append(stream.read_bytes())
        except Exception:
            continue
    return _collect_gids_by_font_from_content(b"\n".join(data_parts))


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
    """Return the GIDs shown with one font resource on a pikepdf page.

    ``font_resource_name`` may include the leading ``/``; an empty/None value
    returns the union of every font on the page.
    """
    by_font = collect_gids_by_font_resource(page)
    if not font_resource_name:
        union: set[int] = set()
        for gids in by_font.values():
            union |= gids
        return union
    name = str(font_resource_name).lstrip("/")
    return set(by_font.get(name, set())) | set(by_font.get(None, set()))


# ---------- PDF patching (pikepdf) ----------

def _family_from_basefont(basefont: str) -> str:
    """``/AAAAAA+SegoeUI-Bold`` → ``SegoeUI-Bold``."""
    s = basefont.lstrip("/")
    if "+" in s:
        s = s.split("+", 1)[1]
    return s


def _font_obj_key(font_obj) -> tuple:
    """Stable identity for a PDF font object (shared across pages)."""
    try:
        generation = font_obj.objgen
        if generation and generation != (0, 0):
            return ("obj", generation[0], generation[1])
    except Exception:
        pass
    return ("direct", id(font_obj))


def _get_or_create_descriptor(pdf, font_obj, basefont: str):
    desc_list = font_obj.get("/DescendantFonts")
    if not desc_list:
        return None
    desc = desc_list[0]
    descriptor = desc.get("/FontDescriptor")
    if descriptor is None:
        font_name = basefont if basefont.startswith("/") else f"/{basefont or 'Unknown'}"
        descriptor = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/FontDescriptor"),
                FontName=pikepdf.Name(font_name),
                Flags=32,
            )
        )
        desc.FontDescriptor = descriptor
    return descriptor


def embed_missing_fonts(
    input_pdf: str,
    output_pdf: str,
    deadline: float | None = None,
) -> dict:
    """Embed a subset of the matching Windows system font into every Type0
    font that lacks a ``/FontFile2`` stream.

    Phase 1 walks all pages and accumulates the *union* of GIDs each font
    object renders anywhere in the document. Phase 2 subsets each font once
    with that union. Embedding a per-page subset would leave glyphs that first
    appear on later pages blank in other PDF viewers.

    Returns a stats dict: ``{family: status}``.
    """
    def check_timeout() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("conversion timed out during font embedding")

    stats_by_family: dict[str, list[str]] = {}

    with pikepdf.open(input_pdf) as pdf:
        # Phase 1: collect the GID union per font object.
        font_entries: dict[tuple, dict] = {}
        for page in pdf.pages:
            check_timeout()
            try:
                font_dict = page.Resources.get("/Font")
            except (AttributeError, KeyError):
                continue
            if not font_dict:
                continue
            gids_by_font = collect_gids_by_font_resource(page)
            if not gids_by_font:
                continue
            for font_key in list(font_dict.keys()):
                font_obj = font_dict[font_key]
                if str(font_obj.get("/Subtype")) != "/Type0":
                    continue
                font_gids = set(gids_by_font.get(str(font_key).lstrip("/"), set()))
                font_gids |= set(gids_by_font.get(None, set()))
                if not font_gids:
                    continue
                basefont = str(font_obj.get("/BaseFont", ""))
                family = _family_from_basefont(basefont)
                key = _font_obj_key(font_obj)
                entry = font_entries.get(key)
                if entry is None:
                    descriptor = _get_or_create_descriptor(pdf, font_obj, basefont)
                    if descriptor is None:
                        continue
                    already_embedded = any(
                        marker in descriptor
                        for marker in ("/FontFile", "/FontFile2", "/FontFile3")
                    )
                    entry = {
                        "family": family,
                        "descriptor": descriptor,
                        "gids": set(),
                        "embedded": already_embedded,
                    }
                    font_entries[key] = entry
                if not entry["embedded"]:
                    entry["gids"] |= font_gids

        # Phase 2: subset each font once with the union of its GIDs.
        for entry in font_entries.values():
            check_timeout()
            family = entry["family"]
            if entry["embedded"]:
                stats_by_family.setdefault(family, []).append("already-embedded")
                continue
            gids = entry["gids"]
            if not gids:
                stats_by_family.setdefault(family, []).append("no-gids")
                continue
            font_path = find_system_font(family)
            if font_path is None:
                stats_by_family.setdefault(family, []).append("no-system-font")
                continue
            subset_bytes = subset_font_to_bytes(font_path, gids)
            if subset_bytes is None:
                stats_by_family.setdefault(family, []).append("no-system-font")
                continue
            entry["descriptor"].FontFile2 = pdf.make_stream(subset_bytes)
            stats_by_family.setdefault(family, []).append(
                f"embedded ({len(subset_bytes)} bytes, {len(gids)} gids)"
            )

        pdf.save(output_pdf)

    stats: dict[str, str] = {}
    for family, statuses in stats_by_family.items():
        if "no-system-font" in statuses:
            stats[family] = "no-system-font"
        elif "no-gids" in statuses:
            stats[family] = "no-gids"
        elif all(status == "already-embedded" for status in statuses):
            stats[family] = "already-embedded"
        else:
            stats[family] = next(
                status for status in statuses if status.startswith("embedded")
            )
    return stats
