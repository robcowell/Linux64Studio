"""Tools → Convert Source (CBM prg Studio's Source File Converter): a Develop 64, Genesis or TASM
source into CBM prg Studio's dialect, previewed (with notes and what the assembler makes of it),
then written as a .asm."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import srcconvert  # noqa: E402


class ConvertDialog(Adw.Window):
    def __init__(self, parent, folder: Path, on_done, can_add: bool = False):
        """`on_done(path, add_to_build)` opens the converted file."""
        super().__init__(transient_for=parent, modal=True, title="Source File Converter", default_width=900,
                         default_height=620)
        self.folder, self.on_done = Path(folder), on_done
        self.source: Path | None = None
        self.result: srcconvert.Result | None = None
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        self.ok = Gtk.Button(label="Convert", css_classes=["suggested-action"], sensitive=False)
        self.ok.connect("clicked", lambda *_: self._convert())
        hb.pack_end(self.ok)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12,
                      margin_top=8, margin_bottom=12)
        tv.set_content(box)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        box.append(grid)
        self.src_label = Gtk.Label(label="(none)", xalign=0, hexpand=True, css_classes=["dim-label"])
        pick = Gtk.Button(label="Browse…")
        pick.connect("clicked", lambda *_: self._choose())
        grid.attach(Gtk.Label(label="Source file", xalign=0), 0, 0, 1, 1)
        grid.attach(self.src_label, 1, 0, 1, 1)
        grid.attach(pick, 2, 0, 1, 1)
        self.kind = Gtk.DropDown.new_from_strings(list(srcconvert.FORMATS.values()))
        self.kind.connect("notify::selected", lambda *_: self._preview())
        grid.attach(Gtk.Label(label="Source file type", xalign=0), 0, 1, 1, 1)
        grid.attach(self.kind, 1, 1, 2, 1)
        self.dest = Gtk.Entry(placeholder_text="converted.asm")
        grid.attach(Gtk.Label(label="Destination file", xalign=0), 0, 2, 1, 1)
        grid.attach(self.dest, 1, 2, 2, 1)
        self.add = Gtk.CheckButton(label="Add it to the project's build list", visible=can_add)
        grid.attach(self.add, 1, 3, 2, 1)
        panes = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True, position=330)
        self.preview = Gtk.TextView(monospace=True, editable=False, top_margin=6, left_margin=6,
                                    css_classes=["card", "monospace"])
        panes.set_start_child(Gtk.ScrolledWindow(child=self.preview))
        self.notes = Gtk.TextView(monospace=True, editable=False, top_margin=6, left_margin=6,
                                  wrap_mode=Gtk.WrapMode.WORD_CHAR, css_classes=["card", "monospace"])
        panes.set_end_child(Gtk.ScrolledWindow(child=self.notes))
        box.append(panes)

    def _choose(self):
        dlg = Gtk.FileDialog(title="Choose the source to convert")
        dlg.set_initial_folder(Gio.File.new_for_path(str(self.folder)))

        def done(d, res):
            try:
                self.load(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self, None, done)

    def load(self, path: Path):
        self.source = Path(path)
        self.src_label.set_text(str(self.source))
        guess = {".prg": "genesis", ".seq": "develop64"}.get(self.source.suffix.lower(), "tasm")
        self.kind.set_selected(list(srcconvert.FORMATS).index(guess))
        self.dest.set_text(str(self.folder / (self.source.stem + ".asm")))
        self._preview()

    def _fmt(self) -> str:
        return list(srcconvert.FORMATS)[self.kind.get_selected()]

    def _preview(self):
        self.result = None
        if self.source is None:
            return
        try:
            self.result = srcconvert.convert_file(self.source, self._fmt())
        except (OSError, ValueError) as e:
            self.preview.get_buffer().set_text("")
            self.notes.get_buffer().set_text(f"Can't read it as {srcconvert.FORMATS[self._fmt()]}: {e}")
            self.ok.set_sensitive(False)
            return
        self.preview.get_buffer().set_text(self.result.text)
        notes = [f"line {n}: {msg}" for n, msg in self.result.notes]
        errs = srcconvert.check(self.result.text)
        lines = ([f"{len(notes)} note(s) from the converter:"] + notes if notes else ["The converter had no notes."])
        lines += [""] + ([f"The assembler finds {len(errs)} error(s) (some may be labels in other files):"] + errs[:40]
                         if errs else ["It assembles without errors."])
        self.notes.get_buffer().set_text("\n".join(lines))
        self.ok.set_sensitive(True)

    def _convert(self):
        if not self.result:
            return
        dest = Path(self.dest.get_text().strip() or (self.folder / "converted.asm")).expanduser()
        if not dest.is_absolute():
            dest = self.folder / dest
        try:
            dest.write_text(self.result.text)
        except OSError as e:
            self.notes.get_buffer().set_text(f"Couldn't write {dest}: {e.strerror}")
            return
        self.close()
        self.on_done(dest, self.add.get_active())
