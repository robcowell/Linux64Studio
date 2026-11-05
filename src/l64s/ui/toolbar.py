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
    ("edit-find-symbolic", "Find in Files (Ctrl+Shift+F)", "win.find-in-files", None),
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


# What goes when the window is narrow (see MainWindow: Adw breakpoints): the tools first, then the
# debugger and editing buttons, then the ones at the right. Files and building always stay.
GROUP_NAMES = ("files", "edit", "build", "debug", "tools")
NARROW_STAGES = ((1300, ("tools",)), (1100, ("tools", "debug", "edit")), (720, ("tools", "debug", "edit", "right")))
RIGHT = (("Light or Dark Mode", "app.toggle-dark"), ("Preferences", "app.preferences"),
         ("Keyboard Shortcuts", "app.shortcuts"))


class Toolbar(Gtk.Box):
    """The toolbar row, in groups that hide on a narrow window, their commands then in ⋯."""

    def __init__(self, recent: Gio.MenuModel, program_choice: Gtk.Widget | None = None):
        super().__init__(css_classes=["toolbar"], spacing=2)
        self.groups: dict[str, Gtk.Box] = {}
        self._items: dict[str, list[tuple[str, str, str | None]]] = {}    # group -> (label, action, target)
        groups = [[]]
        for b in BUTTONS:
            if b is None:
                groups.append([])
            else:
                groups[-1].append(b)
        for gi, (name, buttons) in enumerate(zip(GROUP_NAMES, groups)):
            box = Gtk.Box(spacing=2)
            if gi:
                box.append(_sep())
            if name == "files":
                box.append(Gtk.MenuButton(icon_name="document-new-symbolic", menu_model=new_menu(),
                                          tooltip_text="New"))
                box.append(Adw.SplitButton(icon_name="document-open-symbolic", tooltip_text="Open Project (Ctrl+O)",
                                           dropdown_tooltip="Open a recent project", action_name="win.open-project",
                                           menu_model=recent))
                box.append(Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save (Ctrl+S)",
                                      action_name="win.save"))
            items = []
            for icon, tip, action, target in buttons:
                btn = Gtk.Button(icon_name=icon, tooltip_text=tip, action_name=action, focus_on_click=False)
                if target is not None:
                    btn.set_action_target_value(GLib.Variant.new_string(target))
                if action == "win.run-project":
                    btn.add_css_class("suggested-action")
                box.append(btn)
                items.append((tip.split(" (")[0], action, target))
                if action == "win.debug-project" and program_choice is not None:
                    box.append(program_choice)
            self.groups[name], self._items[name] = box, items
            self.append(box)
        self.append(Gtk.Box(hexpand=True))
        self.overflow = Gtk.MenuButton(icon_name="view-more-symbolic", visible=False,
                                       tooltip_text="More (the buttons that don't fit)")
        self.append(self.overflow)
        right = Gtk.Box(spacing=2)
        right.append(_light_dark_button())
        right.append(Gtk.Button(icon_name="preferences-system-symbolic", tooltip_text="Preferences (Ctrl+,)",
                                action_name="app.preferences", focus_on_click=False))
        right.append(Gtk.Button(icon_name="help-browser-symbolic", tooltip_text="Keyboard Shortcuts",
                                action_name="app.shortcuts", focus_on_click=False))
        self.groups["right"] = right
        self._items["right"] = [(label, action, None) for label, action in RIGHT]
        self.append(right)

    def overflow_menu(self, hidden: tuple[str, ...]) -> Gio.Menu:
        """The ⋯ menu when the ``hidden`` groups are hidden: their commands, a section each."""
        menu = Gio.Menu()
        for name in ("edit", "debug", "tools", "right"):
            if name not in hidden:
                continue
            sec = Gio.Menu()
            for label, action, target in self._items[name]:
                item = Gio.MenuItem.new(label, None)
                if target is not None:
                    item.set_action_and_target_value(action, GLib.Variant.new_string(target))
                else:
                    item.set_detailed_action(action)
                sec.append_item(item)
            menu.append_section(None, sec)
        return menu


def build_toolbar(recent: Gio.MenuModel, program_choice: Gtk.Widget | None = None) -> Toolbar:
    """The toolbar; ``program_choice`` (the current program, for projects with several) goes after
    the build buttons, where CBM prg Studio has its target."""
    return Toolbar(recent, program_choice)
