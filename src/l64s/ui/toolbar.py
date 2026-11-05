"""The toolbar row under the menu bar, as CBM prg Studio's: files, editing, building, the debugger and
the tools used most. Every button runs a menu action, so it's enabled and disabled with it."""
from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from .menus import new_menu

# (icon, tooltip, action, target) per button; None separates groups. "l64s-" icons are the app's own.
BUTTONS = (
    ("l64s-save-all-symbolic", "Save All (Ctrl+Shift+S)", "win.save-all", None),
    None,
    ("edit-undo-symbolic", "Undo (Ctrl+Z)", "win.edit", "text.undo"),
    ("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)", "win.edit", "text.redo"),
    ("edit-cut-symbolic", "Cut (Ctrl+X)", "win.edit", "clipboard.cut"),
    ("edit-copy-symbolic", "Copy (Ctrl+C)", "win.edit", "clipboard.copy"),
    ("edit-paste-symbolic", "Paste (Ctrl+V)", "win.edit", "clipboard.paste"),
    ("go-jump-symbolic", "Go to Line (Ctrl+G)", "win.goto-line", None),
    None,
    ("emblem-system-symbolic", "Build Project (F7)", "win.build-project", None),
    ("text-x-generic-symbolic", "Build Current File (Shift+F7)", "win.build-file", None),
    ("media-playback-start-symbolic", "Build Project and Run (Ctrl+F5)", "win.run-project", None),
    ("system-run-symbolic", "Debug Project (Shift+F5)", "win.debug-project", None),
    None,
    ("media-record-symbolic", "Toggle Breakpoint (F9)", "win.toggle-breakpoint", None),
    ("l64s-continue-symbolic", "Continue (F8)", "win.debug-continue", None),
    ("l64s-step-over-symbolic", "Step Over (F10)", "win.debug-over", None),
    ("l64s-step-into-symbolic", "Step Into (F11)", "win.debug-into", None),
    ("l64s-step-out-symbolic", "Step Out (Shift+F11)", "win.debug-out", None),
    None,
    ("drive-harddisk-symbolic", "Memory Viewer", "win.memory-viewer", None),
    ("view-grid-symbolic", "Memory Manager", "win.memory-manager", None),
    ("system-search-symbolic", "Disassembler", "win.disassembler", None),
    ("insert-text-symbolic", "Screen Code Builder", "win.screen-codes", None),
    ("audio-speakers-symbolic", "SID Designer", "win.sid-designer", None),
)


def _sep() -> Gtk.Separator:
    return Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4,
                         margin_top=6, margin_bottom=6)


def _light_dark_button() -> Gtk.Button:
    """Switches between light and dark; shows what a click switches to."""
    btn = Gtk.Button(action_name="app.toggle-dark", focus_on_click=False)
    sm = Adw.StyleManager.get_default()

    def show(*_):
        dark = sm.get_dark()
        btn.set_icon_name("weather-clear-symbolic" if dark else "weather-clear-night-symbolic")
        btn.set_tooltip_text("Light mode" if dark else "Dark mode")
    sm.connect("notify::dark", show)
    show()
    return btn


def build_toolbar(recent: Gio.MenuModel) -> Gtk.Box:
    bar = Gtk.Box(css_classes=["toolbar"], spacing=2)
    bar.append(Gtk.MenuButton(icon_name="document-new-symbolic", menu_model=new_menu(), tooltip_text="New"))
    opener = Adw.SplitButton(icon_name="document-open-symbolic", tooltip_text="Open Project (Ctrl+O)",
                             dropdown_tooltip="Open a recent project", action_name="win.open-project",
                             menu_model=recent)
    bar.append(opener)
    bar.append(Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save (Ctrl+S)", action_name="win.save"))
    for b in BUTTONS:
        if b is None:
            bar.append(_sep())
            continue
        icon, tip, action, target = b
        btn = Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action, focus_on_click=False)
        if target is not None:
            btn.set_action_target_value(GLib.Variant.new_string(target))
        if action == "win.run-project":
            btn.add_css_class("suggested-action")
        bar.append(btn)
    bar.append(Gtk.Box(hexpand=True))
    bar.append(_light_dark_button())
    bar.append(Gtk.Button(icon_name="preferences-system-symbolic", tooltip_text="Preferences (Ctrl+,)",
                          action_name="app.preferences", focus_on_click=False))
    bar.append(Gtk.Button(icon_name="help-browser-symbolic", tooltip_text="Keyboard Shortcuts",
                          action_name="app.shortcuts", focus_on_click=False))
    return bar
