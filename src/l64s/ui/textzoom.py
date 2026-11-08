"""Text zoom for the whole IDE (Ctrl+Shift+plus, Ctrl+Shift+minus, Ctrl+0), for big high-resolution screens.

GTK sizes every font from the display's font DPI, so raising that scales all the text, the editors'
included, and the widgets around it. What doesn't follow by itself: icons (set here, from CSS),
text drawn with Cairo at a size in pixels (those views use ``px``) and sizes a widget has worked out
from its text (it defines ``text_zoom_changed()``, called after each change)."""
from __future__ import annotations

from gi.repository import Gdk, Gtk

_percent = 100
_base_dpi: int | None = None
_icons: Gtk.CssProvider | None = None

# (the status page's big icon and others with a size of their own stay as they are)
ICON_CSS = "button image, headerbar image, tabbar image, row image, .navigation-sidebar image { -gtk-icon-size: %dpx; }"


def factor() -> float:
    """How much bigger than normal the text is."""
    return _percent / 100


def px(pixels: float) -> float:
    """A length in pixels at normal size, at the current size."""
    return pixels * factor()


def apply(percent: int):
    """Make the text ``percent`` of its normal size, in every window."""
    global _percent, _base_dpi, _icons
    settings, display = Gtk.Settings.get_default(), Gdk.Display.get_default()
    if settings is None or display is None:
        return
    if _base_dpi is None:           # what the desktop asked for (its own text scaling): the normal size
        dpi = settings.get_property("gtk-xft-dpi")
        _base_dpi = dpi if dpi > 0 else 96 * 1024
    _percent = percent
    settings.set_property("gtk-xft-dpi", round(_base_dpi * factor()))
    if _icons is None:
        _icons = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, _icons, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _icons.load_from_data((ICON_CSS % round(px(16))).encode() if percent != 100 else b"", -1)
    for window in Gtk.Window.list_toplevels():
        _notify(window)


def _notify(widget: Gtk.Widget):
    hook = getattr(widget, "text_zoom_changed", None)
    if hook is not None:
        hook()
    widget.queue_draw()
    child = widget.get_first_child()
    while child is not None:
        _notify(child)
        child = child.get_next_sibling()
