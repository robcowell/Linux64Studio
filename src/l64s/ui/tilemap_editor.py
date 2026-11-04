"""Tile map editor for CharPad projects that use tiles: paint tiles onto the map, edit which
characters make up each tile, see the rooms (screens) the map is cut into, and see each
character's material (CharPad's attribute high nibble, which games use for collision)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from ..gfx.charpad import CharPadError, CharPadProject  # noqa: E402
from .charset_editor import CharGrid  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402

# Overlay colours for materials 1-15 (0 is "nothing", left clear)
MATERIAL_RGB = [None, (0.95, 0.30, 0.25), (0.25, 0.75, 1.0), (1.0, 0.85, 0.15), (0.35, 0.90, 0.35),
                (0.85, 0.45, 1.0), (1.0, 0.55, 0.15), (0.2, 0.95, 0.85), (0.95, 0.4, 0.7), (0.6, 0.6, 1.0),
                (0.75, 1.0, 0.4), (1.0, 0.7, 0.7), (0.5, 0.8, 0.6), (0.9, 0.9, 0.5), (0.6, 0.9, 1.0),
                (1.0, 1.0, 1.0)]
TOOLS = [("draw", "document-edit-symbolic", "Draw tiles (left draw, right erase to tile 0, Ctrl+click picks)"),
         ("rect", "view-grid-symbolic", "Fill a rectangle with the tile"),
         ("pick", "color-select-symbolic", "Pick the tile under the pointer")]


class TileRenderer:
    """Cached images of each tile, from the project's characters and colours."""

    def __init__(self, ctm: CharPadProject):
        self.ctm = ctm
        self._cache: dict[int, object] = {}

    def invalidate(self):
        self._cache.clear()

    def surface(self, tile: int):
        if tile not in self._cache:
            p = self.ctm
            cs = p.charset
            tw, th = p.tile_width, p.tile_height
            bm = Bitmap(8 * tw, 8 * th)
            cells = p.tile_cells(tile) if tile < max(1, p.tile_count) else []
            for i, ch in enumerate(cells):
                x, y = i % tw, i // tw
                draw_char_into(bm, 8 * x, 8 * y, cs.chars[ch & 0xFF], p.cell_colour(ch & 0xFF, tile),
                               cs.background, cs.multicolour, cs.mc1, cs.mc2)
            self._cache[tile] = bm.surface()
        return self._cache[tile]


