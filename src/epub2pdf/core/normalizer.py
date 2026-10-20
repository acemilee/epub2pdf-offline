"""Layer 2: Content Normalizer.

Takes an ``EpubBook`` and produces:
  - a single self-contained HTML file with all chapters concatenated
  - all images / fonts written to a sibling ``assets/`` and ``fonts/`` directory
  - injected print CSS (page-break, font fallback, page margins)

The HTML is rendered later by ``renderer.py`` via msedge headless.
"""
from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import unquote

from lxml import html as lxml_html

from .layout import A4_LAYOUT, Layout, layout_for_book
from .parser import EpubBook, EpubChapter


# Anchor marker prefix used to locate each chapter in the rendered PDF.
# We embed this invisible span at the top of every chapter so the
# assembler can later search the PDF text stream and assign page numbers.
ANCHOR_PREFIX = "EPBPFANCHOR_"
ANCHOR_SUFFIX = "_EPBPFANCHOR_END"
END_MARKER = "EPBPFEND_DOCUMENT"


@dataclass(frozen=True)
class TocAnchor:
    """One TOC entry anchored inside the generated HTML.

    ``anchor_id`` is rendered as ``EPBPFANCHOR_<anchor_id>_EPBPFANCHOR_END``
    so the assembler's existing anchor regex finds it without a second
    pattern; ``level`` is the 0-based depth in the EPUB TOC tree.
    """

    title: str
    level: int
    href: str
    fragment: str
    anchor_id: str


@dataclass(frozen=True)
class NormalizeResult:
    """Result of :func:`normalize`."""

    html_path: str
    toc_anchors: tuple[TocAnchor, ...] = ()
    layout: Layout | None = None


# ---------- Print CSS ----------

_PRINT_CSS_TEMPLATE = """
/* Page setup */
@page { size: __PAGE_SIZE__; margin: __MARGIN_BOX__; }
@page :first { margin-top: 0; }

/* Base typography */
html { font-size: __FONT_SIZE__; }
body {
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC",
                 "Hiragino Sans", "Noto Sans CJK SC", "Noto Sans",
                 Arial, sans-serif;
    line-height: __LINE_HEIGHT__;
    color: #1a1a1a;
    text-align: justify;
    hyphens: auto;
}

/* Chapter breaks — each chapter starts on a new page */
.chapter {
    page-break-before: always;
    break-before: page;
}
.chapter:first-of-type {
    page-break-before: avoid;
    break-before: auto;
}

/* Headings */
h1, h2, h3, h4, h5, h6 {
    page-break-after: avoid;
    break-after: avoid;
    font-weight: 600;
    line-height: 1.25;
    margin-top: 0.6em;
    margin-bottom: 0.4em;
}
h1 { font-size: 1.8em; margin-top: 0; }
h2 { font-size: 1.4em; }
h3 { font-size: 1.2em; }
.chapter-title.synthetic {
    margin-bottom: 0.8em;
}
.chapter-title.synthetic.nav-title {
    font-size: 1.4em;
}

/* Paragraphs */
p { margin: 0 0 0.7em 0; orphans: 3; widows: 3; }

/* Images */
img { max-width: 100%; height: auto; page-break-inside: avoid; }

/* Avoid splitting tables and figure-like blocks */
table, figure, blockquote {
    page-break-inside: avoid;
}
pre, code {
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 0.9em;
    line-height: 1.2;
}
pre {
    page-break-inside: auto;
    break-inside: auto;
}

/* Cover page */
.cover-page {
    page-break-after: always;
    break-after: page;
    text-align: center;
}
.cover-page img {
    max-height: 100%;
    max-width: 100%;
    object-fit: __COVER_FIT__;
}
"""

