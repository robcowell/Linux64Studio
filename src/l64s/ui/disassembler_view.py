"""Disassembler: an interactive listing of a file, the last build or VICE's memory, where you
mark code and data, name labels and add comments, then export source that reassembles exactly."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from ..binconv import Binary, ConvertError, basic_sys_address, load_binary  # noqa: E402
from ..disassembler import Session, SessionError, sidecar_path  # noqa: E402
from ..emu.values import ValueError_, parse_address  # noqa: E402
from .editor import EditorPage  # noqa: E402

SOURCES = ["File", "Last build", "Running program (VICE)"]
KEYS_HELP = ("C  code from here     D  data (line or selection)     N  name     ;  comment\n"
             "Enter  follow jump     Esc  back     G  go to address")


class DisassemblerView(EditorPage):
    kind = "disasm"

    def __init__(self, kickass: bool, project_dir: Path | None, get_build, get_session, insert_cb):
        super().__init__(None)
        self.kickass = kickass
        self.project_dir = project_dir
        self.get_build = get_build        # () -> (memory, used, {addr: label}, desc) or None
        self.get_session = get_session    # () -> DebugSession or None
        self.insert_cb = insert_cb
        self.session: Session | None = None
        self.file: Path | None = None
        self.line_addrs: list[int] = []
        self.history: list[int] = []

        bar = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=4,
                          max_children_per_line=12, margin_start=8, margin_end=8, margin_top=6)
        self.append(bar)
        self.source_dd = Gtk.DropDown.new_from_strings(SOURCES)
        bar.append(self.source_dd)
        openb = Gtk.Button(label="Open…", css_classes=["suggested-action"])
        openb.connect("clicked", self._open)
        bar.append(openb)
        self.load = self._entry(bar, "Load", "auto", "Load address for a file without one (.prg files carry it)")
        self.rng_from = self._entry(bar, "From", "0801", "Start of the range (last build or VICE)")
        self.rng_to = self._entry(bar, "To", "", "End of the range, inclusive (empty = end of the program)")
        self.entries = self._entry(bar, "Entry points", "auto", "Where code starts: auto = a BASIC loader's SYS "
                                                                "or the start; or a list (0810 c000)")
        self.trace = Gtk.CheckButton(label="Trace code", active=True,
                                     tooltip_text="Only disassemble code reachable from the entry points and your "
                                                  "code marks; everything else is data")
        self.trace.connect("toggled", lambda *_: self._setting_changed())
        bar.append(self.trace)
        self.names = Gtk.CheckButton(label="C64 names", active=True,
                                     tooltip_text="Name I/O registers and KERNAL routines (EXTCOL, SCROLX, CHROUT...)")
        self.names.connect("toggled", lambda *_: self._setting_changed())
        bar.append(self.names)
        for label, cb in (("Export Source…", self._export), ("Copy", self._copy), ("Insert into Editor", self._insert)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            bar.append(b)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=760,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)
        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=True, left_margin=6, top_margin=4,
                                 css_classes=["monospace"])
        buf = self.view.get_buffer()
        self.t_addr = buf.create_tag("addr", foreground="#8a8a8a")
        self.t_label = buf.create_tag("label", foreground="#62a0ea", weight=Pango.Weight.BOLD)
        self.t_comment = buf.create_tag("comment", foreground="#77767b", style=Pango.Style.ITALIC)
        self.t_data = buf.create_tag("data", foreground="#c64600")
        self.t_current = buf.create_tag("current", paragraph_background="rgba(255,200,0,0.18)")
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.view.add_controller(keys)
        buf.connect("notify::cursor-position", lambda *_: self._cursor_moved())
        paned.set_start_child(Gtk.ScrolledWindow(child=self.view, hexpand=True))

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=8)
        self.here = Gtk.Label(xalign=0, wrap=True, selectable=True)
        side.append(self.here)
        side.append(Gtk.Label(label="<b>Referenced from</b>", use_markup=True, xalign=0))
        self.refs = Gtk.ListBox(css_classes=["boxed-list"])
        self.refs.connect("row-activated", lambda _l, row: self.go_to(row.addr, remember=True))
        side.append(Gtk.ScrolledWindow(child=self.refs, min_content_height=100, max_content_height=180,
                                       propagate_natural_height=True))
        side.append(Gtk.Label(label="<b>Labels</b>", use_markup=True, xalign=0))
        self.labels = Gtk.ListBox(css_classes=["boxed-list"])
        self.labels.connect("row-activated", lambda _l, row: self.go_to(row.addr, remember=True))
        side.append(Gtk.ScrolledWindow(child=self.labels, vexpand=True))
        side.append(Gtk.Label(label=KEYS_HELP, xalign=0, wrap=True, css_classes=["dim-label", "caption"]))
        paned.set_end_child(side)
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"], margin_start=8,
                                margin_bottom=6)
        self.append(self.status)
        self.status.set_text("Open a file, or choose Last build or Running program and press Open.")

    @property
    def title(self) -> str:
        return "Disassembler"

    @staticmethod
    def _entry(parent, label, text, tip) -> Gtk.Entry:
        box = Gtk.Box(spacing=4)
        box.append(Gtk.Label(label=label, css_classes=["dim-label"]))
        e = Gtk.Entry(text=text, width_chars=8, tooltip_text=tip)
        box.append(e)
        parent.append(box)
        return e

    # ================================================================ loading
    def _open(self, *_):
        src = self.source_dd.get_selected()
        if src == 0:
            dlg = Gtk.FileDialog(title="Disassemble a file")
            if self.project_dir:
                dlg.set_initial_folder(Gio.File.new_for_path(str(self.project_dir)))

            def done(d, res):
                try:
                    self.load_file(Path(d.open_finish(res).get_path()))
                except GLib.Error:
                    pass
            dlg.open(self.get_root(), None, done)
            return
        try:
            if src == 1:
                build = self.get_build()
                if not build:
                    raise ConvertError("Build the project first (F7)")
                memory, used, symbols, desc = build
                last = max((a for a in range(0x10000) if used[a]), default=0)
                self._load_memory(memory, symbols, desc, last)
            else:
                s = self.get_session()
                if not s or not s.monitor.connected:
                    raise ConvertError("Start debugging (Shift+F5) to disassemble the running program")
                self._load_memory(s.snapshot_memory(), {}, "VICE snapshot", 0xFFFF)
        except (ConvertError, ValueError_) as e:
            self.status.set_text(str(e))

    def _load_memory(self, memory: bytes, symbols: dict[int, str], desc: str, default_end: int):
        start = parse_address(self.rng_from.get_text() or "0801", {n: a for a, n in symbols.items()})
        end = (parse_address(self.rng_to.get_text(), {n: a for a, n in symbols.items()})
               if self.rng_to.get_text().strip() else default_end)
        if end < start:
            raise ConvertError("'To' is before 'From'")
        self.file = None
        b = Binary(start, bytes(memory[start:end + 1]), desc)
        self._start_session(b)
        # labels from the build, for the addresses inside the range
        for a, name in symbols.items():
            if b.start <= a < b.end:
                try:
                    self.session.set_label(a, name)
                except SessionError:
                    pass
        self.refresh()

    def load_file(self, path: Path):
        try:
            load = None if self.load.get_text().strip().lower() in ("", "auto") else parse_address(self.load.get_text())
            if load is None and path.suffix.lower() != ".prg":
                load = 0xC000
                self.load.set_text("C000")
            b = load_binary(path, load)
        except (ConvertError, ValueError_, OSError) as e:
            self.status.set_text(str(e))
            return
        self.file = path
        self._start_session(b)
        side = sidecar_path(path)
        if side.is_file():
            try:
                self.session.apply_json(side.read_text())
                self.trace.set_active(self.session.trace)
                self.names.set_active(self.session.use_c64_names)
            except (ValueError, OSError) as e:
                self.status.set_text(f"Couldn't read {side.name}: {e}")
        self.refresh()

    def _start_session(self, b: Binary):
        t = self.entries.get_text().strip().lower()
        if t in ("", "auto"):
            sys_addr = basic_sys_address(b)
            entries = [sys_addr] if sys_addr else [b.start]
        else:
            entries = [parse_address(x) for x in t.replace(",", " ").split()]
        self.session = Session(b, entries, self.trace.get_active(), use_c64_names=self.names.get_active())
        self.history.clear()

    def _setting_changed(self):
        if self.session:
            self.session.trace = self.trace.get_active()
            self.session.use_c64_names = self.names.get_active()
            self._changed()

    # ================================================================ listing
    def refresh(self, keep: int | None = None):
        s = self.session
        if not s:
            return
        if keep is None:
            keep = self.current_address()
        lines = s.lines()
        # analysed once per change; cursor moves and keys use these
        self._lines = {ln.addr: ln for ln in lines}
        self._xrefs: dict[int, list[int]] = {}
        for ln in lines:
            if ln.target is not None:
                self._xrefs.setdefault(ln.target, []).append(ln.addr)
        buf = self.view.get_buffer()
        buf.set_text("")
        self.line_addrs = []
        it = buf.get_end_iter()
        for ln in lines:
            if ln.label:
                buf.insert(it, " " * 16)
                buf.insert_with_tags(it, ln.label, self.t_label)
                buf.insert(it, "\n")
                self.line_addrs.append(ln.addr)
            hexbytes = " ".join(f"{x:02X}" for x in ln.raw[:3]) + ("…" if ln.size > 3 else "")
            buf.insert_with_tags(it, f"{ln.addr:04X}  {hexbytes:<10}", self.t_addr)
            buf.insert_with_tags(it, f"{'':8}{ln.text}", *( [self.t_data] if ln.kind == "data" else []))
            if ln.comment:
                buf.insert_with_tags(it, f"   ; {ln.comment}", self.t_comment)
            buf.insert(it, "\n")
            self.line_addrs.append(ln.addr)
        self._fill_labels()
        b = s.binary
        code = sum(ln.size for ln in lines if ln.kind == "code")
        self.status.set_text(f"{b.name}: ${b.start:04X}-${b.end - 1:04X}, {code} bytes of code, "
                             f"{len(b.data) - code} of data")
        if keep is not None:
            self.go_to(keep)

    def _fill_labels(self):
        while (row := self.labels.get_row_at_index(0)) is not None:
            self.labels.remove(row)
        names = getattr(self.session, "_names", {})
        for a, n in sorted(names.items()):
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=f"${a:04X}  {n}", xalign=0, css_classes=["monospace"], margin_start=6))
            row.addr = a
            self.labels.append(row)

    def current_address(self) -> int | None:
        if not self.line_addrs:
            return None
        buf = self.view.get_buffer()
        line = buf.get_iter_at_mark(buf.get_insert()).get_line()
        return self.line_addrs[min(line, len(self.line_addrs) - 1)]

    def selected_range(self) -> tuple[int, int] | None:
        buf = self.view.get_buffer()
        bounds = buf.get_selection_bounds()
        if not bounds or not self.line_addrs:
            return None
        a, b = bounds[0].get_line(), bounds[1].get_line()
        lo = self.line_addrs[min(a, len(self.line_addrs) - 1)]
        hi_line = min(b, len(self.line_addrs) - 1)
        hi_addr = self.line_addrs[hi_line]
        ln = self._lines.get(hi_addr)
        return lo, hi_addr + (ln.size - 1 if ln else 0)

    def go_to(self, addr: int, remember: bool = False):
        if not self.line_addrs:
            return
        cur = self.current_address()
        if remember and cur is not None and cur != addr:
            self.history.append(cur)
        # the last line at or before addr that isn't just a label line
        idx = 0
        for i, a in enumerate(self.line_addrs):
            if a <= addr:
                idx = i
            else:
                break
        buf = self.view.get_buffer()
        ok, it = buf.get_iter_at_line(idx)
        if ok:
            buf.place_cursor(it)
            mark = buf.create_mark(None, it, True)
            GLib.idle_add(lambda: (self.view.scroll_to_mark(mark, 0.1, True, 0, 0.3), False)[1])
        self.view.grab_focus()

    def _cursor_moved(self):
        a = self.current_address()
        if a is None or not self.session:
            return
        buf = self.view.get_buffer()
        buf.remove_tag(self.t_current, buf.get_start_iter(), buf.get_end_iter())
        it = buf.get_iter_at_mark(buf.get_insert())
        start = it.copy()
        start.set_line_offset(0)
        end = start.copy()
        end.forward_line()
        buf.apply_tag(self.t_current, start, end)
        names = getattr(self.session, "_names", {})
        self.here.set_markup(f"<b>${a:04X}</b>" + (f"  {GLib.markup_escape_text(names[a])}" if a in names else ""))
        while (row := self.refs.get_row_at_index(0)) is not None:
            self.refs.remove(row)
        for ref in self._xrefs.get(a, [])[:200]:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=f"${ref:04X}" + (f"  ({names[ref]})" if ref in names else ""), xalign=0,
                                    css_classes=["monospace"], margin_start=6))
            row.addr = ref
            self.refs.append(row)

    # ================================================================ editing
    def _key(self, _c, keyval, _code, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK) or not self.session:
            return False
        name = Gdk.keyval_name(keyval) or ""
        a = self.current_address()
        if a is None:
            return False
        if name in ("c", "C"):
            self.session.mark_code(a)
            self._changed(f"Code from ${a:04X}")
        elif name in ("d", "D"):
            lo, hi = self.selected_range() or (a, a + max(1, self._size_at(a)) - 1)
            self.session.mark_data(lo, hi)
            self._changed(f"${lo:04X}-${hi:04X} marked as data")
        elif name in ("n", "N"):
            self._ask("Label", f"Name for ${a:04X} (empty to remove)", self.session.labels.get(a, ""),
                      lambda text: self.session.set_label(a, text))
        elif name == "semicolon":
            self._ask("Comment", f"Comment for ${a:04X}", self.session.comments.get(a, ""),
                      lambda text: self.session.set_comment(a, text))
        elif name in ("Return", "KP_Enter"):
            ln = self._lines.get(a)
            if ln and ln.target is not None and self.session.in_range(ln.target):
                self.go_to(ln.target, remember=True)
            else:
                self.status.set_text("Nothing to follow here")
        elif name in ("Escape", "BackSpace"):
            if self.history:
                self.go_to(self.history.pop())
        elif name in ("g", "G"):
            self._ask("Go to", "Address or label", "", lambda text: self.go_to(
                parse_address(text, {n: x for x, n in getattr(self.session, "_names", {}).items()}), remember=True),
                      changes=False)
        else:
            return False
        return True

    def _size_at(self, a: int) -> int:
        ln = self._lines.get(a)
        return ln.size if ln else 1

    def _ask(self, heading: str, body: str, text: str, apply, changes: bool = True):
        dlg = Adw.AlertDialog(heading=heading, body=body)
        entry = Gtk.Entry(text=text, activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "OK")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def chosen(d, res):
            if d.choose_finish(res) != "ok":
                return
            try:
                apply(entry.get_text())
            except (SessionError, ValueError_) as e:
                self.status.set_text(str(e))
                return
            if changes:
                self._changed()
        dlg.choose(self.get_root(), None, chosen)

    def _changed(self, message: str = ""):
        self.refresh()
        if message:
            self.status.set_text(message)
        if self.file and self.session:
            try:
                sidecar_path(self.file).write_text(self.session.to_json())
            except OSError as e:
                self.status.set_text(f"Couldn't save the session: {e}")

    # ================================================================ output
    def source(self) -> str:
        return self.session.source(self.kickass) if self.session else ""

    def _copy(self, *_):
        Gdk.Display.get_default().get_clipboard().set(self.source())
        self.status.set_text("Source copied to the clipboard")

    def _insert(self, *_):
        where = self.insert_cb(self.source()) if (self.insert_cb and self.session) else None
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    def _export(self, *_):
        if not self.session:
            return
        dlg = Gtk.FileDialog(title="Export source")
        folder = self.project_dir or (self.file.parent if self.file else None)
        if folder:
            dlg.set_initial_folder(Gio.File.new_for_path(str(folder)))
        dlg.set_initial_name((self.file.stem if self.file else "disassembly") + ".asm")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_text(self.source())
            self.status.set_text(f"Saved {dest.name}")
        dlg.save(self.get_root(), None, done)

    def save(self):
        self.set_modified(False)
