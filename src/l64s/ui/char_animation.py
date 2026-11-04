"""The character animation preview window (CBM prg Studio's Character Editor → Animation).

Give the first and last characters (type them, drop characters from the editor's set on them, or
use the character selected in the editor) and press Play. Frames can be one character or a block
of several that follow each other in the set; the animation loops or ping-pongs, at a speed in
C64 frames, and shows edits to the characters as they're made.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402

from ..gfx.charanim import LOOP, PING_PONG, describe_speed, frame_chars, frame_starts, order  # noqa: E402
from .render import Bitmap, draw_char_into, paint_scaled  # noqa: E402


class CharAnimationWindow(Adw.Window):
    def __init__(self, parent, editor):
        super().__init__(transient_for=parent, title="Character Animation", default_width=420, default_height=560)
        self.editor = editor
        self.step = 0
        self._timer = None
        self.connect("close-request", lambda *_: (self.stop(), False)[1])

        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        self.set_content(tv)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12,
                      margin_top=8, margin_bottom=12)
        tv.set_content(box)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        box.append(grid)
        self.first = self._char_spin(editor.index)
        self.last = self._char_spin(min(255, editor.index + 3))
        for r, (label, spin) in enumerate((("First character", self.first), ("Last character", self.last))):
            use = Gtk.Button(label="Selected", tooltip_text="Use the character selected in the editor")
            use.connect("clicked", lambda _b, s=spin: s.set_value(self.editor.index))
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            grid.attach(spin, 1, r, 1, 1)
            grid.attach(use, 2, r, 1, 1)
        self.across = Gtk.SpinButton.new_with_range(1, 8, 1)
        self.down = Gtk.SpinButton.new_with_range(1, 8, 1)
        for s in (self.across, self.down):
            s.connect("value-changed", lambda *_: self._reset())
        size = Gtk.Box(spacing=4)
        for w in (self.across, Gtk.Label(label="×"), self.down, Gtk.Label(label="characters")):
            size.append(w)
        size.set_tooltip_text("Characters in a frame: they follow one another in the set, row by row "
                              "(2×2 steps 4 characters a frame)")
        grid.attach(Gtk.Label(label="Frame size", xalign=0), 0, 2, 1, 1)
        grid.attach(size, 1, 2, 2, 1)
        self.mode = Gtk.DropDown.new_from_strings(["Loop (first to last, again)", "Ping-pong (there and back)"])
        self.mode.connect("notify::selected", lambda *_: self._reset())
        grid.attach(Gtk.Label(label="Play as", xalign=0), 0, 3, 1, 1)
        grid.attach(self.mode, 1, 3, 2, 1)
        self.delay = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 50, 1)
        self.delay.set_value(8)
        self.delay.set_hexpand(True)
        self.delay.connect("value-changed", lambda *_: self._speed_changed())
        grid.attach(Gtk.Label(label="Speed", xalign=0), 0, 4, 1, 1)
        grid.attach(self.delay, 1, 4, 2, 1)
        self.speed = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"])
        grid.attach(self.speed, 1, 5, 2, 1)
        self.zoom = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 16, 1)
        self.zoom.set_value(6)
        self.zoom.connect("value-changed", lambda *_: self.view.queue_draw())
        grid.attach(Gtk.Label(label="Size", xalign=0), 0, 6, 1, 1)
        grid.attach(self.zoom, 1, 6, 2, 1)

        self.play = Gtk.ToggleButton(icon_name="media-playback-start-symbolic", label="Play",
                                     css_classes=["suggested-action"], halign=Gtk.Align.START)
        self.play.connect("toggled", self._play_toggled)
        box.append(self.play)
        self.view = Gtk.DrawingArea(vexpand=True, hexpand=True)
        self.view.set_draw_func(self._draw)
        box.append(Gtk.Frame(child=self.view))
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"])
        box.append(self.status)
        self._speed_changed()
        self._reset()

    def _char_spin(self, value):
        s = Gtk.SpinButton.new_with_range(0, 255, 1)
        s.set_value(value)
        s.connect("value-changed", lambda *_: self._reset())
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.COPY)
        drop.connect("drop", lambda _t, v, _x, _y, sp=s: str(v).startswith("char:")
                     and (sp.set_value(int(str(v).split(":")[1])), True)[1])
        s.add_controller(drop)
        s.set_tooltip_text("A character number, or drop a character from the editor here")
        return s

    # ---------------------------------------------------------------- frames
    def frames(self) -> list[int]:
        per = int(self.across.get_value()) * int(self.down.get_value())
        return frame_starts(int(self.first.get_value()), int(self.last.get_value()), per)

    def sequence(self) -> list[int]:
        return order(len(self.frames()), PING_PONG if self.mode.get_selected() == 1 else LOOP)

    def current(self) -> int | None:
        f, seq = self.frames(), self.sequence()
        return f[seq[self.step % len(seq)]] if seq else None

    def _reset(self):
        self.step = 0
        self._show()

    def _show(self):
        f, seq = self.frames(), self.sequence()
        if not seq:
            self.status.set_text("No whole frame between the first and last characters")
        else:
            i = seq[self.step % len(seq)]
            ch = f[i]
            per = int(self.across.get_value()) * int(self.down.get_value())
            chars = f"characters {ch}–{ch + per - 1}" if per > 1 else f"character {ch} (${ch:02X})"
            self.status.set_text(f"Frame {i + 1} of {len(f)}: {chars}")
        self.view.queue_draw()

    def refresh(self):
        """The characters were edited."""
        self.view.queue_draw()

    # ---------------------------------------------------------------- playing
    def _speed_changed(self):
        self.speed.set_text(describe_speed(int(self.delay.get_value())))
        if self._timer:
            self.stop()
            self._start()

    def _start(self):
        ms = int(self.delay.get_value() * 20)            # a C64 (PAL) frame is 1/50 s
        self._timer = GLib.timeout_add(ms, self._tick)

    def stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def _play_toggled(self, b):
        if b.get_active():
            b.set_icon_name("media-playback-stop-symbolic")
            b.set_label("Stop")
            self._start()
        else:
            b.set_icon_name("media-playback-start-symbolic")
            b.set_label("Play")
            self.stop()

    def _tick(self):
        self.step += 1
        self._show()
        return True

    # ---------------------------------------------------------------- drawing
    def _draw(self, _da, cr, w, h):
        ed = self.editor
        d = ed.data
        cr.set_source_rgb(0.12, 0.12, 0.12)
        cr.paint()
        ch = self.current()
        if ch is None:
            return
        across, down = int(self.across.get_value()), int(self.down.get_value())
        bm = Bitmap(across * 8, down * 8)
        for r, row in enumerate(frame_chars(ch, across, down)):
            for c, n in enumerate(row):
                fg = d.colour_of(n) if ed.per_char else d.char_colour | (8 if d.multicolour else 0)
                draw_char_into(bm, c * 8, r * 8, d.chars[n], fg, d.background, d.multicolour, d.mc1, d.mc2)
        z = min(self.zoom.get_value(), w / bm.width, h / bm.height)
        paint_scaled(cr, bm.surface(), (w - bm.width * z) / 2, (h - bm.height * z) / 2, z, z)
