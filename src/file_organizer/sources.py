"""Walk a source (a folder, or every filesystem inside an E01) and yield the
files whose extension is wanted. Both kinds yield the same record, which
knows how to copy itself out and hash the bytes as they pass.

The E01 is read in-process through libewf and The Sleuth Kit: no mount, no
driver, no administrator right, and the image is never opened for writing.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Set

import pytsk3

from .ewf_reader import EwfImgInfo, SourceInfo, open_e01

COPY_BLOCK = 4 * 1024 * 1024
Log = Callable[[str], None]
Cancel = Callable[[], bool]


@dataclass
class PartitionInfo:
    index: int
    description: str
    start_sector: int
    length_sectors: int
    fs_type: str         # filesystem name, or "unreadable: <reason>"


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
    allocated: bool = True
    realloc: bool = False  # deleted name whose metadata now belongs to another file
    _fs: Optional[pytsk3.FS_Info] = field(default=None, repr=False)
    _inode: int = 0

    def copy_to(self, dest: str) -> tuple[str, int, str]:
        """Copy to a NEW file `dest` (FileExistsError if anything is there),
        then stamp the modified and accessed times recorded at discovery.
        Returns (SHA-256 of the bytes copied, bytes copied, note). A short
        read (a broken run on a deleted file) is returned as such, never
        padded. The note is non-empty only when the times could not be set."""
        h = hashlib.sha256()
        copied = 0
        with open(dest, "xb") as out:
            if self._fs is None:
                with open(self.path, "rb") as src:
                    for block in iter(lambda: src.read(COPY_BLOCK), b""):
                        out.write(block)
                        h.update(block)
                        copied += len(block)
            else:
                f = self._fs.open_meta(inode=self._inode)
                while copied < self.size:
                    try:
                        block = f.read_random(copied, min(COPY_BLOCK, self.size - copied))
                    except OSError:
                        break
                    if not block:
                        break
                    out.write(block)
                    h.update(block)
                    copied += len(block)
        # The times captured before reading, not copystat afterwards: reading
        # can bump the source's access time, and copystat would also carry a
        # read-only flag that stops a failed copy being cleaned up.
        note = ""
        if self.mtime is not None:
            try:
                os.utime(dest, (self.atime if self.atime is not None else self.mtime, self.mtime))
            except (OSError, OverflowError, ValueError) as exc:
                note = f"times not set on the copy ({exc}); the manifest keeps the originals"
        return h.hexdigest(), copied, note


def _ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def walk_folder(root: str, exts: Set[str], log: Log, cancel: Cancel,
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
            ext = _ext(name)
            if ext not in exts:
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError as exc:
                log(f"cannot stat {full}: {exc.strerror}")
                continue
            yield FoundFile("folder", root, full, name, ext, st.st_size, st.st_mtime, st.st_atime)


def iter_filesystems(img: pytsk3.Img_Info, log: Log,
                     inventory: List[PartitionInfo]) -> Iterator[tuple[int, int, pytsk3.FS_Info]]:
    """Yield (partition index, byte offset, FS_Info) for every readable
    filesystem; every allocated partition is recorded in `inventory`.
    shortcut: no pool layer (pytsk3 exposes no Pool_Info), so APFS containers,
    BitLocker, LVM and VMFS volumes are recorded as unreadable, not walked."""
    found = False
    try:
        vol = pytsk3.Volume_Info(img)
    except OSError:
        vol = None
    if vol is not None:
        bps = vol.info.block_size or 512
        for part in vol:
            if not (part.flags & pytsk3.TSK_VS_PART_FLAG_ALLOC):
                continue
            offset = part.start * bps
            desc = part.desc.decode("utf-8", "replace") if isinstance(part.desc, bytes) else str(part.desc)
            try:
                fs = pytsk3.FS_Info(img, offset=offset)
            except OSError as exc:
                log(f"partition {part.addr} at offset {offset}: no readable filesystem ({exc})")
                inventory.append(PartitionInfo(part.addr, desc, part.start, part.len, f"unreadable: {exc}"))
                continue
            found = True
            inventory.append(PartitionInfo(part.addr, desc, part.start, part.len, _fs_type_name(fs)))
            yield part.addr, offset, fs
    if not found:
        try:
            fs = pytsk3.FS_Info(img, offset=0)
        except OSError as exc:
            log(f"no partition table and no filesystem at offset 0 ({exc})")
            inventory.append(PartitionInfo(0, "whole image", 0, 0, f"unreadable: {exc}"))
            return
        inventory.append(PartitionInfo(0, "whole image (no partition table)", 0, 0, _fs_type_name(fs)))
        yield 0, 0, fs


def _fs_type_name(fs: pytsk3.FS_Info) -> str:
    return str(fs.info.ftype).replace("TSK_FS_TYPE_", "").lower()


def walk_image_fs(fs: pytsk3.FS_Info, label: str, source: str, exts: Set[str],
                  include_deleted: bool, log: Log, cancel: Cancel) -> Iterator[FoundFile]:
    seen_dirs: Set[int] = set()
    stack: List[tuple[str, int]] = [("", fs.info.root_inum)]
    while stack and not cancel():
        path, inum = stack.pop()
        if inum in seen_dirs:
            continue
        seen_dirs.add(inum)
        try:
            directory = fs.open_dir(inode=inum)
        except OSError as exc:
            log(f"{label}: cannot read directory {path or '/'} (inode {inum}): {exc}")
            continue
        for entry in directory:
            try:
                name = entry.info.name.name.decode("utf-8", "replace")
            except AttributeError:
                continue
            if name in (".", ".."):
                continue
            meta = entry.info.meta
            allocated = not (entry.info.name.flags & pytsk3.TSK_FS_NAME_FLAG_UNALLOC)
            if not allocated and not include_deleted:
                continue
            if meta is None:
                continue
            child = f"{path}/{name}" if path else name
            # A deleted name whose metadata entry has since been reused points
            # at another file's bytes (fls shows "(realloc)"). Never copy or
            # descend through it.
            realloc = False
            if not allocated:
                meta_alloc = bool(meta.flags & pytsk3.TSK_FS_META_FLAG_ALLOC)
                name_seq = getattr(entry.info.name, "meta_seq", None)
                meta_seq = getattr(meta, "seq", None)
                realloc = meta_alloc or (name_seq is not None and meta_seq is not None and name_seq != meta_seq)
            if meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                if allocated or not realloc:
                    stack.append((child, meta.addr))
                continue
            if meta.type != pytsk3.TSK_FS_META_TYPE_REG:
                continue
            ext = _ext(name)
            if ext not in exts:
                continue
            yield FoundFile(
                "e01", source, f"{label}/{child}", name, ext, max(meta.size, 0),
                float(meta.mtime) if meta.mtime else None, float(meta.atime) if meta.atime else None,
                allocated=allocated, realloc=realloc, _fs=fs, _inode=meta.addr,
            )


class E01Source:
    """An open E01. Use as a context manager so the handle is closed."""

    def __init__(self, path: str, log: Log) -> None:
        self.img: EwfImgInfo
        self.img, self.info = open_e01(path)
        self.log = log
        self.inventory: List[PartitionInfo] = []

    @property
    def source_info(self) -> SourceInfo:
        return self.info

    def walk(self, exts: Set[str], include_deleted: bool, cancel: Cancel) -> Iterator[FoundFile]:
        for part, offset, fs in iter_filesystems(self.img, self.log, self.inventory):
            label = f"p{part}"
            self.log(f"{os.path.basename(self.info.path)} partition {part}: {_fs_type_name(fs)} at offset {offset}")
            yield from walk_image_fs(fs, label, self.info.path, exts, include_deleted, self.log, cancel)

    def close(self) -> None:
        self.img.close()

    def __enter__(self) -> "E01Source":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
