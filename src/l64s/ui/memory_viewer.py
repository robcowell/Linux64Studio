"""Memory Viewer: where everything is in the C64's 64K, from the last build or the running
program in VICE, and any part of it shown as hex, screen text, characters, sprites or a bitmap."""
from __future__ import annotations

import colorsys
import zlib
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk  # noqa: E402

from .. import memmap  # noqa: E402
from ..emu.values import ValueError_, parse_address  # noqa: E402
from ..gfx.charset import rom_charset  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .hexview import HexView  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled, render_sprite  # noqa: E402
from .widgets import ColourButton, set_rgb  # noqa: E402

REGION_SHADES = [(0.16, 0.16, 0.18), (0.20, 0.20, 0.23)]
KIND_LABEL = {"code": "code", "data": "data", "binary": "included binary"}


def owner_colour(name: str, kind: str) -> tuple[float, float, float]:
    """A steady, distinct colour per source file; data a little lighter, binaries more muted."""
    h = (zlib.crc32(name.encode()) % 360) / 360
    s, v = {"code": (0.65, 0.85), "data": (0.45, 0.95), "binary": (0.35, 0.7)}.get(kind, (0.5, 0.8))
    return colorsys.hsv_to_rgb(h, s, v)


class MapView(Gtk.DrawingArea):
    """All 64K: one pixel per byte, 256 bytes (a page) per row."""

    __gsignals__ = {"picked": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self):
        super().__init__(content_width=256, content_height=256, hexpand=True, vexpand=True)
        self.map: memmap.MemoryMap | None = None
        self.live = False
        self.selected: int | None = None
        self.symbols: dict[int, str] = {}
        self._surface = None
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self._tooltip)

    def set_map(self, m: memmap.MemoryMap, live: bool):
        self.map, self.live = m, live
        self._surface = None
        self.queue_draw()

    def _geometry(self):
        size = max(1, min(self.get_width(), self.get_height()))
        scale = size / 256
        return scale, (self.get_width() - size) / 2, (self.get_height() - size) / 2

    def _render(self):
        import cairo
        data = bytearray(256 * 256 * 4)
        m = self.map
        colours: dict[int, tuple[int, int, int]] = {}
        for i, s in enumerate(m.segments if m else []):
            r, g, b = owner_colour(s.owner, s.kind)
            colours[i] = (int(b * 255), int(g * 255), int(r * 255))
        for page in range(256):
            region = next(i for i, (lo, hi, _n) in enumerate(memmap.SYSTEM_REGIONS) if lo <= page * 256 <= hi)
            br, bg, bb = REGION_SHADES[region % 2]
            base_pix = (int(bb * 255), int(bg * 255), int(br * 255))
            for col in range(256):
                a = page * 256 + col
                o = a * 4
                if m and self.live:
                    v = m.memory[a]
                    lum = 40 + v * 200 // 255 if v else 0
                    px = (lum // 2, lum, lum // 3) if v else base_pix
                elif m and m.used[a]:
                    px = colours.get(m.owners.get(a, -1), (220, 220, 220))
                else:
                    px = base_pix
                data[o], data[o + 1], data[o + 2], data[o + 3] = px[0], px[1], px[2], 255
        return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, 256, 256, 1024)

    def _draw(self, _w, cr, width, height):
        if self._surface is None:
            self._surface = self._render()
        scale, ox, oy = self._geometry()
        paint_scaled(cr, self._surface, ox, oy, scale, scale)
        # region boundaries
        cr.set_source_rgba(1, 1, 1, 0.25)
        cr.set_line_width(1)
        for lo, _hi, _n in memmap.SYSTEM_REGIONS[1:]:
            y = oy + (lo >> 8) * scale + 0.5
            cr.move_to(ox, y)
            cr.line_to(ox + 256 * scale, y)
        cr.stroke()
        if self.selected is not None:
            x, y = ox + (self.selected & 0xFF) * scale, oy + (self.selected >> 8) * scale
            cr.set_source_rgb(1, 0.85, 0)
            cr.set_line_width(2)
            cr.rectangle(x - 3, y - 3, max(scale, 1) + 6, max(scale, 1) + 6)
            cr.stroke()

    def address_at(self, x, y) -> int | None:
        scale, ox, oy = self._geometry()
        col, row = int((x - ox) // scale), int((y - oy) // scale)
        return row * 256 + col if 0 <= col < 256 and 0 <= row < 256 else None

    def _click(self, _g, _n, x, y):
        a = self.address_at(x, y)
        if a is not None:
            self.selected = a
            self.queue_draw()
            self.emit("picked", a)

    def _tooltip(self, _w, x, y, _kb, tooltip):
        a = self.address_at(x, y)
        if a is None or not self.map:
            return False
        lines = [f"<b>${a:04X}</b>  {GLib.markup_escape_text(memmap.system_region(a))}",
                 f"value ${self.map.memory[a]:02X}"]
        seg = self.map.owner_of(a)
        if seg:
            lines.append(f"{GLib.markup_escape_text(seg.owner)}: {KIND_LABEL[seg.kind]} ${seg.start:04X}-${seg.end:04X}")
        label = self.symbols.get(a)
        if label:
            lines.append(f"label {GLib.markup_escape_text(label)}")
        tooltip.set_markup("\n".join(lines))
        return True


class GraphicsView(Gtk.DrawingArea):
    """Memory drawn as the VIC-II would: screen text, a character set, sprites or a hires bitmap."""

    def __init__(self, mode: str):
        super().__init__(hexpand=True, vexpand=True)
        self.mode = mode
        self.memory = bytes(0x10000)
        self.address = 0x0400
        self.charset_addr: int | None = None   # None = ROM
        self.lowercase = False
        self.multicolour = False
        self.fg, self.bg, self.mc1, self.mc2 = 1, 6, 0, 15
        self.set_draw_func(self._draw)

    def _chars(self) -> list[list[int]]:
        if self.charset_addr is None:
            return rom_charset(not self.lowercase) or [[0] * 8 for _ in range(256)]
        a = self.charset_addr
        return [list(self.memory[(a + i * 8) & 0xFFFF:((a + i * 8) & 0xFFFF) + 8].ljust(8, b"\0")) for i in range(256)]

    def _bitmap(self) -> Bitmap:
        mem, a = self.memory, self.address
        fg = self.fg | (8 if self.multicolour else 0)
        if self.mode == "screen":
            chars = self._chars()
            bm = Bitmap(320, 200)
            for i in range(1000):
                draw_char_into(bm, (i % 40) * 8, (i // 40) * 8, chars[mem[(a + i) & 0xFFFF]], fg, self.bg,
                               self.multicolour, self.mc1, self.mc2)
            return bm
        if self.mode == "chars":
            bm = Bitmap(256, 64)
            for i in range(256):
                rows = list(mem[(a + i * 8) & 0xFFFF:((a + i * 8) & 0xFFFF) + 8].ljust(8, b"\0"))
                draw_char_into(bm, (i % 32) * 8, (i // 32) * 8, rows, fg, self.bg, self.multicolour, self.mc1, self.mc2)
            return bm
        if self.mode == "sprites":
            bm = Bitmap(24 * 8, 21 * 4)
            for n in range(32):
                base = (a + n * 64) & 0xFFFF
                raw = mem[base:base + 63].ljust(63, b"\0")
                rows = [(raw[r * 3] << 16) | (raw[r * 3 + 1] << 8) | raw[r * 3 + 2] for r in range(21)]
                sp = render_sprite(rows, self.multicolour, self.fg, self.bg, self.mc1, self.mc2)
                ox, oy = (n % 8) * 24, (n // 8) * 21
                for y in range(21):
                    bm.pixels[(oy + y) * bm.width + ox:(oy + y) * bm.width + ox + 24] = sp.pixels[y * 24:(y + 1) * 24]
            return bm
        # hires bitmap: 8000 bytes, 40x25 cells of 8x8
        bm = Bitmap(320, 200)
        for cell in range(1000):
            rows = list(mem[(a + cell * 8) & 0xFFFF:((a + cell * 8) & 0xFFFF) + 8].ljust(8, b"\0"))
            draw_char_into(bm, (cell % 40) * 8, (cell // 40) * 8, rows, fg, self.bg, self.multicolour, self.mc1, self.mc2)
        return bm

    def _draw(self, _w, cr, width, height):
        bm = self._bitmap()
        scale = min(width / bm.width, height / bm.height)
        if scale >= 2:
            scale = int(scale)  # whole pixels when there's room
        set_rgb(cr, 0)
        cr.paint()
        paint_scaled(cr, bm.surface(), (width - bm.width * scale) / 2, (height - bm.height * scale) / 2, scale, scale)
        if self.mode in ("chars", "sprites"):  # grid between characters / sprites
            cw, ch = (8, 8) if self.mode == "chars" else (24, 21)
            ox, oy = (width - bm.width * scale) / 2, (height - bm.height * scale) / 2
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
            cr.set_line_width(1)
            for x in range(0, bm.width + 1, cw):
                cr.move_to(ox + x * scale + 0.5, oy)
                cr.line_to(ox + x * scale + 0.5, oy + bm.height * scale)
            for y in range(0, bm.height + 1, ch):
                cr.move_to(ox, oy + y * scale + 0.5)
                cr.line_to(ox + bm.width * scale, oy + y * scale + 0.5)
            cr.stroke()


VIEW_SIZES = {"screen": 1000, "chars": 2048, "sprites": 2048, "bitmap": 8000}


class MemoryViewer(EditorPage):
    kind = "memory"

    def __init__(self, get_build, get_session, open_source):
        super().__init__(None)
        self.get_build = get_build          # () -> (MemoryMap | None, symbols {addr: name}, description)
        self.get_session = get_session      # () -> DebugSession | None
        self.open_source = open_source      # (file, line) -> None
        self.map: memmap.MemoryMap | None = None
        self.symbols: dict[int, str] = {}
        self.address = 0x0400
        self._timer = None

        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)
        self.append(bar)
        self.source = Gtk.DropDown.new_from_strings(["Last build", "Running program (VICE)"])
        self.source.connect("notify::selected", lambda *_: self.refresh())
        bar.append(self.source)
        rb = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        rb.connect("clicked", lambda *_: self.refresh())
        bar.append(rb)
        self.auto = Gtk.CheckButton(label="Every second", tooltip_text="Keep refreshing the snapshot of the running program")
        self.auto.connect("toggled", self._auto_toggled)
        bar.append(self.auto)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        bar.append(Gtk.Label(label="Address"))
        self.addr_entry = Gtk.Entry(text="0400", width_chars=14, placeholder_text="address or label")
        self.addr_entry.connect("activate", self._goto)
        bar.append(self.addr_entry)
        self.info = Gtk.Label(xalign=0, hexpand=True, ellipsize=3, css_classes=["dim-label"])
        bar.append(self.info)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=420,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=8, margin_bottom=8)
        self.mapview = MapView()
        self.mapview.connect("picked", lambda _m, a: self.select(a))
        left.append(self.mapview)
        self.legend = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=8)
        left.append(self.legend)
        left.append(Gtk.Label(label="Each pixel is a byte, each row a page of 256. Bands are the C64's regions: "
                                    "zero page/stack, screen, BASIC area, BASIC ROM, $C000, I/O, KERNAL.",
                              wrap=True, xalign=0, css_classes=["dim-label", "caption"], max_width_chars=60))
        paned.set_start_child(Gtk.ScrolledWindow(child=left, hscrollbar_policy=Gtk.PolicyType.NEVER))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_end=8, margin_bottom=8)
        self.stack = Adw.ViewStack(vexpand=True)
        right.append(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        right.append(self.stack)
        paned.set_end_child(Gtk.ScrolledWindow(child=right, hscrollbar_policy=Gtk.PolicyType.NEVER))

        # Overview: segments, free space, warnings
        ov = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.segments = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.segments.connect("row-activated", self._segment_activated)
        self.segments.connect("row-selected", lambda _l, row: row and getattr(row, "seg", None)
                              and self.select(row.seg.start, from_list=True))
        ov.append(Gtk.Label(label="<b>Segments</b>  (double-click to open the source)", use_markup=True, xalign=0))
        ov.append(Gtk.ScrolledWindow(child=self.segments, vexpand=True, min_content_height=160))
        self.free = Gtk.Label(xalign=0, wrap=True, selectable=True, css_classes=["monospace"])
        ov.append(Gtk.Label(label="<b>Free</b>", use_markup=True, xalign=0))
        ov.append(self.free)
        self.warn = Gtk.Label(xalign=0, wrap=True, selectable=True)
        ov.append(Gtk.Label(label="<b>Warnings</b>", use_markup=True, xalign=0))
        ov.append(self.warn)
        self.stack.add_titled_with_icon(ov, "overview", "Overview", "view-list-symbolic")

        self.hex = HexView()
        self.hex.connect("navigate", lambda _h, base: self._show_hex(base))
        self.hex.connect("cursor-moved", lambda _h, a: self._describe(a))
        self.stack.add_titled_with_icon(Gtk.ScrolledWindow(child=self.hex), "hex", "Hex", "format-text-plaintext-symbolic")

        self.views: dict[str, GraphicsView] = {}
        for mode, title, icon in (("screen", "Screen", "video-display-symbolic"),
                                  ("chars", "Characters", "font-x-generic-symbolic"),
                                  ("sprites", "Sprites", "image-x-generic-symbolic"),
                                  ("bitmap", "Bitmap", "image-x-generic-symbolic")):
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            opts = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=4,
                               max_children_per_line=12)
            v = GraphicsView(mode)
            self.views[mode] = v
            mc = Gtk.CheckButton(label="Multicolour")
            mc.connect("toggled", lambda b, view=v: (setattr(view, "multicolour", b.get_active()), view.queue_draw()))
            opts.append(mc)
            for attr, tip in (("fg", "Colour"), ("bg", "Background"), ("mc1", "Multicolour 1"), ("mc2", "Multicolour 2")):
                cb = ColourButton(getattr(v, attr), tip)
                cb.connect("changed", lambda _b, c, view=v, at=attr: (setattr(view, at, c), view.queue_draw()))
                opts.append(cb)
            if mode == "screen":
                opts.append(Gtk.Label(label="Characters from"))
                cs = Gtk.Entry(placeholder_text="ROM, or an address", width_chars=12,
                               tooltip_text="Leave empty for the ROM character set, or give the address of yours "
                                            "(e.g. 3800); Enter to apply")
                cs.connect("activate", lambda e, view=v: self._set_charset(view, e.get_text()))
                opts.append(cs)
                lc = Gtk.CheckButton(label="Lower case ROM")
                lc.connect("toggled", lambda b, view=v: (setattr(view, "lowercase", b.get_active()), view.queue_draw()))
                opts.append(lc)
            page.append(opts)
            page.append(v)
            self.stack.add_titled_with_icon(page, mode, title, icon)
        self.stack.connect("notify::visible-child-name", lambda *_: self._update_views())
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"], margin_start=8)
        self.append(self.status)
        self.connect("unrealize", lambda *_: self._stop_timer())
        self.refresh()

    @property
    def title(self) -> str:
        return "Memory Viewer"

    # ---------------------------------------------------------------- data
    def refresh(self):
        live = self.source.get_selected() == 1
        if live:
            s = self.get_session()
            if not s or not s.monitor.connected:
                self.status.set_text("Start debugging (Shift+F5) to look at the running program.")
                return
            try:
                data = s.snapshot_memory()
            except Exception as e:  # the session may have ended in between
                self.status.set_text(f"Couldn't read VICE's memory: {e}")
                return
            build, syms, _ = self.get_build()
            self.map = memmap.from_memory(data)
            if build:  # keep who-owns-what from the build, with the live bytes
                self.map = memmap.MemoryMap(data, build.used, build.segments, build.owners)
            self.symbols = syms
            self.status.set_text("Snapshot of the running program" + (" (it kept running)" if s.running else ""))
        else:
            build, syms, desc = self.get_build()
            if not build:
                self.status.set_text("Build the project (F7) to see where everything goes.")
                return
            self.map, self.symbols = build, syms
            self.status.set_text(desc)
        self.mapview.symbols = self.symbols
        self.mapview.set_map(self.map, live and not self.map.segments)
        self._fill_overview()
        self.select(self.address)

    def _fill_overview(self):
        m = self.map
        while (row := self.segments.get_row_at_index(0)) is not None:
            self.segments.remove(row)
        while (child := self.legend.get_first_child()) is not None:
            self.legend.remove(child)
        totals: dict[str, int] = {}
        for s in m.segments:
            totals[s.owner] = totals.get(s.owner, 0) + s.size
            box = Gtk.Box(spacing=8, margin_start=6, margin_end=6, margin_top=2, margin_bottom=2)
            chip = Gtk.DrawingArea(content_width=12, content_height=12, valign=Gtk.Align.CENTER)
            chip.set_draw_func(lambda _w, cr, w, h, c=owner_colour(s.owner, s.kind): (cr.set_source_rgb(*c), cr.paint()))
            box.append(chip)
            box.append(Gtk.Label(label=f"${s.start:04X}-${s.end:04X}", css_classes=["monospace"]))
            box.append(Gtk.Label(label=f"{s.size:>6}", css_classes=["monospace", "dim-label"]))
            box.append(Gtk.Label(label=f"{s.owner}  {KIND_LABEL[s.kind]}", xalign=0, hexpand=True))
            row = Gtk.ListBoxRow(child=box)
            row.seg = s
            self.segments.append(row)
        for owner, n in sorted(totals.items(), key=lambda kv: -kv[1]):
            box = Gtk.Box(spacing=4)
            chip = Gtk.DrawingArea(content_width=10, content_height=10, valign=Gtk.Align.CENTER)
            chip.set_draw_func(lambda _w, cr, w, h, c=owner_colour(owner, "code"): (cr.set_source_rgb(*c), cr.paint()))
            box.append(chip)
            box.append(Gtk.Label(label=f"{owner} ({n})", css_classes=["caption"]))
            self.legend.append(box)
        free = m.free_ranges()
        self.free.set_text("\n".join(f"${a:04X}-${b:04X}  {b - a + 1:>6} bytes  {memmap.system_region(a)}"
                                     for a, b in free[:12]) or "(none)")
        ws = memmap.warnings(m)
        self.warn.set_text("\n".join("• " + w.message for w in ws) or "None")
        used = m.total
        self.info.set_text(f"{used} bytes in {len(m.segments)} segments" if m.segments else "")

    # ---------------------------------------------------------------- selection
    def _goto(self, *_):
        names = {name: addr for addr, name in self.symbols.items()}
        try:
            self.select(parse_address(self.addr_entry.get_text(), names))
        except ValueError_ as e:
            self.status.set_text(str(e))

    def select(self, addr: int, from_list: bool = False):
        self.address = addr & 0xFFFF
        self.mapview.selected = self.address
        self.mapview.queue_draw()
        if self.addr_entry.get_text().strip() not in {n for n in self.symbols.values()}:
            self.addr_entry.set_text(f"{self.address:04X}")
        self._show_hex(self.address & 0xFFF0)
        self.hex.cursor = self.address
        self._describe(self.address)
        self._update_views()

    def _show_hex(self, base: int):
        if not self.map:
            return
        base = max(0, min(base, 0x10000 - 256))
        self.hex.set_data(base, self.map.memory[base:base + 256], snapshot=True)

    def _describe(self, addr: int):
        if not self.map:
            return
        seg = self.map.owner_of(addr)
        text = f"${addr:04X} = ${self.map.memory[addr]:02X} · {memmap.system_region(addr)}"
        if seg:
            text += f" · {seg.owner} ({KIND_LABEL[seg.kind]})"
        if addr in self.symbols:
            text += f" · {self.symbols[addr]}"
        self.info.set_text(text)

    def _update_views(self):
        if not self.map:
            return
        name = self.stack.get_visible_child_name()
        v = self.views.get(name)
        if v:
            v.memory, v.address = self.map.memory, self.address
            n = VIEW_SIZES[name]
            self.status.set_text(f"${self.address:04X}-${min(0xFFFF, self.address + n - 1):04X} shown as "
                                 f"{self.stack.get_page(self.stack.get_visible_child()).get_title().lower()}")
            v.queue_draw()

    def _set_charset(self, view: GraphicsView, text: str):
        if not text.strip() or text.strip().lower() == "rom":
            view.charset_addr = None
        else:
            try:
                view.charset_addr = parse_address(text, {n: a for a, n in self.symbols.items()})
            except ValueError_ as e:
                self.status.set_text(str(e))
                return
        view.queue_draw()

    def _segment_activated(self, _lb, row):
        seg = getattr(row, "seg", None)
        if seg and seg.lines and seg.lines[0][0]:
            self.open_source(*seg.lines[0])

    # ---------------------------------------------------------------- live refresh
    def _auto_toggled(self, btn):
        self._stop_timer()
        if btn.get_active():
            self.source.set_selected(1)
            self._timer = GLib.timeout_add(1000, lambda: (self.refresh(), True)[1])

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def save(self):
        self.set_modified(False)
