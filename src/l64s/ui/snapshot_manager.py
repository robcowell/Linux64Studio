"""Snapshot Manager: save the whole machine at any moment of a debug session, restore it later,
and compare two snapshots."""
from __future__ import annotations

import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import memmap  # noqa: E402
from ..emu.binmon import MonitorError  # noqa: E402
from ..emu.values import flags_text  # noqa: E402
from ..snapshot import (Info, SnapshotError, compare, delete_snapshot, list_snapshots, program_stamp,  # noqa: E402
                        read_vsf, rename_snapshot, unique_path)
from .editor import EditorPage  # noqa: E402


class SnapshotManager(EditorPage):
    kind = "snapshots"

    def __init__(self, folder: Path, get_session, get_build, current_prg, restore_cold, show_memory):
        super().__init__(None)
        self.folder = folder
        self.get_session = get_session      # () -> DebugSession or None
        self.get_build = get_build          # () -> (MemoryMap, symbols, desc)
        self.current_prg = current_prg      # () -> Path of the last built program, or None
        self.restore_cold = restore_cold    # (vsf) -> start debugging, then load it
        self.show_memory = show_memory      # (address) -> open the Memory Viewer there

        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        self.append(bar)
        self.name = Gtk.Entry(placeholder_text="name, e.g. before the boss", hexpand=True)
        self.name.connect("activate", self._take)
        bar.append(self.name)
        take = Gtk.Button(label="Take Snapshot", css_classes=["suggested-action"],
                          tooltip_text="Save the whole machine now (during a debug session)")
        take.connect("clicked", self._take)
        bar.append(take)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh the list")
        refresh.connect("clicked", lambda *_: self.refresh())
        bar.append(refresh)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True, position=380,
                          shrink_start_child=False, shrink_end_child=False)
        self.append(paned)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.MULTIPLE, css_classes=["navigation-sidebar"])
        self.list.connect("selected-rows-changed", lambda *_: self._selection_changed())
        # Double-click (or Enter) loads a snapshot straight away, as CBM prg Studio's State Manager does.
        self.list.connect("row-activated", lambda _l, row: self._restore(row.vsf))
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.append(Gtk.ScrolledWindow(child=self.list, vexpand=True))
        left.append(Gtk.Label(label="Double-click a snapshot to load it. Select two (Ctrl+click) to compare them.",
                              wrap=True,
                              xalign=0, css_classes=["dim-label", "caption"], margin_start=8, margin_bottom=4))
        paned.set_start_child(left)

        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_end=8,
                              margin_top=4)
        paned.set_end_child(Gtk.ScrolledWindow(child=self.detail, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label", "caption"], margin_start=8,
                                margin_bottom=6)
        self.append(self.status)
        self.refresh()

    @property
    def title(self) -> str:
        return "Snapshots"

    # ---------------------------------------------------------------- list
    def refresh(self, select: Path | None = None):
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        for vsf, info in list_snapshots(self.folder):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=4, margin_bottom=4, margin_start=6)
            box.append(Gtk.Label(label=info.name, xalign=0, css_classes=["heading"], ellipsize=3))
            when = time.strftime("%d %b %H:%M:%S", time.localtime(info.created))
            pc = f"  ·  PC ${info.pc:04X}" if info.pc is not None else ""
            box.append(Gtk.Label(label=f"{when}{pc}", xalign=0, css_classes=["dim-label", "caption"]))
            if info.note:
                box.append(Gtk.Label(label=info.note, xalign=0, ellipsize=3, css_classes=["caption"]))
            row = Gtk.ListBoxRow(child=box)
            row.vsf = vsf
            self.list.append(row)
            if select and vsf == select:
                self.list.select_row(row)
        if self.list.get_row_at_index(0) is None:
            self._show_text("No snapshots yet. Start debugging (Shift+F5), then Take Snapshot.")

    def _selected(self) -> list[Path]:
        return [r.vsf for r in self.list.get_selected_rows()]

    def _selection_changed(self):
        sel = self._selected()
        if len(sel) == 1:
            self._show_one(sel[0])
        elif len(sel) == 2:
            self._show_compare(*sorted(sel, key=lambda p: Info.load(p).created))
        elif not sel:
            self._show_text("")
        else:
            self._show_text("Select one or two snapshots.")

    def _clear(self):
        while (c := self.detail.get_first_child()) is not None:
            self.detail.remove(c)

    def _show_text(self, text: str):
        self._clear()
        self.detail.append(Gtk.Label(label=text, wrap=True, xalign=0, css_classes=["dim-label"]))

    # ---------------------------------------------------------------- one snapshot
    def _show_one(self, vsf: Path):
        self._clear()
        info = Info.load(vsf)
        try:
            snap = read_vsf(vsf)
        except (SnapshotError, OSError) as e:
            self._show_text(f"Can't read {vsf.name}: {e}")
            return
        r = snap.registers
        self.detail.append(Gtk.Label(label=f"<b>{GLib.markup_escape_text(info.name)}</b>", use_markup=True, xalign=0))
        self.detail.append(Gtk.Label(
            label=f"PC ${r['PC']:04X}  A ${r['A']:02X}  X ${r['X']:02X}  Y ${r['Y']:02X}  SP ${r['SP']:02X}  "
                  f"{flags_text(r['FL'])}", xalign=0, selectable=True, css_classes=["monospace"]))
        _m, syms, _d = self.get_build()
        where = syms.get(r["PC"])
        prg = Path(info.program).name if info.program else "unknown program"
        self.detail.append(Gtk.Label(label=f"{prg}{f', at {where}' if where else ''} · {snap.machine}, "
                                           f"VICE {snap.vice_version} · {vsf.stat().st_size // 1024}K", xalign=0,
                                     wrap=True, css_classes=["dim-label"]))
        cur = self.current_prg()
        if info.program_stamp and cur and program_stamp(cur) != info.program_stamp:
            self.detail.append(Gtk.Label(label="⚠ Taken with an earlier build: the program has been rebuilt since, "
                                               "so source lines may not match the restored code.",
                                         wrap=True, xalign=0, css_classes=["warning"]))
        note = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD, top_margin=6, left_margin=6, css_classes=["card"])
        note.set_size_request(-1, 70)
        note.get_buffer().set_text(info.note)
        self.detail.append(Gtk.Label(label="Note", xalign=0, css_classes=["heading"]))
        self.detail.append(note)
        btns = Gtk.Box(spacing=6)
        for label, cb, cls in (("Restore", lambda *_: self._restore(vsf), "suggested-action"),
                               ("Save Note", lambda *_: self._save_note(vsf, note), ""),
                               ("Rename…", lambda *_: self._rename(vsf), ""),
                               ("Delete…", lambda *_: self._delete(vsf), "destructive-action")):
            b = Gtk.Button(label=label, css_classes=[cls] if cls else [])
            b.connect("clicked", cb)
            btns.append(b)
        self.detail.append(btns)

    def _save_note(self, vsf: Path, view: Gtk.TextView):
        info = Info.load(vsf)
        buf = view.get_buffer()
        info.note = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        info.save(vsf)
        self.refresh(select=vsf)
        self.status.set_text("Note saved")

    # ---------------------------------------------------------------- compare
    def _show_compare(self, a: Path, b: Path):
        self._clear()
        try:
            sa, sb = read_vsf(a), read_vsf(b)
        except (SnapshotError, OSError) as e:
            self._show_text(str(e))
            return
        d = compare(sa, sb)
        ia, ib = Info.load(a), Info.load(b)
        self.detail.append(Gtk.Label(label=f"<b>{GLib.markup_escape_text(ia.name)}</b> → "
                                           f"<b>{GLib.markup_escape_text(ib.name)}</b>",
                                     use_markup=True, xalign=0, wrap=True))
        cycles = f"{d.clock_delta:,} cycles later ({d.clock_delta / 985248:.2f} s on a PAL C64)" if d.clock_delta >= 0 \
            else f"{-d.clock_delta:,} cycles earlier"
        self.detail.append(Gtk.Label(label=cycles, xalign=0, css_classes=["dim-label"]))
        regs = ", ".join(f"{k} ${x:0{4 if k == 'PC' else 2}X}→${y:0{4 if k == 'PC' else 2}X}"
                         for k, (x, y) in d.registers.items()) or "none"
        self.detail.append(Gtk.Label(label=f"Registers changed: {regs}", xalign=0, wrap=True, css_classes=["monospace"]))
        self.detail.append(Gtk.Label(label=f"{d.changed_bytes} bytes changed in {len(d.ranges)} range(s). "
                                           f"Double-click a range to see it in the Memory Viewer.",
                                     xalign=0, wrap=True))
        m, syms, _desc = self.get_build()
        lb = Gtk.ListBox(css_classes=["boxed-list"])
        for lo, hi in d.ranges[:500]:
            owner = m.owner_of(lo) if m else None
            label = syms.get(lo, "")
            before = sa.ram[lo:min(hi + 1, lo + 8)].hex(" ").upper()
            after = sb.ram[lo:min(hi + 1, lo + 8)].hex(" ").upper()
            more = "…" if hi - lo >= 8 else ""
            text = (f"${lo:04X}-${hi:04X} ({hi - lo + 1})  {memmap.system_region(lo)}"
                    + (f" · {owner.owner}" if owner else "") + (f" · {label}" if label else "")
                    + f"\n    {before}{more}  →  {after}{more}")
            row = Gtk.ListBoxRow(child=Gtk.Label(label=text, xalign=0, css_classes=["monospace"], margin_start=6,
                                                 margin_top=2, margin_bottom=2))
            row.addr = lo
            lb.append(row)
        lb.connect("row-activated", lambda _l, row: self.show_memory(row.addr))
        self.detail.append(lb)

    # ---------------------------------------------------------------- actions
    def _take(self, *_):
        s = self.get_session()
        if not s or not s.monitor.connected:
            self.status.set_text("Start debugging (Shift+F5) to take a snapshot")
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        name = self.name.get_text().strip() or time.strftime("Snapshot %H.%M.%S")
        vsf = unique_path(self.folder, name)
        try:
            pc = s.save_snapshot(vsf)
        except (MonitorError, OSError) as e:
            self.status.set_text(f"Couldn't save the snapshot: {e}")
            return
        prg = self.current_prg()
        Info(name=name, pc=pc, program=str(prg) if prg else "", program_stamp=program_stamp(prg)).save(vsf)
        self.name.set_text("")
        self.refresh(select=vsf)
        self.status.set_text(f"Saved '{name}' at PC ${pc:04X}" + (" (the program kept running)" if s.running else ""))

    def _restore(self, vsf: Path):
        s = self.get_session()
        if s and s.monitor.connected:
            try:
                pc = s.restore_snapshot(vsf)
            except (MonitorError, OSError) as e:
                self.status.set_text(f"Couldn't restore: {e}")
                return
            self.status.set_text(f"Restored '{Info.load(vsf).name}': stopped at PC ${pc:04X}")
        else:
            self.status.set_text("Starting a debug session to restore into…")
            self.restore_cold(vsf)

    def _rename(self, vsf: Path):
        dlg = Adw.AlertDialog(heading="Rename snapshot")
        entry = Gtk.Entry(text=Info.load(vsf).name, activates_default=True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("ok", "Rename")
        dlg.set_default_response("ok")

        def chosen(d, res):
            if d.choose_finish(res) == "ok" and entry.get_text().strip():
                self.refresh(select=rename_snapshot(vsf, entry.get_text()))
        dlg.choose(self.get_root(), None, chosen)

    def _delete(self, vsf: Path):
        dlg = Adw.AlertDialog(heading=f"Delete '{Info.load(vsf).name}'?", body="The snapshot file is removed for good.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("delete", "Delete")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def chosen(d, res):
            if d.choose_finish(res) == "delete":
                delete_snapshot(vsf)
                self.refresh()
                self.status.set_text("Deleted")
        dlg.choose(self.get_root(), None, chosen)

    def save(self):
        self.set_modified(False)
