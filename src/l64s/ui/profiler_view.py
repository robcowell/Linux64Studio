"""The Profiler tab: runs the program in VICE and shows where its time goes, by routine, source
line and file, and where in the frame (by raster line) each routine runs. l64s.profiler samples."""
from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from ..profiler import Profile, ProfileRun, Resolver, Row, ViceRun  # noqa: E402
from ..routine_timing import CPU_IRQ, KERNAL_IRQ, Timer, Timing  # noqa: E402
from . import textzoom  # noqa: E402
from .editor import EditorPage  # noqa: E402

ROWS = 80                 # rows shown in each list
# The frame chart's colours for the busiest routines (readable on light and dark backgrounds)
COLOURS = [(0.26, 0.55, 0.96), (0.95, 0.47, 0.18), (0.20, 0.70, 0.40), (0.86, 0.26, 0.42),
           (0.60, 0.40, 0.85), (0.93, 0.75, 0.15), (0.15, 0.70, 0.75), (0.75, 0.50, 0.35)]
OTHER = (0.55, 0.55, 0.55)
VISIBLE = (51, 251)       # the raster lines of the screen's 25 text rows (the rest is border)
EMPTY = ("Profile in VICE builds the program and runs it in VICE, at its real speed, measuring where the "
         "6510's time goes: which routines and lines, and where in the frame. Play the game while it "
         "measures; Reset starts the counts again from now.")


def _clear(box):
    while (c := box.get_first_child()) is not None:
        box.remove(c)


class ShareBar(Gtk.DrawingArea):
    """A row's share, as a bar the length of its share of the top row's."""

    def __init__(self, fraction: float, colour=COLOURS[0]):
        super().__init__(content_width=90, content_height=12, valign=Gtk.Align.CENTER)
        self.fraction, self.colour = max(0.0, min(1.0, fraction)), colour
        self.set_draw_func(self._draw)

    def _draw(self, _w, cr, width, height):
        cr.set_source_rgba(*self.colour, 0.18)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.set_source_rgb(*self.colour)
        cr.rectangle(0, 0, max(1.0, width * self.fraction), height)
        cr.fill()


class FrameChart(Gtk.DrawingArea):
    """The frame, top (raster line 0) to bottom: each line a bar split between the routines that
    run on it, as the border-colour trick shows it, but measured."""

    def __init__(self):
        super().__init__(vexpand=True, hexpand=True, has_tooltip=True)
        self.lines: list = []
        self.colours: dict = {}
        self.set_draw_func(self._draw)
        self.connect("query-tooltip", self._tooltip)

    def show(self, lines, colours):
        self.lines, self.colours = lines, colours
        self.queue_draw()

    def _geometry(self, width, height):
        left = textzoom.px(44)
        n = len(self.lines) or 312
        return left, 6, max(10, width - left - 8), max(10, height - 12), n

    def _draw(self, _w, cr, width, height):
        fg = self.get_color()
        left, top, w, h, n = self._geometry(width, height)
        per = h / n
        # the screen's rows
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
        cr.rectangle(left, top + VISIBLE[0] * per, w, (VISIBLE[1] - VISIBLE[0]) * per)
        cr.fill()
        rank = {k: i for i, k in enumerate(self.colours)}
        for i, parts in enumerate(self.lines):
            x = left
            # in the same order on every line (the busiest routine overall first), so they line up
            for r, share in sorted(parts, key=lambda p: rank.get((p[0].name, p[0].address), len(rank))):
                cr.set_source_rgb(*self.colours.get((r.name, r.address), OTHER))
                cr.rectangle(x, top + i * per, w * share, per + 0.6)
                cr.fill()
                x += w * share
        cr.select_font_face("Sans")
        cr.set_font_size(textzoom.px(10))
        for ln in range(0, n, 50):
            y = top + ln * per
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
            cr.move_to(4, y + 4)
            cr.show_text(str(ln))
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25)
            cr.rectangle(left - 6, y, 4, 1)
            cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
        for ln in VISIBLE:
            cr.rectangle(left - 3, top + ln * per, 2, 1)
        cr.fill()

    def _tooltip(self, _w, x, y, _kb, tip):
        if not self.lines:
            return False
        _left, top, _wd, h, n = self._geometry(self.get_width(), self.get_height())
        ln = int((y - top) / (h / n))
        if not 0 <= ln < n:
            return False
        parts = self.lines[ln]
        where = "the screen" if VISIBLE[0] <= ln < VISIBLE[1] else "the border"
        text = [f"Raster line {ln} (${ln:03X}, {where})"]
        text += [f"{share * 100:5.1f}%  {GLib.markup_escape_text(r.name)}" for r, share in parts[:6]]
        if not parts:
            text.append("No samples yet")
        tip.set_markup("<tt>" + "\n".join(text) + "</tt>")
        return True


