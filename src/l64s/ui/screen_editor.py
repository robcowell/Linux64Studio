"""Screen / map designer: edits CBM prg Studio .sdd files using a project charset."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import digitiser  # noqa: E402

from ..gfx.charset import Charset, rom_charset  # noqa: E402
from ..gfx.screen import Screen, ScreenSet  # noqa: E402
from .charset_editor import CharGrid  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402
from .widgets import ColourButton  # noqa: E402

def _children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


TOOLS = [("draw", "document-edit-symbolic", "Draw"), ("fill", "color-select-symbolic", "Flood fill"),
         ("pick", "find-location-symbolic", "Pick character and colour"),
         ("colour", "applications-graphics-symbolic", "Paint colour only"),
         ("path", "mark-location-symbolic", "Path: click to add points, drag one to move it, right click "
                                            "one to delete it or add a point after it"),
         ("stamp", "view-grid-symbolic", "Stamp the character scratch pad (or the part selected in it): "
                                         "click where its top left goes")]


class ScreenEditor(EditorPage):
    kind = "screen"

    def __init__(self, path: Path | None, charset_files: list[Path] | None = None, *,
                 data: ScreenSet | None = None, charset: Charset | None = None,
                 cell_colour=None, read_only: bool = False, sprite_files: list[Path] | None = None,
                 settings=None):
        """Normally edits an .sdd file. With `data` + `charset` it edits a map owned by another editor
        (a CharPad project): colours and charset belong to that project, and `cell_colour(char)`
        gives each cell's colour. `read_only` shows the map without editing (tile-based maps)."""
        super().__init__(path)
        self.map_mode = data is not None
        self.read_only = read_only
        self.cell_colour = cell_colour
        if data is not None:
            self.data = data
        else:
            self.data = ScreenSet.load_sdd(path) if path and path.exists() else ScreenSet()
        self.index = 0
        self.tool = "draw"
        self.char = 160 if not self.data.multicolour else 0
        self.colour = 1
        self.undo: list[tuple[int, list, list, list]] = []
        self.show_order = False
        self._drag_point: int | None = None
        if charset is not None:
            self.charset = charset
        else:
            self.charset = Charset()
            rom = rom_charset(True)
            if rom:
                self.charset.chars = rom
            self.charset.multicolour = self.data.multicolour
        self.charset_files = [] if self.map_mode else (charset_files or [])
        self.sprite_files = [] if self.map_mode else (sprite_files or [])
        self.settings = settings
        self.digitise = False
        self.pointer: tuple[int, int] | None = None     # pixel on the screen under the mouse
        self._pointer_sprites = None                    # the SpriteSet the pointer sprite comes from
        self._glyphs: dict = {}
        # Screens up to 40x25 scale to fit the window; bigger maps scroll at a fixed zoom.
        self.fixed_zoom = 2.0 if (self.data.cols > 40 or self.data.rows > 25) else None
        self._build()
        if self.charset_files:
            # Prefer a charset in the same folder (e.g. characters.cst next to screens.sdd)
            self.charset_combo.set_selected(1)

    @property
    def screen(self) -> Screen:
        return self.data.screens[self.index]

    def _build(self):
        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self.append(bar)
        group = None
        for tid, icon, tip in TOOLS:
            b = Gtk.ToggleButton(icon_name=icon, tooltip_text=tip, group=group)
            group = group or b
            b.connect("toggled", lambda btn, t=tid: btn.get_active() and setattr(self, "tool", t))
            if tid == "draw":
                b.set_active(True)
            if self.map_mode and tid in ("colour", "path"):
                continue  # in a CharPad project the colour comes from the character; paths are per screen
            bar.append(b)
        ub = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Undo (Ctrl+Z)")
        ub.connect("clicked", self.do_undo)
        bar.append(ub)
        self.screen_spin = Gtk.SpinButton.new_with_range(0, max(0, len(self.data.screens) - 1), 1)
        self.screen_spin.connect("value-changed", lambda s: self._select_screen(int(s.get_value())))
        names = ["C64 ROM"] + [p.name for p in self.charset_files]
        self.charset_combo = Gtk.DropDown.new_from_strings(names)
        self.charset_combo.connect("notify::selected", self._charset_changed)
        if not self.map_mode:
            bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
            bar.append(Gtk.Label(label="Screen"))
            bar.append(self.screen_spin)
            add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add screen")
            add.connect("clicked", self._add_screen)
            bar.append(add)
            rm = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Delete screen")
            rm.connect("clicked", self._delete_screen)
            bar.append(rm)
            bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
            bar.append(Gtk.Label(label="Charset"))
            bar.append(self.charset_combo)
            self.digi_btn = Gtk.ToggleButton(icon_name="find-location-symbolic",
                                             tooltip_text="Digitiser: sprite coordinates of points on the screen")
            self.digi_btn.connect("toggled", lambda b: self._set_digitise(b.get_active()))
            bar.append(self.digi_btn)
            bar.append(self._path_menu())
            bar.append(Gtk.Box(hexpand=True))
            exp = Gtk.Button(label="Export…")
            exp.connect("clicked", self._export_dialog)
            bar.append(exp)
        else:
            bar.append(Gtk.Label(label=f"Map {self.data.cols} × {self.data.rows}", margin_start=12,
                                 css_classes=["dim-label"]))
            if self.read_only:
                bar.append(Gtk.Label(label="Tile-based map: view only", margin_start=12,
                                     css_classes=["warning"]))
        if self.read_only:
            for w in list(_children(bar)):
                if isinstance(w, (Gtk.ToggleButton, Gtk.Button)):
                    w.set_sensitive(False)

        body = Gtk.Box(spacing=8, vexpand=True, margin_start=6, margin_end=6, margin_bottom=6)
        self.append(body)
        self.canvas = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.canvas.set_draw_func(self._draw)
        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        self.canvas.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", lambda *_: self._pointer_left())
        self.canvas.add_controller(motion)
        if self.fixed_zoom:
            self.canvas.set_content_width(int(self.data.cols * 8 * self.fixed_zoom))
            self.canvas.set_content_height(int(self.data.rows * 8 * self.fixed_zoom))
            self.canvas.set_hexpand(False)
            self.canvas.set_vexpand(False)
            sw = Gtk.ScrolledWindow(child=self.canvas, hexpand=True, vexpand=True)
            body.append(Gtk.Frame(child=sw))
        else:
            body.append(Gtk.Frame(child=self.canvas))

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.append(Gtk.ScrolledWindow(child=side, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True))
        self.digi_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        if not self.map_mode:
            self.digi_revealer.set_child(self._digitiser_panel())
            side.append(self.digi_revealer)
        side.append(Gtk.Label(label="<b>Character</b>", use_markup=True, xalign=0))
        self.grid = CharGrid(self.charset, scale=2)
        self.grid.selected = self.char
        self.grid.connect("selected", lambda _g, i: setattr(self, "char", i))
        side.append(self.grid)
        g = Gtk.Grid(row_spacing=4, column_spacing=6)
        self.col_btn = ColourButton(self.colour, "Character colour")
        self.col_btn.connect("changed", lambda _b, c: setattr(self, "colour", c))
        self.mc_colour = Gtk.CheckButton(label="Multicolour char (colour + 8)")
        self.bg_btn = ColourButton(self.screen.background, "Background ($D021)")
        self.bg_btn.connect("changed", self._screen_colour, "background")
        self.border_btn = ColourButton(self.screen.border, "Border ($D020)")
        self.border_btn.connect("changed", self._screen_colour, "border")
        self.bk1_btn = ColourButton(self.screen.bk1, "Multicolour 1 ($D022)")
        self.bk1_btn.connect("changed", self._screen_colour, "bk1")
        self.bk2_btn = ColourButton(self.screen.bk2, "Multicolour 2 ($D023)")
        self.bk2_btn.connect("changed", self._screen_colour, "bk2")
        rows = [("Colour", self.col_btn), ("Background", self.bg_btn), ("Border", self.border_btn),
                ("Multicolour 1", self.bk1_btn), ("Multicolour 2", self.bk2_btn)]
        for r, (label, w) in enumerate(rows):
            g.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            g.attach(w, 1, r, 1, 1)
        self.multi = Gtk.CheckButton(label="Multicolour screen mode", active=self.data.multicolour)
        self.multi.connect("toggled", self._multi_toggled)
        if not self.map_mode:
            side.append(g)
            side.append(self.mc_colour)
            side.append(self.multi)
        else:
            side.append(Gtk.Label(label="Colours come from the character set\n(edit them on the Characters tab).",
                                  xalign=0, css_classes=["dim-label", "caption"]))
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"])
        side.append(self.status)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self._update_grid_colours()

    # ---------------------------------------------------------------- rendering
    def _invalidate(self, glyphs: bool = False):
        if glyphs:
            self._glyphs.clear()
        self.canvas.queue_draw()

    def refresh(self):
        """Redraw after the charset or its colours changed elsewhere."""
        self.grid.invalidate()
        self._invalidate(glyphs=True)

    def _palette(self):
        """(background, border, multicolour 1, multicolour 2, multicolour mode) for the current screen."""
        if self.map_mode:
            cs = self.charset
            return cs.background, cs.background, cs.mc1, cs.mc2, cs.multicolour
        s = self.screen
        return s.background, s.border, s.bk1, s.bk2, self.data.multicolour

    def _colour_of_cell(self, r, c) -> int:
        s = self.screen
        if self.cell_colour:
            return self.cell_colour(s.chars[r][c] & 0xFF)
        return s.colours[r][c] & 0x0F

    def _glyph(self, ch: int, colour: int):
        bg, _border, mc1, mc2, mc = self._palette()
        key = (ch, colour, bg, mc1, mc2, mc)
        surf = self._glyphs.get(key)
        if surf is None:
            bm = Bitmap(8, 8)
            draw_char_into(bm, 0, 0, self.charset.chars[ch & 0xFF], colour, bg, mc, mc1, mc2)
            surf = bm.surface()
            self._glyphs[key] = surf
        return surf

    def _geometry(self):
        if self.fixed_zoom:
            return self.fixed_zoom, 0, 0, 0
        w, h = self.canvas.get_width(), self.canvas.get_height()
        border = 16
        pw, ph = self.data.cols * 8 + 2 * border, self.data.rows * 8 + 2 * border
        scale = max(0.5, min(w / pw, h / ph))
        ox = (w - pw * scale) / 2 + border * scale
        oy = (h - ph * scale) / 2 + border * scale
        return scale, ox, oy, border

    def _draw(self, _w, cr, w, h):
        from .widgets import set_rgb
        scale, ox, oy, border = self._geometry()
        _bg, border_colour, *_ = self._palette()
        set_rgb(cr, border_colour)
        cr.rectangle(ox - border * scale, oy - border * scale,
                     (self.data.cols * 8 + 2 * border) * scale, (self.data.rows * 8 + 2 * border) * scale)
        cr.fill()
        # Only draw the cells inside the area being repainted (big maps are mostly off-screen).
        x1, y1, x2, y2 = cr.clip_extents()
        cell = 8 * scale
        c0, c1 = max(0, int((x1 - ox) // cell)), min(self.data.cols, int((x2 - ox) // cell) + 1)
        r0, r1 = max(0, int((y1 - oy) // cell)), min(self.data.rows, int((y2 - oy) // cell) + 1)
        s = self.screen
        for r in range(r0, r1):
            for c in range(c0, c1):
                paint_scaled(cr, self._glyph(s.chars[r][c], self._colour_of_cell(r, c)),
                             ox + c * cell, oy + r * cell, scale, scale)
        if self.digitise and self.pointer is not None:
            self._draw_pointer(cr, scale, ox, oy)
        if not self.map_mode and self.screen.path.points:
            self._draw_path(cr, scale, ox, oy)

    def _cell(self, x, y):
        scale, ox, oy, _ = self._geometry()
        c, r = int((x - ox) // (8 * scale)), int((y - oy) // (8 * scale))
        if 0 <= c < self.data.cols and 0 <= r < self.data.rows:
            return c, r
        return None

    # ---------------------------------------------------------------- paths
    def _path_menu(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        order = Gtk.CheckButton(label="Show the order")
        order.connect("toggled", lambda b: (setattr(self, "show_order", b.get_active()), self._invalidate()))
        box.append(order)
        pop = Gtk.Popover(child=box)
        for label, cb in (("Generate Data…", self.path_generate_dialog), ("Use a Function…", self.path_function_dialog),
                          ("Subdivide (a point between each)", self.path_subdivide),
                          ("Convert to Characters", self.path_to_characters), ("Clear the Path", self.path_clear)):
            b = Gtk.Button(label=label, css_classes=["flat"])
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, f=cb: (pop.popdown(), f()))
            box.append(b)
        return Gtk.MenuButton(label="Path", popover=pop, tooltip_text="The screen's path: movement data for sprites")

    def _path_hit(self, x, y) -> int | None:
        scale, *_ = self._geometry()
        p = self._screen_pixel(x, y)
        return self.screen.path.nearest(p, max(3, 7 / scale)) if p else None

    def _path_press(self, button, x, y):
        self._drag_point = None
        hit = self._path_hit(x, y)
        if button == 3:
            if hit is not None:
                self._path_point_menu(hit, x, y)
            return
        self._push_undo()
        if hit is not None:
            self._drag_point = hit                   # drag it
            self._start = (x, y)
            return
        p = self._screen_pixel(x, y)
        if p is None:
            self.undo.pop()
            return
        self._drag_point = self.screen.path.add(p)
        self._start = (x, y)
        self.set_modified(True)
        self._invalidate()
        self._path_status()

    def _path_point_menu(self, i, x, y):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=4, margin_bottom=4)
        pop = Gtk.Popover(child=box, has_arrow=True)
        pop.set_parent(self.canvas)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)

        def act(fn):
            pop.popdown()
            self._push_undo()
            fn()
            self.set_modified(True)
            self._invalidate()
            self._path_status()
        for label, fn in ((f"Delete point {i}", lambda: self.screen.path.delete(i)),
                          ("Add a point after it", lambda: self.screen.path.insert_after(i))):
            b = Gtk.Button(label=label, css_classes=["flat"])
            b.connect("clicked", lambda _b, f=fn: act(f))
            box.append(b)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _path_status(self):
        p = self.screen.path
        self.status.set_text(f"Path: {len(p.points)} point{'s' if len(p.points) != 1 else ''}, "
                             f"{p.lines} line{'s' if p.lines != 1 else ''}")

    def _draw_path(self, cr, scale, ox, oy):
        pts = self.screen.path.points
        active = self.tool == "path"
        cr.save()
        cr.set_line_width(max(1.5, scale * 0.6))
        cr.set_source_rgba(1, 0.85, 0.1, 0.95 if active else 0.45)
        sx = [(ox + (x + 0.5) * scale, oy + (y + 0.5) * scale) for x, y in pts]
        cr.move_to(*sx[0])
        for p in sx[1:]:
            cr.line_to(*p)
        cr.stroke()
        if active or self.show_order:
            r = max(2.5, scale * 1.2)
            for n, (px, py) in enumerate(sx):
                cr.set_source_rgba(1, 0.3, 0.1, 1) if n == 0 else cr.set_source_rgba(1, 0.85, 0.1, 1)
                cr.arc(px, py, r, 0, 6.2832)
                cr.fill()
                if self.show_order:
                    cr.set_font_size(max(9, scale * 4))
                    cr.set_source_rgb(1, 1, 1)
                    cr.move_to(px + r + 1, py - r)
                    cr.show_text(str(n))
        cr.restore()

    def path_subdivide(self):
        self._push_undo()
        self.screen.path.subdivide()
        self.set_modified(True)
        self._invalidate()
        self._path_status()

    def path_clear(self):
        self._push_undo()
        self.screen.path.points.clear()
        self.set_modified(True)
        self._invalidate()
        self._path_status()

    def path_to_characters(self):
        """Draw the path in the current character and colour (Path → Convert To Characters)."""
        from ..gfx.paths import to_cells
        cells = to_cells(self.screen.path, self.data.cols, self.data.rows)
        if not cells:
            self.status.set_text("The path doesn't cross the screen")
            return
        self._push_undo()
        s = self.screen
        colour = self.colour | (8 if self.mc_colour.get_active() else 0)
        for c, r in cells:
            s.chars[r][c], s.colours[r][c] = self.char, colour
        self.set_modified(True)
        self._invalidate()
        self.status.set_text(f"Drew the path in {len(cells)} characters")

    def path_function_dialog(self):
        from ..gfx.paths import PathError, function_points
        dlg = Adw.AlertDialog(heading="Path from a Function",
                              body="y = f(x), plotted from the start to the end x. The screen's y runs down, so "
                                   "negate the function to draw it the right way up. This replaces the path.")
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        expr = Gtk.Entry(text="-sin(x/20)*40+100", hexpand=True, activates_default=True)
        x0 = Gtk.SpinButton.new_with_range(-64, 383, 1)
        x1 = Gtk.SpinButton.new_with_range(-64, 383, 1)
        step = Gtk.SpinButton.new_with_range(1, 64, 1)
        x0.set_value(0)
        x1.set_value(self.data.cols * 8 - 1)
        step.set_value(8)
        for r, (label, w) in enumerate((("y =", expr), ("Start x", x0), ("End x", x1), ("Step", step))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            grid.attach(w, 1, r, 1, 1)
        err = Gtk.Label(xalign=0, wrap=True, css_classes=["error"])
        grid.attach(err, 0, 4, 2, 1)
        dlg.set_extra_child(grid)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Make the Path")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            try:
                pts = function_points(expr.get_text(), int(x0.get_value()), int(x1.get_value()),
                                      int(step.get_value()))
            except PathError as e:
                self.status.set_text(str(e))
                return
            self._push_undo()
            self.screen.path.points = pts
            self.set_modified(True)
            self._invalidate()
            self._path_status()
        dlg.choose(self.get_root(), None, chosen)

    def path_generate_dialog(self):
        from .path_dialog import PathGenerateDialog
        root = self.get_root()
        project = getattr(root, "project", None)
        kick = bool(project) and project.toolchain == "kickass"
        insert = getattr(root, "_insert_into_last_source", None)
        dlg = PathGenerateDialog(root, self.screen.path, kick, insert, self.settings,
                                 getattr(root, "code_syntax", None))
        dlg.present()
        return dlg

    # ---------------------------------------------------------------- digitiser
    def _digitiser_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"], hexpand=False)
        g = Gtk.Grid(row_spacing=4, column_spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=8)
        box.append(g)
        st = self.settings
        g.attach(Gtk.Label(label="<b>Digitiser</b>", use_markup=True, xalign=0), 0, 0, 3, 1)
        self.digi_xoff = Gtk.SpinButton.new_with_range(-512, 512, 1)
        self.digi_xoff.set_value(getattr(st, "digitiser_x_offset", digitiser.X_OFFSET))
        self.digi_yoff = Gtk.SpinButton.new_with_range(-512, 512, 1)
        self.digi_yoff.set_value(getattr(st, "digitiser_y_offset", digitiser.Y_OFFSET))
        offs = Gtk.Box(spacing=4)
        offs.append(self.digi_xoff)
        offs.append(self.digi_yoff)
        g.attach(Gtk.Label(label="Offsets X, Y", xalign=0), 0, 1, 1, 1)
        g.attach(offs, 1, 1, 2, 1)
        self.digi_msb = Gtk.CheckButton(label="MSB (take 256 off X)")
        g.attach(self.digi_msb, 0, 2, 3, 1)
        self.digi_format = Gtk.Entry(text=getattr(st, "digitiser_format", digitiser.FORMAT), width_chars=14,
                                     max_width_chars=14,
                                     tooltip_text="{x} and {y}; {$x} / {$y} for hex ({$X} / {$Y} upper case). "
                                                  "\\n starts a new line")
        presets = Gtk.MenuButton(icon_name="view-list-symbolic", tooltip_text="Formats")
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4, margin_top=4,
                       margin_bottom=4)
        for f in digitiser.PRESETS:
            b = Gtk.Button(label=f, css_classes=["flat", "monospace"])
            b.connect("clicked", lambda _b, f=f, p=pop: (p.popdown(), self.digi_format.set_text(f)))
            pbox.append(b)
        pop.set_child(pbox)
        presets.set_popover(pop)
        g.attach(Gtk.Label(label="Format", xalign=0), 0, 3, 1, 1)
        g.attach(self.digi_format, 1, 3, 1, 1)
        g.attach(presets, 2, 3, 1, 1)
        for w in (self.digi_xoff, self.digi_yoff):
            w.connect("value-changed", lambda *_: self._digi_settings_changed())
        self.digi_msb.connect("toggled", lambda *_: self._digi_settings_changed())
        self.digi_format.connect("changed", lambda *_: self._digi_settings_changed())
        self.digi_preview = Gtk.Label(xalign=0, css_classes=["monospace"], selectable=True, wrap=True,
                                      max_width_chars=26, label="Move over the screen")
        g.attach(self.digi_preview, 0, 4, 3, 1)
        self.digi_hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=30, css_classes=["dim-label", "caption"])
        g.attach(self.digi_hint, 0, 5, 3, 1)

        self.digi_use_sprite = Gtk.CheckButton(label="Use sprite as the pointer",
                                               sensitive=bool(self.sprite_files))
        if not self.sprite_files:
            self.digi_use_sprite.set_tooltip_text("The project has no sprite files")
        g.attach(self.digi_use_sprite, 0, 6, 3, 1)
        self.digi_sprite_set = Gtk.DropDown.new_from_strings([p.name for p in self.sprite_files] or ["(none)"])
        self.digi_sprite_set.set_size_request(120, -1)
        self.digi_sprite_no = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.digi_expand_x = Gtk.CheckButton(label="Expand X")
        self.digi_expand_y = Gtk.CheckButton(label="Expand Y")
        g.attach(Gtk.Label(label="Sprite set", xalign=0), 0, 7, 1, 1)
        g.attach(self.digi_sprite_set, 1, 7, 2, 1)
        g.attach(Gtk.Label(label="Sprite #", xalign=0), 0, 8, 1, 1)
        g.attach(self.digi_sprite_no, 1, 8, 2, 1)
        ex = Gtk.Box(spacing=8)
        ex.append(self.digi_expand_x)
        ex.append(self.digi_expand_y)
        g.attach(ex, 0, 9, 3, 1)
        self.digi_sprite_widgets = [self.digi_sprite_set, self.digi_sprite_no, self.digi_expand_x, self.digi_expand_y]
        for w in self.digi_sprite_widgets:
            w.set_sensitive(False)
        self.digi_use_sprite.connect("toggled", lambda *_: self._digi_sprite_changed())
        self.digi_sprite_set.connect("notify::selected", lambda *_: self._digi_sprite_changed(reload=True))
        for w in (self.digi_sprite_no, self.digi_expand_x, self.digi_expand_y):
            w.connect("value-changed" if isinstance(w, Gtk.SpinButton) else "toggled",
                      lambda *_: self.canvas.queue_draw())

        g.attach(Gtk.Label(label="<b>Points</b> (click the screen to add one)", use_markup=True, xalign=0,
                           margin_top=6), 0, 10, 3, 1)
        self.digi_points = Gtk.TextView(monospace=True, top_margin=4, bottom_margin=4, left_margin=4,
                                        css_classes=["monospace"], wrap_mode=Gtk.WrapMode.CHAR)
        g.attach(Gtk.ScrolledWindow(child=self.digi_points, min_content_height=110), 0, 11, 3, 1)
        btns = Gtk.Box(spacing=4)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda *_: self.digi_points.get_buffer().set_text(""))
        copy = Gtk.Button(label="Copy All")
        copy.connect("clicked", lambda *_: self._digi_copy())
        btns.append(clear)
        btns.append(copy)
        g.attach(btns, 0, 12, 3, 1)
        return box

    def _set_digitise(self, on: bool):
        self.digitise = on
        self.digi_revealer.set_reveal_child(on)
        self.canvas.set_cursor(Gdk.Cursor.new_from_name("crosshair" if on else "default"))
        if not on:
            self.pointer = None
        self.canvas.queue_draw()

    def _digi_settings_changed(self):
        st = self.settings
        if st is not None:
            st.digitiser_x_offset = self.digi_xoff.get_value_as_int()
            st.digitiser_y_offset = self.digi_yoff.get_value_as_int()
            st.digitiser_format = self.digi_format.get_text()
            try:
                st.save()
            except OSError:
                pass
        if self.pointer is not None:
            self._show_point(*self.pointer)

    def _screen_pixel(self, x, y) -> tuple[int, int] | None:
        """The pixel on the screen (0,0 = the text area's top left) under widget point x, y; points
        in the border count too, which sprites can reach."""
        scale, ox, oy, border = self._geometry()
        px, py = int((x - ox) // scale), int((y - oy) // scale)
        if -border <= px < self.data.cols * 8 + border and -border <= py < self.data.rows * 8 + border:
            return px, py
        return None

    def digitised(self, px: int, py: int) -> str:
        x, y = digitiser.coords(px, py, self.digi_xoff.get_value_as_int(), self.digi_yoff.get_value_as_int(),
                                self.digi_msb.get_active())
        return digitiser.format_point(self.digi_format.get_text(), x, y)

    def _show_point(self, px, py):
        try:
            self.digi_preview.set_text(self.digitised(px, py))
        except digitiser.FormatError as e:
            self.digi_preview.set_text(str(e))
            return
        x = px + self.digi_xoff.get_value_as_int()
        hint = ""
        if x > 255 and not self.digi_msb.get_active():
            hint = "X is over 255: set the sprite's bit in $D010, and tick MSB for the low part"
        elif x < 0 or x > 511:
            hint = "That X is off the sprite range (0-511)"
        self.digi_hint.set_text(hint)

    def _digitise_motion(self, x, y):
        p = self._screen_pixel(x, y)
        if p != self.pointer:
            self.pointer = p
            if p is not None:
                self._show_point(*p)
            self.canvas.queue_draw()

    def _pointer_left(self):
        if self.digitise and self.pointer is not None:
            self.pointer = None
            self.canvas.queue_draw()

    def _add_point(self, x, y):
        p = self._screen_pixel(x, y)
        if p is None:
            return
        try:
            line = self.digitised(*p)
        except digitiser.FormatError as e:
            self.status.set_text(str(e))
            return
        b = self.digi_points.get_buffer()
        b.insert(b.get_end_iter(), ("" if b.get_char_count() == 0 else "\n") + line)
        self.digi_points.scroll_to_mark(b.get_insert(), 0, False, 0, 1)

    def _digi_copy(self):
        b = self.digi_points.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        if text:
            Gdk.Display.get_default().get_clipboard().set(text + "\n")
            self.status.set_text(f"Copied {len(text.splitlines())} points")

    def _digi_sprite_changed(self, reload: bool = False):
        on = self.digi_use_sprite.get_active()
        for w in self.digi_sprite_widgets:
            w.set_sensitive(on)
        if on and (reload or self._pointer_sprites is None) and self.sprite_files:
            path = self.sprite_files[self.digi_sprite_set.get_selected()]
            try:
                if path.suffix.lower() == ".spd":
                    from ..gfx.spritepad import load_spd
                    self._pointer_sprites = load_spd(path)
                else:
                    from ..gfx.sprite import SpriteSet
                    self._pointer_sprites = SpriteSet.load_spt(path)
            except (OSError, ValueError) as e:
                self._pointer_sprites = None
                self.status.set_text(f"Couldn't read {path.name}: {e}")
            else:
                n = len(self._pointer_sprites.sprites)
                self.digi_sprite_no.set_range(0, max(0, n - 1))
                s0 = self._pointer_sprites.sprites[0]
                self.digi_expand_x.set_active(s0.expand_x)
                self.digi_expand_y.set_active(s0.expand_y)
        self.canvas.queue_draw()

    def _draw_pointer(self, cr, scale, ox, oy):
        from .widgets import set_rgb
        px, py = self.pointer
        x0, y0 = ox + px * scale, oy + py * scale
        sprites = self._pointer_sprites if self.digi_use_sprite.get_active() else None
        if sprites and sprites.sprites:
            s = sprites.sprites[min(self.digi_sprite_no.get_value_as_int(), len(sprites.sprites) - 1)]
            sx = scale * (2 if self.digi_expand_x.get_active() else 1)
            sy = scale * (2 if self.digi_expand_y.get_active() else 1)
            cols = (None, sprites.mcolour1, s.colour, sprites.mcolour2)
            for y in range(21):
                for x in range(s.pixel_width):
                    v = s.get(x, y)
                    if not v:
                        continue                    # transparent
                    set_rgb(cr, cols[v] if s.multi else s.colour)
                    w = 2 if s.multi else 1
                    cr.rectangle(x0 + x * w * sx, y0 + y * sy, w * sx, sy)
                    cr.fill()
            return
        # a crosshair on the pixel
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(1)
        cr.rectangle(x0, y0, scale, scale)
        cr.stroke()
        cr.set_source_rgba(1, 0.2, 0.2, 0.8)
        cr.move_to(x0 + scale / 2, y0 - 6 * scale)
        cr.line_to(x0 + scale / 2, y0 - scale)
        cr.move_to(x0 + scale / 2, y0 + 2 * scale)
        cr.line_to(x0 + scale / 2, y0 + 7 * scale)
        cr.move_to(x0 - 6 * scale, y0 + scale / 2)
        cr.line_to(x0 - scale, y0 + scale / 2)
        cr.move_to(x0 + 2 * scale, y0 + scale / 2)
        cr.line_to(x0 + 7 * scale, y0 + scale / 2)
        cr.stroke()

    # ---------------------------------------------------------------- input
    def _drag_begin(self, g, x, y):
        if self.digitise:
            if g.get_current_button() == 1:
                self._add_point(x, y)
            return
        if self.read_only:
            return
        if self.tool == "path":
            self._path_press(g.get_current_button(), x, y)
            return
        self._start = (x, y)
        self._button = g.get_current_button()
        self._last = None
        self._push_undo()
        self._apply(x, y)

    def _drag_update(self, _g, dx, dy):
        if self.read_only or self.digitise:
            return
        if self.tool == "path":
            if self._drag_point is not None:
                p = self._screen_pixel(self._start[0] + dx, self._start[1] + dy)
                if p and p != self.screen.path.points[self._drag_point]:
                    self.screen.path.move(self._drag_point, p)
                    self.set_modified(True)
                    self._invalidate()
            return
        if self.tool in ("draw", "colour"):
            self._apply(self._start[0] + dx, self._start[1] + dy)

    def _motion(self, _c, x, y):
        if self.digitise:
            self._digitise_motion(x, y)
        cell = self._cell(x, y)
        if cell:
            c, r = cell
            s = self.screen
            self.status.set_text(f"Col {c}  Row {r}  char {s.chars[r][c]}  colour {self._colour_of_cell(r, c)}  "
                                 f"offset {r * self.data.cols + c}")

    def _ink(self) -> tuple[int, int]:
        ch = 32 if self._button == 3 else self.char
        if self.cell_colour:
            return ch, self.cell_colour(ch)
        return ch, self.colour | (8 if self.mc_colour.get_active() else 0)

    def _apply(self, x, y):
        cell = self._cell(x, y)
        if not cell or cell == self._last:
            return
        self._last = cell
        c, r = cell
        s = self.screen
        ch, col = self._ink()
        if self.tool == "draw":
            s.chars[r][c], s.colours[r][c] = ch, col
        elif self.tool == "colour":
            s.colours[r][c] = col
        elif self.tool == "pick":
            self.char = s.chars[r][c]
            self.grid.selected = self.char
            self.grid.queue_draw()
            self.colour = s.colours[r][c] & 7 if s.colours[r][c] & 8 else s.colours[r][c] & 15
            self.mc_colour.set_active(bool(s.colours[r][c] & 8) and self.data.multicolour)
            self.col_btn.colour = self.colour
            self.undo.pop()
            return
        elif self.tool == "fill":
            self._flood(c, r, s.chars[r][c], s.colours[r][c], ch, col)
        elif self.tool == "stamp":
            if not self.stamp(c, r):
                self.undo.pop()
                self.status.set_text("The character scratch pad is empty: open it from the character editor")
                return
        self.set_modified(True)
        self._invalidate()

    def stamp(self, col: int, row: int) -> bool:
        """Put the character scratch pad (or its selected part) here, in the current colour (in a
        CharPad map, each character's own). Empty cells of the pad leave the screen as it is."""
        from ..gfx import charscratch
        block = charscratch.stamp_block()
        if not any(ch is not None for line in block for ch in line):
            return False
        s = self.screen
        colour = self.colour | (8 if self.mc_colour.get_active() else 0)
        for dr, line in enumerate(block):
            for dc, ch in enumerate(line):
                r, c = row + dr, col + dc
                if ch is None or not (0 <= r < self.data.rows and 0 <= c < self.data.cols):
                    continue
                s.chars[r][c] = ch
                s.colours[r][c] = self.cell_colour(ch) if self.cell_colour else colour
        return True

    def _flood(self, c, r, old_ch, old_col, ch, col):
        if old_ch == ch and (self.cell_colour or old_col == col):
            return
        s = self.screen
        stack = [(c, r)]
        while stack:
            x, y = stack.pop()
            if not (0 <= x < self.data.cols and 0 <= y < self.data.rows):
                continue
            if s.chars[y][x] != old_ch or (not self.cell_colour and s.colours[y][x] != old_col):
                continue
            s.chars[y][x], s.colours[y][x] = ch, col
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

    def _key(self, _c, keyval, _code, state):
        from gi.repository import Gdk
        if state & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self.do_undo()
            return True
        return False

    def _push_undo(self):
        s = self.screen
        self.undo.append((self.index, [list(r) for r in s.chars], [list(r) for r in s.colours], list(s.path.points)))
        del self.undo[:-50]

    def do_undo(self, *_):
        if self.undo:
            i, chars, cols, points = self.undo.pop()
            if i < len(self.data.screens):
                self.data.screens[i].chars, self.data.screens[i].colours = chars, cols
                self.data.screens[i].path.points = points
                self._select_screen(i)
                self.set_modified(True)

    # ---------------------------------------------------------------- screens / settings
    def _select_screen(self, i):
        self.index = max(0, min(i, len(self.data.screens) - 1))
        if int(self.screen_spin.get_value()) != self.index:
            self.screen_spin.set_value(self.index)
        s = self.screen
        self.bg_btn.colour, self.border_btn.colour = s.background, s.border
        self.bk1_btn.colour, self.bk2_btn.colour = s.bk1, s.bk2
        self._update_grid_colours()
        self._invalidate()

    def _add_screen(self, *_):
        s = self.screen
        new = Screen(chars=[[32] * self.data.cols for _ in range(self.data.rows)],
                     colours=[[self.colour] * self.data.cols for _ in range(self.data.rows)],
                     flags=[[0] * self.data.cols for _ in range(self.data.rows)],
                     background=s.background, border=s.border, bk1=s.bk1, bk2=s.bk2, m3=s.m3)
        self.data.screens.insert(self.index + 1, new)
        self.screen_spin.set_range(0, len(self.data.screens) - 1)
        self._select_screen(self.index + 1)
        self.set_modified(True)

    def _delete_screen(self, *_):
        if len(self.data.screens) > 1:
            del self.data.screens[self.index]
            self.screen_spin.set_range(0, len(self.data.screens) - 1)
            self._select_screen(min(self.index, len(self.data.screens) - 1))
            self.set_modified(True)

    def _screen_colour(self, _b, colour, attr):
        setattr(self.screen, attr, colour)
        self.set_modified(True)
        self._update_grid_colours()
        self._invalidate()

    def _multi_toggled(self, btn):
        self.data.multicolour = btn.get_active()
        self.charset.multicolour = self.data.multicolour
        self.set_modified(True)
        self._update_grid_colours()
        self._invalidate()

    def _update_grid_colours(self):
        g = self.grid
        bg, _border, mc1, mc2, _mc = self._palette()
        g.fg, g.bg, g.mc1, g.mc2 = self.colour, bg, mc1, mc2
        g.colour_for = self.cell_colour
        g.invalidate()

    def _charset_changed(self, dd, _pspec):
        i = dd.get_selected()
        if i == 0:
            cs = Charset()
            rom = rom_charset(True)
            if rom:
                cs.chars = rom
        else:
            p = self.charset_files[i - 1]
            try:
                cs = Charset.load_cst(p) if p.suffix.lower() == ".cst" else Charset.from_bin(p.read_bytes())
            except Exception:  # a broken charset file shouldn't take the editor down
                return
            if p.suffix.lower() != ".cst":
                rom = rom_charset(True)
                if rom:
                    n = len(p.read_bytes()) // 8
                    cs.chars = cs.chars[:n] + rom[n:]
        cs.multicolour = self.data.multicolour
        self.charset = cs
        self.grid.charset = cs
        self._update_grid_colours()
        self._invalidate(glyphs=True)

    # ---------------------------------------------------------------- save/export
    def save(self):
        if not self.path:
            raise ValueError("No file name")
        self.data.save_sdd(self.path)
        self.set_modified(False)

    def _export_dialog(self, *_):
        win = Gtk.Window(title="Export screens", transient_for=self.get_root(), modal=True, default_width=380)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        win.set_child(box)
        g = Gtk.Grid(row_spacing=6, column_spacing=8)
        first = Gtk.SpinButton.new_with_range(0, self.data.rows - 1, 1)
        last = Gtk.SpinButton.new_with_range(0, self.data.rows - 1, 1)
        last.set_value(self.data.rows - 1)
        g.attach(Gtk.Label(label="First row", xalign=0), 0, 0, 1, 1)
        g.attach(first, 1, 0, 1, 1)
        g.attach(Gtk.Label(label="Last row", xalign=0), 0, 1, 1, 1)
        g.attach(last, 1, 1, 1, 1)
        box.append(g)
        side = Gtk.CheckButton(label="Screens side by side (one wide map, row by row)")
        box.append(side)
        chars_cb = Gtk.CheckButton(label="Character data", active=True)
        cols_cb = Gtk.CheckButton(label="Colour data (separate file, _colours.bin)")
        box.append(chars_cb)
        box.append(cols_cb)
        hint = Gtk.Label(label="The book's map (chapters 14-17) uses rows 2-17, side by side.",
                         xalign=0, wrap=True, css_classes=["dim-label"])
        box.append(hint)
        btns = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: win.close())
        ok = Gtk.Button(label="Export…", css_classes=["suggested-action"])
        btns.append(cancel)
        btns.append(ok)
        box.append(btns)

        def do_export(*_):
            a, b = int(first.get_value()), int(last.get_value())
            sbs = side.get_active()
            dlg = Gtk.FileDialog(title="Export screen data")
            dlg.set_initial_name((self.path.stem if self.path else "screens") + ".bin")
            if self.path:
                dlg.set_initial_folder(Gio.File.new_for_path(str(self.path.parent)))

            def done(d, res):
                try:
                    f = d.save_finish(res)
                except GLib.Error:
                    return
                p = Path(f.get_path())
                if chars_cb.get_active():
                    p.write_bytes(self.data.export_chars(min(a, b), max(a, b), sbs))
                if cols_cb.get_active():
                    p.with_name(p.stem + "_colours.bin").write_bytes(self.data.export_colours(min(a, b), max(a, b), sbs))
                win.close()
            dlg.save(win, None, done)
        ok.connect("clicked", do_export)
        win.present()
