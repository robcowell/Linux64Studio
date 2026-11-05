"""Editor pages. Every tab in the main window is an EditorPage subclass."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .. import numconv  # noqa: E402

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
    def is_basic(self) -> bool:
        return bool(self.path) and self.path.suffix.lower() in (".bas", ".pbas")

    @property
    def is_c(self) -> bool:
        """C source or header (a cc65 project's)."""
        return bool(self.path) and self.path.suffix.lower() in (".c", ".h")

    @property
    def is_pbasic(self) -> bool:
        return bool(self.path) and self.path.suffix.lower() == ".pbas"

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

    def __init__(self, path: Path | None, settings, ca65: bool = False):
        super().__init__(path)
        self.settings = settings
        # an assembler file of a C project: ca65's syntax, not CBM prg Studio's
        self.ca65 = ca65 and bool(path) and path.suffix.lower() in (".s", ".asm", ".inc", ".a")
        if HAVE_SOURCEVIEW:
            self.buffer = GtkSource.Buffer()
            self.view = GtkSource.View(buffer=self.buffer, show_line_numbers=True, highlight_current_line=True,
                                       auto_indent=True, show_line_marks=True, smart_backspace=True)
            lm = GtkSource.LanguageManager.get_default()
            if str(DATA_DIR) not in lm.get_search_path():      # it can only be set before any language loads
                lm.set_search_path([str(DATA_DIR)] + list(lm.get_search_path()))
            sfx = path.suffix.lower() if path else ""
            lang = lm.get_language("cbmbasic" if sfx in (".bas", ".pbas") else "c" if sfx in (".c", ".h")
                                   else "ca65" if self.ca65 else "cbmasm")
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
        self.set_word_wrap(getattr(settings, "word_wrap", False))

        self.pc_tag = self.buffer.create_tag("pc-line", paragraph_background="rgba(255,200,0,0.30)")
        self.error_tag = self.buffer.create_tag("error-line", underline=Pango.Underline.ERROR)
        self.bp_tag = self.buffer.create_tag("bp-line", paragraph_background="rgba(220,40,40,0.18)")
        self.bp_off_tag = self.buffer.create_tag("bp-off-line", paragraph_background="rgba(128,128,128,0.12)")
        self.pc_tag.set_priority(self.buffer.get_tag_table().get_size() - 1)  # PC highlight wins over breakpoints
        self._breakpoints: list[Gtk.TextMark] = []
        self._bp_off: set[Gtk.TextMark] = set()        # breakpoints switched off (kept, but not stopping)

        self.find_bar = None
        if HAVE_SOURCEVIEW:                 # Find and Replace (Ctrl+F, Ctrl+H) across the top
            from .find_bar import FindBar
            self.find_bar = FindBar(self.view)
            self.append(self.find_bar)
        scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        scroller.set_child(self.view)
        self.append(scroller)

        if path and path.exists():
            self._load(path)
        self.buffer.connect("modified-changed", lambda b: self.set_modified(b.get_modified()))

        self.view.set_has_tooltip(True)
        self.view.connect("query-tooltip", self._on_tooltip)
        self._setup_convert_menu()
        from .completion import CompletionPopup
        self.completion = CompletionPopup(self.view, self._completion_candidates,
                                          lambda: getattr(self.settings, "auto_complete", True), lambda: self.is_c)
        # Ctrl+click: go to the definition of the name clicked
        ctrl_click = Gtk.GestureClick(button=1)
        ctrl_click.connect("released", self._on_left_click)
        self.view.add_controller(ctrl_click)
        typing = Gtk.EventControllerKey()
        typing.connect("key-pressed", self._forget_click)
        self.view.add_controller(typing)
        # BASIC: Return at the end of a line starts the next numbered line (after the completion
        # list, which takes Return itself when it's open)
        numbering = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        numbering.connect("key-pressed", self._basic_return)
        self.view.add_controller(numbering)
        from .folding import Folding
        self.folding = Folding(self.view, self.buffer)
        fold_keys = Gtk.EventControllerKey()
        fold_keys.connect("key-pressed", self._fold_key)
        self.view.add_controller(fold_keys)

    # ---------------------------------------------------------------- appearance
    def set_word_wrap(self, on: bool):
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if on else Gtk.WrapMode.NONE)

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
        off = GtkSource.MarkAttributes()
        off.set_icon_name("radio-symbolic")              # a hollow circle: there, but switched off
        self.view.set_mark_attributes("breakpoint-off", off, 9)
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

    def replace_text(self, text: str):
        """Replace the whole buffer as one undoable change."""
        # delete + insert (not set_text, which can't be undone) inside one user action
        self.buffer.begin_user_action()
        self.buffer.delete(self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.buffer.insert(self.buffer.get_start_iter(), text)
        self.buffer.end_user_action()
        self.buffer.set_modified(True)

    def reload(self):
        if self.path and self.path.exists():
            self._load(self.path)

    # ---------------------------------------------------------------- navigation
    def goto_line(self, line: int, select: bool = True):
        if hasattr(self, "folding"):
            self.folding.reveal(max(0, line - 1))     # unfold what hides it
        ok, it = self.buffer.get_iter_at_line(max(0, line - 1))
        if not ok:
            return
        self.buffer.place_cursor(it)
        if select:
            end = it.copy()
            end.forward_to_line_end()
            self.buffer.select_range(it, end)
        # scroll later, once the view has its size; to a mark, which (unlike an iterator) stays valid
        # if the text changes before then
        GLib.idle_add(lambda: (self.view.scroll_to_mark(self.buffer.get_insert(), 0.2, True, 0, 0.4), False)[1])
        self.view.grab_focus()

    def select_match(self, line: int, col: int, length: int):
        """Go to a Find in Files result: the matched text selected."""
        self.goto_line(line, select=False)
        ok, start = self.buffer.get_iter_at_line_offset(max(0, line - 1), col)
        if ok:
            end = start.copy()
            end.forward_chars(length)
            self.buffer.select_range(end, start)      # the cursor at the start of the match
            GLib.idle_add(lambda: (self.view.scroll_to_mark(self.buffer.get_insert(), 0.2, True, 0, 0.4),
                                   False)[1])

    def selected_or_word(self) -> str:
        """The selected text (if on one line), or the name at the cursor: what to search for."""
        b = self.buffer
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            text = b.get_text(s, e, False)
            return text if "\n" not in text else ""
        from ..symindex import word_at
        it = b.get_iter_at_mark(b.get_insert())
        start = it.copy()
        start.set_line_offset(0)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return word_at(b.get_text(start, end, False), it.get_line_offset())[2]

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
        """The lines with a breakpoint that's on."""
        return [ln for ln, on in self.breakpoints() if on]

    def breakpoints(self) -> list[tuple[int, bool]]:
        """(line, on) for each breakpoint, in line order (marks move with the text as lines change)."""
        seen: dict[int, bool] = {}
        for m in self._breakpoints:
            seen.setdefault(self.buffer.get_iter_at_mark(m).get_line() + 1, m not in self._bp_off)
        return sorted(seen.items())

    def set_breakpoints(self, lines: list[tuple[int, bool]]):
        """Show these breakpoints (the project's, as the file opens). Doesn't signal a change."""
        for m in list(self._breakpoints):
            self._remove_bp(m)
        for line, on in lines:
            self._add_bp(line, on)

    def _mark_at(self, line: int):
        return next((m for m in self._breakpoints if self.buffer.get_iter_at_mark(m).get_line() + 1 == line), None)

    def toggle_breakpoint(self, line: int | None = None):
        line = line or self.current_line()
        m = self._mark_at(line)
        if m is not None:
            self._remove_bp(m)
        elif not self._add_bp(line, True):
            return
        self.emit("breakpoints-changed")

    def set_breakpoint_enabled(self, line: int, on: bool):
        m = self._mark_at(line)
        if m is not None and (m not in self._bp_off) != on:
            self._remove_bp(m)
            self._add_bp(line, on)
            self.emit("breakpoints-changed")

    def _add_bp(self, line: int, on: bool) -> bool:
        ok, it = self.buffer.get_iter_at_line(line - 1)
        if not ok:
            return False
        if HAVE_SOURCEVIEW:
            m = self.buffer.create_source_mark(None, "breakpoint" if on else "breakpoint-off", it)
        else:
            m = self.buffer.create_mark(None, it, True)
        self._breakpoints.append(m)
        if not on:
            self._bp_off.add(m)
        end = it.copy()
        end.forward_line()
        self.buffer.apply_tag(self.bp_tag if on else self.bp_off_tag, it, end)
        return True

    def _remove_bp(self, m):
        it = self.buffer.get_iter_at_mark(m)
        end = it.copy()
        end.forward_line()
        self.buffer.remove_tag(self.bp_tag, it, end)
        self.buffer.remove_tag(self.bp_off_tag, it, end)
        self._breakpoints.remove(m)
        self._bp_off.discard(m)
        self.buffer.delete_mark(m)

    def _on_line_mark_activated(self, _view, it, button, _state, n_presses):
        if button == 1 and n_presses == 1:
            if not self.folding.toggle(it.get_line()):      # a #region line: fold it; else a breakpoint
                self.toggle_breakpoint(it.get_line() + 1)

    # ---------------------------------------------------------------- folding
    def _fold_key(self, _c, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            (self.folding.unfold_all if state & Gdk.ModifierType.SHIFT_MASK else self.folding.fold_all)()
            return True
        return False

    def kick_tool(self, mode: str):
        """Create Kick Hash Table / List from the selected lines (CBM prg Studio's Kick Assembler tools)."""
        from .kicktools_dialog import KickToolDialog
        buf = self.buffer
        if buf.get_has_selection():
            a, b = buf.get_selection_bounds()
            text = buf.get_text(a, b, False)
            marks = (buf.create_mark(None, a, True), buf.create_mark(None, b, False))
        else:
            text, marks = "", None

        def replace(result):
            if marks is None:
                buf.insert_at_cursor(result)
                return
            s, e = buf.get_iter_at_mark(marks[0]), buf.get_iter_at_mark(marks[1])
            buf.begin_user_action()
            buf.delete(s, e)
            buf.insert(s, result)
            buf.end_user_action()
        dlg = KickToolDialog(self.get_root(), mode, text, replace)
        dlg.present()
        return dlg

    def fold_selection(self):
        """Put the selected lines (or the cursor's) in a new region (CBM prg Studio's Selection → Fold).
        Kick Assembler sources get the markers as comments."""
        from ..regions import wrap
        buf = self.buffer
        if buf.get_has_selection():
            a, b = buf.get_selection_bounds()
            first, last = a.get_line(), b.get_line()
            if b.starts_line() and last > first:
                last -= 1                           # a selection ending at a line's start doesn't take it
        else:
            first = last = buf.get_iter_at_mark(buf.get_insert()).get_line()
        win = self.get_root()
        project = getattr(win, "project", None)
        kick = bool(project) and project.toolchain == "kickass" and not self.is_basic
        lines = self.get_text().split("\n")
        new = wrap(lines, first, last, comment="//" if kick else "")
        ok, start = buf.get_iter_at_line(first)
        end = buf.get_end_iter() if last + 1 >= len(lines) else buf.get_iter_at_line(last + 1)[1]
        old_end_newline = last + 1 < len(lines)
        block = "\n".join(new[first:last + 3]) + ("\n" if old_end_newline else "")
        buf.begin_user_action()
        buf.delete(start, end)
        buf.insert(start, block)
        buf.end_user_action()
        self.goto_line(first + 1, select=False)

    # ---------------------------------------------------------------- base conversion
    def _setup_convert_menu(self):
        """Right-click → Convert Number, and remember where the right-click was."""
        group = Gio.SimpleActionGroup()
        act = Gio.SimpleAction.new("convert", GLib.VariantType.new("s"))
        act.connect("activate", lambda _a, v: self.convert_number(v.get_string()))
        group.add_action(act)
        for name, fn in (("kick-hash", lambda: self.kick_tool("hash")), ("kick-list", lambda: self.kick_tool("list")),
                         ("fold-selection", lambda: self.fold_selection()),
                         ("fold-all", lambda: self.folding.fold_all()),
                         ("unfold-all", lambda: self.folding.unfold_all())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _v, f=fn: f())
            group.add_action(a)
        self.view.insert_action_group("editor", group)
        sub = Gio.Menu()
        for base, label in (("hex", "Hexadecimal ($)"), ("dec", "Decimal"), ("bin", "Binary (%)")):
            sub.append(label, f"editor.convert::{base}")
        menu = Gio.Menu()
        menu.append("Go to Definition", "win.goto-definition")
        menu.append("Add TODO…", "win.add-todo")
        menu.append_submenu("Convert Number", sub)
        if not self.is_c:          # the analyser and Kick tables are for assembler and BASIC
            menu.append("Analyse…", "win.analyse-here")      # the selection, or the whole file
        if not self.is_basic and not self.is_c and not self.ca65:
            kick = Gio.Menu()
            kick.append("Create Kick Hash Table…", "editor.kick-hash")
            kick.append("Create Kick List…", "editor.kick-list")
            menu.append_section(None, kick)
        folds = Gio.Menu()
        folds.append("Fold Selection (#region)", "editor.fold-selection")
        folds.append("Fold All Regions (Ctrl+P)", "editor.fold-all")
        folds.append("Unfold All Regions (Ctrl+Shift+P)", "editor.unfold-all")
        menu.append_section(None, folds)
        if self.is_pbasic:
            sec = Gio.Menu()
            sec.append("Create Label…", "win.pbasic-create-label")
            sec.append("Remove Line Numbers", "win.pbasic-remove-numbers")
            sec.append("Preview Generated BASIC", "win.pbasic-preview")
            menu.append_section(None, sec)
        elif self.is_basic:
            menu.append("Convert to pBASIC", "win.convert-to-pbasic")
        if self.is_basic:
            fmt = Gio.Menu()
            fmt.append("Reformat BASIC…", "win.reformat-basic")
            fmt.append("Compress (abbreviate keywords)", "win.basic-compress")
            fmt.append("Uncompress (keywords in full)", "win.basic-uncompress")
            menu.append_section(None, fmt)
        self.view.set_extra_menu(menu)
        self._click_iter_offset: int | None = None
        right = Gtk.GestureClick(button=3, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        right.connect("pressed", self._on_right_click)
        self.view.add_controller(right)

    def _basic_return(self, _c, keyval, _code, state):
        if keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) or not self.is_basic or self.is_pbasic:
            return False
        if not getattr(self.settings, "basic_auto_number", True) or self.completion.visible:
            return False
        if state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK):
            return False                        # Shift+Return: a new line without a number (CBM prg Studio)
        buf = self.buffer
        if buf.get_has_selection():
            return False
        it = buf.get_iter_at_mark(buf.get_insert())
        end = it.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        if buf.get_text(it, end, False).strip():
            return False                        # in the middle of a line: just split it
        from ..basic.autonumber import next_number
        lines = self.get_text().split("\n")
        n = next_number(lines, it.get_line(), int(getattr(self.settings, "basic_number_step", 10) or 10))
        if n is None:
            return False
        buf.begin_user_action()
        buf.insert_at_cursor(f"\n{n} ")
        buf.end_user_action()
        self.view.scroll_mark_onscreen(buf.get_insert())
        return True

    def _forget_click(self, *_):
        self._click_iter_offset = None          # menu items act on the cursor again
        return False

    def _on_left_click(self, gesture, _n, x, y):
        self._click_iter_offset = None
        if gesture.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            it = self._iter_at_widget(x, y)
            if it is not None:
                self._click_iter_offset = it.get_offset()
                GLib.idle_add(self._request_definition)

    def _request_definition(self):
        win = self.get_root()
        if hasattr(win, "goto_definition"):
            win.goto_definition(self)
        return False

    def position_at_click(self) -> tuple[int, int, str]:
        """(1-based line, column, the line's text) right-clicked, Ctrl+clicked or at the cursor."""
        buf = self.buffer
        if self._click_iter_offset is not None:
            it = buf.get_iter_at_offset(self._click_iter_offset)
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
        text, col = self.line_at_click()
        return it.get_line() + 1, col, text

    def goto_position(self, line: int, col: int = 0, length: int = 0):
        """Put the cursor at (1-based line, column), selecting `length` characters."""
        self.goto_line(line, select=False)
        ok, it = self.buffer.get_iter_at_line(max(0, line - 1))
        if not ok:
            return
        if col <= it.get_chars_in_line():
            it.set_line_offset(min(col, max(0, it.get_chars_in_line() - (0 if it.ends_line() else 1))))
        end = it.copy()
        end.forward_chars(length)
        self.buffer.select_range(end, it)

    def _completion_candidates(self, prefix: str) -> list[tuple[str, str]]:
        win = self.get_root()
        idx = win.symbol_index() if hasattr(win, "symbol_index") else None
        if idx is None:
            from ..symindex import SymbolIndex
            idx = SymbolIndex()
            if self.path:
                idx.update([self.path], {str(self.path): self.get_text()})
        return [(t, w) for t, w, _s in idx.completions(prefix, str(self.path) if self.path else None,
                                                        basic=self.is_basic, limit=100,
                                                        from_line=self.current_line())]

    def line_at_click(self) -> tuple[str, int]:
        """The text of the line right-clicked (or with the cursor), and the column."""
        buf = self.buffer
        if self._click_iter_offset is not None:
            it = buf.get_iter_at_offset(self._click_iter_offset)
        else:
            it = buf.get_iter_at_mark(buf.get_insert())
        start = it.copy()
        start.set_line_offset(0)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return buf.get_text(start, end, False), it.get_line_offset()

    def _iter_at_widget(self, x, y):
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, it = self.view.get_iter_at_location(bx, by)
        return it if ok else None

    def _on_right_click(self, _g, _n, x, y):
        it = self._iter_at_widget(x, y)
        self._click_iter_offset = it.get_offset() if it else None

    def _number_near(self, it) -> tuple[numconv.Number, Gtk.TextIter] | None:
        """The number at an iter, and the iter at the start of its line."""
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        line = self.buffer.get_text(line_start, line_end, False)
        n = numconv.number_at(line, it.get_line_offset())
        return (n, line_start) if n else None

    def convert_number(self, base: str) -> bool:
        """Rewrite the selected number (or the one right-clicked, or at the cursor) in a base."""
        if self.is_basic:
            return False
        buf = self.buffer
        sel = buf.get_selection_bounds()
        if sel:
            start, end = sel
            text = buf.get_text(start, end, False)
            body = text.lstrip(" \t#")             # "#$12" selected: convert the number, keep the #
            n = numconv.parse(body)
            if n is None:
                self.view.error_bell()
                return False
            lead = len(text) - len(body)
            start.forward_chars(lead)
            end = start.copy()
            end.forward_chars(len(n.text))
        else:
            off = self._click_iter_offset
            it = buf.get_iter_at_offset(off) if off is not None else buf.get_iter_at_mark(buf.get_insert())
            found = self._number_near(it)
            if not found:
                self.view.error_bell()
                return False
            n, line_start = found
            start = line_start.copy()
            start.forward_chars(n.start)
            end = line_start.copy()
            end.forward_chars(n.end)
        new = numconv.to_base(n.value, base, n)
        offset = start.get_offset()
        buf.begin_user_action()
        buf.delete(start, end)
        buf.insert(buf.get_iter_at_offset(offset), new)
        buf.end_user_action()
        if sel:
            buf.select_range(buf.get_iter_at_offset(offset), buf.get_iter_at_offset(offset + len(new)))
        self._click_iter_offset = None
        return True

    # ---------------------------------------------------------------- hover help
    def _on_tooltip(self, view, x, y, _keyboard, tooltip):
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, x, y)
        ok, it = view.get_iter_at_location(bx, by)
        if not ok:
            return False
        if not self.is_basic:
            found = self._number_near(it)
            if found:
                tooltip.set_text(numconv.describe(found[0]))
                return True
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
        if self.is_basic:
            return False
        win = self.get_root()
        if hasattr(win, "describe_symbol"):
            line_start = it.copy()
            line_start.set_line_offset(0)
            line_end = line_start.copy()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            info = win.describe_symbol(self, self.buffer.get_text(line_start, line_end, False),
                                       it.get_line_offset(), it.get_line() + 1)
            if info:
                tooltip.set_text(info)
                return True
        help_text = DIRECTIVE_HELP.get(word)
        if help_text:
            tooltip.set_text(help_text)
            return True
        return False
