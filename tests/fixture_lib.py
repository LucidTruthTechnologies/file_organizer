"""Shared fixture recipe for pytest (conftest.py) and the CI smoke script
(make_fixture.py). Every file is synthetic bytes; no case material is read.
No pytest import here, so the script can use it too."""

from __future__ import annotations

import os
import shutil
import subprocess

from evidence_io.ewf_writer import EwfMetadata, write_file_as_e01
from evidence_io.fat32 import Fat32Builder

# {path in the source: bytes}. Two different beach.jpg files exercise the
# no-overwrite rule; the upper-case .MOV exercises case folding.
FILES = {
    "Users/alice/Pictures/beach.jpg": b"\xff\xd8\xff\xe0alice beach" + b"A" * 3000,
    "Users/bob/Pictures/beach.jpg": b"\xff\xd8\xff\xe0bob beach" + b"B" * 5000,
    "Users/alice/Pictures/diagram.png": b"\x89PNG\r\n\x1a\n" + b"P" * 700,
    "Users/alice/Videos/holiday.mp4": b"\x00\x00\x00\x18ftypmp42" + b"V" * 20000,
    "Users/alice/Videos/2024 trip/clip.MOV": b"\x00\x00\x00\x14ftypqt  " + b"M" * 9000,
    "Users/alice/Documents/report.docx": b"PK\x03\x04docx" + b"D" * 1200,
    "Users/alice/notes.txt": b"not evidence\n" * 50,
    "Users/bob/data.zzq": os.urandom(4096),  # an extension no list carries
}
IMAGES = 3
VIDEOS = 2


def write_tree(root: str) -> dict[str, str]:
    """Write FILES under `root`; returns {relative path: host path}."""
    out = {}
    for rel, data in FILES.items():
        full = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        os.utime(full, (1_600_000_000, 1_600_000_000))  # 2020-09-13, a fixed, checkable time
        out[rel] = full
    return out


def build_source_e01(directory: str) -> tuple[str, str]:
    """FAT32 image of FILES, as an E01. Returns (E01 path, writer used).
    ewfacquire (libewf's own writer) is used when present so the input is
    independent of the in-tree writer; Windows CI uses the in-tree one."""
    tree = write_tree(os.path.join(directory, "tree"))
    fb = Fat32Builder(label="SOURCE")
    for rel, host in tree.items():
        fb.add_file(rel, host, mtime=os.path.getmtime(host))
    raw = os.path.join(directory, "source.img")
    fb.build(raw)
    e01 = os.path.join(directory, "source.E01")
    acquire = shutil.which("ewfacquire")
    if acquire:
        subprocess.run([acquire, "-u", "-q", "-t", os.path.join(directory, "source"), "-f", "encase6",
                        "-c", "fast", "-C", "T1", "-e", "pytest", "-E", "1", "-m", "fixed", "-M", "logical", raw],
                       check=True, capture_output=True)
        writer = "ewfacquire"
    else:
        write_file_as_e01(raw, e01, EwfMetadata(case_number="T1", examiner_name="pytest",
                                                version="fixture", platform="ci"))
        writer = "in-tree"
    os.remove(raw)
    return e01, writer
