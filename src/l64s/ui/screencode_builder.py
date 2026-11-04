"""Screen Code Builder: build PRINT strings with colours, cursor moves and graphics, see what
they do on a C64 screen, and get them as BASIC, PETSCII bytes or screen codes."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from ..basic.petscii import CBM_KEYS, CODE_TO_NAME, SHIFT_KEYS  # noqa: E402
from ..basic.screencodes import (COLOUR_TO_CODE, BuildError, petscii_to_screencode, simulate_print,  # noqa: E402
                                 text_to_petscii, to_basic, to_petscii_bytes, to_screen_codes)
from ..gfx.charset import rom_charset  # noqa: E402
from ..gfx.palette import COLOUR_NAMES  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402
from .c64_keyboard import C64Keyboard  # noqa: E402
from .widgets import ColourButton, set_rgb  # noqa: E402

CONTROLS = [("CLR", "clear"), ("HOME", "home"), ("↑", "up"), ("↓", "down"), ("←", "left"), ("→", "right"),
            ("RVS ON", "reverse on"), ("RVS OFF", "reverse off"), ("RETURN", "return"), ("DEL", "delete"),
            ("INST", "insert"), ("lower case", "lower case"), ("UPPER", "upper case")]
FORMATS = [("basic", "BASIC PRINT statement"), ("petscii", "PETSCII bytes (for CHROUT)"),
           ("screen", "Screen codes (for screen memory)"), ("screen+colour", "Screen codes and colours")]
EXAMPLE = "{clear}{white}hello, {cyan}world!{return}{yellow}{reverse on} BASIC {reverse off} {cbm-a}{shift-*}{cbm-s}"

# The graphics typed with the Commodore and SHIFT keys, in keyboard order, as (key, PETSCII).
KEY_ORDER = "abcdefghijklmnopqrstuvwxyz+-@*£"
GRAPHIC_ROWS = [[("cbm-" + k, CBM_KEYS[k]) for k in KEY_ORDER if k in CBM_KEYS],
                [("shift-" + k, SHIFT_KEYS[k]) for k in KEY_ORDER + "^" if k in SHIFT_KEYS]]


def notation(code: int) -> str:
    """How to write a PETSCII character in the builder's text."""
    if 0xC1 <= code <= 0xDA:
        return chr(code - 0x80)            # shifted letters are just upper case
    name = CODE_TO_NAME.get(code)
    return f"{{{name}}}" if name else f"{{${code:02x}}}"


