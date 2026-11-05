"""The Project Information panel on the right of the window, as in CBM prg Studio: Labels, Variables
and Macros tabs, each a tree of the files defining them (l64s.projinfo builds it). Double-click an
item to go to it; right-click for Refresh. Open files stay open when it refreshes."""
from __future__ import annotations

from collections.abc import Callable

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from ..projinfo import TABS, Group, Item


class _Row(GObject.Object):
    def __init__(self, group: Group | None = None, item: Item | None = None):
        super().__init__()
        self.group, self.item = group, item


class _Tab:
    """One tab: a ListView over a tree of files and their items."""

    def __init__(self, panel: "ProjectInfoPanel"):
        self.panel = panel
        self.model: Gtk.TreeListModel | None = None
        f = Gtk.SignalListItemFactory()
        f.connect("setup", self._setup)
        f.connect("bind", self._bind)
        self.view = Gtk.ListView(factory=f, css_classes=["navigation-sidebar"])
        self.view.connect("activate", self._activate)
        self.empty = Gtk.Label(label="", css_classes=["dim-label"], wrap=True, margin_top=24,
                               margin_start=12, margin_end=12, justify=Gtk.Justification.CENTER)
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=self.view, vexpand=True), "list")
        self.stack.add_named(self.empty, "empty")

    def _setup(self, _f, li):
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
        box.append(Gtk.Label(xalign=1, css_classes=["dim-label", "caption", "monospace"],
                             ellipsize=Pango.EllipsizeMode.END, max_width_chars=14))
        exp = Gtk.TreeExpander(child=box)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", lambda _g, _n, x, y: self.panel._menu(exp, x, y))
        exp.add_controller(click)
        li.set_child(exp)

    def _bind(self, _f, li):
        exp: Gtk.TreeExpander = li.get_child()
        row: Gtk.TreeListRow = li.get_item()
        exp.set_list_row(row)
        r: _Row = row.get_item()
        name, detail = list(exp.get_child())
        if r.group is not None:
            name.set_text(r.group.title)
            name.set_css_classes(["heading"])
            detail.set_text(str(len(r.group.items)))
            exp.set_tooltip_text(r.group.file)
        else:
            it = r.item
            name.set_text(("    " if it.local else "") + it.name)
            name.set_css_classes(["monospace"])
            detail.set_text(it.detail)
            exp.set_tooltip_text(f"{it.name}{' = ' + it.detail if it.detail else ''}\nline {it.line}"
                                 "\nDouble-click to go to it")

    def _activate(self, _view, pos):
        row = self.model.get_item(pos) if self.model else None
        if row is None:
            return
        r: _Row = row.get_item()
        if r.group is not None:
            row.set_expanded(not row.get_expanded())
        elif r.item.line:
            self.panel._go_to(r.item.file, r.item.line)

    def open_files(self) -> set[str]:
        if self.model is None:
            return set()
        rows = (self.model.get_item(i) for i in range(self.model.get_n_items()))
        return {r.get_item().group.file for r in rows if r.get_expanded() and r.get_item().group}

    def show(self, groups: list[Group], keep_open: set[str], empty_text: str):
        store = Gio.ListStore(item_type=_Row)
        for g in groups:
            store.append(_Row(group=g))

        def children(r: _Row):
            if r.group is None:
                return None
            st = Gio.ListStore(item_type=_Row)
            for it in r.group.items:
                st.append(_Row(item=it))
            return st
        self.model = Gtk.TreeListModel.new(store, False, False, children)
        for i in range(self.model.get_n_items() - 1, -1, -1):      # from the end: opening adds rows after
            row = self.model.get_item(i)
            if row.get_item().group and row.get_item().group.file in keep_open:
                row.set_expanded(True)
        self.view.set_model(Gtk.NoSelection(model=self.model))
        self.empty.set_text(empty_text)
        self.stack.set_visible_child_name("list" if groups else "empty")


class ProjectInfoPanel(Gtk.Box):
    def __init__(self, collect: Callable[[], dict[str, list[Group]] | None],
                 go_to: Callable[[str, int], None], on_close: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, width_request=250)
        self._collect, self._go_to_cb = collect, go_to
        head = Gtk.Box(spacing=4, margin_start=10, margin_end=4, margin_top=6, margin_bottom=2)
        head.append(Gtk.Label(label="Project Information", xalign=0, hexpand=True, css_classes=["heading"]))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh", css_classes=["flat"])
        refresh.connect("clicked", lambda *_: self.refresh())
        head.append(refresh)
        close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Close (Window → Project Information)",
                           css_classes=["flat"])
        close.connect("clicked", lambda *_: on_close())
        head.append(close)
        self.append(head)
        self.stack = Gtk.Stack(vexpand=True)
        self.tabs: dict[str, _Tab] = {}
        for key, title in TABS:
            t = _Tab(self)
            self.tabs[key] = t
            self.stack.add_titled(t.stack, key, title)
        switcher = Gtk.StackSwitcher(stack=self.stack, margin_start=8, margin_end=8, margin_bottom=4)
        self.append(switcher)
        self.append(self.stack)
        self._pending = 0

    def refresh(self):
        info = self._collect()
        for key, tab in self.tabs.items():
            if info is None:
                tab.show([], set(), "Open a project to see its labels, variables and macros")
            else:
                tab.show(info.get(key, []), tab.open_files(), f"No {key} in the project")

    def refresh_soon(self, delay_ms: int = 800):
        """Refresh once typing pauses (each call restarts the wait)."""
        if self._pending:
            GLib.source_remove(self._pending)

        def go():
            self._pending = 0
            if self.get_mapped():
                self.refresh()
            return False
        self._pending = GLib.timeout_add(delay_ms, go)

    def _go_to(self, file: str, line: int):
        self._go_to_cb(file, line)

    def _menu(self, widget: Gtk.Widget, x, y):
        menu = Gio.Menu()
        menu.append("Refresh", "projinfo.refresh")
        menu.append("Open All Files", "projinfo.expand")
        menu.append("Close All Files", "projinfo.collapse")
        group = Gio.SimpleActionGroup()
        for name, cb in (("refresh", self.refresh), ("expand", lambda: self._expand_all(True)),
                         ("collapse", lambda: self._expand_all(False))):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_a, cb=cb: cb())
            group.add_action(a)
        self.insert_action_group("projinfo", group)
        pop = Gtk.PopoverMenu.new_from_model(menu)
        pop.set_parent(widget)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _expand_all(self, on: bool):
        tab = self.tabs[self.stack.get_visible_child_name()]
        m = tab.model
        if m is None:
            return
        for i in range(m.get_n_items() - 1, -1, -1):
            row = m.get_item(i)
            if row.get_item().group is not None:
                row.set_expanded(on)
