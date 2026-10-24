"""Orchestrate: walk every source, copy wanted files into Extension-<ext>
folders, write a manifest, and optionally package the result as an E01.

Nothing is overwritten: a second file with a name already taken in its
extension folder is written as "name (2).ext", and the manifest maps every
output file back to where it came from, with its SHA-256.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import platform
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

import pyewf

from . import TOOL_NAME, VERSION
from .ewf_writer import (DEFAULT_SEGMENT_SIZE, MIN_SEGMENT_SIZE, EwfMetadata, existing_segments,
                         segment_stem, write_file_as_e01)
from .extensions import select_extensions
from .fat32 import Fat32Builder
from .sources import E01Source, FoundFile, walk_folder

Log = Callable[[str], None]
Progress = Callable[[int, int, str], None]  # done, total, stage
Cancel = Callable[[], bool]

LOG_NAME = "file_organization_log.txt"
MANIFEST_NAME = "manifest.csv"
FAT32_MAX_FILE = 4 * 1024 ** 3 - 1  # FAT32 cannot hold a file of 4 GiB or more
# UTF-16 units per name: room for a " (nnn)" suffix under FAT32's 195-unit
# reader limit (fat32.MAX_NAME_UNITS) and NTFS's 255.
MAX_NAME_UNITS = 170
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_DEVICE_NAME = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|com[0-9¹²³]|lpt[0-9¹²³])$",
                          re.IGNORECASE)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
MANIFEST_FIELDS = ["output_path", "status", "source_kind", "source", "path_in_source", "allocated",
                   "size_bytes", "bytes_copied", "sha256", "modified_utc", "accessed_utc", "in_e01", "note"]


class CancelledError(Exception):
    pass


@dataclass
class Options:
    sources: List[str]
    output_dir: str
    images: bool = False
    videos: bool = False
    extensions_file: Optional[str] = None  # None means the bundled list
    include_deleted: bool = False          # E01 sources only
    export_e01: Optional[str] = None
    segment_size: int = DEFAULT_SEGMENT_SIZE
    examiner: str = ""
    case_number: str = ""
    evidence_number: str = ""
    notes: str = ""
    overwrite: bool = False                # replace an existing export E01


@dataclass
class Summary:
    files_found: int = 0
    files_copied: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    bytes_copied: int = 0
    counts_by_ext: Dict[str, int] = field(default_factory=dict)
    manifest: str = ""
    log_file: str = ""
    e01_segments: List[str] = field(default_factory=list)
    e01_md5: str = ""
    e01_sha256: str = ""
    e01_excluded: int = 0
    cancelled: bool = False


def _utc(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    try:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, OverflowError, ValueError):
        return ""


def _units(s: str) -> int:
    """Length in UTF-16 code units, which is what NTFS and FAT32 limit."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def safe_name(name: str) -> str:
    """A file name every Windows and FAT32 reader accepts. Names from an image
    (ext4, HFS+) may carry characters Win32 refuses; the original name is kept
    in the manifest."""
    stem, ext = os.path.splitext(name)
    stem = _BAD_CHARS.sub("_", stem)
    ext = _BAD_CHARS.sub("_", ext)[:16]
    budget = MAX_NAME_UNITS - _units(ext)
    while stem and _units(stem) > budget:
        stem = stem[:-1]
    stem = stem.rstrip(" .")
    # Windows treats a device name before the FIRST dot as the device
    # ("NUL.tar.gz" opens NUL), so test that part, not the whole stem.
    if not stem or _DEVICE_NAME.match(stem.split(".", 1)[0].rstrip(" ")):
        stem = "_" + stem
    return stem + ext


def _is_inside(child: str, parent: str) -> bool:
    child = os.path.normcase(os.path.abspath(child))
    parent = os.path.normcase(os.path.abspath(parent))
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)


def is_e01_path(path: str) -> bool:
    return os.path.isfile(path)


