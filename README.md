# EPUB2PDF Offline

A local Windows app for converting EPUB books to clean, readable PDF files.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Renderer](https://img.shields.io/badge/renderer-Microsoft%20Edge-0A66C2)

## Overview

EPUB2PDF Offline converts `.epub` files into `.pdf` files on your own computer.
It is designed for users who want a simple drag-and-drop tool without uploading
books to an online service.

The converter focuses on practical reading quality:

- Chinese and English text display correctly in common PDF readers.
- Book covers are preserved when the EPUB provides one.
- EPUB navigation is converted into PDF bookmarks.
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
4. Find the generated `.pdf` file in the selected output folder.

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
| `--timeout` | Stop conversion after the given number of seconds. |

## Run From Source

For users who want to run or modify the source code:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

$env:PYTHONPATH = "src"
python run.py
```

Main dependencies are listed in [requirements.txt](requirements.txt). Developer
tools are listed in [requirements-dev.txt](requirements-dev.txt).

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
- Very large EPUB files may take longer to render.

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
