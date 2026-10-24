from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from fixture_lib import build_source_e01  # noqa: E402


@pytest.fixture(scope="session")
def source_e01(tmp_path_factory) -> str:
    e01, writer = build_source_e01(str(tmp_path_factory.mktemp("source")))
    print(f"source E01 written by {writer}")
    return e01
