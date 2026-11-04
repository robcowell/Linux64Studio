"""Import → From Memory (CBM prg Studio's, for characters and sprites), and From File: read them
from the last build's memory, the running program's (VICE's, while debugging), a file, or, for
characters, the C64's character ROM, at an address (a number or a label), or where the VIC-II
would find them in a bank."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..emu.values import ValueError_, parse_address  # noqa: E402
from ..gfx import memimport as mi  # noqa: E402


class MemoryImportDialog(Adw.Window):
    """`kind` is "chars" or "sprites". `get_build()` gives (MemoryMap, {addr: label}, description) of
    the last build (or None, {}, ""); `get_session()` the debug session or None. `draw` and
    `on_apply(items, at)` are as for the listing import."""

    def __init__(self, parent, kind: str, get_build, get_session, start_at: int, limit: int, draw, on_apply,
                 folder: Path | None = None):
        self.kind = kind
        self.unit = mi.CHAR_BYTES if kind == "chars" else mi.SPRITE_BYTES
        self.what = "characters" if kind == "chars" else "sprites"
        super().__init__(transient_for=parent, modal=True, title=f"Import {self.what.capitalize()} from Memory",
                         default_width=780, default_height=560)
        self.get_build, self.get_session = get_build, get_session
        self.draw_item, self.on_apply, self.folder, self.limit = draw, on_apply, folder, limit
        self.file_memory: mi.Memory | None = None
        self.items: list = []
        self.memory: mi.Memory | None = None
        self.symbols: dict[int, str] = {}
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        self.ok = Gtk.Button(label="Import", css_classes=["suggested-action"], sensitive=False)
        self.ok.connect("clicked", lambda *_: self._apply())
        hb.pack_end(self.ok)
        body = Gtk.Box(spacing=16, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)
        form = Gtk.Grid(column_spacing=8, row_spacing=8, valign=Gtk.Align.START)
        body.append(form)
        self.sources = ["Last build", "Running program (VICE)", "A file…"]
        if kind == "chars":
            self.sources += ["Character ROM, upper case", "Character ROM, lower case"]
        self.source = Gtk.DropDown.new_from_strings(self.sources)
        self.source.connect("notify::selected", lambda *_: self._source_changed())
        form.attach(Gtk.Label(label="From", xalign=0), 0, 0, 1, 1)
        form.attach(self.source, 1, 0, 2, 1)
        self.file_btn = Gtk.Button(label="Choose File…")
        self.file_btn.connect("clicked", lambda *_: self._choose())
        self.load_addr = Gtk.CheckButton(label="It starts with a load address", active=True)
        self.load_addr.connect("toggled", lambda *_: self._reload_file())
        form.attach(self.file_btn, 1, 1, 1, 1)
        form.attach(self.load_addr, 2, 1, 1, 1)
        self.address = Gtk.Entry(text="$2000", tooltip_text="$hex (or bare hex digits), #decimal, or a label (+n)")
        self.address.connect("changed", lambda *_: self._update())
        form.attach(Gtk.Label(label="Address", xalign=0), 0, 2, 1, 1)
        form.attach(self.address, 1, 2, 2, 1)
        vic = Gtk.Box(spacing=6)
        self.bank = Gtk.SpinButton.new_with_range(0, 3, 1)
        self.slot = Gtk.SpinButton.new_with_range(0, 7 if kind == "chars" else 255, 1)
        self.slot.set_value(1 if kind == "chars" else 128)
        use = Gtk.Button(label="Use")
        use.connect("clicked", lambda *_: self._from_vic())
        for w in (Gtk.Label(label="VIC bank"), self.bank,
                  Gtk.Label(label="character set" if kind == "chars" else "sprite pointer"), self.slot, use):
            vic.append(w)
        vic.set_tooltip_text("Where the VIC-II finds them: a 2K character set ($D018) or the sprite a pointer "
                             "names, in a 16K bank ($DD00)")
        form.attach(vic, 1, 3, 2, 1)
        self.count = Gtk.SpinButton.new_with_range(1, limit, 1)
        self.count.set_value(min(limit, 128 if kind == "chars" else 8))
        self.count.connect("value-changed", lambda *_: self._update())
        form.attach(Gtk.Label(label=f"How many {self.what}", xalign=0), 0, 4, 1, 1)
        form.attach(self.count, 1, 4, 2, 1)
        self.store = Gtk.SpinButton.new_with_range(0, max(0, limit - 1), 1)
        self.store.set_value(start_at)
        self.store.connect("value-changed", lambda *_: self._update())
        form.attach(Gtk.Label(label=f"Store from {self.what[:-1]}", xalign=0), 0, 5, 1, 1)
        form.attach(self.store, 1, 5, 2, 1)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        body.append(right)
        self.preview = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.preview.set_draw_func(self._draw)
        right.append(Gtk.Frame(child=Gtk.ScrolledWindow(child=self.preview, vexpand=True)))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.status)
        session = get_session()
        if session is not None and getattr(session.monitor, "connected", False):
            self.source.set_selected(1)
        self._source_changed()

    # ---------------------------------------------------------------- where from
    def _source_changed(self):
        i = self.source.get_selected()
        self.file_btn.set_visible(i == 2)
        self.load_addr.set_visible(i == 2)
        self.memory, self.symbols, note = None, {}, ""
        try:
            if i == 0:
                build, syms, desc = self.get_build()
                if build is None:
                    note = "Build the project first (F7)."
                else:
                    self.memory = mi.Memory(bytes(build.memory), bytes(build.used), desc or "the last build")
                    self.symbols = syms
            elif i == 1:
                s = self.get_session()
                if s is None or not s.monitor.connected:
                    note = "Start debugging (Shift+F5) to read the running program."
                else:
                    self.memory = mi.from_bytes(s.snapshot_memory(), "the running program")
                    build, syms, _ = self.get_build()
                    self.symbols = syms
            elif i == 2:
                self.memory = self.file_memory
                note = "" if self.memory else "Choose a file."
            else:
                self.memory = mi.rom_charset(i == 3)
                self.address.set_text("$0000")
        except (mi.MemoryImportError, OSError) as e:
            note = str(e)
        except Exception as e:  # the debug session may have just ended
            note = f"Couldn't read the memory: {e}"
        self.note = note
        self._update()

    def _choose(self):
        dlg = Gtk.FileDialog(title="Choose a file with the data")
        if self.folder:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.folder)))

        def done(d, res):
            try:
                self.file_path = Path(d.open_finish(res).get_path())
            except GLib.Error:
                return
            self.load_addr.set_active(self.file_path.suffix.lower() == ".prg")
            self._reload_file()
        dlg.open(self, None, done)

    def load_file(self, path: Path, load_address: bool | None = None):
        self.file_path = Path(path)
        if load_address is not None:
            self.load_addr.set_active(load_address)
        self.source.set_selected(2)
        self._reload_file()

    def _reload_file(self):
        p = getattr(self, "file_path", None)
        if p is None:
            return
        try:
            self.file_memory = mi.from_file(p, self.load_addr.get_active())
        except (mi.MemoryImportError, OSError) as e:
            self.file_memory = None
            self.status.set_text(str(e))
            return
        first = next(a for a in range(0x10000) if self.file_memory.known[a])
        self.address.set_text(f"${first:04X}")
        self._source_changed()

    def _from_vic(self):
        bank, slot = int(self.bank.get_value()), int(self.slot.get_value())
        addr = mi.charset_address(bank, slot) if self.kind == "chars" else mi.sprite_address(bank, slot)
        self.address.set_text(f"${addr:04X}")
        if self.kind == "chars" and mi.rom_shadow(bank, slot) and self.source.get_selected() < 2:
            self.status.set_text("In this bank the VIC-II sees the character ROM there, not this memory: "
                                 "choose Character ROM to import it")

    # ---------------------------------------------------------------- reading
    def _update(self):
        self.items = []
        if self.memory is None:
            self.status.set_text(self.note)
        else:
            names = {n: a for a, n in self.symbols.items()}
            try:
                addr = parse_address(self.address.get_text(), names)
            except ValueError_ as e:
                self.status.set_text(str(e))
            else:
                room = self.limit - int(self.store.get_value())
                n = min(room, int(self.count.get_value()))
                try:
                    self.items = (mi.chars if self.kind == "chars" else mi.sprites)(self.memory, addr, n)
                except mi.MemoryImportError as e:
                    self.status.set_text(str(e))
                else:
                    end = addr + len(self.items) * self.unit - 1
                    label = self.symbols.get(addr)
                    at = int(self.store.get_value())
                    self.status.set_text(f"{len(self.items)} {self.what} from ${addr:04X}-${end:04X}"
                                         + (f" ({label})" if label else "") + f", into {at}–{at + len(self.items) - 1}"
                                         f" — {self.memory.what}")
        self.ok.set_sensitive(bool(self.items))
        step_x, step_y = (40, 40) if self.kind == "chars" else (56, 50)
        cols = max(1, (self.preview.get_width() or 400) // step_x)
        self.preview.set_content_height(max(200, ((len(self.items) + cols - 1) // cols) * step_y + 8))
        self.preview.queue_draw()

    def _draw(self, _da, cr, w, h):
        step_x, step_y, scale = (40, 40, 4) if self.kind == "chars" else (56, 50, 2)
        cols = max(1, w // step_x)
        for n, item in enumerate(self.items):
            self.draw_item(cr, item, 4 + (n % cols) * step_x, 4 + (n // cols) * step_y, scale)

    def _apply(self):
        if self.items:
            self.on_apply(self.items, int(self.store.get_value()))
            self.close()
