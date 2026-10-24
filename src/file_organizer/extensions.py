"""Which extensions a run collects.

Two sources: an extension list file (the bundled file-extensions.txt by
default, or the user's own), or the built-in image and video sets selected
by --images and --videos. The switches replace the list; given together they
collect the union of both sets.
"""

from __future__ import annotations

import os
from typing import Optional, Set

BUNDLED_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file-extensions.txt")

# Still images: camera, phone, editor and vector formats. Camera raw is listed
# by vendor extension because nobody saves a file as ".raw" alone.
IMAGE_EXTENSIONS: Set[str] = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif", ".bmp", ".dib", ".tif", ".tiff",
    ".webp", ".ico", ".heic", ".heif", ".avif", ".jxl", ".jp2", ".j2k", ".psd", ".xcf",
    ".pdn", ".kra", ".ora", ".svg", ".eps", ".ai", ".cdr", ".wmf", ".emf", ".tga", ".pcx",
    ".raw", ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".orf", ".rw2", ".raf", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mrw",
}

# Video containers (same set as video-frame-triage). Audio-only containers are
# not here; ogg and asf can hold video, so they stay.
VIDEO_EXTENSIONS: Set[str] = {
    "." + e for e in (
        "mp4", "m4v", "mov", "qt", "3gp", "3g2", "avi", "mkv", "webm", "wmv", "asf",
        "flv", "f4v", "mpg", "mpeg", "mpe", "m2v", "mpv", "vob", "ts", "mts", "m2ts",
        "mxf", "dv", "ogv", "ogg", "rm", "rmvb", "divx", "xvid", "h264", "264", "hevc",
        "265", "mjpeg", "mjpg", "swf", "amv", "dav", "mod", "tod", "evo", "trp", "tp",
    )
}


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
