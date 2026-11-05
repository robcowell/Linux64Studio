"""String Formatter: split long strings into lines for BASIC or assembler, and change their case."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .. import strformat as sf  # noqa: E402
from .editor import EditorPage  # noqa: E402

EXAMPLE = ("{clear}{white}welcome to the caves of doom. you have three lives and one torch. "
           "press fire to begin your quest!")


class StringFormatter(EditorPage):
    kind = "strformat"

    def __init__(self, kickass: bool = False, insert_cb=None, get_target=None):
        super().__init__(None)
        self.kickass = kickass
        # the syntax to write (syntax.py): the window gives a function that follows where the
        # text is going (C or ca65 in a C project); on its own, Kick or CBM as kickass says
        self.syntax = lambda: "kick" if self.kickass else "cbm"
        self.insert_cb = insert_cb
        self.get_target = get_target
        self._text = ""
        self._ready = False

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=360,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)
        form = Gtk.Grid(column_spacing=8, row_spacing=6, margin_start=10, margin_end=6, margin_top=8, margin_bottom=8)
        paned.set_start_child(Gtk.ScrolledWindow(child=form, hscrollbar_policy=Gtk.PolicyType.NEVER))
        r = 0

        def head(text):
            nonlocal r
            form.attach(Gtk.Label(label=f"<b>{text}</b>", use_markup=True, xalign=0, margin_top=6 if r else 0),
                        0, r, 2, 1)
            r += 1

        def row(label, widget):
            nonlocal r
            form.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            form.attach(widget, 1, r, 1, 1)
            r += 1

        def spin(lo, hi, value, step=1):
            s = Gtk.SpinButton.new_with_range(lo, hi, step)
            s.set_value(value)
            s.connect("value-changed", lambda *_: self._update())
            return s

        def check(text, active, tip=None):
            nonlocal r
            c = Gtk.CheckButton(label=text, active=active, tooltip_text=tip)
            c.connect("toggled", lambda *_: self._update())
            form.attach(c, 0, r, 2, 1)
            r += 1
            return c

        head("Lines")
        self.width = spin(1, 200, 30)
        row("Characters per line", self.width)
        self.words = check("Keep words together", True, "End each line after a space where possible")
        head("Output")
        self.kind_box = Gtk.DropDown.new_from_strings(["BASIC", "Assembler"])
        self.kind_box.connect("notify::selected", lambda *_: self._update())
        row("As", self.kind_box)

        self.basic_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.variable = Gtk.Entry(text="a$", width_chars=6)
        self.variable.connect("changed", lambda *_: self._update())
        self.start = spin(0, 63999, 10)
        self.step = spin(1, 1000, 10)
        self.initialise = Gtk.CheckButton(label="Initialise", active=True,
                                          tooltip_text='The first line sets the variable (a$="…"); without this every '
                                                       'line adds to it (a$=a$+"…")')
        self.initialise.connect("toggled", lambda *_: self._update())
        for i, (label, w) in enumerate((("Variable", self.variable), ("Start line", self.start), ("Step", self.step))):
            self.basic_grid.attach(Gtk.Label(label=label, xalign=0), 0, i, 1, 1)
            self.basic_grid.attach(w, 1, i, 1, 1)
        self.basic_grid.attach(self.initialise, 0, 3, 2, 1)
        form.attach(self.basic_grid, 0, r, 2, 1)
        r += 1

        self.asm_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.code_box = Gtk.DropDown.new_from_strings(['PETSCII (double quotes)', "Screen codes (single quotes)"])
        self.code_box.set_tooltip_text("PETSCII for printing with CHROUT; screen codes for writing to screen memory")
        self.code_box.connect("notify::selected", lambda *_: self._update())
        self.label = Gtk.Entry(placeholder_text="optional", width_chars=12)
        self.label.connect("changed", lambda *_: self._update())
        self.asm_grid.attach(Gtk.Label(label="Codes", xalign=0), 0, 0, 1, 1)
        self.asm_grid.attach(self.code_box, 1, 0, 1, 1)
        self.asm_grid.attach(Gtk.Label(label="Label", xalign=0), 0, 1, 1, 1)
        self.asm_grid.attach(self.label, 1, 1, 1, 1)
        form.attach(self.asm_grid, 0, r, 2, 1)
        r += 1

        head("Convert")
        cases = Gtk.Box(spacing=4)
        for label, fn in (("Upper", sf.upper), ("Lower", sf.lower), ("Mixed", sf.mixed)):
            b = Gtk.Button(label=label, tooltip_text=f"{label} case (control codes are left alone)")
            b.connect("clicked", lambda _b, fn=fn: self._convert(fn))
            cases.append(b)
        form.attach(cases, 0, r, 2, 1)
        r += 1
        self.pattern = Gtk.Entry(placeholder_text="Regular expression")
        self.repl = Gtk.Entry(placeholder_text="Replace with")
        row("Find", self.pattern)
        row("Replace", self.repl)
        rx = Gtk.Box(spacing=4)
        fb = Gtk.Button(label="Find")
        fb.connect("clicked", lambda *_: self._find())
        self.pattern.connect("activate", lambda *_: self._find())
        rb = Gtk.Button(label="Replace All")
        rb.connect("clicked", lambda *_: self._replace())
        rx.append(fb)
        rx.append(rb)
        form.attach(rx, 0, r, 2, 1)
        r += 1
        form.attach(Gtk.Label(label="Lower case letters are the C64's normal letters; capitals are the shifted "
                                    "ones. Write control codes as {white}, {clear}, {3 down}.",
                              xalign=0, wrap=True, max_width_chars=40, css_classes=["dim-label"], margin_top=6),
                    0, r, 2, 1)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=8, margin_top=8,
                        margin_bottom=8)
        srow = Gtk.Box(spacing=6)
        srow.append(Gtk.Label(label="<b>Source</b>", use_markup=True, xalign=0, hexpand=True))
        self.length = Gtk.Label(xalign=1, css_classes=["dim-label"])
        srow.append(self.length)
        right.append(srow)
        self.source = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True, top_margin=6, bottom_margin=6,
                                   left_margin=6, css_classes=["card", "monospace"])
        self.source.get_buffer().set_text(EXAMPLE)
        self.source.get_buffer().connect("changed", lambda *_: self._update())
        right.append(Gtk.ScrolledWindow(child=self.source, vexpand=True, min_content_height=100))
        right.append(Gtk.Label(label="<b>Output</b>", use_markup=True, xalign=0))
        self.output = Gtk.TextView(editable=False, monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                   css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.output, vexpand=True, min_content_height=140))
        btns = Gtk.Box(spacing=6)
        cp = Gtk.Button(label="Copy")
        cp.connect("clicked", lambda *_: self._copy())
        btns.append(cp)
        ins = Gtk.Button(label="Insert into Editor", css_classes=["suggested-action"])
        ins.connect("clicked", lambda *_: self._insert())
        btns.append(ins)
        right.append(btns)
        paned.set_end_child(right)

        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"])
        self.append(self.status)
        self._ready = True
        self.follow_target()

    @property
    def title(self) -> str:
        return "String Formatter"

    def save(self) -> None:
        pass

    def follow_target(self):
        """BASIC output if the last file edited is BASIC, else assembler (as CBM prg Studio does)."""
        t = self.get_target() if self.get_target else None
        self.kind_box.set_selected(0 if t is not None and t.is_basic else 1)
        self._update()

    def text(self) -> str:
        b = self.source.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def options(self) -> sf.Options:
        return sf.Options(width=self.width.get_value_as_int(), words=self.words.get_active(),
                          start_line=self.start.get_value_as_int(), step=self.step.get_value_as_int(),
                          variable=self.variable.get_text(), initialise=self.initialise.get_active(),
                          petscii=self.code_box.get_selected() == 0, label=self.label.get_text().strip(),
                          kickass=self.kickass, syntax=self.syntax())

    @property
    def is_basic(self) -> bool:            # what this page produces (used when inserting)
        return self.kind_box.get_selected() == 0

    def _update(self):
        if not self._ready:
            return
        basic = self.is_basic
        self.basic_grid.set_visible(basic)
        self.asm_grid.set_visible(not basic)
        text = self.text()
        try:
            self.length.set_text(f"{sf.length(text)} characters")
            if basic:
                self._text, warnings = sf.basic(text, self.options())
            else:
                self._text, warnings = sf.assembler(text, self.options()), []
        except sf.FormatError as e:
            self._text = ""
            self.output.get_buffer().set_text("")
            self.status.set_text(str(e))
            return
        self.output.get_buffer().set_text(self._text)
        self.status.set_text("; ".join(warnings))

    def _convert(self, fn):
        try:
            new = fn(self.text())
        except sf.FormatError as e:
            self.status.set_text(str(e))
            return
        self._set_source(new)

    def _set_source(self, new: str):
        """Replace the source text as one undo step."""
        b = self.source.get_buffer()
        b.begin_user_action()
        b.delete(b.get_start_iter(), b.get_end_iter())
        b.insert(b.get_start_iter(), new)
        b.end_user_action()

    def _find(self):
        pat = self.pattern.get_text()
        if not pat:
            return
        try:
            matches = sf.find(self.text(), pat)
        except sf.FormatError as e:
            self.status.set_text(str(e))
            return
        if not matches:
            self.status.set_text("No matches.")
            return
        b = self.source.get_buffer()
        m = matches[0]
        b.select_range(b.get_iter_at_offset(m.position), b.get_iter_at_offset(m.position + len(m.text)))
        shown = ", ".join(f"'{x.text}' at {x.position}" for x in matches[:5])
        self.status.set_text(f"{len(matches)} match{'es' if len(matches) != 1 else ''}: {shown}"
                             + ("…" if len(matches) > 5 else ""))

    def _replace(self):
        pat = self.pattern.get_text()
        if not pat:
            return
        try:
            new, n = sf.replace(self.text(), pat, self.repl.get_text())
        except (sf.FormatError, IndexError) as e:
            self.status.set_text(f"Couldn't replace: {e}")
            return
        if n:
            self._set_source(new)
        self.status.set_text(f"Replaced {n} match{'es' if n != 1 else ''}" if n else "No matches.")

    def _copy(self):
        if self._text:
            Gdk.Display.get_default().get_clipboard().set(self._text)
            self.status.set_text("Copied the output")

    def _insert(self):
        if not self._text or not self.insert_cb:
            return
        t = self.get_target() if self.get_target else None
        if t is not None and t.is_basic != self.is_basic:
            self.status.set_text(f"{t.title} is {'BASIC' if t.is_basic else 'assembler'}: choose that output, "
                                 f"or use Copy")
            return
        where = self.insert_cb(self._text)
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")
