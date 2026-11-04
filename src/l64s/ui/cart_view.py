"""Cartridge (.crt) page: what's in the file, and a button to run it in VICE."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, GObject, Gtk  # noqa: E402

from ..cart.crt import load_crt  # noqa: E402
from .editor import EditorPage  # noqa: E402

CHIP_TYPES = {0: "ROM", 1: "RAM", 2: "Flash"}


class CartView(EditorPage):
    kind = "cart"

    __gsignals__ = {"run-cart": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, path: Path):
        super().__init__(path)
        self.cart = load_crt(path)
        c = self.cart
        bar = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        title = Gtk.Label(label=f"<b>{GLib.markup_escape_text(c.name or path.stem)}</b>", use_markup=True, xalign=0)
        bar.append(title)
        bar.append(Gtk.Label(label=f"{c.type_name} · {c.mode} (EXROM {c.exrom}, GAME {c.game}) · "
                                   f"{len({ch.bank for ch in c.chips})} bank(s) · {c.size // 1024}K",
                             css_classes=["dim-label"], hexpand=True, xalign=0))
        run = Gtk.Button(label="Run in VICE", css_classes=["suggested-action"])
        run.connect("clicked", lambda *_: self.emit("run-cart"))
        bar.append(run)
        self.append(bar)

        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                              margin_start=12, margin_end=12, margin_bottom=12)
        hdr = Gtk.Label(label=f"{'Bank':<6}{'Address':<10}{'Size':<8}Type   First bytes", xalign=0,
                        css_classes=["monospace", "dim-label"], margin_start=8, margin_top=4, margin_bottom=4)
        listbox.append(Gtk.ListBoxRow(child=hdr, activatable=False))
        for ch in c.chips:
            text = (f"{ch.bank:<6}${ch.address:04X}{'':<5}{len(ch.data) // 1024}K{'':<5}"
                    f"{CHIP_TYPES.get(ch.chip_type, '?'):<7}{ch.data[:12].hex(' ')}")
            listbox.append(Gtk.ListBoxRow(child=Gtk.Label(label=text, xalign=0, css_classes=["monospace"],
                                                          margin_start=8, margin_top=2, margin_bottom=2)))
        self.append(Gtk.ScrolledWindow(child=listbox, vexpand=True))

    def save(self):
        """Cartridges are written by builds, not edited here."""
        self.set_modified(False)

