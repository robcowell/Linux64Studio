"""Import CharPad binaries: make a .ctm project from a game's CharPad exports (characters,
attributes, tiles, map), with its linked exports set to write those same files back, so the
data can be edited in Linux64Studio without changing the game's code."""
from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..gfx.charpad import CharPadError, from_binaries, save_ctm  # noqa: E402

PARTS = [("charset", "Characters (8 bytes each)", ("char", "font")),
         ("attribs", "Attributes (colour + material)", ("attrib", "colour", "color", "material")),
         ("tiles", "Tiles (8-bit, row by row)", ("tile",)),
         ("map", "Map (8-bit, row by row)", ("map",))]


def guess_files(folder: Path) -> dict[str, Path]:
    """The likely file for each part, by name."""
    out: dict[str, Path] = {}
    bins = sorted(folder.glob("*.bin"))
    for key, _label, words in PARTS:
        for b in bins:
            if any(w in b.stem.lower() for w in words) and b not in out.values():
                out[key] = b
                break
    return out


class CharPadImportDialog(Adw.Window):
    def __init__(self, parent, project, on_done, folder: Path | None = None):
        super().__init__(transient_for=parent, modal=True, title="Import CharPad Binaries", default_width=620)
        self.project = project
        self.on_done = on_done            # (Path of the new .ctm) -> None
        base = folder or (project.directory if project else Path.home())
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        page = Adw.PreferencesPage()
        tv.set_content(page)
        g = Adw.PreferencesGroup(title="Files", description="CharPad's binary exports, as a game loads them. "
                                                            "The new project writes them back when you save it.")
        page.add(g)
        guesses = guess_files(base)
        if not guesses and project:
            for sub in sorted({p.parent for p in project.all_files() if p.suffix.lower() == ".bin"}):
                guesses = guess_files(sub)
                if len(guesses) == 4:
                    break
        self.rows: dict[str, Adw.EntryRow] = {}
        for key, label, _w in PARTS:
            row = Adw.EntryRow(title=label, text=self._rel(guesses[key]) if key in guesses else "")
            pick = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
            pick.connect("clicked", lambda _b, r=row: self._choose(r))
            row.add_suffix(pick)
            row.connect("changed", lambda *_: self._update())
            g.add(row)
            self.rows[key] = row
        lg = Adw.PreferencesGroup(title="Layout")
        page.add(lg)
        self.tile_w = Adw.SpinRow.new_with_range(1, 10, 1)
        self.tile_w.set_title("Tile width (characters)")
        self.tile_w.set_value(2)
        self.tile_h = Adw.SpinRow.new_with_range(1, 10, 1)
        self.tile_h.set_title("Tile height (characters)")
        self.tile_h.set_value(2)
        self.map_w = Adw.SpinRow.new_with_range(1, 4096, 1)
        self.map_w.set_title("Map width (tiles)")
        self.map_w.set_value(40)
        self.multi = Adw.SwitchRow(title="Multicolour characters")
        for w in (self.tile_w, self.tile_h, self.map_w):
            w.connect("notify::value", lambda *_: self._update())
            lg.add(w)
        lg.add(self.multi)
        og = Adw.PreferencesGroup(title="New project")
        page.add(og)
        first = next(iter(guesses.values()), None)
        default = (first.parent if first else base) / "rooms.ctm"
        self.dest = Adw.EntryRow(title="CharPad project (.ctm)", text=self._rel(default))
        self.dest.connect("changed", lambda *_: self._update())
        og.add(self.dest)
        self.info = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"], margin_top=8)
        og.add(self.info)
        self.ok = Gtk.Button(label="Import", css_classes=["suggested-action"])
        self.ok.connect("clicked", lambda *_: self._import())
        hb.pack_end(self.ok)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        hb.pack_start(cancel)
        self._update()

    # ---------------------------------------------------------------- paths
    def _base(self) -> Path:
        return self.project.directory if self.project else Path.home()

    def _rel(self, p: Path) -> str:
        try:
            return os.path.relpath(p, self._base())
        except ValueError:
            return str(p)

    def _path(self, text: str) -> Path:
        p = Path(text.strip()).expanduser()
        return p if p.is_absolute() else self._base() / p

    def _choose(self, row: Adw.EntryRow):
        dlg = Gtk.FileDialog(title="Choose the file")
        dlg.set_initial_folder(Gio.File.new_for_path(str(self._path(row.get_text() or ".").parent
                                                         if row.get_text() else self._base())))

        def done(d, res):
            try:
                row.set_text(self._rel(Path(d.open_finish(res).get_path())))
            except GLib.Error:
                pass
        dlg.open(self, None, done)

    # ---------------------------------------------------------------- import
    def _project(self):
        data = {}
        for key, _label, _w in PARTS:
            text = self.rows[key].get_text().strip()
            if not text:
                raise CharPadError("Choose all four files")
            p = self._path(text)
            try:
                data[key] = p.read_bytes()
            except OSError as e:
                raise CharPadError(f"Can't read {p.name}: {e.strerror}") from None
        return from_binaries(data["charset"], data["attribs"], data["tiles"], data["map"],
                             int(self.map_w.get_value()), int(self.tile_w.get_value()),
                             int(self.tile_h.get_value()), multicolour=self.multi.get_active())

    def _update(self):
        try:
            p = self._project()
        except CharPadError as e:
            self.info.set_text(str(e))
            self.ok.set_sensitive(False)
            return
        dest = self._path(self.dest.get_text() or "rooms.ctm")
        warn = f"  {dest.name} exists and will be replaced." if dest.exists() else ""
        self.info.set_text(f"{p.charset.count} characters, {p.tile_count} tiles of {p.tile_width}×{p.tile_height}, "
                           f"a map of {p.map_width}×{p.map_height} tiles.{warn}")
        self.ok.set_sensitive(dest.suffix.lower() == ".ctm")

    def _import(self):
        try:
            p = self._project()
        except CharPadError as e:
            self.info.set_text(str(e))
            return
        dest = self._path(self.dest.get_text())
        dest.parent.mkdir(parents=True, exist_ok=True)
        save_ctm(p, dest)
        if self.project:
            # link the exports to the files they came from, so saving writes them back
            self.project.exports[self._rel(dest.resolve())] = {
                key: self._rel(self._path(self.rows[key].get_text()).resolve()) for key, _l, _w in PARTS}
            try:
                self.project.save()
            except OSError:
                pass
        self.close()
        self.on_done(dest)