class ProfilerView(EditorPage):
    kind = "profiler"

    def __init__(self, start: Callable[[], None], open_line: Callable[[str, int], None],
                 line_text: Callable[[str, int], str], show_figures: Callable[[dict | None], None] | None = None,
                 time_routine: Callable[[str], None] | None = None):
        super().__init__(None)
        self._start, self.open_line, self.line_text = start, open_line, line_text
        self.show_figures = show_figures or (lambda _shares: None)
        self.time_routine = time_routine or (lambda _name: None)
        self.run: ViceRun | None = None
        self.mode = "profile"                # what the run's doing: profile or timing
        self.timing: Timing | None = None
        self.timing_name = ""
        self.profile: Profile | None = None
        self.resolver: Resolver | None = None
        self.emulated = 0                    # cycles of the program's time in the profile
        self.clock = 985248
        self.state = "idle"                  # idle, starting, running, stopped
        self.message = ""
        self._dirty = False
        self._closed = False

        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        self.go = Gtk.Button(label="Profile in VICE", css_classes=["suggested-action"],
                             tooltip_text="Build the program and run it in VICE, measuring where its time goes")
        self.go.connect("clicked", lambda *_: self._start())
        self.stop_button = Gtk.Button(label="Stop", sensitive=False,
                                      tooltip_text="Stop measuring (the program carries on in VICE)")
        self.stop_button.connect("clicked", lambda *_: self.stop())
        self.reset = Gtk.Button(label="Reset", sensitive=False,
                                tooltip_text="Start the counts again from now (to measure one part of the program)")
        self.reset.connect("clicked", lambda *_: self.clear())
        self.copy = Gtk.Button(icon_name="edit-copy-symbolic", sensitive=False,
                               tooltip_text="Copy the profile as text")
        self.copy.connect("clicked", lambda *_: self._copy())
        self.in_editor = Gtk.CheckButton(label="In the editor", active=True,
                                         tooltip_text="Show each line's share of the time beside it in the editor, "
                                                      "and tint the busiest lines")
        self.in_editor.connect("toggled", lambda *_: self._push_figures())
        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                css_classes=["dim-label"])
        for w in (self.go, self.stop_button, self.reset, self.copy, self.in_editor, self.status):
            bar.append(w)
        self.append(bar)

        self.views = Adw.ViewStack(vexpand=True)
        self.lists: dict[str, Gtk.ListBox] = {}
        for name, title, icon in (("routines", "Routines", "view-list-symbolic"),
                                  ("lines", "Lines", "format-justify-left-symbolic"),
                                  ("files", "Files", "folder-documents-symbolic")):
            lb = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
                             margin_start=8, margin_end=8, margin_bottom=8)
            lb.set_placeholder(Gtk.Label(label=EMPTY, wrap=True, margin_top=24, margin_bottom=24, margin_start=24,
                                         margin_end=24, css_classes=["dim-label"]))
            lb.connect("row-activated", self._activated)
            self.lists[name] = lb
            self.views.add_titled_with_icon(Gtk.ScrolledWindow(child=lb, vexpand=True), name, title, icon)
        frame = Gtk.Box(spacing=12, margin_start=8, margin_end=8, margin_bottom=8)
        self.chart = FrameChart()
        frame.append(self.chart)
        self.legend = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=220)
        frame.append(Gtk.ScrolledWindow(child=self.legend, hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=False))
        self.views.add_titled_with_icon(frame, "frame", "Frame", "video-display-symbolic")
        self.timing_page = TimingPage(self._time_clicked, lambda: self.stop())
        self.views.add_titled_with_icon(Gtk.ScrolledWindow(child=self.timing_page, hscrollbar_policy=Gtk.PolicyType.NEVER),
                                        "timing", "Timing", "alarm-symbolic")
        self.views.connect("notify::visible-child-name", lambda *_: self._refresh(figures=False))
        switcher = Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE,
                                    halign=Gtk.Align.CENTER, margin_bottom=6)
        self.append(switcher)
        self.append(self.views)
        self._update_buttons()
        GLib.timeout_add(1000, self._tick)

    @property
    def title(self) -> str:
        return "Profiler"

    def save(self):
        pass

    # ------------------------------------------------------------------ running
    def begin(self, target, resolver: Resolver, emulator: str = "", extra_args: list[str] | None = None):
        """Run the program in VICE and profile it (a profile already running stops first)."""
        if self.run:
            self.run.stop()
        self.resolver = resolver
        self.profile = None
        self.emulated = 0
        self.mode = "profile"
        self.state, self.message = "starting", ""
        idle = GLib.idle_add
        run = ProfileRun(target, resolver,
                         on_start=lambda mem, timing: idle(self._started, run, mem, timing),
                         on_batch=lambda samples, cyc: idle(self._batch, run, samples, cyc),
                         on_end=lambda msg: idle(self._ended, run, msg),
                         emulator=emulator, extra_args=extra_args)
        self.run = run
        try:
            run.start()
        except FileNotFoundError as e:
            self.run = None
            self.state, self.message = "idle", str(e)
        self._refresh()

    def stop(self):
        if self.run:
            self.run.stop()

    def _time_clicked(self, name: str):
        self.time_routine(name)

    def begin_timing(self, target, entry: int, name: str, emulator: str = "", extra_args: list[str] | None = None):
        """Run the program in VICE and time every call of the routine at ``entry``."""
        if self.run:
            self.run.stop()
        self.mode = "timing"
        self.timing, self.timing_name = None, name
        self.state, self.message = "starting", ""
        self.views.set_visible_child_name("timing")
        self.timing_page.set_name(name)
        idle = GLib.idle_add
        run = ViceRun(target, lambda m: Timer(m, entry, lambda t: idle(self._timed, run, t)),
                      lambda msg: idle(self._ended, run, msg), emulator, extra_args)
        self.run = run
        try:
            run.start()
        except FileNotFoundError as e:
            self.run = None
            self.state, self.message = "idle", str(e)
        self._refresh()

    def _timed(self, run, timing):
        if run is not self.run:
            return False
        self.timing = timing
        if self.state == "starting":
            self.state = "running"
        self._dirty = True
        return False

    def timing_failed(self, message: str):
        """The routine couldn't be timed (not found, the build failed): say why."""
        self.views.set_visible_child_name("timing")
        self.timing_page.show_message(message)

    def closing(self):
        """The tab's closing: stop measuring (VICE carries on)."""
        self._closed = True
        self.stop()
        self.show_figures(None)

    def clear(self):
        if self.mode == "timing":
            if self.timing:
                self.timing.clear()
                self._refresh()
            return
        if self.profile:
            self.profile.clear()
            self.emulated = 0
            self._refresh()

    def _started(self, run, memory, timing):
        if run is not self.run:
            return False
        self.clock = timing[2]
        self.profile = Profile(self.resolver, memory, timing[1])
        self.state = "running"
        self._refresh()
        return False

    def _batch(self, run, samples, cycles):
        if run is not self.run or self.profile is None:
            return False
        for pc, line in samples:
            self.profile.add(pc, line)
        self.emulated += cycles
        self._dirty = True
        return False

    def _ended(self, run, message):
        if run is not self.run:
            return False
        done = self.timing if self.mode == "timing" else self.profile
        self.state, self.message = ("stopped" if done else "idle"), message
        self.run = None
        self._refresh()
        return False

    def _tick(self):
        if self._closed:
            return False
        if self._dirty:
            self._dirty = False
            self._refresh()
        return True

    # ------------------------------------------------------------------ showing it
    def _update_buttons(self):
        running = self.state in ("starting", "running")
        self.go.set_sensitive(not running)
        self.stop_button.set_sensitive(running)
        self.reset.set_sensitive(self.state == "running")
        page = self.views.get_visible_child_name()
        self.copy.set_sensitive(bool(self.timing and self.timing.calls) if page == "timing"
                                else bool(self.profile and self.profile.samples))
        self.timing_page.set_running(running)

    def _status_text(self) -> str:
        p = self.profile
        if self.state == "starting":
            if self.mode == "timing":
                return f"Starting VICE, waiting for {self.timing_name} to be called…"
            return "Starting VICE, waiting for the program to start…"
        if self.mode == "timing":
            t = self.timing
            if t is None:
                return self.message
            text = f"Timing {self.timing_name}: {len(t.calls):,} calls measured"
            if self.state == "running":
                return "Measuring: " + text
            return "Stopped: " + text + (f". {self.message}" if self.message else "")
        if p is None:
            return self.message
        secs = self.emulated / self.clock
        text = f"{p.samples:,} samples over {secs:.1f} s of the program"
        if self.state == "running":
            text = "Measuring: " + text
        elif self.state == "stopped":
            text = "Stopped: " + text + (f". {self.message}" if self.message else "")
        return text

    def _push_figures(self):
        p = self.profile
        on = self.in_editor.get_active() and p is not None and p.samples > 0
        self.show_figures(p.line_shares() if on else None)

    def _refresh(self, figures: bool = True):
        if figures:
            self._push_figures()
        self._update_buttons()
        self.status.set_text(self._status_text())
        if self.views.get_visible_child_name() == "timing":
            self.timing_page.show(self.timing, self.timing_name, self.message if self.mode == "timing" else "")
        p = self.profile
        if p is None or not p.samples:
            for lb in self.lists.values():
                _clear(lb)
            self.chart.show([], {})
            _clear(self.legend)
            return
        # (only the page that's showing: the others when they're shown)
        page = self.views.get_visible_child_name()
        if page == "timing":
            return
        routines = p.routines()
        colours = {(r.name, r.address): COLOURS[i] for i, r in enumerate(routines[:len(COLOURS)])}
        if page == "routines":
            self._fill(self.lists["routines"], routines, colours, show_code=False)
        elif page == "lines":
            self._fill(self.lists["lines"], p.lines(), {}, show_code=True)
        elif page == "files":
            self._fill(self.lists["files"], p.files(), {}, show_code=False)
        elif page == "frame":
            self._show_frame(p, routines, colours)

    def _show_frame(self, p: Profile, routines: list[Row], colours: dict):
        self.chart.show(p.raster_lines(), colours)
        _clear(self.legend)
        self.legend.append(Gtk.Label(label="The frame, raster line 0 at the top. The shaded band is the "
                                           "screen's 25 rows; hover over a line for its routines.",
                                     wrap=True, xalign=0, css_classes=["dim-label", "caption"]))
        for i, r in enumerate(routines[:len(COLOURS)]):
            self.legend.append(self._legend_row(COLOURS[i], r))
        rest = sum(r.share for r in routines[len(COLOURS):])
        if rest > 0:
            self.legend.append(self._legend_row(OTHER, Row("everything else", rest, 0)))

    @staticmethod
    def _legend_row(colour, row: Row):
        box = Gtk.Box(spacing=6)
        swatch = Gtk.DrawingArea(content_width=12, content_height=12, valign=Gtk.Align.CENTER)
        swatch.set_draw_func(lambda _w, cr, w, h, c=colour: (cr.set_source_rgb(*c), cr.rectangle(0, 0, w, h),
                                                             cr.fill()))
        box.append(swatch)
        box.append(Gtk.Label(label=f"{row.share * 100:.1f}%", width_chars=6, xalign=1,
                             css_classes=["monospace"]))
        box.append(Gtk.Label(label=row.name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                             tooltip_text=row.name))
        return box

    def _fill(self, lb: Gtk.ListBox, rows: list[Row], colours: dict, show_code: bool):
        _clear(lb)
        top = rows[0].share if rows else 1
        for r in rows[:ROWS]:
            row = Gtk.ListBoxRow(activatable=bool(r.file))
            row.data = r
            box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
            box.append(Gtk.Label(label=f"{r.share * 100:.1f}%", width_chars=6, xalign=1,
                                 css_classes=["monospace"]))
            box.append(ShareBar(r.share / top if top else 0, colours.get((r.name, r.address), COLOURS[0])))
            name = Gtk.Label(label=r.name, xalign=0, width_chars=24, ellipsize=Pango.EllipsizeMode.END,
                             tooltip_text=r.file or None)
            box.append(name)
            if show_code:
                text = self.line_text(r.file, r.line).strip() if r.file else ""
                box.append(Gtk.Label(label=text, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                     css_classes=["monospace"]))
            else:
                box.append(Gtk.Label(label=r.module, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                     css_classes=["dim-label"]))
            if r.address and lb is not self.lists["files"]:
                box.append(Gtk.Label(label=f"${r.address:04X}", css_classes=["monospace", "dim-label"]))
            box.append(Gtk.Label(label=f"{r.samples:,}", width_chars=8, xalign=1, css_classes=["dim-label"],
                                 tooltip_text="Samples"))
            row.set_child(box)
            lb.append(row)
        if len(rows) > ROWS:
            lb.append(Gtk.ListBoxRow(activatable=False, child=Gtk.Label(
                label=f"and {len(rows) - ROWS} more, under 0.1% each" if rows[ROWS].share < 0.001
                else f"and {len(rows) - ROWS} more", css_classes=["dim-label"], margin_top=4, margin_bottom=4)))

    def _activated(self, _lb, row):
        r = getattr(row, "data", None)
        if r and r.file:
            self.open_line(r.file, r.line or 1)

    def _copy(self):
        if self.views.get_visible_child_name() == "timing":
            if self.timing and self.timing.calls:
                Gdk.Display.get_default().get_clipboard().set(self.timing.report(self.timing_name))
            return
        if self.profile and self.profile.samples:
            Gdk.Display.get_default().get_clipboard().set(
                self.profile.report(self.emulated / self.clock))


