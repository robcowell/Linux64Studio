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
from .cart_view import CartView  # noqa: E402
from .charpad_editor import CharPadEditor  # noqa: E402
from .charset_editor import CharsetEditor  # noqa: E402
from .debugger import DebuggerPanel, DebugSession  # noqa: E402
from .disk_editor import DiskEditor  # noqa: E402
from .editor import HAVE_SOURCEVIEW, EditorPage, SourceEditor  # noqa: E402
from .screen_editor import ScreenEditor  # noqa: E402
from .binary_tool import BinaryTool  # noqa: E402
from .analyser_view import SourceAnalyser  # noqa: E402
from .datagen_view import DataGenerator  # noqa: E402
from .disassembler_view import DisassemblerView  # noqa: E402
from .memory_manager import MemoryManager  # noqa: E402
from .snapshot_manager import SnapshotManager  # noqa: E402
from .snippets_view import SnippetsView  # noqa: E402
from .strformat_view import StringFormatter  # noqa: E402
from .sysgen_view import SysCallGenerator  # noqa: E402
from .memory_viewer import MemoryViewer  # noqa: E402
from .screen_calculator import ScreenCalculator  # noqa: E402
from .screencode_builder import ScreenCodeBuilder  # noqa: E402
from .sid_designer import SidDesigner  # noqa: E402
from .sid_view import SfxView, SidFileView, SongView  # noqa: E402
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
        new_menu.append("New BASIC File…", "win.new-file::bas")
        new_menu.append("New Sprite Set…", "win.new-file::spt")
        new_menu.append("New Character Set…", "win.new-file::cst")
        new_menu.append("New Screen Design…", "win.new-file::sdd")
        new_menu.append("New Disk Image…", "win.new-file::d64")
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
        sec2.append("List BASIC Program (.prg)…", "win.list-prg")
        sec2.append("Renumber BASIC…", "win.renumber")
        sec2.append("Screen Code Builder", "win.screen-codes")
        sec2.append("Screen Calculator", "win.screen-calculator")
        sec2.append("Code Snippets", "win.snippets")
        sec2.append("SYS() Call Generator", "win.sys-call")
        sec2.append("Data Generator", "win.data-generator")
        sec2.append("String Formatter", "win.string-formatter")
        sec2.append("Source Analyser", "win.source-analyser")
        sec2.append("Memory Viewer", "win.memory-viewer")
        sec2.append("Memory Manager", "win.memory-manager")
        sec2.append("Snapshots", "win.snapshots")
        sec2.append("Binary Import/Export", "win.binary-tool")
        sec2.append("Disassembler", "win.disassembler")
        sec2.append("SID Designer", "win.sid-designer")
        sec2.append("Compose in SidMonkey", "win.music-app::sidmonkey")
        sec2.append("Open GoatTracker", "win.music-app::goattrk2")
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
        self.tab_view.connect("notify::selected-page", lambda *_: self._on_tab_selected())
        self._last_source: SourceEditor | None = None
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
        add("renumber", lambda *_: self.renumber_dialog())
        add("music-app", lambda _a, v: self._music_app(v.get_string()), "s")
        add("screen-codes", lambda *_: self.open_screen_code_builder())
        add("screen-calculator", lambda *_: self.open_screen_calculator())
        add("snippets", lambda *_: self.open_snippets())
        add("sys-call", lambda *_: self.open_sys_call())
        add("data-generator", lambda *_: self.open_data_generator())
        add("string-formatter", lambda *_: self.open_string_formatter())
        add("source-analyser", lambda *_: self.open_source_analyser())
        add("analyse-here", lambda *_: self.analyse_from_editor())
        add("memory-viewer", lambda *_: self.open_memory_viewer())
        add("memory-manager", lambda *_: self.open_memory_manager())
        add("snapshots", lambda *_: self.open_snapshots())
        add("binary-tool", lambda *_: self.open_binary_tool())
        add("disassembler", lambda *_: self.open_disassembler())
        add("sid-designer", lambda *_: self.open_sid_designer())
        add("list-prg", lambda *_: self.choose_prg_to_list())

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
                  ("Binary", lambda f: f.suffix.lower() == ".bin"),
                  ("Music", lambda f: f.suffix.lower() in (".sng", ".ins", ".sid", ".l64sid")),
                  ("Programs", lambda f: f.suffix.lower() in (".prg", ".d64", ".d71", ".d81", ".crt"))]
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
                icon = {"Source": "text-x-generic-symbolic", "Graphics": "image-x-generic-symbolic",
                        "Music": "audio-x-generic-symbolic"}.get(title, "application-x-executable-symbolic")
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
            elif sfx == ".prg":
                return self._open_prg(path)
            elif sfx == ".sid":
                ed = SidFileView(path, self.settings, self.project)
            elif sfx == ".l64sid":
                ed = self._sid_designer(path)
            elif sfx == ".sng":
                ed = SongView(path, self.settings, self.project, self._save_project_quietly)
            elif sfx == ".ins":
                ed = SfxView(path, self.settings, self.project, self._save_project_quietly)
            elif sfx == ".crt":
                ed = CartView(path)
                ed.connect("run-cart", lambda e: self._launch(e.path))
            elif sfx in (".d64", ".d71", ".d81"):
                ed = DiskEditor(path)
                ed.connect("run-disk", self._run_disk_editor)
                ed.connect("list-basic", lambda _e, name, data: self.list_program_bytes(
                    data, path.parent / f"{name.lower() or 'program'}.bas", f"{name} on {path.name}"))
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
        dlg.add_response("import", "Import as Source")
        dlg.add_response("chars", "Characters")
        dlg.add_response("sprites", "Sprites")
        guess = "sprites" if "sprite" in path.name.lower() else "chars"
        dlg.set_default_response(guess)

        def chosen(d, res):
            r = d.choose_finish(res)
            if r == "import":
                self.open_binary_tool(path)
            elif r == "sprites":
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
                "charpad": "font-x-generic-symbolic", "disk": "media-floppy-symbolic",
                "cart": "media-flash-symbolic", "sid": "audio-x-generic-symbolic",
                "song": "audio-x-generic-symbolic", "sfx": "audio-x-generic-symbolic",
                "screencodes": "insert-text-symbolic", "screencalc": "accessories-calculator-symbolic", "snippets": "edit-paste-symbolic", "sysgen": "system-run-symbolic", "datagen": "x-office-spreadsheet-symbolic", "strformat": "format-justify-left-symbolic", "analyser": "utilities-system-monitor-symbolic", "memory": "drive-harddisk-symbolic",
                "binary": "document-open-symbolic", "disasm": "system-search-symbolic",
                "memmgr": "view-grid-symbolic", "snapshots": "camera-photo-symbolic",
                "siddesigner": "audio-speakers-symbolic"}.get(ed.kind)
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
        tool = Adw.ComboRow(title="Type", model=Gtk.StringList.new(
            ["Assembler (CBM prg Studio syntax)", "Kick Assembler", "BASIC V2", "Cartridge, 8K (assembler)"]))
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
            sel = tool.get_selected()
            tc = TOOLCHAIN_KICKASS if sel == 1 else TOOLCHAIN_CBM
            proj = new_project(directory, n, tc, basic=sel == 2, cartridge=sel == 3)
            win.close()
            self.open_project(proj.path)
        btn.connect("clicked", create)
        win.present(self)

    def new_file_dialog(self, kind: str):
        if not self.project:
            self.toast("Open or create a project first")
            return
        dlg = Adw.AlertDialog(heading={"asm": "New source file", "bas": "New BASIC file", "spt": "New sprite set",
                                       "cst": "New character set", "sdd": "New screen design",
                                       "d64": "New disk image (.d64, .d71 or .d81)"}[kind])
        default = {"asm": "gameNew.asm", "bas": "main.bas", "spt": "sprites.spt", "cst": "characters.cst",
                   "sdd": "screens.sdd", "d64": "disk.d64"}[kind]
        entry = Gtk.Entry(text=default, activates_default=True)
        dlg.set_extra_child(entry)
        add_build = None
        if kind in ("asm", "bas") and self.project.toolchain == TOOLCHAIN_CBM:
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
            exts = (".d64", ".d71", ".d81") if kind == "d64" else ("." + kind,)
            if not fname.lower().endswith(exts):
                fname += "." + kind
            path = self.project.directory / fname
            if path.exists():
                self.toast(f"{fname} already exists")
                self.open_file(path)
                return
            if kind in ("asm", "bas"):
                if kind == "asm":
                    path.write_text(f";===============================================================================\n; {path.stem}\n\n")
                else:
                    path.write_text(f"10 rem {path.stem}\n")
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
            elif kind == "d64":
                from ..disk.image import DiskImage, format_for
                d = DiskImage(format_for(path))
                d.format(self.project.name[:16], "00")
                d.save(path)
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
                res = build_project(proj, overrides, only, settings.kickass_jar, settings.java,
                                    settings.goattracker_dir)
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
            self._launch(res.run_target(self.project) if self.project else res.prg, res.labels)

    def _launch(self, target: Path, labels: Path | None = None):
        try:
            proc = vice.launch(target, self.settings.emulator, labels, None, self.settings.emulator_args)
            self._vice_procs.append(proc)
            self.toast(f"Running {target.name} in VICE")
        except FileNotFoundError as e:
            self.toast(str(e))

    def _run_disk_editor(self, ed: DiskEditor):
        if ed.modified:
            self._save(ed)
        self._launch(ed.path)

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
        start = res.run_target(self.project) if self.project else res.prg
        session = DebugSession(start, res.labels, res.srcmap, symbols, self.settings.emulator,
                               self.settings.emulator_args)
        self.debug = session
        self.debugger.attach(session)
        pending = getattr(self, "_pending_snapshot", None)
        if pending:
            self._pending_snapshot = None
            session.connect("connected", lambda s, p=pending: s.cmd(s.restore_snapshot, p))
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

    # ================================================================== screen code builder
    def _on_tab_selected(self):
        ed = self.current_editor()
        if isinstance(ed, SourceEditor):
            self._last_source = ed
        self._update_title()

    def open_screen_code_builder(self):
        for ed in self.editors():
            if isinstance(ed, ScreenCodeBuilder):
                self.tab_view.set_selected_page(self.tab_view.get_page(ed))
                return ed
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(ScreenCodeBuilder(kickass, self._insert_into_last_source))

    def open_screen_calculator(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, ScreenCalculator)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            return tool
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)

        def layout():
            mm = next((ed for ed in self.editors() if isinstance(ed, MemoryManager)), None)
            return mm.layout if mm else None
        return self._add_page(ScreenCalculator(kickass, lambda: self.debug, layout, self._insert_into_last_source))

    def open_snippets(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, SnippetsView)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            return tool
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(SnippetsView(kickass, self._insert_into_last_source, self._last_source_editor))

    def open_sys_call(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, SysCallGenerator)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            return tool
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(SysCallGenerator(kickass, self._insert_into_last_source, self._last_source_editor,
                                               lambda: self._memory_of_last_build()[1]))

    def open_data_generator(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, DataGenerator)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            return tool
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(DataGenerator(kickass, self._insert_into_last_source))

    def open_string_formatter(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, StringFormatter)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            tool.follow_target()
            return tool
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(StringFormatter(kickass, self._insert_into_last_source, self._last_source_editor))

    def open_source_analyser(self) -> SourceAnalyser:
        tool = next((ed for ed in self.editors() if isinstance(ed, SourceAnalyser)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            return tool
        tool = self._add_page(SourceAnalyser(self._analysis_request, self._open_source_line))
        if not self.project:
            tool.set_scope("file")
        return tool

    def analyse_from_editor(self):
        """The editor's right-click Analyse: the selected lines, or else the whole file."""
        ed = self._last_source_editor()
        scope = "selection" if ed is not None and ed.buffer.get_has_selection() else "file"
        self.open_source_analyser().run(scope)

    def _analysis_request(self, scope: str):
        """The arguments for analyser.analyse() for a scope, or why it can't be done."""
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        build = self.project.build_paths() if self.project else []
        if kickass and self.project.main_file:
            from ..analyser import kickass_sources
            build = kickass_sources(self.project.directory / self.project.main_file,
                                    [self.project.directory / d for d in self.project.lib_dirs])
        req = {"files": list(build), "overrides": self._overrides(), "kickass": kickass,
               "padding_byte": self.project.padding_byte if self.project else 0}
        if scope == "project":
            if not self.project:
                return "Open a project first, or analyse the current file"
            return {**req, "title": self.project.name}
        ed = self._last_source_editor()
        if ed is None or not ed.path:
            return "Open (or click into) an assembler file first"
        if ed.is_basic:
            return f"{ed.title} is BASIC: the analyser looks at assembler"
        req["scope"] = ed.path
        if not req["files"]:
            req["files"] = [ed.path]
        if scope == "file":
            return {**req, "title": ed.title}
        sel = ed.buffer.get_selection_bounds()
        if not sel:
            return f"Select some lines in {ed.title} first"
        a, b = sel
        last = b.get_line() + (0 if b.starts_line() and b.get_line() > a.get_line() else 1)
        req["lines"] = (a.get_line() + 1, last)
        return {**req, "title": f"{ed.title} lines {a.get_line() + 1}-{last}"}

    def _last_source_editor(self):
        ed = self._last_source
        return ed if ed is not None and ed in self.editors() else None

    def open_memory_viewer(self):
        for ed in self.editors():
            if isinstance(ed, MemoryViewer):
                self.tab_view.set_selected_page(self.tab_view.get_page(ed))
                ed.refresh()
                return ed
        return self._add_page(MemoryViewer(self._memory_of_last_build, lambda: self.debug, self._open_source_line))

    def open_binary_tool(self, path: Path | None = None):
        tool = next((ed for ed in self.editors() if isinstance(ed, BinaryTool)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
        else:
            kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
            tool = self._add_page(BinaryTool(kickass, self.project.directory if self.project else None,
                                             self._build_memory, self._insert_into_last_source))
        if path:
            tool.load_file(path)
        return tool

    def open_disassembler(self, path: Path | None = None):
        tool = next((ed for ed in self.editors() if isinstance(ed, DisassemblerView)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
        else:
            kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
            tool = self._add_page(DisassemblerView(kickass, self.project.directory if self.project else None,
                                                   self._build_memory, lambda: self.debug,
                                                   self._insert_into_last_source))
        if path:
            tool.load_file(path)
        return tool

    def _build_memory(self):
        """(memory, used, {address: label}, description) of the last build, for exporting."""
        m, symbols, desc = self._memory_of_last_build()
        return (m.memory, m.used, symbols, desc) if m else None

    def open_memory_manager(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, MemoryManager)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            tool._update()
            return tool
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(MemoryManager(kickass, self._memory_of_last_build, lambda: self.debug,
                                            self._insert_into_last_source))

    def snapshot_folder(self) -> Path:
        if self.project:
            return self.project.directory / "snapshots"
        return Path(GLib.get_user_data_dir()) / "linux64studio" / "snapshots"

    def _sid_designer(self, path: Path | None = None) -> SidDesigner:
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return SidDesigner(self.settings, kickass, self.project.directory if self.project else None,
                           self._insert_into_last_source, path)

    def open_sid_designer(self):
        """The untitled SID Designer, or a new one (files open their own)."""
        tool = next((ed for ed in self.editors() if isinstance(ed, SidDesigner) and not ed.path), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            return tool
        return self._add_page(self._sid_designer())

    def open_snapshots(self):
        tool = next((ed for ed in self.editors() if isinstance(ed, SnapshotManager)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            tool.refresh()
            return tool
        return self._add_page(SnapshotManager(
            self.snapshot_folder(), lambda: self.debug, self._memory_of_last_build,
            lambda: self.last_build.prg if self.last_build and self.last_build.ok else None,
            self.debug_from_snapshot, self._show_memory_at))

    def debug_from_snapshot(self, vsf: Path):
        """Start debugging the project, then load the snapshot as soon as VICE is ready."""
        self._pending_snapshot = vsf
        self.build(run=True, debug=True)

    def _show_memory_at(self, addr: int):
        viewer = self.open_memory_viewer()
        if self.debug and self.debug.monitor.connected:
            viewer.source.set_selected(1)
        viewer.select(addr)

    def _memory_of_last_build(self):
        """(MemoryMap, {address: label}, description) for the last successful build."""
        from .. import memmap
        res = self.last_build
        if not res or not res.ok or not res.prg:
            return None, {}, ""
        symbols: dict[int, str] = {}
        if res.asm_result:
            m = memmap.from_build(res.asm_result)
            for key, value in res.asm_result.symbols.items():
                name = res.asm_result.names.get(key, key)
                if "__m" not in key and not name.startswith("@") and value not in symbols:
                    symbols[value] = name
        else:
            m = memmap.from_prg(res.prg.read_bytes(), res.prg.name)
        return m, symbols, f"Last build: {res.prg.name}"

    def _open_source_line(self, file: str, line: int):
        ed = self.open_file(Path(file))
        if isinstance(ed, SourceEditor):
            ed.goto_line(line)

    def _insert_into_last_source(self, text: str) -> str | None:
        ed = self._last_source
        if ed is None or ed not in self.editors():
            return None
        # On a line of its own: after the cursor's line if the cursor is part-way along one.
        buf = ed.buffer
        it = buf.get_iter_at_mark(buf.get_insert())
        if not it.starts_line():
            it.forward_to_line_end()
            text = "\n" + text.rstrip("\n")
        elif not text.endswith("\n"):
            text += "\n"
        buf.begin_user_action()
        buf.insert(it, text)
        buf.end_user_action()
        self.tab_view.set_selected_page(self.tab_view.get_page(ed))
        ed.view.grab_focus()
        return ed.title

    # ================================================================== music
    def _save_project_quietly(self):
        if self.project:
            try:
                self.project.save()
            except OSError as e:
                self.toast(f"Couldn't save project settings: {e}")

    def _music_app(self, which: str):
        """Start SidMonkey or GoatTracker in the project folder (they open their own songs)."""
        import subprocess
        from ..sid.goattracker import find_tool
        tool = find_tool(which, self.settings.goattracker_dir)
        if not tool:
            self.toast(f"{which} not found: set the GoatTracker folder in Preferences")
            return
        subprocess.Popen([tool], cwd=str(self.project.directory) if self.project else None,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        self.toast("Save songs in the project folder to use them here")

    # ================================================================== BASIC
    def choose_prg_to_list(self):
        dlg = Gtk.FileDialog(title="List BASIC Program")
        f = Gtk.FileFilter(name="C64 programs (.prg)")
        f.add_pattern("*.prg")
        f.add_pattern("*.PRG")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)
        if self.project:
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.project.directory)))

        def done(d, res):
            try:
                self.list_prg(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self, None, done)

    def _open_prg(self, path: Path):
        """A .prg can be BASIC or machine code (usually behind a one-line BASIC loader): ask."""
        dlg = Adw.AlertDialog(heading=f"Open {path.name}", body="List it as a BASIC program, or disassemble it?")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("basic", "List as BASIC")
        dlg.add_response("disasm", "Disassemble")
        dlg.set_default_response("disasm")

        def chosen(d, res):
            r = d.choose_finish(res)
            if r == "basic":
                self.list_prg(path)
            elif r == "disasm":
                self.open_disassembler(path)
        dlg.choose(self, None, chosen)
        return None

    def list_prg(self, prg: Path):
        """Detokenize a .prg into a new (unsaved) .bas file next to it."""
        try:
            data = prg.read_bytes()
        except OSError as e:
            self.toast(f"Couldn't read {prg.name}: {e.strerror}")
            return None
        return self.list_program_bytes(data, prg.with_suffix(".bas"), prg.name)

    def list_program_bytes(self, data: bytes, dest: Path, label: str):
        from ..basic.tokenizer import BasicError, detokenize
        try:
            text = detokenize(data)
        except BasicError as e:
            self.toast(f"Couldn't list {label}: {e}")
            return None
        if not text:
            self.toast(f"{label} doesn't contain a BASIC program")
            return None
        base = dest
        n = 1
        while dest.exists() or str(dest.resolve()) in self.pages:
            dest = base.with_name(f"{base.stem}_{n}.bas")
            n += 1
        ed = SourceEditor(dest, self.settings)
        ed.connect("breakpoints-changed", self._on_breakpoints_changed)
        ed.replace_text(text)
        self._add_page(ed)
        self.toast(f"Listed {label}. Save to keep it as {dest.name}")
        return ed

    def renumber_dialog(self):
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor) or not ed.is_basic:
            self.toast("Renumbering works on a BASIC (.bas) file")
            return
        dlg = Adw.AlertDialog(heading="Renumber BASIC program",
                              body="GOTO, GOSUB, THEN, ON…GOTO/GOSUB, RUN and LIST line numbers are updated too.")
        grid = Gtk.Grid(row_spacing=6, column_spacing=8, halign=Gtk.Align.CENTER)
        start = Gtk.SpinButton.new_with_range(0, 63999, 1)
        start.set_value(10)
        step = Gtk.SpinButton.new_with_range(1, 1000, 1)
        step.set_value(10)
        grid.attach(Gtk.Label(label="Start at", xalign=0), 0, 0, 1, 1)
        grid.attach(start, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Step", xalign=0), 0, 1, 1, 1)
        grid.attach(step, 1, 1, 1, 1)
        dlg.set_extra_child(grid)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("go", "Renumber")
        dlg.set_default_response("go")
        dlg.set_response_appearance("go", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "go":
                return
            from ..basic.renumber import renumber
            from ..basic.tokenizer import BasicErrors
            try:
                text, warnings = renumber(ed.get_text(), int(start.get_value()), int(step.get_value()))
            except BasicErrors as e:
                self.toast(e.errors[0].message)
                return
            ed.replace_text(text)
            if warnings:
                self.toast(f"Renumbered. {len(warnings)} reference(s) point at missing lines; "
                           f"first: {warnings[0].message}")
            else:
                self.toast("Renumbered (Ctrl+Z to undo)")
        dlg.choose(self, None, chosen)

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

        # ---------- disk image page
        dpage = Adw.PreferencesPage(title="Disk Image", icon_name="media-floppy-symbolic")
        win.add(dpage)
        dg = Adw.PreferencesGroup(title="Disk image",
                                  description="Written after every project build, with the program as its first "
                                              "file. Files are laid out exactly as the real drive would.")
        dpage.add(dg)
        stem = Path(p.executable or p.name).stem
        d_on = Adw.SwitchRow(title="Write a disk image", active=bool(p.disk_image))
        kinds = [".d64", ".d71", ".d81"]
        current = Path(p.disk_image).suffix.lower() if p.disk_image else ".d64"
        d_kind = Adw.ComboRow(title="Format", model=Gtk.StringList.new(
            ["1541 (.d64, 664 blocks)", "1571 (.d71, 1328 blocks)", "1581 (.d81, 3160 blocks)"]),
            selected=kinds.index(current) if current in kinds else 0)
        d_path = Adw.EntryRow(title="Image file", text=p.disk_image or f"{stem}.d64")

        def kind_changed(row, _ps):
            text = d_path.get_text().strip() or f"{stem}.d64"
            d_path.set_text(str(Path(text).with_suffix(kinds[row.get_selected()])))
        d_kind.connect("notify::selected", kind_changed)
        d_name = Adw.EntryRow(title="Disk name (16 characters)", text=p.disk_name or p.name[:16])
        d_id = Adw.EntryRow(title="Disk ID (2 characters)", text=p.disk_id or "00")
        d_file = Adw.EntryRow(title="Program's name on the disk", text=p.disk_file_name or stem[:16])
        d_run = Adw.SwitchRow(title="Run from the disk image",
                              subtitle="Ctrl+F5 and debugging autostart the .d64 instead of the .prg",
                              active=p.run_from_disk)
        for w in (d_on, d_kind, d_path, d_name, d_id, d_file, d_run):
            dg.add(w)
        xg = Adw.PreferencesGroup(title="More files on the disk",
                                  description="Added after the program: other programs, data files (SEQ) and so on.")
        dpage.add(xg)
        extras = [dict(x) for x in p.disk_extra_files]
        xrows: list = []

        def rebuild_extras():
            for r in xrows:
                xg.remove(r)
            xrows.clear()
            for i, x in enumerate(extras):
                r = Adw.ActionRow(title=x.get("name", ""), subtitle=f"{x.get('file', '')} · {x.get('type', 'prg').upper()}")
                rm = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
                rm.connect("clicked", lambda _b, k=i: (extras.pop(k), rebuild_extras()))
                r.add_suffix(rm)
                xg.add(r)
                xrows.append(r)
            add = Adw.ButtonRow(title="Add a file…") if hasattr(Adw, "ButtonRow") else Adw.ActionRow(
                title="Add a file…", activatable=True)
            add.connect("activated", choose_extra)
            xg.add(add)
            xrows.append(add)

        def choose_extra(*_):
            from ..disk.image import file_type_for
            fd = Gtk.FileDialog(title="Add a file to the disk image")
            fd.set_initial_folder(Gio.File.new_for_path(str(p.directory)))

            def done(d, res):
                try:
                    src = Path(d.open_finish(res).get_path())
                except GLib.Error:
                    return
                try:
                    rel = str(src.relative_to(p.directory))
                except ValueError:
                    rel = str(src)
                kind = file_type_for(src) if src.suffix.lower() != ".bin" else "prg"
                extras.append({"file": rel, "name": src.stem[:16], "type": kind})
                rebuild_extras()
            fd.open(self, None, done)
        rebuild_extras()

        # ---------- cartridge page
        from ..cart.crt import CART_TYPES
        cpage = Adw.PreferencesPage(title="Cartridge", icon_name="media-flash-symbolic")
        win.add(cpage)
        cg = Adw.PreferencesGroup(title="Cartridge image (.crt)",
                                  description="Written after every project build. The program is bank 0: assemble "
                                              "it at $8000 (with a CBM80 header) or, for Ultimax and EasyFlash, "
                                              "at $E000 with a reset vector at $FFFC.")
        cpage.add(cg)
        ckeys = list(CART_TYPES)
        c_on = Adw.SwitchRow(title="Write a cartridge", active=bool(p.cart_type))
        c_type = Adw.ComboRow(title="Type", model=Gtk.StringList.new([CART_TYPES[k].label for k in ckeys]),
                              selected=ckeys.index(p.cart_type) if p.cart_type in ckeys else 0)
        c_file = Adw.EntryRow(title="Cartridge file", text=p.cart_file or f"{stem}.crt")
        c_name = Adw.EntryRow(title="Name in the cartridge header", text=p.cart_name or p.name)
        c_run = Adw.SwitchRow(title="Run with the cartridge plugged in",
                              subtitle="Ctrl+F5 and debugging start VICE with the .crt attached",
                              active=p.run_cart)
        for w in (c_on, c_type, c_file, c_name, c_run):
            cg.add(w)
        bg2 = Adw.PreferencesGroup(title="Banks 1, 2, …",
                                   description="For Magic Desk, Ocean and EasyFlash: data files split into banks "
                                               "after bank 0 (8K each, 16K for EasyFlash). A .prg's load address "
                                               "is dropped.")
        cpage.add(bg2)
        banks = list(p.cart_banks)
        brows: list = []

        def rebuild_banks():
            for r in brows:
                bg2.remove(r)
            brows.clear()
            for i, b in enumerate(banks):
                r = Adw.ActionRow(title=b)
                rm = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
                rm.connect("clicked", lambda _b, k=i: (banks.pop(k), rebuild_banks()))
                r.add_suffix(rm)
                bg2.add(r)
                brows.append(r)
            add = Adw.ActionRow(title="Add a bank file…", activatable=True)
            add.connect("activated", choose_bank)
            bg2.add(add)
            brows.append(add)

        def choose_bank(*_):
            fd = Gtk.FileDialog(title="Add a bank file")
            fd.set_initial_folder(Gio.File.new_for_path(str(p.directory)))

            def done(d, res):
                try:
                    src = Path(d.open_finish(res).get_path())
                except GLib.Error:
                    return
                try:
                    banks.append(str(src.relative_to(p.directory)))
                except ValueError:
                    banks.append(str(src))
                rebuild_banks()
            fd.open(self, None, done)
        rebuild_banks()

        def closed(*_):
            p.executable = exe.get_text().strip() or p.executable
            p.toolchain = TOOLCHAIN_CBM if tool.get_selected() == 0 else TOOLCHAIN_KICKASS
            p.main_file = main.get_text().strip()
            p.build_list = list(order)
            p.disk_image = d_path.get_text().strip() if d_on.get_active() else ""
            p.disk_name = d_name.get_text().strip()[:16]
            p.disk_id = (d_id.get_text().strip() or "00")[:2]
            p.disk_file_name = d_file.get_text().strip()[:16]
            p.run_from_disk = d_run.get_active()
            p.disk_extra_files = extras
            p.cart_type = ckeys[c_type.get_selected()] if c_on.get_active() else ""
            p.cart_file = c_file.get_text().strip()
            p.cart_name = c_name.get_text().strip()[:32]
            p.cart_banks = banks
            p.run_cart = c_run.get_active()
            try:
                p.save()
            except OSError as e:
                self.toast(f"Couldn't save project settings: {e}")
            self._populate_files()
        win.connect("closed", closed)
        win.present(self)

    def toast(self, text: str):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))
