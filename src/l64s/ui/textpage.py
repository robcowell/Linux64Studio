"""A read-only text tab: Git's status, changes (a diff, highlighted as one) and history."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .editor import HAVE_SOURCEVIEW, EditorPage, GtkSource  # noqa: E402


class TextPage(EditorPage):
    kind = "text"

    def __init__(self, title: str, text: str = "", language: str | None = None, key: str | None = None):
        super().__init__(None)
        self._title = title
        self.key = key or title                 # tabs with the same key are reused
        if HAVE_SOURCEVIEW:
            self.buffer = GtkSource.Buffer()
            lang = GtkSource.LanguageManager.get_default().get_language(language) if language else None
            if lang:
                self.buffer.set_language(lang)
            from gi.repository import Adw
            sm = GtkSource.StyleSchemeManager.get_default()
            scheme = sm.get_scheme("Adwaita-dark" if Adw.StyleManager.get_default().get_dark() else "Adwaita")
            if scheme:
                self.buffer.set_style_scheme(scheme)
            self.view = GtkSource.View(buffer=self.buffer, editable=False, monospace=True, cursor_visible=False)
        else:
            self.buffer = Gtk.TextBuffer()
            self.view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True)
        self.view.set_left_margin(8)
        self.view.set_top_margin(6)
        self.append(Gtk.ScrolledWindow(child=self.view, hexpand=True, vexpand=True))
        self.set_text(text)

    @property
    def title(self) -> str:
        return self._title

    def set_text(self, text: str):
        self.buffer.set_text(text)
        self.set_modified(False)

    def get_text(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)

    def save(self):
        self.set_modified(False)
