"""The status bar along the bottom of the window while a source file is in front (see l64s.statusbar
for what each part shows). Parts that switch a setting are flat buttons; the rest are labels."""
from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gdk, Gtk

from ..statusbar import Field

# slim, like CBM prg Studio's: no toolbar padding, and buttons no taller than the labels
CSS = b"""
.l64s-statusbar { padding: 0 6px; border-top: 1px solid alpha(currentColor, 0.15); }
.l64s-statusbar label { padding: 3px 8px; }
.l64s-statusbar button { min-height: 0; padding: 0; border-radius: 4px; }
"""
_css_installed = False


def _install_css():
    global _css_installed
    display = Gdk.Display.get_default()
    if _css_installed or display is None:
        return
    css = Gtk.CssProvider()
    css.load_from_data(CSS, -1)
    Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_installed = True


class StatusBar(Gtk.ScrolledWindow):
    """(A scroller with no scrollbar: on a narrow window the fields at the right are cut off, rather than
    the bar setting how narrow the window can be.)"""

    def __init__(self, on_toggle: Callable[[str], None]):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.EXTERNAL, vscrollbar_policy=Gtk.PolicyType.NEVER,
                         propagate_natural_height=True, propagate_natural_width=True,
                         css_classes=["l64s-statusbar"])
        _install_css()
        self._box = Gtk.Box(spacing=0)
        self.set_child(self._box)
        self._on_toggle = on_toggle
        self._keys: list[str] = []
        self._widgets: dict[str, Gtk.Widget] = {}

    def show_fields(self, fields: list[Field]):
        keys = [f.key for f in fields]
        if keys != self._keys:
            self._rebuild(fields)
        for f in fields:
            w = self._widgets[f.key]
            if isinstance(w, Gtk.Button):
                w.set_label(f.text)
            else:
                w.set_text(f.text)
            w.set_tooltip_text(f.tooltip or None)
            if f.lit:
                w.remove_css_class("dim-label")
            else:
                w.add_css_class("dim-label")

    def _rebuild(self, fields: list[Field]):
        while (c := self._box.get_first_child()) is not None:
            self._box.remove(c)
        self._widgets.clear()
        for i, f in enumerate(fields):
            if i:
                self._box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_top=4, margin_bottom=4))
            if f.toggle:
                w = Gtk.Button(css_classes=["flat", "caption"], focus_on_click=False)
                w.connect("clicked", lambda _b, k=f.key: self._on_toggle(k))
            else:
                w = Gtk.Label(css_classes=["caption"])
            self._widgets[f.key] = w
            self._box.append(w)
        self._keys = [f.key for f in fields]
