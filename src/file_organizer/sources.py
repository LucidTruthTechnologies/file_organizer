"""Walk a source (a folder, or every filesystem inside an E01) and yield the
files that are wanted. Both kinds yield the same record, which knows how to
copy itself out and hash the bytes as they pass.

The E01 is read in-process through evidence-io (libewf and The Sleuth Kit):
no mount, no driver, no administrator right, and the image is never opened
for writing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Set

from evidence_io.ewf_reader import SourceInfo, open_e01
from evidence_io.filetypes import video_match
from evidence_io.hashing import BLOCK, Hashes, hash_stream
from evidence_io.image_walk import ImageFile, PartitionInfo, fs_type_name, iter_filesystems, walk_files

Log = Callable[[str], None]
Cancel = Callable[[], bool]


@dataclass
class Selector:
    """What a run collects: extensions (with the dot), plus renamed videos
    found by container signature when videos are wanted."""
    exts: Set[str]
    sniff_videos: bool = False

    def match(self, name: str, size: int, read_head: Callable[[int], bytes]) -> Optional[str]:
        ext = os.path.splitext(name)[1].lower()
        if ext in self.exts:
            return "extension"
        if self.sniff_videos and video_match(name, size, read_head) == "magic":
            return "magic"
        return None


@dataclass
class FoundFile:
    source_kind: str     # "folder" or "e01"
    source: str          # the folder or E01 the file came from
    path: str            # host path (folder) or path inside the image, forward slashes
    name: str
    ext: str             # lower case, with the dot
    size: int
    mtime: Optional[float]
    atime: Optional[float]
    ctime: Optional[float] = None   # metadata change time, where the source keeps one
    crtime: Optional[float] = None  # creation time, where the source keeps one
    fs_type: str = ""               # source filesystem, for E01 sources
    matched_by: str = "extension"
    allocated: bool = True
    realloc: bool = False  # deleted name whose metadata now belongs to another file
    _image: Optional[ImageFile] = field(default=None, repr=False)

    def copy_to(self, dest: str) -> tuple[Hashes, str]:
        """Copy to a NEW file `dest` (FileExistsError if anything is there),
        then stamp the modified and accessed times recorded at discovery.
        Returns (hashes of the bytes copied, note). A short read (a broken run
        on a deleted file) shows as Hashes.bytes below size, never padded.
        The note is non-empty only when the times could not be set."""
        if self._image is not None:
            h = self._image.copy_to(dest)
        else:
            with open(self.path, "rb") as src, open(dest, "xb") as out:
                h = hash_stream(iter(lambda: src.read(BLOCK), b""), sink=out)
        # The times captured before reading, not copystat afterwards: reading
        # can bump the source's access time, and copystat would also carry a
        # read-only flag that stops a failed copy being cleaned up.
        note = ""
        if self.mtime is not None:
            try:
                os.utime(dest, (self.atime if self.atime is not None else self.mtime, self.mtime))
            except (OSError, OverflowError, ValueError) as exc:
                note = f"times not set on the copy ({exc}); the manifest keeps the originals"
        return h, note


def _head(path: str) -> Callable[[int], bytes]:
    def read(n: int) -> bytes:
        with open(path, "rb") as fh:
            return fh.read(n)
    return read


def walk_folder(root: str, sel: Selector, log: Log, cancel: Cancel,
                skip: Optional[str] = None) -> Iterator[FoundFile]:
    """Every wanted file under `root`. `skip` is a directory never entered
    (the output folder, when it sits inside a source)."""
    root = os.path.abspath(root)
    skip_norm = os.path.normcase(os.path.abspath(skip)) if skip else None

    def onerror(exc: OSError) -> None:
        log(f"cannot read {exc.filename}: {exc.strerror}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        if cancel():
            return
        if skip_norm:
            dirnames[:] = [d for d in dirnames
                           if os.path.normcase(os.path.join(dirpath, d)) != skip_norm]
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError as exc:
                log(f"cannot stat {full}: {exc.strerror}")
                continue
            matched = sel.match(name, st.st_size, _head(full))
            if not matched:
                continue
            crtime = getattr(st, "st_birthtime", None)
            # st_ctime is the change time on POSIX; on Windows it was the
            # creation time (st_birthtime covers that), so it is not recorded there.
            ctime = st.st_ctime if os.name != "nt" else None
            yield FoundFile("folder", root, full, name, os.path.splitext(name)[1].lower(), st.st_size,
                            st.st_mtime, st.st_atime, ctime, crtime, matched_by=matched)


class E01Source:
    """An open E01. Use as a context manager so the handle is closed."""

    def __init__(self, path: str, log: Log) -> None:
        self.img, self.info = open_e01(path)
        self.log = log
        self.inventory: List[PartitionInfo] = []

    @property
    def source_info(self) -> SourceInfo:
        return self.info

    def walk(self, sel: Selector, include_deleted: bool, cancel: Cancel) -> Iterator[FoundFile]:
        for part, offset, fs in iter_filesystems(self.img, self.log, self.inventory):
            self.log(f"{os.path.basename(self.info.path)} partition {part}: {fs_type_name(fs)} at offset {offset}")
            for f in walk_files(fs, include_deleted, self.log, cancel):
                # A reallocated name's bytes belong to another file: match it by
                # name only, so the row exists, and never read it.
                matched = (sel.match(f.name, f.size, lambda n, f=f: f.read(0, n)) if not f.realloc
                           else ("extension" if os.path.splitext(f.name)[1].lower() in sel.exts else None))
                if not matched:
                    continue
                yield FoundFile(
                    "e01", self.info.path, f"p{part}/{f.path}", f.name, os.path.splitext(f.name)[1].lower(),
                    f.size, f.mtime, f.atime, f.ctime, f.crtime, f.fs_type, matched,
                    allocated=f.allocated, realloc=f.realloc, _image=f,
                )

    def close(self) -> None:
        self.img.close()

    def __enter__(self) -> "E01Source":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