_POST_EPUB_CSS_TEMPLATE = """
/* Links are not clickable in the printed PDF. EPUB stylesheets (and the UA
   default for <a>) would otherwise keep the HTML link underline + link color,
   which makes generated TOC/nav pages look like a web page instead of print.
   This rule is emitted after the inlined EPUB CSS on purpose. */
a, a:link, a:visited, a:hover, a:active {
    color: inherit !important;
    text-decoration: none !important;
}

/* EPUB CSS sometimes forces chapter h1 elements onto a new page. The
   outer .chapter section already owns the page break, so suppress only
   the first heading inside each normalized chapter wrapper. */
.chapter > h1.chapter-title.synthetic,
.chapter h1:first-child,
.chapter h2:first-child,
.chapter > section:first-of-type > h1:first-child,
.chapter > section:first-of-type > h2:first-child,
.chapter > div:first-of-type > section:first-of-type > h1:first-child,
.chapter > div:first-of-type > section:first-of-type > h2:first-child,
.chapter > div:first-of-type > nav:first-of-type > h1:first-child {
    page-break-before: avoid !important;
    break-before: auto !important;
}

/* Final page-box guard (v1.1.1). EPUB CSS can carry @page { margin: 0 }
   (InDesign export); the sanitizer removes those rules, but this declaration
   is emitted last so our computed print box wins even if one slipped
   through. */
@page { size: __PAGE_SIZE__; margin: __MARGIN_BOX__; }
@page :first { margin-top: 0; }
"""


def _margin_box(layout: "Layout") -> str:
    return (
        f"{layout.margin_top_pt:.2f}pt {layout.margin_right_pt:.2f}pt "
        f"{layout.margin_bottom_pt:.2f}pt {layout.margin_left_pt:.2f}pt"
    )


def _build_print_css(layout: "Layout") -> str:
    """Render the print stylesheet for *layout* (v1.1.2)."""
    return (
        _PRINT_CSS_TEMPLATE
        .replace("__PAGE_SIZE__", layout.css_page_size)
        .replace("__MARGIN_BOX__", _margin_box(layout))
        .replace("__FONT_SIZE__", f"{layout.font_size_pt:.2f}pt")
        .replace("__LINE_HEIGHT__", f"{layout.line_height:g}")
        .replace("__COVER_FIT__", layout.cover_fill)
    )


def _build_post_epub_css(layout: "Layout") -> str:
    """Render the post-EPUB guard stylesheet for *layout* (v1.1.2)."""
    return (
        _POST_EPUB_CSS_TEMPLATE
        .replace("__PAGE_SIZE__", layout.css_page_size)
        .replace("__MARGIN_BOX__", _margin_box(layout))
    )


#: Legacy A4 stylesheets (kept for backwards-compatible imports).
PRINT_CSS = _build_print_css(A4_LAYOUT)
POST_EPUB_CSS = _build_post_epub_css(A4_LAYOUT)


# ---------- Helpers ----------

def _safe_basename(href: str) -> str:
    """Take basename and decode URL escapes; strip query/fragment."""
    href = unquote(href.split("?", 1)[0].split("#", 1)[0])
    return os.path.basename(href.replace("\\", "/"))


def _clean_href(href: str) -> str:
    href = unquote((href or "").split("?", 1)[0].split("#", 1)[0])
    return href.replace("\\", "/").lstrip("/")


def _resolve_href(base_href: str, href: str) -> str:
    href = _clean_href(href)
    if not href or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
        return href
    if href.startswith("/"):
        return posixpath.normpath(href.lstrip("/"))
    base_dir = posixpath.dirname(_clean_href(base_href))
    return posixpath.normpath(posixpath.join(base_dir, href))


def _strip_xml_declaration(html_text: str) -> str:
    """Remove an XML declaration before passing Unicode text to lxml."""
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", html_text, count=1, flags=re.IGNORECASE)


