"""``python -m epub2pdf`` entry point.

Default behaviour: launch the GUI. Pass ``--cli`` to use the legacy CLI.
"""
import sys

if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from .cli import main as cli_main
        sys.exit(cli_main())
    else:
        from .app import main as app_main
        sys.exit(app_main())