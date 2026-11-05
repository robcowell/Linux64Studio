"""The main IDE window."""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk, Pango  # noqa: E402

from ..emu import vice  # noqa: E402
from .menus import build_menubar  # noqa: E402
from .toolbar import build_toolbar  # noqa: E402
from .projinfo_panel import ProjectInfoPanel  # noqa: E402
from .statusbar import StatusBar  # noqa: E402
from ..statusbar import EditorState, fields as status_fields  # noqa: E402
from ..session import OpenFile, ProjectState, Session, load_project_state, save_project_state  # noqa: E402
from ..project.filetree import Node, build_tree  # noqa: E402
from ..project.build import BuildResult, build_project  # noqa: E402
from ..project.model import (TOOLCHAIN_CBM, TOOLCHAIN_CC65, TOOLCHAIN_KICKASS, Project, load_project,  # noqa: E402
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
from .basic_stats_view import BasicStatistics  # noqa: E402
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

class _FileItem(GObject.Object):
    """A file or folder in the sidebar's tree."""
    def __init__(self, node: Node):
        super().__init__()
        self.node = node


def _file_icon(path: Path) -> str:
    sfx = path.suffix.lower()
    if sfx in SOURCE_EXTS:
        return "text-x-generic-symbolic"
    if sfx in (".spt", ".cst", ".sdd", ".spd", ".ctm"):
        return "image-x-generic-symbolic"
    if sfx in (".sng", ".ins", ".sid", ".l64sid"):
        return "audio-x-generic-symbolic"
    return "application-x-executable-symbolic"


SOURCE_EXTS = {".asm", ".s", ".a", ".inc", ".txt", ".bas", ".pbas", ".lst", ".tkn", ".c", ".h", ".cfg"}


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
        self.recent_menu = Gio.Menu()
        # the menu bar, as in CBM prg Studio, at the start of the header bar
        self.user_tools_menu = Gio.Menu()
        self.menubar = Gtk.PopoverMenuBar.new_from_model(build_menubar(self.recent_menu, self.user_tools_menu))
        hb.pack_start(self.menubar)

        self.title_widget = Adw.WindowTitle(title="Linux64Studio", subtitle="")
        hb.set_title_widget(self.title_widget)

        # the toolbar row under it, as in CBM prg Studio
        self.toolbar = build_toolbar(self.recent_menu)
        tv.add_top_bar(self.toolbar)

        self.toasts = Adw.ToastOverlay()
        tv.set_content(self.toasts)
        self.statusbar = StatusBar(self._status_toggle)
        self.statusbar.set_visible(False)
        tv.add_bottom_bar(self.statusbar)
        self._git_branch: str | None = None
        self._status_editor = None
        self._status_handlers: list[tuple[GObject.Object, int]] = []
        seat = Gdk.Display.get_default().get_default_seat() if Gdk.Display.get_default() else None
        self._keyboard = seat.get_keyboard() if seat else None
        if self._keyboard is not None:
            self._keyboard.connect("notify::caps-lock-state", lambda *_: self._refresh_status())
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
        self._sidebar = side
        self.sidebar_title = Gtk.Label(label="No project", xalign=0, margin_start=10, margin_top=8, margin_bottom=4,
                                       ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"])
        side.append(self.sidebar_title)
        self._file_tree: Gtk.TreeListModel | None = None
        self._tree_project: str | None = None        # whose folders _populate_files last showed
        self._build_order: dict[Path, int] = {}
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._file_row_setup)
        factory.connect("bind", self._file_row_bind)
        self.file_list = Gtk.ListView(factory=factory, single_click_activate=True,
                                      css_classes=["navigation-sidebar"])
        self.file_list.connect("activate", self._on_file_activated)
        root_drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)   # below the files: the top
        root_drop.connect("drop", lambda _t, value, _x, _y:
                          self._drop_into(self.project.directory if self.project else None, value))
        self.file_list.add_controller(root_drop)
        css = Gtk.CssProvider()
        css.load_from_data(b"listview.navigation-sidebar treeexpander:drop(active) "
                           b"{ background: alpha(@accent_bg_color, 0.25); border-radius: 6px; }", -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root_menu = Gtk.GestureClick(button=3)             # the empty space below the files
        root_menu.connect("pressed", lambda _g, _n, x, y: self._project_root_menu(x, y))
        self.file_list.add_controller(root_menu)
        side.append(Gtk.ScrolledWindow(child=self.file_list, vexpand=True))
        outer.set_start_child(side)
        outer.set_shrink_start_child(False)

        # ---------- editors + bottom panel
        right = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        # ---------- Project Information on the right, as in CBM prg Studio
        self.projinfo = ProjectInfoPanel(self._project_info, self._open_source_line,
                                         lambda: self.lookup_action("project-info").change_state(
                                             GLib.Variant.new_boolean(False)))
        self.projinfo.set_visible(self.settings.show_project_info)
        info_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, start_child=right, end_child=self.projinfo,
                               resize_end_child=False, shrink_end_child=False, shrink_start_child=False)
        outer.set_end_child(info_paned)
        tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tab_view = Adw.TabView(vexpand=True)
        self.tab_view.connect("close-page", self._on_close_page)
        self.tab_view.connect("notify::selected-page", lambda *_: self._on_tab_selected())
        self._menu_page: Adw.TabPage | None = None       # the tab whose right-click menu is open
        self.tab_view.set_menu_model(self._tab_menu_model())
        self.tab_view.connect("setup-menu", self._on_tab_setup_menu)
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
        from .tasks_panel import TasksPanel
        self.tasks_panel = TasksPanel(self._open_task, lambda: getattr(self.current_editor(), "path", None))
        self.tasks_page = self.bottom_stack.add_titled_with_icon(self.tasks_panel, "tasks", "Tasks",
                                                                 "object-select-symbolic")
        GLib.timeout_add_seconds(2, self._tick_tasks)
        from ..breakpoints import Breakpoints
        from .breakpoints_panel import BreakpointsPanel
        self.breakpoints = Breakpoints()
        self.bp_panel = BreakpointsPanel(
            items=lambda: (self._sync_breakpoints(), self.breakpoints.all())[1], line_text=self._line_text,
            address=self._breakpoint_address, base=lambda: self.project.directory if self.project else None,
            set_enabled=self._bp_set_enabled, set_all=self._bp_set_all, remove=self._bp_remove,
            remove_all=self._bp_remove_all, go_to=lambda bp: self._open_source_line(bp.file, bp.line))
        self.bottom_stack.add_titled_with_icon(self.bp_panel, "breakpoints", "Breakpoints", "media-record-symbolic")
        self.bottom_stack.connect("notify::visible-child-name", lambda st, _p: st.get_visible_child_name()
                                  == "breakpoints" and self.bp_panel.refresh())
        from .find_panel import FindPanel
        self.find_panel = FindPanel(self._find_texts, self._open_match,
                                    lambda: self.project.directory if self.project else None)
        self.bottom_stack.add_titled_with_icon(self.find_panel, "find", "Find Results", "edit-find-symbolic")
        bottom.append(self.bottom_stack)
        bottom.set_vexpand(True)
        right.set_end_child(bottom)
        right.set_position(int(self.settings.window_height * 0.62))
        self._pc_editor: SourceEditor | None = None

        self._install_actions()
        self._refresh_recent()
        self.refresh_user_tools()

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
        add("edit", lambda _a, v: self._edit(v.get_string()), "s")
        add("find-in-files", lambda *_: self.find_in_files())
        add("find", lambda *_: self.find_in_file(replace=False))
        add("replace", lambda *_: self.find_in_file(replace=True))
        add("find-next", lambda *_: self._find_step(True))
        add("find-previous", lambda *_: self._find_step(False))
        info = Gio.SimpleAction.new_stateful("project-info", None,
                                             GLib.Variant.new_boolean(self.settings.show_project_info))
        info.connect("change-state", self._show_project_info)
        self.add_action(info)
        # F10 is Step Over (as in CBM prg Studio), but GTK windows bind F10 to opening the menu bar,
        # and that binding runs before application shortcuts. Catch it first, in the capture phase.
        f10 = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        f10.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("F10"),
                                      action=Gtk.NamedAction.new("win.debug-over")))
        self.add_controller(f10)
        add("tab-close", lambda *_: self._close_tabs("this"))
        add("tab-close-others", lambda *_: self._close_tabs("others"))
        add("tab-close-right", lambda *_: self._close_tabs("right"))
        add("tab-close-all", lambda *_: self._close_tabs("all"))
        add("tab-reveal", lambda *_: self._reveal_tab_file())
        add("reveal-path", lambda _a, v: self.reveal_in_file_manager(Path(v.get_string())), "s")
        add("tab-copy-path", lambda *_: self._copy_tab_path())
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
        add("debug-into-instruction", lambda *_: self.debugger.do("into-instruction"))
        add("debug-over-instruction", lambda *_: self.debugger.do("over-instruction"))
        add("project-properties", lambda *_: self.project_properties())
        add("goto-line", lambda *_: self._goto_line_dialog())
        add("renumber", lambda *_: self.renumber_dialog())
        add("reformat-basic", lambda *_: self.reformat_dialog())
        add("print", lambda *_: self.print_source())
        add("utf8-check", lambda *_: self.open_utf8_check())
        add("create-token-file", lambda *_: self.create_token_file())
        add("convert-source", lambda *_: self.convert_source())
        add("user-tool", lambda _a, v: self.run_user_tool(v.get_int32()), "i")
        add("git-status", lambda *_: self.git_status())
        add("git-diff", lambda *_: self.git_diff())
        add("git-log", lambda *_: self.git_log())
        add("git-commit", lambda *_: self.git_commit_dialog())
        add("git-add-all", lambda *_: self.git_do("add-all"))
        add("git-ignore", lambda *_: self.git_ignore_list())
        add("git-init", lambda *_: self.git_init())
        add("git-file", lambda _a, v: self.git_file(v.get_string()), "s")
        add("file-op", lambda _a, v: self.file_op(*v.get_string().split("|", 1)), "s")
        add("print-preview", lambda *_: self.print_source(preview=True))
        add("basic-compress", lambda *_: self.basic_keywords("abbreviate"))
        add("basic-uncompress", lambda *_: self.basic_keywords(
            "full" if self.settings.basic_uncompress_lowercase else "FULL"))
        add("goto-definition", lambda *_: self.goto_definition())
        add("add-todo", lambda *_: self.add_todo())
        add("go-back", lambda *_: self.go_back())
        add("pbasic-create-label", lambda *_: self.pbasic_create_label())
        add("pbasic-remove-numbers", lambda *_: self.pbasic_remove_numbers())
        add("pbasic-preview", lambda *_: self.pbasic_preview())
        add("convert-to-pbasic", lambda *_: self.convert_to_pbasic())
        add("music-app", lambda _a, v: self._music_app(v.get_string()), "s")
        add("screen-codes", lambda *_: self.open_screen_code_builder())
        add("screen-calculator", lambda *_: self.open_screen_calculator())
        add("snippets", lambda *_: self.open_snippets())
        add("sys-call", lambda *_: self.open_sys_call())
        add("data-generator", lambda *_: self.open_data_generator())
        add("string-formatter", lambda *_: self.open_string_formatter())
        add("source-analyser", lambda *_: self.open_source_analyser())
        add("basic-statistics", lambda *_: self.open_basic_statistics())
        add("import-charpad", lambda *_: self.import_charpad())
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

    def open_project(self, path: Path, reopen_tabs: bool = True):
        """Open a project, with the tabs it had open when last left (else its first source file)."""
        if not self._confirm_discard_all():
            return
        try:
            proj = load_project(path)
        except Exception as e:  # report any bad project file instead of crashing
            self.toast(f"Couldn't open {path.name}: {e}")
            return
        self._remember_project()
        self._close_all_tabs(force=True)
        self.project = proj
        from ..breakpoints import Breakpoints
        state = self._project_state()                # its breakpoints, before any of its files open
        self.breakpoints = Breakpoints.from_list(state.breakpoints if state else [])
        self.bp_panel.refresh()
        # the .l64proj once there is one (opening the original loads it anyway), else what was opened
        settings_file = proj.settings_path()
        self.settings.add_recent(str((settings_file if settings_file.exists() else path).resolve()))
        self.settings.save()
        self._refresh_recent()
        self._populate_files()
        self._update_title()
        state = self._project_state() if reopen_tabs else None
        files, selected, missing = state.restorable() if state else ([], -1, [])
        if files:
            self._reopen_tabs(files, selected)
            if missing:
                self.toast(f"Not found, so not opened: {', '.join(missing)}")
        elif reopen_tabs:
            first = (proj.build_paths()[:1] if proj.toolchain in (TOOLCHAIN_CBM, TOOLCHAIN_CC65)
                     else [proj.directory / proj.main_file] if proj.main_file else [])
            for p in first:
                if p.exists():
                    self.open_file(p)
        if proj.imported_from:
            self.toast(f"Opened {proj.imported_from}. Settings are saved to {proj.settings_path().name}")

    def close_project(self):
        if not self._confirm_discard_all():
            return
        self._remember_project()
        self._close_all_tabs(force=True)
        from ..breakpoints import Breakpoints
        self.breakpoints = Breakpoints()
        self.bp_panel.refresh()
        self.project = None
        self._populate_files()
        self._update_title()

    def _populate_files(self):
        """The project's files as a folder tree, keeping open the folders that were open."""
        self._git_states = self._git_status_map()
        self._git_branch = self._git_branch_name()
        self.projinfo.refresh_soon(100)
        expanded = self._open_folders()
        renamed = getattr(self, "_folder_renamed", None)
        if renamed:                       # a renamed folder keeps open, as do folders inside it
            o, n = renamed
            expanded = {n / f.relative_to(o) if (f == o or o in f.parents) else f for f in expanded}
            self._folder_renamed = None
        expanded |= getattr(self, "_expand_after_refresh", set())
        self._expand_after_refresh = set()
        if not self.project:
            self._tree_project = None
            self.sidebar_title.set_text("No project")
            self._file_tree = None
            self.file_list.set_model(None)
            return
        p = self.project
        self.sidebar_title.set_text(p.name + {TOOLCHAIN_KICKASS: "  (Kick Assembler)",
                                              TOOLCHAIN_CC65: "  (C, cc65)"}.get(p.toolchain, ""))
        self._build_order = {(p.directory / n).resolve(): i for i, n in enumerate(p.build_list)}
        roots = [p.directory] + [p.directory / d for d in p.lib_dirs] + p.referenced_dirs()
        tree = build_tree(p.directory, p.all_files(), self._build_order, roots, p.all_folders())
        first_time = self._tree_project != self._project_key()
        self._tree_project = self._project_key()
        if first_time:                   # a project just opened: its folders as they were left
            state = self._project_state()
            saved = state.folders if state else None
            expanded = ({Path(f) for f in saved} if saved is not None else      # else its top-level folders
                        {c.path for c in tree.children if c.is_dir and c.path.is_relative_to(tree.path)})

        def store(nodes):
            st = Gio.ListStore(item_type=_FileItem)
            for n in nodes:
                st.append(_FileItem(n))
            return st
        model = Gtk.TreeListModel.new(store(tree.children), False, False,
                                      lambda item: store(item.node.children) if item.node.is_dir else None)
        i = 0
        while i < model.get_n_items():   # opening a folder inserts its rows after it, which this visits
            row = model.get_item(i)
            if row.get_item().node.path in expanded:
                row.set_expanded(True)
            i += 1
        self._file_tree = model
        self.file_list.set_model(Gtk.NoSelection(model=model))

    def _project_key(self) -> str:
        return self.project.identity()

    def _project_state(self) -> ProjectState | None:
        for key in [self._project_key()] + self.project.old_identities():
            if (state := load_project_state(key)) is not None:
                return state
        return None

    def _open_folders(self) -> set[Path]:
        tree = self._file_tree
        if tree is None:
            return set()
        rows = (tree.get_item(i) for i in range(tree.get_n_items()))
        return {r.get_item().node.path for r in rows if r.get_expanded()}

    def _remember_project(self):
        """Keep the project's open folders and tabs, for when it's opened again."""
        if not self.project or self._tree_project != self._project_key():
            return
        tabs = self.capture_session()
        self._sync_breakpoints()
        save_project_state(self._tree_project,
                           ProjectState([str(f) for f in self._open_folders()], tabs.files, tabs.selected,
                                        self.breakpoints.to_list()))

    def _file_row_setup(self, _f, li):
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image())
        box.append(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True))
        box.append(Gtk.Label(css_classes=["caption-heading"]))                 # Git state
        box.append(Gtk.Label(css_classes=["dim-label", "caption"], margin_end=6,
                             tooltip_text="Position in the build order"))
        exp = Gtk.TreeExpander(child=box)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", lambda g, _n, x, y: (g.set_state(Gtk.EventSequenceState.CLAIMED),
                                                      self._file_menu(exp, x, y)))
        exp.add_controller(click)
        # drag a file or folder onto a folder (or a file, for its folder) to move it there
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", lambda _src, _x, _y: self._drag_prepare(exp))
        drag.connect("drag-begin", lambda src, _d: self._drag_icon(src, exp))
        drag.connect("drag-end", lambda *_: GLib.timeout_add(150, self._do_pending_move))
        exp.add_controller(drag)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", lambda _t, value, _x, _y: self._drop_into(self._drop_folder(exp), value))
        exp.add_controller(drop)
        li.set_child(exp)

    def _file_row_bind(self, _f, li):
        exp: Gtk.TreeExpander = li.get_child()
        row: Gtk.TreeListRow = li.get_item()
        exp.set_list_row(row)
        node = row.get_item().node
        icon, name, git, order = list(exp.get_child())
        icon.set_from_icon_name("folder-symbolic" if node.is_dir else _file_icon(node.path))
        name.set_text(node.name)
        exp.set_tooltip_text(str(node.path))
        gs = None if node.is_dir else self._git_states.get(node.path)
        git.set_visible(gs is not None)
        if gs is not None:
            git.set_text(gs.letter)
            git.set_tooltip_text(f"Git: {gs.description}")
            git.set_css_classes(["caption-heading", {"?": "dim-label", "A": "success", "D": "error",
                                                     "U": "error"}.get(gs.letter, "warning")])
        bi = None if node.is_dir else self._build_order.get(node.path)
        order.set_visible(bi is not None)
        order.set_text(str(bi + 1) if bi is not None else "")

    def _on_file_activated(self, _view, position):
        row = self._file_tree.get_item(position) if self._file_tree else None
        if row is None:
            return
        node = row.get_item().node
        if node.is_dir:
            row.set_expanded(not row.get_expanded())
        else:
            self.open_file(node.path)

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
        self._refresh_status()          # the project, its Git branch and toolchain may have changed

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
                sprite_files = [f for f in (self.project.all_files() if self.project else [])
                                if f.suffix.lower() in (".spt", ".spd")]
                ed = ScreenEditor(path, charsets, sprite_files=sprite_files, settings=self.settings)
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
                self._watch_breakpoints(ed)
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
                "screencodes": "insert-text-symbolic", "screencalc": "accessories-calculator-symbolic", "snippets": "edit-paste-symbolic", "sysgen": "system-run-symbolic", "datagen": "x-office-spreadsheet-symbolic", "strformat": "format-justify-left-symbolic", "analyser": "utilities-system-monitor-symbolic", "utf8": "dialog-warning-symbolic", "basicstats": "view-list-bullet-symbolic", "memory": "drive-harddisk-symbolic",
                "binary": "document-open-symbolic", "disasm": "system-search-symbolic",
                "memmgr": "view-grid-symbolic", "snapshots": "camera-photo-symbolic",
                "siddesigner": "audio-speakers-symbolic"}.get(ed.kind)
        if icon:
            page.set_icon(Gio.ThemedIcon.new(icon))
        ed.connect("modified-changed", lambda e: page.set_title(("● " if e.modified else "") + e.title))
        if isinstance(ed, SourceEditor):       # Project Information follows what's typed
            ed.buffer.connect("changed", lambda *_: self.projinfo.refresh_soon(1500))
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
        GLib.idle_add(lambda: (self.refresh_tasks(), self._populate_files(), False)[2])
        return True

    def save_all(self):
        for ed in self.editors():
            if ed.modified:
                self._save(ed)

    def _edit(self, action: str):
        """Edit menu: run a text action (text.undo, clipboard.copy, ...) on whatever has the focus."""
        focus = self.get_focus()
        if focus is not None:
            focus.activate_action(action, None)

    def _close_current_tab(self):
        page = self.tab_view.get_selected_page()
        if page:
            self.tab_view.close_page(page)

    # ------------------------------------------------------------------ tab right-click menu
    @staticmethod
    def _tab_menu_model() -> Gio.Menu:
        menu = Gio.Menu()
        close = Gio.Menu()
        close.append("Close", "win.tab-close")
        close.append("Close Others", "win.tab-close-others")
        close.append("Close to the Right", "win.tab-close-right")
        close.append("Close All", "win.tab-close-all")
        menu.append_section(None, close)
        file = Gio.Menu()
        file.append("Reveal File", "win.tab-reveal")
        file.append("Copy Path", "win.tab-copy-path")
        menu.append_section(None, file)
        return menu

    def _on_tab_setup_menu(self, view, page):
        # Called with None once the menu closes, possibly before the chosen item activates,
        # so keep the last tab rather than clearing it.
        if page is None:
            return
        self._menu_page = page
        n, pos = view.get_n_pages(), view.get_page_position(page)
        has_file = bool(getattr(page.get_child(), "path", None))
        for name, on in (("tab-close-others", n > 1), ("tab-close-right", pos < n - 1),
                         ("tab-reveal", has_file), ("tab-copy-path", has_file)):
            self.lookup_action(name).set_enabled(on)

    def _menu_tab(self) -> Adw.TabPage | None:
        return self._menu_page or self.tab_view.get_selected_page()

    def _close_tabs(self, which: str):
        """Close the menu's tab, the others, those to its right or all; each unsaved one asks first."""
        page = self._menu_tab()
        if page is None:
            return
        pages = [self.tab_view.get_nth_page(i) for i in range(self.tab_view.get_n_pages())]
        pos = pages.index(page)
        doomed = {"this": [page], "others": pages[:pos] + pages[pos + 1:],
                  "right": pages[pos + 1:], "all": pages}[which]
        if which in ("others", "right"):
            self.tab_view.set_selected_page(page)
        for p in reversed(doomed):
            self.tab_view.close_page(p)

    def _reveal_tab_file(self):
        page = self._menu_tab()
        path = getattr(page.get_child(), "path", None) if page else None
        if path:
            self.reveal_in_file_manager(Path(path))

    def reveal_in_file_manager(self, path: Path):
        """Open the desktop's file manager at the folder holding ``path``, with it selected."""
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(Path(path).resolve())))

        def done(lnch, res):
            try:
                lnch.open_containing_folder_finish(res)
            except GLib.Error as e:
                if not e.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self.toast(f"Couldn't show {Path(path).name} in the file manager: {e.message}")
        launcher.open_containing_folder(self, None, done)

    def _copy_tab_path(self):
        page = self._menu_tab()
        path = getattr(page.get_child(), "path", None) if page else None
        if path:
            self.get_clipboard().set(str(Path(path).resolve()))
            self.toast("Copied the path")

    # ------------------------------------------------------------------ continue where I left off
    def capture_session(self) -> Session:
        """The project and the files open in tabs (not tool pages), with the cursor in each."""
        sel = self.tab_view.get_selected_page()
        files, selected = [], -1
        for i in range(self.tab_view.get_n_pages()):
            page = self.tab_view.get_nth_page(i)
            ed = page.get_child()
            if not getattr(ed, "path", None):            # a tool page or an unsaved file
                continue
            line = col = 0
            if isinstance(ed, SourceEditor):
                it = ed.buffer.get_iter_at_mark(ed.buffer.get_insert())
                line, col = it.get_line() + 1, it.get_line_offset()
            if page is sel:
                selected = len(files)
            files.append(OpenFile(str(Path(ed.path).resolve()), line, col))
        project = str(Path(self.project.path).resolve()) if self.project else ""
        return Session(project, files, selected)

    def restore_session(self, session: Session | None = None) -> bool:
        """Open the last session again. Returns whether there was anything to open."""
        session, missing = (session or Session.load()).restorable()
        if session.empty:
            if missing:
                self.toast(f"Couldn't continue where you left off: {', '.join(missing)} not found")
            return False
        if session.project:
            self.open_project(Path(session.project), reopen_tabs=False)     # the session's tabs instead
            if self.project is None:
                return False
        self._reopen_tabs(session.files, session.selected)
        if missing:
            self.toast(f"Not found, so not opened: {', '.join(missing)}")
        return True

    def _reopen_tabs(self, files: list[OpenFile], selected: int):
        """Open files in tabs with the cursor where it was in each, and ``selected`` in front."""
        opened = []
        for f in files:
            ed = self.open_file(Path(f.path))
            opened.append(ed)
            if isinstance(ed, SourceEditor) and f.line > 0:
                ok, it = ed.buffer.get_iter_at_line(f.line - 1)
                if ok:
                    if f.column:
                        it.forward_chars(min(f.column, it.get_chars_in_line()))
                    ed.buffer.place_cursor(it)
                    if hasattr(ed, "folding"):
                        ed.folding.reveal(f.line - 1)
                    GLib.idle_add(lambda e=ed: (e.view.scroll_to_mark(e.buffer.get_insert(), 0.2, True, 0, 0.4),
                                                False)[1])
        if 0 <= selected < len(opened) and opened[selected] is not None:
            front = self.tab_view.get_page(opened[selected])
            if front is not None:
                self.tab_view.set_selected_page(front)

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
        if page is self._menu_page:
            self._menu_page = None
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
        try:
            self.capture_session().save()
        except OSError:
            pass
        self._remember_project()
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
            ["Assembler (CBM prg Studio syntax)", "Kick Assembler", "BASIC V2", "Cartridge, 8K (assembler)",
             "C (cc65)"]))
        own_folder = Adw.SwitchRow(title="Make a folder for it", active=True,
                                   subtitle="Off: the project goes in Location itself, e.g. a folder of C files you "
                                            "already have")
        from ..gitrepo import available as git_available
        make_git = Adw.SwitchRow(title="Create a Git repository", active=False, sensitive=git_available(),
                                 subtitle="With an ignore list (Preferences → Git)")
        grp.add(name)
        grp.add(loc)
        grp.add(tool)
        grp.add(own_folder)
        grp.add(make_git)
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
            directory = Path(loc.get_subtitle()) / n if own_folder.get_active() else Path(loc.get_subtitle())
            sel = tool.get_selected()
            tc = TOOLCHAIN_KICKASS if sel == 1 else TOOLCHAIN_CC65 if sel == 4 else TOOLCHAIN_CBM
            if (directory / f"{n}.l64proj").exists():
                self.toast(f"There's already a project called {n} there")
                return
            proj = new_project(directory, n, tc, basic=sel == 2, cartridge=sel == 3)
            win.close()
            self.open_project(proj.path)
            if tc == TOOLCHAIN_CC65 and not proj.build_list:
                self.toast("Add the program's .c and .s files to the build list: right-click each in the file tree "
                           "and choose Add to Build")
            if make_git.get_active():
                self.git_init()
        btn.connect("clicked", create)
        win.present(self)

    def new_file_dialog(self, kind: str, folder: Path | None = None):
        if not self.project:
            self.toast("Open or create a project first")
            return
        dlg = Adw.AlertDialog(heading={"asm": "New source file", "bas": "New BASIC file",
                                       "pbas": "New pBASIC file (BASIC without line numbers)", "spt": "New sprite set",
                                       "cst": "New character set", "sdd": "New screen design",
                                       "d64": "New disk image (.d64, .d71 or .d81)", "c": "New C file",
                                       "h": "New C header file"}[kind])
        default = {"asm": "gameNew.asm", "bas": "main.bas", "pbas": "main.pbas", "spt": "sprites.spt", "cst": "characters.cst",
                   "sdd": "screens.sdd", "d64": "disk.d64", "c": "new.c", "h": "new.h"}[kind]
        entry = Gtk.Entry(text=default, activates_default=True)
        dlg.set_extra_child(entry)
        add_build = None
        if (kind in ("asm", "bas", "pbas") and self.project.toolchain == TOOLCHAIN_CBM) or \
                (kind == "c" and self.project.toolchain == TOOLCHAIN_CC65):
            add_build = Gtk.CheckButton(label="Add to the build list" + ("" if kind == "c" else " (before the last file)"),
                                        active=True)
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
            path = (folder or self.project.directory) / fname
            if path.exists():
                self.toast(f"{fname} already exists")
                self.open_file(path)
                return
            if kind in ("c", "h"):
                if kind == "h":
                    guard = re.sub(r"\W", "_", path.name).upper()
                    path.write_text(f"#ifndef {guard}\n#define {guard}\n\n\n#endif\n")
                else:
                    path.write_text(f"/* {path.name} */\n\n")
                if add_build and add_build.get_active():
                    from ..project.fileops import build_add
                    build_add(self.project, path)
                    self.project.save()
            elif kind in ("asm", "bas", "pbas"):
                if kind == "asm":
                    path.write_text(f";===============================================================================\n; {path.stem}\n\n")
                elif kind == "pbas":
                    path.write_text(f"rem {path.stem}\n")
                else:
                    path.write_text(f"10 rem {path.stem}\n")
                if add_build and add_build.get_active():
                    from ..project.fileops import relative
                    bl = self.project.build_list
                    bl.insert(max(0, len(bl) - 1), relative(self.project, path))
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
        if current_file and run and self.project.toolchain == TOOLCHAIN_CC65:
            current_file = False      # one C file doesn't make a program: F5 builds and runs the project
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
                                    settings.goattracker_dir, settings.pbasic_options())
            except Exception as e:  # report internal errors in the log rather than losing them
                import traceback
                from ..asm.errors import Diagnostic
                res = BuildResult(False, None, None, [Diagnostic("error", f"Internal error: {e}", None)],
                                  traceback.format_exc())
            GLib.idle_add(self._build_done, res, run, debug)
        threading.Thread(target=work, daemon=True).start()

    def _build_done(self, res: BuildResult, run: bool, debug: bool):
        self.last_build = res
        self.bp_panel.refresh()                  # the addresses breakpoints stop at
        self.projinfo.refresh_soon(100)          # the labels' values
        self.refresh_tasks()
        self._set_log(res.log)
        self._show_diagnostics(res)
        if self.settings.pbasic_preview:
            for src, text in res.basic_preview:
                self._show_basic_preview(src, text, select=False)
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

    def _vice_args(self) -> list[str]:
        """VICE options: the ones in Preferences, then the project's own."""
        return list(self.settings.emulator_args) + (list(self.project.vice_args) if self.project else [])

    def _launch(self, target: Path, labels: Path | None = None):
        try:
            proc = vice.launch(target, self.settings.emulator, labels, None, self._vice_args())
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
        """Where every breakpoint that's on stops, in open files and closed ones."""
        self._sync_breakpoints()
        addrs = set()
        for bp in self.breakpoints.enabled():
            a = session.address_for_line(bp.file, bp.line)
            if a is not None:
                addrs.add(a)
        return addrs

    def _start_debug(self, res: BuildResult):
        if self.project and self.project.toolchain == TOOLCHAIN_KICKASS and not res.srcmap:
            self.toast("Kick Assembler didn't write a debug dump (.dbg), so the debugger can't show source lines")
        if self.project and self.project.toolchain == TOOLCHAIN_CC65 and not res.srcmap:
            self.toast("ld65 didn't write a debug file, so the debugger can't show C source lines")
        symbols = self._build_symbols(res)
        if res.asm_result:
            for key, value in res.asm_result.symbols.items():
                name = res.asm_result.names.get(key, key)
                if "__m" not in key and not name.startswith("@") and value not in symbols:
                    symbols[value] = name
        start = res.run_target(self.project) if self.project else res.prg
        session = DebugSession(start, res.labels, res.srcmap, symbols, self.settings.emulator,
                               self._vice_args(), c_lines=res.c_lines, asm_lines=res.asm_lines)
        r = res.asm_result
        if r is not None:
            # CBM prg Studio's BREAKPOINT, DEBUGSTARTADDRESS and WATCH directives
            for addr, cond in r.breakpoints:
                session.source_breakpoints.add(addr)
                if cond:
                    session.conditions[addr] = cond
            if r.debug_start is not None:
                session.source_breakpoints.add(r.debug_start)
            session.watches = list(r.watches)
        self.debug = session
        self.debugger.set_c_program(self._c_program(res), res.c_sp)
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

    def _c_program(self, res: BuildResult):
        """A C build's variables for the debugger: types from the project's C sources (as they are in
        the editor), addresses from ld65's debug file. None for anything else."""
        if not (self.project and self.project.toolchain == TOOLCHAIN_CC65 and (res.c_globals or res.c_frames)):
            return None
        from ..cvars import CProgram
        open_texts = {str(Path(e.path).resolve()): e.get_text() for e in self.editors()
                      if isinstance(e, SourceEditor) and e.path}
        sources = {}
        built = {f.resolve() for f in self.project.build_paths()}
        for f in self.project.all_files():
            # the program's own C files (not other programs' in the same folder), and every header
            if (f.suffix.lower() == ".c" and f.resolve() in built) or f.suffix.lower() == ".h":
                key = str(f.resolve())
                try:
                    sources[key] = open_texts.get(key) or f.read_text(errors="replace")
                except OSError:
                    pass
        return CProgram(sources, res.c_globals, res.c_frames)

    def _on_breakpoints_changed(self, ed):
        if getattr(ed, "path", None):
            self.breakpoints.set_file(ed.path, ed.breakpoints())
        self._breakpoints_updated()

    # ------------------------------------------------------------------ the project's breakpoints
    def _watch_breakpoints(self, ed: SourceEditor):
        """A source file opening: show the project's breakpoints in it, and follow its changes."""
        if ed.path:
            ed.set_breakpoints(self.breakpoints.for_file(ed.path))
        ed.connect("breakpoints-changed", self._on_breakpoints_changed)

    def _sync_breakpoints(self):
        """Take the breakpoints' lines from the open editors (their marks move as lines are added)."""
        for ed in self.editors():
            if isinstance(ed, SourceEditor) and ed.path:
                self.breakpoints.set_file(ed.path, ed.breakpoints())

    def _breakpoints_updated(self):
        """After any change: the Breakpoints list, and VICE if a debug session is running."""
        self.bp_panel.refresh()
        if self.debug and self.debug.monitor.connected:
            self.debug.cmd(self.debug.set_breakpoints, self._all_breakpoint_addresses(self.debug))

    def _open_editor_for(self, file: str) -> SourceEditor | None:
        want = Path(file).resolve()
        return next((e for e in self.editors() if isinstance(e, SourceEditor) and e.path
                     and Path(e.path).resolve() == want), None)

    def _line_text(self, file: str, line: int) -> str:
        ed = self._open_editor_for(file)
        try:
            lines = ed.get_text().splitlines() if ed else Path(file).read_text(errors="replace").splitlines()
        except OSError:
            return ""
        return lines[line - 1] if 0 < line <= len(lines) else ""

    def _breakpoint_address(self, file: str, line: int) -> int | None:
        from ..breakpoints import address_for, line_addresses
        res = self.last_build
        if res is None or not res.srcmap:
            return None
        if getattr(self, "_line_addr_for", None) is not res:
            self._line_addr_for, self._line_addr = res, line_addresses(res.srcmap)
        return address_for(self._line_addr, file, line)

    def _bp_set_enabled(self, bp, on: bool):
        ed = self._open_editor_for(bp.file)
        if ed is not None:
            ed.set_breakpoint_enabled(bp.line, on)          # (signals the change)
        elif self.breakpoints.set_enabled(bp.file, bp.line, on):
            self._breakpoints_updated()

    def _bp_set_all(self, on: bool):
        self._sync_breakpoints()
        self.breakpoints.set_all_enabled(on)
        for ed in self.editors():
            if isinstance(ed, SourceEditor) and ed.path:
                ed.set_breakpoints(self.breakpoints.for_file(ed.path))
        self._breakpoints_updated()

    def _bp_remove(self, bp):
        ed = self._open_editor_for(bp.file)
        if ed is not None:
            ed.toggle_breakpoint(bp.line)                   # (signals the change)
        elif self.breakpoints.remove(bp.file, bp.line):
            self._breakpoints_updated()

    def _bp_remove_all(self):
        self.breakpoints.clear()
        for ed in self.editors():
            if isinstance(ed, SourceEditor):
                ed.set_breakpoints([])
        self._breakpoints_updated()

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
        self._watch_status(ed if isinstance(ed, SourceEditor) else None)
        self._update_title()

    # ------------------------------------------------------------------ status bar
    def _watch_status(self, ed):
        """Follow the cursor and insert/overwrite mode of the source file in front."""
        if ed is self._status_editor:
            return
        for obj, hid in self._status_handlers:
            obj.disconnect(hid)
        self._status_handlers = []
        self._status_editor = ed
        if ed is not None:
            refresh = lambda *_: self._refresh_status()    # noqa: E731
            self._status_handlers = [(ed.buffer, ed.buffer.connect("notify::cursor-position", refresh)),
                                     (ed.view, ed.view.connect("notify::overwrite", refresh))]
        self._refresh_status()

    def _refresh_status(self):
        ed = self._status_editor
        if ed is None or ed not in self.editors():
            self.statusbar.set_visible(False)
            return
        it = ed.buffer.get_iter_at_mark(ed.buffer.get_insert())
        p = self.project
        state = EditorState(
            caps_lock=bool(self._keyboard and self._keyboard.get_caps_lock_state()),
            overwrite=ed.view.get_overwrite(), word_wrap=self.settings.word_wrap,
            line=it.get_line() + 1, column=it.get_line_offset(),
            basic=ed.is_basic and not ed.is_pbasic, auto_line_numbers=self.settings.basic_auto_number,
            kickass=bool(p and p.toolchain == TOOLCHAIN_KICKASS), cc65=bool(p and p.toolchain == TOOLCHAIN_CC65),
            git_branch=self._git_branch,
            has_project=p is not None)
        self.statusbar.show_fields(status_fields(state))
        self.statusbar.set_visible(True)

    def _status_toggle(self, key: str):
        ed = self._status_editor
        if key == "overwrite" and ed is not None:
            ed.view.set_overwrite(not ed.view.get_overwrite())
        elif key == "wrap":
            self.settings.word_wrap = not self.settings.word_wrap
            for e in self.editors():
                if isinstance(e, SourceEditor):
                    e.set_word_wrap(self.settings.word_wrap)
            self.settings.save()
        elif key == "autonum":
            self.settings.basic_auto_number = not self.settings.basic_auto_number
            self.settings.save()
        if ed is not None:
            ed.view.grab_focus()
        self._refresh_status()

    def open_screen_code_builder(self):
        for ed in self.editors():
            if isinstance(ed, ScreenCodeBuilder):
                self.tab_view.set_selected_page(self.tab_view.get_page(ed))
                return ed
        kickass = bool(self.project and self.project.toolchain == TOOLCHAIN_KICKASS)
        return self._add_page(ScreenCodeBuilder(kickass, self._insert_into_last_source,
                                                self.settings.basic_code_style))

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

    def open_basic_statistics(self) -> BasicStatistics:
        tool = next((ed for ed in self.editors() if isinstance(ed, BasicStatistics)), None)
        if tool:
            self.tab_view.set_selected_page(self.tab_view.get_page(tool))
            tool.refresh()
            return tool
        return self._add_page(BasicStatistics(self._last_source_editor, self._open_source_line))

    def import_charpad(self):
        """Make a .ctm from a game's CharPad binaries, linked to write them back."""
        from .charpad_import import CharPadImportDialog

        def done(ctm: Path):
            if self.project:
                self._populate_files()           # the new .ctm appears in the file list
            self.open_file(ctm)
            self.toast(f"Made {ctm.name}: saving it writes the four files back")
        dlg = CharPadImportDialog(self, self.project, done)
        dlg.present()
        return dlg

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
        lb = self.last_build
        if kickass and lb and lb.ok and lb.prg and lb.kick_debug is not None:
            req["kick_build"] = (lb.kick_debug, lb.prg)
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
        elif res.kick_debug is not None:
            from ..kickdbg import memory_map
            m = memory_map(res.prg.read_bytes(), res.kick_debug, res.prg.name)
            symbols = self._build_symbols(res)
        else:
            m = memmap.from_prg(res.prg.read_bytes(), res.prg.name)
            symbols = self._build_symbols(res)
        return m, symbols, f"Last build: {res.prg.name}"

    @staticmethod
    def _build_symbols(res: BuildResult) -> dict[int, str]:
        """address -> label for a build that wasn't made by the built-in assembler: from Kick
        Assembler's debug dump, or else its VICE labels file."""
        if res.asm_result:
            return {}
        if res.kick_debug is not None:
            from ..kickdbg import symbols
            return symbols(res.kick_debug)
        out: dict[int, str] = {}
        if res.labels and res.labels.exists():
            for line in res.labels.read_text(errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "al":
                    try:
                        addr = int(parts[1].split(":")[-1], 16)
                    except ValueError:
                        continue
                    name = parts[2].lstrip(".")
                    if name.startswith("__") and name.endswith("__"):
                        continue      # ld65's own symbols (segment sizes, offsets): small numbers, not places
                    out.setdefault(addr, name)
        return out

    # ------------------------------------------------------------------ Project Information panel
    def _show_project_info(self, action, value):
        action.set_state(value)
        on = value.get_boolean()
        self.projinfo.set_visible(on)
        self.settings.show_project_info = on
        self.settings.save()
        if on:
            self.projinfo.refresh()

    def _project_info(self):
        """What the Project Information panel shows: the project's labels, variables and macros."""
        from ..projinfo import collect
        if not self.project:
            return None
        unsaved = {str(e.path.resolve()): e.get_text() for e in self.editors()
                   if isinstance(e, SourceEditor) and e.path and e.modified}
        basic = {}
        for f in self.project.all_files():
            if f.suffix.lower() == ".bas":
                key = str(f.resolve())
                try:
                    basic[key] = unsaved.get(key) or f.read_text(errors="replace")
                except OSError:
                    pass
        return collect(self.symbol_index().symbols(), basic, self.project.directory, self._symbol_value)

    def _open_source_line(self, file: str, line: int):
        ed = self.open_file(Path(file))
        if isinstance(ed, SourceEditor):
            ed.goto_line(line)

    def _insert_into_last_source(self, text: str) -> str | None:
        ed = self._last_source
        if ed is None or ed not in self.editors():
            return None
        # On a line of its own: after the cursor's line if the cursor is part-way along one.
        if ed.is_pbasic and re.match(r"\s*\d", text):
            # a tool's numbered BASIC, going into pBASIC: labels for its jumps, no line numbers
            from ..basic.pbasic import from_basic
            from ..basic.tokenizer import BasicErrors
            try:
                text = from_basic(text, self.settings.pbasic_options().prefix)[0]
            except BasicErrors:
                pass
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
            text = detokenize(data, style=self.settings.basic_code_style)
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
        self._watch_breakpoints(ed)
        ed.replace_text(text)
        self._add_page(ed)
        self.toast(f"Listed {label}. Save to keep it as {dest.name}")
        return ed

    def renumber_dialog(self):
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor) or not ed.is_basic:
            self.toast("Renumbering works on a BASIC (.bas) file")
            return
        if ed.is_pbasic:
            self.toast("pBASIC has no line numbers to renumber: Preferences → BASIC sets how it's numbered")
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

    # ================================================================== tasks
    def refresh_tasks(self):
        """Rescan the project's files (and open editors, as they are now) for TODOs."""
        from ..tasks import SOURCE_EXTS, TaskList
        if getattr(self, "_tasks", None) is None:
            self._tasks = TaskList()
        files = [f for f in (self.project.all_files() if self.project else []) if f.suffix.lower() in SOURCE_EXTS]
        seen = {f.resolve() for f in files}
        for e in self.editors():
            if isinstance(e, SourceEditor) and e.path and e.path.suffix.lower() in SOURCE_EXTS \
                    and e.path.resolve() not in seen:
                files.append(e.path)
        overrides = {str(e.path): e.get_text() for e in self.editors()
                     if isinstance(e, SourceEditor) and e.path and e.modified}
        tasks = self._tasks.update(files, overrides)
        self.tasks_panel.set_tasks(tasks, self.project.directory if self.project else None)
        self.tasks_page.set_badge_number(len(tasks))

    def _tick_tasks(self):
        if self.get_visible():
            try:
                self.refresh_tasks()
            except Exception:  # never let the scanner stop the timer
                pass
        return True

    # ------------------------------------------------------------------ Find in Files
    def find_in_files(self):
        """Ctrl+Shift+F: the Find Results tab, searching for the selection or the word at the cursor."""
        ed = self.current_editor()
        text = ed.selected_or_word() if isinstance(ed, SourceEditor) else ""
        self.bottom_stack.set_visible_child_name("find")
        self.find_panel.start(text)

    def find_in_file(self, replace: bool):
        """Ctrl+F / Ctrl+H: the find bar in the source file in front, with the selection or word."""
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor):
            return
        if ed.find_bar is None:
            self.toast("Find needs GtkSourceView: sudo apt install gir1.2-gtksource-5")
            return
        ed.find_bar.open(ed.selected_or_word(), replace)

    def _find_step(self, forward: bool):
        ed = self.current_editor()
        if isinstance(ed, SourceEditor) and ed.find_bar is not None:
            if not ed.find_bar.settings.get_search_text():
                ed.find_bar.open(ed.selected_or_word())
            elif forward:
                ed.find_bar.next()
            else:
                ed.find_bar.previous()

    def _find_texts(self, scope: str) -> dict[str, str]:
        """{file: text} to search: open files as they are in the editor (unsaved changes too)."""
        open_texts = {str(Path(e.path).resolve()): e.get_text() for e in self.editors()
                      if isinstance(e, SourceEditor) and e.path}
        if scope == "current":
            ed = self.current_editor()
            ed = ed if isinstance(ed, SourceEditor) else self._last_source
            if ed is None or ed not in self.editors() or not ed.path:
                return {}
            return {str(Path(ed.path).resolve()): ed.get_text()}
        if scope == "open":
            return dict(sorted(open_texts.items()))
        texts: dict[str, str] = {}
        files = self.project.all_files() if self.project else []
        for f in sorted(files, key=lambda f: str(f).lower()):
            if f.suffix.lower() not in SOURCE_EXTS:
                continue
            key = str(f.resolve())
            if key in open_texts:
                texts[key] = open_texts[key]
                continue
            try:
                data = f.read_bytes()
            except OSError:
                continue
            try:
                texts[key] = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                texts[key] = data.decode("cp1252", errors="replace")
        for key, text in open_texts.items():      # open files outside the project too
            texts.setdefault(key, text)
        return texts

    def _open_match(self, m):
        ed = self.open_file(Path(m.file))
        if isinstance(ed, SourceEditor):
            ed.select_match(m.line, m.col, m.length)

    def _open_task(self, task):
        ed = self.open_file(Path(task.file))
        if isinstance(ed, SourceEditor):
            ed.goto_line(task.line)

    def add_todo(self):
        """Edit → Add TODO: a task above the cursor's line, as the file's language writes one."""
        from ..tasks import basic_todo, todo_line
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor):
            self.toast("Open a source file to add a TODO to")
            return
        dlg = Adw.AlertDialog(heading="Add TODO", body="A task, shown in the Tasks panel until you remove it.")
        entry = Gtk.Entry(placeholder_text="What needs doing", activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Add")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            text = entry.get_text().strip()
            line_no = ed.current_line()
            if ed.is_basic and not ed.is_pbasic:
                new, at = basic_todo(ed.get_text(), line_no, text)
                ed.replace_text(new)
                ed.goto_line(at)
            else:
                buf = ed.buffer
                ok, it = buf.get_iter_at_line(line_no - 1)
                end = it.copy()
                if not end.ends_line():
                    end.forward_to_line_end()
                current = buf.get_text(it, end, False)
                kind = "pbasic" if ed.is_pbasic else "c" if ed.is_c else \
                    "kick" if self.project and self.project.toolchain == TOOLCHAIN_KICKASS else "cbm"
                buf.begin_user_action()
                buf.insert(it, todo_line(current, text, kind) + "\n")
                buf.end_user_action()
                ed.goto_line(line_no)
            self.refresh_tasks()
        dlg.choose(self, None, chosen)

    # ================================================================== definitions
    ASM_EXTS = (".asm", ".s", ".a", ".inc", ".i")

    def symbol_index(self):
        """The project's definitions, brought up to date (unsaved editors included)."""
        from ..symindex import SymbolIndex
        if getattr(self, "_symbols", None) is None:
            self._symbols = SymbolIndex()
        files = [f for f in (self.project.all_files() if self.project else []) if f.suffix.lower() in self.ASM_EXTS]
        seen = {f.resolve() for f in files}
        for e in self.editors():
            if isinstance(e, SourceEditor) and e.path and e.path.suffix.lower() in self.ASM_EXTS \
                    and e.path.resolve() not in seen:
                files.append(e.path)
        overrides = {str(e.path): e.get_text() for e in self.editors()
                     if isinstance(e, SourceEditor) and e.path and e.modified}
        kick = None if not self.project else self.project.toolchain == TOOLCHAIN_KICKASS
        self._symbols.update(files, overrides, kick)
        return self._symbols

    def _symbol_value(self, sym) -> int | None:
        """A label's value in the last build (found by where it's defined), if it was built."""
        res = getattr(self, "last_build", None)
        if res is None:
            return None
        here = Path(sym.file).resolve()
        if res.asm_result is not None:
            for key, loc in res.asm_result.label_locs.items():
                if loc.line == sym.line and loc.file and Path(loc.file).resolve() == here:
                    return res.asm_result.symbols.get(key)
        if res.kick_debug is not None:
            for addr, _name, f, line in res.kick_debug.labels:
                if line == sym.line and f and Path(f).resolve() == here:
                    return addr
        return None

    def describe_symbol(self, ed, line_text: str, col: int, line_no: int) -> str | None:
        """Hover text for a name: where it's defined, that line, and its value in the last build."""
        from ..symindex import word_at
        if not ed.path:
            return None
        _s, _e, word = word_at(line_text, col)
        if not word:
            return None
        defs = self.symbol_index().definitions(word, str(ed.path), line_no)
        if not defs:
            return None
        d = defs[0]
        try:
            where = os.path.relpath(d.file, self.project.directory) if self.project else Path(d.file).name
        except ValueError:
            where = d.file
        text = f"{d.name}: {d.kind} in {where}, line {d.line}\n{d.text}"
        v = self._symbol_value(d) if d.kind in ("label", "local") else None
        if v is not None:
            text += f"\n= ${v:04X} ({v}) in the last build"
        if len(defs) > 1:
            text += f"\n(also defined in {len(defs) - 1} other place{'s' if len(defs) > 2 else ''})"
        return text + "\nF12 or Ctrl+click: go to it"

    def goto_definition(self, ed=None):
        """F12 / Ctrl+click / right-click: open where the name at the cursor is defined (or the
        file an include line names, or in BASIC the line a GOTO goes to)."""
        from ..symindex import basic_target, include_at, word_at
        ed = ed or self.current_editor()
        if not isinstance(ed, SourceEditor):
            return
        line_no, col, line_text = ed.position_at_click()
        ed._click_iter_offset = None
        if ed.is_basic:
            target = basic_target(ed.get_text(), line_no, col, self.settings.pbasic_options().prefix)
            if target is None:
                self.toast("Put the cursor on the line number (or label) after a GOTO, GOSUB or THEN")
                return
            self._push_back(ed)
            ed.goto_line(target)
            return
        inc = include_at(line_text, ed.path.parent) if ed.path else None
        _s, _e, word = word_at(line_text, col)
        if inc is not None and (not word or line_text.find(word) > line_text.find(" ")):
            if inc.exists():
                self._push_back(ed)
                self.open_file(inc)
            else:
                self.toast(f"{inc.name} doesn't exist")
            return
        if not word:
            self.toast("Put the cursor on a label, constant or macro name")
            return
        defs = self.symbol_index().definitions(word, str(ed.path) if ed.path else None, line_no)
        here = str(ed.path.resolve()) if ed.path else None
        others = [d for d in defs if not (d.file == here and d.line == line_no)]
        if not defs:
            self.toast(f"No definition of {word} in the project")
            return
        if not others:
            self.toast(f"This is where {word} is defined")
            return
        if len(others) == 1:
            self._jump_to(ed, others[0])
            return
        self._choose_definition(ed, word, others)

    def _jump_to(self, ed, sym):
        self._push_back(ed)
        target = self.open_file(Path(sym.file))
        if isinstance(target, SourceEditor):
            target.goto_position(sym.line, sym.col, len(sym.name))

    def _choose_definition(self, ed, word, defs):
        dlg = Adw.AlertDialog(heading=f"{word} is defined in {len(defs)} places")
        lb = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        for d in defs:
            try:
                where = os.path.relpath(d.file, self.project.directory) if self.project else Path(d.file).name
            except ValueError:
                where = d.file
            row = Adw.ActionRow(title=GLib.markup_escape_text(f"{where}:{d.line}"),
                                subtitle=GLib.markup_escape_text(d.text), activatable=True)
            row.connect("activated", lambda _r, s=d: (dlg.close(), self._jump_to(ed, s)))
            lb.append(row)
        sc = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=360)
        sc.set_child(lb)
        dlg.set_extra_child(sc)
        dlg.add_response("cancel", "Cancel")
        dlg.present(self)

    def _push_back(self, ed):
        if not ed.path:
            return
        stack = self.__dict__.setdefault("_back", [])
        stack.append((ed.path, ed.current_line()))
        del stack[:-50]

    def go_back(self):
        """Alt+Left: back to where Go to Definition jumped from."""
        stack = self.__dict__.get("_back") or []
        if not stack:
            self.toast("Nowhere to go back to")
            return
        path, line = stack.pop()
        ed = self.open_file(path)
        if isinstance(ed, SourceEditor):
            ed.goto_line(line, select=False)

    # ================================================================== git
    def _repo(self, quiet: bool = False):
        from ..gitrepo import Repo, available
        if not self.project:
            if not quiet:
                self.toast("Open a project first")
            return None
        if not available():
            if not quiet:
                self.toast("git isn't installed: sudo apt install git")
            return None
        return Repo(self.project.directory, self.settings.git_author, self.settings.git_email)

    def _git_branch_name(self) -> str | None:
        """The project's Git branch, or None if it isn't in a repository (for the status bar)."""
        r = self._repo(quiet=True)
        try:
            return r.branch() if r is not None and r.is_repo() else None
        except Exception:
            return None

    def _git_status_map(self) -> dict:
        r = self._repo(quiet=True)
        if r is None:
            return {}
        try:
            return r.status()
        except Exception:
            return {}

    def _git_page(self, title: str, text: str, language: str | None = None, key: str | None = None):
        from .textpage import TextPage
        key = key or title
        for ed in self.editors():
            if isinstance(ed, TextPage) and ed.key == key:
                ed.set_text(text)
                self.tab_view.set_selected_page(self.tab_view.get_page(ed))
                return ed
        return self._add_page(TextPage(title, text, language, key))

    def _git_run(self, fn, done=None):
        """Run a git command, telling of a failure."""
        from ..gitrepo import GitError
        try:
            out = fn()
        except GitError as e:
            self.toast(f"Git: {e}")
            return None
        self._populate_files()
        if done:
            done(out)
        return out

    def git_status(self):
        r = self._repo()
        if r is None:
            return
        if not r.is_repo():
            self.toast("The project isn't in a Git repository: Git → Create a Repository")
            return

        def show(st):
            lines = [f"On branch {r.branch()} in {r.root}", ""]
            if not st:
                lines.append("Nothing to commit: everything is as last committed.")
            for p, s in sorted(st.items()):
                try:
                    rel = p.relative_to(r.root)
                except ValueError:
                    rel = p
                lines.append(f"  {s.letter}  {rel}    ({s.description})")
            self._git_page("Git Status", "\n".join(lines) + "\n")
        self._git_run(r.status, show)

    def git_diff(self, path: Path | None = None):
        r = self._repo()
        if r is None:
            return
        self._git_run(lambda: r.diff(path), lambda text: self._git_page(
            f"Changes: {path.name}" if path else "Changes", text or "No changes since the last commit.\n", "diff"))

    def git_log(self, path: Path | None = None):
        r = self._repo()
        if r is None:
            return

        def show(commits):
            lines = [f"{c.hash}  {c.date}  {c.author:16}  {c.subject}" for c in commits]
            self._git_page(f"History: {path.name}" if path else "History",
                           "\n".join(lines) + "\n" if lines else "Nothing committed yet.\n")
        self._git_run(lambda: r.log(path), show)

    def git_do(self, what: str, path: Path | None = None):
        r = self._repo()
        if r is None:
            return
        name = path.name if path else "all files"
        fn = {"add": lambda: r.add([path]), "add-all": r.add_all, "remove": lambda: r.remove([path])}[what]
        msg = {"add": f"Added {name}", "add-all": "Added all the project's files",
               "remove": f"{name} taken out of the repository (the file is kept)"}[what]
        self._git_run(fn, lambda _o: self.toast(msg))

    def git_file(self, spec: str):
        """A file list menu command: "what|path"."""
        what, _, p = spec.partition("|")
        path = Path(p)
        if what == "open":
            self.open_file(path)
        elif what == "diff":
            self.git_diff(path)
        elif what == "log":
            self.git_log(path)
        elif what == "commit":
            self.git_commit_dialog(path)
        else:
            self.git_do(what, path)

    def git_init(self):
        from ..gitrepo import DEFAULT_IGNORE
        r = self._repo()
        if r is None:
            return
        if r.is_repo():
            self.toast(f"The project is already in a repository ({r.root})")
            return
        self._git_run(lambda: r.init(self.project.name, self.settings.git_author, "",
                                     self.settings.git_ignore or DEFAULT_IGNORE),
                      lambda _o: self.toast("Made a Git repository for the project, with an ignore list"))

    def git_ignore_list(self):
        r = self._repo()
        if r is None:
            return
        root = r.root or self.project.directory
        path = root / ".gitignore"
        if not path.exists():
            from ..gitrepo import DEFAULT_IGNORE
            import time as _t
            path.write_text((self.settings.git_ignore or DEFAULT_IGNORE).replace("{project}", self.project.name)
                            .replace("{now}", _t.strftime("%Y-%m-%d %H:%M"))
                            .replace("{author}", self.settings.git_author).replace("{comment}", ""))
        self.open_file(path)

    def git_commit_dialog(self, path: Path | None = None):
        r = self._repo()
        if r is None:
            return
        if not r.is_repo():
            self.toast("The project isn't in a Git repository: Git → Create a Repository")
            return
        for ed in self.editors():                  # commit what's on screen
            if ed.modified and ed.path and isinstance(ed, SourceEditor):
                self._save(ed)
        try:
            st = r.status()
        except Exception as e:
            self.toast(f"Git: {e}")
            return
        dlg = Adw.AlertDialog(heading=f"Commit {path.name}" if path else "Commit",
                              body=("Changed: " + ", ".join(sorted(p.name for p in st))) if st and not path
                              else ("" if st else "Nothing has changed since the last commit."))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        msg = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6, left_margin=6,
                           css_classes=["card"])
        msg.set_size_request(380, 90)
        box.append(Gtk.Label(label="Message", xalign=0))
        box.append(msg)
        author = Gtk.Entry(text=self.settings.git_author, placeholder_text="git's user.name")
        email = Gtk.Entry(text=self.settings.git_email, placeholder_text="git's user.email")
        for label, w in (("Author", author), ("Email", email)):
            box.append(Gtk.Label(label=label, xalign=0))
            box.append(w)
        add_first = Gtk.CheckButton(label="Add changed files first" if not path else "Add the file first",
                                    active=self.settings.git_auto_add)
        box.append(add_first)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Commit")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            b = msg.get_buffer()
            text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
            r.author, r.email = author.get_text().strip(), email.get_text().strip()
            self._git_run(lambda: r.commit(text, [path] if path else None, add_first.get_active()),
                          lambda h: self.toast(f"Committed {h}"))
        dlg.choose(self, None, chosen)

    def _file_op_item(self, label: str, op: str, path: Path) -> Gio.MenuItem:
        it = Gio.MenuItem.new(label, None)
        it.set_action_and_target_value("win.file-op", GLib.Variant.new_string(f"{op}|{path}"))
        return it

    def _new_in_folder_menu(self, folder: Path) -> Gio.Menu:
        new = Gio.Menu()
        for label, kind in (("Source File…", "asm"), ("BASIC File…", "bas"), ("pBASIC File…", "pbas"),
                            ("C File…", "c"), ("C Header File…", "h"),
                            ("Sprite Set…", "spt"), ("Character Set…", "cst"), ("Screen Design…", "sdd"),
                            ("Disk Image…", "d64")):
            new.append_item(self._file_op_item(label, f"new-{kind}", folder))
        sec = Gio.Menu()
        sec.append_submenu("New", new)
        sec.append_item(self._file_op_item("New Folder…", "new-folder", folder))
        return sec

    def _project_root_menu(self, x, y):
        """Right-click below the files: make a file or folder at the top of the project."""
        if not self.project:
            return
        menu = Gio.Menu()
        menu.append_section(None, self._new_in_folder_menu(self.project.directory))
        reveal = Gio.Menu()
        reveal.append_item(self._file_op_item("Reveal in File Manager", "reveal", self.project.path))
        menu.append_section(None, reveal)
        # not on the ListView itself: it owns its children, and a popover there crashes GTK
        ok, pt = self.file_list.compute_point(self._sidebar, Graphene.Point().init(x, y))
        self._popup_menu(menu, self._sidebar, pt.x if ok else x, pt.y if ok else y)

    def _file_menu(self, row_widget: Gtk.TreeExpander, x, y):
        """Right-click in the file tree: open, rename, delete, the build list, the file manager and Git."""
        row = row_widget.get_list_row()
        if row is None or not self.project:
            return
        self._popup_menu(self._file_menu_model(row.get_item().node), row_widget, x, y)

    def _file_menu_model(self, node) -> Gio.Menu:
        from ..project.fileops import build_index
        path = node.path
        inside = path.is_relative_to(self.project.directory.resolve())
        menu = Gio.Menu()
        if node.is_dir:
            if inside:
                menu.append_section(None, self._new_in_folder_menu(path))
        else:
            menu.append_item(self._file_op_item("Open", "open", path))
        edit = Gio.Menu()
        if inside and path != self.project.directory.resolve():
            edit.append_item(self._file_op_item("Rename…", "rename", path))
            edit.append_item(self._file_op_item("Move to Trash…", "delete", path))
        menu.append_section(None, edit)
        cc65_source = self.project.toolchain == TOOLCHAIN_CC65 and path.suffix.lower() in (".c", ".s", ".asm")
        if not node.is_dir and path.suffix.lower() in SOURCE_EXTS and \
                (self.project.toolchain != TOOLCHAIN_CC65 or cc65_source):
            build = Gio.Menu()
            if self.project.toolchain in (TOOLCHAIN_CBM, TOOLCHAIN_CC65):
                i = build_index(self.project, path)
                if i is None:
                    build.append_item(self._file_op_item("Add to Build", "build-add", path))
                else:
                    build.append_item(self._file_op_item("Remove from Build", "build-remove", path))
                    if i > 0:
                        build.append_item(self._file_op_item("Build Earlier", "build-earlier", path))
                    if i < len(self.project.build_list) - 1:
                        build.append_item(self._file_op_item("Build Later", "build-later", path))
            elif (self.project.directory / self.project.main_file).resolve() != path:
                build.append_item(self._file_op_item("Set as Main File", "set-main", path))
            menu.append_section(None, build)
        reveal = Gio.Menu()
        reveal.append_item(self._file_op_item("Reveal in File Manager", "reveal", path))
        menu.append_section(None, reveal)
        if not node.is_dir and self._repo(quiet=True) is not None:
            git = Gio.Menu()
            for label, what in (("Add", "add"), ("Commit This File…", "commit"), ("Changes (diff)", "diff"),
                                ("History (log)", "log"), ("Remove from the Repository", "remove")):
                it = Gio.MenuItem.new(label, None)
                it.set_action_and_target_value("win.git-file", GLib.Variant.new_string(f"{what}|{path}"))
                git.append_item(it)
            menu.append_section("Git", git)
        return menu

    @staticmethod
    def _popup_menu(menu: Gio.Menu, widget: Gtk.Widget, x, y):
        pop = Gtk.PopoverMenu.new_from_model(menu)
        pop.set_parent(widget)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    # ================================================================== managing the project's files
    def file_op(self, op: str, path_str: str):
        """A command from the file tree's right-click menu on ``path``."""
        from ..project import fileops
        path = Path(path_str)
        p = self.project
        if op == "open":
            self.open_file(path)
        elif op == "reveal":
            self.reveal_in_file_manager(path)
        elif op.startswith("new-") and op != "new-folder":
            self.new_file_dialog(op[4:], path)
        elif op == "new-folder":
            self._name_dialog("New folder", "Create", "", path, lambda name: self._make_folder(path / name))
        elif op == "rename":
            self._name_dialog(f"Rename {path.name}", "Rename", path.name, path.parent,
                              lambda name: self._rename(path, path.parent / name), current=path)
        elif op == "delete":
            self._confirm_trash(path)
        elif p is not None and op.startswith(("build-", "set-main")):
            changed = {"build-add": lambda: fileops.build_add(p, path),
                       "build-remove": lambda: fileops.build_remove(p, path),
                       "build-earlier": lambda: fileops.build_move(p, path, -1),
                       "build-later": lambda: fileops.build_move(p, path, 1),
                       "set-main": lambda: self._set_main_file(path)}[op]()
            if changed:
                p.save()
                self._populate_files()

    # ------------------------------------------------------------------ drag to move
    def _drag_prepare(self, exp: Gtk.TreeExpander):
        """What a drag from a tree row carries: the file's path. Only the project's own files move."""
        row = exp.get_list_row()
        if row is None or not self.project:
            return None
        path = row.get_item().node.path
        if not path.exists() or not path.is_relative_to(self.project.directory.resolve()):
            return None
        return Gdk.ContentProvider.new_for_value(str(path))

    def _drag_icon(self, source: Gtk.DragSource, exp: Gtk.TreeExpander):
        """The file's icon under the pointer while dragging. Not a picture of the row: a move rebuilds
        the tree, and a drag icon still showing a destroyed row crashes GTK."""
        row = exp.get_list_row()
        if row is None:
            return
        node = row.get_item().node
        theme = Gtk.IconTheme.get_for_display(self.get_display())
        icon = theme.lookup_icon("folder-symbolic" if node.is_dir else _file_icon(node.path), None, 24,
                                 self.get_scale_factor(), Gtk.TextDirection.NONE, 0)
        source.set_icon(icon, 12, 12)

    def _drop_folder(self, exp: Gtk.TreeExpander) -> Path | None:
        """Where a drop on a row goes: into the folder, or the folder a file is in."""
        row = exp.get_list_row()
        if row is None:
            return None
        node = row.get_item().node
        return node.path if node.is_dir else node.path.parent

    def _drop_into(self, folder: Path | None, value) -> bool:
        from ..project.fileops import check_move
        if folder is None or not value or not self.project:
            return False
        src = Path(str(value))
        if not folder.resolve().is_relative_to(self.project.directory.resolve()):
            self.toast("Files can only be moved within the project folder")
            return False
        why = check_move(src, folder)
        if why == "":
            return False
        if why:
            self.toast(why)
            return False
        # Moved once the drag is over: the move rebuilds the tree, and GTK crashes if a row it's still
        # using for the drag is destroyed. (So folders don't open on hover either: that rebuilds rows
        # under the pointer.) A timer covers a drag that never reports its end.
        self._pending_move = (src, folder / src.name)
        GLib.timeout_add(1000, self._do_pending_move)
        return True

    def _do_pending_move(self):
        move, self._pending_move = getattr(self, "_pending_move", None), None
        if move is not None:
            self._rename(*move)
        return False

    def _set_main_file(self, path: Path) -> bool:
        from ..project.fileops import relative
        self.project.main_file = relative(self.project, path)
        self.toast(f"Kick Assembler now builds {path.name}")
        return True

    def _name_dialog(self, heading: str, verb: str, name: str, folder: Path, done, current: Path | None = None):
        """Ask for a file or folder name in ``folder``; refuse names that clash or can't be used."""
        from ..project.fileops import check_name
        dlg = Adw.AlertDialog(heading=heading)
        entry = Gtk.Entry(text=name, activates_default=True)
        problem = Gtk.Label(css_classes=["error", "caption"], xalign=0, visible=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(entry)
        box.append(problem)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", verb)
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def check(*_):
            text = entry.get_text().strip()
            why = check_name(folder, text, current)
            same = current is not None and text == current.name
            problem.set_text(why or "")
            problem.set_visible(bool(why) and bool(text))
            dlg.set_response_enabled("ok", why is None and not same)
        entry.connect("changed", check)
        check()
        if current is not None and current.is_file() and "." in name:
            GLib.idle_add(lambda: (entry.select_region(0, name.rindex(".")), False)[1])   # the name, not .asm

        def chosen(d, res):
            if d.choose_finish(res) == "ok":
                done(entry.get_text().strip())
        dlg.choose(self, None, chosen)

    def _make_folder(self, folder: Path):
        try:
            folder.mkdir()
        except OSError as e:
            self.toast(f"Couldn't make {folder.name}: {e.strerror}")
            return
        self._expand_after_refresh = {folder.parent.resolve()}
        self._populate_files()

    def _affected_editors(self, old: Path) -> list[EditorPage]:
        """The open tabs showing ``old`` or (for a folder) a file inside it."""
        old = old.resolve()
        return [e for e in self.editors() if getattr(e, "path", None)
                and (Path(e.path).resolve() == old or old in Path(e.path).resolve().parents)]

    def _rename(self, old: Path, new: Path):
        """Rename a file or folder, then the project's settings and open tabs to match."""
        from ..project import fileops
        old_r = old.resolve()
        affected = self._affected_editors(old_r)
        try:
            old.rename(new)
        except OSError as e:
            self.toast(f"Couldn't rename {old.name}: {e.strerror}")
            return
        new_r = new.resolve()
        self._sync_breakpoints()
        self.breakpoints.rename(old_r, new_r)
        if fileops.rename(self.project, old_r, new_r):
            self.project.save()
        for ed in affected:
            here = Path(ed.path).resolve()
            self._retarget_tab(ed, new_r / here.relative_to(old_r) if here != old_r else new_r)
        self._folder_renamed = (old_r, new_r)
        self._populate_files()
        self._update_title()
        if new.is_dir():
            return
        texts = {}
        for f in self.project.all_files():
            if f.suffix.lower() in SOURCE_EXTS and f.is_file():
                try:
                    texts[str(f)] = f.read_text(errors="replace")
                except OSError:
                    pass
        still = fileops.including_lines(texts, old_r)
        if still:
            files = sorted({Path(f).name for f, _n in still})
            toast = Adw.Toast(title=f"{len(still)} include line{'s' if len(still) > 1 else ''} still "
                                    f"name{'' if len(still) > 1 else 's'} {old.name} ({', '.join(files)})", button_label="Show", timeout=10)
            toast.connect("button-clicked", lambda *_: self._open_source_line(*still[0]))
            self.toasts.add_toast(toast)

    def _retarget_tab(self, ed: EditorPage, new: Path):
        """A file open in a tab was renamed or moved: follow it."""
        page = self.tab_view.get_page(ed)
        if page is None:
            return
        if isinstance(ed, SourceEditor) and Path(ed.path).suffix.lower() == new.suffix.lower():
            old_key = str(Path(ed.path).resolve())
            ed.path = new
            if self.pages.get(old_key) is page:
                del self.pages[old_key]
            self.pages[str(new.resolve())] = page
            page.set_title(("● " if ed.modified else "") + ed.title)
            page.set_tooltip(str(new))
            return
        # other editors keep their path in more places (export links, ...): reopen them at the new path
        if ed.modified:
            self._save(ed)
        pos = self.tab_view.get_page_position(page)
        front = self.tab_view.get_selected_page()
        self._force_close = True
        self.tab_view.close_page(page)
        self._force_close = False
        reopened = self.open_file(new)
        p2 = self.tab_view.get_page(reopened) if reopened is not None else None
        if p2 is not None:
            self.tab_view.reorder_page(p2, min(pos, self.tab_view.get_n_pages() - 1))
            if front is not page and front is not None and self.tab_view.get_page_position(front) >= 0:
                self.tab_view.set_selected_page(front)

    def _confirm_trash(self, path: Path):
        from ..project.fileops import build_index
        notes = []
        if path.is_dir():
            n = sum(1 for f in path.rglob("*") if f.is_file())
            notes.append(f"It holds {n} file{'s' if n != 1 else ''}.")
        elif build_index(self.project, path) is not None:
            notes.append("It comes off the build list.")
        if self._affected_editors(path):
            notes.append("Its open tabs close, without saving.")
        what = "folder" if path.is_dir() else "file"
        dlg = Adw.AlertDialog(heading=f"Move {path.name} to the Trash?",
                              body=" ".join(notes + [f"You can restore the {what} from the Trash."]))
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("trash", "Move to Trash")
        dlg.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.choose(self, None, lambda d, res: d.choose_finish(res) == "trash" and self._trash(path))

    def _trash(self, path: Path):
        from ..project.fileops import forget
        try:
            Gio.File.new_for_path(str(path)).trash(None)
        except GLib.Error as e:
            self.toast(f"Couldn't move {path.name} to the Trash: {e.message}")
            return
        self._force_close = True
        for ed in self._affected_editors(path):
            page = self.tab_view.get_page(ed)
            if page is not None:
                self.tab_view.close_page(page)
        self._force_close = False
        self.breakpoints.forget(path)
        self._breakpoints_updated()
        if forget(self.project, path):
            self.project.save()
        self._populate_files()
        self._update_title()
        self.toast(f"Moved {path.name} to the Trash")

    # ================================================================== user tools
    def refresh_user_tools(self):
        """The User Tools menu, from Preferences."""
        from ..usertools import UserTool
        self.user_tools_menu.remove_all()
        tools = [UserTool.from_dict(d) for d in self.settings.user_tools]
        for i, t in enumerate(tools):
            self.user_tools_menu.append(t.name or t.command, f"win.user-tool({i})")
        self.user_tools_menu.append("Set Up User Tools…", "app.preferences")

    def run_user_tool(self, i: int):
        from ..usertools import Context, ToolError, UserTool, run
        try:
            tool = UserTool.from_dict(self.settings.user_tools[i])
        except IndexError:
            return
        ed = self.current_editor()
        if not (isinstance(ed, SourceEditor) and ed.path):
            ed = self._last_source if self._last_source in self.editors() else ed
        current = ed.path if ed is not None and getattr(ed, "path", None) else None
        last = getattr(self, "last_build", None)
        ctx = Context.make(self.project, current, last.prg if last and last.prg else None)
        if not tool.capture:
            try:
                run(tool, ctx)
                self.toast(f"Started {tool.name}")
            except ToolError as e:
                self.toast(str(e))
            return
        self.bottom_stack.set_visible_child_name("output")
        self._set_log(f"Running {tool.name}…")

        def work():
            try:
                ok, out = run(tool, ctx)
                text = f"> {tool.name}\n{out}" if out else f"> {tool.name}\n(nothing printed)"
            except ToolError as e:
                ok, text = False, str(e)
            GLib.idle_add(lambda: (self._set_log(text), self.toast(f"{tool.name} {'finished' if ok else 'failed'}"),
                                   False)[2])
        threading.Thread(target=work, daemon=True).start()

    # ================================================================== source converter
    def convert_source(self, path: Path | None = None):
        from .convert_dialog import ConvertDialog
        folder = self.project.directory if self.project else Path.home()

        def done(dest: Path, add: bool):
            if add and self.project:
                try:
                    rel = str(dest.relative_to(self.project.directory))
                except ValueError:
                    rel = str(dest)
                if rel not in self.project.build_list:
                    self.project.build_list.append(rel)
                    self._save_project_quietly()
            self._populate_files()
            self.open_file(dest)
            self.toast(f"Converted to {dest.name}")
        dlg = ConvertDialog(self, folder, done, can_add=bool(self.project and self.project.toolchain == TOOLCHAIN_CBM))
        dlg.present()
        if path:
            dlg.load(path)
        return dlg

    # ================================================================== BASIC token files
    def create_token_file(self):
        """Tools → Create Token File: BASIC V2's tokens in a .tkn file to edit (tokenfile.py)."""
        from ..basic.tokenfile import default_text
        folder = self.project.directory if self.project else (
            self._last_source.path.parent if self._last_source and self._last_source.path else Path.home())
        dlg = Adw.AlertDialog(heading="Create Token File",
                              body=f"BASIC V2's keywords and tokens, in {folder}, to change or add an "
                                   f"extension's keywords to. A BASIC file uses it with a tokenfile line.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        entry = Gtk.Entry(text="tokens", activates_default=True)
        copy = Gtk.CheckButton(label="Copy the 'tokenfile' line, to paste at the top of a BASIC file", active=True)
        box.append(entry)
        box.append(copy)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Create")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            name = entry.get_text().strip() or "tokens"
            path = folder / name
            if not path.suffix:
                path = path.with_suffix(".tkn")
            if path.exists():
                self.toast(f"{path.name} is there already: opened it")
            else:
                try:
                    path.write_text(default_text(self.project.name if self.project else ""))
                except OSError as e:
                    self.toast(f"Couldn't write {path.name}: {e.strerror}")
                    return
            if copy.get_active():
                Gdk.Display.get_default().get_clipboard().set(f"tokenfile {path.name}\n")
            self._populate_files()
            self.open_file(path)
            if copy.get_active():
                self.toast(f"Copied 'tokenfile {path.name}': paste it at the top of a BASIC file")
        dlg.choose(self, None, chosen)

    # ================================================================== UTF-8 check
    def open_utf8_check(self):
        from .utf8check_view import Utf8CheckView
        for ed in self.editors():
            if isinstance(ed, Utf8CheckView):
                ed.refresh()
                self.tab_view.set_selected_page(self.tab_view.get_page(ed))
                return ed

        def files(scope):
            if scope == "project" and self.project:
                return [f for f in self.project.all_files()
                        if f.suffix.lower() in (".asm", ".s", ".a", ".inc", ".i", ".bas", ".pbas", ".txt")]
            ed = self.current_editor()
            if not (isinstance(ed, SourceEditor) and ed.path):
                ed = self._last_source if self._last_source in self.editors() else None
            return [ed.path] if ed is not None and ed.path else []

        def editor_for(path, open_it=False):
            for e in self.editors():
                if isinstance(e, SourceEditor) and e.path and e.path.resolve() == Path(path).resolve():
                    return e
            return self.open_file(Path(path)) if open_it else None

        def open_at(path, line, column):
            ed = self.open_file(path)
            if isinstance(ed, SourceEditor):
                ed.goto_position(line, column - 1, 1)
        return self._add_page(Utf8CheckView(files, editor_for, open_at))

    # ================================================================== printing
    def print_source(self, preview: bool = False):
        """File → Print / Print Preview for the source file being edited."""
        from .printing import SourcePrinter
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor):
            ed = self._last_source if self._last_source in self.editors() else None
        if not isinstance(ed, SourceEditor):
            self.toast("Open a source file to print")
            return
        printer = SourcePrinter(ed, self.settings)
        if preview:
            pdf = printer.preview()
            self.toast(f"Print preview: {pdf}" if pdf else "Couldn't make the print preview")
            return
        from gi.repository import Gtk as _Gtk
        res = printer.print_(self)
        if res == _Gtk.PrintOperationResult.ERROR:
            self.toast("Printing failed")

    # ================================================================== reformatting BASIC
    def _basic_editor(self):
        ed = self.current_editor()
        if isinstance(ed, SourceEditor) and ed.is_basic:
            return ed
        self.toast("This works on a BASIC (.bas or .pbas) file")
        return None

    def _apply_reformat(self, ed, options, what: str, backup: bool = False):
        from ..basic.reformat import reformat
        text = ed.get_text()
        new, warnings = reformat(text, options)
        if backup and ed.path:
            try:
                ed.path.with_name(ed.path.name + ".bak").write_text(text)
            except OSError as e:
                self.toast(f"Couldn't write the backup: {e.strerror}")
                return
        if new != text:
            ed.replace_text(new)
        ed.clear_errors()
        for w in warnings:
            if w.line:
                ed.mark_error(w.line)
        if warnings:
            w = warnings[0]
            self.toast(f"{what}; {len(warnings)} line{'s' if len(warnings) != 1 else ''} left as "
                       f"{'they were' if len(warnings) != 1 else 'it was'} (line {w.line}: {w.message})")
        else:
            self.toast(f"{what} (Ctrl+Z to undo)" if new != text else "Nothing to change")

    def basic_keywords(self, how: str):
        """Compress (keywords abbreviated) or Uncompress (in full), as CBM prg Studio's Edit → Advanced."""
        from ..basic.reformat import Options
        ed = self._basic_editor()
        if ed:
            self._apply_reformat(ed, Options(space_after_number=False, remove_blank_lines=False, keywords=how),
                                 "Compressed" if how == "abbreviate" else "Uncompressed")

    def reformat_dialog(self):
        """CBM prg Studio's Reformat BASIC Code."""
        from ..basic.reformat import Options
        ed = self._basic_editor()
        if not ed:
            return
        dlg = Adw.AlertDialog(heading="Reformat BASIC Code",
                              body="Lines that would do anything different are left as they are.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        def check(label, active=False, tip=None):
            c = Gtk.CheckButton(label=label, active=active, tooltip_text=tip)
            box.append(c)
            return c

        def case_row(label):
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            dd = Gtk.DropDown.new_from_strings(["No case conversion", "Convert to lower case", "Convert to upper case"])
            row.append(dd)
            box.append(row)
            return dd
        box.append(Gtk.Label(label="<b>General formatting</b>", use_markup=True, xalign=0))
        space = check("Insert space after line number", True)
        blank = check("Remove blank lines", True)
        strings = case_row("Quoted strings")
        comments = case_row("Comments (REM)")
        box.append(Gtk.Label(label="<b>Source compression</b>", use_markup=True, xalign=0, margin_top=6))
        rems = check("Remove REM statements", tip="A line that's only a REM is kept as 'rem' if a GOTO goes to it")
        spaces = check("Remove spaces")
        after_rem = check("    (also after REM)")
        zeros = check("Remove zeros from DATA", tip="data 0,0.5 becomes data ,.5, which READ reads the same")
        abbrev = check("Abbreviate keywords (Compress: ? for print, pO for poke)")
        box.append(Gtk.Label(label="<b>Expand</b>", use_markup=True, xalign=0, margin_top=6))
        expand = check("Expand code (keywords in full, spaced out)")
        box.append(Gtk.Label(label="", margin_top=2))
        backup = check("Create backup file (.bak)", True)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Reformat")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        cases = [None, "lower", "upper"]

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            o = Options(space_after_number=space.get_active(), remove_blank_lines=blank.get_active(),
                        strings_case=cases[strings.get_selected()], comments_case=cases[comments.get_selected()],
                        remove_rems=rems.get_active(), remove_spaces=spaces.get_active(),
                        spaces_after_rem=after_rem.get_active(), remove_zeros=zeros.get_active(),
                        expand=expand.get_active(), keywords="abbreviate" if abbrev.get_active() else None)
            self._apply_reformat(ed, o, "Reformatted", backup.get_active())
        dlg.choose(self, None, chosen)

    # ================================================================== pBASIC
    def _pbasic_editor(self) -> SourceEditor | None:
        ed = self.current_editor()
        if isinstance(ed, SourceEditor) and ed.is_pbasic:
            return ed
        self.toast("This works on a pBASIC (.pbas) file")
        return None

    def pbasic_create_label(self):
        """CBM prg Studio's Create Label: name the line that the right-clicked jump goes to."""
        from ..basic.pbasic import create_label, jump_target_at
        from ..basic.tokenizer import BasicError
        ed = self._pbasic_editor()
        if not ed:
            return
        line, col = ed.line_at_click()
        target = jump_target_at(line, col)
        if target is None:
            self.toast("Right-click a line number that a GOTO, GOSUB, THEN, RUN or LIST jumps to")
            return
        prefix = self.settings.pbasic_options().prefix
        dlg = Adw.AlertDialog(heading="Create Label", body=f"A label for line {target}, used by every jump to it.")
        entry = Gtk.Entry(placeholder_text="name", activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Create")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            name = entry.get_text().strip().lstrip(prefix)
            try:
                text, n = create_label(ed.get_text(), target, name, prefix)
            except BasicError as e:
                self.toast(e.message)
                return
            ed.replace_text(text)
            self.toast(f"{prefix}{name} is line {target}: {n} jump{'s' if n != 1 else ''} changed (Ctrl+Z to undo)")
        dlg.choose(self, None, chosen)

    def pbasic_remove_numbers(self):
        from ..basic.pbasic import remove_line_numbers
        ed = self._pbasic_editor()
        if not ed:
            return
        text, warnings = remove_line_numbers(ed.get_text(), self.settings.pbasic_options().prefix)
        ed.replace_text(text)
        if warnings:
            w = warnings[0]
            self.toast((f"Line {w.line}: " if w.line else "") + w.message +
                       (f" (and {len(warnings) - 1} more)" if len(warnings) > 1 else ""))
        else:
            self.toast("Line numbers removed (Ctrl+Z to undo)")

    def pbasic_preview(self):
        from ..basic.pbasic import to_basic
        from ..basic.tokenizer import BasicErrors
        ed = self._pbasic_editor()
        if not ed:
            return
        try:
            res = to_basic(ed.get_text(), self.settings.pbasic_options())
        except BasicErrors as e:
            err = e.errors[0]
            if err.line:
                ed.goto_line(err.line)
            self.toast((f"Line {err.line}: " if err.line else "") + err.message)
            return
        self._show_basic_preview(ed.path, res.text)

    def _show_basic_preview(self, src: Path, text: str, select: bool = True):
        """The numbered BASIC a pBASIC file makes, in a read-only tab (one per file)."""
        dest = src.with_name(f"{src.stem} (generated).bas")
        key = str(dest.resolve())
        if key in self.pages:
            ed = self.pages[key].get_child()
            if select:
                self.tab_view.set_selected_page(self.pages[key])
        else:
            ed = SourceEditor(dest, self.settings)
            ed.view.set_editable(False)
            cur = self.tab_view.get_selected_page()
            self._add_page(ed)
            if not select and cur is not None:
                self.tab_view.set_selected_page(cur)
        ed.view.set_editable(True)
        ed.replace_text(text)
        ed.view.set_editable(False)
        ed.buffer.set_modified(False)

    def convert_to_pbasic(self):
        """A numbered BASIC file as a new pBASIC one: every jump target gets a label."""
        from ..basic.pbasic import from_basic
        from ..basic.tokenizer import BasicErrors
        ed = self.current_editor()
        if not isinstance(ed, SourceEditor) or not ed.is_basic or ed.is_pbasic or not ed.path:
            self.toast("Open a BASIC (.bas) file to convert")
            return
        try:
            text, warnings = from_basic(ed.get_text(), self.settings.pbasic_options().prefix)
        except BasicErrors as e:
            self.toast((f"Line {e.errors[0].line}: " if e.errors[0].line else "") + e.errors[0].message)
            return
        dest = ed.path.with_suffix(".pbas")
        n = 1
        while dest.exists() or str(dest.resolve()) in self.pages:
            dest = ed.path.with_name(f"{ed.path.stem}_{n}.pbas")
            n += 1
        new = SourceEditor(dest, self.settings)
        self._watch_breakpoints(new)
        new.replace_text(text)
        self._add_page(new)
        self.toast(f"Save to keep it as {dest.name}" + (f". {warnings[0].message}" if warnings else ""))

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
        toolchains = [TOOLCHAIN_CBM, TOOLCHAIN_KICKASS, TOOLCHAIN_CC65]
        tool = Adw.ComboRow(title="Assembler", model=Gtk.StringList.new(
            ["Built-in (CBM prg Studio syntax)", "Kick Assembler", "C (cc65)"]),
            selected=toolchains.index(p.toolchain) if p.toolchain in toolchains else 0)
        g.add(tool)
        main = Adw.EntryRow(title="Main file (Kick Assembler)", text=p.main_file)
        g.add(main)

        bg = Adw.PreferencesGroup(title="Build order", description=(
            "The program's C (.c) and assembler (.s) files, compiled one by one and linked in this order."
            if p.toolchain == TOOLCHAIN_CC65 else
            "Files are assembled together in this order, like CBM prg Studio's build list. Labels and macros "
            "are shared between them."))
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
            from ..project.fileops import relative
            kinds = (".c", ".s", ".asm") if p.toolchain == TOOLCHAIN_CC65 else (".asm", ".s", ".bas", ".pbas")
            candidates = [relative(p, f) for f in p.all_files()
                          if f.suffix.lower() in kinds and relative(p, f) not in order]
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

        # ---------- build page: Kick Assembler options and build events
        import shlex
        bpage = Adw.PreferencesPage(title="Build", icon_name="system-run-symbolic")
        win.add(bpage)
        is_c = p.toolchain == TOOLCHAIN_CC65
        kg = Adw.PreferencesGroup(title="C (cc65)" if is_c else "Kick Assembler", description=(
            "Every file is compiled with cl65 -t c64 -g and these options; the source folders are include "
            "paths (#include and .include) and show in the file tree." if is_c else None))
        bpage.add(kg)
        k_jar = Adw.EntryRow(title="KickAss.jar for this project (empty = the one in Preferences)",
                             text=p.kickass_jar)
        k_args = Adw.EntryRow(title="Compiler options, e.g. -O -DDEBUG" if is_c else
                              "More command-line options, e.g. -define DEBUG",
                              text=" ".join(shlex.quote(a) for a in p.assembler_args))
        k_dirs = Adw.EntryRow(title="More source folders, e.g. ../lib (separate them with ;)",
                              text="; ".join(p.lib_dirs))
        if not is_c:
            kg.add(k_jar)
        kg.add(k_args)
        if is_c:
            kg.add(k_dirs)
        dd = Adw.SwitchRow(title="Write a debug dump (.dbg)",
                           subtitle="Kick Assembler's format, which C64 Debugger, RetroDebugger and VS64 read "
                                    "for source-level debugging. Kick Assembler projects always get one.",
                           active=p.debug_dump)
        if p.toolchain == TOOLCHAIN_CBM:          # the built-in assembler's; Kick and cc65 write their own
            dg = Adw.PreferencesGroup(title="Debugging in other tools")
            dg.add(dd)
            bpage.add(dg)
        eg = Adw.PreferencesGroup(
            title="Build events",
            description="Commands run in the project folder before and after a project build, one a line, as in "
                        "CBM prg Studio. [prg], [prgName], [prgDir], [ProjectDir], [ProjectName] and [OutputDir] are "
                        "filled in; a line starting with ; is skipped; echo text writes to the build output. "
                        "Commands don't go through a shell: use sh -c \"…\" for pipes and redirection.")
        bpage.add(eg)

        def commands_box(title):
            # a group of its own, so the box sits under its title (groups put rows before other widgets)
            g = Adw.PreferencesGroup(title=title)
            bpage.add(g)
            tv = Gtk.TextView(monospace=True, top_margin=6, bottom_margin=6, left_margin=6,
                              css_classes=["card", "monospace"])
            tv.set_size_request(-1, 80)
            g.add(tv)
            return g, tv
        _pre_g, pre_tv = commands_box("Before the build")
        pre_tv.get_buffer().set_text("\n".join(p.pre_build))
        post_g, post_tv = commands_box("After the build")
        post_tv.get_buffer().set_text("\n".join(p.post_build))
        post_always = Adw.SwitchRow(title="Run them even if the build fails", active=p.post_build_always)
        ag = Adw.PreferencesGroup()
        ag.add(post_always)
        bpage.add(ag)

        def lines_of(tv):
            b = tv.get_buffer()
            return [ln for ln in b.get_text(b.get_start_iter(), b.get_end_iter(), False).splitlines() if ln.strip()]

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
        d_prog = Adw.EntryRow(title="Program file to put on the disk (empty = the built .prg)",
                              text=p.disk_program)
        d_prog.set_tooltip_text("For example a crunched copy that a post-build command makes, such as game.prg.exo")
        d_run = Adw.SwitchRow(title="Run from the disk image",
                              subtitle="Ctrl+F5 and debugging autostart the .d64 instead of the .prg",
                              active=p.run_from_disk)
        for w in (d_on, d_kind, d_path, d_name, d_id, d_file, d_prog, d_run):
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
            p.toolchain = toolchains[tool.get_selected()]
            if is_c:
                p.lib_dirs = [d.strip() for d in k_dirs.get_text().split(";") if d.strip()]
            p.main_file = main.get_text().strip()
            p.build_list = list(order)
            p.disk_image = d_path.get_text().strip() if d_on.get_active() else ""
            p.disk_name = d_name.get_text().strip()[:16]
            p.disk_id = (d_id.get_text().strip() or "00")[:2]
            p.disk_file_name = d_file.get_text().strip()[:16]
            p.run_from_disk = d_run.get_active()
            p.disk_extra_files = extras
            p.disk_program = d_prog.get_text().strip()
            p.kickass_jar = k_jar.get_text().strip()
            try:
                p.assembler_args = shlex.split(k_args.get_text())
            except ValueError:
                self.toast("The options have an unmatched quote; they weren't changed")
            p.pre_build = lines_of(pre_tv)
            p.post_build = lines_of(post_tv)
            p.post_build_always = post_always.get_active()
            p.debug_dump = dd.get_active()
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
