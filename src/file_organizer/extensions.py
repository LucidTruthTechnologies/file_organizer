"""Which files a run collects.

Two sources: an extension list file (the bundled file-extensions.txt by
default, or the user's own), or the built-in image and video sets selected
by --images and --videos. The switches replace the list; given together they
collect the union of both sets. With --videos, a renamed video is also found
by its container signature. The sets come from evidence-io, so every LTT
tool agrees on what an image or a video is.
"""

from __future__ import annotations

import os
from typing import Optional, Set

from evidence_io import filetypes

from .sources import Selector

BUNDLED_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file-extensions.txt")

IMAGE_EXTENSIONS: Set[str] = {"." + e for e in filetypes.IMAGE_EXTENSIONS}
VIDEO_EXTENSIONS: Set[str] = {"." + e for e in filetypes.VIDEO_EXTENSIONS}


def load_extension_list(path: str) -> Set[str]:
    """Parse an extension list. Lines starting with # are section headers,
    text in parentheses is a comment, several extensions may share a line
    separated by commas, and the leading dot is optional."""
    exts: Set[str] = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.split("(", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            for ext in line.split(","):
                ext = ext.strip().lower()
                if not ext:
                    continue
                if not ext.startswith("."):
                    ext = "." + ext
                if any(ch.isspace() for ch in ext) or len(ext) < 2:
                    raise ValueError(f"{path}: not an extension: {ext!r}")
                exts.add(ext)
    if not exts:
        raise ValueError(f"{path}: no extensions listed")
    return exts


def select_extensions(images: bool, videos: bool, list_path: Optional[str] = None) -> tuple[Set[str], str]:
    """Return (extensions, description of where they came from)."""
    if images or videos:
        chosen: Set[str] = set()
        names = []
        if images:
            chosen |= IMAGE_EXTENSIONS
            names.append("images")
        if videos:
            chosen |= VIDEO_EXTENSIONS
            names.append("videos")
        return chosen, "built-in " + " and ".join(names) + " set"
    path = list_path or BUNDLED_LIST
    return load_extension_list(path), f"extension list {path}"


def make_selector(images: bool, videos: bool, list_path: Optional[str] = None) -> tuple[Selector, str]:
    exts, origin = select_extensions(images, videos, list_path)
    if videos:
        origin += ", plus renamed videos found by container signature"
    return Selector(exts, sniff_videos=videos), origin