class TilePalette(Gtk.DrawingArea):
    """All the tiles; click one to choose it."""

    __gsignals__ = {"selected": (GObject.SignalFlags.RUN_FIRST, None, (int,))}
    COLS = 6

    def __init__(self, ctm: CharPadProject, renderer: TileRenderer, scale: int = 2):
        super().__init__()
        self.ctm, self.renderer, self.scale = ctm, renderer, scale
        self.selected = 0
        self.uses: list[int] = []
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)
        self.resize()

    def _cell(self):
        p = self.ctm
        return 8 * p.tile_width * self.scale + 4, 8 * p.tile_height * self.scale + 4

    def resize(self):
        cw, ch = self._cell()
        rows = (max(1, self.ctm.tile_count) + self.COLS - 1) // self.COLS
        self.set_content_width(cw * self.COLS)
        self.set_content_height(ch * rows)
        self.queue_draw()

    def _index_at(self, x, y):
        cw, ch = self._cell()
        i = int(y // ch) * self.COLS + int(x // cw)
        return i if 0 <= x < cw * self.COLS and 0 <= i < self.ctm.tile_count else None

    def _click(self, _g, _n, x, y):
        i = self._index_at(x, y)
        if i is not None:
            self.emit("selected", i)

    def _tooltip(self, _w, x, y, _kb, tip):
        i = self._index_at(x, y)
        if i is None:
            return False
        used = self.uses[i] if i < len(self.uses) else 0
        tip.set_text(f"Tile {i} (${i:02X}): used {used} time{'s' if used != 1 else ''}")
        return True

    def _draw(self, _w, cr, _width, _height):
        cw, ch = self._cell()
        s = self.scale
        for i in range(self.ctm.tile_count):
            x, y = (i % self.COLS) * cw + 2, (i // self.COLS) * ch + 2
            paint_scaled(cr, self.renderer.surface(i), x, y, s, s)
            if i < len(self.uses) and not self.uses[i]:
                cr.set_source_rgba(0, 0, 0, 0.45)          # unused tiles are dimmed
                cr.rectangle(x, y, cw - 4, ch - 4)
                cr.fill()
            if i == self.selected:
                cr.set_source_rgb(1, 0.85, 0.2)
                cr.set_line_width(2)
                cr.rectangle(x - 1, y - 1, cw - 2, ch - 2)
                cr.stroke()


class TileCellEditor(Gtk.DrawingArea):
    """The chosen tile, large; click a cell to choose which character to change."""

    __gsignals__ = {"cell": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, ctm: CharPadProject, renderer: TileRenderer):
        super().__init__(halign=Gtk.Align.START)
        self.ctm, self.renderer = ctm, renderer
        self.tile = 0
        self.cell = 0
        self.scale = 8
        self.set_content_width(8 * ctm.tile_width * self.scale)
        self.set_content_height(8 * ctm.tile_height * self.scale)
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)

    def _click(self, _g, _n, x, y):
        tw, th = self.ctm.tile_width, self.ctm.tile_height
        c, r = int(x // (8 * self.scale)), int(y // (8 * self.scale))
        if 0 <= c < tw and 0 <= r < th:
            self.emit("cell", r * tw + c)

    def _draw(self, _w, cr, _width, _height):
        s = self.scale
        paint_scaled(cr, self.renderer.surface(self.tile), 0, 0, s, s)
        tw = self.ctm.tile_width
        cr.set_source_rgba(1, 1, 1, 0.5)
        cr.set_line_width(1)
        for i in range(self.ctm.tile_width * self.ctm.tile_height):
            x, y = (i % tw) * 8 * s, (i // tw) * 8 * s
            cr.rectangle(x + 0.5, y + 0.5, 8 * s - 1, 8 * s - 1)
            cr.stroke()
        x, y = (self.cell % tw) * 8 * s, (self.cell // tw) * 8 * s
        cr.set_source_rgb(1, 0.85, 0.2)
        cr.set_line_width(3)
        cr.rectangle(x + 1.5, y + 1.5, 8 * s - 3, 8 * s - 3)
        cr.stroke()


class TileMapEditor(EditorPage):
    """The Map page of a tile-based CharPad project."""

    kind = "tilemap"

    def __init__(self, ctm: CharPadProject, view: dict | None = None, save_view=None):
        super().__init__(None)
        self.ctm = ctm
        self.view = view if view is not None else {}
        self.save_view = save_view          # (view dict) -> None, keeps the room size and material names
        self.renderer = TileRenderer(ctm)
        self.tool = "draw"
        self.tile = 0
        self.zoom = 2
        self.undo: list[tuple[list[int], list[int], int]] = []
        self.redo: list[tuple[list[int], list[int], int]] = []
        self.hover: tuple[int, int] | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_now: tuple[int, int] | None = None
        self._painting = 0
        self._build()
        self._select_tile(0)

    # ================================================================== layout
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
            bar.append(b)
        for icon, tip, cb in (("edit-undo-symbolic", "Undo (Ctrl+Z)", self.do_undo),
                              ("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)", self.do_redo)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", lambda *_, cb=cb: cb())
            bar.append(b)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(Gtk.Label(label="Zoom"))
        self.zoom_box = Gtk.DropDown.new_from_strings(["1×", "2×", "3×", "4×"])
        self.zoom_box.set_selected(self.zoom - 1)
        self.zoom_box.connect("notify::selected", lambda d, _p: self._set_zoom(d.get_selected() + 1))
        bar.append(self.zoom_box)
        self.show_mat = Gtk.CheckButton(label="Materials", tooltip_text="Tint each character by its material "
                                                                         "(the attribute's high nibble)")
        self.show_mat.connect("toggled", lambda *_: (self._fill_legend(), self.canvas.queue_draw()))
        bar.append(self.show_mat)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(Gtk.Label(label="Rooms"))
        room = self.view.get("room") or [0, 0]
        self.room_w = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.room_h = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.room_w.set_value(room[0])
        self.room_h.set_value(room[1])
        for s in (self.room_w, self.room_h):
            s.set_tooltip_text("The size of a room (screen) in tiles, to draw the map's room grid; 0 for none")
            s.connect("value-changed", lambda *_: self._room_changed())
        bar.append(self.room_w)
        bar.append(Gtk.Label(label="×"))
        bar.append(self.room_h)
        bar.append(Gtk.Label(label="tiles", css_classes=["dim-label"]))

        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, shrink_end_child=False,
                         resize_end_child=False)
        self.append(body)
        self.canvas = Gtk.DrawingArea(halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.canvas.set_draw_func(self._draw)
        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.canvas.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self._motion(x, y))
        motion.connect("leave", lambda *_: self._set_hover(None))
        self.canvas.add_controller(motion)
        self.scroller = Gtk.ScrolledWindow(child=self.canvas, hexpand=True, vexpand=True)
        body.set_start_child(Gtk.Frame(child=self.scroller, margin_start=6, margin_bottom=6))

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=8, margin_end=8,
                       margin_bottom=6)
        side.append(Gtk.Label(label="<b>Tiles</b>", use_markup=True, xalign=0))
        self.palette = TilePalette(self.ctm, self.renderer)
        self.palette.connect("selected", lambda _p, i: self._select_tile(i))
        side.append(self.palette)
        row = Gtk.Box(spacing=6)
        add = Gtk.Button(label="New Tile", tooltip_text="Add a tile at the end, a copy of the chosen one")
        add.connect("clicked", lambda *_: self._add_tile())
        row.append(add)
        self.tile_label = Gtk.Label(xalign=0, css_classes=["dim-label"], hexpand=True)
        row.append(self.tile_label)
        side.append(row)
        side.append(Gtk.Label(label="<b>Tile</b>  click a cell, then a character for it", use_markup=True,
                              xalign=0))
        self.cell_editor = TileCellEditor(self.ctm, self.renderer)
        self.cell_editor.connect("cell", lambda _e, c: self._select_cell(c))
        side.append(self.cell_editor)
        self.cell_label = Gtk.Label(xalign=0, css_classes=["dim-label"], wrap=True)
        side.append(self.cell_label)
        self.chars = CharGrid(self.ctm.charset, scale=2)
        self.chars.colour_for = lambda ch: self.ctm.cell_colour(ch)
        self.chars.fg, self.chars.bg = self.ctm.charset.char_colour, self.ctm.charset.background
        self.chars.mc1, self.chars.mc2 = self.ctm.charset.mc1, self.ctm.charset.mc2
        self.chars.connect("selected", lambda _g, ch: self._set_cell_char(ch))
        side.append(self.chars)
        self.legend = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        side.append(self.legend)
        body.set_end_child(Gtk.ScrolledWindow(child=side, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                              propagate_natural_width=True))

        self.status = Gtk.Label(xalign=0, margin_start=8, margin_bottom=4, css_classes=["dim-label"])
        self.append(self.status)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self._resize_canvas()
        self._fill_legend()

    # ================================================================== state
    def material_names(self) -> list[str]:
        names = list(self.view.get("materials") or [])
        return names + [""] * (16 - len(names))

    def _room(self) -> tuple[int, int]:
        return self.room_w.get_value_as_int(), self.room_h.get_value_as_int()

    def _room_changed(self):
        self.view["room"] = list(self._room())
        if self.save_view:
            self.save_view(self.view)
        self.canvas.queue_draw()

    def _fill_legend(self):
        while (c := self.legend.get_first_child()) is not None:
            self.legend.remove(c)
        if not self.show_mat.get_active():
            return
        self.legend.append(Gtk.Label(label="<b>Materials</b>  (name them for this project)", use_markup=True,
                                     xalign=0))
        used = sorted({self.ctm.charset.material_of(c) for c in range(self.ctm.charset.count)})
        names = self.material_names()
        for m in used:
            row = Gtk.Box(spacing=6)
            sw = Gtk.DrawingArea(content_width=16, content_height=16, valign=Gtk.Align.CENTER)
            rgb = MATERIAL_RGB[m]
            sw.set_draw_func(lambda _a, cr, w, h, rgb=rgb: (cr.set_source_rgba(*(rgb or (0.5, 0.5, 0.5)),
                                                                                1 if rgb else 0.2),
                                                             cr.rectangle(0, 0, w, h), cr.fill()))
            row.append(sw)
            row.append(Gtk.Label(label=f"{m}", width_chars=3, xalign=0))
            e = Gtk.Entry(text=names[m], placeholder_text="name", width_chars=12)
            e.connect("changed", lambda en, m=m: self._name_material(m, en.get_text()))
            row.append(e)
            self.legend.append(row)

    def _name_material(self, m: int, name: str):
        names = self.material_names()
        names[m] = name.strip()
        while names and not names[-1]:
            names.pop()
        self.view["materials"] = names
        if self.save_view:
            self.save_view(self.view)

    def refresh(self):
        """Redraw after characters or colours changed (on the Characters page)."""
        self.renderer.invalidate()
        self.chars.invalidate()
        self.palette.queue_draw()
        self.cell_editor.queue_draw()
        self.canvas.queue_draw()
        self._fill_legend()

    # ================================================================== geometry
    def _tile_px(self) -> tuple[int, int]:
        return 8 * self.ctm.tile_width * self.zoom, 8 * self.ctm.tile_height * self.zoom

    def _resize_canvas(self):
        tw, th = self._tile_px()
        self.canvas.set_content_width(self.ctm.map_width * tw)
        self.canvas.set_content_height(self.ctm.map_height * th)
        self.canvas.queue_draw()

    def _set_zoom(self, z: int):
        self.zoom = z
        self._resize_canvas()

    def _cell_at(self, x, y) -> tuple[int, int] | None:
        tw, th = self._tile_px()
        c, r = int(x // tw), int(y // th)
        if 0 <= c < self.ctm.map_width and 0 <= r < self.ctm.map_height:
            return c, r
        return None

    # ================================================================== drawing
    def _draw(self, _w, cr, _width, _height):
        p = self.ctm
        tw, th = self._tile_px()
        z = self.zoom
        x1, y1, x2, y2 = cr.clip_extents()
        c0, c1 = max(0, int(x1 // tw)), min(p.map_width, int(x2 // tw) + 1)
        r0, r1 = max(0, int(y1 // th)), min(p.map_height, int(y2 // th) + 1)
        for r in range(r0, r1):
            for c in range(c0, c1):
                paint_scaled(cr, self.renderer.surface(p.tile_at(c, r)), c * tw, r * th, z, z)
        if self.show_mat.get_active():
            # dim the graphics, then colour each character by its material, so it stands out
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.rectangle(c0 * tw, r0 * th, (c1 - c0) * tw, (r1 - r0) * th)
            cr.fill()
            cs = p.charset
            cw, chh = 8 * z, 8 * z
            cr.set_line_width(1)
            for r in range(r0, r1):
                for c in range(c0, c1):
                    for i, ch in enumerate(p.tile_cells(p.tile_at(c, r))):
                        m = cs.material_of(ch & 0xFF)
                        rgb = MATERIAL_RGB[m] if m else None
                        if rgb:
                            x, y = c * tw + (i % p.tile_width) * cw, r * th + (i // p.tile_width) * chh
                            cr.set_source_rgba(*rgb, 0.55)
                            cr.rectangle(x, y, cw, chh)
                            cr.fill()
                            cr.set_source_rgba(*rgb, 1)
                            cr.rectangle(x + 0.5, y + 0.5, cw - 1, chh - 1)
                            cr.stroke()
        rw, rh = self._room()
        if rw and rh:
            per_row = (p.map_width + rw - 1) // rw
            cr.set_line_width(2)
            for gx in range(0, p.map_width + 1, rw):
                cr.set_source_rgba(1, 1, 1, 0.8)
                cr.move_to(gx * tw, 0)
                cr.line_to(gx * tw, p.map_height * th)
                cr.stroke()
            for gy in range(0, p.map_height + 1, rh):
                cr.set_source_rgba(1, 1, 1, 0.8)
                cr.move_to(0, gy * th)
                cr.line_to(p.map_width * tw, gy * th)
                cr.stroke()
            cr.select_font_face("Sans")
            cr.set_font_size(11 + 2 * z)
            for ry in range(0, p.map_height, rh):
                for rx in range(0, p.map_width, rw):
                    n = (ry // rh) * per_row + rx // rw
                    label = f"room {n}"
                    ext = cr.text_extents(label)
                    cr.set_source_rgba(0, 0, 0, 0.6)
                    cr.rectangle(rx * tw + 2, ry * th + 2, ext.x_advance + 8, ext.height + 8)
                    cr.fill()
                    cr.set_source_rgb(1, 1, 1)
                    cr.move_to(rx * tw + 6, ry * th + 6 + ext.height)
                    cr.show_text(label)
        if self._drag_start and self._drag_now and self.tool == "rect":
            (ax, ay), (bx, by) = self._drag_start, self._drag_now
            cr.set_source_rgba(1, 0.85, 0.2, 0.9)
            cr.set_line_width(2)
            cr.rectangle(min(ax, bx) * tw, min(ay, by) * th, (abs(bx - ax) + 1) * tw, (abs(by - ay) + 1) * th)
            cr.stroke()
        elif self.hover:
            c, r = self.hover
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.set_line_width(2)
            cr.rectangle(c * tw + 1, r * th + 1, tw - 2, th - 2)
            cr.stroke()

    # ================================================================== tiles and cells
    def _select_tile(self, i: int):
        self.tile = max(0, min(i, max(0, self.ctm.tile_count - 1)))
        self.palette.selected = self.tile
        self.palette.uses = self.ctm.tile_uses()
        self.palette.queue_draw()
        self.cell_editor.tile = self.tile
        self.cell_editor.queue_draw()
        used = self.palette.uses[self.tile] if self.tile < len(self.palette.uses) else 0
        self.tile_label.set_text(f"Tile {self.tile} of {self.ctm.tile_count}, used {used}×")
        self._select_cell(self.cell_editor.cell)

    def _select_cell(self, cell: int):
        self.cell_editor.cell = cell
        self.cell_editor.queue_draw()
        ch = self.ctm.tile_cells(self.tile)[cell] & 0xFF
        self.chars.selected = ch
        self.chars.queue_draw()
        m = self.ctm.charset.material_of(ch)
        name = self.material_names()[m]
        self.cell_label.set_text(f"Cell {cell}: character {ch} (${ch:02X}), colour {self.ctm.cell_colour(ch)}, "
                                 f"material {m}" + (f" ({name})" if name else ""))

    def _set_cell_char(self, ch: int):
        cells = self.ctm.tile_cells(self.tile)
        cell = self.cell_editor.cell
        if cells[cell] == ch:
            return
        self._push_undo()
        try:
            self.ctm.set_tile_cell(self.tile, cell, ch)
        except CharPadError as e:
            self.status.set_text(str(e))
            return
        self.renderer.invalidate()
        n = self.ctm.tile_width * self.ctm.tile_height
        self._select_cell((cell + 1) % n)         # on to the next cell, for building a tile quickly
        self._edited()

    def _add_tile(self):
        self._push_undo()
        try:
            t = self.ctm.add_tile(self.tile)
        except CharPadError as e:
            self.undo.pop()
            self.status.set_text(str(e))
            return
        self.palette.resize()
        self._select_tile(t)
        self._edited()
        self.status.set_text(f"Added tile {t}, a copy of tile {t - 1 if t else 0}")

    # ================================================================== painting
    def _drag_begin(self, g, x, y):
        cell = self._cell_at(x, y)
        if cell is None:
            return
        button = g.get_current_button()
        ctrl = bool(g.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK)
        if self.tool == "pick" or (ctrl and button == 1):
            self._select_tile(self.ctm.tile_at(*cell))
            return
        self._push_undo()
        self._painting = button
        if self.tool == "rect":
            self._drag_start = self._drag_now = cell
            self.canvas.queue_draw()
        else:
            self._paint(cell)

    def _drag_update(self, g, dx, dy):
        ok, x, y = g.get_start_point()
        cell = self._cell_at(x + dx, y + dy)
        if cell is None or not self._painting:
            return
        if self.tool == "rect":
            self._drag_now = cell
            self.canvas.queue_draw()
        elif self.tool == "draw":
            self._paint(cell)
        self._set_hover(cell)

    def _drag_end(self, _g, _dx, _dy):
        if self.tool == "rect" and self._drag_start and self._drag_now:
            (ax, ay), (bx, by) = self._drag_start, self._drag_now
            tile = 0 if self._painting == 3 else self.tile
            for r in range(min(ay, by), max(ay, by) + 1):
                for c in range(min(ax, bx), max(ax, bx) + 1):
                    self.ctm.set_tile_at(c, r, tile)
            self._edited()
        self._drag_start = self._drag_now = None
        self._painting = 0
        self.canvas.queue_draw()

    def _paint(self, cell):
        tile = 0 if self._painting == 3 else self.tile
        if self.ctm.tile_at(*cell) != tile:
            self.ctm.set_tile_at(*cell, tile)
            self._edited(redraw_palette=False)

    def _edited(self, redraw_palette: bool = True):
        self.set_modified(True)
        self.redo.clear()
        if redraw_palette:
            self.palette.uses = self.ctm.tile_uses()
            self.palette.queue_draw()
            self.cell_editor.queue_draw()
        self.canvas.queue_draw()

    # ================================================================== hover and status
    def _motion(self, x, y):
        self._set_hover(self._cell_at(x, y))

    def _set_hover(self, cell):
        if cell == self.hover:
            return
        self.hover = cell
        self.canvas.queue_draw()
        if cell is None:
            return
        c, r = cell
        t = self.ctm.tile_at(c, r)
        text = f"Tile ({c}, {r}) · tile {t}"
        rw, rh = self._room()
        if rw and rh:
            per_row = (self.ctm.map_width + rw - 1) // rw
            n = (r // rh) * per_row + c // rw
            text += f" · room {n}, at ({c % rw}, {r % rh})"
        self.status.set_text(text)

    # ================================================================== undo
    def _snapshot(self):
        p = self.ctm
        return list(p.map_data), list(p.tile_data), p.tile_count

    def _restore(self, snap):
        p = self.ctm
        p.map_data, p.tile_data, p.tile_count = list(snap[0]), list(snap[1]), snap[2]
        self.renderer.invalidate()
        self.palette.resize()
        self._select_tile(min(self.tile, p.tile_count - 1))
        self.set_modified(True)
        self.canvas.queue_draw()

    def _push_undo(self):
        self.undo.append(self._snapshot())
        del self.undo[:-200]

    def do_undo(self):
        if self.undo:
            self.redo.append(self._snapshot())
            self._restore(self.undo.pop())

    def do_redo(self):
        if self.redo:
            self.undo.append(self._snapshot())
            self._restore(self.redo.pop())

    def _key(self, _c, keyval, _code, state):
        if state & Gdk.ModifierType.CONTROL_MASK and Gdk.keyval_name(keyval) in ("z", "Z"):
            (self.do_redo if state & Gdk.ModifierType.SHIFT_MASK else self.do_undo)()
            return True
        return False

    def save(self) -> None:
        pass                                   # the CharPad editor saves the project
