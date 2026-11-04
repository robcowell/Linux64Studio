"""Sprite Editor → Import from Image: cut sprites out of a .bmp (or PNG, GIF, ...), as CBM prg
Studio's Import From Bitmap. The image is shown with the cells it will be cut into, and the
sprites it makes are previewed before they're added."""
from __future__ import annotations

from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from ..gfx.bmpimport import ImageError, Options, cell_size, cells, guess_colours, import_sprites, load_image  # noqa: E402
from .render import paint_scaled, render_sprite  # noqa: E402

PLACES = [("after", "After the current sprite"), ("end", "At the end of the set"),
          ("replace", "Over the current sprite and those after it")]
SLOTS = ["Background (00)", "Multicolour 1 (01)", "Sprite colour (10)", "Multicolour 2 (11)"]


def _hex(rgb) -> str:
    return "" if rgb is None else "%02X%02X%02X" % rgb


def _parse_hex(text: str):
    t = text.strip().lstrip("#$")
    if not t:
        return None
    if len(t) != 6:
        raise ValueError
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


class BmpImportDialog(Adw.Window):
    def __init__(self, parent, data, index: int, on_apply, folder: Path | None = None, multi: bool = False):
        super().__init__(transient_for=parent, modal=True, title="Import Sprites from Image", default_width=980,
                         default_height=680)
        self.data = data
        self.index = index
        self.on_apply = on_apply          # (sprites, place, (colour, mc1, mc2) or None) -> None
        self.folder = folder
        self.image = None
        self.pixbuf = None
        self.result = None
        self.picking: int | None = None
        self._pending = False

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        self.ok = Gtk.Button(label="Import", css_classes=["suggested-action"], sensitive=False)
        self.ok.connect("clicked", lambda *_: self._apply())
        hb.pack_end(self.ok)
        body = Gtk.Box(spacing=16, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)

        form = Gtk.Grid(column_spacing=8, row_spacing=6, valign=Gtk.Align.START)
        body.append(Gtk.ScrolledWindow(child=form, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       propagate_natural_width=True))
        self._r = 0

        def add(label, w, tip=None):
            lab = Gtk.Label(label=label, xalign=0)
            if tip:
                lab.set_tooltip_text(tip)
                w.set_tooltip_text(tip)
            form.attach(lab, 0, self._r, 1, 1)
            form.attach(w, 1, self._r, 1, 1)
            self._r += 1

        def heading(text):
            form.attach(Gtk.Label(label=f"<b>{text}</b>", use_markup=True, xalign=0, margin_top=6), 0, self._r, 2, 1)
            self._r += 1

        def spin(lo, hi, value=0):
            s = Gtk.SpinButton.new_with_range(lo, hi, 1)
            s.set_value(value)
            s.connect("value-changed", lambda *_: self._changed())
            return s

        choose = Gtk.Button(label="Choose Image…")
        choose.connect("clicked", lambda *_: self._choose())
        form.attach(choose, 0, self._r, 2, 1)
        self._r += 1
        self.summary = Gtk.Label(label="A .bmp, .png or .gif: a sprite sheet, a screenshot…", xalign=0, wrap=True,
                                 max_width_chars=34, css_classes=["dim-label"])
        form.attach(self.summary, 0, self._r, 2, 1)
        self._r += 1

        heading("Layout")
        self.x, self.y = spin(0, 9999), spin(0, 9999)
        add("Skip pixels across", self.x, "Pixels to skip at the left before the first sprite")
        add("Skip pixels down", self.y, "Pixels to skip at the top before the first sprite")
        self.gap_x, self.gap_y = spin(0, 999), spin(0, 999)
        add("Gap across", self.gap_x, "Pixels between sprites side by side (a sheet's grid lines or spacing)")
        add("Gap down", self.gap_y, "Pixels between rows of sprites")
        self.scale = spin(1, 16, 1)
        add("Image pixels per pixel", self.scale, "For an image saved zoomed in: 2 if each sprite pixel is 2×2")
        self.count = spin(0, 256)
        add("Sprites (0 = all)", self.count, "How many sprites to import; 0 takes all that fit")
        self.order = Gtk.DropDown.new_from_strings(["Row by row", "Column by column"])
        self.order.connect("notify::selected", lambda *_: self._changed())
        add("Scan", self.order)
        self.skip_empty = Gtk.CheckButton(label="Leave out empty cells")
        self.skip_empty.connect("toggled", lambda *_: self._changed())
        form.attach(self.skip_empty, 0, self._r, 2, 1)
        self._r += 1

        heading("Pixels")
        self.multi = Gtk.Switch(active=multi, halign=Gtk.Align.START)
        self.multi.connect("notify::active", lambda *_: (self._mode(), self._changed()))
        add("Multicolour", self.multi)
        self.hires_box = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.threshold = spin(1, 99, 50)
        self.hires_box.attach(Gtk.Label(label="Threshold %", xalign=0), 0, 0, 1, 1)
        self.hires_box.attach(self.threshold, 1, 0, 1, 1)
        self.threshold.set_tooltip_text("How dark (or light) a pixel must be to be set")
        self.light = Gtk.DropDown.new_from_strings(["Dark pixels", "Light pixels"])
        self.light.connect("notify::selected", lambda *_: self._changed())
        self.hires_box.attach(Gtk.Label(label="Set", xalign=0), 0, 1, 1, 1)
        self.hires_box.attach(self.light, 1, 1, 1, 1)
        form.attach(self.hires_box, 0, self._r, 2, 1)
        self._r += 1
        self.mc_box = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.colour_entries, self.swatches, self.pick_buttons = [], [], []
        for i, name in enumerate(SLOTS):
            e = Gtk.Entry(width_chars=7, max_width_chars=7, placeholder_text="none",
                          tooltip_text="The colour in the image, as RRGGBB hex (empty: not used)")
            e.connect("changed", lambda *_: (self._swatch_all(), self._changed()))
            sw = Gtk.DrawingArea(content_width=20, content_height=20, valign=Gtk.Align.CENTER)
            sw.set_draw_func(self._draw_swatch, i)
            pick = Gtk.ToggleButton(icon_name="color-select-symbolic", tooltip_text="Pick it from the image")
            pick.connect("toggled", self._pick_toggled, i)
            self.mc_box.attach(Gtk.Label(label=name, xalign=0), 0, i, 1, 1)
            self.mc_box.attach(sw, 1, i, 1, 1)
            self.mc_box.attach(e, 2, i, 1, 1)
            self.mc_box.attach(pick, 3, i, 1, 1)
            self.colour_entries.append(e)
            self.swatches.append(sw)
            self.pick_buttons.append(pick)
        guess = Gtk.Button(label="Guess from the Image")
        guess.connect("clicked", lambda *_: self._guess())
        self.mc_box.attach(guess, 0, 4, 4, 1)
        self.tolerance = spin(1, 100, 30)
        self.tolerance.set_tooltip_text("How far (in %) a pixel's colour may be from its colour")
        self.mc_box.attach(Gtk.Label(label="Tolerance %", xalign=0), 0, 5, 1, 1)
        self.mc_box.attach(self.tolerance, 2, 5, 2, 1)
        form.attach(self.mc_box, 0, self._r, 2, 1)
        self._r += 1

        heading("Into the sprite set")
        self.set_colours = Gtk.CheckButton(label="Set the sprite colours from the image", active=True)
        self.set_colours.set_tooltip_text("The nearest C64 colours to the image's (CBM prg Studio keeps the "
                                          "editor's colours)")
        self.set_colours.connect("toggled", lambda *_: self._redraw())
        form.attach(self.set_colours, 0, self._r, 2, 1)
        self._r += 1
        self.place = Gtk.DropDown.new_from_strings([p[1] for p in PLACES])
        add("Put them", self.place)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        body.append(right)
        self.source = Gtk.DrawingArea(hexpand=True, vexpand=True, content_height=300)
        self.source.set_draw_func(self._draw_source)
        click = Gtk.GestureClick()
        click.connect("pressed", self._source_clicked)
        self.source.add_controller(click)
        right.append(Gtk.Frame(child=self.source))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.status)
        self.preview = Gtk.DrawingArea(hexpand=True, content_height=150)
        self.preview.set_draw_func(self._draw_preview)
        right.append(Gtk.ScrolledWindow(child=self.preview, min_content_height=150, vexpand=False))
        self._set_colours([(0, 0, 0), (255, 255, 255), (136, 136, 136), (68, 68, 68)])
        self._mode()

    # ---------------------------------------------------------------- file
    def _choose(self):
        dlg = Gtk.FileDialog(title="Choose an image")
        f = Gtk.FileFilter(name="Images")
        for pat in ("*.bmp", "*.png", "*.gif", "*.BMP", "*.PNG", "*.GIF"):
            f.add_pattern(pat)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)
        if self.folder:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.folder)))

        def done(d, res):
            try:
                self.load(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self, None, done)

    def load(self, path: Path):
        try:
            self.image = load_image(path)
            self.pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
        except (ImageError, GLib.Error) as e:
            self.summary.set_text(str(getattr(e, "message", e)))
            self.image = self.pixbuf = None
            self._changed()
            return
        self.summary.set_text(f"{path.name}: {self.image.kind}")
        if self.multi.get_active():
            self._guess()
        self._changed()

    # ---------------------------------------------------------------- options
    def options(self) -> Options:
        colours = []
        for e in self.colour_entries:
            try:
                colours.append(_parse_hex(e.get_text()))
            except ValueError:
                colours.append(None)
        return Options(x=int(self.x.get_value()), y=int(self.y.get_value()), gap_x=int(self.gap_x.get_value()),
                       gap_y=int(self.gap_y.get_value()), scale=int(self.scale.get_value()),
                       count=int(self.count.get_value()), column_first=self.order.get_selected() == 1,
                       multi=self.multi.get_active(), threshold=int(self.threshold.get_value()),
                       light_on=self.light.get_selected() == 1, colours=colours,
                       tolerance=int(self.tolerance.get_value()), skip_empty=self.skip_empty.get_active())

    def _mode(self):
        m = self.multi.get_active()
        self.hires_box.set_visible(not m)
        self.mc_box.set_visible(m)

    def _set_colours(self, colours):
        for e, c in zip(self.colour_entries, colours):
            e.set_text(_hex(c))

    def _guess(self):
        if self.image:
            hints = (self.data.sprites[self.index].colour, self.data.mcolour1, self.data.mcolour2)
            self._set_colours(guess_colours(self.image, self.options(), hints))

    def _swatch_all(self):
        for sw in self.swatches:
            sw.queue_draw()

    def _draw_swatch(self, _da, cr, w, h, i):
        try:
            c = _parse_hex(self.colour_entries[i].get_text())
        except ValueError:
            c = None
        if c is None:
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.rectangle(0.5, 0.5, w - 1, h - 1)
            cr.set_line_width(1)
            cr.stroke()
            cr.move_to(0, h)
            cr.line_to(w, 0)
            cr.stroke()
            return
        cr.set_source_rgb(*(v / 255 for v in c))
        cr.rectangle(0, 0, w, h)
        cr.fill()

    def _pick_toggled(self, btn, i):
        if btn.get_active():
            for j, b in enumerate(self.pick_buttons):
                if j != i:
                    b.set_active(False)
            self.picking = i
            self.status.set_text(f"Click the image to pick the {SLOTS[i].split(' (')[0].lower()}")
        elif self.picking == i:
            self.picking = None
            self._update_status()

    # ---------------------------------------------------------------- import
    def _changed(self):
        if not self._pending:
            self._pending = True
            GLib.idle_add(self._recompute)

    def _recompute(self):
        self._pending = False
        self.result = import_sprites(self.image, self.options()) if self.image else None
        self.ok.set_sensitive(bool(self.result and self.result.sprites))
        self._update_status()
        self._redraw()
        return False

    def _update_status(self):
        if not self.image:
            self.status.set_text("Choose an image to import from.")
            return
        n = len(self.result.sprites) if self.result else 0
        total = len(cells(self.image, self.options()))
        cw, ch = cell_size(self.options())
        if not total:
            self.status.set_text(f"No whole {cw}×{ch} cell fits: check the skips and the pixel size.")
        else:
            self.status.set_text(f"{n} sprite{'s' if n != 1 else ''} from {total} cell{'s' if total != 1 else ''} "
                                 f"of {cw}×{ch} pixels.")

    def _redraw(self):
        if self.result:
            per_row = max(1, (self.preview.get_width() or 600) // 56)
            rows = (len(self.result.sprites) + per_row - 1) // per_row
            self.preview.set_content_height(max(150, rows * 50 + 4))
        self.source.queue_draw()
        self.preview.queue_draw()

    def _colours(self):
        r = self.result
        if r and self.set_colours.get_active():
            return r.colour, r.mcolour1, r.mcolour2
        return None

    def _apply(self):
        if not self.result or not self.result.sprites:
            return
        self.on_apply(self.result.sprites, PLACES[self.place.get_selected()][0], self._colours())
        self.close()

    # ---------------------------------------------------------------- drawing
    def _fit(self, w, h):
        iw, ih = self.pixbuf.get_width(), self.pixbuf.get_height()
        s = min(w / iw, h / ih)
        s = max(1, int(s)) if s >= 1 else s           # whole-number zoom keeps pixels square
        return s, (w - iw * s) / 2, (h - ih * s) / 2

    def _draw_source(self, _da, cr, w, h):
        if not self.pixbuf:
            return
        s, ox, oy = self._fit(w, h)
        cr.save()
        cr.translate(ox, oy)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()
        o = self.options()
        cw, ch = cell_size(o)
        used = set(self.result.cells) if self.result else set()
        cr.set_line_width(1)
        for (x, y) in cells(self.image, o):
            if (x, y) in used:
                cr.set_source_rgba(0.2, 0.8, 1.0, 0.9)
            else:
                cr.set_source_rgba(1.0, 0.4, 0.2, 0.6)
            cr.rectangle(ox + x * s + 0.5, oy + y * s + 0.5, cw * s - 1, ch * s - 1)
            cr.stroke()

    def _source_clicked(self, _g, _n, x, y):
        if self.picking is None or not self.image:
            return
        s, ox, oy = self._fit(self.source.get_width(), self.source.get_height())
        ix, iy = int((x - ox) / s), int((y - oy) / s)
        if 0 <= ix < self.image.width and 0 <= iy < self.image.height:
            r, g, b, a = self.image.rgba(ix, iy)
            self.colour_entries[self.picking].set_text("" if a < 128 else _hex((r, g, b)))
            self.pick_buttons[self.picking].set_active(False)

    def _draw_preview(self, _da, cr, w, h):
        if not self.result:
            return
        cols = self._colours() or (self.data.sprites[self.index].colour, self.data.mcolour1, self.data.mcolour2)
        per_row = max(1, w // 56)
        for n, sp in enumerate(self.result.sprites):
            x, y = (n % per_row) * 56 + 4, (n // per_row) * 50 + 4
            bm = render_sprite(sp.rows, sp.multi, cols[0], self.data.background, cols[1], cols[2])
            paint_scaled(cr, bm.surface(), x, y, 2, 2)
