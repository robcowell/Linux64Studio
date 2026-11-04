"""Widgets shared by the graphics editors."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk  # noqa: E402

from ..gfx.palette import COLOUR_NAMES, PALETTE_RGB  # noqa: E402


def set_rgb(cr, colour: int):
    cr.set_source_rgb(*PALETTE_RGB[colour & 0x0F])


class ColourButton(Gtk.MenuButton):
    """A button showing a C64 colour; clicking opens a 16-colour grid."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, colour: int = 0, tooltip: str = ""):
        super().__init__()
        self._colour = colour
        self.swatch = Gtk.DrawingArea(content_width=22, content_height=16)
        self.swatch.set_draw_func(self._draw_swatch)
        self.set_child(self.swatch)
        if tooltip:
            self.set_tooltip_text(tooltip)
        pop = Gtk.Popover()
        grid = Gtk.Grid(row_spacing=2, column_spacing=2, margin_top=6, margin_bottom=6,
                        margin_start=6, margin_end=6)
        for i in range(16):
            b = Gtk.Button(tooltip_text=f"{i}: {COLOUR_NAMES[i]}")
            da = Gtk.DrawingArea(content_width=24, content_height=24)
            da.set_draw_func(lambda _w, cr, w, h, c=i: (set_rgb(cr, c), cr.paint()))
            b.set_child(da)
            b.add_css_class("flat")
            b.connect("clicked", self._picked, i, pop)
            grid.attach(b, i % 8, i // 8, 1, 1)
        pop.set_child(grid)
        self.set_popover(pop)

    def _draw_swatch(self, _w, cr, w, h):
        set_rgb(cr, self._colour)
        cr.rectangle(0, 0, w, h)
        cr.fill()

    def _picked(self, _b, colour, pop):
        pop.popdown()
        self.colour = colour
        self.emit("changed", colour)

    @property
    def colour(self) -> int:
        return self._colour

    @colour.setter
    def colour(self, c: int):
        self._colour = c & 0x0F
        self.set_tooltip_text(COLOUR_NAMES[self._colour])
        self.swatch.queue_draw()


class PixelCanvas(Gtk.DrawingArea):
    """A zoomable grid editor. Subclasses supply size and colours; this handles drawing and mouse input.

    Left button paints with the selected value, right button paints with 0 (erase).
    `pixel_aspect` is 2 for multicolour modes, where each pixel is double width.
    """

    __gsignals__ = {
        "paint": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int)),  # x, y, button
        "stroke-begin": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "stroke-end": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "hover": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
    }

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True)
        self.cols, self.rows = 8, 8
        self.pixel_aspect = 1
        self.grid = True
        self.colour_at = lambda x, y: 0  # -> palette index
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", lambda *_: self.emit("stroke-end"))
        self.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        self.add_controller(motion)
        self._start = (0, 0)
        self._button = 1
        self._last = None
        self.extra_draw = None  # optional callback(cr, cell_w, cell_h, ox, oy)

    def geometry(self):
        w, h = self.get_width(), self.get_height()
        cw = max(1, min(w / (self.cols * self.pixel_aspect), h / self.rows))
        cell_w, cell_h = cw * self.pixel_aspect, cw
        ox = (w - cell_w * self.cols) / 2
        oy = (h - cell_h * self.rows) / 2
        return cell_w, cell_h, ox, oy

    def cell_at(self, x, y):
        cw, ch, ox, oy = self.geometry()
        cx, cy = int((x - ox) // cw), int((y - oy) // ch)
        if 0 <= cx < self.cols and 0 <= cy < self.rows:
            return cx, cy
        return None

    def _draw(self, _w, cr, w, h):
        cw, ch, ox, oy = self.geometry()
        for y in range(self.rows):
            for x in range(self.cols):
                set_rgb(cr, self.colour_at(x, y))
                cr.rectangle(ox + x * cw, oy + y * ch, cw + 0.5, ch + 0.5)
                cr.fill()
        if self.grid and ch >= 6:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
            cr.set_line_width(1)
            for x in range(self.cols + 1):
                cr.move_to(ox + x * cw + 0.5, oy)
                cr.line_to(ox + x * cw + 0.5, oy + self.rows * ch)
            for y in range(self.rows + 1):
                cr.move_to(ox, oy + y * ch + 0.5)
                cr.line_to(ox + self.cols * cw, oy + y * ch + 0.5)
            cr.stroke()
        if self.extra_draw:
            self.extra_draw(cr, cw, ch, ox, oy)

    def _drag_begin(self, gesture, x, y):
        self._start = (x, y)
        self._button = gesture.get_current_button()
        self._last = None
        self.emit("stroke-begin")
        self._paint_at(x, y)

    def _drag_update(self, _g, dx, dy):
        self._paint_at(self._start[0] + dx, self._start[1] + dy)

    def _paint_at(self, x, y):
        cell = self.cell_at(x, y)
        if cell and cell != self._last:
            self._last = cell
            self.emit("paint", cell[0], cell[1], self._button)

    def _motion(self, _c, x, y):
        cell = self.cell_at(x, y)
        if cell:
            self.emit("hover", *cell)
