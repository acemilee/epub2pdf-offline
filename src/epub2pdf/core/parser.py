"""Layer 1: EPUB Parser.

Reads an .epub file, extracts metadata, spine-ordered chapters,
images, fonts, and styles. Returns an ``EpubBook`` data object.

Handles EPUB 2 (toc.ncx) and EPUB 3 (nav.xhtml) navigation.
Refuses DRM-encrypted files with a clear error.
"""
from __future__ import annotations

import os
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

import ebooklib
from ebooklib import epub
from lxml import etree


# ---------- Data ----------

@dataclass
class EpubChapter:
    id: str
    href: str
    title: str
    content_html: str  # raw XHTML/HTML body bytes decoded to str
    is_cover_only: bool = False  # True if chapter is essentially just an image
    is_nav: bool = False  # True for EPUB 3 navigation documents
    title_is_fallback: bool = False  # True when title came from item id/path


@dataclass
class TocNode:
    title: str
    href: str  # may be empty
    children: list["TocNode"] = field(default_factory=list)


@dataclass
class EpubBook:
    title: str
    author: str
    language: str
    chapters: list[EpubChapter]
    images: dict[str, bytes]   # filename -> bytes
    fonts: dict[str, bytes]
    styles: dict[str, bytes]   # CSS files: filename -> bytes
    cover_image: Optional[str]  # filename of cover, or None
    toc: list[TocNode]
    cover_bytes: Optional[bytes] = None  # raw bytes of the cover image


# ---------- Errors ----------

class EpubParseError(Exception):
    """Base for parse failures."""


class EpubEncryptedError(EpubParseError):
    """Raised when the EPUB is DRM-protected."""


# ---------- Helpers ----------

def _first(metadata_list: list[tuple[Any, dict]]) -> str:
    if not metadata_list:
        return ""
    val = metadata_list[0][0]
    return str(val) if val is not None else ""


