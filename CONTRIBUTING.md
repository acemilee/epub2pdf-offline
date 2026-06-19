# Contributing

Thanks for helping improve EPUB2PDF.

## Development

1. Create a virtual environment.
2. Install `requirements.txt` and `requirements-dev.txt`.
3. Run the test suite before submitting changes:

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m pytest tests -q -p no:cacheprovider
```

## Test Data

Do not commit copyrighted EPUB files, generated PDFs or personal documents.
Use synthetic EPUB fixtures for tests.

## Scope

Keep changes focused. Parser, normalizer, renderer and assembler behavior are
covered by regression tests because small layout changes can have visible PDF
effects.
