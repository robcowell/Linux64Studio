"""Screen / map designer: edits CBM prg Studio .sdd files using a project charset."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from ..gfx.charset import Charset, rom_charset  # noqa: E402
from ..gfx.screen import Screen, ScreenSet  # noqa: E402
from .charset_editor import CharGrid  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402
from .widgets import ColourButton  # noqa: E402

TOOLS = [("draw", "document-edit-symbolic", "Draw"), ("fill", "color-select-symbolic", "Flood fill"),
         ("pick", "find-location-symbolic", "Pick character and colour"),
         ("colour", "applications-graphics-symbolic", "Paint colour only")]


class ScreenEditor(EditorPage):
    kind = "screen"

    def __init__(self, path: Path | None, charset_files: list[Path] | None = None):
        super().__init__(path)
        self.data = ScreenSet.load_sdd(path) if path and path.exists() else ScreenSet()
        self.index = 0
        self.tool = "draw"
        self.char = 160 if not self.data.multicolour else 0
        self.colour = 1
        self.undo: list[tuple[int, list, list]] = []
        self.charset = Charset()
        rom = rom_charset(True)
        if rom:
            self.charset.chars = rom
        self.charset.multicolour = self.data.multicolour
        self.charset_files = charset_files or []
        self._surface = None
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
            bar.append(b)
        ub = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Undo (Ctrl+Z)")
        ub.connect("clicked", self.do_undo)
        bar.append(ub)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(Gtk.Label(label="Screen"))
        self.screen_spin = Gtk.SpinButton.new_with_range(0, max(0, len(self.data.screens) - 1), 1)
        self.screen_spin.connect("value-changed", lambda s: self._select_screen(int(s.get_value())))
        bar.append(self.screen_spin)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add screen")
        add.connect("clicked", self._add_screen)
        bar.append(add)
        rm = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Delete screen")
        rm.connect("clicked", self._delete_screen)
        bar.append(rm)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(Gtk.Label(label="Charset"))
        names = ["C64 ROM"] + [p.name for p in self.charset_files]
        self.charset_combo = Gtk.DropDown.new_from_strings(names)
        self.charset_combo.connect("notify::selected", self._charset_changed)
        bar.append(self.charset_combo)
        bar.append(Gtk.Box(hexpand=True))
        exp = Gtk.Button(label="Export…")
        exp.connect("clicked", self._export_dialog)
        bar.append(exp)

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
        self.canvas.add_controller(motion)
        body.append(Gtk.Frame(child=self.canvas))

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.append(Gtk.ScrolledWindow(child=side, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True))
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
        side.append(g)
        side.append(self.mc_colour)
        self.multi = Gtk.CheckButton(label="Multicolour screen mode", active=self.data.multicolour)
        self.multi.connect("toggled", self._multi_toggled)
        side.append(self.multi)
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"])
        side.append(self.status)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    # ---------------------------------------------------------------- rendering
    def _invalidate(self):
        self._surface = None
        self.canvas.queue_draw()

    def _render(self):
        cols, rows = self.data.cols, self.data.rows
        bm = Bitmap(cols * 8, rows * 8)
        s = self.screen
        mc = self.data.multicolour
        for r in range(rows):
            for c in range(cols):
                draw_char_into(bm, c * 8, r * 8, self.charset.chars[s.chars[r][c] & 0xFF], s.colours[r][c] & 0x0F,
                               s.background, mc, s.bk1, s.bk2)
        return bm.surface()

    def _geometry(self):
        w, h = self.canvas.get_width(), self.canvas.get_height()
        border = 16
        pw, ph = self.data.cols * 8 + 2 * border, self.data.rows * 8 + 2 * border
        scale = max(0.5, min(w / pw, h / ph))
        ox = (w - pw * scale) / 2 + border * scale
        oy = (h - ph * scale) / 2 + border * scale
        return scale, ox, oy, border

    def _draw(self, _w, cr, w, h):
        from .widgets import set_rgb
        if self._surface is None:
            self._surface = self._render()
        scale, ox, oy, border = self._geometry()
        set_rgb(cr, self.screen.border)
        cr.rectangle(ox - border * scale, oy - border * scale,
                     (self.data.cols * 8 + 2 * border) * scale, (self.data.rows * 8 + 2 * border) * scale)
        cr.fill()
        paint_scaled(cr, self._surface, ox, oy, scale, scale)

    def _cell(self, x, y):
        scale, ox, oy, _ = self._geometry()
        c, r = int((x - ox) // (8 * scale)), int((y - oy) // (8 * scale))
        if 0 <= c < self.data.cols and 0 <= r < self.data.rows:
            return c, r
        return None

    # ---------------------------------------------------------------- input
    def _drag_begin(self, g, x, y):
        self._start = (x, y)
        self._button = g.get_current_button()
        self._last = None
        self._push_undo()
        self._apply(x, y)

    def _drag_update(self, _g, dx, dy):
        if self.tool in ("draw", "colour"):
            self._apply(self._start[0] + dx, self._start[1] + dy)

    def _motion(self, _c, x, y):
        cell = self._cell(x, y)
        if cell:
            c, r = cell
            s = self.screen
            self.status.set_text(f"Col {c}  Row {r}  char {s.chars[r][c]}  colour {s.colours[r][c] & 15}  "
                                 f"offset {r * self.data.cols + c}")

    def _ink(self) -> tuple[int, int]:
        colour = self.colour | (8 if self.mc_colour.get_active() else 0)
        if self._button == 3:
            return 32, colour
        return self.char, colour

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
        self.set_modified(True)
        self._invalidate()

    def _flood(self, c, r, old_ch, old_col, ch, col):
        if (old_ch, old_col) == (ch, col):
            return
        s = self.screen
        stack = [(c, r)]
        while stack:
            x, y = stack.pop()
            if not (0 <= x < self.data.cols and 0 <= y < self.data.rows):
                continue
            if s.chars[y][x] != old_ch or s.colours[y][x] != old_col:
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
        self.undo.append((self.index, [list(r) for r in s.chars], [list(r) for r in s.colours]))
        del self.undo[:-50]

    def do_undo(self, *_):
        if self.undo:
            i, chars, cols = self.undo.pop()
            if i < len(self.data.screens):
                self.data.screens[i].chars, self.data.screens[i].colours = chars, cols
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
        s = self.screen
        g = self.grid
        g.fg, g.bg, g.mc1, g.mc2 = self.colour, s.background, s.bk1, s.bk2
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
        self._invalidate()

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