def _decode_html_bytes(raw: bytes) -> str:
    """Decode an XHTML/HTML resource using its declared character set.

    EPUB content is usually UTF-8, but older or poorly generated books may
    declare another encoding. Decoding everything as UTF-8 with replacement
    silently corrupts those books before the renderer sees the text.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")

    head = raw[:4096]
    encodings: list[str] = []
    patterns = (
        br"<\?xml[^>]+encoding=[\"']([^\"']+)",
        br"<meta[^>]+charset=[\"']?([^\"'>\s/]+)",
        br"<meta[^>]+content=[\"'][^\"']*charset=([^\"'>\s;]+)",
    )
    for pat in patterns:
        m = re.search(pat, head, re.IGNORECASE)
        if m:
            try:
                encodings.append(m.group(1).decode("ascii").strip())
            except UnicodeDecodeError:
                pass

    for enc in encodings + ["utf-8"]:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _strip_xml_declaration(html_text: str) -> str:
    """Remove an XML declaration before parsing Unicode XHTML."""
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", html_text, count=1, flags=re.IGNORECASE)


def _local_name(elem) -> str:
    """Return an element or attribute local-name, tolerant of namespaces."""
    tag = getattr(elem, "tag", elem)
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _parse_document(html_text: str):
    """Parse XHTML/HTML into an lxml tree with recovery enabled."""
    cleaned = _strip_xml_declaration(html_text)
    raw = cleaned.encode("utf-8", errors="replace")
    for parser in (
        etree.XMLParser(recover=True, resolve_entities=False),
        etree.HTMLParser(),
    ):
        try:
            root = etree.fromstring(raw, parser=parser)
            if root is not None:
                return root
        except Exception:
            continue
    return None


def _element_text(elem) -> str:
    text = " ".join(part.strip() for part in elem.itertext() if part and part.strip())
    return re.sub(r"\s+", " ", text).strip()


def _extract_title_from_xhtml(content_html: str) -> str:
    """Best-effort title extraction from chapter XHTML.

    Uses the first heading (h1-h6) in document order because many EPUB3 books
    use h3/h4 for chapter titles; falls back to ``<title>``.
    """
    root = _parse_document(content_html)
    if root is None:
        return ""
    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
    for cand in root.iter():
        if _local_name(cand) not in heading_tags:
            continue
        text = _element_text(cand)
        if text:
            return text[:200]
    for cand in root.iter():
        if _local_name(cand) == "title":
            text = _element_text(cand)
            if text:
                return text[:200]
    return ""


def _body_or_root(root):
    for elem in root.iter():
        if _local_name(elem) == "body":
            return elem
    return root


def _extract_image_refs(html_text: str) -> list[str]:
    """Return image references from <img> and SVG <image> elements."""
    root = _parse_document(html_text)
    if root is None:
        return re.findall(
            r'<(?:img|image)\b[^>]*(?:src|href|xlink:href)=["\']([^"\']+)',
            html_text,
            re.IGNORECASE,
        )

    refs: list[str] = []
    for elem in root.iter():
        name = _local_name(elem)
        if name == "img":
            src = elem.get("src")
            if src:
                refs.append(src)
        elif name == "image":
            for attr_name, value in elem.attrib.items():
                if _local_name(attr_name) == "href" and value:
                    refs.append(value)
    return refs


def _is_cover_only_chapter(html_text: str) -> bool:
    """Heuristic: a chapter is "cover only" if its body text is empty
    (after stripping tags + entities) and it contains an image.

    EPUB generators often wrap covers as SVG <image> instead of <img>.
    Regex-based detection misses those and lets internal ids such as
    ``cover_xhtml`` leak into the PDF as fake chapter titles.
    """
    image_refs = _extract_image_refs(html_text)
    if not image_refs:
        return False

    root = _parse_document(html_text)
    if root is None:
        body_match = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.IGNORECASE)
        inner = body_match.group(1) if body_match else html_text
        text_only = re.sub(r"<[^>]+>", " ", inner)
    else:
        body = _body_or_root(root)
        text_only = _element_text(body)

    text_only = (
        text_only.replace("&nbsp;", " ")
                 .replace("&#160;", " ")
                 .replace("&#13;", "")
                 .replace("&#10;", "")
                 .replace("&amp;", "")
    )
    text_only = re.sub(r"\s+", "", text_only)
    if text_only and text_only.lower() not in {"cover", "封面"}:
        return False
    return len(html_text) < 50000


def _has_epub_type(elem, wanted: str) -> bool:
    for attr_name, value in getattr(elem, "attrib", {}).items():
        if _local_name(attr_name) != "type":
            continue
        tokens = {part.strip().lower() for part in str(value).split() if part.strip()}
        if wanted in tokens:
            return True
    return False


def _is_navigation_chapter(html_text: str, item: "epub.EpubItem") -> bool:
    """Return True for EPUB 3 nav.xhtml documents."""
    props = _item_properties(item)
    if "nav" in props:
        return True

    basename = os.path.basename((getattr(item, "file_name", "") or "").lower())
    item_id = (getattr(item, "id", "") or "").lower()
    if basename not in {"nav.xhtml", "nav.html", "toc.xhtml", "toc.html"} and item_id not in {"nav", "toc"}:
        return False

    root = _parse_document(html_text)
    if root is None:
        return False
    for elem in root.iter():
        if _local_name(elem) == "nav" and _has_epub_type(elem, "toc"):
            return True
    return False


def _looks_like_cover_item(item: "epub.EpubItem", title: str = "") -> bool:
    props = _item_properties(item)
    if "cover-image" in props:
        return True
    label = " ".join(
        str(part or "")
        for part in (
            getattr(item, "id", ""),
            getattr(item, "file_name", ""),
            title,
        )
    ).lower()
    return "cover" in label or "封面" in label


def _clean_href(href: str) -> str:
    href = unquote((href or "").split("?", 1)[0].split("#", 1)[0])
    return href.replace("\\", "/").lstrip("/")


def _resolve_href(base_href: str, href: str) -> str:
    """Resolve an EPUB relative href against a content document href."""
    href = _clean_href(href)
    if not href or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href):
        return href
    if href.startswith("/"):
        return posixpath.normpath(href.lstrip("/"))
    base_dir = posixpath.dirname(_clean_href(base_href))
    return posixpath.normpath(posixpath.join(base_dir, href))


_IMAGE_EXTS = {
    ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".jxl", ".png",
    ".svg", ".tif", ".tiff", ".webp",
}


def _item_properties(item) -> list[str]:
    props = getattr(item, "properties", None) or []
    if isinstance(props, str):
        props = props.split()
    return [str(prop).lower() for prop in props]


def _item_type(item) -> Optional[int]:
    try:
        return item.get_type()
    except Exception:
        return None


def _is_image_item(item) -> bool:
    media_type = (getattr(item, "media_type", "") or "").lower()
    if media_type.startswith("image/"):
        return True
    filename = (getattr(item, "file_name", "") or "").lower()
    return os.path.splitext(filename)[1] in _IMAGE_EXTS


def _find_title_in_toc(toc_nodes: list[TocNode], target_href: str) -> Optional[str]:
    """Walk the TOC tree and return the first title whose href matches
    the basename of ``target_href`` (ignoring fragment and query)."""
    if not target_href:
        return None
    target_base = os.path.basename(target_href.split("#", 1)[0].split("?", 1)[0])

    def walk(nodes: list[TocNode]) -> Optional[str]:
        for n in nodes:
            n_base = os.path.basename((n.href or "").split("#", 1)[0].split("?", 1)[0])
            if n_base and n_base == target_base:
                return n.title
            found = walk(n.children)
            if found:
                return found
        return None

    return walk(toc_nodes)


def _parse_toc(toc) -> list[TocNode]:
    """Convert ebooklib's nested toc structure into TocNode trees.

    ebooklib's TOC has two flavors:
      - ``[Section(...), [Link(...), Link(...)], ...]``        (NCX-style)
      - ``[Section(...), [Section(...), ...]]``                (NAV-style)
    Each node's ``.href`` may be a string, a ``Link`` object, or a
    list of ``Link`` objects.
    """
    result: list[TocNode] = []

    def _href_to_str(href) -> str:
        if href is None:
            return ""
        if isinstance(href, str):
            return href
        if isinstance(href, list):
            # pick the first link's href
            for h in href:
                s = _href_to_str(h)
                if s:
                    return s
            return ""
        # ebooklib Link or Section
        if hasattr(href, "href"):
            return str(href.href or "")
        if hasattr(href, "title"):
            return ""
        return str(href)

    def walk(node) -> list[TocNode]:
        """Return a list (a single toc item may expand to multiple nodes
        when it's a tuple-of-links)."""
        # tuple form: (Section, [Link, Link, ...])
        if isinstance(node, tuple):
            sec, links = node[0], (node[1] if len(node) > 1 else [])
            section_title = getattr(sec, "title", "") or ""
            section_href = _href_to_str(getattr(sec, "href", ""))
            child_nodes: list[TocNode] = []
            for child in getattr(sec, "children", []) or []:
                child_nodes.extend(walk(child))
            if isinstance(links, (list, tuple)) and links:
                for i, link in enumerate(links):
                    # Nested (Section, [Link, ...]) tuples appear inside the
                    # children list of a top-level section; recurse into them
                    # instead of stringifying the tuple into a bogus href.
                    if isinstance(link, (tuple, list)):
                        child_nodes.extend(walk(link))
                        continue
                    href = _href_to_str(link)
                    title = getattr(link, "title", "") or section_title or f"Section {i+1}"
                    child_nodes.append(TocNode(title=str(title), href=href))
            if section_href:
                # The section itself is a real destination (chapter start);
                # keep it as the parent of its sub-entries so the generated
                # TOC page has one row per chapter plus one per section.
                return [TocNode(
                    title=str(section_title),
                    href=section_href,
                    children=child_nodes,
                )]
            return child_nodes

        # Plain Section with .title / .href / .children
        if hasattr(node, "title"):
            href = _href_to_str(getattr(node, "href", ""))
            children = []
            for child in getattr(node, "children", []) or []:
                children.extend(walk(child))
            return [TocNode(title=str(node.title or ""), href=href, children=children)]

        # Bare Link
        if hasattr(node, "href"):
            return [TocNode(
                title=str(getattr(node, "title", "") or ""),
                href=_href_to_str(node.href),
                children=[],
            )]

        return []

    for entry in toc:
        try:
            result.extend(walk(entry))
        except Exception:
            continue
    return result


def _detect_drm(path: str) -> bool:
    """Check for common DRM indicators in the EPUB container."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            # Adobe DRM: rights.xml
            if "META-INF/rights.xml" in names:
                return True
            # LCP: license.lcpl inside META-INF
            for n in names:
                if n.lower().endswith(".lcpl") or n.lower().endswith(".lcp"):
                    return True
            # Readium LCP
            for n in names:
                if n.endswith("META-INF/license.lcpl"):
                    return True
    except zipfile.BadZipFile:
        raise EpubParseError("file is not a valid ZIP / EPUB")
    return False


def _read_cover_bytes(book: "epub.EpubBook", cover_filename: str) -> Optional[bytes]:
    """Read cover image bytes regardless of which book.get_items* path
    holds them (EpubCover objects are excluded from ITEM_IMAGE)."""
    cover_filename = _clean_href(cover_filename)
    # Try direct lookup by href first
    item = book.get_item_with_href(cover_filename)
    if item is not None:
        try:
            return item.get_content()
        except Exception:
            pass
    # Try by id
    item = book.get_item_with_id(cover_filename)
    if item is not None:
        try:
            return item.get_content()
        except Exception:
            pass
    # Scan all items (covers may be EpubCover / EpubImage / EpubItem)
    cover_base = os.path.basename(cover_filename)
    for item in book.get_items():
        item_name = _clean_href(getattr(item, "file_name", "") or "")
        if item_name == cover_filename or os.path.basename(item_name) == cover_base:
            try:
                return item.get_content()
            except Exception:
                pass
    return None


def _find_cover(book: "epub.EpubBook", chapters: list[EpubChapter] | None = None) -> Optional[str]:
    """Try multiple ways to locate the cover image filename.

    Falls back to: the only/largest image in the first spine chapter if
    no explicit cover metadata is present.
    """
    # 1. <meta name="cover" content="...">
    for _, attrs in book.get_metadata("OPF", "cover"):
        content = attrs.get("content")
        if content:
            # content may be an idref or a filename
            item = book.get_item_with_id(content) or book.get_item(content)
            if item is not None:
                return item.file_name
            return content
    # 2. properties="cover-image" on an image item
    cover_type = getattr(ebooklib, "ITEM_COVER", None)
    for item in book.get_items():
        if not _is_image_item(item):
            continue
        props = _item_properties(item)
        if "cover-image" in props or (cover_type is not None and _item_type(item) == cover_type):
            return item.file_name
    # 3. Guide fallback: <reference type="cover" href="...">
    for guide_ref in getattr(book, "guide", []) or []:
        try:
            ref_type = (guide_ref.get("type") or "").lower()
            href = guide_ref.get("href") or ""
        except AttributeError:
            continue
        if ref_type == "cover" and href:
            item = book.get_item_with_href(_clean_href(href))
            if item is not None and _is_image_item(item):
                return item.file_name

    # 4. Heuristic: image in an early cover-only spine chapter.
    if chapters:
        for idx, ch in enumerate(chapters[:3]):
            label = f"{ch.id} {ch.href} {ch.title}".lower()
            if not ch.is_cover_only:
                continue
            if idx != 0 and "cover" not in label and "封面" not in label:
                continue
            for ref in _extract_image_refs(ch.content_html):
                resolved = _resolve_href(ch.href, ref)
                if resolved:
                    return resolved
    # 5. Last resort: image filename/id that clearly says cover.
    for item in book.get_items():
        if not _is_image_item(item):
            continue
        label = f"{getattr(item, 'id', '')} {getattr(item, 'file_name', '')}".lower()
        if "cover" in label or "封面" in label:
            return item.file_name
    return None


# ---------- Public API ----------

def parse(epub_path: str) -> EpubBook:
    """Parse an EPUB file into an ``EpubBook`` object."""
    p = Path(epub_path)
    if not p.exists():
        raise EpubParseError(f"file not found: {epub_path}")

    if _detect_drm(epub_path):
        raise EpubEncryptedError("EPUB is DRM-protected; cannot convert")

    try:
        book = epub.read_epub(str(p))
    except Exception as e:
        raise EpubParseError(f"ebooklib failed to read EPUB: {e}") from e

    title = _first(book.get_metadata("DC", "title")) or p.stem
    author = _first(book.get_metadata("DC", "creator")) or "Unknown"
    language = _first(book.get_metadata("DC", "language")) or "en"

    # TOC
    toc = _parse_toc(book.toc)

    # Chapters in spine order.
    # ebooklib's spine entries vary by version:
    #   - ('id_str', 'yes'|'no')            <- newer versions
    #   - (EpubItem, bool)                  <- older versions
    #   - 'id_str'                          <- very old versions
    chapters: list[EpubChapter] = []
    seen: set[str] = set()

    def _resolve_spine_entry(entry) -> Optional[epub.EpubItem]:
        """Normalize a spine entry to an EpubItem, or None to skip."""
        if isinstance(entry, epub.EpubItem):
            return entry
        if isinstance(entry, tuple):
            ref, linear = entry[0], entry[1] if len(entry) > 1 else True
            if isinstance(linear, str):
                if linear.lower() not in ("yes", "true", "1"):
                    return None
            elif not linear:
                return None
            if isinstance(ref, epub.EpubItem):
                return ref
            return book.get_item_with_id(ref)
        # bare string id
        return book.get_item_with_id(entry)

    for entry in book.spine:
        item = _resolve_spine_entry(entry)
        if item is None:
            continue
        if item.id in seen:
            continue
        seen.add(item.id)
        try:
            raw = item.get_content()
        except Exception:
            continue
        content_html = _decode_html_bytes(raw)
        # Title resolution order:
        #   1. First heading inside the chapter XHTML
        #   2. TOC entry that points to the same href
        #   3. Fallback to id
        # Prefer the document heading because TOCs often point to the first
        # subsection, which produced repeated "What You'll Learn" titles.
        title_from_heading = _extract_title_from_xhtml(content_html)
        title_from_toc = _find_title_in_toc(toc, item.file_name)
        ch_title = title_from_heading or title_from_toc or item.id
        title_is_fallback = not title_from_heading and not title_from_toc
        # Detect "image-only" chapters (typical cover pages).
        is_image_only = _is_cover_only_chapter(content_html)
        spine_index = len(chapters)
        is_cover = is_image_only and (
            spine_index == 0
            or (spine_index < 3 and _looks_like_cover_item(item, ch_title))
        )
        is_nav = _is_navigation_chapter(content_html, item)
        chapters.append(EpubChapter(
            id=item.id,
            href=item.file_name,
            title=ch_title,
            content_html=content_html,
            is_cover_only=is_cover,
            is_nav=is_nav,
            title_is_fallback=title_is_fallback,
        ))

    # Cover (now that we have chapters for the heuristic)
    cover_image = _find_cover(book, chapters)
    cover_bytes = None
    if cover_image:
        cover_bytes = _read_cover_bytes(book, cover_image)

    # Images
    images: dict[str, bytes] = {}
    for item in book.get_items():
        if not _is_image_item(item):
            continue
        try:
            images[item.file_name] = item.get_content()
        except Exception:
            continue

    # Fonts
    fonts: dict[str, bytes] = {}
    for item in book.get_items_of_type(ebooklib.ITEM_FONT):
        try:
            fonts[item.file_name] = item.get_content()
        except Exception:
            continue

    # Styles
    styles: dict[str, bytes] = {}
    for item in book.get_items_of_type(ebooklib.ITEM_STYLE):
        try:
            styles[item.file_name] = item.get_content()
        except Exception:
            continue

    return EpubBook(
        title=title,
        author=author,
        language=language,
        chapters=chapters,
        images=images,
        fonts=fonts,
        styles=styles,
        cover_image=cover_image,
        cover_bytes=cover_bytes,
        toc=toc,
    )
