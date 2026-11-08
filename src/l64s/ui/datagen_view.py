"""Data Generator: byte, word or float tables from a function of x, with a graph to preview them."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from ..datagen import DataGenError, Options, Table, generate, label_ok, source  # noqa: E402
from . import textzoom  # noqa: E402
from .editor import EditorPage  # noqa: E402

EXAMPLES = ["100+99*sin(x/20)", "128+127*sin(x*2*pi/256)", "int(x*x/256)", "160+100*cos(x*pi/64)",
            "abs(64-x)", "255*(x/63)^2"]


class Graph(Gtk.DrawingArea):
    """The values against x. As in CBM prg Studio, the origin is at the top left: y grows downwards,
    like screen coordinates."""

    def __init__(self):
        super().__init__(content_height=220, hexpand=True)
        self.table: Table | None = None
        self.set_draw_func(self._draw)

    def show(self, table: Table | None):
        self.table = table
        self.queue_draw()

    def _draw(self, _w, cr, width, height):
        fg = self.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        t = self.table
        if not t or not t.xs:
            return
        m, top = textzoom.px(34), textzoom.px(14)
        lo, hi = min(0.0, min(t.ys)), max(t.ys)
        if hi == lo:
            hi = lo + 1
        x0, x1 = t.xs[0], t.xs[-1]
        w, h = width - 2 * m, height - 2 * top

        def px(x):
            return m + (x - x0) / (x1 - x0 or 1) * w

        def py(y):
            return top + (y - lo) / (hi - lo) * h        # downwards

        # axes and labels
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
        cr.set_line_width(1)
        cr.move_to(m, top)
        cr.line_to(m, top + h)
        cr.move_to(m, py(0) + 0.5)
        cr.line_to(m + w, py(0) + 0.5)
        cr.stroke()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.75)
        cr.select_font_face("Monospace")
        cr.set_font_size(textzoom.px(9))
        for text, x, y in ((f"{lo:g}", 2, top + textzoom.px(4)), (f"{hi:g}", 2, top + h), (str(x0), m, height - 2),
                           (str(x1), m + w - textzoom.px(6) * len(str(x1)), height - 2)):
            cr.move_to(x, y)
            cr.show_text(text)
        # the curve
        cr.set_source_rgb(0.30, 0.62, 1.0)
        cr.set_line_width(1.5)
        for i, (x, y) in enumerate(zip(t.xs, t.ys)):
            (cr.move_to if i == 0 else cr.line_to)(px(x), py(y))
        cr.stroke()
        if len(t.xs) <= 64:
            for x, y in zip(t.xs, t.ys):
                cr.arc(px(x), py(y), 2, 0, 6.3)
                cr.fill()


class DataGenerator(EditorPage):
    kind = "datagen"

    def __init__(self, kickass: bool = False, insert_cb=None):
        super().__init__(None)
        self.kickass = kickass
        # the syntax to write (syntax.py): the window gives a function that follows where the
        # text is going (C or ca65 in a C project); on its own, Kick or CBM as kickass says
        self.syntax = lambda: "kick" if self.kickass else "cbm"
        self.insert_cb = insert_cb
        self._text = ""
        self._ready = False

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=380,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)
        form = Gtk.Grid(column_spacing=8, row_spacing=6, margin_start=10, margin_end=6, margin_top=8, margin_bottom=8)
        paned.set_start_child(Gtk.ScrolledWindow(child=form, hscrollbar_policy=Gtk.PolicyType.NEVER))
        r = 0

        def head(text):
            nonlocal r
            form.attach(Gtk.Label(label=f"<b>{text}</b>", use_markup=True, xalign=0, margin_top=6 if r else 0),
                        0, r, 3, 1)
            r += 1

        def row(label, widget, extra=None):
            nonlocal r
            form.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            form.attach(widget, 1, r, 1 if extra else 2, 1)
            if extra:
                form.attach(extra, 2, r, 1, 1)
            r += 1

        head("Function of x")
        self.function = Gtk.Entry(text=EXAMPLES[0], hexpand=True,
                                  tooltip_text="+ - * / ^, brackets, pi, sin cos tan atn (radians), exp log sqr abs "
                                               "int sgn min max")
        self.function.connect("changed", lambda *_: self._update())
        examples = Gtk.MenuButton(icon_name="view-list-symbolic", tooltip_text="Examples")
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4, margin_top=4,
                       margin_bottom=4)
        for ex in EXAMPLES:
            b = Gtk.Button(label=ex, css_classes=["flat", "monospace"])
            b.connect("clicked", lambda _b, e=ex, p=pop: (p.popdown(), self.function.set_text(e)))
            pbox.append(b)
        pop.set_child(pbox)
        examples.set_popover(pop)
        row("y =", self.function, examples)

        def spin(lo, hi, value, step=1):
            s = Gtk.SpinButton.new_with_range(lo, hi, step)
            s.set_value(value)
            s.connect("value-changed", lambda *_: self._update())
            return s
        self.start = spin(-65535, 65535, 0)
        self.end = spin(-65535, 65535, 255)
        self.step = spin(1, 65535, 1)
        row("Start x", self.start)
        row("End x", self.end)
        row("Step", self.step)

        head("Output")
        self.types = []
        first = None
        tbox = Gtk.Box(spacing=8)
        for key, label in (("byte", "Bytes"), ("word", "Words"), ("float", "Floats")):
            b = Gtk.CheckButton(label=label, group=first)
            first = first or b
            b.connect("toggled", lambda btn: btn.get_active() and self._update())
            self.types.append((key, b))
            tbox.append(b)
        self.types[0][1].set_active(True)
        form.attach(tbox, 0, r, 3, 1)
        r += 1
        self.per_line = spin(1, 64, 8)
        row("Values per line", self.per_line)
        self.label = Gtk.Entry(placeholder_text="optional", width_chars=12)
        self.label.connect("changed", lambda *_: self._update())
        row("Label", self.label)

        def check(text, active=False, tip=None):
            nonlocal r
            c = Gtk.CheckButton(label=text, active=active, tooltip_text=tip)
            c.connect("toggled", lambda *_: self._update())
            form.attach(c, 0, r, 3, 1)
            r += 1
            return c
        self.deltas = check("As deltas", tip="Each value minus the one before (the first is as it is)")
        self.include_x = check("Include x values", tip="x, y pairs")
        self.comment = check("Add comment", True)

        head("Clamping")
        self.clamp = check("Clamp y to a range")
        self.clamp_min = spin(-1e9, 1e9, 0)
        self.clamp_max = spin(-1e9, 1e9, 255)
        row("Min y", self.clamp_min)
        row("Max y", self.clamp_max)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=8, margin_top=8,
                        margin_bottom=8)
        self.graph = Graph()
        right.append(self.graph)
        self.summary = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.summary)
        self.code = Gtk.TextView(editable=False, monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                 css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.code, vexpand=True, min_content_height=120))
        btns = Gtk.Box(spacing=6)
        cp = Gtk.Button(label="Copy")
        cp.connect("clicked", lambda *_: self._copy())
        btns.append(cp)
        ins = Gtk.Button(label="Insert into Editor", css_classes=["suggested-action"],
                         tooltip_text="Insert at the cursor in the last source file used")
        ins.connect("clicked", lambda *_: self._insert())
        btns.append(ins)
        right.append(btns)
        paned.set_end_child(right)

        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"])
        self.append(self.status)
        self._ready = True
        self._update()

    @property
    def title(self) -> str:
        return "Data Generator"

    def save(self) -> None:
        pass

    def options(self) -> Options:
        return Options(function=self.function.get_text(), start=self.start.get_value_as_int(),
                       end=self.end.get_value_as_int(), step=self.step.get_value_as_int(),
                       type=next(k for k, b in self.types if b.get_active()), deltas=self.deltas.get_active(),
                       include_x=self.include_x.get_active(), clamp=self.clamp.get_active(),
                       clamp_min=self.clamp_min.get_value(), clamp_max=self.clamp_max.get_value(),
                       per_line=self.per_line.get_value_as_int(), comment=self.comment.get_active(),
                       label=self.label.get_text().strip(), kickass=self.kickass,
                       syntax=self.syntax())

    def _update(self):
        if not self._ready:
            return
        self.clamp_min.set_sensitive(self.clamp.get_active())
        self.clamp_max.set_sensitive(self.clamp.get_active())
        opts = self.options()
        try:
            if opts.label and not label_ok(opts.label):
                raise DataGenError(f"'{opts.label}' isn't a valid label name")
            table = generate(opts)
            self._text = source(opts, table)
        except DataGenError as e:
            self._text = ""
            self.graph.show(None)
            self.code.get_buffer().set_text("")
            self.summary.set_text("")
            self.status.set_text(str(e))
            return
        self.graph.show(table)
        size = len(table.xs) * (1 + opts.include_x) * {"byte": 1, "word": 2, "float": 5}[opts.type]
        self.summary.set_text(f"{len(table.xs)} values, y from {min(table.ys):g} to {max(table.ys):g}: {size} bytes")
        self.code.get_buffer().set_text(self._text)
        self.status.set_text("")

    def _copy(self):
        if self._text:
            Gdk.Display.get_default().get_clipboard().set(self._text)
            self.status.set_text("Copied the data")

    def _insert(self):
        if not self._text or not self.insert_cb:
            return
        where = self.insert_cb(self._text)
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")
