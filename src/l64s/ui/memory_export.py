"""Export Memory: a block of memory as formatted text (or BASIC DATA), with a preview to copy or
save (CBM prg Studio's Export Memory and Create DATA From Memory)."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..binconv import Binary, ConvertError, to_basic_data  # noqa: E402
from ..emu.values import ValueError_, parse_address  # noqa: E402
from ..memtools import BASES, ExportOptions, MemToolError, export  # noqa: E402

MODES = ["Formatted text", "BASIC DATA with a loader"]


class MemoryExportDialog(Adw.Window):
    def __init__(self, parent, memory: bytes, start: int, end: int, symbols: dict[int, str] | None = None,
                 description: str = ""):
        super().__init__(transient_for=parent, modal=True, title="Export Memory", default_width=860,
                         default_height=600)
        self.memory = memory
        self.names = {n: a for a, n in (symbols or {}).items()}
        self._text = ""
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        body = Gtk.Box(spacing=14, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)

        form = Gtk.Grid(column_spacing=8, row_spacing=6, valign=Gtk.Align.START)
        body.append(Gtk.ScrolledWindow(child=form, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       propagate_natural_width=True))
        r = 0

        def row(label, w, tip=None):
            nonlocal r
            lab = Gtk.Label(label=label, xalign=0)
            if tip:
                w.set_tooltip_text(tip)
            form.attach(lab, 0, r, 1, 1)
            form.attach(w, 1, r, 1, 1)
            r += 1

        def entry(text="", width=16, tip=None):
            e = Gtk.Entry(text=text, width_chars=width)
            if tip:
                e.set_tooltip_text(tip)
            e.connect("changed", lambda *_: self._update())
            return e

        def spin(lo, hi, v):
            s = Gtk.SpinButton.new_with_range(lo, hi, 1)
            s.set_value(v)
            s.connect("value-changed", lambda *_: self._update())
            return s

        self.mode = Gtk.DropDown.new_from_strings(MODES)
        self.mode.connect("notify::selected", lambda *_: self._update())
        row("Export as", self.mode)
        self.start = entry(f"${start:04X}", 10, "$hex, decimal or a label")
        self.end = entry(f"${end:04X}", 10, "The last address (included)")
        row("Block start", self.start)
        row("Block end", self.end)
        self.text_rows = []

        def text_row(label, w, tip=None):
            """A row only shown for formatted text."""
            nonlocal r
            lab = Gtk.Label(label=label, xalign=0)
            if tip:
                w.set_tooltip_text(tip)
            form.attach(lab, 0, r, 1, 1)
            form.attach(w, 1, r, 1, 1)
            r += 1
            self.text_rows += [lab, w]

        self.prefix = entry("$", 6)
        text_row("Format specifier", self.prefix, "Text before each value, e.g. $ or 0x")
        self.sep = entry(", ", 6)
        text_row("Separator", self.sep, "Text between the values")
        self.base = Gtk.DropDown.new_from_strings(list(BASES.values()))
        self.base.connect("notify::selected", lambda *_: self._update())
        text_row("Number base", self.base, "This doesn't change the format specifier")
        self.pad = Gtk.CheckButton(label="Pad (2 hex, 3 octal, 8 binary digits)", active=True)
        self.pad.connect("toggled", lambda *_: self._update())
        form.attach(self.pad, 0, r, 2, 1)
        self.text_rows.append(self.pad)
        r += 1
        self.per_row = spin(1, 256, 16)
        row("Values per row", self.per_row)
        self.lead = entry("", 16)
        text_row("Row leading text", self.lead, "Added to the start of each row, e.g. 'byte '")
        self.trail = entry("", 16)
        text_row("Row trailing text", self.trail, "Added to the end of each row (the last one too)")
        kw = "%start%, %end%, %size% and %date% are replaced"
        self.header = entry("; %start%-%end%, %size% bytes, %date%", 24, kw)
        text_row("Header", self.header, kw)
        self.footer = entry("", 24, kw)
        text_row("Footer", self.footer, kw)
        self.first_line = spin(0, 63999, 1000)
        self.step = spin(1, 1000, 10)
        self.loader_line = spin(0, 63999, 10)
        self.basic_rows = []
        for label, w in (("Loader line", self.loader_line), ("First DATA line", self.first_line),
                         ("Step", self.step)):
            lab = Gtk.Label(label=label, xalign=0)
            form.attach(lab, 0, r, 1, 1)
            form.attach(w, 1, r, 1, 1)
            self.basic_rows += [lab, w]
            r += 1
        self.desc = Gtk.Label(label=description, xalign=0, wrap=True, max_width_chars=36,
                              css_classes=["dim-label", "caption"], margin_top=6)
        form.attach(self.desc, 0, r, 2, 1)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        body.append(right)
        right.append(Gtk.Label(label="<b>Preview</b>", use_markup=True, xalign=0))
        self.preview = Gtk.TextView(editable=False, monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                    css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.preview, vexpand=True, hexpand=True))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.status)

        save = Gtk.Button(label="Save…")
        save.connect("clicked", lambda *_: self._save())
        hb.pack_end(save)
        copy = Gtk.Button(label="Copy", css_classes=["suggested-action"])
        copy.connect("clicked", lambda *_: self._copy())
        hb.pack_end(copy)
        self._update()

    def _addr(self, e: Gtk.Entry) -> int:
        return parse_address(e.get_text(), self.names)

    def _update(self):
        basic = self.mode.get_selected() == 1
        for w in self.text_rows:
            w.set_visible(not basic)
        for w in self.basic_rows:
            w.set_visible(basic)
        try:
            a, b = self._addr(self.start), self._addr(self.end)
            if b < a:
                raise MemToolError("The block's start address must be before its end address")
            if basic:
                self._text = to_basic_data(Binary(a, bytes(self.memory[a:b + 1])), self.first_line.get_value_as_int(),
                                           self.step.get_value_as_int(), self.per_row.get_value_as_int(),
                                           loader=True, loader_line=self.loader_line.get_value_as_int())
            else:
                bases = list(BASES)
                self._text = export(self.memory, ExportOptions(
                    start=a, end=b, prefix=self.prefix.get_text(), separator=self.sep.get_text(),
                    base=bases[self.base.get_selected()], per_row=self.per_row.get_value_as_int(),
                    header=self.header.get_text(), footer=self.footer.get_text(), row_lead=self.lead.get_text(),
                    row_trail=self.trail.get_text(), pad=self.pad.get_active()))
        except (ValueError_, MemToolError, ConvertError) as e:
            self._text = ""
            self.preview.get_buffer().set_text("")
            self.status.set_text(str(e))
            return
        self.preview.get_buffer().set_text(self._text)
        self.status.set_text(f"${a:04X}-${b:04X}: {b - a + 1} bytes, {len(self._text.splitlines())} lines")

    def _copy(self):
        if self._text:
            Gdk.Display.get_default().get_clipboard().set(self._text)
            self.status.set_text("Copied the export")

    def _save(self):
        if not self._text:
            return
        dlg = Gtk.FileDialog(title="Save the export")
        dlg.set_initial_name("memory.bas" if self.mode.get_selected() == 1 else "memory.txt")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_text(self._text)
            self.status.set_text(f"Saved {dest}")
        dlg.save(self, None, done)
