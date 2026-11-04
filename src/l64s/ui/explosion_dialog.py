"""Sprite Explosion Generator: make the frames of an explosion animation, preview them, and add
them to the sprite set or export them as BASIC DATA (CBM prg Studio's tool)."""
from __future__ import annotations

import random
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..gfx.explode import RECOMMENDED, TYPES, Params, basic_data, generate, mutate, random_preset  # noqa: E402
from .render import paint_scaled, render_sprite  # noqa: E402
from .widgets import ColourButton  # noqa: E402

PLACES = [("after", "After the current sprite"), ("end", "At the end of the set")]


class ExplosionDialog(Adw.Window):
    def __init__(self, parent, data, index: int, on_apply, project_dir: Path | None = None):
        super().__init__(transient_for=parent, modal=True, title="Sprite Explosion Generator", default_width=820,
                         default_height=600)
        self.data = data
        self.index = index
        self.on_apply = on_apply          # (sprites, insert_at, (mc1, mc2) or None) -> None
        self.project_dir = project_dir
        self.frames = []
        self.current = 0
        self._timer = None
        self._loading = False
        self.rng = random.Random()
        self.connect("close-request", lambda *_: (self._stop(), False)[1])

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        body = Gtk.Box(spacing=16, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)

        form = Gtk.Grid(column_spacing=8, row_spacing=6, valign=Gtk.Align.START)
        body.append(Gtk.ScrolledWindow(child=form, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       propagate_natural_width=True))
        r = 0

        def add(label, w, tip=None):
            nonlocal r
            lab = Gtk.Label(label=label, xalign=0)
            if tip:
                lab.set_tooltip_text(tip)
                w.set_tooltip_text(tip)
            form.attach(lab, 0, r, 1, 1)
            form.attach(w, 1, r, 1, 1)
            r += 1

        def spin(lo, hi, step, digits=0):
            s = Gtk.SpinButton.new_with_range(lo, hi, step)
            s.set_digits(digits)
            s.connect("value-changed", lambda *_: self._generate())
            return s

        self.type = Gtk.DropDown.new_from_strings([t.capitalize() for t in TYPES])
        self.type.connect("notify::selected", lambda *_: self._generate())
        add("Type", self.type)
        self.count = spin(1, 64, 1)
        add("Number of frames", self.count)
        self.params = {
            "radius": spin(1, 12, 1), "spikes": spin(1, 32, 1), "debris": spin(0, 40, 1),
            "turbulence": spin(0, 5, 0.5, 1), "thickness": spin(1, 3, 0.5, 1),
        }
        tips = {"radius": "How big it gets, in pixels", "spikes": "How many spikes (radial and starburst)",
                "debris": "How many pieces fly off (debris)", "turbulence": "How much the shapes wobble",
                "thickness": "How thick lines and rings are"}
        for k, w in self.params.items():
            lo, hi = RECOMMENDED[k]
            add(k.capitalize(), w, f"{tips[k]} (recommended {lo}-{hi})")
        self.seed = spin(1, (1 << 30) - 1, 1)
        add("Seed", self.seed, "The same seed and parameters always give the same explosion")
        presets = Gtk.Box(spacing=6)
        rnd = Gtk.Button(label="Random Preset", tooltip_text="Pick everything at random")
        rnd.connect("clicked", lambda *_: self._set_params(random_preset(self.rng)))
        mut = Gtk.Button(label="Mutate", tooltip_text="A variation on this one")
        mut.connect("clicked", lambda *_: self._set_params(mutate(self.params_now(), self.rng)))
        presets.append(rnd)
        presets.append(mut)
        form.attach(presets, 0, r, 2, 1)
        r += 1

        form.attach(Gtk.Label(label="<b>Colours</b>", use_markup=True, xalign=0, margin_top=8), 0, r, 2, 1)
        r += 1
        self.mode = Gtk.DropDown.new_from_strings(["Single colour", "Multicolour"])
        self.mode.set_selected(1)
        self.mode.connect("notify::selected", lambda *_: self._generate())
        add("Mode", self.mode)
        has_multi = any(s.multi for s in data.sprites)
        # %01 and %11 are the set's shared colours: start from them if the set already uses them
        mc1, mc2 = (data.mcolour1, data.mcolour2) if has_multi else (8, 2)
        self.col1 = ColourButton(7, "The hottest parts: the sprite's own colour (%10)")
        self.col2 = ColourButton(mc1, "Multicolour 1, $D025 (%01), shared by every sprite")
        self.col3 = ColourButton(mc2, "Multicolour 2, $D026 (%11), shared by every sprite")
        for c in (self.col1, self.col2, self.col3):
            c.connect("changed", lambda *_: self._redraw())
        add("Colour 1 (10)", self.col1)
        add("Colour 2 (01)", self.col2)
        add("Colour 3 (11)", self.col3)
        self.set_mc = Gtk.CheckButton(label="Set the sprite set's multicolours to these",
                                      active=not has_multi,
                                      tooltip_text="$D025 and $D026 are shared by every sprite, so this changes "
                                                   "how the other multicolour sprites look too")
        self.set_mc.connect("toggled", lambda *_: (self._sensitivity(), self._redraw()))
        form.attach(self.set_mc, 0, r, 2, 1)
        r += 1
        self.place = Gtk.DropDown.new_from_strings([p[1] for p in PLACES])
        self.place.set_selected(1)
        add("Add the frames", self.place)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        body.append(right)
        self.preview = Gtk.DrawingArea(content_width=24 * 8, content_height=21 * 8, halign=Gtk.Align.CENTER)
        self.preview.set_draw_func(self._draw_preview)
        right.append(self.preview)
        ctl = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        prev = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text="Previous frame")
        prev.connect("clicked", lambda *_: self._step(-1))
        self.play = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Play")
        self.play.connect("clicked", lambda *_: self._toggle_play())
        nxt = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Next frame")
        nxt.connect("clicked", lambda *_: self._step(1))
        self.fps = Gtk.SpinButton.new_with_range(1, 50, 1)
        self.fps.set_value(10)
        self.fps.set_tooltip_text("Preview speed (frames a second)")
        self.fps.connect("value-changed", lambda *_: self._restart_timer())
        self.frame_label = Gtk.Label(width_chars=12)
        for w in (prev, self.play, nxt, self.fps, self.frame_label):
            ctl.append(w)
        right.append(ctl)
        self.strip = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=16,
                                 min_children_per_line=4, column_spacing=4, row_spacing=4, valign=Gtk.Align.START)
        right.append(Gtk.ScrolledWindow(child=self.strip, vexpand=True, min_content_height=80,
                                        hscrollbar_policy=Gtk.PolicyType.NEVER))
        data_row = Gtk.Box(spacing=6)
        cp = Gtk.Button(label="Copy as DATA", tooltip_text="BASIC DATA lines, 63 bytes a frame")
        cp.connect("clicked", lambda *_: self._copy_data())
        sv = Gtk.Button(label="Export DATA…", tooltip_text="Save the frames as BASIC DATA lines (.bas)")
        sv.connect("clicked", lambda *_: self._export_data())
        data_row.append(cp)
        data_row.append(sv)
        self.status = Gtk.Label(xalign=0, hexpand=True, css_classes=["dim-label"], wrap=True)
        data_row.append(self.status)
        right.append(data_row)

        self.apply = Gtk.Button(css_classes=["suggested-action"])
        self.apply.connect("clicked", lambda *_: self._apply())
        hb.pack_end(self.apply)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        hb.pack_start(cancel)
        self._set_params(Params(type="fireball", frames=8, radius=9, spikes=10, debris=12, turbulence=1.5,
                                thickness=1.5, seed=1))

    # ================================================================== parameters
    def params_now(self) -> Params:
        v = {k: w.get_value() for k, w in self.params.items()}
        return Params(type=TYPES[self.type.get_selected()], frames=self.count.get_value_as_int(),
                      radius=v["radius"], spikes=int(v["spikes"]), debris=int(v["debris"]),
                      turbulence=v["turbulence"], thickness=v["thickness"], seed=self.seed.get_value_as_int())

    def _set_params(self, p: Params):
        self._loading = True
        self.type.set_selected(TYPES.index(p.type))
        self.count.set_value(p.frames)
        for k, w in self.params.items():
            w.set_value(getattr(p, k))
        self.seed.set_value(p.seed)
        self._loading = False
        self._generate()

    @property
    def multi(self) -> bool:
        return self.mode.get_selected() == 1

    def _generate(self):
        if self._loading:
            return
        self._sensitivity()
        try:
            self.frames = generate(self.params_now(), self.multi, self.col1.colour)
        except ValueError as e:
            self.frames = []
            self.status.set_text(str(e))
        else:
            self.status.set_text("")
        self.current = min(self.current, max(0, len(self.frames) - 1))
        self._fill_strip()
        n = len(self.frames)
        self.apply.set_label(f"Add {n} Sprite{'s' if n != 1 else ''}")
        self.apply.set_sensitive(n > 0)
        self._show_frame()

    def _sensitivity(self):
        for c in (self.col2, self.col3):
            c.set_sensitive(self.multi and self.set_mc.get_active())
        self.set_mc.set_sensitive(self.multi)

    def _shared_colours(self) -> tuple[int, int]:
        """The %01 and %11 colours the sprites will have."""
        if self.set_mc.get_active():
            return self.col2.colour, self.col3.colour
        return self.data.mcolour1, self.data.mcolour2

    def _redraw(self):
        for f in self.frames:
            f.colour = self.col1.colour
        self.preview.queue_draw()
        self.strip.queue_draw()
        c = self.strip.get_first_child()
        while c:
            c.get_child().get_child().queue_draw()
            c = c.get_next_sibling()

    # ================================================================== drawing
    def _render(self, s, cr, w, h):
        mc1, mc2 = self._shared_colours()
        bm = render_sprite(s.rows, s.multi, self.col1.colour, self.data.background, mc1, mc2)
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

    def _goto(self, i):
        self.current = i
        self._show_frame()

    def _step(self, d):
        if self.frames:
            self._goto((self.current + d) % len(self.frames))

    def _toggle_play(self):
        if self._timer:
            self._stop()
        else:
            self._restart_timer(start=True)

    def _restart_timer(self, start=False):
        running = self._timer is not None
        self._stop()
        if running or start:
            self._timer = GLib.timeout_add(int(1000 / self.fps.get_value()), lambda: (self._step(1), True)[1])
            self.play.set_icon_name("media-playback-stop-symbolic")
            self.play.set_tooltip_text("Stop")

    def _stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        self.play.set_icon_name("media-playback-start-symbolic")
        self.play.set_tooltip_text("Play")

    # ================================================================== output
    def data_text(self) -> str:
        p = self.params_now()
        head = (f"rem {p.type} explosion, {len(self.frames)} frames "
                f"({'multicolour' if self.multi else 'single colour'})")
        return f"990 {head}\n" + basic_data(self.frames, 1000, 10)

    def _copy_data(self):
        if self.frames:
            Gdk.Display.get_default().get_clipboard().set(self.data_text())
            self.status.set_text(f"Copied {len(self.frames)} frames as DATA")

    def _export_data(self):
        if not self.frames:
            return
        dlg = Gtk.FileDialog(title="Export the frames as DATA")
        dlg.set_initial_name("explosion_sprites.bas")
        if self.project_dir:
            from gi.repository import Gio
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.project_dir)))

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_text(self.data_text())
            self.status.set_text(f"Exported {len(self.frames)} frames as DATA statements to {dest.name}")
        dlg.save(self, None, done)

    def _apply(self):
        if not self.frames:
            return
        self._stop()
        at = self.index + 1 if PLACES[self.place.get_selected()][0] == "after" else len(self.data.sprites)
        mc = (self.col2.colour, self.col3.colour) if self.multi and self.set_mc.get_active() else None
        frames = []
        p = self.params_now()
        for i, f in enumerate(self.frames):
            s = f.copy()
            s.colour = self.col1.colour
            s.description = f"{p.type} {i + 1}"
            frames.append(s)
        self.on_apply(frames, at, mc)
        self.close()
