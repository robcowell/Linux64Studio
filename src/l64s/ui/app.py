"""Linux64Studio application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..settings import Settings  # noqa: E402

APP_ID = "io.github.linux64studio.Linux64Studio"

# Shortcuts follow CBM prg Studio where it has one.
ACCELS = {
    "win.open-project": ["<Control>o"],
    "win.save": ["<Control>s"],
    "win.save-all": ["<Control><Shift>s"],
    "win.close-tab": ["<Control>w"],
    "win.build-project": ["F7"],
    "win.build-file": ["<Shift>F7"],
    "win.run-file": ["F5"],                 # CBM prg Studio: Build -> Program -> And Run
    "win.run-project": ["<Control>F5"],     # CBM prg Studio: Build -> Project -> And Run
    "win.debug-project": ["<Shift>F5"],
    "win.toggle-breakpoint": ["F9"],
    "win.debug-continue": ["F8"],
    "win.debug-over": ["F10"],
    "win.debug-into": ["F11"],
    "win.debug-out": ["<Shift>F11"],
    "win.goto-line": ["<Control>g"],
    "app.preferences": ["<Control>comma"],
    "app.quit": ["<Control>q"],
}

SHORTCUT_GROUPS = [
    ("Files", [("<Control>o", "Open project"), ("<Control>s", "Save"), ("<Control><Shift>s", "Save all"),
               ("<Control>w", "Close tab"), ("<Control>g", "Go to line")]),
    ("Build and run", [("F7", "Build project"), ("<Shift>F7", "Build current file"),
                       ("F5", "Build current file and run"), ("<Control>F5", "Build project and run"),
                       ("<Shift>F5", "Debug project")]),
    ("Debugging", [("F9", "Toggle breakpoint"), ("F8", "Continue"), ("F10", "Step over"),
                   ("F11", "Step into"), ("<Shift>F11", "Step out")]),
]


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.settings = Settings.load()
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._apply_colour_scheme()
        for name, cb in (("preferences", self._preferences), ("about", self._about),
                         ("shortcuts", self._shortcuts), ("quit", lambda *_: self.window and self.window.close())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

    def _ensure_window(self):
        if not self.window:
            from .window import MainWindow
            self.window = MainWindow(self, self.settings)
        return self.window

    def do_activate(self):
        self._ensure_window().present()

    def do_open(self, files, _n, _hint):
        win = self._ensure_window()
        win.present()
        for f in files:
            p = Path(f.get_path())
            if p.suffix.lower() in (".l64proj", ".cbmprj", ".code-workspace") or p.is_dir():
                if p.is_dir():
                    found = sorted(list(p.glob("*.l64proj")) + list(p.glob("*.cbmprj")) + list(p.glob("*.code-workspace")))
                    if not found:
                        win.toast(f"No project file in {p}")
                        continue
                    p = found[0]
                win.open_project(p)
            else:
                win.open_file(p)

    def _apply_colour_scheme(self):
        sm = Adw.StyleManager.get_default()
        sm.set_color_scheme({"light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}.get(
            self.settings.dark_mode, Adw.ColorScheme.DEFAULT))

    # ------------------------------------------------------------------ dialogs
    def _about(self, *_):
        about = Adw.AboutDialog(application_name="Linux64Studio", version=__version__,
                                application_icon="applications-games-symbolic",
                                comments="A Commodore 64 development environment for Linux, with an assembler "
                                         "compatible with CBM prg Studio's syntax.")
        about.present(self.window)

    def _shortcuts(self, *_):
        win = Gtk.ShortcutsWindow(transient_for=self.window, modal=True)
        section = Gtk.ShortcutsSection(visible=True)
        # add_section/add_group/add_shortcut need GTK 4.14+
        for title, items in SHORTCUT_GROUPS:
            group = Gtk.ShortcutsGroup(title=title, visible=True)
            for accel, label in items:
                group.add_shortcut(Gtk.ShortcutsShortcut(accelerator=accel, title=label, visible=True))
            section.add_group(group)
        win.add_section(section)
        win.present()

    def _preferences(self, *_):
        s = self.settings
        dlg = Adw.PreferencesDialog(title="Preferences")
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        dlg.add(page)

        emu = Adw.PreferencesGroup(title="Emulator", description="VICE is used to run and debug programs.")
        emu_path = Adw.EntryRow(title="VICE executable", text=s.emulator)
        emu_args = Adw.EntryRow(title="Extra VICE arguments", text=" ".join(s.emulator_args))
        emu.add(emu_path)
        emu.add(emu_args)
        page.add(emu)

        ka = Adw.PreferencesGroup(title="Kick Assembler",
                                  description="Used for Kick Assembler projects (Retro Game Dev Vol 2, VS Code "
                                              "workspaces). Point this at KickAss.jar.")
        jar = Adw.ActionRow(title="KickAss.jar", subtitle=s.kickass_jar or "Not set")
        pick = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        jar.add_suffix(pick)
        java = Adw.EntryRow(title="Java", text=s.java)
        ka.add(jar)
        ka.add(java)
        page.add(ka)

        def choose_jar(*_):
            fd = Gtk.FileDialog(title="Choose KickAss.jar")
            f = Gtk.FileFilter(name="Java archives")
            f.add_pattern("*.jar")
            store = Gio.ListStore.new(Gtk.FileFilter)
            store.append(f)
            fd.set_filters(store)

            def done(d, res):
                try:
                    jar.set_subtitle(d.open_finish(res).get_path())
                except GLib.Error:
                    pass
            fd.open(self.window, None, done)
        pick.connect("clicked", choose_jar)

        mg = Adw.PreferencesGroup(title="Music",
                                  description="GoatTracker GTK Edition and SidMonkey (github.com/robcowell/"
                                              "goattracker) for songs and sound effects; VICE's vsid to play them.")
        gt_dir = Adw.EntryRow(title="GoatTracker folder (with gt2reloc, ins2snd2, goattrk2, sidmonkey)",
                              text=s.goattracker_dir)
        vsid = Adw.EntryRow(title="SID player", text=s.vsid)
        mg.add(gt_dir)
        mg.add(vsid)
        page.add(mg)

        ed = Adw.PreferencesGroup(title="Editor")
        font = Adw.EntryRow(title="Font", text=s.font)
        tabw = Adw.SpinRow.new_with_range(1, 16, 1)
        tabw.set_title("Tab width")
        tabw.set_value(s.tab_width)
        spaces = Adw.SwitchRow(title="Insert spaces instead of tabs", active=s.insert_spaces)
        save_first = Adw.SwitchRow(title="Save files before building", active=s.save_before_build)
        scheme = Adw.ComboRow(title="Appearance", model=Gtk.StringList.new(["Follow system", "Light", "Dark"]),
                              selected=["system", "light", "dark"].index(s.dark_mode)
                              if s.dark_mode in ("system", "light", "dark") else 0)
        for w in (font, tabw, spaces, save_first, scheme):
            ed.add(w)
        page.add(ed)

        def closed(*_):
            s.emulator = emu_path.get_text().strip() or "x64sc"
            s.emulator_args = emu_args.get_text().split()
            sub = jar.get_subtitle()
            s.kickass_jar = "" if sub == "Not set" else sub
            s.java = java.get_text().strip() or "java"
            s.goattracker_dir = gt_dir.get_text().strip()
            s.vsid = vsid.get_text().strip() or "vsid"
            s.font = font.get_text().strip() or "Monospace 11"
            s.tab_width = int(tabw.get_value())
            s.insert_spaces = spaces.get_active()
            s.save_before_build = save_first.get_active()
            s.dark_mode = ["system", "light", "dark"][scheme.get_selected()]
            s.save()
            self._apply_colour_scheme()
        dlg.connect("closed", closed)
        dlg.present(self.window)


def main(argv: list[str] | None = None) -> int:
    app = Application()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
