# PyInstaller spec for the single-file Windows build.
# Build: pyinstaller file-organizer.spec
# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None
here = os.path.abspath(".")
ext_list = os.path.join(here, "src", "file_organizer", "file-extensions.txt")
icon_src = os.path.join(here, "src", "file_organizer", "icon.ico")  # sources: assets/icon*.svg

a = Analysis(
    ["src/file_organizer/__main__.py"],
    pathex=["src"],
    binaries=[],
    # the bundled extension list (extensions.BUNDLED_LIST) and the window icon (gui.ICON_PATH)
    datas=[(ext_list, "file_organizer"), (icon_src, "file_organizer")],
    hiddenimports=["tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "PIL"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="file-organizer",
    icon=icon_src,
    debug=False,
    strip=False,
    upx=False,
    console=True,  # keep a console so headless runs print progress; the window opens on top of it
    disable_windowed_traceback=False,
)
