"""A C64 keyboard to click (CBM prg Studio's Screen Code Builder → Virtual Keyboard). Each key
types what a C64 would (the KERNAL's tables, basic/keyboard.py); its face shows the Commodore and
SHIFT graphics, and on 1-8 the CTRL and Commodore colours.

SHIFT, C= and CTRL hold for the next key; double-click one to lock it (SHIFT LOCK locks SHIFT).
It can be typed on too: as in CBM prg Studio, Tab is CTRL and Ctrl is the Commodore key.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo  # noqa: E402

from ..basic.keyboard import (CBM_KEY, CTRL_KEY, LAYOUT, LSHIFT, PC_SPECIAL, RSHIFT, SHIFT_LOCK, decode,  # noqa: E402
                              pc_key)
from ..basic.screencodes import COLOUR_CODES, petscii_to_screencode  # noqa: E402
from ..gfx.charset import rom_charset  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402
from .widgets import set_rgb  # noqa: E402

WIDTH_UNITS = 18.5


class C64Keyboard(Gtk.DrawingArea):
    """Emits "typed" with the PETSCII code (or keyboard.TOGGLE_CASE) of each key pressed."""

    __gsignals__ = {"typed": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self):
        super().__init__(hexpand=True, content_height=170, focusable=True)
        self.mods = {"shift": 0, "cbm": 0, "ctrl": 0}       # 0 off, 1 for the next key, 2 locked
        self.lowercase = False
        self._pressed = None
        self._tab = False
        self._glyphs: dict = {}
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        click.connect("released", lambda *_: (setattr(self, "_pressed", None), self.queue_draw()))
        self.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key_down)
        keys.connect("key-released", self._key_up)
        self.add_controller(keys)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)

    # ---------------------------------------------------------------- geometry
    def _unit(self) -> float:
        return min(self.get_width() / WIDTH_UNITS, self.get_height() / 5.2)

    def _key_rect(self, k):
        u = self._unit()
        ox = (self.get_width() - WIDTH_UNITS * u) / 2
        return ox + k.x * u + 1.5, 4 + k.y * u + 1.5, k.w * u - 3, u - 3

    def _key_at(self, x, y):
        for k in LAYOUT:
            kx, ky, kw, kh = self._key_rect(k)
            if kx <= x <= kx + kw and ky <= y <= ky + kh:
                return k
        return None

    # ---------------------------------------------------------------- state
    def held(self, name) -> bool:
        return self.mods[name] > 0

    def _mod_for(self, code):
        return {LSHIFT: "shift", RSHIFT: "shift", SHIFT_LOCK: "shift", CBM_KEY: "cbm", CTRL_KEY: "ctrl"}.get(code)

    def press(self, code: int, shift=None, cbm=None, ctrl=None):
        """Type a key, with the held modifiers unless given."""
        v = decode(code, self.held("shift") if shift is None else shift, self.held("cbm") if cbm is None else cbm,
                   self.held("ctrl") if ctrl is None else ctrl)
        for m in self.mods:
            if self.mods[m] == 1:
                self.mods[m] = 0                   # one-shot modifiers are used up
        if v is not None:
            self.emit("typed", v)
        self.queue_draw()
        return v

    # ---------------------------------------------------------------- mouse
    def _click(self, g, n, x, y):
        self.grab_focus()
        k = self._key_at(x, y)
        if k is None:
            return
        mod = self._mod_for(k.code)
        if mod:
            if k.code == SHIFT_LOCK:
                self.mods["shift"] = 0 if self.mods["shift"] == 2 else 2
            elif n == 2:
                self.mods[mod] = 2                  # double-click: locked
            else:
                self.mods[mod] = 0 if self.mods[mod] else 1
            self.queue_draw()
            return
        self._pressed = k.code
        self.press(k.code)

    def _tooltip(self, _w, x, y, _kb, tooltip):
        k = self._key_at(x, y)
        if k is None:
            return False
        from ..basic.petscii import petscii_to_text
        parts = []
        for name, kw in (("", {}), ("SHIFT", {"shift": True}), ("C=", {"cbm": True}), ("CTRL", {"ctrl": True})):
            v = decode(k.code, **kw)
            if v is not None and v >= 0:
                parts.append(f"{name + '+' if name else ''}{k.label.split()[0]}: {petscii_to_text(v, True)}  (${v:02X})")
        tooltip.set_text("\n".join(parts) or k.label)
        return True

    # ---------------------------------------------------------------- the PC keyboard
    def _key_down(self, _c, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        if name in ("Tab", "ISO_Left_Tab"):
            self._tab = True
            return True
        if name.startswith(("Control", "Shift", "Alt", "Super", "Meta")):
            return False
        pc_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        cbm = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if name in PC_SPECIAL:
            code, shifted = PC_SPECIAL[name]
            self._pressed = code
            self.press(code, shift=shifted or pc_shift or self.held("shift"), cbm=cbm or self.held("cbm"),
                       ctrl=self._tab or self.held("ctrl"))
            return True
        ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        if cbm or self._tab:
            ch = ch.lower()
        hit = pc_key(ch)
        if hit is None:
            return False
        code, shifted = hit
        self._pressed = code
        self.press(code, shift=shifted or self.held("shift"), cbm=cbm or self.held("cbm"),
                   ctrl=self._tab or self.held("ctrl"))
        return True

    def _key_up(self, _c, keyval, _code, _state):
        if (Gdk.keyval_name(keyval) or "") in ("Tab", "ISO_Left_Tab"):
            self._tab = False
        self._pressed = None
        self.queue_draw()

    # ---------------------------------------------------------------- drawing
    def _glyph(self, petscii: int):
        sc = petscii_to_screencode(petscii)
        if sc is None:
            return None
        key = (sc, self.lowercase)
        if key not in self._glyphs:
            rom = rom_charset(not self.lowercase)
            if not rom:
                return None
            bm = Bitmap(8, 8)
            draw_char_into(bm, 0, 0, rom[sc], 1, 11)
            self._glyphs[key] = bm.surface()
        return self._glyphs[key]

    def _draw(self, _w, cr, width, height):
        u = self._unit()
        for k in LAYOUT:
            x, y, w, h = self._key_rect(k)
            mod = self._mod_for(k.code)
            level = self.mods[mod] if mod else 0          # 1 held for the next key, 2 locked
            if k.code == SHIFT_LOCK:
                level = 2 if level == 2 else 0
            if level == 2:
                cr.set_source_rgb(0.15, 0.40, 0.75)
            elif level == 1 or k.code == self._pressed:
                cr.set_source_rgb(0.30, 0.55, 0.85)
            elif k.code in (4, 5, 6, 3):
                cr.set_source_rgb(0.55, 0.45, 0.35)
            else:
                cr.set_source_rgb(0.33, 0.27, 0.24)
            r = min(4, h / 6)
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -1.5708, 0)
            cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
            cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
            cr.arc(x + r, y + r, r, 3.1416, 4.7124)
            cr.close_path()
            cr.fill()
            # the label (Pango, so arrows and £ come from whichever font has them)
            cr.set_source_rgb(0.95, 0.93, 0.88)
            words = k.label.split()
            small = len(words) > 1 or len(k.label) > 2
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(Pango.FontDescription.from_string(
                f"Sans {'' if small else 'Bold '}{max(7, int(u * (0.22 if small else 0.34)))}px"))
            layout.set_text("\n".join(words) if small else k.label, -1)
            layout.set_alignment(Pango.Alignment.CENTER)
            lw, lh = layout.get_pixel_size()
            cr.move_to(x + (w - lw) / 2 if small else x + u * 0.12, y + (h - lh) / 2 if small else y + u * 0.04)
            PangoCairo.show_layout(cr, layout)
            if small:
                continue
            # the Commodore graphic (left) and the SHIFT graphic (right), as on the keys
            g = max(6, u * 0.3)
            for petscii, gx in ((decode(k.code, cbm=True), x + u * 0.1), (decode(k.code, shift=True), x + w - g - u * 0.1)):
                if petscii is None or (0x20 <= petscii < 0x60) or petscii in COLOUR_CODES:
                    continue
                surf = self._glyph(petscii)
                if surf is not None:
                    paint_scaled(cr, surf, gx, y + h - g - u * 0.08, g / 8, g / 8)
            # 1-8: the colours CTRL (top) and C= (bottom) type
            for petscii, cy in ((decode(k.code, ctrl=True), y + u * 0.12), (decode(k.code, cbm=True), y + h - u * 0.3)):
                if petscii in COLOUR_CODES:
                    set_rgb(cr, COLOUR_CODES[petscii])
                    cr.rectangle(x + w - u * 0.36, cy, u * 0.24, u * 0.16)
                    cr.fill()
