"""make_fixture - write a synthetic source E01 into a directory.

USAGE:
    python tests/make_fixture.py <out-dir>

Used by the CI smoke test so the built exe is exercised on a real image.
Every file inside is synthetic bytes; no case material is involved. The
recipe is shared with the pytest fixtures (fixture_lib.py).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_lib import build_source_e01  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    os.makedirs(argv[0], exist_ok=True)
    e01, _writer = build_source_e01(argv[0])
    print(e01)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