def validate(opts: Options) -> None:
    if not opts.sources:
        raise ValueError("at least one source (a folder or an E01) is required")
    for src in opts.sources:
        if not os.path.exists(src):
            raise FileNotFoundError(f"source not found: {src}")
        if not os.access(src, os.R_OK):
            raise PermissionError(f"cannot read source: {src}")
        # Refuse a non-E01 file now, before earlier sources are copied.
        if os.path.isfile(src) and not pyewf.check_file_signature(os.path.abspath(src)):
            raise ValueError(f"not an E01 (EWF) image: {src}")
    if not opts.output_dir:
        raise ValueError("an output folder is required")
    out = os.path.abspath(opts.output_dir)
    parent = os.path.dirname(out)
    if not os.path.isdir(out) and not os.path.isdir(parent):
        raise FileNotFoundError(f"output folder's parent not found: {parent}")
    for src in opts.sources:
        if os.path.isdir(src) and _is_inside(src, out):
            raise ValueError(f"source {src} is inside the output folder")
        if os.path.isfile(src) and _is_inside(src, out):
            raise ValueError(f"source image {src} is inside the output folder")
    if opts.extensions_file and not (opts.images or opts.videos) and not os.path.isfile(opts.extensions_file):
        raise FileNotFoundError(f"extension list not found: {opts.extensions_file}")
    if opts.export_e01:
        e01_dir = os.path.dirname(os.path.abspath(opts.export_e01))
        if not os.path.isdir(e01_dir):
            raise FileNotFoundError(f"E01 export folder not found: {e01_dir}")
        if not os.access(e01_dir, os.W_OK):
            raise PermissionError(f"cannot write to E01 export folder: {e01_dir}")
        opts.export_e01 = segment_stem(opts.export_e01) + ".E01"
        # The export and its working volume must never land in the evidence
        # or among the sorted copies.
        if _is_inside(opts.export_e01, out):
            raise ValueError("the E01 export cannot be inside the output folder")
        for src in opts.sources:
            if os.path.isdir(src) and _is_inside(opts.export_e01, src):
                raise ValueError(f"the E01 export cannot be inside the source folder {src}")
        for src in opts.sources:
            if os.path.isfile(src) and os.path.normcase(segment_stem(os.path.abspath(src))) == \
                    os.path.normcase(segment_stem(os.path.abspath(opts.export_e01))):
                raise ValueError("the E01 export would overwrite the source image")
        clash = existing_segments(opts.export_e01)
        if clash and not opts.overwrite:
            raise FileExistsError(f"E01 export exists (use overwrite): {', '.join(clash)}")
        if opts.segment_size < MIN_SEGMENT_SIZE:
            raise ValueError(f"segment size must be at least {MIN_SEGMENT_SIZE // 1024 ** 2} MiB")


class _Namer:
    """Unique, case-insensitive names per extension folder, including names
    left by an earlier run into the same output folder. Keys are upper-cased,
    close to how NTFS compares names; the exclusive create in copy_to is the
    backstop for any pair this still misjudges."""

    def __init__(self) -> None:
        self.taken: Dict[str, Set[str]] = {}

    def claim(self, folder: str, name: str) -> str:
        used = self.taken.get(folder)
        if used is None:
            used = {n.upper() for n in os.listdir(folder)} if os.path.isdir(folder) else set()
            self.taken[folder] = used
        stem, ext = os.path.splitext(name)
        candidate, n = name, 1
        while candidate.upper() in used:
            n += 1
            candidate = f"{stem} ({n}){ext}"
        used.add(candidate.upper())
        return candidate


def _claim_manifest(out_root: str) -> str:
    """Create this run's manifest file exclusively. An earlier run's
    manifest is a record and is never replaced."""
    names = [MANIFEST_NAME] + [time.strftime("manifest-%Y%m%d-%H%M%S") + (f"-{n}" if n > 1 else "") + ".csv"
                               for n in range(1, 1000)]
    for name in names:
        path = os.path.join(out_root, name)
        try:
            with open(path, "x", encoding="utf-8"):
                return path
        except FileExistsError:
            continue
    raise FileExistsError(f"no free manifest name in {out_root}")


