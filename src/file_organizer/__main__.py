"""Entry point for `python -m file_organizer` and the PyInstaller exe."""

import sys

# Absolute import: PyInstaller runs this file as a top-level script, where a
# relative import has no parent package.
from file_organizer.cli import main

if __name__ == "__main__":
    sys.exit(main())
