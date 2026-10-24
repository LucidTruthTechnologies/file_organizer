"""GUI construction check. Skips where Tk cannot open a display (Linux CI
without X); runs on the Windows runner, where Tk is part of the interpreter."""

from __future__ import annotations

import os

import pytest

tk = pytest.importorskip("tkinter")


def test_window_builds_and_options_assemble():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    try:
        from file_organizer.gui import App

        app = App(root)
        from file_organizer.gui import ICON_PATH

        assert os.path.isfile(ICON_PATH)  # App() set it on Windows without raising
        assert app.images.get() is False and app.videos.get() is False
        assert str(app.cancel_btn["state"]) == "disabled"
        assert str(app.export_entry["state"]) == "disabled"
        app.images.set(True)
        app._sync()
        assert str(app.ext_entry["state"]) == "disabled"  # a built-in set replaces the list
        app._add("C:/cases/in.E01")
        app._add("C:/Users/alice")
        app.out_var.set("D:/out")
        app.export.set(True)
        app.export_var.set("D:/out.E01")
        opts = app._options()
        assert len(opts.sources) == 2 and opts.images and not opts.videos
        assert opts.extensions_file is None and opts.export_e01 == "D:/out.E01"
        root.update()
    finally:
        root.destroy()
