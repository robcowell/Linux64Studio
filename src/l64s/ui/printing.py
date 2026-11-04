"""Printing source files (CBM prg Studio's File → Print and Print Preview).

The text is printed with its syntax colours, from a copy in a light colour scheme (so a dark
editor theme doesn't come out pale on paper) and with folded regions printed in full. A header
gives the file name and "Page n of N", a footer the date. The print dialog's Source tab turns line
numbers (on for assembler, off for BASIC, which has its own), colours, wrapping and the header on
or off. Print Preview makes the pages as a PDF and opens it in the PDF viewer.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gio, GLib, Gtk, GtkSource, Pango  # noqa: E402

LIGHT_SCHEMES = ("Adwaita", "classic", "kate", "tango")


class SourcePrinter:
    def __init__(self, editor, settings=None):
        self.editor = editor
        self.settings = settings
        self.line_numbers = not editor.is_basic
        self.colours = True
        self.wrap = True
        self.header = True
        self.compositor = None

    def _buffer(self) -> GtkSource.Buffer:
        """A copy of the text to print: whole (no folds), in a light colour scheme."""
        src = self.editor.buffer
        buf = GtkSource.Buffer()
        if hasattr(src, "get_language") and src.get_language():
            buf.set_language(src.get_language())
        sm = GtkSource.StyleSchemeManager.get_default()
        for sid in LIGHT_SCHEMES:
            scheme = sm.get_scheme(sid)
            if scheme:
                buf.set_style_scheme(scheme)
                break
        buf.set_text(src.get_text(src.get_start_iter(), src.get_end_iter(), True))
        buf.ensure_highlight(buf.get_start_iter(), buf.get_end_iter())
        return buf

    def operation(self) -> Gtk.PrintOperation:
        op = Gtk.PrintOperation(job_name=self.editor.title, embed_page_setup=True)
        op.connect("begin-print", self._begin)
        op.connect("paginate", self._paginate)
        op.connect("draw-page", self._draw)
        op.connect("create-custom-widget", self._custom_widget)
        op.connect("custom-widget-apply", self._custom_apply)
        op.set_custom_tab_label("Source")
        return op

    # ---------------------------------------------------------------- the print operation
    def _begin(self, _op, _ctx):
        c = GtkSource.PrintCompositor.new(self._buffer())
        font = Pango.FontDescription.from_string(getattr(self.settings, "font", "") or "Monospace 11")
        size = max(7, min(10, (font.get_size() // Pango.SCALE) or 10))
        family = font.get_family() or "Monospace"
        c.set_body_font_name(f"{family} {size}")
        c.set_line_numbers_font_name(f"{family} {size - 1}")
        c.set_header_font_name(f"Sans {size}")
        c.set_footer_font_name(f"Sans {size - 1}")
        c.set_tab_width(getattr(self.settings, "tab_width", 8) or 8)
        c.set_highlight_syntax(self.colours)
        c.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if self.wrap else Gtk.WrapMode.NONE)
        c.set_print_line_numbers(1 if self.line_numbers else 0)
        if self.header:
            path = self.editor.path
            c.set_print_header(True)
            c.set_header_format(True, path.name if path else self.editor.title, None, "Page %N of %Q")
            c.set_print_footer(True)
            c.set_footer_format(True, str(path.parent) if path else "", None, time.strftime("%d %B %Y"))
        self.compositor = c

    def _paginate(self, op, ctx):
        if self.compositor.paginate(ctx):
            op.set_n_pages(self.compositor.get_n_pages())
            return True
        return False

    def _draw(self, _op, ctx, page):
        self.compositor.draw_page(ctx, page)

    def _custom_widget(self, _op):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=12, margin_top=12)
        self._checks = {}
        for key, label in (("line_numbers", "Line numbers"), ("colours", "Syntax colours"),
                           ("wrap", "Wrap long lines"), ("header", "Header and footer (file name, pages, date)")):
            c = Gtk.CheckButton(label=label, active=getattr(self, key))
            box.append(c)
            self._checks[key] = c
        return box

    def _custom_apply(self, _op, _widget):
        for key, c in self._checks.items():
            setattr(self, key, c.get_active())

    # ---------------------------------------------------------------- doing it
    def print_(self, parent) -> Gtk.PrintOperationResult:
        try:
            return self.operation().run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
        except GLib.Error:
            return Gtk.PrintOperationResult.ERROR

    def export_pdf(self, path: Path) -> bool:
        op = self.operation()
        op.set_export_filename(str(path))
        try:
            return op.run(Gtk.PrintOperationAction.EXPORT, None) == Gtk.PrintOperationResult.APPLY
        except GLib.Error:
            return False

    def preview(self) -> Path | None:
        """The pages as a PDF, opened in the PDF viewer."""
        stem = self.editor.path.stem if self.editor.path else "source"
        out = Path(tempfile.mkdtemp(prefix="l64s-print-")) / f"{stem}.pdf"
        if not self.export_pdf(out):
            return None
        try:
            Gio.AppInfo.launch_default_for_uri(out.as_uri(), None)
        except GLib.Error:
            pass
        return out
