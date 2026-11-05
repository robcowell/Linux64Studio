"""Binary Import/Export: turn a binary into source (data, disassembly or BASIC DATA), and write
part of the last build out as a .bin or .prg."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..binconv import (Binary, ConvertError, basic_sys_address, disassemble_to_source, export_range,  # noqa: E402
                       load_binary, to_asm_data, to_basic_data)
from ..emu.values import ValueError_, parse_address  # noqa: E402
from .editor import EditorPage  # noqa: E402

FORMATS = [("disasm", "Disassembly"), ("data", "Assembler data (byte lines)"), ("basic", "BASIC DATA statements")]


class BinaryTool(EditorPage):
    kind = "binary"

    def __init__(self, kickass: bool, project_dir: Path | None, get_build, insert_cb):
        super().__init__(None)
        self.kickass = kickass
        # the syntax to write (syntax.py): the window gives a function that follows where the
        # text is going (C or ca65 in a C project); on its own, Kick or CBM as kickass says
        self.syntax = lambda: "kick" if self.kickass else "cbm"
        self.project_dir = project_dir
        self.get_build = get_build          # () -> (memory bytes, used bytes, {address: label}, description) or None
        self.insert_cb = insert_cb
        self.binary: Binary | None = None
        self.file: Path | None = None
        self.stack = Adw.ViewStack(vexpand=True)
        sw = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE, margin_top=6)
        self.append(sw)
        self.append(self.stack)
        self.stack.add_titled_with_icon(self._import_page(), "import", "Import", "document-open-symbolic")
        self.stack.add_titled_with_icon(self._export_page(), "export", "Export", "document-save-symbolic")
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"], margin_start=8,
                                margin_bottom=6)
        self.append(self.status)

    @property
    def title(self) -> str:
        return "Binary Import/Export"

    # ================================================================ import
    def _import_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_end=8, margin_top=6)
        row = Gtk.Box(spacing=6)
        pick = Gtk.Button(label="Choose File…", css_classes=["suggested-action"])
        pick.connect("clicked", self._choose)
        row.append(pick)
        self.file_label = Gtk.Label(label="No file", xalign=0, hexpand=True, ellipsize=3)
        row.append(self.file_label)
        box.append(row)

        opts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=4,
                           max_children_per_line=10)
        self.load_addr = self._entry(opts, "Load address", "auto", "Where the bytes go. A .prg says itself (auto)")
        self.skip = self._entry(opts, "Skip", "0", "Bytes to skip at the start of the file (after a .prg's load address)")
        self.length = self._entry(opts, "Length", "all", "How many bytes to take")
        self.format = Gtk.DropDown.new_from_strings([f[1] for f in FORMATS])
        self.format.connect("notify::selected", lambda *_: self._convert())
        opts.append(self.format)
        box.append(opts)

        # options for each format
        self.fmt_opts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=4,
                                    max_children_per_line=10)
        self.trace = Gtk.CheckButton(label="Trace code from the entry points", active=True,
                                     tooltip_text="Follow the code from its start (and a BASIC loader's SYS) so data "
                                                  "isn't disassembled as instructions")
        self.trace.connect("toggled", lambda *_: self._convert())
        self.entries = self._entry(self.fmt_opts, "Entry points", "auto",
                                   "Where the code starts: auto = the load address, or the SYS address of a BASIC "
                                   "loader; or a list such as 0810 c000")
        self.fmt_opts.append(self.trace)
        self.label = self._entry(self.fmt_opts, "Label", "", "A label for the data")
        self.per_line = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.per_line.set_value(16)
        self.per_line.connect("value-changed", lambda *_: self._convert())
        self._labelled(self.fmt_opts, "Per line", self.per_line)
        self.radix = Gtk.DropDown.new_from_strings(["hex", "decimal", "binary"])
        self.radix.connect("notify::selected", lambda *_: self._convert())
        self.fmt_opts.append(self.radix)
        self.first_line = Gtk.SpinButton.new_with_range(0, 63999, 10)
        self.first_line.set_value(1000)
        self.first_line.connect("value-changed", lambda *_: self._convert())
        self._labelled(self.fmt_opts, "First line", self.first_line)
        self.step = Gtk.SpinButton.new_with_range(1, 1000, 1)
        self.step.set_value(10)
        self.step.connect("value-changed", lambda *_: self._convert())
        self._labelled(self.fmt_opts, "Step", self.step)
        self.loader = Gtk.CheckButton(label="With a loader (FOR/READ/POKE at line 10)", active=True)
        self.loader.connect("toggled", lambda *_: self._convert())
        self.fmt_opts.append(self.loader)
        box.append(self.fmt_opts)

        self.output = Gtk.TextView(editable=False, monospace=True, top_margin=6, left_margin=6, css_classes=["card", "monospace"])
        box.append(Gtk.ScrolledWindow(child=self.output, vexpand=True))
        btns = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        for label, cb in (("Copy", self._copy), ("Save As…", self._save_as), ("Insert into Editor", self._insert)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            btns.append(b)
        box.append(btns)
        self._show_format_options()
        return box

    def _entry(self, parent, label: str, text: str, tip: str) -> Gtk.Entry:
        e = Gtk.Entry(text=text, width_chars=10, tooltip_text=tip)
        e.connect("activate", lambda *_: self._reload())
        e.connect("changed", lambda *_: self._changed_soon())
        self._labelled(parent, label, e)
        return e

    @staticmethod
    def _labelled(parent, label: str, widget):
        box = Gtk.Box(spacing=4)
        box.append(Gtk.Label(label=label, css_classes=["dim-label"]))
        box.append(widget)
        parent.append(box)

    def _changed_soon(self):
        # Re-read after typing pauses (entries change on every key).
        if getattr(self, "_pending", None):
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(350, lambda: (self._reload(), setattr(self, "_pending", None), False)[2])

    def _choose(self, *_):
        dlg = Gtk.FileDialog(title="Import a binary file")
        if self.project_dir:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.project_dir)))

        def done(d, res):
            try:
                self.load_file(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self.get_root(), None, done)

    def load_file(self, path: Path):
        self.file = path
        self.file_label.set_text(str(path))
        self.load_addr.set_text("auto" if path.suffix.lower() == ".prg" else "C000")
        self._reload()

    def _number(self, entry: Gtk.Entry, default):
        t = entry.get_text().strip().lower()
        if t in ("", "auto", "all"):
            return default
        return parse_address(t)

    def _reload(self):
        if not self.file:
            return
        try:
            load = self._number(self.load_addr, None)
            skip = self._number(self.skip, 0)
            length = self._number(self.length, None)
            self.binary = load_binary(self.file, load, skip, length)
        except (ConvertError, ValueError_, OSError) as e:
            self.status.set_text(str(e))
            return
        self._convert()

    def _show_format_options(self):
        fmt = FORMATS[self.format.get_selected()][0]
        for w, formats in ((self.trace, {"disasm"}), (self.entries.get_parent(), {"disasm"}),
                           (self.label.get_parent(), {"data"}), (self.per_line.get_parent(), {"data", "basic"}),
                           (self.radix, {"data"}), (self.first_line.get_parent(), {"basic"}),
                           (self.step.get_parent(), {"basic"}), (self.loader, {"basic"})):
            (w.get_parent() if isinstance(w.get_parent(), Gtk.FlowBoxChild) else w).set_visible(fmt in formats)

    def _convert(self):
        self._show_format_options()
        b = self.binary
        if b is None:
            return
        fmt = FORMATS[self.format.get_selected()][0]
        try:
            if fmt == "disasm":
                entries = None
                if self.trace.get_active():
                    t = self.entries.get_text().strip().lower()
                    if t in ("", "auto"):
                        sys_addr = basic_sys_address(b)
                        entries = [sys_addr] if sys_addr else [b.start]
                    else:
                        entries = [parse_address(x) for x in t.replace(",", " ").split()]
                d = disassemble_to_source(b, entries, self.kickass, syntax=self.syntax())
                text = d.source
                info = f"{d.code_bytes} bytes of code, {d.data_bytes} of data, {len(d.labels)} labels"
                if entries:
                    info += " (traced from " + ", ".join(f"${e:04X}" for e in entries) + ")"
            elif fmt == "data":
                radix = ["hex", "dec", "bin"][self.radix.get_selected()]
                text = to_asm_data(b, self.label.get_text().strip(), int(self.per_line.get_value()), radix,
                                   self.kickass, syntax=self.syntax())
                info = f"{len(b.data)} bytes"
            else:
                text = to_basic_data(b, int(self.first_line.get_value()), int(self.step.get_value()),
                                     int(self.per_line.get_value()), self.loader.get_active())
                info = f"{len(b.data)} bytes in DATA statements"
        except (ConvertError, ValueError_) as e:
            self.status.set_text(str(e))
            return
        self.output.get_buffer().set_text(text)
        self.status.set_text(f"{b.name}: ${b.start:04X}-${b.end - 1:04X}. {info}")

    def output_text(self) -> str:
        buf = self.output.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _copy(self, *_):
        Gdk.Display.get_default().get_clipboard().set(self.output_text())
        self.status.set_text("Copied to the clipboard")

    def _insert(self, *_):
        where = self.insert_cb(self.output_text()) if self.insert_cb else None
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    def _save_as(self, *_):
        if not self.binary:
            return
        fmt = FORMATS[self.format.get_selected()][0]
        dlg = Gtk.FileDialog(title="Save the source")
        folder = self.project_dir or (self.file.parent if self.file else None)
        if folder:
            dlg.set_initial_folder(Gio.File.new_for_path(str(folder)))
        dlg.set_initial_name(Path(self.binary.name or "binary").stem + (".bas" if fmt == "basic" else ".asm"))

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_text(self.output_text())
            self.status.set_text(f"Saved {dest.name}")
        dlg.save(self.get_root(), None, done)

    # ================================================================ export
    def _export_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup(title="Export part of the last build",
                                 description="Write a range of the built program's memory to a file. Use addresses "
                                             "or labels, e.g. from SPRITEDATA to SPRITEDATA+$3FF.")
        page.add(g)
        self.ex_from = Adw.EntryRow(title="From (address or label)")
        self.ex_to = Adw.EntryRow(title="To (inclusive)")
        self.ex_prg = Adw.SwitchRow(title="Add a load address (.prg)", active=False)
        for w in (self.ex_from, self.ex_to, self.ex_prg):
            g.add(w)
        for w in (self.ex_from, self.ex_to):
            w.connect("changed", lambda *_: self._export_info())
        self.ex_prg.connect("notify::active", lambda *_: self._export_info())
        go = Gtk.Button(label="Export…", css_classes=["suggested-action"], valign=Gtk.Align.CENTER)
        go.connect("clicked", self._export)
        g.set_header_suffix(go)
        self.ex_info = Adw.ActionRow(title="Range")
        g.add(self.ex_info)
        return page

    def _export_range(self):
        build = self.get_build()
        if not build:
            raise ConvertError("Build the project first (F7)")
        memory, used, symbols, _desc = build
        names = {n: a for a, n in symbols.items()}
        try:
            start = parse_address(self.ex_from.get_text(), names)
            end = parse_address(self.ex_to.get_text(), names)
        except ValueError_ as e:
            raise ConvertError(str(e))
        if end < start:
            raise ConvertError("'To' is before 'From'")
        return memory, used, start, end

    def _export_info(self):
        try:
            _m, used, start, end = self._export_range()
        except ConvertError as e:
            self.ex_info.set_subtitle(str(e))
            return
        n = end - start + 1
        set_bytes = sum(used[start:end + 1])
        self.ex_info.set_subtitle(f"${start:04X}-${end:04X}: {n} bytes ({set_bytes} set by the program)"
                                  + (", plus the 2-byte load address" if self.ex_prg.get_active() else ""))

    def _export(self, *_):
        try:
            memory, _used, start, end = self._export_range()
        except ConvertError as e:
            self.status.set_text(str(e))
            return
        prg = self.ex_prg.get_active()
        dlg = Gtk.FileDialog(title="Export")
        if self.project_dir:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.project_dir)))
        dlg.set_initial_name(f"export-{start:04x}.{'prg' if prg else 'bin'}")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_bytes(export_range(memory, start, end, prg))
            self.status.set_text(f"Wrote ${start:04X}-${end:04X} to {dest.name}")
        dlg.save(self.get_root(), None, done)

    def save(self):
        self.set_modified(False)
