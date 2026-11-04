"""Disk image (.d64) page: the directory, plus adding, extracting and deleting files."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from ..disk.image import DiskError, DiskImage, file_type_for, format_for  # noqa: E402
from .editor import EditorPage  # noqa: E402


class DiskEditor(EditorPage):
    kind = "disk"

    __gsignals__ = {
        "run-disk": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "list-basic": (GObject.SignalFlags.RUN_FIRST, None, (str, GObject.TYPE_PYOBJECT)),  # name, bytes
    }

    def __init__(self, path: Path):
        super().__init__(path)
        self.disk = DiskImage.load(path) if path.exists() else DiskImage(format_for(path))

        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self.append(bar)
        for icon, tip, cb in [("list-add-symbolic", "Add files…", self._add),
                              ("document-save-as-symbolic", "Extract selected file…", self._extract),
                              ("list-remove-symbolic", "Delete selected file", self._delete),
                              ("text-x-generic-symbolic", "List selected program as BASIC", self._list_basic)]:
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", cb)
            bar.append(b)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(Gtk.Label(label="Disk name"))
        self.name_entry = Gtk.Entry(text=self.disk.disk_name, max_length=16, width_chars=16)
        self.id_entry = Gtk.Entry(text=self.disk.disk_id, max_length=2, width_chars=3)
        for e in (self.name_entry, self.id_entry):
            e.connect("changed", self._header_changed)
        bar.append(self.name_entry)
        bar.append(Gtk.Label(label="ID"))
        bar.append(self.id_entry)
        bar.append(Gtk.Box(hexpand=True))
        run = Gtk.Button(label="Run in VICE", css_classes=["suggested-action"])
        run.connect("clicked", lambda *_: self.emit("run-disk"))
        bar.append(run)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["monospace"])
        self.listbox.connect("row-activated", lambda *_: self._list_basic())
        self.append(Gtk.ScrolledWindow(child=self.listbox, vexpand=True, margin_start=6, margin_end=6))
        self.status = Gtk.Label(xalign=0, margin_start=8, margin_bottom=6, css_classes=["dim-label"])
        self.append(self.status)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)
        self._refresh()

    # ---------------------------------------------------------------- view
    def _refresh(self):
        while (row := self.listbox.get_row_at_index(0)) is not None:
            self.listbox.remove(row)
        hdr = Gtk.Label(xalign=0, margin_start=6, margin_top=4, margin_bottom=4,
                        label=f'0 "{self.disk.disk_name:<16}" {self.disk.disk_id} {self.disk.fmt.dos_type.decode()}')
        hdr.add_css_class("heading")
        self.listbox.append(Gtk.ListBoxRow(child=hdr, activatable=False, selectable=False))
        for e in self.disk.entries():
            text = f'{e.blocks:<5}{chr(34) + e.name + chr(34):<19}{e.type_label()}'
            row = Gtk.ListBoxRow(child=Gtk.Label(label=text, xalign=0, margin_start=6, margin_top=2, margin_bottom=2))
            row.entry = e
            self.listbox.append(row)
        foot = Gtk.Label(label=f"{self.disk.blocks_free} BLOCKS FREE.", xalign=0, margin_start=6, margin_top=4)
        self.listbox.append(Gtk.ListBoxRow(child=foot, activatable=False, selectable=False))
        n = len(self.disk.entries())
        self.status.set_text(f"{self.disk.fmt.drive} disk (.{self.disk.fmt.kind}), {n} file(s). Drop files here to "
                             f"add them. Double-click a program to list it as BASIC.")

    def _selected(self):
        row = self.listbox.get_selected_row()
        return getattr(row, "entry", None) if row else None

    def _error(self, msg: str):
        self.status.set_text(msg)

    # ---------------------------------------------------------------- actions
    def _header_changed(self, *_):
        try:
            self.disk.set_header(self.name_entry.get_text(), self.id_entry.get_text() or "00")
        except DiskError as e:
            self._error(str(e))
            return
        self.set_modified(True)
        self._refresh()

    def add_paths(self, paths: list[Path]):
        for p in paths:
            name = p.stem[:16]
            try:
                self.disk.add_file(name, p.read_bytes(), file_type_for(p) if p.suffix.lower() != ".bin" else "prg",
                                   replace=False)
            except (DiskError, OSError) as e:
                self._error(f"Couldn't add {p.name}: {e}")
                break
        self.disk.validate()
        self.set_modified(True)
        self._refresh()

    def _add(self, *_):
        dlg = Gtk.FileDialog(title="Add files to the disk")
        dlg.set_initial_folder(Gio.File.new_for_path(str(self.path.parent)))

        def done(d, res):
            try:
                files = d.open_multiple_finish(res)
            except GLib.Error:
                return
            self.add_paths([Path(files.get_item(i).get_path()) for i in range(files.get_n_items())])
        dlg.open_multiple(self.get_root(), None, done)

    def _extract(self, *_):
        e = self._selected()
        if not e:
            self._error("Select a file first")
            return
        dlg = Gtk.FileDialog(title=f"Extract {e.name}")
        dlg.set_initial_folder(Gio.File.new_for_path(str(self.path.parent)))
        dlg.set_initial_name(f"{e.name.lower()}.{e.file_type}")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            try:
                dest.write_bytes(self.disk.read_file(e))
                self._error(f"Extracted {e.name} to {dest.name}")
            except (DiskError, OSError) as err:
                self._error(f"Couldn't extract {e.name}: {err}")
        dlg.save(self.get_root(), None, done)

    def _delete(self, *_):
        e = self._selected()
        if not e:
            self._error("Select a file first")
            return
        try:
            self.disk.delete(e)
        except DiskError as err:
            self._error(str(err))
            return
        self.set_modified(True)
        self._refresh()

    def _list_basic(self, *_):
        e = self._selected()
        if not e or e.file_type != "prg":
            self._error("Select a PRG file to list it")
            return
        try:
            self.emit("list-basic", e.name, self.disk.read_file(e))
        except DiskError as err:
            self._error(str(err))

    def _on_drop(self, _target, value, _x, _y):
        files = value.get_files() if hasattr(value, "get_files") else []
        self.add_paths([Path(f.get_path()) for f in files if f.get_path()])
        return True

    def save(self):
        self.disk.save(self.path)
        self.set_modified(False)

