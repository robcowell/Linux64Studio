"""Character set editor (CBM prg Studio .cst or raw .bin) plus a reusable character picker."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from ..gfx.charset import Charset, rom_charset  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .exports import ExportLinks  # noqa: E402
from .render import paint_scaled, render_charset_grid  # noqa: E402
from .widgets import ColourButton, PixelCanvas  # noqa: E402


class CharGrid(Gtk.DrawingArea):
    """16x16 grid showing all 256 characters of a charset; click to select one."""

    __gsignals__ = {"selected": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, charset: Charset, scale: int = 2):
        super().__init__(content_width=16 * 8 * scale, content_height=16 * 8 * scale)
        self.charset = charset
        self.selected = 0
        self.fg, self.bg, self.mc1, self.mc2 = 1, 0, 1, 2
        self.per_char = False  # colour each character from charset.attribs (CharPad per-char colouring)
        self.colour_for = None  # or a function char -> colour RAM value
        self._surface = None
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._clicked)
        self.add_controller(click)
        # drag a character out (onto the character scratch pad)
        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag.connect("prepare", self._drag_prepare)
        self.add_controller(drag)

    def _char_at(self, x, y) -> int | None:
        s = min(self.get_width(), self.get_height()) / 128
        cx, cy = int(x // (8 * s)), int(y // (8 * s))
        return cy * 16 + cx if 0 <= cx < 16 and 0 <= cy < 16 else None

    def _drag_prepare(self, _src, x, y):
        ch = self._char_at(x, y)
        return Gdk.ContentProvider.new_for_value(f"char:{ch}") if ch is not None else None

    def invalidate(self):
        self._surface = None
        self.queue_draw()

    def _draw(self, _w, cr, w, h):
        if self._surface is None:
            if self.colour_for:
                fg = [self.colour_for(i) for i in range(len(self.charset.chars))]
            elif self.per_char:
                fg = [self.charset.colour_of(i) for i in range(len(self.charset.chars))]
            else:
                fg = self.fg | (8 if self.charset.multicolour else 0)
            bm = render_charset_grid(self.charset.chars, fg, self.bg, self.charset.multicolour, self.mc1, self.mc2)
            self._surface = bm.surface()
        s = min(w, h) / 128
        paint_scaled(cr, self._surface, 0, 0, s, s)
        x, y = (self.selected % 16) * 8 * s, (self.selected // 16) * 8 * s
        cr.set_source_rgb(1, 0.8, 0)
        cr.set_line_width(2)
        cr.rectangle(x + 1, y + 1, 8 * s - 2, 8 * s - 2)
        cr.stroke()

    def _clicked(self, _g, _n, x, y):
        s = min(self.get_width(), self.get_height()) / 128
        cx, cy = int(x // (8 * s)), int(y // (8 * s))
        if 0 <= cx < 16 and 0 <= cy < 16:
            self.selected = cy * 16 + cx
            self.queue_draw()
            self.emit("selected", self.selected)


class CharsetEditor(EditorPage):
    kind = "charset"

    def __init__(self, path: Path | None, data: Charset | None = None, per_char_colour: bool = False,
                 project=None, material_names=None):
        super().__init__(path)
        self.project = project
        # CharPad: each character's material (its attribute's high nibble), named by the project
        self.material_names = material_names
        # per_char_colour: each character has its own colour (CharPad); colours 8-15 make a character
        # multicolour when multicolour mode is on, 0-7 leave it hires.
        self.per_char = per_char_colour and data is not None and data.attribs is not None
        if data is not None:
            self.data = data
        elif path and path.exists():
            if path.suffix.lower() == ".cst":
                self.data = Charset.load_cst(path)
            else:
                self.data = Charset.from_bin(path.read_bytes())
        else:
            self.data = Charset()
            rom = rom_charset(True)
            if rom:
                self.data.chars = rom
        self.index = 0
        self.pen = 1
        self.undo: list[tuple[int, list[int]]] = []
        self.clipboard: list[int] | None = None
        self._pad_window = None
        self._anim_window = None
        self._build()
        self._select(0)

    def _build(self):
        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self.append(bar)
        for icon, tip, cb in [
            ("edit-undo-symbolic", "Undo (Ctrl+Z)", self.do_undo),
            ("edit-copy-symbolic", "Copy character (Ctrl+C)", self._copy),
            ("edit-paste-symbolic", "Paste character (Ctrl+V)", self._paste),
            ("edit-clear-all-symbolic", "Clear character", lambda *_: self._modify(lambda c: [0] * 8)),
            ("view-refresh-symbolic", "Invert character", lambda *_: self._modify(lambda c: [b ^ 0xFF for b in c])),
            ("object-flip-horizontal-symbolic", "Flip horizontally", lambda *_: self._modify(self._flip_x)),
            ("object-flip-vertical-symbolic", "Flip vertically", lambda *_: self._modify(lambda c: c[::-1])),
            ("go-previous-symbolic", "Shift left", lambda *_: self._modify(lambda c: [((b << 1) | (b >> 7)) & 0xFF for b in c])),
            ("go-next-symbolic", "Shift right", lambda *_: self._modify(lambda c: [((b >> 1) | (b << 7)) & 0xFF for b in c])),
            ("go-up-symbolic", "Shift up", lambda *_: self._modify(lambda c: c[1:] + c[:1])),
            ("go-down-symbolic", "Shift down", lambda *_: self._modify(lambda c: c[-1:] + c[:-1])),
            ("view-grid-symbolic", "Scratch Pad… (design graphics made of several characters)",
             lambda *_: self.open_scratch_pad()),
            ("media-playback-start-symbolic", "Animation… (play a run of characters as an animation)",
             lambda *_: self.open_animation()),
        ]:
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", cb)
            bar.append(b)
        bar.append(Gtk.Box(hexpand=True))
        self.links = None
        if self.path and self.path.suffix.lower() == ".cst":
            self.links = ExportLinks(self.path, [("bin", "Character data (.bin)", self.path.stem + ".bin",
                                                  lambda: self.data.to_bin())], self.project)
            bar.append(self.links)
        bar.append(Gtk.Label(label="Export"))
        self.export_count = Gtk.SpinButton.new_with_range(1, 256, 1)
        self.export_count.set_value(self.data.count)
        self.export_count.set_tooltip_text("Number of characters to export (each is 8 bytes)")
        self.export_count.connect("value-changed", lambda s: (setattr(self.data, "count", int(s.get_value())),
                                                              self.set_modified(True)))
        bar.append(self.export_count)
        bar.append(Gtk.Label(label="chars as"))
        for label, fmt in (("Binary…", "bin"), ("Source…", "asm")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, f=fmt: self._export(f))
            bar.append(b)

        body = Gtk.Box(spacing=8, vexpand=True, margin_start=6, margin_end=6, margin_bottom=6)
        self.append(body)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.grid = CharGrid(self.data, scale=3)
        self.grid.per_char = self.per_char
        self.grid.connect("selected", lambda _g, i: self._select(i))
        left.append(self.grid)
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"])
        left.append(self.status)
        body.append(Gtk.ScrolledWindow(child=left, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True))

        self.canvas = PixelCanvas()
        self.canvas.rows = 8
        self.canvas.colour_at = self._colour_at
        self.canvas.connect("paint", self._paint)
        self.canvas.connect("stroke-begin", lambda *_: self._push_undo())
        body.append(Gtk.Frame(child=self.canvas, hexpand=True))

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, width_request=230)
        body.append(Gtk.ScrolledWindow(child=side, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True))
        self.multi = Gtk.CheckButton(label="Multicolour", active=self.data.multicolour)
        self.multi.connect("toggled", self._multi_toggled)
        side.append(self.multi)
        side.append(Gtk.Label(label="<b>Pen</b> (left draw, right erase)", use_markup=True, xalign=0))
        g = Gtk.Grid(row_spacing=4, column_spacing=6)
        self.pen_buttons, self.colour_buttons = [], {}
        group = None
        for r, (pen, label, attr) in enumerate([(0, "Background ($D021)", "background"),
                                                 (1, "Multicolour 1 ($D022)", "mc1"),
                                                 (2, "Multicolour 2 ($D023)", "mc2"),
                                                 (3, "This character's colour" if self.per_char
                                                  else "Character colour (colour RAM)", "char_colour")]):
            rb = Gtk.CheckButton(label=label, group=group)
            group = group or rb
            rb.connect("toggled", self._pen_toggled, pen)
            cb = ColourButton(self._fg() if attr == "char_colour" else getattr(self.data, attr), label)
            cb.connect("changed", self._colour_changed, attr)
            g.attach(rb, 0, r, 1, 1)
            g.attach(cb, 1, r, 1, 1)
            self.pen_buttons.append(rb)
            self.colour_buttons[attr] = cb
        side.append(g)
        if self.per_char:
            side.append(Gtk.Label(label="Colours 8–15 make this character multicolour;\n0–7 keep it hires.",
                                  xalign=0, css_classes=["dim-label", "caption"]))
            mrow = Gtk.Box(spacing=6)
            mrow.append(Gtk.Label(label="Material"))
            self.material = Gtk.SpinButton.new_with_range(0, 15, 1)
            self.material.set_tooltip_text("CharPad's material for this character (the attribute's high "
                                           "nibble): games use it for collision and the like")
            self.material.connect("value-changed", self._material_changed)
            mrow.append(self.material)
            self.material_name = Gtk.Label(xalign=0, css_classes=["dim-label"])
            mrow.append(self.material_name)
            side.append(mrow)
        side.append(Gtk.Label(label="Preview (3x3 tiled)", xalign=0))
        self.preview = Gtk.DrawingArea(content_width=144, content_height=144)
        self.preview.set_draw_func(self._draw_preview)
        side.append(self.preview)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self._update_mode()

    # ---------------------------------------------------------------- state
    def _fg(self, i: int | None = None) -> int:
        """Colour RAM value of character i (the current one by default)."""
        i = self.index if i is None else i
        return self.data.colour_of(i) if self.per_char else self.data.char_colour

    def _is_mc(self, i: int | None = None) -> bool:
        """Whether character i is drawn in multicolour."""
        if not self.data.multicolour:
            return False
        return self._fg(i) >= 8 if self.per_char else True

    def _colours(self):
        return (self.data.background, self.data.mc1, self.data.mc2, self._fg() & 7)

    def _colour_at(self, x, y):
        mc = self._is_mc()
        v = self.data.get(self.index, x, y, mc)
        if mc:
            return self._colours()[v]
        return self._fg() if v else self.data.background

    def _update_mode(self):
        mc = self._is_mc()
        self.canvas.cols = 4 if mc else 8
        self.canvas.pixel_aspect = 2 if mc else 1
        for i in (1, 2):
            self.pen_buttons[i].set_visible(mc)
            self.colour_buttons[("mc1", "mc2")[i - 1]].set_visible(mc)
        if not mc and self.pen in (1, 2):
            self.pen = 1
        self.pen_buttons[0 if self.pen == 0 else (3 if not mc and self.pen == 1 else self.pen)].set_active(True)
        g = self.grid
        g.fg, g.bg, g.mc1, g.mc2 = self.data.char_colour, self.data.background, self.data.mc1, self.data.mc2
        g.invalidate()
        self.canvas.queue_draw()
        self.preview.queue_draw()
        for w in (getattr(self, "_pad_window", None), getattr(self, "_anim_window", None)):
            if w is not None:
                w.refresh()

    def _select(self, i):
        self.index = i
        self.grid.selected = i
        self.grid.queue_draw()
        self.status.set_text(f"Character {i} (${i:02X})" + (f"  colour {self._fg()}" if self.per_char else ""))
        if self.per_char:
            self.colour_buttons["char_colour"].colour = self._fg()
            self._showing = True
            self.material.set_value(self.data.material_of(i))
            self._showing = False
            self._show_material_name()
            self._update_mode()
        self.canvas.queue_draw()
        self.preview.queue_draw()
        if getattr(self, "_pad_window", None) is not None:
            self._pad_window._hint()

    def _show_material_name(self):
        names = self.material_names() if self.material_names else []
        m = self.data.material_of(self.index)
        self.material_name.set_text(names[m] if m < len(names) else "")

    def _material_changed(self, spin):
        if getattr(self, "_showing", False):
            return
        self.data.set_material_of(self.index, spin.get_value_as_int())
        self._show_material_name()
        self.set_modified(True)

    def _pen_toggled(self, btn, pen):
        if btn.get_active():
            self.pen = (1 if pen == 3 else 0) if not self._is_mc() else pen

    def _colour_changed(self, _b, colour, attr):
        if attr == "char_colour" and self.per_char:
            was_mc = self._is_mc()
            self.data.set_colour_of(self.index, colour)
            if was_mc != self._is_mc():  # the pen means "character colour" in both modes
                self.pen = {3: 1}.get(self.pen, 0) if was_mc else {1: 3}.get(self.pen, self.pen)
        else:
            setattr(self.data, attr, colour)
        self.set_modified(True)
        self._update_mode()

    def _multi_toggled(self, btn):
        self.data.multicolour = btn.get_active()
        self.pen = {1: 3}.get(self.pen, self.pen) if self.data.multicolour else (1 if self.pen else 0)
        self.set_modified(True)
        self._update_mode()

    def _paint(self, _c, x, y, button):
        self.data.set(self.index, x, y, 0 if button == 3 else self.pen, self._is_mc())
        self._changed()

    def _changed(self):
        self.set_modified(True)
        self.grid.invalidate()
        self.canvas.queue_draw()
        self.preview.queue_draw()
        if self._pad_window is not None:
            self._pad_window.refresh()
        if self._anim_window is not None:
            self._anim_window.refresh()

    def open_animation(self):
        from .char_animation import CharAnimationWindow
        if self._anim_window is None:
            self._anim_window = CharAnimationWindow(self.get_root(), self)
            self._anim_window.connect("close-request", lambda *_: (setattr(self, "_anim_window", None), False)[1])
        self._anim_window.present()
        return self._anim_window

    def open_scratch_pad(self):
        from .char_scratchpad import CharScratchPadWindow
        if self._pad_window is None:
            self._pad_window = CharScratchPadWindow(self.get_root(), self)
            self._pad_window.connect("close-request", lambda *_: (setattr(self, "_pad_window", None), False)[1])
        self._pad_window.present()
        return self._pad_window

    def _draw_preview(self, _da, cr, w, h):
        from .render import Bitmap, draw_char_into
        bm = Bitmap(24, 24)
        fg = self._fg() if self.per_char else self.data.char_colour | (8 if self.data.multicolour else 0)
        for ty in range(3):
            for tx in range(3):
                draw_char_into(bm, tx * 8, ty * 8, self.data.chars[self.index], fg, self.data.background,
                               self.data.multicolour, self.data.mc1, self.data.mc2)
        paint_scaled(cr, bm.surface(), 0, 0, w / 24, h / 24)

    # ---------------------------------------------------------------- edit ops
    @staticmethod
    def _flip_x(c):
        return [int(f"{b:08b}"[::-1], 2) for b in c]

    def _push_undo(self):
        self.undo.append((self.index, list(self.data.chars[self.index])))
        del self.undo[:-200]

    def _modify(self, fn):
        self._push_undo()
        self.data.chars[self.index] = [b & 0xFF for b in fn(list(self.data.chars[self.index]))]
        self._changed()

    def do_undo(self, *_):
        if self.undo:
            i, c = self.undo.pop()
            if i == "group":                    # several characters changed at once (scratch pad)
                for j, cj in c:
                    self.data.chars[j] = cj
                i = c[0][0]
            else:
                self.data.chars[i] = c
            self._select(i)
            self._changed()

    def _copy(self, *_):
        self.clipboard = list(self.data.chars[self.index])

    def _paste(self, *_):
        if self.clipboard:
            self._modify(lambda _c: list(self.clipboard))

    def _key(self, _c, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self.do_undo()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self._copy()
            return True
        if ctrl and keyval in (Gdk.KEY_v, Gdk.KEY_V):
            self._paste()
            return True
        moves = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1, Gdk.KEY_Up: -16, Gdk.KEY_Down: 16}
        if keyval in moves and not ctrl:
            self._select((self.index + moves[keyval]) % 256)
            return True
        return False

    # ---------------------------------------------------------------- save/export
    def save(self):
        if not self.path:
            raise ValueError("No file name")
        if self.path.suffix.lower() == ".cst":
            self.data.save_cst(self.path)
        else:
            self.path.write_bytes(self.data.to_bin())
        self.set_modified(False)
        return self.links.write_all() if self.links else []

    def _export(self, fmt: str):
        from gi.repository import Gio
        dlg = Gtk.FileDialog(title="Export characters")
        dlg.set_initial_name((self.path.stem if self.path else "characters") + (".bin" if fmt == "bin" else ".asm"))
        if self.path:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.path.parent)))
        count = int(self.export_count.get_value())

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            p = Path(f.get_path())
            if fmt == "bin":
                p.write_bytes(self.data.to_bin(count))
            else:
                p.write_text(self.data.to_source(p.stem, count))
        dlg.save(self.get_root(), None, done)