def run(opts: Options, log: Log = print, progress: Progress = lambda _d, _t, _s: None,
        cancel: Cancel = lambda: False) -> Summary:
    validate(opts)
    exts, ext_origin = select_extensions(opts.images, opts.videos, opts.extensions_file)
    out_root = os.path.abspath(opts.output_dir)
    os.makedirs(out_root, exist_ok=True)
    summary = Summary(log_file=os.path.join(out_root, LOG_NAME), manifest=_claim_manifest(out_root))
    # backslashreplace: a name that is not valid Unicode (an unpaired
    # surrogate on NTFS) must never stop the run halfway.
    log_fh = open(summary.log_file, "a", encoding="utf-8", errors="backslashreplace")

    def say(msg: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_fh.write(f"{stamp} - {msg}\n")
        log_fh.flush()
        log(msg)

    rows: List[Dict[str, object]] = []
    namer = _Namer()
    t0 = time.time()
    try:
        say(f"{TOOL_NAME} {VERSION}: collecting {len(exts)} extensions from the {ext_origin}")
        say(f"output folder {out_root}")
        for s_idx, src in enumerate(opts.sources, start=1):
            if cancel():
                raise CancelledError()
            progress(s_idx - 1, len(opts.sources), f"source {s_idx}/{len(opts.sources)}: {os.path.basename(src)}")
            if is_e01_path(src):
                say(f"opening E01 {src} read-only")
                with E01Source(src, say) as e01:
                    info = e01.source_info
                    say(f"media {info.media_size} bytes, {len(info.segments)} segment(s), "
                        f"stored hashes {info.stored_hashes or 'none'}")
                    for found in e01.walk(exts, opts.include_deleted, cancel):
                        _take(found, out_root, namer, rows, summary, say)
            else:
                say(f"scanning folder {src}")
                for found in walk_folder(src, exts, say, cancel, skip=out_root):
                    _take(found, out_root, namer, rows, summary, say)
            if cancel():
                raise CancelledError()
        progress(len(opts.sources), len(opts.sources), "files copied")

        if opts.export_e01:
            _mark_exportable(rows, say)
        _write_manifest(summary.manifest, rows)
        say(f"copied {summary.files_copied} of {summary.files_found} files "
            f"({summary.bytes_copied} bytes), {summary.files_failed} failed, {summary.files_skipped} skipped "
            f"in {time.time() - t0:.1f} s")
        for ext in sorted(summary.counts_by_ext):
            say(f"{ext}: {summary.counts_by_ext[ext]}")
        say(f"manifest {summary.manifest}")

        if opts.export_e01:
            try:
                if cancel():
                    raise CancelledError()
                _export(opts, out_root, rows, summary, say, progress, cancel)
            except BaseException:
                # The manifest said "yes" for an E01 that was never written.
                for row in rows:
                    if row["in_e01"] == "yes":
                        row["in_e01"] = "export not written"
                raise
        return summary
    except CancelledError:
        summary.cancelled = True
        say("cancelled; files copied so far stay in the output folder")
        _write_manifest(summary.manifest, rows)
        return summary
    except BaseException as exc:
        # Any other failure: the copies already made keep their record.
        say(f"run stopped by an error: {type(exc).__name__}: {exc}")
        _write_manifest(summary.manifest, rows)
        raise
    finally:
        log_fh.close()


def _take(found: FoundFile, out_root: str, namer: _Namer, rows: List[Dict[str, object]],
          summary: Summary, say: Log) -> None:
    summary.files_found += 1
    row: Dict[str, object] = {
        "output_path": "", "status": "", "source_kind": found.source_kind, "source": found.source,
        "path_in_source": found.path, "allocated": found.allocated, "size_bytes": found.size,
        "bytes_copied": "", "sha256": "", "modified_utc": _utc(found.mtime),
        "accessed_utc": _utc(found.atime), "in_e01": "", "note": "",
    }
    rows.append(row)
    if found.realloc:
        row["status"] = "skipped"
        row["note"] = "deleted name points at metadata reused by another file; not copied"
        summary.files_skipped += 1
        say(f"skipped {found.path}: deleted name with reallocated metadata")
        return
    folder_name = f"Extension-{safe_name(found.ext)}"
    folder = os.path.join(out_root, folder_name)
    os.makedirs(folder, exist_ok=True)
    base = safe_name(found.name)
    notes: List[str] = []
    for _attempt in range(1000):
        name = namer.claim(folder, base)
        dest = os.path.join(folder, name)
        try:
            sha, copied, time_note = found.copy_to(dest)
            break
        except FileExistsError:
            continue  # a name the namer thought free exists on disk; take the next one
        except OSError as exc:
            row["status"], row["note"] = "failed", str(exc)
            summary.files_failed += 1
            say(f"error copying {found.path}: {exc}")
            try:
                os.remove(dest)
            except OSError:
                pass
            return
    else:
        row["status"], row["note"] = "failed", "no free output name"
        summary.files_failed += 1
        say(f"error copying {found.path}: no free output name")
        return
    if not os.path.isfile(dest):
        # A device name Windows intercepts swallows the bytes and leaves no file.
        row["status"], row["note"] = "failed", f"written to {name} but no file exists there"
        summary.files_failed += 1
        say(f"error copying {found.path}: {row['note']}")
        return
    row["output_path"] = f"{folder_name}/{name}"
    row["sha256"], row["bytes_copied"] = sha, copied
    partial = copied < found.size
    row["status"] = "copied-partial" if partial else "copied"
    if partial:
        notes.append(f"only {copied} of {found.size} bytes readable; hash covers the copied bytes")
    if time_note:
        notes.append(time_note)
    row["note"] = "; ".join(notes)
    summary.files_copied += 1
    summary.bytes_copied += copied
    summary.counts_by_ext[found.ext] = summary.counts_by_ext.get(found.ext, 0) + 1
    say(f"copied: {found.path} -> {dest}{' (partial)' if partial else ''}")


def _mark_exportable(rows: List[Dict[str, object]], say: Log) -> None:
    for row in rows:
        if not row["output_path"]:
            row["in_e01"] = "no"
            continue
        if int(row["bytes_copied"]) > FAT32_MAX_FILE:  # type: ignore[call-overload]
            row["in_e01"] = "no"
            row["note"] = (str(row["note"]) + "; " if row["note"] else "") + "4 GiB or larger: FAT32 cannot hold it"
            say(f"not in E01 (4 GiB or larger): {row['output_path']}")
            continue
        row["in_e01"] = "yes"


def _export(opts: Options, out_root: str, rows: List[Dict[str, object]], summary: Summary,
            say: Log, progress: Progress, cancel: Cancel) -> None:
    assert opts.export_e01 is not None
    say(f"building FAT32 volume for {opts.export_e01}")
    builder = Fat32Builder(label="ORGANIZED")
    for row in rows:
        if row["in_e01"] == "yes":
            rel = str(row["output_path"])
            full = os.path.join(out_root, *rel.split("/"))
            builder.add_file(rel, full, mtime=os.path.getmtime(full))
        elif row["output_path"]:
            summary.e01_excluded += 1
    for path in (summary.manifest, summary.log_file):
        builder.add_file(os.path.basename(path), path)
    e01_dir = os.path.dirname(os.path.abspath(opts.export_e01))
    work = tempfile.mkdtemp(prefix="fo_", dir=e01_dir)
    try:
        raw = os.path.join(work, "volume.img")
        size = builder.build(raw, lambda d, t: progress(d, t, "writing volume"))
        if cancel():
            raise CancelledError()
        say(f"volume image {size} bytes; writing E01")
        meta = EwfMetadata(
            case_number=opts.case_number, evidence_number=opts.evidence_number,
            description=f"Files organized by extension from {', '.join(os.path.basename(os.path.normpath(s)) for s in opts.sources)}"[:200],
            examiner_name=opts.examiner, notes=opts.notes,
            version=f"fo {VERSION}", platform=platform.system(),
        )
        pending = os.path.join(work, os.path.basename(opts.export_e01))
        w = write_file_as_e01(raw, pending, meta, opts.segment_size, lambda d, t: progress(d, t, "writing E01"))
        os.remove(raw)
        if opts.overwrite:
            # Remove the whole stale set, so a shorter new set never leaves an
            # orphan segment that libewf would pull back in.
            for stale in existing_segments(opts.export_e01):
                os.remove(stale)
        for seg in w.segments:
            dst = os.path.join(e01_dir, os.path.basename(seg))
            shutil.move(seg, dst)
            summary.e01_segments.append(dst)
        summary.e01_md5, summary.e01_sha256 = w.md5.hexdigest(), w.sha256.hexdigest()
        say(f"E01 written: {', '.join(summary.e01_segments)} md5 {summary.e01_md5} sha256 {summary.e01_sha256}"
            + (f"; {summary.e01_excluded} file(s) left out, see manifest" if summary.e01_excluded else ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _cell(value: object) -> object:
    """Names come from evidence; a cell starting with = + - @ would run as a
    formula when the manifest is opened in a spreadsheet. A leading
    apostrophe keeps it text (README documents this)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _write_manifest(path: str, rows: List[Dict[str, object]]) -> None:
    with open(path, "w", encoding="utf-8", errors="backslashreplace", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: _cell(v) for k, v in r.items()})

