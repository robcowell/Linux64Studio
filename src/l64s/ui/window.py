"""The main IDE window."""
from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

from ..emu import vice  # noqa: E402
from ..project.build import BuildResult, build_project  # noqa: E402
from ..project.model import (TOOLCHAIN_CBM, TOOLCHAIN_KICKASS, Project, load_project,  # noqa: E402
                             new_project)
from .charpad_editor import CharPadEditor  # noqa: E402
from .charset_editor import CharsetEditor  # noqa: E402
from .debugger import DebuggerPanel, DebugSession  # noqa: E402
from .editor import HAVE_SOURCEVIEW, EditorPage, SourceEditor  # noqa: E402
from .screen_editor import ScreenEditor  # noqa: E402
from .sprite_editor import SpriteEditor  # noqa: E402

SOURCE_EXTS = {".asm", ".s", ".a", ".inc", ".txt", ".bas", ".lst"}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, settings):
        super().__init__(application=app, title="Linux64Studio",
                         default_width=settings.window_width, default_height=settings.window_height)
        self.settings = settings
        self.project: Project | None = None
        self.pages: dict[str, Adw.TabPage] = {}  # resolved path -> tab
        self.debug: DebugSession | None = None
        self.last_build: BuildResult | None = None
        self._vice_procs = []
        self._build_ui()
        self.connect("close-request", self._on_close_request)
        self._update_title()

    # ================================================================== UI construction
    def _build_ui(self):
        tv = Adw.ToolbarView()
        self.set_content(tv)
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)

        open_btn = Adw.SplitButton(label="Open", tooltip_text="Open a project (Ctrl+O)",
                                   action_name="win.open-project")
        self.recent_menu = Gio.Menu()
        open_btn.set_menu_model(self.recent_menu)
        hb.pack_start(open_btn)
        new_menu = Gio.Menu()
        new_menu.append("New Project…", "win.new-project")
        new_menu.append("New Source File…", "win.new-file::asm")
        new_menu.append("New Sprite Set…", "win.new-file::spt")
        new_menu.append("New Character Set…", "win.new-file::cst")
        new_menu.append("New Screen Design…", "win.new-file::sdd")
        hb.pack_start(Gtk.MenuButton(icon_name="document-new-symbolic", menu_model=new_menu, tooltip_text="New"))
        save_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save (Ctrl+S)", action_name="win.save")
        hb.pack_start(save_btn)

        self.title_widget = Adw.WindowTitle(title="Linux64Studio", subtitle="")
        hb.set_title_widget(self.title_widget)

        menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append("Build Project", "win.build-project")
        sec.append("Build Current File", "win.build-file")
        sec.append("Build Project and Run", "win.run-project")
        sec.append("Build Current File and Run", "win.run-file")
        sec.append("Debug Project", "win.debug-project")
        menu.append_section(None, sec)
        sec2 = Gio.Menu()
        sec2.append("Project Properties…", "win.project-properties")
        sec2.append("Open File…", "win.open-file")
        sec2.append("Save All", "win.save-all")
        sec2.append("Close Project", "win.close-project")
        menu.append_section(None, sec2)
        sec3 = Gio.Menu()
        sec3.append("Preferences", "app.preferences")
        sec3.append("Keyboard Shortcuts", "app.shortcuts")
        sec3.append("About Linux64Studio", "app.about")
        menu.append_section(None, sec3)
        hb.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True))
        hb.pack_end(Gtk.Button(icon_name="system-run-symbolic", tooltip_text="Debug project (Shift+F5)",
                               action_name="win.debug-project"))
        run = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Build project and run (Ctrl+F5)",
                         action_name="win.run-project")
        run.add_css_class("suggested-action")
        hb.pack_end(run)
        hb.pack_end(Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Build project (F7)",
                               action_name="win.build-project"))

        self.toasts = Adw.ToastOverlay()
        tv.set_content(self.toasts)
        if not HAVE_SOURCEVIEW:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            banner = Adw.Banner(title="Install gir1.2-gtksource-5 for syntax highlighting, line numbers and breakpoints",
                                revealed=True)
            box.append(banner)
            self.toasts.set_child(box)
            container = box
        else:
            container = None

        outer = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=240, vexpand=True)
        if container:
            container.append(outer)
        else:
            self.toasts.set_child(outer)

        # ---------- project sidebar
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar_title = Gtk.Label(label="No project", xalign=0, margin_start=10, margin_top=8, margin_bottom=4,
                                       ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"])
        side.append(self.sidebar_title)
        self.file_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.file_list.connect("row-activated", self._on_file_activated)
        side.append(Gtk.ScrolledWindow(child=self.file_list, vexpand=True))
        outer.set_start_child(side)
        outer.set_shrink_start_child(False)

        # ---------- editors + bottom panel
        right = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        outer.set_end_child(right)
        tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tab_view = Adw.TabView(vexpand=True)
        self.tab_view.connect("close-page", self._on_close_page)
        self.tab_view.connect("notify::selected-page", lambda *_: self._update_title())
        tab_bar = Adw.TabBar(view=self.tab_view, autohide=False)
        tabs_box.append(tab_bar)
        self.empty = Adw.StatusPage(icon_name="applications-games-symbolic", title="Linux64Studio",
                                    description="Open a project (a CBM prg Studio .cbmprj works) or create a new one.\n"
                                                "Ctrl+F5 builds and runs the project in VICE.", vexpand=True)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(self.tab_view, "tabs")
        tabs_box.append(self.stack)
        tab_bar.set_visible(False)
        self.tab_bar = tab_bar
        right.set_start_child(tabs_box)
        right.set_resize_start_child(True)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.bottom_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.bottom_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        sw_bar = Gtk.CenterBox(start_widget=switcher)
        bottom.append(sw_bar)
        # output page
        out = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=560)
        self.diag_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.diag_list.connect("row-activated", self._on_diag_activated)
        out.set_start_child(Gtk.ScrolledWindow(child=self.diag_list, min_content_height=140))
        self.log = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        out.set_end_child(Gtk.ScrolledWindow(child=self.log))
        self.bottom_stack.add_titled_with_icon(out, "output", "Build Output", "dialog-information-symbolic")
        self.debugger = DebuggerPanel()
        self.debugger.connect("show-source", self._on_show_source)
        self.bottom_stack.add_titled_with_icon(self.debugger, "debugger", "Debugger", "system-run-symbolic")
        bottom.append(self.bottom_stack)
        bottom.set_vexpand(True)
        right.set_end_child(bottom)
        right.set_position(int(self.settings.window_height * 0.62))
        self._pc_editor: SourceEditor | None = None

        self._install_actions()
        self._refresh_recent()

    def _install_actions(self):
        def add(name, cb, param=None):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
            a.connect("activate", cb)
            self.add_action(a)
        add("open-project", lambda *_: self.choose_project())
        add("open-recent", lambda _a, v: self.open_project(Path(v.get_string())), "s")
        add("open-file", lambda *_: self.choose_file())
        add("new-project", lambda *_: self.new_project_dialog())
        add("new-file", lambda _a, v: self.new_file_dialog(v.get_string()), "s")
        add("save", lambda *_: self.save_current())
        add("save-all", lambda *_: self.save_all())
        add("close-tab", lambda *_: self._close_current_tab())
        add("close-project", lambda *_: self.close_project())
        add("build-project", lambda *_: self.build(run=False))
        add("build-file", lambda *_: self.build(run=False, current_file=True))
        add("run-project", lambda *_: self.build(run=True))
        add("run-file", lambda *_: self.build(run=True, current_file=True))
        add("debug-project", lambda *_: self.build(run=True, debug=True))
        add("toggle-breakpoint", lambda *_: self._toggle_breakpoint())
        add("debug-continue", lambda *_: self.debugger.do("continue"))
        add("debug-over", lambda *_: self.debugger.do("over"))
        add("debug-into", lambda *_: self.debugger.do("into"))
        add("debug-out", lambda *_: self.debugger.do("out"))
        add("project-properties", lambda *_: self.project_properties())
        add("goto-line", lambda *_: self._goto_line_dialog())

    # ================================================================== projects
    def _refresh_recent(self):
        self.recent_menu.remove_all()
        for p in self.settings.recent_projects:
            if Path(p).exists():
                self.recent_menu.append(Path(p).name + "  —  " + str(Path(p).parent), f"win.open-recent('{p}')"
                                        if "'" not in p else None)

    def choose_project(self):
        dlg = Gtk.FileDialog(title="Open Project")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter(name="Projects (.l64proj, .cbmprj, .code-workspace)")
        for pat in ("*.l64proj", "*.cbmprj", "*.code-workspace"):
            f.add_pattern(pat)
        filters.append(f)
        f2 = Gtk.FileFilter(name="Assembler source (.asm)")
        f2.add_pattern("*.asm")
        filters.append(f2)
        dlg.set_filters(filters)

        def done(d, res):
            try:
                self.open_project(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self, None, done)

    def open_project(self, path: Path):
        if not self._confirm_discard_all():
            return
        try:
            proj = load_project(path)
        except Exception as e:  # report any bad project file instead of crashing
            self.toast(f"Couldn't open {path.name}: {e}")
            return
        self._close_all_tabs(force=True)
        self.project = proj
        self.settings.add_recent(str(path.resolve()))
        self.settings.save()
        self._refresh_recent()
        self._populate_files()
        self._update_title()
        first = (proj.build_paths()[:1] if proj.toolchain == TOOLCHAIN_CBM
                 else [proj.directory / proj.main_file] if proj.main_file else [])
        for p in first:
            if p.exists():
                self.open_file(p)
        if proj.imported_from:
            self.toast(f"Opened {proj.imported_from}. Settings are saved to {proj.settings_path().name}")

    def close_project(self):
        if not self._confirm_discard_all():
            return
        self._close_all_tabs(force=True)
        self.project = None
        self._populate_files()
        self._update_title()

    def _populate_files(self):
        while (row := self.file_list.get_row_at_index(0)) is not None:
            self.file_list.remove(row)
        if not self.project:
            self.sidebar_title.set_text("No project")
            return
        p = self.project
        self.sidebar_title.set_text(p.name + ("  (Kick Assembler)" if p.toolchain == TOOLCHAIN_KICKASS else ""))
        build = {str((p.directory / n).resolve()): i for i, n in enumerate(p.build_list)}
        files = p.all_files()
        groups = [("Source", lambda f: f.suffix.lower() in SOURCE_EXTS),
                  ("Graphics", lambda f: f.suffix.lower() in (".spt", ".cst", ".sdd", ".spd", ".ctm")),
                  ("Binary", lambda f: f.suffix.lower() == ".bin")]
        for title, pred in groups:
            members = [f for f in files if pred(f)]
            if not members:
                continue
            if p.toolchain == TOOLCHAIN_CBM and title == "Source":
                members.sort(key=lambda f: (build.get(str(f.resolve()), 999), f.name.lower()))
            hdr = Gtk.Label(label=title, xalign=0, css_classes=["dim-label", "caption-heading"],
                            margin_start=8, margin_top=8)
            row = Gtk.ListBoxRow(child=hdr, activatable=False, selectable=False)
            self.file_list.append(row)
            for f in members:
                try:
                    rel = f.relative_to(p.directory)
                except ValueError:
                    rel = Path(f.name)
                box = Gtk.Box(spacing=6, margin_start=6)
                icon = {"Source": "text-x-generic-symbolic", "Graphics": "image-x-generic-symbolic"}.get(
                    title, "application-x-executable-symbolic")
                box.append(Gtk.Image(icon_name=icon))
                lbl = Gtk.Label(label=str(rel), xalign=0, ellipsize=Pango.EllipsizeMode.START, hexpand=True)
                box.append(lbl)
                bi = build.get(str(f.resolve()))
                if bi is not None:
                    box.append(Gtk.Label(label=str(bi + 1), css_classes=["dim-label", "caption"],
                                         tooltip_text="Position in the build order", margin_end=6))
                r = Gtk.ListBoxRow(child=box)
                r.path = f
                self.file_list.append(r)

    def _on_file_activated(self, _lb, row):
        path = getattr(row, "path", None)
        if path:
            self.open_file(path)

    def _update_title(self):
        page = self.tab_view.get_selected_page()
        sub = ""
        if page:
            ed: EditorPage = page.get_child()
            sub = str(ed.path) if ed.path else ed.title
        self.title_widget.set_title(self.project.name if self.project else "Linux64Studio")
        self.title_widget.set_subtitle(sub)
        has_tabs = self.tab_view.get_n_pages() > 0
        self.stack.set_visible_child_name("tabs" if has_tabs else "empty")
        self.tab_bar.set_visible(has_tabs)

    # ================================================================== files and tabs
    def choose_file(self):
        dlg = Gtk.FileDialog(title="Open File")
        if self.project:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.project.directory)))

        def done(d, res):
            try:
                self.open_file(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self, None, done)

    def open_file(self, path: Path) -> EditorPage | None:
        key = str(path.resolve())
        if key in self.pages:
            self.tab_view.set_selected_page(self.pages[key])
            return self.pages[key].get_child()
        sfx = path.suffix.lower()
        try:
            if sfx in (".spt", ".spd"):
                ed = SpriteEditor(path, self.project)
            elif sfx == ".cst":
                ed = CharsetEditor(path, project=self.project)
            elif sfx == ".ctm":
                ed = CharPadEditor(path, self.project)
            elif sfx == ".sdd":
                charsets = [f for f in (self.project.all_files() if self.project else [])
                            if f.suffix.lower() in (".cst",) or f.name.lower().startswith("char") and f.suffix == ".bin"]
                charsets.sort(key=lambda f: (f.parent != path.parent, f.suffix != ".cst"))
                ed = ScreenEditor(path, charsets)
            elif sfx == ".bin":
                return self._open_bin(path)
            else:
                ed = SourceEditor(path, self.settings)
                ed.connect("breakpoints-changed", self._on_breakpoints_changed)
        except Exception as e:  # unreadable/corrupt file
            self.toast(f"Couldn't open {path.name}: {e}")
            return None
        return self._add_page(ed)

    def _open_bin(self, path: Path):
        """A .bin could be sprites or characters; ask which editor to use."""
        dlg = Adw.AlertDialog(heading=f"Open {path.name} as…",
                              body="Raw binary files don't say what they contain.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("chars", "Characters")
        dlg.add_response("sprites", "Sprites")
        guess = "sprites" if "sprite" in path.name.lower() else "chars"
        dlg.set_default_response(guess)

        def chosen(d, res):
            r = d.choose_finish(res)
            if r == "sprites":
                self._add_page(SpriteEditor(path, self.project))
            elif r == "chars":
                self._add_page(CharsetEditor(path, project=self.project))
        dlg.choose(self, None, chosen)
        return None

    def _add_page(self, ed: EditorPage) -> EditorPage:
        page = self.tab_view.append(ed)
        page.set_title(ed.title)
        page.set_tooltip(str(ed.path) if ed.path else ed.title)
        icon = {"source": "text-x-generic-symbolic", "sprites": "image-x-generic-symbolic",
                "charset": "font-x-generic-symbolic", "screen": "video-display-symbolic",
                "charpad": "font-x-generic-symbolic"}.get(ed.kind)
        if icon:
            page.set_icon(Gio.ThemedIcon.new(icon))
        ed.connect("modified-changed", lambda e: page.set_title(("● " if e.modified else "") + e.title))
        if ed.path:
            self.pages[str(ed.path.resolve())] = page
        self.tab_view.set_selected_page(page)
        self._update_title()
        return ed

    def current_editor(self) -> EditorPage | None:
        page = self.tab_view.get_selected_page()
        return page.get_child() if page else None

    def editors(self) -> list[EditorPage]:
        return [self.tab_view.get_nth_page(i).get_child() for i in range(self.tab_view.get_n_pages())]

    def save_current(self):
        ed = self.current_editor()
        if ed:
            self._save(ed)

    def _save(self, ed: EditorPage) -> bool:
        if not ed.path:
            return False
        try:
            extra = ed.save() or []
        except Exception as e:
            self.toast(f"Couldn't save {ed.title}: {e}")
            return False
        if extra:
            self.toast(f"Saved {ed.title} and updated {', '.join(p.name for p in extra)}")
        return True

    def save_all(self):
        for ed in self.editors():
            if ed.modified:
                self._save(ed)

    def _close_current_tab(self):
        page = self.tab_view.get_selected_page()
        if page:
            self.tab_view.close_page(page)

    def _on_close_page(self, view, page):
        ed: EditorPage = page.get_child()
        if not ed.modified or getattr(self, "_force_close", False):
            self._forget_page(page)
            view.close_page_finish(page, True)
            GLib.idle_add(self._update_title)
            return True
        dlg = Adw.AlertDialog(heading=f"Save changes to {ed.title}?", body="Unsaved changes will be lost.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("discard", "Discard")
        dlg.add_response("save", "Save")
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("save")

        def chosen(d, res):
            r = d.choose_finish(res)
            ok = r == "discard" or (r == "save" and self._save(ed))
            if ok:
                self._forget_page(page)
            view.close_page_finish(page, ok)
            GLib.idle_add(self._update_title)
        dlg.choose(self, None, chosen)
        return True

    def _forget_page(self, page):
        ed = page.get_child()
        if ed is self._pc_editor:
            self._pc_editor = None
        for k, v in list(self.pages.items()):
            if v is page:
                del self.pages[k]

    def _close_all_tabs(self, force=False):
        self._force_close = force
        for i in reversed(range(self.tab_view.get_n_pages())):
            self.tab_view.close_page(self.tab_view.get_nth_page(i))
        self._force_close = False
        self._update_title()

    def _confirm_discard_all(self) -> bool:
        """Synchronous check used before replacing the project; saves are offered via the window close flow."""
        dirty = [e for e in self.editors() if e.modified]
        if not dirty:
            return True
        # Keep it simple and safe: save everything that has a file name.
        for e in dirty:
            self._save(e)
        return True

    def _on_close_request(self, *_):
        w, h = self.get_default_size()
        self.settings.window_width, self.settings.window_height = w, h
        self.settings.save()
        if self.debug:
            self.debug.stop()
        dirty = [e for e in self.editors() if e.modified]
        if not dirty or getattr(self, "_really_close", False):
            return False
        dlg = Adw.AlertDialog(heading="Save changes before closing?",
                              body="\n".join(e.title for e in dirty))
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("discard", "Discard")
        dlg.add_response("save", "Save All")
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            r = d.choose_finish(res)
            if r == "cancel":
                return
            if r == "save":
                self.save_all()
            self._really_close = True
            self.close()
        dlg.choose(self, None, chosen)
        return True

    # ================================================================== new things
    def new_project_dialog(self):
        win = Adw.Dialog(title="New Project", content_width=420)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        grp = Adw.PreferencesGroup()
        name = Adw.EntryRow(title="Project name", text="mygame")
        loc = Adw.ActionRow(title="Location", subtitle=str(Path.home() / "c64"))
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        loc.add_suffix(pick)
        tool = Adw.ComboRow(title="Assembler", model=Gtk.StringList.new(
            ["Built-in (CBM prg Studio syntax)", "Kick Assembler"]))
        grp.add(name)
        grp.add(loc)
        grp.add(tool)
        page.add(grp)
        btn = Gtk.Button(label="Create", css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER,
                         margin_bottom=12)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(page)
        box.append(btn)
        tv.set_content(box)
        win.set_child(tv)

        def choose(*_):
            fd = Gtk.FileDialog(title="Project location")

            def done(d, res):
                try:
                    loc.set_subtitle(d.select_folder_finish(res).get_path())
                except GLib.Error:
                    pass
            fd.select_folder(self, None, done)
        pick.connect("clicked", choose)

        def create(*_):
            n = name.get_text().strip() or "mygame"
            directory = Path(loc.get_subtitle()) / n
            tc = TOOLCHAIN_CBM if tool.get_selected() == 0 else TOOLCHAIN_KICKASS
            proj = new_project(directory, n, tc)
            win.close()
            self.open_project(proj.path)
        btn.connect("clicked", create)
        win.present(self)

    def new_file_dialog(self, kind: str):
        if not self.project:
            self.toast("Open or create a project first")
            return
        dlg = Adw.AlertDialog(heading={"asm": "New source file", "spt": "New sprite set", "cst": "New character set",
                                       "sdd": "New screen design"}[kind])
        default = {"asm": "gameNew.asm", "spt": "sprites.spt", "cst": "characters.cst", "sdd": "screens.sdd"}[kind]
        entry = Gtk.Entry(text=default, activates_default=True)
        dlg.set_extra_child(entry)
        add_build = None
        if kind == "asm" and self.project.toolchain == TOOLCHAIN_CBM:
            add_build = Gtk.CheckButton(label="Add to the build list (before the last file)", active=True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.append(entry)
            box.append(add_build)
            dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("create", "Create")
        dlg.set_default_response("create")
        dlg.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "create":
                return
            fname = entry.get_text().strip()
            if not fname:
                return
            if not fname.lower().endswith("." + kind):
                fname += "." + kind
            path = self.project.directory / fname
            if path.exists():
                self.toast(f"{fname} already exists")
                self.open_file(path)
                return
            if kind == "asm":
                path.write_text(f";===============================================================================\n; {path.stem}\n\n")
                if add_build and add_build.get_active():
                    bl = self.project.build_list
                    bl.insert(max(0, len(bl) - 1), fname)
                    self.project.save()
            elif kind == "spt":
                from ..gfx.sprite import SpriteSet
                SpriteSet().save_spt(path)
            elif kind == "cst":
                from ..gfx.charset import Charset, rom_charset
                cs = Charset()
                cs.chars = rom_charset(True) or cs.chars
                cs.save_cst(path)
            elif kind == "sdd":
                from ..gfx.screen import ScreenSet
                ScreenSet().save_sdd(path)
            self._populate_files()
            self.open_file(path)
        dlg.choose(self, None, chosen)

    # ================================================================== building and running
    def _overrides(self) -> dict[str, str]:
        return {str(e.path): e.get_text() for e in self.editors() if isinstance(e, SourceEditor) and e.path}

    def build(self, run: bool = False, current_file: bool = False, debug: bool = False):
        ed = self.current_editor()
        if not self.project:
            if isinstance(ed, SourceEditor) and ed.path:
                self.project = load_project(ed.path)
            else:
                self.toast("Open a project or an .asm file first")
                return
        only = None
        if current_file:
            if not isinstance(ed, SourceEditor) or not ed.path:
                self.toast("The current tab isn't a source file")
                return
            only = ed.path
        if self.settings.save_before_build:
            self.save_all()
        if self.debug and debug:
            self.debug.stop()
            self.debug = None
        self.bottom_stack.set_visible_child_name("output")
        self._set_log("Building…")
        overrides = self._overrides()
        proj = self.project
        settings = self.settings

        def work():
            try:
                res = build_project(proj, overrides, only, settings.kickass_jar, settings.java)
            except Exception as e:  # report internal errors in the log rather than losing them
                import traceback
                from ..asm.errors import Diagnostic
                res = BuildResult(False, None, None, [Diagnostic("error", f"Internal error: {e}", None)],
                                  traceback.format_exc())
            GLib.idle_add(self._build_done, res, run, debug)
        threading.Thread(target=work, daemon=True).start()

    def _build_done(self, res: BuildResult, run: bool, debug: bool):
        self.last_build = res
        self._set_log(res.log)
        self._show_diagnostics(res)
        if not res.ok:
            self.toast("Build failed")
            return
        if not run:
            self.toast(f"Built {res.prg.name}")
            return
        if debug:
            self._start_debug(res)
        else:
            try:
                proc = vice.launch(res.prg, self.settings.emulator, res.labels, None, self.settings.emulator_args)
                self._vice_procs.append(proc)
                self.toast(f"Running {res.prg.name} in VICE")
            except FileNotFoundError as e:
                self.toast(str(e))

    def _set_log(self, text: str):
        self.log.get_buffer().set_text(text)

    def _show_diagnostics(self, res: BuildResult):
        while (row := self.diag_list.get_row_at_index(0)) is not None:
            self.diag_list.remove(row)
        for ed in self.editors():
            if isinstance(ed, SourceEditor):
                ed.clear_errors()
        first = None
        for d in res.diagnostics:
            box = Gtk.Box(spacing=8, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
            icon = "dialog-error-symbolic" if d.severity == "error" else "dialog-warning-symbolic"
            box.append(Gtk.Image(icon_name=icon))
            where = ""
            if d.loc:
                where = f"{Path(d.loc.file).name}:{d.loc.line}"
                if d.loc.macro:
                    where += f" (macro {d.loc.macro})"
            box.append(Gtk.Label(label=where, xalign=0, css_classes=["monospace", "dim-label"]))
            box.append(Gtk.Label(label=d.message, xalign=0, wrap=True, hexpand=True))
            row = Gtk.ListBoxRow(child=box)
            row.diag = d
            self.diag_list.append(row)
            if d.loc:
                key = str(Path(d.loc.file).resolve())
                page = self.pages.get(key)
                if page and isinstance(page.get_child(), SourceEditor) and d.severity == "error":
                    page.get_child().mark_error(d.loc.line)
            if first is None and d.severity == "error":
                first = row
        if not res.diagnostics:
            self.diag_list.append(Gtk.ListBoxRow(child=Gtk.Label(
                label="No errors or warnings" if res.ok else "Build failed", margin_top=6, margin_bottom=6),
                activatable=False))
        if first is not None:
            self._on_diag_activated(self.diag_list, first)

    def _on_diag_activated(self, _lb, row):
        d = getattr(row, "diag", None)
        if d and d.loc:
            ed = self.open_file(Path(d.loc.file))
            if isinstance(ed, SourceEditor):
                ed.goto_line(d.loc.line)
                if d.severity == "error":
                    ed.mark_error(d.loc.line)

    # ================================================================== debugging
    def _all_breakpoint_addresses(self, session: DebugSession) -> set[int]:
        addrs = set()
        for ed in self.editors():
            if isinstance(ed, SourceEditor) and ed.path:
                for line in ed.breakpoint_lines():
                    a = session.address_for_line(str(ed.path), line)
                    if a is not None:
                        addrs.add(a)
        return addrs

    def _start_debug(self, res: BuildResult):
        if self.project and self.project.toolchain == TOOLCHAIN_KICKASS:
            self.toast("Source-level debugging needs the built-in assembler; running in VICE with the monitor enabled")
        symbols = {}
        if res.asm_result:
            for key, value in res.asm_result.symbols.items():
                name = res.asm_result.names.get(key, key)
                if "__m" not in key and not name.startswith("@") and value not in symbols:
                    symbols[value] = name
        session = DebugSession(res.prg, res.labels, res.srcmap, symbols, self.settings.emulator,
                               self.settings.emulator_args)
        self.debug = session
        self.debugger.attach(session)
        session.connect("ended", lambda *_: setattr(self, "debug", None))
        self.bottom_stack.set_visible_child_name("debugger")
        try:
            session.start(sorted(self._all_breakpoint_addresses(session)))
        except FileNotFoundError as e:
            self.toast(str(e))
            self.debug = None

    def _on_breakpoints_changed(self, _ed):
        if self.debug and self.debug.monitor.connected:
            self.debug.cmd(self.debug.set_breakpoints, self._all_breakpoint_addresses(self.debug))

    def _toggle_breakpoint(self):
        ed = self.current_editor()
        if isinstance(ed, SourceEditor):
            ed.toggle_breakpoint()

    def _on_show_source(self, _panel, file: str, line: int):
        if self._pc_editor:
            self._pc_editor.set_pc_line(None)
            self._pc_editor = None
        if not file:
            return
        ed = self.open_file(Path(file))
        if isinstance(ed, SourceEditor):
            ed.set_pc_line(line)
            self._pc_editor = ed

    # ================================================================== misc dialogs
    def _goto_line_dialog(self):
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor):
            return
        dlg = Adw.AlertDialog(heading="Go to line")
        entry = Gtk.Entry(input_purpose=Gtk.InputPurpose.DIGITS, activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("go", "Go")
        dlg.set_default_response("go")

        def chosen(d, res):
            if d.choose_finish(res) == "go" and entry.get_text().strip().isdigit():
                ed.goto_line(int(entry.get_text()))
        dlg.choose(self, None, chosen)

    def project_properties(self):
        if not self.project:
            self.toast("No project open")
            return
        p = self.project
        win = Adw.PreferencesDialog(title="Project Properties")
        page = Adw.PreferencesPage(title="Project", icon_name="document-properties-symbolic")
        win.add(page)
        g = Adw.PreferencesGroup(title="Output")
        exe = Adw.EntryRow(title="Program file (.prg)", text=p.executable)
        g.add(exe)
        page.add(g)
        tool = Adw.ComboRow(title="Assembler", model=Gtk.StringList.new(
            ["Built-in (CBM prg Studio syntax)", "Kick Assembler"]),
            selected=0 if p.toolchain == TOOLCHAIN_CBM else 1)
        g.add(tool)
        main = Adw.EntryRow(title="Main file (Kick Assembler)", text=p.main_file)
        g.add(main)

        bg = Adw.PreferencesGroup(title="Build order",
                                  description="Files are assembled together in this order, like CBM prg Studio's "
                                              "build list. Labels and macros are shared between them.")
        page.add(bg)
        order = list(p.build_list)
        rows: list[Adw.ActionRow] = []

        def rebuild():
            for r in rows:
                bg.remove(r)
            rows.clear()
            for i, name in enumerate(order):
                r = Adw.ActionRow(title=name, subtitle=f"{i + 1}")
                for icon, delta in (("go-up-symbolic", -1), ("go-down-symbolic", 1)):
                    b = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, css_classes=["flat"])
                    b.connect("clicked", move, i, delta)
                    r.add_suffix(b)
                rm = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
                rm.connect("clicked", remove, i)
                r.add_suffix(rm)
                bg.add(r)
                rows.append(r)
            add_row = Adw.ComboRow(title="Add file")
            candidates = [str(f.relative_to(p.directory)) for f in p.all_files()
                          if f.suffix.lower() in (".asm", ".s") and str(f.relative_to(p.directory)) not in order]
            add_row.set_model(Gtk.StringList.new(["—"] + candidates))
            add_row.connect("notify::selected", lambda r, _ps: (r.get_selected() > 0 and (
                order.append(candidates[r.get_selected() - 1]), GLib.idle_add(rebuild))))
            bg.add(add_row)
            rows.append(add_row)

        def move(_b, i, delta):
            j = i + delta
            if 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
                rebuild()

        def remove(_b, i):
            del order[i]
            rebuild()
        rebuild()

        def closed(*_):
            p.executable = exe.get_text().strip() or p.executable
            p.toolchain = TOOLCHAIN_CBM if tool.get_selected() == 0 else TOOLCHAIN_KICKASS
            p.main_file = main.get_text().strip()
            p.build_list = list(order)
            try:
                p.save()
            except OSError as e:
                self.toast(f"Couldn't save project settings: {e}")
            self._populate_files()
        win.connect("closed", closed)
        win.present(self)

    def toast(self, text: str):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))