def _local_name(elem) -> str:
    """Return an element's tag local-name, tolerant of XHTML namespaces."""
    tag = getattr(elem, "tag", "")
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _clean_text_artifacts(html_text: str) -> str:
    """Normalize whitespace artifacts that commonly become visible mojibake.

    Many EPUB generators use NBSP for indentation. In the browser this looks
    like a regular space, but downstream PDF text extraction/viewers can expose
    UTF-8 NBSP bytes as ``Â``. We do not need non-breaking behavior for the PDF
    layout here, so normalize it early.
    """
    html_text = html_text.replace("\u00c2\u00a0", " ")
    html_text = re.sub(
        r"\u00c2(?=(?:\s|&nbsp;|&#160;|&#x0*a0;))",
        "",
        html_text,
        flags=re.IGNORECASE,
    )
    html_text = re.sub(
        r"(?:&nbsp;|&#160;|&#x0*a0;)",
        " ",
        html_text,
        flags=re.IGNORECASE,
    )
    return html_text.replace("\u00a0", " ")


def _plain_text_from_html(html_text: str) -> str:
    cleaned = _strip_xml_declaration(html_text)
    try:
        root = lxml_html.fragment_fromstring(cleaned, create_parent="div")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", cleaned)
    else:
        text = root.text_content()
    text = _clean_text_artifacts(text)
    return re.sub(r"\s+", " ", text).strip()


def _serialize_fragment_children(root) -> str:
    """Serialize a synthetic fragment parent without keeping the wrapper."""
    parts: list[str] = []
    if root.text:
        parts.append(escape(root.text))
    for child in root:
        parts.append(lxml_html.tostring(child, encoding="unicode"))
    return "".join(parts)


def _normalize_title_for_compare(text: str) -> str:
    text = _clean_text_artifacts(text or "")
    # Compare ignoring all whitespace: parser titles join nested elements with
    # spaces while the rendered heading text does not, so whitespace must not
    # make an existing heading look different from the chapter title.
    return re.sub(r"\s+", "", text).lower()


