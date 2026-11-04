"""The sprite scratch pad window (CBM prg Studio's Sprite Editor → Scratch Pad).

Choose a sprite on the right, then click cells to put it there (or drag it onto a cell). Right
click or Esc switches to selecting: click a cell to see its sprites, then move them (the offsets,
or the arrow keys), flip or invert them, change which is on top, or remove them. The pad follows
edits in the sprite editor as they're made, and is kept with the project.
"""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from ..gfx.scratchpad import MAX_OFFSET, WIDTH  # noqa: E402
from ..gfx.sprite import HEIGHT  # noqa: E402
from .render import Bitmap, paint_scaled, render_sprite  # noqa: E402


class SpriteScratchPad(Adw.Window):
    def __init__(self, parent, editor):
        super().__init__(transient_for=parent, title="Sprite Scratch Pad", default_width=1000, default_height=640)
        self.editor = editor
        self.pad = editor.scratch_pad
        self.current: int | None = editor.index       # the sprite clicks put down (None: selecting)
        self.cell: tuple[int, int] | None = None
        self.sel = -1                                 # the selected sprite in the cell's stack
        self.zoom = 3
        self._loading = False

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        clear = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text="Clear the pad")
        clear.connect("clicked", lambda *_: self._clear())
        hb.pack_start(clear)
        export = Gtk.Button(icon_name="document-save-as-symbolic", tooltip_text="Save the pad as a PNG image…")
        export.connect("clicked", lambda *_: self._export())
        hb.pack_start(export)
        self.cols = Gtk.SpinButton.new_with_range(1, 40, 1)
        self.rows = Gtk.SpinButton.new_with_range(1, 25, 1)
        self.cols.set_value(self.pad.cols)
        self.rows.set_value(self.pad.rows)
        for s in (self.cols, self.rows):
            s.connect("value-changed", lambda *_: self._resize())
        size = Gtk.Box(spacing=4)
        for w in (Gtk.Label(label="Grid"), self.cols, Gtk.Label(label="×"), self.rows):
            size.append(w)
        hb.pack_start(size)
        self.zoom_spin = Gtk.SpinButton.new_with_range(1, 8, 1)
        self.zoom_spin.set_value(self.zoom)
        self.zoom_spin.set_tooltip_text("Zoom")
        self.zoom_spin.connect("value-changed", lambda s: self._set_zoom(int(s.get_value())))
        hb.pack_end(self.zoom_spin)
        self.grid_lines = Gtk.ToggleButton(icon_name="view-grid-symbolic", active=True, tooltip_text="Grid lines")
        self.grid_lines.connect("toggled", lambda *_: self.area.queue_draw())
        hb.pack_end(self.grid_lines)

        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=640)
        tv.set_content(body)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_top=8, margin_bottom=8)
        self.mode = Gtk.Label(xalign=0, css_classes=["dim-label"])
        left.append(self.mode)
        self.area = Gtk.DrawingArea(focusable=True, halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.area.set_draw_func(self._draw)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._clicked)
        self.area.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.area.add_controller(keys)
        self.add_controller(self._esc_controller())
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        drop.connect("drop", self._dropped)
        self.area.add_controller(drop)
        left.append(Gtk.ScrolledWindow(child=self.area, vexpand=True, hexpand=True))
        body.set_start_child(left)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=8, margin_end=8,
                       margin_top=8, margin_bottom=8, width_request=300)
        body.set_end_child(side)
        body.set_resize_end_child(False)
        self.cell_title = Gtk.Label(xalign=0, use_markup=True)
        side.append(self.cell_title)
        self.stack_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.stack_list.connect("row-selected", self._row_selected)
        side.append(Gtk.ScrolledWindow(child=self.stack_list, min_content_height=110, max_content_height=160,
                                       propagate_natural_height=True))
        ctl = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.dx = Gtk.SpinButton.new_with_range(-MAX_OFFSET, MAX_OFFSET, 1)
        self.dy = Gtk.SpinButton.new_with_range(-MAX_OFFSET, MAX_OFFSET, 1)
        for s in (self.dx, self.dy):
            s.connect("value-changed", lambda *_: self._edit_placement())
        ctl.attach(Gtk.Label(label="Move across", xalign=0), 0, 0, 1, 1)
        ctl.attach(self.dx, 1, 0, 1, 1)
        ctl.attach(Gtk.Label(label="Move down", xalign=0), 0, 1, 1, 1)
        ctl.attach(self.dy, 1, 1, 1, 1)
        flips = Gtk.Box(spacing=4)
        self.fx = Gtk.ToggleButton(icon_name="object-flip-horizontal-symbolic", tooltip_text="Flip across")
        self.fy = Gtk.ToggleButton(icon_name="object-flip-vertical-symbolic", tooltip_text="Flip down")
        self.inv = Gtk.ToggleButton(label="Invert", tooltip_text="Invert the pixels")
        for b in (self.fx, self.fy, self.inv):
            b.connect("toggled", lambda *_: self._edit_placement())
            flips.append(b)
        ctl.attach(flips, 0, 2, 2, 1)
        order = Gtk.Box(spacing=4)
        up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Bring forward (drawn later, on top)")
        up.connect("clicked", lambda *_: self._order(1))
        down = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Send back")
        down.connect("clicked", lambda *_: self._order(-1))
        rm = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove it from the cell (Delete)")
        rm.connect("clicked", lambda *_: self._remove())
        for b in (up, down, rm):
            order.append(b)
        ctl.attach(order, 0, 3, 2, 1)
        self.controls = ctl
        side.append(ctl)
        side.append(Gtk.Label(label="<b>Sprites</b>  click one, then click cells (or drag it)", use_markup=True,
                              xalign=0, margin_top=8))
        self.palette = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, max_children_per_line=6,
                                   column_spacing=4, row_spacing=4, homogeneous=True)
        self.palette.connect("child-activated", lambda _f, child: self._choose(child.get_index()))
        side.append(Gtk.ScrolledWindow(child=self.palette, vexpand=True))
        self.refresh()

    # ---------------------------------------------------------------- state
    def _esc_controller(self):
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _k, _s: (self._select_mode(), True)[1]
                     if kv == Gdk.KEY_Escape else False)
        return keys

    def _sprites(self):
        return self.editor.data.sprites

    def refresh(self):
        """Redraw everything (the sprites may have been edited, added or removed)."""
        self._fill_palette()
        self._size_area()
        self._fill_stack()
        self._update_mode()
        self.area.queue_draw()

    def _changed(self):
        self.editor.scratch_pad_changed()
        self.area.queue_draw()
        self._fill_stack()

    def _size_area(self):
        self.area.set_content_width(self.pad.cols * WIDTH * self.zoom + 1)
        self.area.set_content_height(self.pad.rows * HEIGHT * self.zoom + 1)

    def _set_zoom(self, z):
        self.zoom = z
        self._size_area()
        self.area.queue_draw()

    def _resize(self):
        self.pad.resize(int(self.cols.get_value()), int(self.rows.get_value()))
        if self.cell and (self.cell[0] >= self.pad.cols or self.cell[1] >= self.pad.rows):
            self.cell = None
        self._size_area()
        self._changed()

    def _clear(self):
        self.pad.clear()
        self.cell, self.sel = None, -1
        self._changed()

    def _update_mode(self):
        if self.current is not None and self.current < len(self._sprites()):
            self.mode.set_text(f"Placing sprite {self.current}: click cells to put it there. "
                               f"Right click or Esc to select instead.")
        else:
            self.current = None
            self.mode.set_text("Selecting: click a cell to see its sprites. Choose a sprite on the right to "
                               "place it.")

    def _select_mode(self):
        self.current = None
        self.palette.unselect_all()
        self._update_mode()

    def _choose(self, i):
        self.current = i
        self._update_mode()

    # ---------------------------------------------------------------- palette
    def _fill_palette(self):
        while (child := self.palette.get_child_at_index(0)) is not None:
            self.palette.remove(child)
        for i, _s in enumerate(self._sprites()):
            da = Gtk.DrawingArea(content_width=48, content_height=42, tooltip_text=f"Sprite {i}")
            da.set_draw_func(self._draw_thumb, i)
            src = Gtk.DragSource(actions=Gdk.DragAction.COPY)
            src.connect("prepare", lambda _s, _x, _y, n=i: Gdk.ContentProvider.new_for_value(f"sprite:{n}"))
            da.add_controller(src)
            self.palette.append(da)
        if self.current is not None and self.current < len(self._sprites()):
            self.palette.select_child(self.palette.get_child_at_index(self.current))

    def _draw_thumb(self, _da, cr, w, h, i):
        d = self.editor.data
        if i >= len(d.sprites):
            return
        s = d.sprites[i]
        bm = render_sprite(s.rows, s.multi, s.colour, d.background, d.mcolour1, d.mcolour2)
        paint_scaled(cr, bm.surface(), 0, 0, w / 24, h / 21)

    # ---------------------------------------------------------------- the grid
    def _image(self) -> Bitmap:
        d = self.editor.data
        rows = self.pad.render(d.sprites, d.background, d.mcolour1, d.mcolour2)
        bm = Bitmap(len(rows[0]), len(rows))
        bm.pixels = bytearray(v for row in rows for v in row)
        return bm

    def _draw(self, _da, cr, w, h):
        z = self.zoom
        paint_scaled(cr, self._image().surface(), 0, 0, z, z)
        cw, ch = WIDTH * z, HEIGHT * z
        if self.grid_lines.get_active():
            cr.set_source_rgba(1, 1, 1, 0.25)
            cr.set_line_width(1)
            for c in range(self.pad.cols + 1):
                cr.move_to(c * cw + 0.5, 0)
                cr.line_to(c * cw + 0.5, self.pad.rows * ch)
            for r in range(self.pad.rows + 1):
                cr.move_to(0, r * ch + 0.5)
                cr.line_to(self.pad.cols * cw, r * ch + 0.5)
            cr.stroke()
        if self.cell:
            c, r = self.cell
            cr.set_source_rgba(0.2, 0.8, 1.0, 0.95)
            cr.set_line_width(2)
            cr.rectangle(c * cw + 1, r * ch + 1, cw - 1, ch - 1)
            cr.stroke()

    def _cell_at(self, x, y):
        c, r = int(x // (WIDTH * self.zoom)), int(y // (HEIGHT * self.zoom))
        return (c, r) if 0 <= c < self.pad.cols and 0 <= r < self.pad.rows else None

    def _clicked(self, gesture, _n, x, y):
        self.area.grab_focus()
        cell = self._cell_at(x, y)
        if gesture.get_current_button() == 3:
            self._select_mode()
            if cell:
                self._select_cell(cell)
            return
        if cell is None:
            return
        if self.current is not None:
            self.pad.place(*cell, self.current)
            self.cell, self.sel = cell, len(self.pad.stack(*cell)) - 1
            self._changed()
        else:
            self._select_cell(cell)

    def _dropped(self, _t, value, x, y):
        cell = self._cell_at(x, y)
        if not cell or not str(value).startswith("sprite:"):
            return False
        n = int(str(value).split(":")[1])
        self.pad.place(*cell, n)
        self.cell, self.sel = cell, len(self.pad.stack(*cell)) - 1
        self._changed()
        return True

    def _select_cell(self, cell):
        self.cell = cell
        self.sel = len(self.pad.stack(*cell)) - 1
        self._fill_stack()
        self.area.queue_draw()

    def _key(self, _c, keyval, _code, _state):
        p = self._placement()
        if keyval == Gdk.KEY_Delete and p:
            self._remove()
            return True
        moves = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if keyval in moves and p:
            dx, dy = moves[keyval]
            self.dx.set_value(p.dx + dx)
            self.dy.set_value(p.dy + dy)
            return True
        return False

    # ---------------------------------------------------------------- a cell's sprites
    def _placement(self):
        if not self.cell:
            return None
        st = self.pad.stack(*self.cell)
        return st[self.sel] if 0 <= self.sel < len(st) else None

    def _fill_stack(self):
        self._loading = True
        while (row := self.stack_list.get_row_at_index(0)) is not None:
            self.stack_list.remove(row)
        if not self.cell:
            self.cell_title.set_markup("<b>No cell selected</b>")
        else:
            c, r = self.cell
            st = self.pad.stack(c, r)
            self.cell_title.set_markup(f"<b>Cell {c}, {r}</b>  ({len(st)} sprite{'s' if len(st) != 1 else ''}, "
                                       f"the last on top)")
            for p in st:
                self.stack_list.append(Gtk.Label(label=p.describe(), xalign=0, margin_start=8, margin_top=4,
                                                 margin_bottom=4))
            if 0 <= self.sel < len(st):
                self.stack_list.select_row(self.stack_list.get_row_at_index(self.sel))
        p = self._placement()
        self.controls.set_sensitive(p is not None)
        if p:
            self.dx.set_value(p.dx)
            self.dy.set_value(p.dy)
            self.fx.set_active(p.flip_x)
            self.fy.set_active(p.flip_y)
            self.inv.set_active(p.invert)
        self._loading = False

    def _row_selected(self, _lb, row):
        if self._loading or row is None:
            return
        self.sel = row.get_index()
        self._fill_stack()

    def _edit_placement(self):
        p = self._placement()
        if self._loading or not p:
            return
        p.dx, p.dy = int(self.dx.get_value()), int(self.dy.get_value())
        p.flip_x, p.flip_y, p.invert = self.fx.get_active(), self.fy.get_active(), self.inv.get_active()
        self._changed()

    def _order(self, by):
        if self._placement():
            self.sel = self.pad.raise_(*self.cell, self.sel, by)
            self._changed()

    def _remove(self):
        if self._placement():
            self.pad.remove(*self.cell, self.sel)
            self.sel = len(self.pad.stack(*self.cell)) - 1
            self._changed()

    # ---------------------------------------------------------------- export
    def _export(self):
        dlg = Gtk.FileDialog(title="Save the scratch pad as an image")
        base = self.editor.path
        dlg.set_initial_name(f"{base.stem if base else 'sprites'}-pad.png")
        if base:
            dlg.set_initial_folder(Gio.File.new_for_path(str(base.parent)))

        def done(d, res):
            try:
                self.save_png(Path(d.save_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.save(self, None, done)

    def save_png(self, path: Path, scale: int = 1):
        import cairo
        bm = self._image()
        out = cairo.ImageSurface(cairo.FORMAT_RGB24, bm.width * scale, bm.height * scale)
        cr = cairo.Context(out)
        paint_scaled(cr, bm.surface(), 0, 0, scale, scale)
        out.write_to_png(str(path))
