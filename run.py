"""Convenience launcher.

Usage:
    python run.py                       # launch GUI
    python run.py input.epub [options]  # CLI mode

The launcher detects when the active Python cannot load PySide6 (a common
issue with mixed conda + system installs) and falls back to any other
Python on PATH that *can*. Pass ``--no-fallback`` to disable.
"""
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SRC = HERE / "src"


# ---------- Python discovery ----------

_KNOWN_PYTHONS = [
    r"F:\python313\python.exe",
    r"C:\Python313\python.exe",
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
    r"C:\Users\{USER}\AppData\Local\Programs\Python\Python313\python.exe",
    r"C:\Users\{USER}\AppData\Local\Programs\Python\Python312\python.exe",
]


def _candidate_pythons():
    user = os.environ.get("USERNAME", "")
    for p in _KNOWN_PYTHONS:
        yield p.replace("{USER}", user)
    # Also search PATH
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("python.exe", "python3.exe", "python"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                yield cand


def _current_python_works() -> bool:
    """Return True if THIS Python can import PySide6.QtWidgets."""
    try:
        from PySide6 import QtWidgets  # noqa: F401
        return True
    except Exception:
        return False


def _other_python_works() -> str | None:
    """Return the path of any Python on disk that can load PySide6."""
    here = os.path.normcase(sys.executable)
    for cand in _candidate_pythons():
        if not os.path.isfile(cand):
            continue
        if os.path.normcase(cand) == here:
            continue
        probe = (
            "try:\n"
            "    from PySide6 import QtWidgets\n"
            "    print('OK', end='')\n"
            "except Exception:\n"
            "    pass\n"
        )
        try:
            r = subprocess.run(
                [cand, "-c", probe],
                capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if b"OK" in r.stdout:
                return cand
        except Exception:
            continue
    return None


# ---------- Main ----------

def main() -> int:
    args = sys.argv[1:]
    no_fallback = "--no-fallback" in args
    if no_fallback:
        args = [a for a in args if a != "--no-fallback"]

    # Add src/ to path so direct execution works
    sys.path.insert(0, str(SRC))

    # Decide route: CLI if there's a positional file arg OR explicit help
    positionals = [a for a in args if not a.startswith("-")]
    is_gui = not positionals and "-h" not in args and "--help" not in args

    # If current Python can't load PySide6 and this is a GUI run, try fallback
    if is_gui and not _current_python_works() and not no_fallback:
        other = _other_python_works()
        if other:
            print(f"[run.py] current Python {sys.executable} cannot load PySide6;")
            print(f"[run.py] re-launching with {other}")
            r = subprocess.run([other, str(Path(__file__).resolve())] + args,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.returncode
        else:
            print("ERROR: PySide6 is installed but Qt failed to load:", file=sys.stderr)
            print(f"  Python: {sys.executable}", file=sys.stderr)
            print("  Could not find another Python on this machine with a working "
                  "PySide6 install.", file=sys.stderr)
            print("\nTry one of:", file=sys.stderr)
            print("  pip install --upgrade --force-reinstall PySide6", file=sys.stderr)
            print("  conda install -c conda-forge pyside6", file=sys.stderr)
            return 1

    # Route to CLI or GUI
    if not is_gui:
        from epub2pdf.cli import main as cli_main
        return cli_main(args)
    else:
        # Final PySide6 check
        try:
            from PySide6 import QtWidgets  # noqa: F401
        except ImportError as e:
            print(f"ERROR: PySide6 is required for the GUI but not installed "
                  f"in this Python interpreter.", file=sys.stderr)
            print(f"  Python : {sys.executable}", file=sys.stderr)
            print(f"  Reason : {e}", file=sys.stderr)
            print(f"\nFix:  pip install PySide6", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"ERROR: PySide6 is installed but Qt failed to load:", file=sys.stderr)
            print(f"  Python: {sys.executable}", file=sys.stderr)
            print(f"  Reason: {e}", file=sys.stderr)
            print(f"\nThis usually means a version mismatch between PySide6 and Python.",
                  file=sys.stderr)
            print(f"Try:  pip install --upgrade --force-reinstall PySide6",
                  file=sys.stderr)
            return 1
        from epub2pdf.app import main as app_main
        return app_main()


if __name__ == "__main__":
    sys.exit(main())