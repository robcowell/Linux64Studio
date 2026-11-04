"""Linked exports: .bin files rewritten automatically whenever a graphics file is saved.

The book's workflow is edit in SpritePad/CharPad (or CBM prg Studio's editors), then export
.bin files that the code includes. A link is switched on by default only when the .bin is
currently in sync with the source, i.e. exporting now would produce exactly its bytes, so an
unrelated or out-of-date file is never overwritten without you asking. Choices are saved in
the project (`exports` in the .l64proj file).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

# (key, label, default file name, function returning the export bytes)
ExportKind = tuple[str, str, str, Callable[[], bytes]]


def _rel(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return str(path)


def detect_link(source: Path, default_name: str, data: bytes) -> Path | None:
    """The .bin this export currently matches: the default name, or any sibling with identical bytes."""
    default = source.parent / default_name
    try:
        if default.is_file() and default.read_bytes() == data:
            return default
    except OSError:
        pass
    if not data:
        return None
    for p in sorted(source.parent.glob("*.bin")):
        try:
            if p.stat().st_size == len(data) and p.read_bytes() == data:
                return p
        except OSError:
            continue
    return None


class ExportLinks(Gtk.MenuButton):
    """Header button + popover listing the files written on save."""

    def __init__(self, source: Path, kinds: list[ExportKind], project=None):
        super().__init__(icon_name="emblem-synchronizing-symbolic",
                         tooltip_text="Files updated automatically when you save")
        self.source = source
        self.kinds = kinds
        self.project = project
        self.targets: dict[str, Path | None] = {}
        saved = self._saved_config()
        for key, _label, default, fn in kinds:
            if saved is not None:
                rel = saved.get(key)
                self.targets[key] = (project.directory / rel).resolve() if rel else None
            else:
                try:
                    self.targets[key] = detect_link(source, default, fn())
                except Exception:  # a broken model shouldn't stop the editor opening
                    self.targets[key] = None
        self._build_popover()
        self._update_label()

    # ---------------------------------------------------------------- persistence
    def _key(self) -> str | None:
        if not self.project:
            return None
        return _rel(self.source.resolve(), self.project.directory)

    def _saved_config(self) -> dict | None:
        key = self._key()
        if key is None:
            return None
        return getattr(self.project, "exports", {}).get(key)

    def _persist(self):
        key = self._key()
        if key is None:
            return
        self.project.exports[key] = {k: (_rel(p, self.project.directory) if p else "")
                                     for k, p in self.targets.items()}
        try:
            self.project.save()
        except OSError:
            pass

    # ---------------------------------------------------------------- UI
    def _build_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8, margin_bottom=8,
                      margin_start=8, margin_end=8, width_request=360)
        box.append(Gtk.Label(label="<b>When saving, also write</b>", use_markup=True, xalign=0))
        self.rows = {}
        for key, label, default, _fn in self.kinds:
            row = Gtk.Box(spacing=6)
            check = Gtk.CheckButton(label=label, active=self.targets[key] is not None, hexpand=True)
            name = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.START, css_classes=["dim-label"],
                             max_width_chars=28)
            pick = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Choose file…")
            check.connect("toggled", self._toggled, key, default)
            pick.connect("clicked", self._choose, key, default)
            row.append(check)
            row.append(pick)
            box.append(row)
            box.append(name)
            self.rows[key] = (check, name)
        box.append(Gtk.Label(label="Links are switched on automatically only when the file\n"
                                   "already matches, so nothing unrelated gets overwritten.",
                             xalign=0, css_classes=["dim-label", "caption"]))
        self.set_popover(Gtk.Popover(child=box))
        self._refresh_rows()

    def _refresh_rows(self):
        for key, (check, name) in self.rows.items():
            p = self.targets.get(key)
            name.set_text(_rel(p, self.source.parent) if p else "(not written)")
            if check.get_active() != (p is not None):
                check.handler_block_by_func(self._toggled)
                check.set_active(p is not None)
                check.handler_unblock_by_func(self._toggled)

    def _update_label(self):
        n = sum(1 for p in self.targets.values() if p)
        self.set_tooltip_text(f"{n} file(s) updated when you save" if n else "No files updated on save")
        if n:
            self.add_css_class("accent")
        else:
            self.remove_css_class("accent")

    def _toggled(self, check, key, default):
        self.targets[key] = (self.source.parent / default) if check.get_active() else None
        self._changed()

    def _choose(self, _b, key, default):
        dlg = Gtk.FileDialog(title="Export to")
        current = self.targets.get(key)
        dlg.set_initial_folder(Gio.File.new_for_path(str((current or self.source).parent)))
        dlg.set_initial_name(current.name if current else default)

        def done(d, res):
            try:
                self.targets[key] = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            self._changed()
        dlg.save(self.get_root(), None, done)

    def _changed(self):
        self._refresh_rows()
        self._update_label()
        self._persist()

    # ---------------------------------------------------------------- writing
    def write_all(self) -> list[Path]:
        written = []
        for key, _label, _default, fn in self.kinds:
            p = self.targets.get(key)
            if p:
                p.write_bytes(fn())
                written.append(p)
        return written
