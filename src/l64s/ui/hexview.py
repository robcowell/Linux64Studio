"""An editable hex view of C64 memory for the debugger.

Type hex digits to overwrite the byte under the cursor (two digits make a byte, which is
written straight away). Arrow keys, Home/End and Page Up/Down move; the wheel scrolls.
Bytes that changed since the program last stopped are highlighted.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo  # noqa: E402

ROWS = 16
COLS = 16
PAGE = ROWS * COLS


def _screen_char(b: int) -> str:
    """How a byte looks as a screen code in the default (upper-case) character set, roughly."""
    c = b & 0x7F
    if c == 0:
        return "@"
    if 1 <= c <= 26:
        return chr(c + 64)
    if 32 <= c <= 63:
        return chr(c)
    return "."


class HexView(Gtk.DrawingArea):
    __gsignals__ = {
        "edit": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),      # address, new value
        "navigate": (GObject.SignalFlags.RUN_FIRST, None, (int,)),      # new first address
        "cursor-moved": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, focusable=True, can_focus=True)
        self.base = 0x0400
        self.data = b""
        self.previous: dict[int, int] = {}   # address -> value when the program last stopped
        self.cursor = self.base
        self.pending: int | None = None      # first hex digit typed for the cursor byte
        self.editable = False
        self.labels: dict[int, str] = {}
        self.set_draw_func(self._draw)
        self._font = Pango.FontDescription.from_string("Monospace 10")
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        self.add_controller(scroll)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._cancel_pending())
        self.add_controller(focus)

    # ---------------------------------------------------------------- data
    def set_data(self, base: int, data: bytes, snapshot: bool = False):
        """Show `data` starting at `base`. With snapshot, remember these as the 'stopped' values."""
        self.base = base & 0xFFFF
        self.data = data
        if snapshot:  # these are the reference values: nothing is highlighted yet
            self.previous = {self.base + i: b for i, b in enumerate(data)}
        if not self.base <= self.cursor < self.base + len(data):
            self.cursor = self.base
        self.pending = None
        self._fit_height()
        self.queue_draw()

    def value_at(self, addr: int) -> int | None:
        i = addr - self.base
        return self.data[i] if 0 <= i < len(self.data) else None

    # ---------------------------------------------------------------- geometry
    def _metrics(self):
        layout = self.create_pango_layout("0")
        layout.set_font_description(self._font)
        _ink, logical = layout.get_pixel_extents()
        return max(1, logical.width), max(1, logical.height) + 2

    def _fit_height(self):
        cw, ch = self._metrics()
        self.set_content_height(ch * (ROWS + 1) + 6)
        self.set_content_width(cw * (6 + COLS * 3 + COLS + 2) + 12)

    def _cell_x(self, col: int, cw: int) -> int:
        return 6 + cw * (6 + col * 3)

    def _ascii_x(self, col: int, cw: int) -> int:
        return 6 + cw * (6 + COLS * 3 + 1 + col)

    # ---------------------------------------------------------------- drawing
    def _draw(self, _w, cr, width, height):
        cw, ch = self._metrics()
        fg = self.get_color()
        layout = self.create_pango_layout("")
        layout.set_font_description(self._font)

        def text(x, y, s, rgba=None, bold=False):
            layout.set_text(s, -1)
            attrs = Pango.AttrList()
            if bold:
                attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
            layout.set_attributes(attrs)
            c = rgba or fg
            cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, layout)

        dim = Gdk.RGBA()
        dim.parse("rgba(128,128,128,0.9)")
        changed = Gdk.RGBA()
        changed.parse("#e01b24")
        header = "      " + " ".join(f"{c:02X}" for c in range(COLS))
        text(6, 2, header, dim)
        for r in range(ROWS):
            y = 2 + ch * (r + 1)
            row_addr = self.base + r * COLS
            if row_addr > 0xFFFF:
                break
            text(6, y, f"{row_addr:04X}", dim)
            for c in range(COLS):
                a = row_addr + c
                v = self.value_at(a)
                if v is None:
                    continue
                x = self._cell_x(c, cw)
                if a == self.cursor:
                    acc = self.get_color()
                    cr.set_source_rgba(acc.red, acc.green, acc.blue, 0.22 if self.has_focus() else 0.12)
                    cr.rectangle(x - 2, y, cw * 2 + 4, ch)
                    cr.fill()
                    cr.rectangle(self._ascii_x(c, cw), y, cw, ch)
                    cr.fill()
                was = self.previous.get(a)
                hot = was is not None and was != v
                s = f"{v:02X}"
                if a == self.cursor and self.pending is not None:
                    s = f"{self.pending:X}_"
                text(x, y, s, changed if hot else None, bold=hot)
                text(self._ascii_x(c, cw), y, _screen_char(v), changed if hot else dim)

    # ---------------------------------------------------------------- input
    def scrolled_base(self, addr: int) -> int:
        """Where the view should start so `addr` is visible, scrolling by whole rows."""
        base = self.base
        if addr < base:
            base -= COLS * -(-(base - addr) // COLS)
        elif addr >= base + PAGE:
            base += COLS * -(-(addr - (base + PAGE) + 1) // COLS)
        return max(0, min(base, 0x10000 - PAGE))

    def _move(self, addr: int):
        addr = max(0, min(addr, 0xFFFF))
        self.pending = None
        self.cursor = addr
        new = self.scrolled_base(addr)
        if new != self.base:
            self.emit("navigate", new)
        self.emit("cursor-moved", self.cursor)
        self.queue_draw()

    def _cancel_pending(self):
        if self.pending is not None:
            self.pending = None
            self.queue_draw()

    def _key(self, _c, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        moves = {"Left": -1, "Right": 1, "Up": -COLS, "Down": COLS, "Page_Up": -PAGE, "Page_Down": PAGE}
        if name in moves:
            self._move(self.cursor + moves[name])
            return True
        if name == "Home":
            self._move(self.cursor - (self.cursor - self.base) % COLS)
            return True
        if name == "End":
            self._move(self.cursor - (self.cursor - self.base) % COLS + COLS - 1)
            return True
        if name == "Escape":
            self._cancel_pending()
            return True
        ch = Gdk.keyval_to_unicode(keyval)
        if self.editable and ch and chr(ch) in "0123456789abcdefABCDEF" and not state & Gdk.ModifierType.CONTROL_MASK:
            d = int(chr(ch), 16)
            if self.pending is None:
                self.pending = d
                self.queue_draw()
            else:
                value = (self.pending << 4) | d
                addr = self.cursor
                self.pending = None
                self.emit("edit", addr, value)
                self._move(addr + 1)
            return True
        return False

    def _click(self, _g, _n, x, y):
        self.grab_focus()
        cw, ch = self._metrics()
        r = int((y - 2) // ch) - 1
        if not 0 <= r < ROWS:
            return
        for c in range(COLS):
            x0 = self._cell_x(c, cw)
            if x0 - 2 <= x <= x0 + cw * 2 + 2 or self._ascii_x(c, cw) <= x < self._ascii_x(c, cw) + cw:
                self._move(self.base + r * COLS + c)
                return

    def _scroll(self, _c, _dx, dy):
        step = COLS * (1 if dy > 0 else -1) * max(1, int(abs(dy)))
        self.emit("navigate", max(0, min(0x10000 - PAGE, self.base + step)))
        return True
