"""Auto-complete for the source editor: a list under the cursor of the names that could finish
the word being typed (the project's labels, constants and macros, then instructions and
directives), with what each one is and where it's defined.

It's a plain popover rather than GtkSourceView's completion engine, which PyGObject 3.48 can't
drive from Python (it loses the data passed through the provider's async populate call).
"""
from __future__ import annotations

import re
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

_WORD_CHAR = re.compile(r"[A-Za-z0-9_@$.#]")
MIN_AUTO = 2          # letters typed before the list appears by itself


def _in_comment_or_string(before: str) -> bool:
    q = None
    for i, ch in enumerate(before):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == ";" or before.startswith("//", i):
            return True
    return q is not None


def prefix_before(line: str) -> str:
    """The part of a name before the cursor (`line` is the text up to it)."""
    i = len(line)
    while i > 0 and _WORD_CHAR.match(line[i - 1]):
        i -= 1
    word = line[i:]
    while word[:1] == "#" and line[:i].strip():
        word = word[1:]                           # lda #VALUE: only #import and so on start with #
    if "." in word[1:]:
        word = word[word.rindex(".") + 1:]       # Kick's name.sub: complete the part after the dot
    if word.startswith("$") or (word[:1].isdigit()):
        return ""                                 # a number
    return word


class CompletionPopup:
    """Attach to a Gtk.TextView. `candidates(prefix)` gives [(text, what it is)]; `auto()` says
    whether to open the list while typing (Ctrl+Space always does)."""

    def __init__(self, view: Gtk.TextView, candidates: Callable[[str], list[tuple[str, str]]],
                 auto: Callable[[], bool]):
        self.view = view
        self.buffer = view.get_buffer()
        self.candidates = candidates
        self.auto = auto
        self.items: list[tuple[str, str]] = []
        self.prefix = ""
        self.pop = Gtk.Popover(autohide=False, has_arrow=False, can_focus=False, position=Gtk.PositionType.BOTTOM,
                               halign=Gtk.Align.START)
        self.pop.add_css_class("menu")
        self.pop.set_parent(view)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, can_focus=False, activate_on_single_click=True)
        self.list.connect("row-activated", lambda _l, row: self.accept(row.get_index()))
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                         propagate_natural_width=True, max_content_height=260, can_focus=False)
        self.scroll.set_child(self.list)
        self.pop.set_child(self.scroll)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        view.add_controller(keys)
        click = Gtk.GestureClick(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", lambda *_: self.hide())
        view.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self.hide())
        view.add_controller(focus)
        view.connect("destroy", lambda *_: self.pop.unparent())

    @property
    def visible(self) -> bool:
        return self.pop.get_visible()

    # ---------------------------------------------------------------- keys
    def _on_key(self, _c, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval == Gdk.KEY_space:
            self.update(force=True)
            return True
        if self.visible:
            if keyval in (Gdk.KEY_Down, Gdk.KEY_Up, Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
                step = {Gdk.KEY_Down: 1, Gdk.KEY_Up: -1, Gdk.KEY_Page_Down: 8, Gdk.KEY_Page_Up: -8}[keyval]
                self._select(self._selected() + step)
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter, Gdk.KEY_Tab):
                self.accept(self._selected())
                return True
            if keyval == Gdk.KEY_Escape:
                self.hide()
                return True
            if keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Home, Gdk.KEY_End):
                self.hide()
                return False
        if ctrl or state & Gdk.ModifierType.ALT_MASK:
            return False
        ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        if keyval == Gdk.KEY_BackSpace and self.visible:
            GLib.idle_add(self._after_typing, True)
        elif ch and _WORD_CHAR.match(ch):
            GLib.idle_add(self._after_typing, False)
        elif ch and self.visible:
            self.hide()
        return False

    def _after_typing(self, deleting: bool):
        if self.visible or (not deleting and self.auto()):
            self.update()
        return False

    # ---------------------------------------------------------------- the list
    def _cursor(self):
        return self.buffer.get_iter_at_mark(self.buffer.get_insert())

    def update(self, force: bool = False):
        """Show (or refresh) the list for the word before the cursor."""
        it = self._cursor()
        start = it.copy()
        start.set_line_offset(0)
        before = self.buffer.get_text(start, it, False)
        if _in_comment_or_string(before) and not force:
            self.hide()
            return
        prefix = prefix_before(before)
        if not prefix or (len(prefix) < MIN_AUTO and not force):
            self.hide()
            return
        items = self.candidates(prefix)
        if not items:
            self.hide()
            return
        self.prefix = prefix
        self.items = items
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for text, what in items:
            box = Gtk.Box(spacing=18, margin_start=4, margin_end=4)
            name = Gtk.Label(xalign=0, hexpand=True, css_classes=["monospace"])
            n = len(prefix) if text.lower().startswith(prefix.lower()) else 0
            name.set_markup(f"<b>{GLib.markup_escape_text(text[:n])}</b>{GLib.markup_escape_text(text[n:])}")
            box.append(name)
            box.append(Gtk.Label(label=what, xalign=1, css_classes=["dim-label", "caption"]))
            self.list.append(box)
        self._select(0)
        word_start = it.copy()
        word_start.backward_chars(len(prefix))
        r = self.view.get_iter_location(word_start)
        x, y = self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, r.x, r.y)
        rect = Gdk.Rectangle()
        # kept inside the view: a popover pointing outside its window can't be placed
        w, h = max(1, self.view.get_width()), max(1, self.view.get_height())
        rect.x, rect.y = max(0, min(x, w - 1)), max(0, min(y, h - r.height))
        rect.width, rect.height = 1, max(1, r.height)
        self.pop.set_pointing_to(rect)
        if not self.visible:
            self.pop.popup()

    def hide(self):
        if self.visible:
            self.pop.popdown()

    def _selected(self) -> int:
        row = self.list.get_selected_row()
        return row.get_index() if row else 0

    def _select(self, i: int):
        if not self.items:
            return
        i = max(0, min(len(self.items) - 1, i))
        row = self.list.get_row_at_index(i)
        self.list.select_row(row)
        adj = self.scroll.get_vadjustment()
        ok, bounds = row.compute_bounds(self.list)
        if ok:
            top, h = bounds.get_y(), bounds.get_height()
            if top < adj.get_value():
                adj.set_value(top)
            elif top + h > adj.get_value() + adj.get_page_size():
                adj.set_value(top + h - adj.get_page_size())

    def accept(self, i: int):
        """Put the chosen name in place of the word at the cursor."""
        if not 0 <= i < len(self.items):
            return
        text = self.items[i][0]
        it = self._cursor()
        start = it.copy()
        start.backward_chars(len(self.prefix))
        end = it.copy()
        while not end.ends_line() and _WORD_CHAR.match(end.get_char()) and end.get_char() not in ".":
            end.forward_char()                  # the rest of the word, if the cursor was inside one
        self.buffer.begin_user_action()
        self.buffer.delete(start, end)
        self.buffer.insert(start, text)
        self.buffer.end_user_action()
        self.hide()
