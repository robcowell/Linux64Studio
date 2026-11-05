"""Path → Generate Data: turn the screen's path into movement data (CBM prg Studio's dialog),
previewed as the options change, then copied or put into the last source file."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..gfx.paths import GenOptions, PathError, generate  # noqa: E402

OUTPUTS = [("bytes", "Assembler bytes"), ("words", "Assembler words"), ("basic", "BASIC DATA lines")]


class PathGenerateDialog(Adw.Window):
    def __init__(self, parent, path, kickass: bool, insert=None, settings=None, syntax=None):
        # syntax(): what to write (syntax.py) when it's C or ca65 (a C project); else the checkbox decides
        self.syntax = syntax or (lambda: "")
        super().__init__(transient_for=parent, modal=False, title="Generate Path Data", default_width=860,
                         default_height=560)
        self.path = path
        self.insert = insert              # MainWindow._insert_into_last_source, or None
        self.text = ""
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        copy = Gtk.Button(label="Copy")
        copy.connect("clicked", lambda *_: Gdk.Display.get_default().get_clipboard().set(self.text))
        hb.pack_end(copy)
        if insert:
            ins = Gtk.Button(label="Insert into Editor", css_classes=["suggested-action"])
            ins.connect("clicked", lambda *_: self._insert())
            hb.pack_end(ins)
        body = Gtk.Box(spacing=16, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)
        form = Gtk.Grid(column_spacing=8, row_spacing=6, valign=Gtk.Align.START)
        body.append(Gtk.ScrolledWindow(child=form, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       propagate_natural_width=True))
        self._r = 0

        def add(label, w, tip=None):
            lab = Gtk.Label(label=label, xalign=0)
            if tip:
                lab.set_tooltip_text(tip)
                w.set_tooltip_text(tip)
            form.attach(lab, 0, self._r, 1, 1)
            form.attach(w, 1, self._r, 1, 1)
            self._r += 1

        def heading(text):
            form.attach(Gtk.Label(label=f"<b>{text}</b>", use_markup=True, xalign=0, margin_top=6), 0, self._r, 2, 1)
            self._r += 1

        def spin(lo, hi, v):
            s = Gtk.SpinButton.new_with_range(lo, hi, 1)
            s.set_value(v)
            s.connect("value-changed", lambda *_: self._update())
            return s

        def check(label, active=False):
            c = Gtk.CheckButton(label=label, active=active)
            c.connect("toggled", lambda *_: self._update())
            form.attach(c, 0, self._r, 2, 1)
            self._r += 1
            return c

        def entry(text):
            e = Gtk.Entry(text=text)
            e.connect("changed", lambda *_: self._update())
            return e

        heading("Lines")
        self.step = spin(1, 64, 4)
        add("A point every", self.step, "Pixels between points along each line (1 makes a lot of data)")
        lines = max(1, path.lines)
        self.first = spin(1, lines, 1)
        self.last = spin(1, lines, lines)
        add("From line", self.first)
        add("To line", self.last)
        self.only = check("Only the path's own points (no points between)")
        heading("Generate as")
        self.layout = Gtk.DropDown.new_from_strings(["x, y pairs", "x table, then y table"])
        self.layout.connect("notify::selected", lambda *_: self._update())
        add("Layout", self.layout)
        heading("Transform")
        self.fx = entry("x")
        self.fy = entry("y")
        add("x =", self.fx, "A function of x, e.g. x+24 (sprite coordinates), x*2, (x+5)/2, or a number")
        add("y =", self.fy, "A function of y, e.g. y+50")
        sprite = Gtk.Button(label="Sprite Coordinates")
        xo = getattr(settings, "digitiser_x_offset", 24)
        yo = getattr(settings, "digitiser_y_offset", 50)
        sprite.set_tooltip_text(f"x+{xo}, y+{yo}: where a sprite must be for its top left to be on the point "
                                f"(the digitiser's offsets)")
        sprite.connect("clicked", lambda *_: (self.fx.set_text(f"x+{xo}"), self.fy.set_text(f"y+{yo}")))
        form.attach(sprite, 1, self._r, 1, 1)
        self._r += 1
        heading("Output")
        self.output = Gtk.DropDown.new_from_strings([o[1] for o in OUTPUTS])
        self.output.connect("notify::selected", lambda *_: self._update())
        add("As", self.output)
        self.label = entry("path")
        add("Label", self.label)
        self.kick = check("Kick Assembler syntax", kickass)
        if self.syntax() in ("c", "ca65"):          # a C project: C, or ca65 for an assembler file
            self.kick.set_label(f"{'C' if self.syntax() == 'c' else 'ca65'} (the project's language)")
            self.kick.set_active(False)
            self.kick.set_sensitive(False)
        self.basic_start = spin(0, 63999, 1000)
        self.basic_step = spin(1, 1000, 10)
        add("BASIC: start line", self.basic_start)
        add("BASIC: increment", self.basic_step)
        self.per_line = spin(1, 32, 8)
        add("Points a line", self.per_line, "For BASIC, 8 or fewer keeps lines short enough to type in")
        self.comments = check("Add comments", True)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        body.append(right)
        self.preview = Gtk.TextView(editable=False, monospace=True, vexpand=True)
        right.append(Gtk.ScrolledWindow(child=self.preview, vexpand=True))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.status)
        self._update()

    def options(self) -> GenOptions:
        return GenOptions(step=int(self.step.get_value()), first=int(self.first.get_value()),
                          last=int(self.last.get_value()), only_points=self.only.get_active(),
                          separate=self.layout.get_selected() == 1, fx=self.fx.get_text(), fy=self.fy.get_text(),
                          output=OUTPUTS[self.output.get_selected()][0], label=self.label.get_text().strip(),
                          kickass=self.kick.get_active(), syntax=self.syntax() if self.syntax() in ("c", "ca65") else "",
                          basic_start=int(self.basic_start.get_value()),
                          basic_step=int(self.basic_step.get_value()), per_line=int(self.per_line.get_value()),
                          comments=self.comments.get_active())

    def _update(self):
        try:
            self.text, warnings = generate(self.path, self.options())
        except PathError as e:
            self.text, warnings = "", []
            self.status.set_text(str(e))
            self.status.set_css_classes(["error"])
        else:
            n = self.text.count("\n")
            self.status.set_text("  ".join(warnings) or f"{n} line{'s' if n != 1 else ''}")
            self.status.set_css_classes(["warning"] if warnings else ["dim-label"])
        self.preview.get_buffer().set_text(self.text)

    def _insert(self):
        if not self.text:
            return
        where = self.insert(self.text)
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")
