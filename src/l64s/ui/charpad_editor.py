"""CharPad (.ctm) project editor: a Characters page and a Map page sharing one project."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..gfx.charpad import COLOUR_GLOBAL, COLOUR_PER_CHAR, COLOUR_PER_TILE, load_ctm, save_ctm  # noqa: E402
from .charset_editor import CharsetEditor  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .exports import ExportLinks  # noqa: E402
from .screen_editor import ScreenEditor  # noqa: E402

METHOD_NAMES = {COLOUR_GLOBAL: "global colour", COLOUR_PER_TILE: "colour per tile", COLOUR_PER_CHAR: "colour per character"}


class CharPadEditor(EditorPage):
    kind = "charpad"

    def __init__(self, path: Path, project=None):
        super().__init__(path)
        self.project = project
        self.ctm = load_ctm(path)
        p = self.ctm
        cs = p.charset

        bar = Gtk.Box(spacing=8, margin_top=6, margin_start=6, margin_end=6)
        self.append(bar)
        self.stack = Adw.ViewStack(vexpand=True)
        bar.append(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        info = f"{cs.count} characters · {METHOD_NAMES.get(p.colour_method, '?')}"
        info += " · multicolour" if cs.multicolour else " · hires"
        if p.tiles_enabled:
            info += f" · {p.tile_count} tiles of {p.tile_width}×{p.tile_height}"
        info += f" · map {p.map_width}×{p.map_height}"
        bar.append(Gtk.Label(label=info, css_classes=["dim-label"], hexpand=True, xalign=0, margin_start=12))
        kinds = [("charset", "Character set", path.stem + "Charset.bin", p.export_charset),
                 ("attribs", "Character colours / attributes", path.stem + "Colors.bin", p.export_attribs),
                 ("map", "Map (1 byte per cell)", path.stem + "Map.bin", p.export_map)]
        if p.tiles_enabled:
            kinds.append(("tiles", "Tile set", path.stem + "Tiles.bin", p.export_tiles))
        self.links = ExportLinks(path, kinds, project)
        bar.append(self.links)

        self.chars = CharsetEditor(None, data=cs, per_char_colour=p.colour_method == COLOUR_PER_CHAR)
        self.stack.add_titled_with_icon(self.chars, "chars", "Characters", "font-x-generic-symbolic")
        self.screens = p.to_screenset()
        if p.tiles_enabled:
            # Tile maps are shown with the colours worked out at load time (per tile or per char).
            cell_colour = None
        else:
            cell_colour = (lambda ch: p.cell_colour(ch))
        self.map = ScreenEditor(None, data=self.screens, charset=cs, cell_colour=cell_colour,
                                read_only=not p.map_editable)
        self.stack.add_titled_with_icon(self.map, "map", "Map", "video-display-symbolic")
        for child in (self.chars, self.map):
            child.connect("modified-changed", self._child_modified)
        # Character edits show up on the map when you switch to it.
        self.stack.connect("notify::visible-child", lambda *_: self.map.refresh())
        self.append(self.stack)

    def _child_modified(self, child):
        if child.modified:
            self.set_modified(True)

    def save(self):
        self.ctm.update_map_from(self.screens)
        save_ctm(self.ctm, self.path)
        for child in (self.chars, self.map):
            child.set_modified(False)
        self.set_modified(False)
        return self.links.write_all()
