# Third-Party Notices

EPUB2PDF depends on third-party open-source software. This file summarizes the
direct runtime dependencies used by the source release and bundled executable.
Transitive dependencies are resolved by `pip` from `requirements.txt`.

| Dependency | Purpose | License |
| --- | --- | --- |
| EbookLib | EPUB parsing | GNU Affero General Public License |
| lxml | XML/XHTML parsing | BSD-3-Clause |
| pypdf | PDF reading, writing, bookmarks and metadata | BSD-3-Clause |
| pikepdf | PDF object editing for font embedding | MPL-2.0 |
| fontTools | Font subsetting | MIT |
| PySide6 | Qt GUI bindings | LGPL-3.0-only or GPL-2.0-only or GPL-3.0-only |
| Microsoft Edge | Local HTML-to-PDF rendering engine | External system dependency, not bundled |

The release executable is built with PyInstaller. PyInstaller is used as a
build tool and is not a runtime service of the application.

Because EbookLib is AGPL-licensed and is bundled in the standalone executable,
EPUB2PDF is released under AGPL-3.0-or-later and the corresponding source is
distributed with the release.