def _first_heading_text(body_inner: str) -> str:
    cleaned = _strip_xml_declaration(body_inner)
    try:
        root = lxml_html.fragment_fromstring(cleaned, create_parent="div")
    except Exception:
        return ""
    for elem in root.iter():
        if _local_name(elem) in {"h1", "h2", "h3"}:
            text = elem.text_content()
            text = _clean_text_artifacts(text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text
    return ""


def _looks_like_internal_title(title: str, ch: EpubChapter) -> bool:
    """Return True for generated ids/filenames that should not be visible."""
    title = _clean_text_artifacts(title or "").strip()
    if not title:
        return True
    if getattr(ch, "title_is_fallback", False):
        return True

    candidates = {
        ch.id,
        ch.href,
        os.path.basename(ch.href.replace("\\", "/")),
        os.path.splitext(os.path.basename(ch.href.replace("\\", "/")))[0],
    }
    slug_title = re.sub(r"[\W_]+", "", title, flags=re.UNICODE).lower()
    for candidate in candidates:
        candidate = _clean_text_artifacts(candidate or "").strip()
        if not candidate:
            continue
        if title.lower() == candidate.lower():
            return True
        slug_candidate = re.sub(r"[\W_]+", "", candidate, flags=re.UNICODE).lower()
        if slug_title and slug_title == slug_candidate:
            return True
    return False


def _should_inject_title(ch: EpubChapter, body_inner: str) -> bool:
    title = _clean_text_artifacts(ch.title or "").strip()
    if _looks_like_internal_title(title, ch):
        return False

    first_heading = _first_heading_text(body_inner)
    if first_heading and _normalize_title_for_compare(first_heading) == _normalize_title_for_compare(title):
        return False

    plain = _plain_text_from_html(body_inner)
    if plain and _normalize_title_for_compare(plain).startswith(_normalize_title_for_compare(title)):
        return False

    return True


def _inject_anchor_after_first_heading(body_inner: str, anchor_html: str) -> tuple[str, bool]:
    """Place the outline marker as a sibling *after* the first real heading.

    The marker must stay outside the heading element: Chromium's
    ``generateDocumentOutline`` derives bookmark titles from the heading's text
    content, so a marker inside the heading pollutes every bookmark title.
    Keeping the marker in-flow (no position:absolute) is still required for the
    fallback path that locates anchors in extracted page text.
    """
    cleaned = _strip_xml_declaration(body_inner)
    try:
        root = lxml_html.fragment_fromstring(cleaned, create_parent="div")
        anchor = lxml_html.fragment_fromstring(anchor_html)
    except Exception:
        return body_inner, False

    for elem in root.iter():
        if _local_name(elem) in {"h1", "h2", "h3"}:
            parent = elem.getparent()
            if parent is None:
                continue
            parent.insert(parent.index(elem) + 1, anchor)
            return _serialize_fragment_children(root), True
    return body_inner, False


def _anchor_span(marker_text: str, element_id: str = "") -> str:
    """Invisible, in-flow span carrying one or more anchor markers."""
    id_attr = f' id="{escape(element_id)}"' if element_id else ""
    return (
        f'<span class="epub-anchor"{id_attr} '
        f'style="display:inline;font-size:1px;line-height:1px;'
        f'color:transparent;height:0;overflow:hidden;">'
        f"{escape(marker_text)}"
        f"</span>"
    )


def _anchor_marker(anchor_id: str) -> str:
    return f"{ANCHOR_PREFIX}{anchor_id}{ANCHOR_SUFFIX}"


def _iter_toc(nodes, level: int = 0):
    """Yield ``(TocNode, depth)`` depth-first."""
    for node in nodes or []:
        yield node, level
        yield from _iter_toc(node.children, level + 1)


def _normalize_href_path(href: str) -> str:
    path = unquote(href.split("#", 1)[0]).strip()
    while path.startswith("./"):
        path = path[2:]
    return posixpath.normpath(path) if path else ""


def _resolve_toc_chapter(book: EpubBook, href: str) -> EpubChapter | None:
    """Map a TOC href to a chapter, tolerating path prefix differences.

    Some EPUB 3 nav documents are generated with ``href="chapter1.html"``
    while the actual chapter file is ``chapter1.xhtml`` (InDesign exports do
    this). Full-path matching fails, so fall back to an extension-insensitive
    stem match, but only when it is unambiguous.
    """
    norm = _normalize_href_path(href)
    if not norm:
        return None
    for ch in book.chapters:
        if _normalize_href_path(ch.href) == norm:
            return ch
    base = posixpath.basename(norm)
    matches = [
        ch for ch in book.chapters
        if posixpath.basename(_normalize_href_path(ch.href)) == base
    ]
    if len(matches) == 1:
        return matches[0]
    stem = posixpath.splitext(base)[0].lower()
    if stem:
        stem_matches = [
            ch for ch in book.chapters
            if posixpath.splitext(
                posixpath.basename(_normalize_href_path(ch.href))
            )[0].lower() == stem
        ]
        if len(stem_matches) == 1:
            return stem_matches[0]
    return None


def _build_toc_anchors(
    book: EpubBook,
) -> tuple[tuple[TocAnchor, ...], dict[str, list[TocAnchor]], int]:
    """Build one :class:`TocAnchor` per resolvable TOC entry.

    Returns ``(anchors, anchors_by_chapter_id, skipped_count)``.
    """
    anchors: list[TocAnchor] = []
    by_chapter: dict[str, list[TocAnchor]] = {}
    skipped = 0
    for node, level in _iter_toc(book.toc):
        href = (node.href or "").strip()
        if not href:
            continue
        chapter = _resolve_toc_chapter(book, href)
        if chapter is None or chapter.is_cover_only:
            skipped += 1
            continue
        fragment = ""
        if "#" in href:
            fragment = unquote(href.split("#", 1)[1]).strip()
        anchor = TocAnchor(
            title=_clean_text_artifacts(node.title or "").strip(),
            level=level,
            href=href,
            fragment=fragment,
            anchor_id=f"EPBPFTOC_{len(anchors) + 1}",
        )
        anchors.append(anchor)
        by_chapter.setdefault(chapter.id, []).append(anchor)
    return tuple(anchors), by_chapter, skipped


def _insert_anchor_after_element(
    body_inner: str,
    target_id: str,
    anchor_html: str,
) -> tuple[str, bool]:
    """Insert ``anchor_html`` right after the element whose id is ``target_id``."""
    if not target_id:
        return body_inner, False
    try:
        root = lxml_html.fragment_fromstring(
            _strip_xml_declaration(body_inner), create_parent="div"
        )
        anchor = lxml_html.fragment_fromstring(anchor_html)
    except Exception:
        return body_inner, False

    target = None
    for elem in root.iter():
        if elem.get("id") == target_id:
            target = elem
            break
    if target is None:
        return body_inner, False
    parent = target.getparent()
    if parent is None:
        return body_inner, False
    parent.insert(parent.index(target) + 1, anchor)
    return _serialize_fragment_children(root), True


def _inject_fragment_anchors(
    body_inner: str,
    anchors: list[TocAnchor],
) -> tuple[str, list[TocAnchor]]:
    """Inject fragment-targeted TOC anchors; return those that failed."""
    failed: list[TocAnchor] = []
    for anchor in anchors:
        body_inner, ok = _insert_anchor_after_element(
            body_inner, anchor.fragment, _anchor_span(_anchor_marker(anchor.anchor_id))
        )
        if not ok:
            failed.append(anchor)
    return body_inner, failed


def _rewrite_relative_paths(
    chapter_html: str,
    chapter_dir: str,
    assets_dir_name: str,
    image_map: dict[str, str] | None = None,
    font_map: dict[str, str] | None = None,
) -> str:
    """Rewrite relative URLs in the chapter HTML so they resolve to the
    assets directory we will write next to the index.html.
    """
    # Keep this as a Unicode string. Passing UTF-8 bytes without an
    # in-fragment charset lets lxml guess Latin-1/Windows-1252 and turns
    # smart quotes / CJK text into mojibake before Edge ever sees it.
    cleaned = _strip_xml_declaration(chapter_html)
    try:
        root = lxml_html.fragment_fromstring(cleaned, create_parent="div")
    except Exception:
        return chapter_html

    image_map = image_map or {}
    unique_basenames: dict[str, str | None] = {}
    for orig_name, out_name in image_map.items():
        basename = _safe_basename(orig_name)
        if not basename:
            continue
        if basename in unique_basenames:
            unique_basenames[basename] = None
        else:
            unique_basenames[basename] = out_name

    def mapped_asset(src: str) -> str:
        resolved = _resolve_href(chapter_dir, src)
        cleaned = _clean_href(src)
        basename = _safe_basename(src)
        out_name = (
            image_map.get(resolved)
            or image_map.get(cleaned)
            or unique_basenames.get(basename)
            or basename
        )
        return f"{assets_dir_name}/{out_name}" if out_name else src

    # img / image / svg image: src / xlink:href
    for img in root.iter():
        if _local_name(img) == "img":
            attr_names = ("src",)
        elif _local_name(img) == "image":
            attr_names = ("href", "{http://www.w3.org/1999/xlink}href")
        else:
            continue
        for attr_name in attr_names:
            src = img.get(attr_name)
            if not src:
                continue
            if src.startswith(("data:", "http://", "https://", "file://", "asset://")):
                continue
            img.set(attr_name, mapped_asset(src))

    # <a> links: leave as-is (PDF won't follow them); but rewrite href to absolute-ish
    # We skip rewriting <a> since the PDF won't be clickable for internal refs in MVP.

    # <link rel="stylesheet" href="...">: remove (we inline CSS separately)
    for link in [el for el in root.iter() if _local_name(el) == "link"]:
        rel = (link.get("rel") or "").lower()
        parent = link.getparent()
        if "stylesheet" in rel and parent is not None:
            parent.remove(link)

    # <style>: keep inline content, but point its url(...) references at the
    # flattened assets/fonts directories written next to index.html. EPUB
    # page-box rules are dropped for the same reason as in ``_concat_css``.
    for style in [el for el in root.iter() if _local_name(el) == "style"]:
        if style.text:
            style.text = _sanitize_epub_css(
                _rewrite_css_urls(style.text, image_map, font_map or {})
            )

    return _serialize_fragment_children(root)


def _html5_wrap(
    body_html: str,
    head_extras: str,
    title: str,
    layout: Layout | None = None,
) -> str:
    """Wrap arbitrary HTML body fragments in a complete HTML5 document."""
    layout = layout or A4_LAYOUT
    return (
        "<!DOCTYPE html>\n"
        '<html lang="und">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>{_build_print_css(layout)}</style>\n"
        f"{head_extras}\n"
        f"<style>{_build_post_epub_css(layout)}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body_html}\n"
        "</body>\n"
        "</html>\n"
    )


_CHARSET_RE = re.compile(r"@charset\s+[^;]*;\s*", re.IGNORECASE)


def _strip_at_page_rules(css: str) -> str:
    """Remove every ``@page`` at-rule (with nested margin boxes) from *css*.

    InDesign-style EPUB exports declare ``@page { margin: 0 }`` for readers
    that supply their own page margins. Inlined after ``PRINT_CSS`` such a
    rule wins the cascade and body text runs to the paper edge (v1.1.1
    regression: ``Systematic Trading``). We own the print page box, so drop
    these rules from the EPUB CSS; ``POST_EPUB_CSS`` re-declares our A4 box
    as a final guard.
    """
    out: list[str] = []
    i = 0
    length = len(css)
    while i < length:
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            end = length if end < 0 else end + 2
            out.append(css[i:end])
            i = end
            continue
        char = css[i]
        if char in "\"'":
            quote = char
            j = i + 1
            while j < length:
                if css[j] == "\\":
                    j += 2
                    continue
                if css[j] == quote:
                    j += 1
                    break
                j += 1
            out.append(css[i:j])
            i = j
            continue
        if css[i:i + 5].lower() == "@page" and (
            i == 0 or not (css[i - 1].isalnum() or css[i - 1] in "-_")
        ):
            j = i + 5
            while j < length and css[j] not in "{;":
                j += 1
            if j >= length:
                i = length
                break
            if css[j] == ";":
                i = j + 1
                continue
            depth = 0
            while j < length:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            i = j
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _sanitize_epub_css(css: str) -> str:
    """Strip rules from third-party EPUB CSS that conflict with print layout."""
    return _strip_at_page_rules(css)


def _concat_css(styles: dict[str, bytes]) -> str:
    """Concatenate all CSS files, dropping in-fragment ``@charset`` rules.

    ``@charset`` is only legal as the very first bytes of a stylesheet.
    Once fragments are concatenated and inlined into a ``<style>``
    element, a stray ``@charset`` makes the browser mis-decode the rest
    of the block; the document is already UTF-8, so they are stripped.
    ``@page`` rules are stripped as well: the converter owns the A4 page box.
    """
    parts: list[str] = []
    for fname, raw in styles.items():
        try:
            css_text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            continue
        css_text = _CHARSET_RE.sub("", css_text)
        css_text = _sanitize_epub_css(css_text)
        parts.append(f"/* === {fname} === */\n{css_text}\n")
    return "\n".join(parts)


_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", re.IGNORECASE)


def _basename_lookup(mapping: dict[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for original, on_disk in mapping.items():
        basename = _safe_basename(original)
        if basename:
            lookup[basename] = on_disk
    return lookup


def _rewrite_css_urls(css: str, image_map: dict[str, str], font_map: dict[str, str]) -> str:
    """Point relative ``url(...)`` references at the flattened asset dirs.

    EPUB fonts are declared through ``@font-face { src: url("../fonts/x.ttf") }``
    in CSS. The normalized document lives at the work-directory root, so those
    relative paths would otherwise escape the work directory and the webfont
    would silently fail to load. Images referenced from CSS need the same
    treatment.
    """
    images_by_base = _basename_lookup(image_map)
    fonts_by_base = _basename_lookup(font_map)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(2).strip()
        if raw.startswith(("data:", "http://", "https://", "file://", "#", "asset://")):
            return match.group(0)
        path = raw.split("#", 1)[0].split("?", 1)[0]
        basename = _safe_basename(path)
        if not basename:
            return match.group(0)
        extension = os.path.splitext(basename)[1].lower()
        if extension in _FONT_EXTENSIONS and basename in fonts_by_base:
            return f'url("fonts/{fonts_by_base[basename]}")'
        if basename in images_by_base:
            return f'url("assets/{images_by_base[basename]}")'
        return match.group(0)

    return _CSS_URL_RE.sub(replace, css)


def _write_assets(book: EpubBook, work_dir: str) -> dict[str, str]:
    """Write images and fonts to work_dir. Returns a mapping
    ``original_filename -> on_disk_filename``."""
    assets_dir = os.path.join(work_dir, "assets")
    fonts_dir = os.path.join(work_dir, "fonts")
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(fonts_dir, exist_ok=True)

    image_map: dict[str, str] = {}
    used_image_names: set[str] = set()
    for orig_name, content in book.images.items():
        basename = _safe_basename(orig_name)
        if not basename:
            continue
        # de-collide
        out_name = basename
        i = 1
        while out_name in used_image_names:
            stem, ext = os.path.splitext(basename)
            out_name = f"{stem}_{i}{ext}"
            i += 1
        used_image_names.add(out_name)
        out_path = os.path.join(assets_dir, out_name)
        try:
            Path(out_path).write_bytes(content)
            image_map[orig_name] = out_name
        except OSError:
            continue

    font_map: dict[str, str] = {}
    used_font_names: set[str] = set()
    for orig_name, content in book.fonts.items():
        basename = _safe_basename(orig_name)
        if not basename:
            continue
        out_name = basename
        i = 1
        while out_name in used_font_names:
            stem, ext = os.path.splitext(basename)
            out_name = f"{stem}_{i}{ext}"
            i += 1
        used_font_names.add(out_name)
        out_path = os.path.join(fonts_dir, out_name)
        try:
            Path(out_path).write_bytes(content)
            font_map[orig_name] = out_name
        except OSError:
            continue

    return {"images": image_map, "fonts": font_map}


# ---------- Public API ----------

def normalize(book: EpubBook, work_dir: str, layout: Layout | None = None) -> NormalizeResult:
    """Build a single self-contained HTML file in ``work_dir``.

    ``layout`` carries the print page box and typography (v1.1.2). When
    omitted, ``layout_for_book(book)`` is used, i.e. the default auto trim
    size derived from the cover (A4 when the cover is unusable).

    Returns a :class:`NormalizeResult` whose ``html_path`` is the absolute
    path to ``index.html`` and whose ``toc_anchors`` map every resolvable
    EPUB TOC entry to an anchor injected into the HTML.
    """
    if layout is None:
        layout = layout_for_book(book)
    os.makedirs(work_dir, exist_ok=True)

    # 1. Write assets
    asset_maps = _write_assets(book, work_dir)
    image_map = asset_maps.get("images", {})
    font_map = asset_maps.get("fonts", {})
    toc_anchors, toc_by_chapter, skipped_toc = _build_toc_anchors(book)

    # 2. Build chapter HTML
    body_parts: list[str] = []
    skipped_cover = 0
    for idx, ch in enumerate(book.chapters):
        if ch.is_cover_only:
            # Already extracted as the cover page by the assembler
            skipped_cover += 1
            continue
        # Extract just the body / inner content if lxml could parse it
        body_inner = _extract_body_inner(ch.content_html)
        body_inner = _rewrite_relative_paths(
            body_inner, ch.href, "assets", image_map, font_map
        )
        body_inner = _clean_text_artifacts(body_inner)
        chapter_title = _clean_text_artifacts(ch.title)
        title_html = ""
        if _should_inject_title(ch, body_inner):
            nav_class = " nav-title" if getattr(ch, "is_nav", False) else ""
            title_html = (
                f'  <h1 class="chapter-title synthetic{nav_class}">'
                f'{escape(chapter_title)}</h1>\n'
            )

        # TOC entries pointing at this chapter: fragment targets go right
        # after the target element, chapter-level targets go at the top.
        chapter_toc = toc_by_chapter.get(ch.id, [])
        fragment_anchors = [a for a in chapter_toc if a.fragment]
        start_anchors = [a for a in chapter_toc if not a.fragment]
        if fragment_anchors:
            body_inner, failed = _inject_fragment_anchors(
                body_inner, fragment_anchors
            )
            start_anchors.extend(failed)

        # Anchor: zero-height inline span with a unique marker string.
        # Must stay in-flow (no position:absolute) so msedge --print-to-pdf
        # actually includes it in the text stream — that's what we search
        # for later to compute outline page numbers.  The chapter marker and
        # any chapter-level TOC markers share one span so the heading keeps
        # exactly one sibling and literal text stays contiguous.
        start_markers = _anchor_marker(ch.id) + "".join(
            _anchor_marker(a.anchor_id) for a in start_anchors
        )
        chapter_anchor_html = _anchor_span(start_markers, f"anchor_{ch.id}")

        leading_anchor_html = ""
        if title_html:
            # Synthetic heading first, marker as its sibling so outline titles
            # stay clean.
            title_html = title_html.rstrip("\n") + chapter_anchor_html + "\n"
        else:
            body_inner, anchor_inserted = _inject_anchor_after_first_heading(
                body_inner,
                chapter_anchor_html,
            )
            if not anchor_inserted:
                leading_anchor_html = f"  {chapter_anchor_html}\n"

        body_parts.append(
            f'<section class="chapter" id="{escape(ch.id)}" '
            f'data-href="{escape(ch.href)}">\n'
            f'{leading_anchor_html}'
            f'{title_html}'
            f'  {body_inner}\n'
            f'</section>'
        )

    body_html = "\n".join(body_parts)
    body_html = (
        body_html
        + "\n"
        + '<span class="epub-end-marker" '
        + 'style="display:inline;font-size:1px;line-height:1px;'
        + 'color:transparent;height:0;overflow:hidden;">'
        + END_MARKER
        + "</span>"
    )
    if skipped_cover:
        # Record the skip in a hidden comment for diagnostics
        body_html = (
            f"<!-- skipped {skipped_cover} cover-only chapter(s) -->\n"
            + body_html
        )
    if skipped_toc:
        body_html = (
            f"<!-- skipped {skipped_toc} TOC entr(y/ies) with unresolved target -->\n"
            + body_html
        )

    # 3. Inline all EPUB CSS (so head_extras covers them)
    inline_css = _rewrite_css_urls(_concat_css(book.styles), image_map, font_map)
    head_extras = f"<style>\n{inline_css}\n</style>"

    # 4. Final document
    final_html = _html5_wrap(body_html, head_extras, book.title, layout)

    index_path = os.path.join(work_dir, "index.html")
    Path(index_path).write_text(final_html, encoding="utf-8")
    return NormalizeResult(html_path=index_path, toc_anchors=toc_anchors, layout=layout)


def _extract_body_inner(html_text: str) -> str:
    """Return the inner HTML of <body>, or the whole document if no <body>."""
    cleaned = _strip_xml_declaration(html_text)
    try:
        root = lxml_html.fromstring(cleaned)
    except Exception:
        return cleaned

    body = next((el for el in root.iter() if _local_name(el) == "body"), None)
    if body is None:
        # No body — return everything inside <html>
        return lxml_html.tostring(root, encoding="unicode")

    body_str = lxml_html.tostring(body, encoding="unicode")
    # Strip <body> wrappers
    body_str = re.sub(r"^<body[^>]*>", "", body_str, flags=re.IGNORECASE)
    body_str = re.sub(r"</body>\s*$", "", body_str, flags=re.IGNORECASE)
    return body_str
