"""Screen Calculator: click or type a row and column to get its screen and colour memory addresses
(and BASIC, assembler and sprite coordinates for it); or type an address or sprite position to
find its cell."""
from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from ..screencalc import (COLOUR_BASE, COLUMNS, ROWS, SCREEN_BASE, locate, results, screen_address,  # noqa: E402
                          sprite_cell)
from ..vicmem import Layout  # noqa: E402
from . import textzoom  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .widgets import ColourButton  # noqa: E402

INSERTABLE = {"BASIC", "Assembler", "Expression", "C"}


def parse_value(text: str) -> int:
    """$hex, 0xhex, %binary or decimal."""
    t = text.strip().replace("_", "")
    if not t:
        raise ValueError("Nothing entered")
    try:
        if t.startswith("$"):
            return int(t[1:], 16)
        if t.lower().startswith("0x"):
            return int(t[2:], 16)
        if t.startswith("%"):
            return int(t[1:], 2)
        if re.fullmatch(r"\d+", t):
            return int(t)
        if re.fullmatch(r"[0-9A-Fa-f]+", t):
            return int(t, 16)          # D800, C000: plainly hex
    except ValueError:
        pass
    raise ValueError(f"{text.strip()} isn't a number ($hex, %binary or decimal)")


class ScreenGrid(Gtk.DrawingArea):
    """The 40×25 screen; click a cell to choose it."""

    __gsignals__ = {"picked": (GObject.SignalFlags.RUN_FIRST, None, (int, int))}
    CW, CH, MARGIN = 13, 10, 22

    def __init__(self):
        super().__init__(halign=Gtk.Align.START)
        self.text_zoom_changed()
        self.row, self.col = 0, 0
        self.hover: tuple[int, int] | None = None
        self.base = SCREEN_BASE
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", lambda *_: self._set_hover(None))
        self.add_controller(motion)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)

    def text_zoom_changed(self):                # the whole grid is drawn to scale, for its rulers
        self.set_content_width(int(textzoom.px(self.MARGIN + COLUMNS * self.CW + 2)))
        self.set_content_height(int(textzoom.px(self.MARGIN + ROWS * self.CH + 2)))

    def _cell(self, x, y):
        x, y = x / textzoom.factor(), y / textzoom.factor()
        c, r = int((x - self.MARGIN) // self.CW), int((y - self.MARGIN) // self.CH)
        return (r, c) if 0 <= r < ROWS and 0 <= c < COLUMNS and x >= self.MARGIN and y >= self.MARGIN else None

    def _click(self, _g, _n, x, y):
        cell = self._cell(x, y)
        if cell:
            self.emit("picked", *cell)

    def _motion(self, _c, x, y):
        self._set_hover(self._cell(x, y))

    def _set_hover(self, cell):
        if cell != self.hover:
            self.hover = cell
            self.queue_draw()

    def _tooltip(self, _w, x, y, _kb, tip):
        cell = self._cell(x, y)
        if not cell:
            return False
        r, c = cell
        a = screen_address(r, c, self.base)
        tip.set_text(f"Row {r}, column {c}: ${a:04X} ({a}), colour ${COLOUR_BASE + r * 40 + c:04X}")
        return True

    def select(self, row, col):
        self.row, self.col = row, col
        self.queue_draw()

    def _draw(self, _w, cr, _width, _height):
        cr.scale(textzoom.factor(), textzoom.factor())
        m, cw, ch = self.MARGIN, self.CW, self.CH
        fg = self.get_color()
        # the screen
        cr.set_source_rgb(0.21, 0.16, 0.47)          # the C64's blue
        cr.rectangle(m, m, COLUMNS * cw, ROWS * ch)
        cr.fill()
        if self.hover:
            r, c = self.hover
            cr.set_source_rgba(1, 1, 1, 0.25)
            cr.rectangle(m, m + r * ch, COLUMNS * cw, ch)
            cr.rectangle(m + c * cw, m, cw, ROWS * ch)
            cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.12)
        cr.set_line_width(1)
        for c in range(COLUMNS + 1):
            cr.move_to(m + c * cw + 0.5, m)
            cr.line_to(m + c * cw + 0.5, m + ROWS * ch)
        for r in range(ROWS + 1):
            cr.move_to(m, m + r * ch + 0.5)
            cr.line_to(m + COLUMNS * cw, m + r * ch + 0.5)
        cr.stroke()
        cr.set_source_rgb(0.53, 0.84, 1.0)
        cr.rectangle(m + self.col * cw + 1, m + self.row * ch + 1, cw - 1, ch - 1)
        cr.fill()
        # rulers
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
        cr.select_font_face("Monospace")
        cr.set_font_size(9)
        for c in range(0, COLUMNS, 5):
            cr.move_to(m + c * cw + 2, m - 6)
            cr.show_text(str(c))
        for r in range(0, ROWS, 5):
            cr.move_to(2, m + r * ch + 9)
            cr.show_text(str(r))


