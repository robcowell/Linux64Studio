"""Preferences → User Tools: the programs on the User Tools menu (CBM prg Studio's Add User Tool)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..usertools import PRESETS, UserTool  # noqa: E402


class UserToolsPage(Adw.PreferencesPage):
    def __init__(self, tools: list[dict]):
        super().__init__(title="User Tools", icon_name="applications-utilities-symbolic")
        self.group = Adw.PreferencesGroup(
            title="User Tools",
            description="Programs of your own on the User Tools menu: an editor, a cruncher, another "
                        "emulator. Arguments are split into words as a shell would (quote ones with spaces) and "
                        "can name the project's files: " + " ".join(PRESETS) + ".")
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add a tool", valign=Gtk.Align.CENTER,
                         css_classes=["flat"])
        add.connect("clicked", lambda *_: self._add(UserTool("New tool", "", ""), expanded=True))
        self.group.set_header_suffix(add)
        self.add(self.group)
        self.rows: list[tuple] = []
        for d in tools:
            self._add(UserTool.from_dict(d))
        ex = Adw.PreferencesGroup(title="Examples")
        for title, sub in (("Crunch the program", "exomizer, with arguments: sfx sys -o [prgDir]/[ProjectName].exo [prg]"),
                           ("Run it in another emulator", "x64sc (or VICE's xvic…), with arguments: -autostart [prg]"),
                           ("Edit the file in another editor", "gedit (or code, kate…), with arguments: [CurrentFile]"),
                           ("Commit the project", "git, arguments: commit -am \"[Date]\", output in the build log")):
            ex.add(Adw.ActionRow(title=title, subtitle=sub, subtitle_selectable=True))
        self.add(ex)

    def _add(self, t: UserTool, expanded: bool = False):
        row = Adw.ExpanderRow(title=t.name or "(no name)", subtitle=t.command, expanded=expanded)
        name = Adw.EntryRow(title="Name on the menu", text=t.name)
        cmd = Adw.EntryRow(title="Program (a name on the PATH, or a path)", text=t.command)
        args = Adw.EntryRow(title="Arguments", text=t.arguments)
        folder = Adw.EntryRow(title="Run in folder (empty: the project's)", text=t.folder)
        capture = Adw.SwitchRow(title="Show its output in the build log",
                                subtitle="Waits for it to finish; otherwise it's just started", active=t.capture)
        name.connect("changed", lambda e: row.set_title(e.get_text() or "(no name)"))
        cmd.connect("changed", lambda e: row.set_subtitle(e.get_text()))
        for w in (name, cmd, args, folder, capture):
            row.add_row(w)
        rm = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove this tool", valign=Gtk.Align.CENTER,
                        css_classes=["flat"])
        entry = (row, name, cmd, args, folder, capture)
        rm.connect("clicked", lambda *_: (self.group.remove(row), self.rows.remove(entry)))
        row.add_suffix(rm)
        self.group.add(row)
        self.rows.append(entry)

    def tools(self) -> list[UserTool]:
        return [UserTool(n.get_text().strip(), c.get_text().strip(), a.get_text().strip(), f.get_text().strip(),
                         cap.get_active())
                for _r, n, c, a, f, cap in self.rows if c.get_text().strip()]
