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
from html import escape
from pathlib import Path
from urllib.parse import unquote

from lxml import html as lxml_html

from .parser import EpubBook, EpubChapter


# Anchor marker prefix used to locate each chapter in the rendered PDF.
# We embed this invisible span at the top of every chapter so the
# assembler can later search the PDF text stream and assign page numbers.
ANCHOR_PREFIX = "EPBPFANCHOR_"
ANCHOR_SUFFIX = "_EPBPFANCHOR_END"
END_MARKER = "EPBPFEND_DOCUMENT"


# ---------- Print CSS ----------

PRINT_CSS = """
/* Page setup */
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
@page :first { margin-top: 0; }

/* Base typography */
html { font-size: 11pt; }
body {
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC",
                 "Hiragino Sans", "Noto Sans CJK SC", "Noto Sans",
                 Arial, sans-serif;
    line-height: 1.5;
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
    max-height: 240mm;
    max-width: 100%;
    object-fit: contain;
}
"""


POST_EPUB_CSS = """
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
"""


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
    # flattened assets/fonts directories written next to index.html.
    for style in [el for el in root.iter() if _local_name(el) == "style"]:
        if style.text:
            style.text = _rewrite_css_urls(style.text, image_map, font_map or {})

    return _serialize_fragment_children(root)


def _html5_wrap(body_html: str, head_extras: str, title: str) -> str:
    """Wrap arbitrary HTML body fragments in a complete HTML5 document."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="und">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>{PRINT_CSS}</style>\n"
        f"{head_extras}\n"
        f"<style>{POST_EPUB_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body_html}\n"
        "</body>\n"
        "</html>\n"
    )


_CHARSET_RE = re.compile(r"@charset\s+[^;]*;\s*", re.IGNORECASE)


def _concat_css(styles: dict[str, bytes]) -> str:
    """Concatenate all CSS files, dropping in-fragment ``@charset`` rules.

    ``@charset`` is only legal as the very first bytes of a stylesheet.
    Once fragments are concatenated and inlined into a ``<style>``
    element, a stray ``@charset`` makes the browser mis-decode the rest
    of the block; the document is already UTF-8, so they are stripped.
    """
    parts: list[str] = []
    for fname, raw in styles.items():
        try:
            css_text = raw.decode("utf-8-sig", errors="replace")
        except Exception:
            continue
        css_text = _CHARSET_RE.sub("", css_text)
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

def normalize(book: EpubBook, work_dir: str) -> str:
    """Build a single self-contained HTML file in ``work_dir``.

    Returns the absolute path to ``index.html``.
    """
    os.makedirs(work_dir, exist_ok=True)

    # 1. Write assets
    asset_maps = _write_assets(book, work_dir)
    image_map = asset_maps.get("images", {})
    font_map = asset_maps.get("fonts", {})

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

        # Anchor: zero-height inline span with a unique marker string.
        # Must stay in-flow (no position:absolute) so msedge --print-to-pdf
        # actually includes it in the text stream — that's what we search
        # for later to compute outline page numbers.
        anchor_id = f"{ANCHOR_PREFIX}{ch.id}{ANCHOR_SUFFIX}"
        anchor_html = (
            f'<span class="epub-anchor" '
            f'id="anchor_{escape(ch.id)}" '
            f'style="display:inline;font-size:1px;line-height:1px;'
            f'color:transparent;height:0;overflow:hidden;">'
            f'{escape(anchor_id)}'
            f'</span>'
        )
        leading_anchor_html = ""
        if title_html:
            # Synthetic heading first, marker as its sibling so outline titles
            # stay clean.
            title_html = title_html.rstrip("\n") + anchor_html + "\n"
        else:
            body_inner, anchor_inserted = _inject_anchor_after_first_heading(
                body_inner,
                anchor_html,
            )
            if not anchor_inserted:
                leading_anchor_html = f"  {anchor_html}\n"

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

    # 3. Inline all EPUB CSS (so head_extras covers them)
    inline_css = _rewrite_css_urls(_concat_css(book.styles), image_map, font_map)
    head_extras = f"<style>\n{inline_css}\n</style>"

    # 4. Final document
    final_html = _html5_wrap(body_html, head_extras, book.title)

    index_path = os.path.join(work_dir, "index.html")
    Path(index_path).write_text(final_html, encoding="utf-8")
    return index_path


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