class Histogram(Gtk.DrawingArea):
    """How many calls took how many cycles."""

    def __init__(self):
        super().__init__(content_height=140, content_width=200, hexpand=True)
        self.bins: list[tuple[int, int, int]] = []
        self.set_draw_func(self._draw)

    def show(self, bins):
        self.bins = bins
        self.queue_draw()

    def _draw(self, _w, cr, width, height):
        fg = self.get_color()
        if not self.bins:
            return
        top = max(n for _a, _b, n in self.bins) or 1
        base, left = height - textzoom.px(18), 4
        w = (width - 2 * left) / len(self.bins)
        cr.set_source_rgb(*COLOURS[0])
        for i, (_a, _b, n) in enumerate(self.bins):
            h = (base - 6) * n / top
            cr.rectangle(left + i * w + 1, base - h, max(1.0, w - 2), h)
        cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
        cr.select_font_face("Sans")
        cr.set_font_size(textzoom.px(10))
        cr.move_to(left, height - 4)
        cr.show_text(f"{self.bins[0][0]:,} cycles")
        text = f"{self.bins[-1][1]:,}"
        cr.move_to(width - left - cr.text_extents(text).x_advance, height - 4)
        cr.show_text(text)


class CallFrame(Gtk.DrawingArea):
    """The frame, top to bottom, shaded where the routine runs: how many of its calls are running
    on each raster line."""

    def __init__(self):
        super().__init__(content_width=90, content_height=330, vexpand=True, has_tooltip=True)
        self.cover: list[float] = []
        self.set_draw_func(self._draw)
        self.connect("query-tooltip", self._tooltip)

    def show(self, timing: Timing | None):
        self.cover = []
        if timing and timing.calls:
            lines = timing.timing[1]
            hits = [0] * lines
            for c in timing.calls:
                n = c.end_line - c.start_line if c.end_line >= c.start_line else c.end_line + lines - c.start_line
                for k in range(n + 1):
                    hits[(c.start_line + k) % lines] += 1
            self.cover = [h / len(timing.calls) for h in hits]
        self.queue_draw()

    def _draw(self, _w, cr, width, height):
        fg = self.get_color()
        n = len(self.cover) or 312
        per = (height - 12) / n
        left = textzoom.px(30)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
        cr.rectangle(left, 6, width - left, n * per)
        cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.05)
        cr.rectangle(left, 6 + VISIBLE[0] * per, width - left, (VISIBLE[1] - VISIBLE[0]) * per)
        cr.fill()
        for i, f in enumerate(self.cover):
            if f > 0:
                cr.set_source_rgba(*COLOURS[1], 0.25 + 0.75 * f)
                cr.rectangle(left, 6 + i * per, width - left, per + 0.6)
                cr.fill()
        cr.select_font_face("Sans")
        cr.set_font_size(textzoom.px(10))
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
        for ln in range(0, n, 50):
            cr.move_to(2, 6 + ln * per + 4)
            cr.show_text(str(ln))

    def _tooltip(self, _w, _x, y, _kb, tip):
        if not self.cover:
            return False
        n = len(self.cover)
        ln = int((y - 6) / ((self.get_height() - 12) / n))
        if not 0 <= ln < n:
            return False
        tip.set_text(f"Raster line {ln}: running in {self.cover[ln] * 100:.0f}% of the calls")
        return True


