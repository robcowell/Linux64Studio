"""Linux64Studio application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

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
    "win.find-in-files": ["<Control><Shift>f"],
    "win.find": ["<Control>f"],
    "win.replace": ["<Control>h"],
    "win.find-next": ["F3"],
    "win.find-previous": ["<Shift>F3"],
    "win.goto-definition": ["F12"],
    "win.go-back": ["<Alt>Left"],
    "app.preferences": ["<Control>comma"],
    "app.quit": ["<Control>q"],
}

SHORTCUT_GROUPS = [
    ("Files", [("<Control>o", "Open project"), ("<Control>s", "Save"), ("<Control><Shift>s", "Save all"),
               ("<Control>w", "Close tab"), ("<Control>g", "Go to line")]),
    ("Editing", [("<Control>f", "Find"), ("<Control>h", "Replace"), ("F3", "Find next"),
                 ("<Shift>F3", "Find previous"), ("<Control><Shift>f", "Find in files"), ("<Control>space", "Complete the name"), ("F12", "Go to definition (or Ctrl+click)"),
                 ("<Alt>Left", "Back to where you were")]),
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
        # the app's icon, from the package (tools/install-desktop.sh also installs it for the menu)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.IconTheme.get_for_display(display).add_search_path(
                str(Path(__file__).resolve().parent.parent / "data" / "icons"))
        Gtk.Window.set_default_icon_name(APP_ID)
        # Appearance: Follow System / Light / Dark (Window → Appearance), and the toolbar's light/dark switch
        appearance = Gio.SimpleAction.new_stateful("appearance", GLib.VariantType.new("s"),
                                                   GLib.Variant.new_string(self.settings.dark_mode))
        appearance.connect("change-state", lambda _a, v: self.set_appearance(v.get_string()))
        self.add_action(appearance)
        self._apply_colour_scheme()
        for name, cb in (("preferences", self._preferences), ("about", self._about),
                         ("toggle-dark", lambda *_: self.set_appearance(
                             "light" if Adw.StyleManager.get_default().get_dark() else "dark")),
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
        first = self.window is None
        win = self._ensure_window()
        win.present()
        if first and self.settings.continue_session:
            win.restore_session()

    def do_open(self, files, _n, _hint):        # files named on the command line: no session
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

    def set_appearance(self, mode: str):
        """"system", "light" or "dark": apply it and keep it in the preferences."""
        if mode not in ("system", "light", "dark"):
            return
        self.settings.dark_mode = mode
        self.settings.save()
        self._apply_colour_scheme()

    def _apply_colour_scheme(self):
        sm = Adw.StyleManager.get_default()
        sm.set_color_scheme({"light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}.get(
            self.settings.dark_mode, Adw.ColorScheme.DEFAULT))
        action = self.lookup_action("appearance")
        if action is not None:
            action.set_state(GLib.Variant.new_string(self.settings.dark_mode))

    # ------------------------------------------------------------------ dialogs
    def _about(self, *_):
        about = Adw.AboutDialog(application_name="Linux64Studio", version=__version__,
                                application_icon=APP_ID,
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
                                              "workspaces). Point this at KickAss.jar, or leave it unset to use "
                                              "the one tools/install-kickassembler.sh installs.")
        from ..project.build import default_kickass_jar
        installed = default_kickass_jar()
        unset = f"Not set: using {installed}" if installed else "Not set"
        jar = Adw.ActionRow(title="KickAss.jar", subtitle=s.kickass_jar or unset)
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
        resume = Adw.SwitchRow(title="Continue where I left off",
                               subtitle="At start, open the last project and files, with the cursor where it was",
                               active=s.continue_session)
        complete = Adw.SwitchRow(title="Suggest completions as you type",
                                 subtitle="Labels, constants, macros, instructions and directives. Ctrl+Space "
                                          "shows them at any time", active=s.auto_complete)
        scheme = Adw.ComboRow(title="Appearance", model=Gtk.StringList.new(["Follow system", "Light", "Dark"]),
                              selected=["system", "light", "dark"].index(s.dark_mode)
                              if s.dark_mode in ("system", "light", "dark") else 0)
        for w in (font, tabw, spaces, complete, save_first, resume, scheme):
            ed.add(w)
        page.add(ed)
        pb = Adw.PreferencesGroup(title="BASIC")
        auto_num = Adw.SwitchRow(title="Number new lines", active=s.basic_auto_number,
                                 subtitle="Return at the end of a line starts the next one with a line number "
                                          "(Shift+Return doesn't)")
        num_step = Adw.SpinRow.new_with_range(1, 1000, 1)
        num_step.set_title("Line number step")
        num_step.set_value(s.basic_number_step)
        pb.add(auto_num)
        pb.add(num_step)
        uncompress_lower = Adw.SwitchRow(title="Uncompress to lower case", active=s.basic_uncompress_lowercase,
                                         subtitle="Uncompress writes keywords in lower case (off: upper case)")
        pb.add(uncompress_lower)
        pb_start = Adw.SpinRow.new_with_range(0, 63999, 1)
        pb_start.set_title("pBASIC: first line number")
        pb_start.set_value(s.pbasic_start)
        pb_step = Adw.SpinRow.new_with_range(1, 1000, 1)
        pb_step.set_title("pBASIC: increment")
        pb_step.set_value(s.pbasic_step)
        pb_prefix = Adw.EntryRow(title="pBASIC: label prefix (best left as @)", text=s.pbasic_prefix)
        pb_preview = Adw.SwitchRow(title="pBASIC: preview generation",
                                   subtitle="Show the numbered BASIC after building", active=s.pbasic_preview)
        for w in (pb_start, pb_step, pb_prefix, pb_preview):
            pb.add(w)
        page.add(pb)
        from ..basic.codestyles import STYLES
        style_keys = list(STYLES)
        codes = Adw.ComboRow(title="Control codes in BASIC", subtitle="How listings and the Screen Code Builder "
                                                                       "write them (all three are read)",
                             model=Gtk.StringList.new(list(STYLES.values())),
                             selected=style_keys.index(s.basic_code_style) if s.basic_code_style in STYLES else 0)
        pb.add(codes)

        def closed(*_):
            s.emulator = emu_path.get_text().strip() or "x64sc"
            s.emulator_args = emu_args.get_text().split()
            sub = jar.get_subtitle()
            s.kickass_jar = "" if sub.startswith("Not set") else sub
            s.java = java.get_text().strip() or "java"
            s.goattracker_dir = gt_dir.get_text().strip()
            s.vsid = vsid.get_text().strip() or "vsid"
            s.font = font.get_text().strip() or "Monospace 11"
            s.tab_width = int(tabw.get_value())
            s.insert_spaces = spaces.get_active()
            s.save_before_build = save_first.get_active()
            s.continue_session = resume.get_active()
            s.auto_complete = complete.get_active()
            s.pbasic_start = int(pb_start.get_value())
            s.pbasic_step = int(pb_step.get_value())
            prefix = pb_prefix.get_text().strip()
            s.pbasic_prefix = prefix if prefix and not prefix.isalnum() and " " not in prefix else "@"
            s.pbasic_preview = pb_preview.get_active()
            s.basic_auto_number = auto_num.get_active()
            s.basic_number_step = int(num_step.get_value())
            s.basic_uncompress_lowercase = uncompress_lower.get_active()
            s.basic_code_style = style_keys[codes.get_selected()]
            s.dark_mode = ["system", "light", "dark"][scheme.get_selected()]
            s.user_tools = [t.to_dict() for t in tools_page.tools()]
            s.git_author, s.git_email = git_author.get_text().strip(), git_email.get_text().strip()
            s.git_auto_add = git_add.get_active()
            ib = ignore_view.get_buffer()
            ignore_text = ib.get_text(ib.get_start_iter(), ib.get_end_iter(), False)
            s.git_ignore = "" if ignore_text.strip() == DEFAULT_IGNORE.strip() else ignore_text
            s.save()
            self._apply_colour_scheme()
            if self.window and hasattr(self.window, "refresh_user_tools"):
                self.window.refresh_user_tools()
        dlg.connect("closed", closed)
        from .usertools_prefs import UserToolsPage
        tools_page = UserToolsPage(s.user_tools)
        dlg.add(tools_page)
        from ..gitrepo import DEFAULT_IGNORE
        gp = Adw.PreferencesPage(title="Git", icon_name="emblem-shared-symbolic")
        gg = Adw.PreferencesGroup(title="Git", description="For the Git menu and the file list's Git commands.")
        git_author = Adw.EntryRow(title="Author (empty: git's own user.name)", text=s.git_author)
        git_email = Adw.EntryRow(title="Email (empty: git's own user.email)", text=s.git_email)
        git_add = Adw.SwitchRow(title="Add changed files before committing", active=s.git_auto_add)
        for w in (git_author, git_email, git_add):
            gg.add(w)
        gp.add(gg)
        ig = Adw.PreferencesGroup(title="Ignore list for new repositories",
                                  description="Files Git leaves alone. {now}, {author}, {comment} and {project} "
                                              "are filled in when a repository is made.")
        ignore_view = Gtk.TextView(monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                                   css_classes=["card"])
        ignore_view.set_size_request(-1, 160)
        ignore_view.get_buffer().set_text(s.git_ignore or DEFAULT_IGNORE)
        ig.add(ignore_view)
        gp.add(ig)
        dlg.add(gp)
        dlg.present(self.window)


def main(argv: list[str] | None = None) -> int:
    app = Application()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
