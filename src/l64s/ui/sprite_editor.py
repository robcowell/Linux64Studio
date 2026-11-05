"""Sprite editor: edits CBM prg Studio .spt sprite sets (or raw .bin), exports .bin / BYTE source."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..gfx.sprite import HEIGHT, Sprite, SpriteSet  # noqa: E402
from ..gfx.spritepad import load_spd, save_spd  # noqa: E402
from .editor import EditorPage  # noqa: E402
from .exports import ExportLinks  # noqa: E402
from .render import paint_scaled, render_sprite  # noqa: E402
from .widgets import ColourButton, PixelCanvas  # noqa: E402


class SpriteEditor(EditorPage):
    kind = "sprites"

    def __init__(self, path: Path | None, project=None):
        super().__init__(path)
        self.project = project
        if path and path.exists():
            if path.suffix.lower() == ".spd":
                self.data = load_spd(path)
            elif path.suffix.lower() == ".spt":
                self.data = SpriteSet.load_spt(path)
            else:
                self.data = SpriteSet.from_bin(path.read_bytes())
        else:
            self.data = SpriteSet()
        self.index = 0
        self.pen = 1
        self.undo: list[tuple[int, Sprite]] = []
        self.redo: list[tuple[int, Sprite]] = []
        self._anim_source = None
        self._anim_frame = 0
        from ..gfx.scratchpad import ScratchPad
        saved = self._pad_key() and self.project.sprite_pads.get(self._pad_key())
        self.scratch_pad = ScratchPad.from_dict(saved) if saved else ScratchPad()
        self._pad_window = None
        self._build()
        self._select(0)

    @property
    def sprite(self) -> Sprite:
        return self.data.sprites[self.index]

    # ---------------------------------------------------------------- UI
    def _build(self):
        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self.append(bar)
        for icon, tip, cb in [
            ("list-add-symbolic", "Add sprite", self._add),
            ("edit-copy-symbolic", "Duplicate sprite", self._duplicate),
            ("list-remove-symbolic", "Delete sprite", self._delete),
            (None, None, None),
            ("edit-undo-symbolic", "Undo (Ctrl+Z)", self.do_undo),
            ("edit-redo-symbolic", "Redo (Ctrl+Shift+Z)", self.do_redo),
            ("edit-clear-all-symbolic", "Clear sprite", lambda *_: self._modify(lambda s: s.clear())),
            ("object-flip-horizontal-symbolic", "Flip horizontally", lambda *_: self._modify(lambda s: s.flip_x())),
            ("object-flip-vertical-symbolic", "Flip vertically", lambda *_: self._modify(lambda s: s.flip_y())),
            ("go-previous-symbolic", "Shift left", lambda *_: self._modify(lambda s: s.shift(-1, 0))),
            ("go-next-symbolic", "Shift right", lambda *_: self._modify(lambda s: s.shift(1, 0))),
            ("go-up-symbolic", "Shift up", lambda *_: self._modify(lambda s: s.shift(0, -1))),
            ("go-down-symbolic", "Shift down", lambda *_: self._modify(lambda s: s.shift(0, 1))),
            (None, None, None),
            ("media-playlist-shuffle-symbolic", "Morph… (frames that turn this sprite into another)",
             lambda *_: self.open_morph()),
            ("weather-storm-symbolic", "Explosion Generator… (frames of an explosion)",
             lambda *_: self.open_explosion()),
            ("insert-image-symbolic", "Import from Image… (sprites cut from a .bmp, .png or .gif)",
             lambda *_: self.open_bmp_import()),
            ("insert-text-symbolic", "Import from Listing… (sprites from DATA or byte lines in a source)",
             lambda *_: self.open_listing_import()),
            ("drive-harddisk-symbolic", "Import from Memory or a File… (the last build, the running program, "
                                        "a .prg or .bin)",
             lambda *_: self.open_memory_import()),
            ("view-grid-symbolic", "Scratch Pad… (sprites side by side and in layers)",
             lambda *_: self.open_scratch_pad()),
        ]:
            if icon is None:
                bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
                continue
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", cb)
            bar.append(b)
        bar.append(Gtk.Box(hexpand=True))
        self.links = None
        if self.path and self.path.suffix.lower() in (".spt", ".spd"):
            kinds = [("bin", "Sprite data (.bin)", self.path.stem + ".bin", lambda: self.data.to_bin())]
            if getattr(self.project, "toolchain", "") == "cc65":     # a C project: the sprites as a C array too
                from ..syntax import identifier
                name = identifier(self.path.stem)
                kinds.append(("c", "Sprite data (C source, .c)", self.path.stem + ".c",
                              lambda: self.data.to_source(name, "c").encode()))
            self.links = ExportLinks(self.path, kinds, self.project)
            bar.append(self.links)
        exp = Gtk.MenuButton(label="Export", tooltip_text="Export sprite data")
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=6, margin_bottom=6,
                       margin_start=6, margin_end=6)
        b1 = Gtk.Button(label="Binary (.bin, 64 bytes per sprite)…")
        b1.add_css_class("flat")
        b1.connect("clicked", lambda *_: self._export("bin"))
        b2 = Gtk.Button(label="Source (.asm, .s for ca65, .c for C)…")
        b2.add_css_class("flat")
        b2.connect("clicked", lambda *_: self._export("asm"))
        menu.append(b1)
        menu.append(b2)
        pop = Gtk.Popover(child=menu)
        exp.set_popover(pop)
        bar.append(exp)

        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        self.append(body)

        # sprite list
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._row_selected)
        ls = Gtk.ScrolledWindow(min_content_width=150, child=self.listbox)
        body.set_start_child(ls)
        body.set_resize_start_child(False)

        centre = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_end_child(centre)
        self.canvas = PixelCanvas()
        self.canvas.connect("paint", self._paint)
        self.canvas.connect("stroke-begin", lambda *_: self._push_undo())
        self.canvas.connect("hover", self._hover)
        self.canvas.colour_at = self._colour_at
        frame = Gtk.Frame(child=self.canvas, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        centre.set_start_child(frame)
        centre.set_resize_end_child(False)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=8, margin_end=8,
                       margin_top=8, width_request=230)
        centre.set_end_child(Gtk.ScrolledWindow(child=side, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True))

        self.multi = Gtk.CheckButton(label="Multicolour")
        self.multi.connect("toggled", self._multi_toggled)
        side.append(self.multi)
        self.expx = Gtk.CheckButton(label="Expand X")
        self.expx.connect("toggled", lambda b: self._set_attr("expand_x", b.get_active()))
        self.expy = Gtk.CheckButton(label="Expand Y")
        self.expy.connect("toggled", lambda b: self._set_attr("expand_y", b.get_active()))
        row = Gtk.Box(spacing=8)
        row.append(self.expx)
        row.append(self.expy)
        side.append(row)

        side.append(Gtk.Label(label="<b>Pen</b> (left draw, right erase)", use_markup=True, xalign=0))
        grid = Gtk.Grid(row_spacing=4, column_spacing=6)
        self.pen_buttons = []
        self.colour_buttons = {}
        group = None
        specs = [(0, "Background", "background", True), (1, "Multicolour 1 ($D025)", "mcolour1", True),
                 (2, "Sprite colour", "colour", False), (3, "Multicolour 2 ($D026)", "mcolour2", True)]
        for r, (pen, label, attr, on_set) in enumerate(specs):
            rb = Gtk.CheckButton(label=label, group=group)
            group = group or rb
            rb.connect("toggled", self._pen_toggled, pen)
            cb = ColourButton(0, label)
            cb.connect("changed", self._colour_changed, attr, on_set)
            grid.attach(rb, 0, r, 1, 1)
            grid.attach(cb, 1, r, 1, 1)
            self.pen_buttons.append(rb)
            self.colour_buttons[attr] = cb
        side.append(grid)

        side.append(Gtk.Label(label="<b>Preview</b>", use_markup=True, xalign=0))
        self.preview = Gtk.DrawingArea(content_width=96, content_height=84)
        self.preview.set_draw_func(self._draw_preview)
        side.append(self.preview)
        anim = Gtk.Box(spacing=4)
        anim.append(Gtk.Label(label="Animate"))
        self.anim_from = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.anim_to = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.anim_play = Gtk.ToggleButton(icon_name="media-playback-start-symbolic", tooltip_text="Play animation")
        self.anim_play.connect("toggled", self._anim_toggled)
        anim.append(self.anim_from)
        anim.append(Gtk.Label(label="–"))
        anim.append(self.anim_to)
        anim.append(self.anim_play)
        side.append(anim)
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label"])
        side.append(self.status)

        self._refresh_list()
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    # ---------------------------------------------------------------- list
    def _refresh_list(self):
        while (row := self.listbox.get_row_at_index(0)) is not None:
            self.listbox.remove(row)
        for i, s in enumerate(self.data.sprites):
            box = Gtk.Box(spacing=8, margin_top=2, margin_bottom=2, margin_start=4)
            da = Gtk.DrawingArea(content_width=48, content_height=42)
            da.set_draw_func(self._draw_thumb, i)
            box.append(da)
            box.append(Gtk.Label(label=f"{i}  (${i:02X})"))
            self.listbox.append(box)
        self.anim_to.set_range(0, max(0, len(self.data.sprites) - 1))
        self.anim_from.set_range(0, max(0, len(self.data.sprites) - 1))
        if getattr(self, "_pad_window", None) is not None:
            self._pad_window.refresh()

    def _draw_thumb(self, _da, cr, w, h, i):
        if i >= len(self.data.sprites):
            return
        s = self.data.sprites[i]
        bm = render_sprite(s.rows, s.multi, s.colour, self.data.background, self.data.mcolour1, self.data.mcolour2)
        paint_scaled(cr, bm.surface(), 0, 0, w / 24, h / 21)

    def _row_selected(self, _lb, row):
        if row is not None and row.get_index() != self.index:
            self._select(row.get_index())

    def _select(self, i: int):
        self.index = max(0, min(i, len(self.data.sprites) - 1))
        row = self.listbox.get_row_at_index(self.index)
        if row and self.listbox.get_selected_row() is not row:
            self.listbox.select_row(row)
        s = self.sprite
        self._updating = True
        self.multi.set_active(s.multi)
        self.expx.set_active(s.expand_x)
        self.expy.set_active(s.expand_y)
        self.colour_buttons["background"].colour = self.data.background
        self.colour_buttons["mcolour1"].colour = self.data.mcolour1
        self.colour_buttons["mcolour2"].colour = self.data.mcolour2
        self.colour_buttons["colour"].colour = s.colour
        self._updating = False
        self._update_pens()
        self._redraw()

    def _update_pens(self):
        multi = self.sprite.multi
        self.pen_buttons[1].set_visible(multi)
        self.colour_buttons["mcolour1"].set_visible(multi)
        self.pen_buttons[3].set_visible(multi)
        self.colour_buttons["mcolour2"].set_visible(multi)
        if not multi and self.pen not in (0, 1):
            self.pen = 1
        self.canvas.cols = self.sprite.pixel_width
        self.canvas.rows = HEIGHT
        self.canvas.pixel_aspect = 2 if multi else 1
        # pen 1 in hires is the sprite colour (pen index 2 in the multicolour table)
        target = {0: 0, 1: 2}.get(self.pen, self.pen) if not multi else self.pen
        self.pen_buttons[target].set_active(True)

    # ---------------------------------------------------------------- drawing
    def _colour_at(self, x, y):
        s = self.sprite
        v = s.get(x, y)
        if s.multi:
            return (self.data.background, self.data.mcolour1, s.colour, self.data.mcolour2)[v]
        return s.colour if v else self.data.background

    def _paint(self, _c, x, y, button):
        value = 0 if button == 3 else self.pen
        self.sprite.set(x, y, value)
        self._changed()

    def _hover(self, _c, x, y):
        self.status.set_text(f"Sprite {self.index}  x {x}  y {y}")

    def _pen_toggled(self, btn, pen):
        if btn.get_active():
            # In hires mode the sprite-colour row means bit value 1.
            self.pen = (1 if pen == 2 else 0) if not self.sprite.multi else pen

    def _colour_changed(self, _b, colour, attr, on_set):
        if getattr(self, "_updating", False):
            return
        if on_set:
            setattr(self.data, attr, colour)
        else:
            self.sprite.colour = colour
        self._changed(thumbs=True)

    def _set_attr(self, attr, value):
        if getattr(self, "_updating", False):
            return
        setattr(self.sprite, attr, value)
        self._changed()

    def _multi_toggled(self, btn):
        if getattr(self, "_updating", False):
            return
        multi = btn.get_active()
        # Keep the pen meaning "sprite colour" when switching modes (bit value 1 in hires, 2 in multicolour).
        if multi:
            self.pen = {1: 2}.get(self.pen, self.pen)
        else:
            self.pen = 1 if self.pen else 0
        self.sprite.multi = multi
        self._update_pens()
        self._changed(thumbs=True)

    def _changed(self, thumbs=True):
        self.set_modified(True)
        self._redraw()

    def _redraw(self):
        self.canvas.queue_draw()
        self.preview.queue_draw()
        if self._pad_window is not None:
            self._pad_window.area.queue_draw()
            child = self._pad_window.palette.get_child_at_index(self.index)
            if child:
                child.get_child().queue_draw()
        row = self.listbox.get_row_at_index(self.index)
        if row:
            box = row.get_child()
            box.get_first_child().queue_draw()

    def _draw_preview(self, _da, cr, w, h):
        idx = self._anim_frame if self._anim_source else self.index
        idx = min(idx, len(self.data.sprites) - 1)
        s = self.data.sprites[idx]
        bm = render_sprite(s.rows, s.multi, s.colour, self.data.background, self.data.mcolour1, self.data.mcolour2)
        sx = (4 if s.expand_x else 2)
        sy = (4 if s.expand_y else 2)
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.paint()
        paint_scaled(cr, bm.surface(), 0, 0, sx, sy)

    def _anim_toggled(self, btn):
        if btn.get_active():
            self._anim_frame = int(self.anim_from.get_value())
            self._anim_source = GLib.timeout_add(120, self._anim_tick)
        elif self._anim_source:
            GLib.source_remove(self._anim_source)
            self._anim_source = None
            self.preview.queue_draw()

    def _anim_tick(self):
        a, b = int(self.anim_from.get_value()), int(self.anim_to.get_value())
        if b < a:
            a, b = b, a
        self._anim_frame = a if self._anim_frame >= b else self._anim_frame + 1
        self.preview.queue_draw()
        return True

    # ---------------------------------------------------------------- edit ops
    def _push_undo(self):
        self.undo.append((self.index, self.sprite.copy()))
        del self.undo[:-100]
        self.redo.clear()

    def _modify(self, fn):
        self._push_undo()
        fn(self.sprite)
        self._changed()

    def do_undo(self, *_):
        if self.undo:
            i, s = self.undo.pop()
            if i < len(self.data.sprites):
                self.redo.append((i, self.data.sprites[i].copy()))
                self.data.sprites[i] = s
                self._select(i)
                self.set_modified(True)

    def do_redo(self, *_):
        if self.redo:
            i, s = self.redo.pop()
            if i < len(self.data.sprites):
                self.undo.append((i, self.data.sprites[i].copy()))
                self.data.sprites[i] = s
                self._select(i)
                self.set_modified(True)

    def open_morph(self):
        from .morph_dialog import MorphDialog
        if len(self.data.sprites) < 2:
            self._add()                 # a second sprite to morph into
        dlg = MorphDialog(self.get_root(), self.data, self.index, self._insert_frames)
        dlg.present()
        return dlg

    def open_explosion(self):
        from .explosion_dialog import ExplosionDialog
        folder = self.project.directory if self.project else (self.path.parent if self.path else None)
        dlg = ExplosionDialog(self.get_root(), self.data, self.index, self._insert_explosion, folder)
        dlg.present()
        return dlg

    def open_bmp_import(self, path: Path | None = None):
        from .bmp_import_dialog import BmpImportDialog
        folder = self.project.directory if self.project else (self.path.parent if self.path else None)
        dlg = BmpImportDialog(self.get_root(), self.data, self.index, self._insert_imported, folder,
                              multi=self.sprite.multi)
        dlg.present()
        if path:
            dlg.load(path)
        return dlg

    def open_memory_import(self, path=None):
        """Import → From Memory (and From File): the last build's memory, the running program's, a file."""
        from .listing_import_dialog import char_drawer, sprite_drawer  # noqa: F401
        from .memory_import_dialog import MemoryImportDialog
        win = self.get_root()
        get_build = getattr(win, "_memory_of_last_build", lambda: (None, {}, ""))
        folder = self.project.directory if self.project else (self.path.parent if self.path else None)
        dlg = MemoryImportDialog(win, "sprites", get_build, lambda: getattr(win, "debug", None), self.index, 256,
                                 sprite_drawer(self.data, self.sprite.multi, self.sprite.colour), self._import_listing_sprites, folder)
        dlg.present()
        if path:
            dlg.load_file(path)
        return dlg

    def open_listing_import(self):
        """Import → From Listing: sprites out of the DATA or byte lines of a source file."""
        from .editor import SourceEditor
        from .listing_import_dialog import ListingImportDialog, sprite_drawer
        win = self.get_root()
        eds = [e for e in (win.editors() if hasattr(win, "editors") else []) if isinstance(e, SourceEditor)]
        last = getattr(win, "_last_source", None)
        eds.sort(key=lambda e: e is not last)
        sources = [(e.title, e.get_text(), e.is_basic) for e in eds]
        folder = self.project.directory if self.project else (self.path.parent if self.path else None)
        dlg = ListingImportDialog(win, "sprites", sources, self.index, 256,
                                  sprite_drawer(self.data, self.sprite.multi, self.sprite.colour),
                                  self._import_listing_sprites, folder)
        dlg.present()
        return dlg

    def _import_listing_sprites(self, items, at: int):
        """Store the sprites from `at`, over those there (and on past the end), in the current
        sprite's mode and colour."""
        base = self.sprite
        new = [Sprite.from_bytes(d, multi=base.multi, colour=base.colour) for d in items]
        at = min(at, len(self.data.sprites))
        self.data.sprites[at:at + len(new)] = new       # over those there, then on past the end
        self.undo.clear()
        self.redo.clear()
        self._refresh_list()
        self._select(at)
        self.set_modified(True)

    def _insert_imported(self, sprites, place: str, colours):
        """Sprites from an image: after the current one, at the end, or over the current one and
        those after it. `colours` (sprite colour, MC1, MC2) or None to keep the editor's."""
        if colours:
            colour, self.data.mcolour1, self.data.mcolour2 = colours
        else:
            colour = self.sprite.colour
        for s in sprites:
            s.colour = colour
        if place == "replace":
            at = self.index
            self.data.sprites[at:at + len(sprites)] = sprites
            self.undo.clear()
            self.redo.clear()
            self._refresh_list()
            self._select(at)
            self.set_modified(True)
            return
        self._insert_frames(sprites, self.index + 1 if place == "after" else len(self.data.sprites))

    def _insert_explosion(self, frames, at: int, multicolours):
        if multicolours:
            self.data.mcolour1, self.data.mcolour2 = multicolours
        self._insert_frames(frames, at)

    # ---------------------------------------------------------------- scratch pad
    def _pad_key(self) -> str | None:
        if not (self.project and self.path):
            return None
        import os
        try:
            return os.path.relpath(self.path.resolve(), self.project.directory)
        except ValueError:
            return None

    def scratch_pad_changed(self):
        """The pad is saved with the sprites (into the project), so it and they stay in step."""
        self.set_modified(True)

    def _save_scratch_pad(self):
        key = self._pad_key()
        if key is None:
            return
        if self.scratch_pad.cells or key in self.project.sprite_pads:
            self.project.sprite_pads[key] = self.scratch_pad.to_dict()
            try:
                self.project.save()
            except OSError:
                pass

    def open_scratch_pad(self):
        from .sprite_scratchpad import SpriteScratchPad
        if self._pad_window is None:
            self._pad_window = SpriteScratchPad(self.get_root(), self)
            self._pad_window.connect("close-request", lambda *_: (setattr(self, "_pad_window", None), False)[1])
        self._pad_window.present()
        return self._pad_window

    def _sprites_moved(self, inserted_at: int | None = None, count: int = 1, removed: int | None = None):
        if inserted_at is not None:
            self.scratch_pad.sprites_inserted(inserted_at, count)
        if removed is not None:
            self.scratch_pad.sprite_removed(removed)

    def _insert_frames(self, frames, at: int):
        self._sprites_moved(inserted_at=at, count=len(frames))
        for k, f in enumerate(frames):
            self.data.sprites.insert(at + k, f)
        self.undo.clear()               # undo works per sprite, and the sprites have moved
        self.redo.clear()
        self._refresh_list()
        self._select(at)
        self.set_modified(True)

    def _add(self, *_):
        self._sprites_moved(inserted_at=self.index + 1)
        self.data.sprites.insert(self.index + 1, Sprite(multi=self.sprite.multi, colour=self.sprite.colour))
        self._refresh_list()
        self._select(self.index + 1)
        self.set_modified(True)

    def _duplicate(self, *_):
        self._sprites_moved(inserted_at=self.index + 1)
        self.data.sprites.insert(self.index + 1, self.sprite.copy())
        self._refresh_list()
        self._select(self.index + 1)
        self.set_modified(True)

    def _delete(self, *_):
        if len(self.data.sprites) > 1:
            del self.data.sprites[self.index]
            self._sprites_moved(removed=self.index)
            self.undo.clear()
            self.redo.clear()
            self._refresh_list()
            self._select(min(self.index, len(self.data.sprites) - 1))
            self.set_modified(True)

    def _key(self, _c, keyval, _code, state):
        from gi.repository import Gdk
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            (self.do_redo if state & Gdk.ModifierType.SHIFT_MASK else self.do_undo)()
            return True
        if keyval == Gdk.KEY_Page_Down:
            self._select(self.index + 1)
            return True
        if keyval == Gdk.KEY_Page_Up:
            self._select(self.index - 1)
            return True
        return False

    # ---------------------------------------------------------------- save/export
    def save(self):
        if not self.path:
            raise ValueError("No file name")
        sfx = self.path.suffix.lower()
        if sfx == ".spt":
            self.data.save_spt(self.path)
        elif sfx == ".spd":
            save_spd(self.data, self.path)
        else:
            self.path.write_bytes(self.data.to_bin())
        self._save_scratch_pad()
        self.set_modified(False)
        return self.links.write_all() if self.links else []

    def _export(self, fmt: str):
        dlg = Gtk.FileDialog(title="Export sprites")
        c_project = getattr(self.project, "toolchain", "") == "cc65"
        ext = ".bin" if fmt == "bin" else ".c" if c_project else ".asm"
        base = self.path.with_suffix(ext).name if self.path else f"sprites{ext}"
        dlg.set_initial_name(base)
        if self.path:
            from gi.repository import Gio
            dlg.set_initial_folder(Gio.File.new_for_path(str(self.path.parent)))

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            p = Path(f.get_path())
            if fmt == "bin":
                p.write_bytes(self.data.to_bin())
            else:                       # the syntax the file name says (.c, .s, or the project's .asm)
                from ..syntax import KICK, for_file, identifier
                kick = getattr(self.project, "toolchain", "") == "kickass"
                p.write_text(self.data.to_source(identifier(p.stem), for_file(p, KICK if kick else "cbm")))
        dlg.save(self.get_root(), None, done)