class TimingPage(Gtk.Box):
    """Routine timing: every call of one routine, measured in VICE."""

    def __init__(self, start: Callable[[str], None], stop: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=12, margin_end=12,
                         margin_bottom=8)
        self._start = start
        row = Gtk.Box(spacing=6)
        row.append(Gtk.Label(label="Routine"))
        self.entry = Gtk.Entry(placeholder_text="a label, a C function or an address ($1000)", hexpand=True,
                               width_chars=20,
                               tooltip_text="What to time: its first instruction is where each call starts")
        self.entry.connect("activate", lambda *_: self._go())
        row.append(self.entry)
        self.go = Gtk.Button(label="Time in VICE", css_classes=["suggested-action"],
                             tooltip_text="Build the program and run it in VICE, measuring every call of the routine")
        self.go.connect("clicked", lambda *_: self._go())
        row.append(self.go)
        self.stop_button = Gtk.Button(label="Stop", sensitive=False)
        self.stop_button.connect("clicked", lambda *_: stop())
        row.append(self.stop_button)
        self.append(row)
        self.note = Gtk.Label(wrap=True, xalign=0, max_width_chars=60, width_chars=30, css_classes=["dim-label"], label=(
            "Times every call of one routine exactly, in cycles, as the program runs in VICE: the fewest, "
            "the most and the average, how often it's called, and where in the frame it runs. Name it "
            "above, or right-click in it in the editor: Time This Routine."))
        self.append(self.note)
        body = Gtk.Box(spacing=16, vexpand=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True)
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)     # the figures, a row each
        left.append(self.grid)
        self.hist_label = Gtk.Label(label="Calls by cycles", xalign=0, css_classes=["heading"], visible=False)
        left.append(self.hist_label)
        self.histogram = Histogram()
        left.append(self.histogram)
        body.append(left)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.frame_label = Gtk.Label(label="Where in the frame", css_classes=["heading"], visible=False)
        side.append(self.frame_label)
        self.frame = CallFrame()
        side.append(self.frame)
        body.append(side)
        self.append(body)

    def _go(self):
        name = self.entry.get_text().strip()
        if name:
            self._start(name)

    def set_name(self, name: str):
        if self.entry.get_text().strip() != name:
            self.entry.set_text(name)

    def set_running(self, running: bool):
        self.go.set_sensitive(not running)
        self.stop_button.set_sensitive(running)

    def show_message(self, message: str):
        self.note.set_text(message)
        self.note.remove_css_class("dim-label")

    def _row(self, r: int, label: str, value: str, extra: str = ""):
        row = Gtk.Box(spacing=18)
        row.append(Gtk.Label(label=label, xalign=0, width_chars=15, css_classes=["dim-label"]))
        row.append(Gtk.Label(label=value, xalign=1, width_chars=12, css_classes=["monospace"]))
        row.append(Gtk.Label(label=extra, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                             css_classes=["dim-label"]))
        self.grid.append(row)

    def show(self, t: Timing | None, name: str, message: str = ""):
        _clear(self.grid)
        st = t.stats() if t else None
        if message:
            self.show_message(message)
        for w in (self.hist_label, self.frame_label):
            w.set_visible(st is not None)
        if t is None or st is None:
            self.histogram.show([])
            self.frame.show(None)
            return
        line, frame = t.timing[0], t.frame_cycles
        r = 0
        how = {KERNAL_IRQ: "an interrupt handler (through the KERNAL's vector)",
               CPU_IRQ: "an interrupt handler (the CPU's vector)"}.get(t.how, "a subroutine (JSR)")
        self._row(r, "Routine", name, how)
        r += 1
        self._row(r, "Calls measured", f"{len(t.calls):,}",
                  f"of {t.counted:,} counted" if t.counted > len(t.calls) else "")
        r += 1
        pf = t.per_frame()
        if pf is not None:
            self._row(r, "Calls a frame", f"{pf:.2f}", f"over {t.frames:,.0f} frames")
            r += 1
        for key, label in (("min", "Fewest cycles"), ("mean", "Average"), ("median", "Median"), ("max", "Most")):
            v = st[key]
            self._row(r, label, f"{v:,.0f}", f"{v / line:.1f} raster lines, {100 * v / frame:.1f}% of a frame")
            r += 1
        s0, s1, e0, e1 = t.lines()
        self._row(r, "Starts", f"line {s0}" if s0 == s1 else f"lines {s0}-{s1}")
        r += 1
        self._row(r, "Ends", f"line {e0}" if e0 == e1 else f"lines {e0}-{e1}")
        self.histogram.show(t.histogram())
        self.frame.show(t)
