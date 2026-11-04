"""Sprite Morph: make the frames that turn one sprite into another, preview them, and add them to
the sprite set (CBM prg Studio's Sprite Morph Tool)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..gfx.morph import EASINGS, ORDERS, morph  # noqa: E402
from .render import paint_scaled, render_sprite  # noqa: E402

PLACES = [("between", "After the start sprite (the in-between frames)"),
          ("end", "At the end of the set (the whole sequence)")]


class MorphDialog(Adw.Window):
    def __init__(self, parent, data, start: int, on_apply):
        super().__init__(transient_for=parent, modal=True, title="Sprite Morph", default_width=760,
                         default_height=560)
        self.data = data                  # the SpriteSet
        self.on_apply = on_apply          # (frames, insert_at) -> None
        self.frames = []
        self.current = 0
        self._timer = None
        self.connect("close-request", lambda *_: (self._stop(), False)[1])

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        body = Gtk.Box(spacing=16, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)

        form = Gtk.Grid(column_spacing=8, row_spacing=8, valign=Gtk.Align.START)
        body.append(form)
        # numbered as the sprite editor's list numbers them
        names = [f"{i} (${i:02X})" + (f"  {s.description}" if s.description else "") for i, s in enumerate(data.sprites)]
        self.start = Gtk.DropDown.new_from_strings(names)
        self.start.set_selected(start)
        self.end = Gtk.DropDown.new_from_strings(names)
        self.end.set_selected(min(start + 1, len(names) - 1))
        self.count = Gtk.SpinButton.new_with_range(2, 64, 1)
        self.count.set_value(8)
        self.easing = Gtk.DropDown.new_from_strings([e.capitalize() for e in EASINGS])
        self.order = Gtk.DropDown.new_from_strings([o.capitalize() for o in ORDERS])
        self.place = Gtk.DropDown.new_from_strings([p[1] for p in PLACES])
        self.fps = Gtk.SpinButton.new_with_range(1, 50, 1)
        self.fps.set_value(8)
        rows = [("Start sprite", self.start), ("End sprite", self.end), ("Frames", self.count),
                ("Function", self.easing), ("Order", self.order), ("Preview speed (fps)", self.fps),
                ("Add the frames", self.place)]
        for r, (label, w) in enumerate(rows):
            form.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            form.attach(w, 1, r, 1, 1)
        for w in (self.start, self.end, self.easing, self.order):
            w.connect("notify::selected", lambda *_: self._generate())
        self.count.connect("value-changed", lambda *_: self._generate())
        self.place.connect("notify::selected", lambda *_: self._update_apply())
        self.fps.connect("value-changed", lambda *_: self._restart_timer())
        self.note = Gtk.Label(xalign=0, wrap=True, max_width_chars=36, css_classes=["dim-label"])
        form.attach(self.note, 0, len(rows), 2, 1)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        body.append(right)
        self.preview = Gtk.DrawingArea(content_width=24 * 9, content_height=21 * 9, halign=Gtk.Align.CENTER)
        self.preview.set_draw_func(self._draw_preview)
        right.append(self.preview)
        ctl = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        prev = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text="Previous frame")
        prev.connect("clicked", lambda *_: self._step(-1))
        self.play = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Play")
        self.play.connect("clicked", lambda *_: self._toggle_play())
        nxt = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Next frame")
        nxt.connect("clicked", lambda *_: self._step(1))
        self.frame_label = Gtk.Label(width_chars=12)
        for w in (prev, self.play, nxt, self.frame_label):
            ctl.append(w)
        right.append(ctl)
        self.strip = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=16,
                                 min_children_per_line=4, column_spacing=4, row_spacing=4, valign=Gtk.Align.START)
        right.append(Gtk.ScrolledWindow(child=self.strip, vexpand=True, min_content_height=80,
                                        hscrollbar_policy=Gtk.PolicyType.NEVER))

        self.apply = Gtk.Button(css_classes=["suggested-action"])
        self.apply.connect("clicked", lambda *_: self._apply())
        hb.pack_end(self.apply)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        hb.pack_start(cancel)
        self._generate()

    # ================================================================== frames
    def _generate(self):
        a, b = self.start.get_selected(), self.end.get_selected()
        sprites = self.data.sprites
        try:
            self.frames = morph(sprites[a], sprites[b], self.count.get_value_as_int(),
                                list(EASINGS)[self.easing.get_selected()], ORDERS[self.order.get_selected()])
        except ValueError as e:
            self.frames = []
            self.note.set_text(str(e))
            return
        self.current = min(self.current, len(self.frames) - 1)
        notes = []
        if a == b:
            notes.append("The start and end sprites are the same, so every frame is too.")
        if sprites[a].multi != sprites[b].multi:
            notes.append(f"The frames are {'multicolour' if sprites[a].multi else 'single colour'}, like the "
                         f"start sprite; the end sprite is read that way too.")
        self.note.set_text(" ".join(notes))
        self._fill_strip()
        self._update_apply()
        self.preview.queue_draw()
        self._show_frame()

    def _render(self, s, cr, w, h):
        bm = render_sprite(s.rows, s.multi, s.colour, self.data.background, self.data.mcolour1, self.data.mcolour2)
        paint_scaled(cr, bm.surface(), 0, 0, w / 24, h / 21)

    def _fill_strip(self):
        while (c := self.strip.get_first_child()) is not None:
            self.strip.remove(c)
        for i, f in enumerate(self.frames):
            b = Gtk.Button(css_classes=["flat"], tooltip_text=f"Frame {i + 1}", valign=Gtk.Align.START,
                           halign=Gtk.Align.START)
            da = Gtk.DrawingArea(content_width=48, content_height=42)
            da.set_draw_func(lambda _d, cr, w, h, f=f: self._render(f, cr, w, h))
            b.set_child(da)
            b.connect("clicked", lambda _b, i=i: self._goto(i))
            self.strip.append(b)

    def _draw_preview(self, _da, cr, w, h):
        if self.frames:
            self._render(self.frames[self.current], cr, w, h)

    def _show_frame(self):
        self.frame_label.set_text(f"Frame {self.current + 1} of {len(self.frames)}" if self.frames else "")
        self.preview.queue_draw()

    def _goto(self, i: int):
        self.current = i
        self._show_frame()

    def _step(self, d: int):
        if self.frames:
            self._goto((self.current + d) % len(self.frames))

    # ================================================================== playing
    def _toggle_play(self):
        if self._timer:
            self._stop()
        else:
            self._restart_timer(start=True)

    def _restart_timer(self, start: bool = False):
        running = self._timer is not None
        self._stop()
        if running or start:
            self._timer = GLib.timeout_add(int(1000 / self.fps.get_value()), self._tick)
            self.play.set_icon_name("media-playback-pause-symbolic")
            self.play.set_tooltip_text("Pause")

    def _tick(self):
        self._step(1)
        return True

    def _stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        self.play.set_icon_name("media-playback-start-symbolic")
        self.play.set_tooltip_text("Play")

    # ================================================================== adding them
    def _to_add(self):
        """(the sprites to add, where to insert them)."""
        if PLACES[self.place.get_selected()][0] == "between":
            return self.frames[1:-1], self.start.get_selected() + 1
        return list(self.frames), len(self.data.sprites)

    def _update_apply(self):
        sprites, _ = self._to_add() if self.frames else ([], 0)
        self.apply.set_label(f"Add {len(sprites)} Sprite{'s' if len(sprites) != 1 else ''}")
        self.apply.set_sensitive(bool(sprites))

    def _apply(self):
        sprites, at = self._to_add()
        if sprites:
            self._stop()
            self.on_apply([s.copy() for s in sprites], at)
            self.close()
