"""The character scratch pad window (CBM prg Studio's Character Editor → Scratch Pad).

Paint the character selected in the editor with the left button, drag characters in from the
editor's character set, or use Get Characters for a list (1,2,3,4-10). Right button clears cells;
Shift+drag selects a block to cut, copy and paste (Ctrl+X, C, V) or for the screen designer to
stamp; double-click a cell to edit that character. The pad shows the editor's characters as they
are drawn, and is kept in the settings folder, so it's the same whichever set is open.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GObject, Gtk  # noqa: E402

from ..gfx import charscratch  # noqa: E402
from ..gfx.charscratch import ListError, parse_list  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402


class CharScratchPadWindow(Adw.Window):
    def __init__(self, parent, editor):
        super().__init__(transient_for=parent, title="Character Scratch Pad", default_width=900, default_height=560)
        self.editor = editor
        self.pad = charscratch.shared()
        self.zoom = 3
        self.clipboard: list | None = None
        self.anchor: tuple[int, int] | None = None     # where a Shift+drag started
        self.last_cell = (0, 0)

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        get = Gtk.Button(label="Get Characters…", tooltip_text="Put a list of characters (1,2,3,4-10) on the pad")
        get.connect("clicked", lambda *_: self._get_dialog())
        hb.pack_start(get)
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6, margin_bottom=6,
                       margin_start=6, margin_end=6)
        for label, cb in (("Clear the pad", self._clear), ("Clear the characters on it…", self._clear_chars_dialog)):
            b = Gtk.Button(label=label, css_classes=["flat"])
            b.connect("clicked", lambda _b, f=cb: (pop.popdown(), f()))
            menu.append(b)
        pop = Gtk.Popover(child=menu)
        hb.pack_start(Gtk.MenuButton(icon_name="edit-clear-all-symbolic", popover=pop, tooltip_text="Clear"))
        shifts = Gtk.Box(css_classes=["linked"])
        for icon, d, tip in (("go-previous-symbolic", (-1, 0), "Shift left"), ("go-next-symbolic", (1, 0), "Shift right"),
                             ("go-up-symbolic", (0, -1), "Shift up"), ("go-down-symbolic", (0, 1), "Shift down")):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip + " (wraps round)")
            b.connect("clicked", lambda _b, dd=d: self._shift(*dd))
            shifts.append(b)
        hb.pack_start(shifts)
        self.cols = Gtk.SpinButton.new_with_range(1, 80, 1)
        self.rows = Gtk.SpinButton.new_with_range(1, 50, 1)
        self.cols.set_value(self.pad.cols)
        self.rows.set_value(self.pad.rows)
        for s in (self.cols, self.rows):
            s.connect("value-changed", lambda *_: self._resize())
        size = Gtk.Box(spacing=4)
        for w in (Gtk.Label(label="Grid"), self.cols, Gtk.Label(label="×"), self.rows):
            size.append(w)
        hb.pack_start(size)
        zoom = Gtk.SpinButton.new_with_range(1, 8, 1)
        zoom.set_value(self.zoom)
        zoom.set_tooltip_text("Zoom")
        zoom.connect("value-changed", lambda s: self._set_zoom(int(s.get_value())))
        hb.pack_end(zoom)
        self.codes = Gtk.ToggleButton(label="#", tooltip_text="Show character codes")
        self.codes.connect("toggled", lambda *_: self.area.queue_draw())
        hb.pack_end(self.codes)
        self.grid_lines = Gtk.ToggleButton(icon_name="view-grid-symbolic", active=True, tooltip_text="Grid lines")
        self.grid_lines.connect("toggled", lambda *_: self.area.queue_draw())
        hb.pack_end(self.grid_lines)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_end=8,
                      margin_top=6, margin_bottom=8)
        tv.set_content(box)
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"], wrap=True)
        box.append(self.status)
        self.area = Gtk.DrawingArea(focusable=True, halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.area.set_draw_func(self._draw)
        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        self.area.add_controller(drag)
        dbl = Gtk.GestureClick()
        dbl.connect("pressed", self._double)
        self.area.add_controller(dbl)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        self.area.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        drop.connect("drop", self._dropped)
        self.area.add_controller(drop)
        box.append(Gtk.ScrolledWindow(child=self.area, vexpand=True, hexpand=True))
        self._size()
        self._hint()

    # ---------------------------------------------------------------- state
    def _changed(self):
        charscratch.save_shared()
        self.area.queue_draw()

    def refresh(self):
        self.area.queue_draw()

    def _hint(self, text: str | None = None):
        sel = charscratch.selection
        self.status.set_text(text or (
            f"Left: paint character {self.editor.index}. Right: clear. Shift+drag: select. "
            f"Double-click: edit that character." + (f"  Selected {sel[2]}×{sel[3]} (Ctrl+C, X, V; Esc)."
                                                    if sel else "")))

    def _size(self):
        self.area.set_content_width(self.pad.cols * 8 * self.zoom + 1)
        self.area.set_content_height(self.pad.rows * 8 * self.zoom + 1)

    def _set_zoom(self, z):
        self.zoom = z
        self._size()
        self.area.queue_draw()

    def _resize(self):
        self.pad.resize(int(self.cols.get_value()), int(self.rows.get_value()))
        charscratch.selection = None
        self._size()
        self._changed()

    def _clear(self):
        self.pad.clear()
        charscratch.selection = None
        self._hint()
        self._changed()

    def _shift(self, dx, dy):
        self.pad.shift(dx, dy)
        self._changed()

    # ---------------------------------------------------------------- drawing
    def colour_of(self, ch: int) -> int:
        """A character's colour RAM value, as the editor shows it."""
        ed = self.editor
        if ed.per_char:
            return ed.data.colour_of(ch)
        return ed.data.char_colour | (8 if ed.data.multicolour else 0)

    def _image(self) -> Bitmap:
        d = self.editor.data
        bm = Bitmap(self.pad.cols * 8, self.pad.rows * 8)
        bm.pixels[:] = bytes([d.background & 15]) * len(bm.pixels)
        for r in range(self.pad.rows):
            for c in range(self.pad.cols):
                ch = self.pad.cells[r][c]
                if ch is not None and ch < len(d.chars):
                    draw_char_into(bm, c * 8, r * 8, d.chars[ch], self.colour_of(ch), d.background,
                                   d.multicolour, d.mc1, d.mc2)
        return bm

    def _draw(self, _da, cr, w, h):
        z = self.zoom
        paint_scaled(cr, self._image().surface(), 0, 0, z, z)
        cs = 8 * z
        if self.grid_lines.get_active():
            cr.set_source_rgba(1, 1, 1, 0.18)
            cr.set_line_width(1)
            for c in range(self.pad.cols + 1):
                cr.move_to(c * cs + 0.5, 0)
                cr.line_to(c * cs + 0.5, self.pad.rows * cs)
            for r in range(self.pad.rows + 1):
                cr.move_to(0, r * cs + 0.5)
                cr.line_to(self.pad.cols * cs, r * cs + 0.5)
            cr.stroke()
        if self.codes.get_active():
            cr.set_font_size(max(7, cs * 0.32))
            for r in range(self.pad.rows):
                for c in range(self.pad.cols):
                    ch = self.pad.cells[r][c]
                    if ch is not None:
                        x, y = c * cs + 2, r * cs + cs * 0.36
                        cr.set_source_rgba(0, 0, 0, 0.7)
                        cr.rectangle(x - 1, y - cs * 0.3, cs * 0.6, cs * 0.36)
                        cr.fill()
                        cr.set_source_rgb(1, 1, 0.4)
                        cr.move_to(x, y)
                        cr.show_text(str(ch))
        sel = charscratch.selection
        if sel:
            c, r, sw, sh = sel
            cr.set_source_rgba(0.2, 0.8, 1.0, 0.95)
            cr.set_line_width(2)
            cr.set_dash([4, 3])
            cr.rectangle(c * cs + 1, r * cs + 1, sw * cs - 1, sh * cs - 1)
            cr.stroke()

    # ---------------------------------------------------------------- input
    def _cell(self, x, y):
        c, r = int(x // (8 * self.zoom)), int(y // (8 * self.zoom))
        return (c, r) if 0 <= c < self.pad.cols and 0 <= r < self.pad.rows else None

    def _drag_begin(self, g, x, y):
        self.area.grab_focus()
        self._start = (x, y)
        self._button = g.get_current_button()
        self._shift_sel = bool(g.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
        cell = self._cell(x, y)
        if cell:
            self.last_cell = cell
        if self._shift_sel and cell:
            self.anchor = cell
            charscratch.selection = (*cell, 1, 1)
            self._hint()
            self.area.queue_draw()
            return
        self._paint(cell)

    def _drag_update(self, _g, dx, dy):
        cell = self._cell(self._start[0] + dx, self._start[1] + dy)
        if not cell:
            return
        if self._shift_sel and self.anchor:
            (c0, r0), (c1, r1) = self.anchor, cell
            charscratch.selection = (min(c0, c1), min(r0, r1), abs(c1 - c0) + 1, abs(r1 - r0) + 1)
            self._hint()
            self.area.queue_draw()
        else:
            self._paint(cell)

    def _paint(self, cell):
        if not cell:
            return
        ch = None if self._button == 3 else self.editor.index
        if self.pad.get(*cell) != ch:
            self.pad.set(*cell, ch)
            self._changed()

    def _double(self, g, n, x, y):
        cell = self._cell(x, y)
        if n == 2 and cell and self.pad.get(*cell) is not None and g.get_current_button() == 1:
            self.editor._select(self.pad.get(*cell))
            self._hint()

    def _motion(self, _c, x, y):
        cell = self._cell(x, y)
        if cell:
            ch = self.pad.get(*cell)
            self._hint(f"Cell {cell[0]}, {cell[1]}: " + (f"character {ch} (${ch:02X})" if ch is not None else "empty")
                       + ".  Left: paint, right: clear, Shift+drag: select, double-click: edit it.")

    def _dropped(self, _t, value, x, y):
        cell = self._cell(x, y)
        if not cell or not str(value).startswith("char:"):
            return False
        self.pad.set(*cell, int(str(value).split(":")[1]))
        self._changed()
        return True

    def _key(self, _c, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        sel = charscratch.selection
        if keyval == Gdk.KEY_Escape and sel:
            charscratch.selection = None
            self._hint()
            self.area.queue_draw()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_x) and sel:
            self.clipboard = self.pad.copy(sel)
            if keyval == Gdk.KEY_x:
                self.pad.erase(sel)
                self._changed()
            return True
        if ctrl and keyval == Gdk.KEY_v and self.clipboard:
            at = sel[:2] if sel else self.last_cell
            self.pad.paste(self.clipboard, *at)
            self._changed()
            return True
        if keyval == Gdk.KEY_Delete and sel:
            self.pad.erase(sel)
            self._changed()
            return True
        return False

    # ---------------------------------------------------------------- dialogs
    def _get_dialog(self):
        dlg = Adw.AlertDialog(heading="Get Characters",
                              body="A list of characters, such as 1,2,3,4-10,11,12, put on the pad in order.")
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        entry = Gtk.Entry(placeholder_text="1,2,3,4-10", activates_default=True, hexpand=True)
        col = Gtk.SpinButton.new_with_range(0, self.pad.cols - 1, 1)
        row = Gtk.SpinButton.new_with_range(0, self.pad.rows - 1, 1)
        col.set_value(self.last_cell[0])
        row.set_value(self.last_cell[1])
        way = Gtk.DropDown.new_from_strings(["Across, then the next row", "Down, then the next column"])
        for r, (label, w) in enumerate((("Characters", entry), ("From column", col), ("From row", row),
                                        ("Going", way))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            grid.attach(w, 1, r, 1, 1)
        dlg.set_extra_child(grid)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Put Them on the Pad")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            try:
                codes = parse_list(entry.get_text())
            except ListError as e:
                self._hint(str(e))
                return
            left = self.pad.place_list(codes, int(col.get_value()), int(row.get_value()),
                                       across=way.get_selected() == 0)
            self._changed()
            self._hint(f"{len(codes) - left} characters put on the pad" +
                       (f"; {left} didn't fit (make the grid bigger)" if left else "."))
        dlg.choose(self, None, chosen)

    def _clear_chars_dialog(self):
        used = sorted(self.pad.used())
        if not used:
            self._hint("There are no characters on the pad.")
            return
        dlg = Adw.AlertDialog(heading="Clear the characters?",
                              body=f"This clears the pixels of the {len(used)} character{'s' if len(used) != 1 else ''} "
                                   f"on the pad in the character set (one Ctrl+Z in the editor undoes it), so you can "
                                   f"draw them afresh. The pad keeps them in place.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("clear", "Clear Them")
        dlg.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)

        def chosen(d, res):
            if d.choose_finish(res) == "clear":
                self.clear_characters()
        dlg.choose(self, None, chosen)

    def clear_characters(self):
        ed = self.editor
        chars = [ch for ch in sorted(self.pad.used()) if ch < len(ed.data.chars)]
        if not chars:
            return
        ed.undo.append(("group", [(ch, list(ed.data.chars[ch])) for ch in chars]))   # one Ctrl+Z undoes it
        for ch in chars:
            ed.data.chars[ch] = [0] * 8
        ed._changed()
        self.area.queue_draw()
