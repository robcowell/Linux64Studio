"""Import → From Listing (CBM prg Studio's, for characters and sprites): read the data out of a
BASIC or assembler source, from a line number or a label, with a preview of what it makes."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..gfx import listing  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled, render_sprite  # noqa: E402


class ListingImportDialog(Adw.Window):
    """`kind` is "chars" (8 bytes each) or "sprites" (63, or 64 when padded). `sources` are
    (title, text, is_basic) of the open source files, the one to start with first. `draw(cr, item, x,
    y, scale)` draws one imported item; `on_apply(items, at)` stores them."""

    def __init__(self, parent, kind: str, sources, start_at: int, limit: int, draw, on_apply, folder=None):
        what = "Characters" if kind == "chars" else "Sprites"
        super().__init__(transient_for=parent, modal=True, title=f"Import {what} from a Listing",
                         default_width=760, default_height=560)
        self.kind = kind
        self.size = 8 if kind == "chars" else 63
        self.what = what.lower()
        self.sources = list(sources)
        self.draw_item = draw
        self.on_apply = on_apply
        self.folder = folder
        self.blocks: list[listing.Block] = []
        self.items: list = []
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
        self.source = Gtk.DropDown.new_from_strings([s[0] for s in self.sources] or ["(no source open)"])
        self.source.connect("notify::selected", lambda *_: self._source_changed())
        pick = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Read a file instead")
        pick.connect("clicked", lambda *_: self._choose())
        src = Gtk.Box(spacing=4)
        src.append(self.source)
        src.append(pick)
        form.attach(Gtk.Label(label="Source", xalign=0), 0, 0, 1, 1)
        form.attach(src, 1, 0, 1, 1)
        self.start = Gtk.DropDown.new_from_strings([])
        self.start.connect("notify::selected", lambda *_: self._update())
        form.attach(Gtk.Label(label="Start at", xalign=0), 0, 1, 1, 1)
        form.attach(self.start, 1, 1, 1, 1)
        find = Gtk.Button(label=f"Find {what[:-1]} Data")
        find.connect("clicked", lambda *_: self._find())
        form.attach(find, 1, 2, 1, 1)
        self.store = Gtk.SpinButton.new_with_range(0, max(0, limit - 1), 1)
        self.store.set_value(start_at)
        self.store.connect("value-changed", lambda *_: self._update())
        form.attach(Gtk.Label(label=f"Store from {what[:-1].lower()}", xalign=0), 0, 3, 1, 1)
        form.attach(self.store, 1, 3, 1, 1)
        self.all = Gtk.CheckButton(label="As many as possible", active=True)
        self.all.connect("toggled", lambda *_: (self.count.set_sensitive(not self.all.get_active()), self._update()))
        form.attach(self.all, 1, 4, 1, 1)
        self.count = Gtk.SpinButton.new_with_range(1, limit, 1)
        self.count.set_value(1)
        self.count.set_sensitive(False)
        self.count.connect("value-changed", lambda *_: self._update())
        form.attach(Gtk.Label(label="Or this many", xalign=0), 0, 5, 1, 1)
        form.attach(self.count, 1, 5, 1, 1)
        self.limit = limit
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        body.append(right)
        self.preview = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.preview.set_draw_func(self._draw)
        right.append(Gtk.Frame(child=Gtk.ScrolledWindow(child=self.preview, vexpand=True)))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.status)
        self._source_changed()

    # ---------------------------------------------------------------- sources
    def _current(self):
        i = self.source.get_selected()
        return self.sources[i] if 0 <= i < len(self.sources) else None

    def _choose(self):
        dlg = Gtk.FileDialog(title="Choose a source file")
        if self.folder:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.folder)))

        def done(d, res):
            try:
                p = Path(d.open_finish(res).get_path())
            except GLib.Error:
                return
            try:
                text = p.read_bytes().decode("utf-8-sig", errors="replace")
            except OSError as e:
                self.status.set_text(f"Can't read {p.name}: {e.strerror}")
                return
            self.sources.append((p.name, text, p.suffix.lower() in (".bas", ".pbas")))
            self.source.set_model(Gtk.StringList.new([s[0] for s in self.sources]))
            self.source.set_selected(len(self.sources) - 1)
        dlg.open(self, None, done)

    def _source_changed(self):
        s = self._current()
        self.blocks = listing.blocks(s[1], s[2]) if s else []
        self.start.set_model(Gtk.StringList.new([b.describe(self.size, self.what) for b in self.blocks]))
        self._find(quiet=True)

    def _find(self, quiet=False):
        s = self._current()
        b = listing.find(s[1], s[2], self.size) if s else None
        if b is not None:
            self.start.set_selected(self.blocks.index(b))
        elif not quiet:
            self.status.set_text(f"No {self.what[:-1]} data found: at least {self.size} bytes of data are needed")
        self._update()

    # ---------------------------------------------------------------- reading
    def _update(self):
        s = self._current()
        i = self.start.get_selected()
        self.items = []
        if s and 0 <= i < len(self.blocks):
            try:
                vals = listing.values(s[1], s[2], self.blocks[i])
            except listing.ListingError as e:
                self.status.set_text(str(e))
            else:
                room = self.limit - int(self.store.get_value())
                n = room if self.all.get_active() else min(room, int(self.count.get_value()))
                make = listing.chars if self.kind == "chars" else listing.sprites
                self.items = make(vals, n)
                at = int(self.store.get_value())
                if self.items:
                    self.status.set_text(f"{len(self.items)} {self.what if len(self.items) != 1 else self.what[:-1]} "
                                         f"from {len(vals)} bytes, into {at}–{at + len(self.items) - 1}")
                else:
                    self.status.set_text(f"Only {len(vals)} bytes there: not a whole {self.what[:-1]}")
        elif not self.blocks:
            self.status.set_text("This source has no data in DATA statements or byte lines")
        self.ok.set_sensitive(bool(self.items))
        cols = max(1, (self.preview.get_width() or 400) // (40 if self.kind == "chars" else 56))
        rows = (len(self.items) + cols - 1) // cols
        self.preview.set_content_height(max(200, rows * (40 if self.kind == "chars" else 50) + 8))
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


def char_drawer(charset, colour_of):
    """Draw a character for the preview, in the editor's colours."""
    def draw(cr, rows, x, y, scale):
        bm = Bitmap(8, 8)
        draw_char_into(bm, 0, 0, rows, colour_of(), charset.background, charset.multicolour, charset.mc1, charset.mc2)
        paint_scaled(cr, bm.surface(), x, y, scale, scale)
    return draw


def sprite_drawer(sprite_set, multi: bool, colour: int):
    def draw(cr, data, x, y, scale):
        from ..gfx.sprite import Sprite
        s = Sprite.from_bytes(data)
        bm = render_sprite(s.rows, multi, colour, sprite_set.background, sprite_set.mcolour1, sprite_set.mcolour2)
        paint_scaled(cr, bm.surface(), x, y, scale, scale)
    return draw
