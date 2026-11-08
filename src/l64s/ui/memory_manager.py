"""Memory Manager: plan what the VIC-II sees (bank, screen, character set or bitmap, sprite data),
get the register values and setup code, and check them against the program and the ROM."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..emu.values import ValueError_, parse_address, parse_number  # noqa: E402
from ..vicmem import Layout, check, setup_code  # noqa: E402
from . import textzoom  # noqa: E402
from .editor import EditorPage  # noqa: E402

AREA_COLOURS = {"Screen": (0.38, 0.63, 0.92), "Sprite pointers": (0.95, 0.85, 0.3), "Character set": (0.36, 0.78, 0.45),
                "Bitmap": (0.85, 0.55, 0.2), "Sprite": (0.85, 0.4, 0.8)}


class BankView(Gtk.DrawingArea):
    """The 16K the VIC-II sees: 128 bytes per pixel row, 128 rows."""

    def __init__(self):
        super().__init__(content_width=256, content_height=256, hexpand=True, vexpand=True)
        self.layout = Layout()
        self.used: bytes | None = None
        self.set_draw_func(self._draw)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)

    def _geometry(self):
        size = max(1, min(self.get_width() - int(textzoom.px(70)), self.get_height()))
        return size / 128, int(textzoom.px(64)), (self.get_height() - size) / 2

    def _draw(self, _w, cr, width, height):
        scale, ox, oy = self._geometry()
        lay = self.layout
        base = lay.bank_base
        cr.set_source_rgb(0.17, 0.17, 0.19)
        cr.rectangle(ox, oy, 128 * scale, 128 * scale)
        cr.fill()
        # the program's bytes, faint
        if self.used is not None:
            cr.set_source_rgba(1, 1, 1, 0.16)
            for row in range(128):
                seg = self.used[base + row * 128: base + row * 128 + 128]
                col = 0
                while col < 128:
                    if seg[col]:
                        start = col
                        while col < 128 and seg[col]:
                            col += 1
                        cr.rectangle(ox + start * scale, oy + row * scale, (col - start) * scale, scale)
                    col += 1
            cr.fill()
        # character ROM shadow, hatched
        shadow = lay.char_rom_shadow()
        if shadow:
            y0, y1 = oy + (shadow[0] - base) / 128 * scale, oy + (shadow[1] + 1 - base) / 128 * scale
            cr.save()
            cr.rectangle(ox, y0, 128 * scale, y1 - y0)
            cr.clip()
            cr.set_source_rgba(0.9, 0.3, 0.3, 0.35)
            cr.set_line_width(1)
            for k in range(-int(128 * scale), int(128 * scale), 8):
                cr.move_to(ox + k, y1)
                cr.line_to(ox + k + (y1 - y0), y0)
            cr.stroke()
            cr.restore()
        for name, lo, hi in lay.areas():
            colour = AREA_COLOURS.get(name, AREA_COLOURS["Sprite"] if name.startswith("Sprite ") else (0.7, 0.7, 0.7))
            cr.set_source_rgba(*colour, 0.85)
            for a in range(lo - base, hi - base + 1, 128):
                row, col = a // 128, a % 128
                end = min(hi - base, (row + 1) * 128 - 1)
                cr.rectangle(ox + col * scale, oy + row * scale, (end - (row * 128) - col + 1) * scale, scale)
            cr.fill()
        # address scale every 2K
        cr.set_source_rgba(0.6, 0.6, 0.6, 1)
        cr.set_font_size(max(textzoom.px(9), scale * 4))
        for k in range(0, 0x4001, 0x800):
            y = oy + k / 128 * scale
            cr.move_to(4, y + 4)
            cr.show_text(f"${base + k:04X}" if k < 0x4000 else "")
            cr.move_to(ox - 4, y)
            cr.line_to(ox, y)
            cr.stroke()

    def _tooltip(self, _w, x, y, _kb, tooltip):
        scale, ox, oy = self._geometry()
        col, row = int((x - ox) // scale), int((y - oy) // scale)
        if not (0 <= col < 128 and 0 <= row < 128):
            return False
        a = self.layout.bank_base + row * 128 + col
        names = [n for n, lo, hi in self.layout.areas() if lo <= a <= hi]
        shadow = self.layout.char_rom_shadow()
        if shadow and shadow[0] <= a <= shadow[1]:
            names.append("character ROM (as the VIC-II sees it)")
        if self.used is not None and self.used[a]:
            names.append("used by the program")
        tooltip.set_markup(f"<b>${a:04X}</b>  " + GLib.markup_escape_text(", ".join(names) or "free"))
        return True


class MemoryManager(EditorPage):
    kind = "memmgr"

    def __init__(self, kickass: bool, get_build, get_session, insert_cb):
        super().__init__(None)
        self.kickass = kickass
        # the syntax to write (syntax.py): the window gives a function that follows where the
        # text is going (C or ca65 in a C project); on its own, Kick or CBM as kickass says
        self.syntax = lambda: "kick" if self.kickass else "cbm"
        self.get_build = get_build        # () -> (MemoryMap or None, {addr: label}, desc)
        self.get_session = get_session
        self.insert_cb = insert_cb
        self.layout = Layout(bank=0, screen=1, charset=2)
        self._updating = False

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=430,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)
        page = Adw.PreferencesPage()
        paned.set_start_child(page)

        g = Adw.PreferencesGroup(title="VIC-II bank", description="The 16K of memory the VIC-II reads from ($DD00).")
        page.add(g)
        banks = Gtk.Box(spacing=4, css_classes=["linked"], halign=Gtk.Align.START, margin_top=4, margin_bottom=4)
        self.bank_btns = []
        group = None
        for b in range(4):
            btn = Gtk.ToggleButton(label=f"{b}: ${b * 0x4000:04X}", group=group)
            group = group or btn
            btn.connect("toggled", self._bank_toggled, b)
            banks.append(btn)
            self.bank_btns.append(btn)
        g.add(banks)

        g2 = Adw.PreferencesGroup(title="Screen and characters ($D018)")
        page.add(g2)
        self.screen_row = Adw.ComboRow(title="Screen memory (1K)")
        self.screen_row.connect("notify::selected", lambda *_: self._from_controls())
        self.mode_row = Adw.SwitchRow(title="Bitmap mode", subtitle="A hires/multicolour bitmap instead of characters")
        self.mode_row.connect("notify::active", lambda *_: self._from_controls())
        self.charset_row = Adw.ComboRow(title="Character set (2K)")
        self.charset_row.connect("notify::selected", lambda *_: self._from_controls())
        self.bitmap_row = Adw.ComboRow(title="Bitmap (8K)")
        self.bitmap_row.connect("notify::selected", lambda *_: self._from_controls())
        for w in (self.screen_row, self.mode_row, self.charset_row, self.bitmap_row):
            g2.add(w)

        g3 = Adw.PreferencesGroup(title="Sprite data",
                                  description="Each sprite's data is a 64-byte block in the bank. Add one by its "
                                              "address (3000, or a label) or pointer value (#192).")
        page.add(g3)
        self.sprite_entry = Adw.EntryRow(title="Add sprite data at")
        self.sprite_entry.connect("entry-activated", self._add_sprite)
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
        add.connect("clicked", self._add_sprite)
        self.sprite_entry.add_suffix(add)
        g3.add(self.sprite_entry)
        self.sprite_rows: list = []
        self.sprite_group = g3

        g4 = Adw.PreferencesGroup(title="Compare")
        page.add(g4)
        self.overlay = Adw.SwitchRow(title="Show the last build", subtitle="Your program's bytes, and overlaps with them",
                                     active=True)
        self.overlay.connect("notify::active", lambda *_: self._update())
        g4.add(self.overlay)
        read = Adw.ActionRow(title="Read from VICE", subtitle="The layout the running program has set (debug session)")
        rb = Gtk.Button(label="Read", valign=Gtk.Align.CENTER)
        rb.connect("clicked", self._read_vice)
        read.add_suffix(rb)
        g4.add(read)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=8, margin_top=6,
                        margin_bottom=6)
        paned.set_end_child(Gtk.ScrolledWindow(child=right, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.bank_view = BankView()
        self.bank_view.set_size_request(-1, 280)
        right.append(self.bank_view)
        self.legend = Gtk.Label(xalign=0, wrap=True, use_markup=True, css_classes=["caption"])
        right.append(self.legend)
        self.registers = Gtk.Label(xalign=0, wrap=True, selectable=True, use_markup=True, css_classes=["monospace"])
        right.append(self.registers)
        self.issues = Gtk.Label(xalign=0, wrap=True, selectable=True)
        right.append(self.issues)
        cbar = Gtk.Box(spacing=6)
        cbar.append(Gtk.Label(label="<b>Setup code</b>", use_markup=True, hexpand=True, xalign=0))
        for label, cb in (("Copy", self._copy), ("Insert into Editor", self._insert)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            cbar.append(b)
        right.append(cbar)
        self.code = Gtk.TextView(editable=False, monospace=True, top_margin=6, left_margin=6,
                                 css_classes=["card", "monospace"])
        right.append(self.code)
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"], margin_start=8, margin_bottom=6)
        self.append(self.status)
        self._sync_controls()

    @property
    def title(self) -> str:
        return "Memory Manager"

    # ---------------------------------------------------------------- controls
    def _sync_controls(self):
        """Put the layout into the controls (address lists depend on the bank)."""
        self._updating = True
        lay = self.layout
        base = lay.bank_base
        self.bank_btns[lay.bank].set_active(True)
        self.screen_row.set_model(Gtk.StringList.new([f"${base + i * 0x400:04X}" for i in range(16)]))
        self.screen_row.set_selected(lay.screen)
        shadow = lay.char_rom_shadow()
        names = []
        for i in range(8):
            a = base + i * 0x800
            rom = " (ROM upper case)" if shadow and a == shadow[0] else " (ROM lower case)" if shadow and a == shadow[0] + 0x800 else ""
            names.append(f"${a:04X}{rom}")
        self.charset_row.set_model(Gtk.StringList.new(names))
        self.charset_row.set_selected(lay.charset)
        self.bitmap_row.set_model(Gtk.StringList.new([f"${base:04X}", f"${base + 0x2000:04X}"]))
        self.bitmap_row.set_selected(lay.bitmap)
        self.mode_row.set_active(lay.bitmap_mode)
        self.charset_row.set_visible(not lay.bitmap_mode)
        self.bitmap_row.set_visible(lay.bitmap_mode)
        for r in self.sprite_rows:
            self.sprite_group.remove(r)
        self.sprite_rows = []
        for p in sorted(set(lay.sprites)):
            row = Adw.ActionRow(title=f"${lay.sprite_addr(p):04X}", subtitle=f"pointer {p}")
            rm = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
            rm.connect("clicked", lambda _b, ptr=p: self._remove_sprite(ptr))
            row.add_suffix(rm)
            self.sprite_group.add(row)
            self.sprite_rows.append(row)
        self._updating = False
        self._update()

    def _bank_toggled(self, btn, bank):
        if self._updating or not btn.get_active():
            return
        # keep sprites at the same offsets within the new bank
        self.layout.bank = bank
        self._sync_controls()

    def _from_controls(self):
        if self._updating:
            return
        lay = self.layout
        lay.screen = self.screen_row.get_selected()
        lay.charset = self.charset_row.get_selected()
        lay.bitmap = self.bitmap_row.get_selected()
        if lay.bitmap_mode != self.mode_row.get_active():
            lay.bitmap_mode = self.mode_row.get_active()
            self._sync_controls()
            return
        self._update()

    def _symbols(self) -> dict[str, int]:
        _m, syms, _d = self.get_build()
        return {n: a for a, n in syms.items()}

    def _add_sprite(self, *_):
        text = self.sprite_entry.get_text().strip()
        try:
            if text.startswith("#"):
                p = parse_number(text)
                if not 0 <= p <= 255:
                    raise ValueError("Sprite pointers are 0-255")
            else:
                p = self.layout.pointer_for(parse_address(text, self._symbols()))
        except (ValueError, ValueError_) as e:
            self.status.set_text(str(e))
            return
        self.layout.sprites.append(p)
        self.sprite_entry.set_text("")
        self._sync_controls()

    def _remove_sprite(self, p: int):
        self.layout.sprites = [x for x in self.layout.sprites if x != p]
        self._sync_controls()

    # ---------------------------------------------------------------- results
    def _update(self):
        lay = self.layout
        m, _syms, desc = self.get_build() if self.overlay.get_active() else (None, {}, "")
        self.bank_view.layout = lay
        self.bank_view.used = m.used if m else None
        self.bank_view.queue_draw()

        def chip(name):
            r, g, b = AREA_COLOURS[name]
            return f"<span foreground='#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'>■</span> {name}"
        parts = [chip("Screen"), chip("Sprite pointers"), chip("Bitmap" if lay.bitmap_mode else "Character set"),
                 chip("Sprite"), "<span foreground='#e05050'>▨</span> character ROM", "░ program" if m else ""]
        self.legend.set_markup("   ".join(p for p in parts if p))
        what = (f"bitmap ${lay.bitmap_addr:04X}" if lay.bitmap_mode else f"characters ${lay.charset_addr:04X}")
        self.registers.set_markup(
            f"<b>$DD00</b> bits 0-1 = %{lay.dd00_bits:02b}   bank {lay.bank} (${lay.bank_base:04X})\n"
            f"<b>$D018</b> = ${lay.d018:02X} (%{lay.d018:08b})   screen ${lay.screen_addr:04X}, {what}\n"
            f"<b>Sprite pointers</b> at ${lay.sprite_pointers_addr:04X}-${lay.sprite_pointers_addr + 7:04X}"
            + (f"\n<b>Book</b>: LIBSCREEN_SETCHARMEMORY {lay.book_charmemory_value}" if not lay.bitmap_mode else ""))
        issues = check(lay, m)
        self.issues.set_text("\n".join(("⚠ " if i.severity == "warning" else "• ") + i.message for i in issues)
                             or "No problems found")
        self.code.get_buffer().set_text(setup_code(lay, self.kickass, syntax=self.syntax()))
        if m:
            self.status.set_text(f"Compared with {desc}")

    def _read_vice(self, *_):
        s = self.get_session()
        if not s or not s.monitor.connected:
            self.status.set_text("Start debugging (Shift+F5) to read the running program's layout")
            return
        try:
            mem = s.snapshot_memory()
        except Exception as e:  # the session may have ended in between
            self.status.set_text(f"Couldn't read VICE's memory: {e}")
            return
        # $DD00 and the VIC registers are I/O, which the snapshot reads as the CPU sees them
        first = Layout.from_registers(mem[0xDD00], mem[0xD018], mem[0xD011], [], mem[0xD015])
        ptrs = list(mem[first.sprite_pointers_addr:first.sprite_pointers_addr + 8])
        self.layout = Layout.from_registers(mem[0xDD00], mem[0xD018], mem[0xD011], ptrs, mem[0xD015])
        self._sync_controls()
        self.status.set_text("Read from the running program: " + (
            f"{len(self.layout.sprites)} sprite(s) switched on" if self.layout.sprites else "no sprites switched on"))

    def _copy(self, *_):
        buf = self.code.get_buffer()
        Gdk.Display.get_default().get_clipboard().set(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))
        self.status.set_text("Setup code copied to the clipboard")

    def _insert(self, *_):
        buf = self.code.get_buffer()
        where = self.insert_cb(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)) if self.insert_cb else None
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    def save(self):
        self.set_modified(False)
