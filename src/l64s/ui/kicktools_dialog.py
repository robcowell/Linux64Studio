"""Create Kick Hash Table / Create Kick List (CBM prg Studio's Kick Assembler tools): the selection
turned into a Kick Assembler Hashtable or List, previewed, then copied or put in its place."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import kicktools as kt  # noqa: E402


class KickToolDialog(Adw.Window):
    def __init__(self, parent, mode: str, text: str, replace=None):
        """`mode` is "hash" or "list"; `replace(text)` puts the result in place of the selection."""
        self.mode = mode
        hash_ = mode == "hash"
        super().__init__(transient_for=parent, modal=True, default_width=860, default_height=520,
                         title="Create Kick Hash Table" if hash_ else "Create Kick List")
        self.replace = replace
        self.result = ""
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tv.add_top_bar(hb)
        self.set_content(tv)
        copy = Gtk.Button(label="Copy")
        copy.connect("clicked", lambda *_: self._copy())
        hb.pack_end(copy)
        if replace:
            rep = Gtk.Button(label="Replace Selection", css_classes=["suggested-action"])
            rep.connect("clicked", lambda *_: self._replace())
            hb.pack_end(rep)
        body = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        tv.set_content(body)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=250)
        body.append(left)
        left.append(Gtk.Label(label="<b>Source</b>  " + ("a key and a value a line" if hash_ else "an item a line"),
                              use_markup=True, xalign=0))
        self.source = Gtk.TextView(monospace=True, top_margin=6, left_margin=6, css_classes=["card", "monospace"])
        self.source.get_buffer().set_text(text)
        self.source.get_buffer().connect("changed", lambda *_: self._update())
        left.append(Gtk.ScrolledWindow(child=self.source, vexpand=True))
        mid = Gtk.Grid(column_spacing=8, row_spacing=8, valign=Gtk.Align.START)
        body.append(mid)
        self.name = Gtk.Entry(text="DirectionTable" if hash_ else "DirectionList")
        self.name.connect("changed", lambda *_: self._update())
        mid.attach(Gtk.Label(label="Name", xalign=0), 0, 0, 1, 1)
        mid.attach(self.name, 1, 0, 1, 1)
        styles = (["As a table (.define)", "As a string: one put", "As a string: a put each"] if hash_
                  else ["As a list (.set each)", "As a string (.add)"])
        self.style = Gtk.DropDown.new_from_strings(styles)
        self.style.connect("notify::selected", lambda *_: self._update())
        mid.attach(Gtk.Label(label="Generate", xalign=0), 0, 1, 1, 1)
        mid.attach(self.style, 1, 1, 1, 1)
        self.q_keys = Gtk.CheckButton(label="Quotes round the keys")
        self.q_values = Gtk.CheckButton(label="Quotes round the values" if hash_ else "Quotes round the items",
                                        active=True)
        for n, c in enumerate((self.q_keys, self.q_values) if hash_ else (self.q_values,)):
            c.connect("toggled", lambda *_: self._update())
            mid.attach(c, 1, 2 + n, 1, 1)
        self.start = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.start.connect("value-changed", lambda *_: self._update())
        if not hash_:
            mid.attach(Gtk.Label(label="Start index", xalign=0), 0, 4, 1, 1)
            mid.attach(self.start, 1, 4, 1, 1)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        body.append(right)
        right.append(Gtk.Label(label="<b>Kick Assembler</b>", use_markup=True, xalign=0))
        self.out = Gtk.TextView(monospace=True, editable=False, top_margin=6, left_margin=6,
                               css_classes=["card", "monospace"],
                               wrap_mode=Gtk.WrapMode.WORD_CHAR)
        right.append(Gtk.ScrolledWindow(child=self.out, vexpand=True))
        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        right.append(self.status)
        self._update()

    def _update(self):
        b = self.source.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        try:
            if self.mode == "hash":
                pairs = kt.parse_pairs(text)
                style = (kt.TABLE, kt.SINGLE, kt.MULTIPLE)[self.style.get_selected()]
                self.result = kt.hashtable(self.name.get_text(), pairs, style, self.q_keys.get_active(),
                                           self.q_values.get_active())
                n = len(pairs)
            else:
                items = kt.parse_items(text)
                style = (kt.LIST, kt.STRING)[self.style.get_selected()]
                self.result = kt.kick_list(self.name.get_text(), items, style, self.q_values.get_active(),
                                           int(self.start.get_value()))
                n = len(items)
            self.status.set_text(f"{n} {'pairs' if self.mode == 'hash' else 'items'}")
        except kt.KickToolError as e:
            self.result = ""
            self.status.set_text(str(e))
        self.out.get_buffer().set_text(self.result)

    def _copy(self):
        if self.result:
            Gdk.Display.get_default().get_clipboard().set(self.result)
            self.status.set_text("Copied: paste it where it's needed")

    def _replace(self):
        if self.result and self.replace:
            self.replace(self.result)
            self.close()
