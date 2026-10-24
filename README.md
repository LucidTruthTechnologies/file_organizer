# File Organizer

Copies files out of folders or out of an E01 forensic image and sorts them into one folder per file extension. It can also package the sorted result as a new E01. It ships as a single Windows executable with a graphical window, and it also runs from the command line.

Typical uses: saving a user's files off a computer that is about to be rebuilt, or pulling every image and video out of an evidence image during intake triage.

## Acknowledgment

This utility was inspired by `sorter`, written by Brian Carrier as part of [The Sleuth Kit](https://www.sleuthkit.org/sleuthkit/). Sorter walks a file system image and organizes its files into categories by type. File Organizer applies the same idea to both live folders and E01 images, and it reads those images with The Sleuth Kit through `pytsk3`. Thanks to Brian Carrier for The Sleuth Kit and for the idea.

## Features

- Sources can be folders, E01 images, or a mix, several in one run
- E01 images are read in place, read-only, through libewf and The Sleuth Kit: no mounting, no driver, no administrator rights
- Every filesystem in the image is searched (each partition, or a bare volume), and deleted files whose name entry survives can be included
- Files are copied into `Extension-.jpg`, `Extension-.mp4` and similar folders; originals are never moved or modified (on a live folder, reading a file may update its last-accessed time if Windows tracks it)
- Same-named files never overwrite each other: the second `beach.jpg` becomes `beach (2).jpg`
- `manifest.csv` maps every copy back to its source path, with size, SHA-256, and the original modified and accessed times in UTC
- The modified and accessed times recorded before each file is read are set on its copy
- `--images` and `--videos` collect only images, only videos, or both together
- Optional E01 export of the sorted result, with examiner, case, evidence and notes in the E01 header
- A log of every action, `file_organization_log.txt`, in the output folder

## Download and run (Windows)

Download `file-organizer.exe` from the latest successful run of the **build-windows** workflow on the repository's Actions tab (artifact `file-organizer-windows`), or from a release when one is tagged. Nothing needs installing.

Double-click it, or run it with no arguments, and the window opens:

1. **Sources**: click **Add folder...** or **Add E01...** (pick any segment of the set). Add as many as you need.
2. **Output folder**: click **Browse...** and pick or create the folder that receives the sorted copies.
3. **What to collect**: leave both boxes clear to use the extension list, tick **Images only** or **Videos only**, or tick both for images and videos.
4. **Export (optional)**: tick **Also write an E01**, choose where with **Save as...**, and fill in the header fields.
5. Click **Run**. Progress and the log appear in the window; **Cancel** stops after the current file.

## Command line

```text
file-organizer --source PATH [--source PATH ...] --output DIR [options]
```

| Option | Meaning |
| --- | --- |
| `--source PATH` | A folder or an E01 (any segment) to search. Repeat for several. |
| `--output DIR` | Folder that receives the `Extension-<ext>` folders. Created if absent. |
| `--images` | Collect image files only. |
| `--videos` | Collect video files only. |
| `--images --videos` | Collect images and videos, nothing else. |
| `--extensions FILE` | Use your own extension list instead of the bundled one. Ignored with `--images` or `--videos`. |
| `--include-deleted` | E01 sources: also copy deleted files whose name entry survives. |
| `--export-e01 PATH` | Also write the sorted files into a new E01 at `PATH`. |
| `--examiner`, `--case`, `--evidence`, `--notes` | E01 header values for the export. |
| `--segment-size-mib N` | E01 segment size, default 2048. |
| `--overwrite` | Replace an existing export E01. |
| `--no-gui` | Never open the window. |
| `-v`, `--version` / `-h`, `--help` | Version and full help. |

Examples:

```text
file-organizer --source C:\Users\alice --output E:\rescue
file-organizer --source D:\cases\0042\laptop.E01 --output D:\cases\0042\media --images --videos
file-organizer --source laptop.E01 --output media --videos --export-e01 media.E01 --examiner "LTT" --case 0042
```

Exit codes: 0 success, 1 one or more files failed to copy (or another error), 2 usage error, 4 source not found, 5 permission denied, 6 stopped by Cancel.

## What gets collected

With neither switch, the run collects every extension in the extension list. The bundled list, `src/file_organizer/file-extensions.txt`, covers documents, spreadsheets, presentations, images, audio, video, archives, design files, source code, databases and game data. To use your own, copy it, trim it, and pass it with `--extensions` (or choose it in the window). Format:

```text
# Section header (optional)
.ext1, .ext2 (optional description)
.ext3 (another description)
```

Lines starting with `#` are headers, text in parentheses is a comment, several extensions may share a line, and the leading dot is optional.

`--images` and `--videos` replace the list with built-in sets. The image set covers common photo, phone, editor and vector formats plus camera raw (`.cr2`, `.nef`, `.arw`, `.dng` and others). The video set is the same one `video-frame-triage` uses (`.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.3gp`, `.ts` and others). Matching is by extension, without regard to case.

## Output

```text
<output folder>/
  Extension-.jpg/beach.jpg
  Extension-.jpg/beach (2).jpg
  Extension-.mp4/holiday.mp4
  manifest.csv
  file_organization_log.txt
```

`manifest.csv` has one row per file found: the output path, status (`copied`, `copied-partial`, `failed`, `skipped`), whether it came from a folder or an E01, the source, the path inside the source (E01 paths start with the partition, such as `p2/Users/alice/...`), whether it was allocated or deleted, the size, bytes copied, SHA-256, and the original modified and accessed times in UTC. Running again into the same output folder adds to it without replacing anything; the new run's manifest is named `manifest-<date>-<time>.csv`. If a run stops on an error, the manifest still records every file copied before it stopped.

File names come from evidence, so a manifest cell that begins with `=`, `+`, `-` or `@` gets a leading apostrophe. That stops spreadsheet programs from running it as a formula. Remove the apostrophe to recover the exact name.

Names that Windows cannot store are made safe in the output folder: characters such as `:` and `?` become `_`, device names such as `CON` get a leading `_`, and very long names are shortened. The manifest keeps the original path.

A deleted file whose metadata has since been reused by another file is listed as `skipped` and never copied, because its bytes now belong to the other file. A deleted file that can only be partly read is copied as far as it reads, marked `copied-partial`, and its hash covers only the bytes copied.

## E01 export

The export writes the sorted folder, the manifest and the log into a FAT32 volume and wraps that volume in an EnCase 6 E01 (deflate compressed, MD5 of the media stored in the image; the run also logs its SHA-256). Tools that read E01, such as Oxygen Forensic Detective, FTK Imager, Autopsy or The Sleuth Kit, can open it. The export is verified in testing with `ewfverify` and with The Sleuth Kit.

Things to know:

- FAT32 cannot hold a file of 4 GiB or more. Such a file is still copied to the output folder but left out of the E01, and its manifest row says so (`in_e01` is `no`).
- FAT32 stores times as local wall-clock time with no time zone. The times inside the E01 are the original modified times in the exporting machine's time zone; `manifest.csv` holds the authoritative UTC times.
- The volume is built beside the export before it is compressed, so allow free space for about twice the size of the sorted files.
- The export must go outside the output folder and outside every source folder, so it never lands in the evidence or among the copies.
- If the export fails or is canceled, the manifest's `in_e01` column says `export not written`.

## Building from source

On Windows with Python 3.11 or later:

```powershell
.\build.ps1
```

This creates a virtual environment, installs the pinned dependencies (`libewf-python`, `pytsk3`, `pytest`, `pyinstaller`), runs the tests, and builds `dist\file-organizer.exe`. GitHub Actions does the same on every push (`.github/workflows/build-windows.yml`), runs the built exe on a synthetic E01, and publishes the exe as an artifact.

The application icon is `src/file_organizer/icon.ico`, drawn from `assets/icon.svg` (32 px and up) and `assets/icon-small.svg` (16 and 24 px) in the Lucid Truth Technologies palette.

To run from source on any platform: `pip install -e .`, then `file-organizer` or `python -m file_organizer`.

The E01 writer and the FAT32 builder are pure Python, shared with `video-frame-triage`, because the `libewf-python` wheel cannot write E01 files.
