# File Organizer

A Python script that helps organize files by their extensions. It recursively scans specified directories and copies files with matching extensions to a designated storage location, organizing them into extension-specific folders.

This is very helpful when needing to save user files off of a computer that needs to be rebuilt.

## Features

- Scans multiple source directories recursively
- Organizes files by extension into separate folders
- Supports a configurable list of file extensions
- Maintains original files (copies, doesn't move)
- Preserves file metadata during copying
- Saves configuration for repeated use
- Cross-platform support (Windows, WSL, Linux)
- Detailed logging of operations

## Prerequisites

- Python 3.6 or higher
- No additional dependencies required (uses standard library only)

## Setup

1. Clone or download this repository
2. Ensure you have the following files:
   - `file_organizer.py` - The main script
   - `file-extensions.txt` - List of file extensions to process
   - `file_organizer.config.ini` - Configuration file (created automatically)

## Usage

1. Run the script:
   ```bash
   python file_organizer.py
   ```

2. On first run, you'll be prompted to enter:
   - Search paths (comma-separated list of directories to scan)
   - Storage location (where organized files will be stored)
   - Extensions file path (path to file-extensions.txt)

3. On subsequent runs, previous values will be offered as defaults. Press Enter to use them or type new values.

## Configuration Files

### file-extensions.txt
- Lists file extensions to process
- Format:
  ```
  # Section Header (optional)
  .ext1, .ext2 (Optional description)
  .ext3 (Another description)
  ```
- Lines starting with # are treated as section headers
- Text in parentheses is treated as comments
- Multiple extensions can be comma-separated

> **TIP**
> Modify this list to include only the files you want.

### file_organizer.config.ini
- Automatically created and updated
- Stores last used:
  - Search paths
  - Storage location
  - Extensions file path

