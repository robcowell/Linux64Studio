"""SYS() call generator: the bytes of a BASIC line that starts a machine code program, to put at
the top of an assembler source."""
from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from ..sysgen import SysCall, SysError, generate, source  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .screen_calculator import parse_value  # noqa: E402

STYLE_LABELS = [("decorated", "Decorated, e.g. 10 SYS (4096)"), ("plain", "Plain, e.g. 10 SYS4096"),
                ("obfuscated", "Obfuscated: lists as a message instead")]


class SysCallGenerator(EditorPage):
    kind = "sysgen"

    def __init__(self, kickass: bool = False, insert_cb=None, get_target=None, get_symbols=None):
        super().__init__(None)
        self.kickass = kickass
        # the syntax to write (syntax.py): the window gives a function that follows where the
        # text is going (C or ca65 in a C project); on its own, Kick or CBM as kickass says
        self.syntax = lambda: "kick" if self.kickass else "cbm"
        self.insert_cb = insert_cb
        self.get_target = get_target        # () -> the SourceEditor to insert into, or None
        self.get_symbols = get_symbols      # () -> {address: label} of the last build

        box = Gtk.Box(spacing=20, margin_start=10, margin_end=10, margin_top=8, margin_bottom=8, vexpand=True)
        self.append(box)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(form)

        form.append(Gtk.Label(label="<b>Style</b>", use_markup=True, xalign=0))
        self.styles = []
        first = None
        for key, label in STYLE_LABELS:
            b = Gtk.CheckButton(label=label, group=first)
            first = first or b
            b.connect("toggled", lambda btn: btn.get_active() and self._update())
            self.styles.append((key, b))
            form.append(b)
        self.styles[0][1].set_active(True)
        mrow = Gtk.Box(spacing=6, margin_start=24)
        mrow.append(Gtk.Label(label="Message"))
        self.message = Gtk.Entry(text="{white}my game (c) 2026", hexpand=True, width_chars=28,
                                 tooltip_text="What LIST shows instead of the SYS line. Control codes such as "
                                              "{white} or {reverse on} work, as in the Screen Code Builder")
        self.message.connect("changed", lambda *_: self._update())
        mrow.append(self.message)
        form.append(mrow)

        form.append(Gtk.Label(label="<b>BASIC line number</b>", use_markup=True, xalign=0, margin_top=8))
        self.line = Gtk.SpinButton.new_with_range(0, 63999, 1)
        self.line.set_value(10)
        self.line.set_halign(Gtk.Align.START)
        self.line.connect("value-changed", lambda *_: self._update())
        form.append(self.line)

        form.append(Gtk.Label(label="<b>Program start</b>", use_markup=True, xalign=0, margin_top=8))
        self.after = Gtk.CheckButton(label="Right after the SYS line", active=True)
        self.after.connect("toggled", lambda *_: self._update())
        form.append(self.after)
        self.at = Gtk.CheckButton(label="At", group=self.after)
        arow = Gtk.Box(spacing=6)
        arow.append(self.at)
        self.address = Gtk.Entry(placeholder_text="$C000, 4096 or a label", width_chars=16,
                                 tooltip_text="$hex, decimal, or a label from the last build")
        self.address.connect("changed", lambda *_: (self.at.set_active(True), self._update()))
        arow.append(self.address)
        form.append(arow)
        self.comments = Gtk.CheckButton(label="Add comments", active=True, margin_top=8)
        self.comments.connect("toggled", lambda *_: self._update())
        form.append(self.comments)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        right.append(Gtk.Label(label="<b>Lists as</b>", use_markup=True, xalign=0))
        self.listing = Gtk.Label(xalign=0, selectable=True, css_classes=["monospace"])
        right.append(self.listing)
        self.size = Gtk.Label(xalign=0, css_classes=["dim-label"], wrap=True)
        right.append(self.size)
        right.append(Gtk.Label(label="<b>Source</b>", use_markup=True, xalign=0, margin_top=6))
        self.code = Gtk.TextView(editable=False, monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                 css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.code, vexpand=True, min_content_height=160))
        btns = Gtk.Box(spacing=6)
        cp = Gtk.Button(label="Copy")
        cp.connect("clicked", lambda *_: self._copy())
        btns.append(cp)
        top = Gtk.Button(label="Insert at Top", css_classes=["suggested-action"],
                         tooltip_text="Put it at the start of the last source file used")
        top.connect("clicked", lambda *_: self._insert(top=True))
        btns.append(top)
        here = Gtk.Button(label="Insert at Cursor")
        here.connect("clicked", lambda *_: self._insert(top=False))
        btns.append(here)
        right.append(btns)
        box.append(right)

        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"])
        self.append(self.status)
        self._text = ""
        self._update()

    @property
    def title(self) -> str:
        return "SYS() Call Generator"

    def save(self) -> None:
        pass

    # ================================================================== generating
    def _style(self) -> str:
        return next(k for k, b in self.styles if b.get_active())

    def _address(self) -> int | None:
        if self.after.get_active():
            return None
        text = self.address.get_text().strip()
        if not text:
            raise SysError("Type the program's start address, or choose Right after the SYS line")
        try:
            return parse_value(text)
        except ValueError:
            pass
        syms = self.get_symbols() if self.get_symbols else {}
        for addr, name in (syms or {}).items():
            if name.lower() == text.lower():
                return addr
        raise SysError(f"{text} isn't a number or a label in the last build")

    def call(self) -> SysCall:
        return SysCall(address=self._address(), line=self.line.get_value_as_int(), style=self._style(),
                       message=self.message.get_text())

    def _update(self):
        if not hasattr(self, "status"):
            return                          # still being built
        self.message.get_parent().set_sensitive(self._style() == "obfuscated")
        try:
            call = self.call()
            data, addr, listing = generate(call)
            self._text = source(call, self.kickass, self.comments.get_active(), syntax=self.syntax())
        except SysError as e:
            self._text = ""
            self.listing.set_text("")
            self.size.set_text("")
            self.code.get_buffer().set_text("")
            self.status.set_text(str(e))
            return
        self.listing.set_text(listing)
        gap = addr - (call.load + len(data))
        self.size.set_text(f"{len(data)} bytes at ${call.load:04X}-${call.load + len(data) - 1:04X}; SYS {addr} "
                           f"(${addr:04X})" + (f". The {gap} bytes between are padding in the .prg" if gap > 0 else ""))
        self.code.get_buffer().set_text(self._text)
        self.status.set_text("Put this at the top of the program's first source file")

    def _copy(self):
        if self._text:
            Gdk.Display.get_default().get_clipboard().set(self._text)
            self.status.set_text("Copied the SYS line")

    def _insert(self, top: bool):
        if not self._text or not self.insert_cb:
            return
        t = self.get_target() if self.get_target else None
        if t is not None:
            if t.is_basic:
                self.status.set_text(f"{t.title} is BASIC: this goes into an assembler source")
                return
            b = t.buffer
            text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
            if re.search(r"^\s*\*\s*=\s*(\$0*801|2049)\b", text, re.M | re.I):
                self.status.set_text(f"{t.title} already has code at $0801 (a SYS line?): remove it first, "
                                     f"or use Copy")
                return
            if top:
                b.place_cursor(b.get_start_iter())
        where = self.insert_cb(self._text)
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")
