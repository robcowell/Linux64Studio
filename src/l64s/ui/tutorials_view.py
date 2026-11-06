"""The Tutorials tab (Help → Tutorials): docs/tutorials shown beside your work, with their
pictures, and a button that opens a copy of each one's example project. l64s.mdview reads them."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from .. import mdview  # noqa: E402
from .editor import EditorPage  # noqa: E402

IMAGE_WIDTH = 720           # pictures are scaled down to this


class TutorialsView(EditorPage):
    kind = "tutorials"

    def __init__(self, open_example: Callable[[str], None], open_doc: Callable[[Path], None]):
        super().__init__(None)
        self.open_example, self.open_doc = open_example, open_doc
        self.current: Path | None = None
        self.example: str | None = None
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=230, vexpand=True,
                          shrink_start_child=False)
        self.list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.list.connect("row-selected", self._selected)
        for path in mdview.tutorials():
            title = mdview.title_of(path.read_text()) or path.stem
            if path.name == "README.md":
                title = "Start here"
            row = Gtk.ListBoxRow(child=Gtk.Label(label=title, xalign=0, wrap=True, margin_start=6,
                                                 margin_top=4, margin_bottom=4))
            row.path = path
            self.list.append(row)
        paned.set_start_child(Gtk.ScrolledWindow(child=self.list, hscrollbar_policy=Gtk.PolicyType.NEVER))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=6, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        self.heading = Gtk.Label(xalign=0, hexpand=True, css_classes=["dim-label"], ellipsize=Pango.EllipsizeMode.END)
        bar.append(self.heading)
        self.example_button = Gtk.Button(label="Open the Example Project", css_classes=["suggested-action"],
                                         tooltip_text="Open a copy of this tutorial's finished project (in "
                                                      "~/c64/tutorials), to compare with yours or run")
        self.example_button.connect("clicked", lambda *_: self.example and self.open_example(self.example))
        bar.append(self.example_button)
        right.append(bar)
        self.view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD,
                                 left_margin=24, right_margin=24, top_margin=12, bottom_margin=24,
                                 pixels_below_lines=4)
        click = Gtk.GestureClick()
        click.connect("released", self._clicked)
        self.view.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._hover)
        self.view.add_controller(motion)
        self.scroller = Gtk.ScrolledWindow(child=self.view, vexpand=True, hexpand=True)
        right.append(self.scroller)
        paned.set_end_child(right)
        self.append(paned)

        b = self.view.get_buffer()
        self.tags = {
            "h1": b.create_tag("h1", weight=Pango.Weight.BOLD, scale=1.7, pixels_below_lines=10),
            "h2": b.create_tag("h2", weight=Pango.Weight.BOLD, scale=1.3, pixels_above_lines=14,
                               pixels_below_lines=6),
            "h3": b.create_tag("h3", weight=Pango.Weight.BOLD, scale=1.1, pixels_above_lines=10),
            "bold": b.create_tag("bold", weight=Pango.Weight.BOLD),
            "italic": b.create_tag("italic", style=Pango.Style.ITALIC),
            "code": b.create_tag("code", family="Monospace", background="rgba(128,128,128,0.18)"),
            "block": b.create_tag("block", family="Monospace", paragraph_background="rgba(128,128,128,0.14)",
                                  left_margin=36, right_margin=24, pixels_above_lines=0, pixels_below_lines=0),
            "item": b.create_tag("item", left_margin=44, indent=-20),
            "image": b.create_tag("image", justification=Gtk.Justification.CENTER),
        }
        self._links: dict[Gtk.TextTag, str] = {}
        self._hand = Gdk.Cursor.new_from_name("pointer")
        first = self.list.get_row_at_index(0)
        if first is not None:
            self.list.select_row(first)

    @property
    def title(self) -> str:
        return "Tutorials"

    def save(self):
        pass

    # ------------------------------------------------------------------
    def _selected(self, _lb, row):
        if row is not None:
            self.show(row.path)

    def show_tutorial(self, path: Path):
        """Show a tutorial, choosing it in the list."""
        i = 0
        while (row := self.list.get_row_at_index(i)) is not None:
            if row.path == path:
                self.list.select_row(row)
                return
            i += 1
        self.show(path)

    def show(self, path: Path):
        self.current = path
        text = path.read_text()
        self.example = mdview.example_of(text)
        self.example_button.set_visible(self.example is not None and (mdview.EXAMPLES / self.example).is_dir())
        self.heading.set_text(f"Example project: examples/tutorials/{self.example}" if self.example else "")
        self._render(mdview.parse(text), path.parent)
        GLib.idle_add(lambda: (self.scroller.get_vadjustment().set_value(0), False)[1])

    def _render(self, blocks: list[mdview.Block], base: Path):
        b = self.view.get_buffer()
        b.set_text("")
        for tag in self._links:
            b.get_tag_table().remove(tag)
        self._links = {}
        end = b.get_end_iter
        for blk in blocks:
            if blk.kind == "heading":
                self._runs(blk.runs, [self.tags[f"h{min(blk.level, 3)}"]])
                b.insert(end(), "\n")
            elif blk.kind == "para":
                self._runs(blk.runs, [])
                b.insert(end(), "\n")
            elif blk.kind in ("bullet", "number"):
                start = b.create_mark(None, end(), True)
                b.insert(end(), "•  " if blk.kind == "bullet" else f"{blk.level}.  ")
                self._runs(blk.runs, [])
                b.insert(end(), "\n")
                b.apply_tag(self.tags["item"], b.get_iter_at_mark(start), end())
                b.delete_mark(start)
            elif blk.kind == "code":
                b.insert_with_tags(end(), blk.text + "\n", self.tags["block"])
                b.insert(end(), "\n")
            elif blk.kind == "image":
                path = (base / blk.url).resolve()
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file(str(path))
                    if pix.get_width() > IMAGE_WIDTH:
                        pix = pix.scale_simple(IMAGE_WIDTH, pix.get_height() * IMAGE_WIDTH // pix.get_width(),
                                               GdkPixbuf.InterpType.BILINEAR)
                    start = b.create_mark(None, end(), True)
                    b.insert_paintable(end(), Gdk.Texture.new_for_pixbuf(pix))
                    b.insert(end(), "\n")
                    if blk.text:
                        b.insert_with_tags(end(), blk.text + "\n", self.tags["italic"])
                    b.apply_tag(self.tags["image"], b.get_iter_at_mark(start), end())
                    b.delete_mark(start)
                except GLib.Error:
                    b.insert_with_tags(end(), f"[{blk.text}]\n", self.tags["italic"])

    def _runs(self, runs: list[mdview.Run], tags: list):
        b = self.view.get_buffer()
        for r in runs:
            extra = []
            if r.style in ("bold", "italic", "code"):
                extra = [self.tags[r.style]]
            elif r.style == "link":
                tag = b.create_tag(None, foreground="#3584e4", underline=Pango.Underline.SINGLE)
                self._links[tag] = r.url
                extra = [tag]
            b.insert_with_tags(b.get_end_iter(), r.text, *(tags + extra))

    def _link_at(self, x: float, y: float) -> str | None:
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, it = self.view.get_iter_at_location(bx, by)
        if not ok:
            return None
        return next((self._links[t] for t in it.get_tags() if t in self._links), None)

    def _hover(self, _c, x, y):
        self.view.set_cursor(self._hand if self._link_at(x, y) else None)

    def _clicked(self, _g, _n, x, y):
        url = self._link_at(x, y)
        if not url:
            return
        if url.startswith(("http://", "https://")):
            Gtk.UriLauncher.new(url).launch(self.get_root(), None, None)
            return
        target = ((self.current.parent if self.current else mdview.TUTORIALS) / url.split("#")[0]).resolve()
        if target.parent == mdview.TUTORIALS.resolve() and target.suffix == ".md":
            self.show_tutorial(target)
        elif target.exists():
            self.open_doc(target)