class GlyphPalette(Gtk.DrawingArea):
    """The CBM- and SHIFT-key graphics, drawn from the character ROM; click to insert one."""

    __gsignals__ = {"picked": (GObject.SignalFlags.RUN_FIRST, None, (int,))}
    PER_ROW = max(len(r) for r in GRAPHIC_ROWS)

    def __init__(self):
        super().__init__(content_height=2 * 24 + 6, hexpand=True)
        self.lowercase = False
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        self.add_controller(motion)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)
        self._hover = None

    def _cell(self, x, y):
        """(row, column) of the glyph under the pointer: row 0 is the Commodore key, row 1 SHIFT."""
        w = self.get_width() / self.PER_ROW
        col, row = int(x // w), int(y // 26)
        return (row, col) if 0 <= row < len(GRAPHIC_ROWS) and 0 <= col < len(GRAPHIC_ROWS[row]) else None

    def _draw(self, _w, cr, width, height):
        rom = rom_charset(not self.lowercase) or [[0] * 8 for _ in range(256)]
        w = width / self.PER_ROW
        size = min(w - 4, 22)
        for row, items in enumerate(GRAPHIC_ROWS):
            for col, (_name, code) in enumerate(items):
                x, y = col * w + (w - size) / 2, row * 26 + 2
                bm = Bitmap(8, 8)
                draw_char_into(bm, 0, 0, rom[petscii_to_screencode(code)], 1, 0)
                set_rgb(cr, 0)
                cr.rectangle(x - 1, y - 1, size + 2, size + 2)
                cr.fill()
                paint_scaled(cr, bm.surface(), x, y, size / 8, size / 8)
                if (row, col) == self._hover:
                    cr.set_source_rgb(1, 0.8, 0)
                    cr.set_line_width(2)
                    cr.rectangle(x - 1, y - 1, size + 2, size + 2)
                    cr.stroke()

    def _click(self, _g, _n, x, y):
        cell = self._cell(x, y)
        if cell is not None:
            self.emit("picked", GRAPHIC_ROWS[cell[0]][cell[1]][1])

    def _motion(self, _c, x, y):
        i = self._cell(x, y)
        if i != self._hover:
            self._hover = i
            self.queue_draw()

    def _tooltip(self, _w, x, y, _kb, tooltip):
        cell = self._cell(x, y)
        if cell is None:
            return False
        name, code = GRAPHIC_ROWS[cell[0]][cell[1]]
        tooltip.set_text(f"{name.upper()}  (PETSCII ${code:02X})")
        return True


class ScreenPreview(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, content_width=320, content_height=200)
        self.screen = None
        self.border, self.background = 14, 6
        self.set_draw_func(self._draw)

    def _draw(self, _w, cr, width, height):
        border = 16
        scale = max(0.5, min(width / (320 + 2 * border), height / (200 + 2 * border)))
        ox = (width - (320 + 2 * border) * scale) / 2
        oy = (height - (200 + 2 * border) * scale) / 2
        set_rgb(cr, self.border)
        cr.rectangle(ox, oy, (320 + 2 * border) * scale, (200 + 2 * border) * scale)
        cr.fill()
        s = self.screen
        if s is None:
            return
        rom = rom_charset(not s.lowercase) or [[0] * 8 for _ in range(256)]
        bm = Bitmap(320, 200)
        for r in range(25):
            for c in range(40):
                ch = s.chars[r][c]
                draw_char_into(bm, c * 8, r * 8, rom[ch], s.colours[r][c], self.background)
        # the cursor, where the next character would go
        cx, cy = s.col * 8, s.row * 8
        if cy < 200:
            for y in range(cy, cy + 8):
                for x in range(cx, min(cx + 8, 320)):
                    bm.pixels[y * 320 + x] = s.colour if bm.pixels[y * 320 + x] == self.background else self.background
        paint_scaled(cr, bm.surface(), ox + border * scale, oy + border * scale, scale, scale)


class ScreenCodeBuilder(EditorPage):
    kind = "screencodes"

    def __init__(self, kickass: bool = False, insert_cb=None, style: str = "standard"):
        super().__init__(None)
        self.kickass = kickass
        from ..basic.codestyles import STYLES
        self.style = style if style in STYLES else "standard"
        self.insert_cb = insert_cb
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=560,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_top=8,
                       margin_bottom=8, margin_end=4)
        paned.set_start_child(Gtk.ScrolledWindow(child=left, hscrollbar_policy=Gtk.PolicyType.NEVER))
        left.append(Gtk.Label(label="<b>Text</b>  type it, or click the keys below. Codes are written "
                                    "{like this}, as in a BASIC listing.", use_markup=True, xalign=0, wrap=True))
        self.text = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6,
                                 left_margin=6, css_classes=["card", "monospace"])
        self.text.set_size_request(-1, 90)
        self.text.get_buffer().set_text(EXAMPLE)
        self.text.get_buffer().connect("changed", lambda *_: self._update())
        left.append(self.text)
        # CBM prg Studio's Raw and Actual strings: the text above, and as it comes out (runs counted)
        actual = Gtk.Box(spacing=8)
        self.actual = Gtk.Label(xalign=0, hexpand=True, wrap=True, selectable=True, css_classes=["monospace"])
        actual.append(Gtk.Label(label="Actual", css_classes=["dim-label"]))
        actual.append(self.actual)
        from ..basic.codestyles import STYLES
        self._style_keys = list(STYLES)
        self.style_box = Gtk.DropDown.new_from_strings([v.split(" (")[0] for v in STYLES.values()])
        self.style_box.set_selected(self._style_keys.index(self.style))
        self.style_box.set_tooltip_text("How control codes are written: Linux64Studio's {clear} {cbm-a}, BasText's "
                                        "{clear} {cm a}, or Tok64's (as VICE's petcat) {clr} {CBM-A}")
        self.style_box.connect("notify::selected", lambda *_: self._style_changed())
        actual.append(self.style_box)
        left.append(actual)

        # three ways to add codes, as CBM prg Studio's tabs: the keyboard, a key map, and a list
        stack = Gtk.Stack()
        left.append(Gtk.StackSwitcher(stack=stack, halign=Gtk.Align.START))
        left.append(stack)
        kb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.keyboard = C64Keyboard()
        self.keyboard.connect("typed", self._typed)
        kb.append(self.keyboard)
        kb.append(Gtk.Label(label="Click SHIFT, C= or CTRL for the next key, double-click to lock it. Or type: "
                                  "Tab is CTRL and Ctrl is C=, as in CBM prg Studio. Hover over a key to see "
                                  "what it types.", xalign=0, wrap=True, css_classes=["dim-label", "caption"]))
        stack.add_titled(kb, "keyboard", "Virtual Keyboard")
        keymap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stack.add_titled(keymap, "keymap", "Key Map")
        stack.add_titled(self._code_list(), "codes", "Key Codes")
        keymap.append(Gtk.Label(label="<b>Colours</b>", use_markup=True, xalign=0))
        colours = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=16, min_children_per_line=8,
                              homogeneous=True)
        for c in range(16):
            b = Gtk.Button(tooltip_text=COLOUR_NAMES[c].lower())
            da = Gtk.DrawingArea(content_width=22, content_height=18)
            da.set_draw_func(lambda _w, cr, w, h, col=c: (set_rgb(cr, col), cr.paint()))
            b.set_child(da)
            b.connect("clicked", lambda _b, col=c: self.insert(self.code(COLOUR_TO_CODE[col])))
            colours.append(b)
        keymap.append(colours)

        keymap.append(Gtk.Label(label="<b>Keys</b>", use_markup=True, xalign=0))
        keys = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=13, min_children_per_line=5)
        for label, name in CONTROLS + [(f"F{n}", f"f{n}") for n in range(1, 9)]:
            b = Gtk.Button(label=label, tooltip_text="{" + name + "}")
            b.connect("clicked", lambda _b, n=name: self.insert(self.code(text_to_petscii("{" + n + "}")[0])))
            keys.append(b)
        keymap.append(keys)

        keymap.append(Gtk.Label(label="<b>Graphics</b>  Commodore key (top) and SHIFT (bottom)", use_markup=True,
                                xalign=0))
        self.glyphs = GlyphPalette()
        self.glyphs.connect("picked", lambda _g, code: self.insert(self.code(code)))
        keymap.append(self.glyphs)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=4, margin_end=8, margin_top=8,
                        margin_bottom=8)
        paned.set_end_child(right)
        head = Gtk.Box(spacing=6)
        head.append(Gtk.Label(label="<b>On the C64</b>", use_markup=True))
        head.append(Gtk.Box(hexpand=True))
        right.append(head)
        bar = Gtk.Box(spacing=6)
        self.border_btn = ColourButton(14, "Border")
        self.bg_btn = ColourButton(6, "Background")
        self.start_colour = ColourButton(14, "Cursor colour at the start")
        for lbl, w in (("Border", self.border_btn), ("Background", self.bg_btn), ("Text", self.start_colour)):
            bar.append(Gtk.Label(label=lbl, css_classes=["dim-label"]))
            bar.append(w)
            w.connect("changed", lambda *_: self._update())
        self.lower = Gtk.CheckButton(label="Start in lower case")
        self.lower.connect("toggled", lambda *_: self._update())
        head.append(self.lower)
        right.append(bar)
        self.preview = ScreenPreview()
        right.append(self.preview)

        out_bar = Gtk.Box(spacing=6)
        self.format = Gtk.DropDown.new_from_strings([f[1] for f in FORMATS])
        self.format.connect("notify::selected", lambda *_: self._update())
        out_bar.append(self.format)
        self.label = Gtk.Entry(placeholder_text="label", width_chars=10, tooltip_text="Label for byte output")
        self.label.connect("changed", lambda *_: self._update())
        out_bar.append(self.label)
        self.line_no = Gtk.SpinButton.new_with_range(0, 63999, 10)
        self.line_no.set_tooltip_text("BASIC line number (0 for none)")
        self.line_no.connect("value-changed", lambda *_: self._update())
        out_bar.append(self.line_no)
        self.zero = Gtk.CheckButton(label="End with 0", active=True)
        self.zero.connect("toggled", lambda *_: self._update())
        out_bar.append(self.zero)
        right.append(out_bar)
        out_bar = Gtk.Box(spacing=6)
        out_bar.append(Gtk.Box(hexpand=True))
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy")
        copy.connect("clicked", self._copy)
        out_bar.append(copy)
        ins = Gtk.Button(label="Insert into Editor", css_classes=["suggested-action"],
                         tooltip_text="Insert at the cursor in the source file you last edited")
        ins.connect("clicked", self._insert_into_editor)
        out_bar.append(ins)
        right.append(out_bar)
        self.output = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6,
                                   bottom_margin=6, left_margin=6, css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.output, min_content_height=110))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"])
        right.append(self.status)
        self._update()

    @property
    def title(self) -> str:
        return "Screen Code Builder"

    def _code_list(self):
        """Every named code, with how it's typed; double-click (or Enter) to add one."""
        from ..basic.keyboard import LABELS, keys_for
        from ..basic.petscii import CODE_TO_NAME
        lb = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        for code in sorted(CODE_TO_NAME):
            ways = ", ".join(f"{m.upper() + '+' if m else ''}{LABELS[k].split()[0]}" for k, m in keys_for(code)[:2])
            row = Gtk.ListBoxRow()
            row.code = code
            box = Gtk.Box(spacing=12, margin_start=8, margin_end=8, margin_top=3, margin_bottom=3)
            box.append(Gtk.Label(label="{" + CODE_TO_NAME[code] + "}", xalign=0, hexpand=True,
                                 css_classes=["monospace"]))
            box.append(Gtk.Label(label=ways, css_classes=["dim-label"]))
            box.append(Gtk.Label(label=f"${code:02X}  {code}", width_chars=8, xalign=1, css_classes=["monospace"]))
            row.set_child(box)
            lb.append(row)
        lb.connect("row-activated", lambda _l, row: self.insert(self.code(row.code)))
        return Gtk.ScrolledWindow(child=lb, min_content_height=240, vexpand=True)

    def _typed(self, _kb, code: int):
        from ..basic.keyboard import TOGGLE_CASE
        if code == TOGGLE_CASE:              # SHIFT + C=: switch to the other character set
            lower = self.preview.screen.lowercase if self.preview.screen else self.lower.get_active()
            self.insert("{upper case}" if lower else "{lower case}")
        else:
            self.insert(self.code(code))
        self.keyboard.grab_focus()

    def code(self, petscii: int) -> str:
        """One code, written in the chosen style."""
        from ..basic.codestyles import code_text
        return code_text(petscii, self.style)

    def _style_changed(self):
        self.style = self._style_keys[self.style_box.get_selected()]
        self._update()

    # ---------------------------------------------------------------- editing
    def insert(self, text: str):
        buf = self.text.get_buffer()
        buf.insert_at_cursor(text)
        self.text.grab_focus()

    def get_text(self) -> str:
        buf = self.text.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _update(self):
        self.preview.border, self.preview.background = self.border_btn.colour, self.bg_btn.colour
        fmt = FORMATS[self.format.get_selected()][0]
        self.line_no.set_visible(fmt == "basic")
        self.zero.set_visible(fmt == "petscii")
        self.label.set_visible(fmt != "basic")
        try:
            petscii = text_to_petscii(self.get_text())
            from ..basic.codestyles import string_text
            self.actual.set_text(string_text(petscii, self.style))
            screen = simulate_print(petscii, self.start_colour.colour, self.lower.get_active())
            self.preview.screen = screen
            self.glyphs.lowercase = screen.lowercase
            if self.keyboard.lowercase != screen.lowercase:
                self.keyboard.lowercase = screen.lowercase
                self.keyboard.queue_draw()
            label = self.label.get_text().strip()
            if fmt == "basic":
                n = int(self.line_no.get_value())
                out = to_basic(petscii, n or None, self.style)
            elif fmt == "petscii":
                out = to_petscii_bytes(petscii, label, self.kickass, self.zero.get_active())
            else:
                out = to_screen_codes(screen, label, self.kickass, colours=fmt == "screen+colour")
            self.output.get_buffer().set_text(out)
            self.status.set_text(f"{len(petscii)} PETSCII bytes" + (
                ". Screen codes skip the control codes: they hold what's left on the screen."
                if fmt.startswith("screen") else ""))
        except BuildError as e:
            self.status.set_text(str(e))
        self.preview.queue_draw()
        self.glyphs.queue_draw()

    def output_text(self) -> str:
        buf = self.output.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _copy(self, *_):
        Gdk.Display.get_default().get_clipboard().set(self.output_text())
        self.status.set_text("Copied to the clipboard")

    def _insert_into_editor(self, *_):
        if not self.insert_cb:
            return
        where = self.insert_cb(self.output_text())
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    def save(self):
        self.set_modified(False)

