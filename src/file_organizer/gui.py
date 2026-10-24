"""Tkinter window: add source folders or E01s, choose the output folder,
pick what to collect, optionally choose an E01 to export, run.

The pipeline runs in a worker thread and reports through a queue; the
window polls the queue so the log pane and progress bar stay live. Cancel
sets a flag the pipeline checks between files.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, Optional

from . import BRAND, TOOL_NAME, VERSION
from .extensions import BUNDLED_LIST
from .pipeline import Options, Summary, run, validate

# Package data; the PyInstaller spec ships it beside this module in the exe.
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{TOOL_NAME} {VERSION}")
        if os.name == "nt":
            # default= also applies to dialogs (file choosers, message boxes).
            root.iconbitmap(default=ICON_PATH)
        root.minsize(780, 680)
        self.q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.cancel_flag = threading.Event()
        self.worker: Optional[threading.Thread] = None

        pad: Dict[str, Any] = {"padx": 6, "pady": 3}
        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        # Sources
        src = ttk.LabelFrame(frm, text="Sources (folders or E01 images)", padding=8)
        src.grid(row=0, column=0, columnspan=3, sticky="ew", **pad)
        self.sources = tk.Listbox(src, height=4, selectmode="extended")
        self.sources.grid(row=0, column=0, rowspan=3, sticky="ew", **pad)
        ttk.Button(src, text="Add folder...", command=self.add_folder).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(src, text="Add E01...", command=self.add_e01).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(src, text="Remove", command=self.remove_source).grid(row=2, column=1, sticky="ew", **pad)
        src.columnconfigure(0, weight=1)

        # Output
        self.out_var = tk.StringVar()
        ttk.Label(frm, text="Output folder").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.out_var, width=70).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self.pick_output).grid(row=1, column=2, **pad)

        # What to collect
        what = ttk.LabelFrame(frm, text="What to collect", padding=8)
        what.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        self.images = tk.BooleanVar(value=False)
        self.videos = tk.BooleanVar(value=False)
        self.deleted = tk.BooleanVar(value=False)
        self.ext_var = tk.StringVar(value=BUNDLED_LIST)
        ttk.Checkbutton(what, text="Images only", variable=self.images, command=self._sync).grid(
            row=0, column=0, sticky="w", **pad)
        ttk.Checkbutton(what, text="Videos only", variable=self.videos, command=self._sync).grid(
            row=0, column=1, sticky="w", **pad)
        ttk.Label(what, text="(tick both for images and videos)").grid(row=0, column=2, sticky="w", **pad)
        ttk.Label(what, text="Extension list").grid(row=1, column=0, sticky="w", **pad)
        self.ext_entry = ttk.Entry(what, textvariable=self.ext_var, width=55)
        self.ext_entry.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        self.ext_btn = ttk.Button(what, text="Browse...", command=self.pick_extensions)
        self.ext_btn.grid(row=1, column=3, **pad)
        ttk.Checkbutton(what, text="E01 sources: include deleted files", variable=self.deleted).grid(
            row=2, column=0, columnspan=3, sticky="w", **pad)
        what.columnconfigure(2, weight=1)

        # E01 export
        exp = ttk.LabelFrame(frm, text="Export (optional)", padding=8)
        exp.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
        self.export = tk.BooleanVar(value=False)
        self.export_var = tk.StringVar()
        ttk.Checkbutton(exp, text="Also write an E01", variable=self.export, command=self._sync).grid(
            row=0, column=0, sticky="w", **pad)
        self.export_entry = ttk.Entry(exp, textvariable=self.export_var, width=55)
        self.export_entry.grid(row=0, column=1, sticky="ew", **pad)
        self.export_btn = ttk.Button(exp, text="Save as...", command=self.pick_export)
        self.export_btn.grid(row=0, column=2, **pad)
        self.examiner = tk.StringVar(value="")
        self.case = tk.StringVar(value="")
        self.evidence = tk.StringVar(value="")
        self.notes = tk.StringVar(value="")
        self.meta_entries = []
        for r, (label, var) in enumerate([("Examiner", self.examiner), ("Case number", self.case),
                                          ("Evidence number", self.evidence), ("Notes", self.notes)], start=1):
            ttk.Label(exp, text=label).grid(row=r, column=0, sticky="w", **pad)
            e = ttk.Entry(exp, textvariable=var, width=55)
            e.grid(row=r, column=1, sticky="ew", **pad)
            self.meta_entries.append(e)
        exp.columnconfigure(1, weight=1)

        # Controls
        ctl = ttk.Frame(frm)
        ctl.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        self.run_btn = ttk.Button(ctl, text="Run", command=self.start)
        self.run_btn.pack(side="left")
        self.cancel_btn = ttk.Button(ctl, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.stage = tk.StringVar(value="idle")
        ttk.Label(ctl, textvariable=self.stage).pack(side="left", padx=12)
        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)

        # Log
        self.log = tk.Text(frm, height=14, wrap="word", state="disabled")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)
        sb = ttk.Scrollbar(frm, command=self.log.yview)
        sb.grid(row=6, column=3, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(6, weight=1)
        ttk.Label(frm, text=f"{BRAND}. Sources are opened read-only; E01s are read in place, no mount.").grid(
            row=7, column=0, columnspan=3, sticky="w", **pad)
        self._sync()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(150, self.poll)

    def _sync(self) -> None:
        """Grey out what does not apply: the list when a built-in set is
        ticked, the export fields when no export is wanted."""
        list_state = "disabled" if (self.images.get() or self.videos.get()) else "normal"
        self.ext_entry.configure(state=list_state)
        self.ext_btn.configure(state=list_state)
        exp_state = "normal" if self.export.get() else "disabled"
        for w in [self.export_entry, self.export_btn] + self.meta_entries:
            w.configure(state=exp_state)

    def on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if messagebox.askyesno("Run in progress", "A run is in progress. Cancel it and close?"):
                self.cancel()
                self.root.withdraw()  # poll() destroys the window once the worker reports done
            return
        self.root.destroy()

    # -- pickers -------------------------------------------------------------

    def _add(self, path: str) -> None:
        path = os.path.normpath(path)
        if path not in self.sources.get(0, "end"):
            self.sources.insert("end", path)

    def add_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder to search", mustexist=True)
        if path:
            self._add(path)

    def add_e01(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose an E01 image",
            filetypes=[("EnCase images", "*.E01 *.e01"), ("All files", "*.*")])
        for path in paths or ():
            self._add(path)

    def remove_source(self) -> None:
        for idx in reversed(self.sources.curselection()):
            self.sources.delete(idx)

    def pick_output(self) -> None:
        path = filedialog.askdirectory(title="Choose the output folder", mustexist=False)
        if path:
            self.out_var.set(os.path.normpath(path))
            if not self.export_var.get():
                self.export_var.set(os.path.normpath(path).rstrip("\\/") + ".E01")

    def pick_extensions(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an extension list", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.ext_var.set(os.path.normpath(path))

    def pick_export(self) -> None:
        current = self.export_var.get()
        path = filedialog.asksaveasfilename(
            title="Where to write the E01", defaultextension=".E01",
            filetypes=[("EnCase image", "*.E01"), ("All files", "*.*")],
            initialfile=os.path.basename(current) if current else "organized.E01")
        if path:
            self.export_var.set(os.path.normpath(path))

    # -- run -------------------------------------------------------------------

    def _options(self) -> Options:
        ext_file = self.ext_var.get().strip()
        return Options(
            sources=list(self.sources.get(0, "end")), output_dir=self.out_var.get().strip(),
            images=self.images.get(), videos=self.videos.get(),
            extensions_file=None if ext_file in ("", BUNDLED_LIST) else ext_file,
            include_deleted=self.deleted.get(),
            export_e01=self.export_var.get().strip() if self.export.get() else None,
            examiner=self.examiner.get(), case_number=self.case.get(),
            evidence_number=self.evidence.get(), notes=self.notes.get(),
        )

    def start(self) -> None:
        try:
            opts = self._options()
            if self.export.get() and not opts.export_e01:
                raise ValueError("choose where to write the E01, or untick the export")
            try:
                validate(opts)
            except FileExistsError as exc:
                if not messagebox.askyesno("E01 exists", f"Replace?\n{exc}"):
                    return
                opts.overwrite = True
                validate(opts)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot start", str(exc))
            return
        self.cancel_flag.clear()
        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.bar["value"] = 0
        self._append(f"starting {TOOL_NAME} {VERSION}")
        self.worker = threading.Thread(target=self._work, args=(opts,), daemon=True)
        self.worker.start()

    def _work(self, opts: Options) -> None:
        try:
            summary = run(opts, log=lambda m: self.q.put(("log", m)),
                          progress=lambda d, t, s: self.q.put(("progress", (d, t, s))),
                          cancel=self.cancel_flag.is_set)
            self.q.put(("done", summary))
        except Exception as exc:  # surfaced to the user, never swallowed
            self.q.put(("error", f"{type(exc).__name__}: {exc}"))

    def cancel(self) -> None:
        self.cancel_flag.set()
        self.stage.set("cancelling after the current file")

    def poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(str(payload))
                elif kind == "progress":
                    done, total, stage = payload  # type: ignore[misc]
                    self.bar["maximum"] = max(total, 1)
                    self.bar["value"] = done
                    self.stage.set(stage)
                elif kind == "done":
                    self._finish(payload)  # type: ignore[arg-type]
                    if self.cancel_flag.is_set() and not self.root.winfo_viewable():
                        self.root.destroy()
                elif kind == "error":
                    if self.cancel_flag.is_set() and not self.root.winfo_viewable():
                        self.root.destroy()  # closed mid-run: never leave a hidden process behind
                        return
                    self._append(str(payload))
                    messagebox.showerror("Run failed", str(payload))
                    self._reset()
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def _finish(self, s: Summary) -> None:
        self._reset()
        if s.cancelled:
            self.stage.set("cancelled")
            messagebox.showinfo("Cancelled", "Run cancelled; files copied so far stay in the output folder.")
            return
        self.stage.set("done")
        text = (f"Files found: {s.files_found}\nCopied: {s.files_copied}\nFailed: {s.files_failed}\n"
                f"Skipped: {s.files_skipped}\n\nManifest: {s.manifest}")
        if s.e01_segments:
            text += f"\n\nE01: {', '.join(s.e01_segments)}\nMD5: {s.e01_md5}"
            if s.e01_excluded:
                text += f"\n{s.e01_excluded} file(s) of 4 GiB or more left out of the E01 (see manifest)"
        messagebox.showinfo("Done", text)

    def _reset(self) -> None:
        self.run_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def _append(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def launch() -> int:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0
