"""file-organizer - command line entry point.

With no arguments the graphical window opens. With --source and --output it
runs headless and prints progress to stderr. Exit codes follow the house
coding standard: 0 ok, 1 error, 2 usage, 3 missing dependency, 4 not found,
5 permission denied, 6 cancelled.
"""

from __future__ import annotations

import argparse
import sys

from . import BRAND, TOOL_NAME, VERSION
from .ewf_writer import DEFAULT_SEGMENT_SIZE

# Exit codes per the house coding standard, matched in order (subclasses first).
_EXIT_CODES = [
    (FileNotFoundError, 4),
    (PermissionError, 5),
    (FileExistsError, 2),
    (ValueError, 2),
    (RuntimeError, 3),
    (OSError, 1),
]

EPILOG = f"""
EXAMPLES:
    {TOOL_NAME}
        Open the graphical window.
    {TOOL_NAME} --source C:\\Users\\alice --output E:\\rescue
        Copy every file type in the bundled extension list, sorted by extension.
    {TOOL_NAME} --source D:\\cases\\0042\\laptop.E01 --output D:\\cases\\0042\\media --images --videos
        Pull only images and videos out of an E01.
    {TOOL_NAME} --source laptop.E01 --output media --videos --export-e01 media.E01 --examiner "LTT" --case 0042
        Also package the sorted videos as a new E01.

DESCRIPTION:
    Walks each source (a folder, or every filesystem inside an E01, opened
    read-only with no mount and no driver), copies the files whose extension
    is wanted into Extension-<ext> folders under the output folder, and writes
    manifest.csv mapping every copy to its source path and SHA-256. Same-named
    files never overwrite each other. --images and --videos replace the
    extension list with built-in sets; together they collect both. With
    --export-e01 the sorted folder is also written as a FAT32 volume inside a
    new E01. Inspired by Brian Carrier's sorter from The Sleuth Kit.
    {BRAND}.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Copy files out of folders or an E01, sorted by extension",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("--source", action="append", default=[], metavar="PATH",
                   help="folder or E01 (any segment) to search; repeat for several")
    p.add_argument("--output", help="folder that receives the Extension-<ext> folders (created if absent)")
    p.add_argument("--images", action="store_true", help="collect image files only (combine with --videos)")
    p.add_argument("--videos", action="store_true", help="collect video files only (combine with --images)")
    p.add_argument("--extensions", metavar="FILE",
                   help="extension list to use instead of the bundled one (ignored with --images/--videos)")
    p.add_argument("--include-deleted", action="store_true",
                   help="E01 sources: also copy deleted files whose name entry survives")
    p.add_argument("--export-e01", metavar="PATH", help="also write the sorted files into a new E01 here")
    p.add_argument("--segment-size-mib", type=int, default=DEFAULT_SEGMENT_SIZE // 1024 ** 2,
                   help=f"E01 segment size in MiB (default {DEFAULT_SEGMENT_SIZE // 1024 ** 2})")
    p.add_argument("--examiner", default="", help="examiner name for the E01 header")
    p.add_argument("--case", default="", help="case number for the E01 header")
    p.add_argument("--evidence", default="", help="evidence number for the E01 header")
    p.add_argument("--notes", default="", help="notes for the E01 header")
    p.add_argument("--overwrite", action="store_true", help="replace an existing export E01")
    p.add_argument("--no-gui", action="store_true", help="never open the window, even without arguments")
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.source and not args.output and not args.no_gui:
        from .gui import launch
        return launch()
    if not args.source or not args.output:
        parser.error("--source and --output are both required for a headless run")
    from .pipeline import Options, run

    opts = Options(
        sources=args.source, output_dir=args.output, images=args.images, videos=args.videos,
        extensions_file=args.extensions, include_deleted=args.include_deleted,
        export_e01=args.export_e01, segment_size=args.segment_size_mib * 1024 ** 2,
        examiner=args.examiner, case_number=args.case, evidence_number=args.evidence,
        notes=args.notes, overwrite=args.overwrite,
    )

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        summary = run(opts, log=log)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"{TOOL_NAME}: Error: {exc}", file=sys.stderr)
        return next(code for kind, code in _EXIT_CODES if isinstance(exc, kind))
    if summary.cancelled:
        return 6
    print(f"files_found={summary.files_found} files_copied={summary.files_copied} "
          f"files_failed={summary.files_failed} files_skipped={summary.files_skipped} "
          f"manifest={summary.manifest}"
          + (f" e01={','.join(summary.e01_segments)} e01_md5={summary.e01_md5}" if summary.e01_segments else ""))
    return 1 if summary.files_failed else 0


if __name__ == "__main__":
    sys.exit(main())
