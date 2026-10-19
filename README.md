# EPUB2PDF Offline

A local Windows app for converting EPUB books to clean, readable PDF files.

![Version](https://img.shields.io/badge/version-1.1.1-blue)
![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Renderer](https://img.shields.io/badge/renderer-Microsoft%20Edge-0A66C2)

## Overview

EPUB2PDF Offline converts `.epub` files into `.pdf` files on your own computer.
It is designed for users who want a simple drag-and-drop tool without uploading
books to an online service.

The converter focuses on practical reading quality:

- Chinese and English text display correctly in common PDF readers; the fonts
  used by the browser are embedded into the PDF, so text stays selectable and
  searchable on other machines.
- A printable table of contents page is generated for every book, with page
  numbers that match the final PDF and clickable rows.
- Covers in PNG, JPEG, GIF, WebP, BMP, SVG and AVIF are placed on a dedicated
  page scaled to fit; TIFF covers are skipped with a warning because Edge cannot
  render them.
- EPUB navigation and the document's heading hierarchy become nested PDF
  bookmarks (levels follow `h1`–`h6`; the fallback renderer produces a flat,
  chapter-level outline).
- Conversion runs locally and does not send your files anywhere.
- The app processes one book at a time to keep large-book conversion stable.

## Download

Download the Windows release package from the project's GitHub Releases page,
extract it, and run:

```text
EpubToPdf.exe
```

Keep the extracted folder intact. The app depends on files included beside the
executable.

## Requirements

- Windows 10 or Windows 11.
- Microsoft Edge installed on the system.

The release package already includes the required Python runtime and Python
libraries. You do not need to install Python when using the released Windows
app.

## Usage

### Graphical App

1. Open `EpubToPdf.exe`.
2. Drag one or more `.epub` files into the window.
3. Wait for each conversion to finish.
4. Find the generated `.pdf` file in the selected output folder, or click
   **打开输出目录** in the toolbar to open it in File Explorer.

By default, the app keeps conversion clean: it outputs the PDF and removes
temporary work files after the job finishes.

### Command Line

If you run the project from source, you can also convert files from the command
line:

```powershell
$env:PYTHONPATH = "src"
python run.py .\book.epub -o .\book.pdf
```

Or through the module entry point:

```powershell
$env:PYTHONPATH = "src"
python -m epub2pdf --cli .\book.epub -o .\book.pdf
```

CLI options:

| Option | Description |
| --- | --- |
| `input` | Path to the source `.epub` file. |
| `-o, --output` | Output `.pdf` path. Defaults to the source filename with `.pdf`. |
| `--keep-temp` | Keep intermediate files for troubleshooting. |
| `--no-cover` | Do not insert the EPUB cover as the first PDF page. |
| `--quiet` | Hide normal progress output. |
| `--timeout` | Total conversion timeout in seconds (0 = no timeout). The CLI prints a per-stage timing summary; a large book (400+ chapters) can take several minutes. |
| `--outline-source` | Bookmark source: `chromium` (default, follows rendered `h1`–`h6` nesting) or `ncx` (uses the EPUB navigation document; flatter on many books). |
| `--debug` | Print a full Python traceback when conversion fails. |

## Run From Source

For users who want to run or modify the source code:

```powershell
# Use an existing Python 3.11+ installation; the repository does not ship a
# virtual environment.
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

$env:PYTHONPATH = "src"
python run.py
```

`requirements.txt` is the single source of truth for runtime dependencies;
`pyproject.toml` lists the same packages for packaging. Test and packaging
dependencies (`pytest`, `pyinstaller`) live in `requirements-dev.txt`.

Run the fast unit suite with:

```powershell
python -m pytest -q
```

End-to-end tests actually launch Microsoft Edge and are opt-in:

```powershell
python -m pytest -q -m e2e
```

## Build From Source

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean .\EpubToPdf.spec
```

The built Windows app is written to:

```text
dist\EpubToPdf\EpubToPdf.exe
```

## Troubleshooting

- If the app does not start, make sure the release folder was fully extracted.
- If conversion fails, make sure Microsoft Edge is installed and up to date.
- DRM-protected EPUB files cannot be converted.
- Fixed-layout books such as comics, magazines, or heavily designed picture
  books may not keep their original layout perfectly.
- Very large EPUB files may take longer to render. A 400-chapter book can take
  several minutes; use `--timeout` with a generous value if you need a hard
  limit.
- If the PDF viewer shows a flat chapter list instead of a nested outline, the
  Chrome DevTools route was unavailable and the fallback renderer was used. The
  conversion itself still succeeded.
- The EPUB's own navigation page (the table of contents) is kept as a normal
  content page with print styling; it is not regenerated.

## Privacy

EPUB2PDF Offline runs locally. It does not upload books, generated PDFs, logs,
or metadata.

## Contributing

Issues and pull requests are welcome. Please read
[CONTRIBUTING.md](CONTRIBUTING.md) before contributing.

When reporting a conversion problem, include:

- Windows version
- Microsoft Edge version
- EPUB type, such as novel, textbook, code book, or fixed-layout book
- The visible error message
- Whether the issue also happens with a smaller public-domain EPUB

Please do not attach copyrighted books to public issues unless you have the
right to share them.

## License

Copyright (c) 2026 EPUB2PDF contributors.

This project is released under the GNU Affero General Public License v3.0 or
later. See [LICENSE](LICENSE) for the full license text.

Third-party dependency notices are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