class ScreenCalculator(EditorPage):
    kind = "screencalc"

    def __init__(self, kickass: bool = False, get_session=None, get_layout=None, insert_cb=None):
        super().__init__(None)
        self.kickass = kickass
        # the syntax to write (syntax.py): the window gives a function that follows where the
        # text is going (C or ca65 in a C project); on its own, Kick or CBM as kickass says
        self.syntax = lambda: "kick" if self.kickass else "cbm"
        self.get_session = get_session      # () -> DebugSession or None
        self.get_layout = get_layout        # () -> the Memory Manager's Layout, or None
        self.insert_cb = insert_cb
        self._busy = False

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        self.append(scroll)
        top = Gtk.Box(spacing=20, margin_start=10, margin_end=10, margin_top=8, margin_bottom=8)
        scroll.set_child(top)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        # ---- inputs
        form = Gtk.Grid(column_spacing=8, row_spacing=6, valign=Gtk.Align.START)
        r = 0

        def label(text):
            return Gtk.Label(label=text, xalign=0)

        form.attach(Gtk.Label(label="<b>Cell</b>", use_markup=True, xalign=0), 0, r, 3, 1)
        r += 1
        form.attach(label("Row"), 0, r, 1, 1)
        self.row = Gtk.SpinButton.new_with_range(0, ROWS - 1, 1)
        self.row.connect("value-changed", lambda *_: self._update())
        form.attach(self.row, 1, r, 1, 1)
        r += 1
        form.attach(label("Column"), 0, r, 1, 1)
        self.col = Gtk.SpinButton.new_with_range(0, COLUMNS - 1, 1)
        self.col.connect("value-changed", lambda *_: self._update())
        form.attach(self.col, 1, r, 1, 1)
        r += 1
        form.attach(label("Character"), 0, r, 1, 1)
        self.char = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.char.set_value(1)
        self.char.set_tooltip_text("The screen code to put there, for the BASIC and assembler lines (1 = A)")
        self.char.connect("value-changed", lambda *_: self._update())
        form.attach(self.char, 1, r, 1, 1)
        self.colour = ColourButton(1, "Its colour")
        self.colour.connect("changed", lambda *_: self._update())
        form.attach(self.colour, 2, r, 1, 1)
        r += 1

        form.attach(Gtk.Label(label="<b>Memory</b>", use_markup=True, xalign=0, margin_top=6), 0, r, 3, 1)
        r += 1
        form.attach(label("Screen base"), 0, r, 1, 1)
        self.screen_base = Gtk.Entry(text=f"${SCREEN_BASE:04X}", width_chars=8)
        self.screen_base.connect("changed", lambda *_: self._update())
        form.attach(self.screen_base, 1, r, 1, 1)
        from_btn = Gtk.MenuButton(label="From…", tooltip_text="Take the screen address from somewhere")
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_start=4, margin_end=4,
                       margin_top=4, margin_bottom=4)
        for text, cb in (("The C64's default ($0400)", lambda: self._set_base(SCREEN_BASE, "the default")),
                         ("The running program (VICE)", self._base_from_vice),
                         ("The Memory Manager's layout", self._base_from_layout)):
            b = Gtk.Button(label=text, css_classes=["flat"])
            b.connect("clicked", lambda _b, cb=cb, p=pop: (p.popdown(), cb()))
            pbox.append(b)
        pop.set_child(pbox)
        from_btn.set_popover(pop)
        form.attach(from_btn, 2, r, 1, 1)
        r += 1
        form.attach(label("Colour base"), 0, r, 1, 1)
        self.colour_base = Gtk.Entry(text=f"${COLOUR_BASE:04X}", width_chars=8,
                                     tooltip_text="Colour RAM is always at $D800 on the C64")
        self.colour_base.connect("changed", lambda *_: self._update())
        form.attach(self.colour_base, 1, r, 1, 1)
        r += 1

        form.attach(Gtk.Label(label="<b>Find the cell</b>", use_markup=True, xalign=0, margin_top=6), 0, r, 3, 1)
        r += 1
        form.attach(label("At address"), 0, r, 1, 1)
        self.find_addr = Gtk.Entry(placeholder_text="$0590 or 1424", width_chars=10)
        self.find_addr.connect("activate", lambda *_: self._find_address())
        form.attach(self.find_addr, 1, r, 1, 1)
        go = Gtk.Button(icon_name="edit-find-symbolic", tooltip_text="Find (Enter)")
        go.connect("clicked", lambda *_: self._find_address())
        form.attach(go, 2, r, 1, 1)
        r += 1
        form.attach(label("Under sprite X, Y"), 0, r, 1, 1)
        sb = Gtk.Box(spacing=4)
        self.spr_x = Gtk.SpinButton.new_with_range(0, 511, 1)
        self.spr_y = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.spr_x.set_value(24)
        self.spr_y.set_value(50)
        sb.append(self.spr_x)
        sb.append(self.spr_y)
        form.attach(sb, 1, r, 1, 1)
        go2 = Gtk.Button(icon_name="edit-find-symbolic", tooltip_text="Find the cell under the sprite's top-left corner")
        go2.connect("clicked", lambda *_: self._find_sprite())
        form.attach(go2, 2, r, 1, 1)
        self.grid = ScreenGrid()
        self.grid.connect("picked", lambda _g, r, c: self.set_cell(r, c))
        outer.append(self.grid)
        top.append(outer)
        top.append(form)

        # ---- results
        outer.append(Gtk.Label(label="<b>Results</b>", use_markup=True, xalign=0))
        self.results = Gtk.Grid(column_spacing=10, row_spacing=4)
        outer.append(self.results)
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"],
                                label="Click a cell on the screen, or type its row and column")
        outer.append(self.status)
        self._update()

    @property
    def title(self) -> str:
        return "Screen Calculator"

    def save(self) -> None:
        pass

    # ================================================================== the cell
    def set_cell(self, row: int, col: int):
        self._busy = True
        self.row.set_value(row)
        self.col.set_value(col)
        self._busy = False
        self._update()

    def _bases(self) -> tuple[int, int]:
        sb, cb = parse_value(self.screen_base.get_text()), parse_value(self.colour_base.get_text())
        for name, v in (("screen", sb), ("colour", cb)):
            if not 0 <= v <= 0xFFFF - 999:
                raise ValueError(f"The {name} base must be $0000-${0xFFFF - 999:04X}")
        return sb, cb

    def _update(self):
        if self._busy:
            return
        row, col = self.row.get_value_as_int(), self.col.get_value_as_int()
        self.grid.select(row, col)
        child = self.results.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.results.remove(child)
            child = nxt
        try:
            sb, cb = self._bases()
        except ValueError as e:
            self.status.set_text(str(e))
            return
        self.grid.base = sb
        for i, res in enumerate(results(row, col, sb, cb, self.char.get_value_as_int(), self.colour.colour,
                                        self.kickass, syntax=self.syntax())):
            self.results.attach(Gtk.Label(label=res.label, xalign=0, yalign=0, css_classes=["dim-label"]), 0, i, 1, 1)
            self.results.attach(Gtk.Label(label=res.text, xalign=0, selectable=True, css_classes=["monospace"]),
                                1, i, 1, 1)
            btns = Gtk.Box(spacing=2, valign=Gtk.Align.START)
            cp = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy", css_classes=["flat"])
            value = res.text.split("  (")[0] if res.label in ("Screen address", "Colour address", "Offset") else res.text
            cp.connect("clicked", lambda _b, v=value, n=res.label: self._copy(v, n))
            btns.append(cp)
            if res.label in INSERTABLE and self.insert_cb:
                ins = Gtk.Button(icon_name="insert-text-symbolic", tooltip_text="Insert into the editor",
                                 css_classes=["flat"])
                ins.connect("clicked", lambda _b, v=res.text: self._insert(v))
                btns.append(ins)
            self.results.attach(btns, 2, i, 1, 1)
        self.status.set_text(f"Row {row}, column {col}")

    def _copy(self, text: str, what: str):
        Gdk.Display.get_default().get_clipboard().set(text)
        self.status.set_text(f"Copied the {what.lower()}: {text.splitlines()[0].strip()}")

    def _insert(self, text: str):
        where = self.insert_cb(text)
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    # ================================================================== bases
    def _set_base(self, addr: int, where: str):
        self.screen_base.set_text(f"${addr:04X}")
        self.status.set_text(f"Screen memory at ${addr:04X}, from {where}")

    def _base_from_vice(self):
        s = self.get_session() if self.get_session else None
        if not s or not s.monitor.connected:
            self.status.set_text("Start debugging (Shift+F5) to read the running program's screen address")
            return
        try:
            mem = s.snapshot_memory()
        except Exception as e:  # the session may have ended in between
            self.status.set_text(f"Couldn't read VICE's memory: {e}")
            return
        lay = Layout.from_registers(mem[0xDD00], mem[0xD018], mem[0xD011])
        self._set_base(lay.screen_addr, f"the running program ($DD00 = ${mem[0xDD00]:02X}, "
                                        f"$D018 = ${mem[0xD018]:02X})")

    def _base_from_layout(self):
        lay = self.get_layout() if self.get_layout else None
        if lay is None:
            self.status.set_text("Open the Memory Manager and plan a layout first")
            return
        self._set_base(lay.screen_addr, f"the Memory Manager (bank {lay.bank})")

    # ================================================================== finding cells
    def _find_address(self):
        try:
            addr = parse_value(self.find_addr.get_text())
            sb, cb = self._bases()
        except ValueError as e:
            self.status.set_text(str(e))
            return
        where = locate(addr, sb, cb)
        if not where:
            self.status.set_text(f"${addr:04X} isn't in screen memory (${sb:04X}-${sb + 999:04X}) or colour RAM "
                                 f"(${cb:04X}-${cb + 999:04X})")
            return
        self.set_cell(where.row, where.col)
        self.status.set_text(f"${addr:04X} is row {where.row}, column {where.col} of "
                             + ("screen memory" if where.area == "screen" else "colour RAM"))

    def _find_sprite(self):
        x, y = self.spr_x.get_value_as_int(), self.spr_y.get_value_as_int()
        cell = sprite_cell(x, y)
        if not cell:
            self.status.set_text(f"Sprite position {x}, {y} is in the border (the screen is X 24-343, Y 50-249)")
            return
        self.set_cell(*cell)
        self.status.set_text(f"Sprite position {x}, {y} is over row {cell[0]}, column {cell[1]}")
