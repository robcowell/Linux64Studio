"""Editor pages. Every tab in the main window is an EditorPage subclass."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk, Pango  # noqa: E402

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource  # noqa: E402
    HAVE_SOURCEVIEW = True
except (ValueError, ImportError):
    GtkSource = None
    HAVE_SOURCEVIEW = False

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Short help shown when hovering over a directive (CBM prg Studio shows similar tooltips).
DIRECTIVE_HELP = {
    "byte": "byte <value>[, <value>...]\nDefine bytes. Quoted strings give screen codes.",
    "word": "word <value>[, ...]\nDefine 16-bit words, low byte first.",
    "text": "text 'string'\nDefine a string as screen codes ('a' = 1).",
    "dcb": "dcb <count>, <value>\nDefine a block of <count> bytes, all <value>.",
    "incbin": "incbin <file>\nInclude a binary file. Quotes are optional.",
    "incasm": "incasm \"file\"\nInclude another source file here.",
    "operator": "Operator Calc | HiLo\nCalc: <A+1 means <(A+1).  HiLo (default): (<A)+1.",
    "defm": "defm NAME ... endm\nDefine a macro. Parameters are /1 to /9; @labels are local to each use.",
    "endm": "End of a macro definition.",
    "align": "align <n>\nPad to the next multiple of n.",
    "if": "if <expr> ... [else ...] endif\nConditional assembly.",
}


class EditorPage(Gtk.Box):
    """Base class: something with a file that can be modified and saved."""

    __gsignals__ = {"modified-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    kind = "file"

    def __init__(self, path: Path | None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.path = path
        self._modified = False

    @property
    def title(self) -> str:
        return self.path.name if self.path else "Untitled"

    @property
    def modified(self) -> bool:
        return self._modified

    def set_modified(self, value: bool):
        if value != self._modified:
            self._modified = value
            self.emit("modified-changed")

    def save(self) -> None:
        raise NotImplementedError

    def save_as(self, path: Path) -> None:
        self.path = path
        self.save()


class SourceEditor(EditorPage):
    kind = "source"

    __gsignals__ = {"breakpoints-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, path: Path | None, settings):
        super().__init__(path)
        self.settings = settings
        if HAVE_SOURCEVIEW:
            self.buffer = GtkSource.Buffer()
            self.view = GtkSource.View(buffer=self.buffer, show_line_numbers=True, highlight_current_line=True,
                                       auto_indent=True, show_line_marks=True, smart_backspace=True)
            lm = GtkSource.LanguageManager.get_default()
            lm.set_search_path([str(DATA_DIR)] + list(lm.get_search_path()))
            lang = lm.get_language("cbmasm")
            if lang:
                self.buffer.set_language(lang)
            self._setup_marks()
            self._apply_scheme()
            Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self._apply_scheme())
            self.view.connect("line-mark-activated", self._on_line_mark_activated)
            self.view.set_tab_width(settings.tab_width)
            self.view.set_insert_spaces_instead_of_tabs(settings.insert_spaces)
        else:
            self.buffer = Gtk.TextBuffer()
            self.view = Gtk.TextView(buffer=self.buffer)
        self.view.set_monospace(True)
        self.view.set_left_margin(6)
        self.view.set_top_margin(4)
        self._apply_font(settings.font)

        self.pc_tag = self.buffer.create_tag("pc-line", paragraph_background="rgba(255,200,0,0.30)")
        self.error_tag = self.buffer.create_tag("error-line", underline=Pango.Underline.ERROR)
        self.bp_tag = self.buffer.create_tag("bp-line", paragraph_background="rgba(220,40,40,0.18)")
        self.pc_tag.set_priority(self.buffer.get_tag_table().get_size() - 1)  # PC highlight wins over breakpoints
        self._breakpoints: list[Gtk.TextMark] = []

        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroller.set_child(self.view)
        self.append(scroller)

        if path and path.exists():
            self._load(path)
        self.buffer.connect("modified-changed", lambda b: self.set_modified(b.get_modified()))

        self.view.set_has_tooltip(True)
        self.view.connect("query-tooltip", self._on_tooltip)

    # ---------------------------------------------------------------- appearance
    def _apply_font(self, font: str):
        desc = Pango.FontDescription.from_string(font or "Monospace 11")
        css = Gtk.CssProvider()
        family = desc.get_family() or "Monospace"
        size = desc.get_size() / Pango.SCALE if desc.get_size() else 11
        css.load_from_data(f"textview {{ font-family: '{family}'; font-size: {size}pt; }}".encode())
        self.view.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _apply_scheme(self):
        sm = GtkSource.StyleSchemeManager.get_default()
        dark = Adw.StyleManager.get_default().get_dark()
        for sid in (["Adwaita-dark", "oblivion", "classic-dark"] if dark else ["Adwaita", "classic"]):
            scheme = sm.get_scheme(sid)
            if scheme:
                self.buffer.set_style_scheme(scheme)
                break

    def _setup_marks(self):
        bp = GtkSource.MarkAttributes()
        bp.set_icon_name("media-record-symbolic")
        self.view.set_mark_attributes("breakpoint", bp, 10)
        err = GtkSource.MarkAttributes()
        err.set_icon_name("dialog-error-symbolic")
        self.view.set_mark_attributes("error", err, 5)
        pc = GtkSource.MarkAttributes()
        pc.set_icon_name("go-next-symbolic")
        self.view.set_mark_attributes("pc", pc, 20)

    # ---------------------------------------------------------------- file io
    def _load(self, path: Path):
        data = path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
        if HAVE_SOURCEVIEW:
            self.buffer.begin_irreversible_action()
        self.buffer.set_text(text)
        if HAVE_SOURCEVIEW:
            self.buffer.end_irreversible_action()
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.buffer.set_modified(False)

    def get_text(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)

    def save(self):
        if not self.path:
            raise ValueError("No file name")
        text = self.get_text()
        # Keep Windows line endings if the file had them (the book's files do).
        try:
            if b"\r\n" in self.path.read_bytes()[:4096]:
                text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        except OSError:
            pass
        self.path.write_text(text, newline="")
        self.buffer.set_modified(False)

    def reload(self):
        if self.path and self.path.exists():
            self._load(self.path)

    # ---------------------------------------------------------------- navigation
    def goto_line(self, line: int, select: bool = True):
        ok, it = self.buffer.get_iter_at_line(max(0, line - 1))
        if not ok:
            return
        self.buffer.place_cursor(it)
        if select:
            end = it.copy()
            end.forward_to_line_end()
            self.buffer.select_range(it, end)
        GLib.idle_add(lambda: (self.view.scroll_to_iter(it, 0.2, True, 0, 0.4), False)[1])
        self.view.grab_focus()

    def current_line(self) -> int:
        it = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return it.get_line() + 1

    # ---------------------------------------------------------------- diagnostics
    def clear_errors(self):
        self.buffer.remove_tag(self.error_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
        if HAVE_SOURCEVIEW:
            self.buffer.remove_source_marks(self.buffer.get_start_iter(), self.buffer.get_end_iter(), "error")

    def mark_error(self, line: int):
        ok, it = self.buffer.get_iter_at_line(max(0, line - 1))
        if not ok:
            return
        end = it.copy()
        end.forward_to_line_end()
        self.buffer.apply_tag(self.error_tag, it, end)
        if HAVE_SOURCEVIEW:
            self.buffer.create_source_mark(None, "error", it)

    # ---------------------------------------------------------------- debugger
    def set_pc_line(self, line: int | None):
        self.buffer.remove_tag(self.pc_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
        if HAVE_SOURCEVIEW:
            self.buffer.remove_source_marks(self.buffer.get_start_iter(), self.buffer.get_end_iter(), "pc")
        if line:
            ok, it = self.buffer.get_iter_at_line(line - 1)
            if ok:
                end = it.copy()
                end.forward_line()
                self.buffer.apply_tag(self.pc_tag, it, end)
                if HAVE_SOURCEVIEW:
                    self.buffer.create_source_mark(None, "pc", it)
                self.goto_line(line, select=False)

    def breakpoint_lines(self) -> list[int]:
        lines = sorted({self.buffer.get_iter_at_mark(m).get_line() + 1 for m in self._breakpoints})
        return lines

    def toggle_breakpoint(self, line: int | None = None):
        line = line or self.current_line()
        for m in list(self._breakpoints):
            if self.buffer.get_iter_at_mark(m).get_line() + 1 == line:
                self._remove_bp(m)
                self.emit("breakpoints-changed")
                return
        ok, it = self.buffer.get_iter_at_line(line - 1)
        if not ok:
            return
        if HAVE_SOURCEVIEW:
            m = self.buffer.create_source_mark(None, "breakpoint", it)
        else:
            m = self.buffer.create_mark(None, it, True)
        self._breakpoints.append(m)
        end = it.copy()
        end.forward_line()
        self.buffer.apply_tag(self.bp_tag, it, end)
        self.emit("breakpoints-changed")

    def _remove_bp(self, m):
        it = self.buffer.get_iter_at_mark(m)
        end = it.copy()
        end.forward_line()
        self.buffer.remove_tag(self.bp_tag, it, end)
        self._breakpoints.remove(m)
        self.buffer.delete_mark(m)

    def _on_line_mark_activated(self, _view, it, button, _state, n_presses):
        if button == 1 and n_presses == 1:
            self.toggle_breakpoint(it.get_line() + 1)

    # ---------------------------------------------------------------- hover help
    def _on_tooltip(self, view, x, y, _keyboard, tooltip):
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, x, y)
        ok, it = view.get_iter_at_location(bx, by)
        if not ok:
            return False
        start = it.copy()
        while not start.starts_line():
            start.backward_char()
            if not (start.get_char().isalnum() or start.get_char() == "_"):
                start.forward_char()
                break
        end = it.copy()
        while end.get_char().isalnum() or end.get_char() == "_":
            end.forward_char()
        word = self.buffer.get_text(start, end, False).lower()
        help_text = DIRECTIVE_HELP.get(word)
        if help_text:
            tooltip.set_text(help_text)
            return True
        return False
