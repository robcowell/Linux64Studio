"""Music pages: SID files (.sid), GoatTracker songs (.sng) and sound effects (.ins)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..sid.goattracker import (MusicError, PackOptions, launch_editor, pack_song, player_code,  # noqa: E402
                               read_instrument_name, read_song_info)
from ..sid.sidfile import SidError, load_sid, usage_code  # noqa: E402
from .editor import EditorPage  # noqa: E402


def parse_hex(text: str, default: int) -> int:
    t = text.strip().lstrip("$").lower().removeprefix("0x")
    try:
        return int(t, 16) if t else default
    except ValueError:
        return default


def _rel(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return str(path)


class _Player:
    """Plays .sid files with VICE's vsid (one at a time)."""

    def __init__(self, settings):
        self.settings = settings
        self.proc: subprocess.Popen | None = None

    def play(self, sid: Path, tune: int = 1) -> str | None:
        self.stop()
        exe = shutil.which(self.settings.vsid or "vsid") or (self.settings.vsid if Path(self.settings.vsid).is_file() else None)
        if not exe:
            return "VICE's vsid isn't installed (it comes with the vice package)"
        self.proc = subprocess.Popen([exe, "-tune", str(tune), str(sid)], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None


class _MusicPage(EditorPage):
    """Shared layout: a header, a preferences page, and a code box."""

    def __init__(self, path: Path, settings, project=None):
        super().__init__(path)
        self.settings = settings
        self.project = project
        self.player = _Player(settings)
        self.connect("unrealize", lambda *_: self.player.stop())
        self.page = Adw.PreferencesPage(vexpand=True)
        self.append(self.page)
        self.status = Gtk.Label(xalign=0, margin_start=12, margin_bottom=6, wrap=True, css_classes=["dim-label"])
        self.append(self.status)

    def _code_group(self, title: str) -> Gtk.TextView:
        group = Adw.PreferencesGroup(title=title)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy", valign=Gtk.Align.CENTER,
                          css_classes=["flat"])
        group.set_header_suffix(copy)
        view = Gtk.TextView(editable=False, monospace=True, top_margin=8, bottom_margin=8, left_margin=8,
                            css_classes=["card"])
        copy.connect("clicked", lambda *_: (Gdk.Display.get_default().get_clipboard().set(
            view.get_buffer().get_text(view.get_buffer().get_start_iter(), view.get_buffer().get_end_iter(), False)),
            self.status.set_text("Copied to the clipboard")))
        group.add(view)
        self.page.add(group)
        return view

    def _kickass(self) -> bool:
        return bool(self.project) and getattr(self.project, "toolchain", "") == "kickass"

    def save(self):
        self.set_modified(False)


class SidFileView(_MusicPage):
    kind = "sid"

    def __init__(self, path: Path, settings, project=None):
        super().__init__(path, settings, project)
        self.sid = load_sid(path)
        s = self.sid
        info = Adw.PreferencesGroup(title=s.name or path.stem, description=f"{s.author} · {s.released}".strip(" ·"))
        play = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.tune = Gtk.SpinButton.new_with_range(1, max(1, s.songs), 1)
        self.tune.set_value(s.start_song or 1)
        self.tune.set_tooltip_text("Tune to play")
        pb = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Play in vsid")
        sb = Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text="Stop")
        pb.connect("clicked", self._play)
        sb.connect("clicked", lambda *_: self.player.stop())
        for w in (self.tune, pb, sb):
            play.append(w)
        info.set_header_suffix(play)
        for title, value in [
            ("Format", f"{s.magic} version {s.version}"),
            ("Memory", f"${s.load:04X}-${s.end - 1:04X} ({len(s.data)} bytes)"),
            ("Init / play", f"${s.init:04X} / " + (f"${s.play:04X}" if s.play else "its own interrupt")),
            ("Tunes", f"{s.songs} (starts with {s.start_song}, {s.speed_of(s.start_song)} timing)"),
            ("Machine", f"{s.clock}, SID {s.model}"),
        ]:
            info.add(Adw.ActionRow(title=title, subtitle=value, subtitle_selectable=True))
        self.page.add(info)

        ex = Adw.PreferencesGroup(title="Use it in your program",
                                  description="Extract the music to include it at its load address.")
        row = Adw.ActionRow(title="Extract the music data")
        for label, fmt in (("As .bin…", "bin"), ("As .prg…", "prg")):
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, f=fmt: self._extract(f))
            row.add_suffix(b)
        ex.add(row)
        self.page.add(ex)
        self.code = self._code_group("Code to play it")
        self.code.get_buffer().set_text(usage_code(s, f"{path.stem}.bin" if not self._kickass() else path.name,
                                                   kickass=self._kickass()))
        if s.magic == "RSID" or not s.play:
            self.status.set_text("This tune sets up its own interrupt (no play address), so call init only.")

    def _play(self, *_):
        err = self.player.play(self.path, int(self.tune.get_value()))
        self.status.set_text(err or f"Playing tune {int(self.tune.get_value())} in vsid")

    def _extract(self, fmt: str):
        dlg = Gtk.FileDialog(title="Extract music")
        dlg.set_initial_folder(Gio.File.new_for_path(str(self.path.parent)))
        dlg.set_initial_name(f"{self.path.stem}.{fmt}")

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            dest.write_bytes(self.sid.prg() if fmt == "prg" else self.sid.data)
            self.status.set_text(f"Wrote {dest.name}: load it at ${self.sid.load:04X}")
        dlg.save(self.get_root(), None, done)


class SongView(_MusicPage):
    """A GoatTracker song: edit it in GoatTracker or SidMonkey, play it, and pack it on every build."""

    kind = "song"

    def __init__(self, path: Path, settings, project=None, save_project=None):
        super().__init__(path, settings, project)
        self.save_project = save_project or (lambda: None)
        self.info = read_song_info(path)
        i = self.info
        head = Adw.PreferencesGroup(title=i.name or path.stem,
                                    description=" · ".join(x for x in (i.author, i.copyright) if x))
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        for label, which in (("SidMonkey", "sidmonkey"), ("GoatTracker", "goattrk2")):
            b = Gtk.Button(label=f"Edit in {label}")
            b.connect("clicked", lambda _b, w=which: self._edit(w))
            box.append(b)
        head.set_header_suffix(box)
        play_row = Adw.ActionRow(title="Play", subtitle=f"{i.subtunes} subtune(s), packed with the settings below")
        self.tune = Gtk.SpinButton.new_with_range(1, max(1, i.subtunes), 1)
        self.tune.set_valign(Gtk.Align.CENTER)
        pb = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Play")
        sb = Gtk.Button(icon_name="media-playback-stop-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Stop")
        pb.connect("clicked", self._play)
        sb.connect("clicked", lambda *_: self.player.stop())
        for w in (self.tune, pb, sb):
            play_row.add_suffix(w)
        head.add(play_row)
        self.page.add(head)

        link = self._link() or {}
        opts = PackOptions.from_dict(link)
        g = Adw.PreferencesGroup(title="Pack for this project",
                                 description="GoatTracker's gt2reloc packs the song with its playroutine before "
                                             "every build, so your code can include the result.")
        self.on = Adw.SwitchRow(title="Pack on every build", active=bool(link))
        self.out = Adw.EntryRow(title="Output (.bin, .prg or .sid)",
                                text=link.get("output") or _rel(path.with_suffix(".bin"), self._base()))
        self.addr = Adw.EntryRow(title="Player address (hex, a page start)", text=f"{opts.address:04X}")
        self.zp = Adw.EntryRow(title="Zeropage (hex, two bytes)", text=f"{opts.zeropage:02X}")
        self.sfx = Adw.SwitchRow(title="Sound effect support", subtitle="Adds an entry point for effects at +6",
                                 active=opts.sfx)
        self.vol = Adw.SwitchRow(title="Volume change support", active=opts.volume)
        self.ntsc = Adw.SwitchRow(title="NTSC timing", active=opts.ntsc)
        for w in (self.on, self.out, self.addr, self.zp, self.sfx, self.vol, self.ntsc):
            g.add(w)
            w.connect("notify::active" if isinstance(w, Adw.SwitchRow) else "changed", self._changed)
        pack = Gtk.Button(label="Pack now", valign=Gtk.Align.CENTER)
        pack.connect("clicked", self._pack_now)
        g.set_header_suffix(pack)
        self.page.add(g)
        self.code = self._code_group("Code to play it")
        self._update_code()
        if not project:
            self.on.set_sensitive(False)
            self.status.set_text("Open a project to pack this song as part of its build.")

    # ---------------------------------------------------------------- settings
    def _base(self) -> Path:
        return self.project.directory if self.project else self.path.parent

    def _key(self) -> str:
        return _rel(self.path, self._base())

    def _link(self) -> dict | None:
        if not self.project:
            return None
        return next((m for m in self.project.music if m.get("source") == self._key()), None)

    def options(self) -> PackOptions:
        return PackOptions(address=parse_hex(self.addr.get_text(), 0x1000) & 0xFF00,
                           zeropage=parse_hex(self.zp.get_text(), 0xFC) & 0xFF,
                           sfx=self.sfx.get_active(), volume=self.vol.get_active(), ntsc=self.ntsc.get_active())

    def _changed(self, *_):
        self._update_code()
        if not self.project:
            return
        self.project.music = [m for m in self.project.music if m.get("source") != self._key()]
        if self.on.get_active():
            self.project.music.append({"source": self._key(), "output": self.out.get_text().strip(),
                                       **self.options().to_dict()})
        self.save_project()

    def _update_code(self):
        out = self.out.get_text().strip() or "music.bin"
        sfx = Path(out).suffix.lower()
        self.code.get_buffer().set_text(player_code(Path(out).name, self.options(), sfx if sfx in (".sid", ".prg", ".bin")
                                                    else ".bin", kickass=self._kickass()))

    # ---------------------------------------------------------------- actions
    def _edit(self, which: str):
        try:
            launch_editor(which, self.path, self.settings.goattracker_dir)
            self.status.set_text(f"Opened {self.path.name} in {'SidMonkey' if which == 'sidmonkey' else 'GoatTracker'}."
                                 " Save there; the next build packs the new version.")
        except MusicError as e:
            self.status.set_text(str(e))

    def _play(self, *_):
        tmp = Path(tempfile.gettempdir()) / f"l64s-{os.getpid()}-{self.path.stem}.sid"
        try:
            pack_song(self.path, tmp, self.options(), self.settings.goattracker_dir)
        except MusicError as e:
            self.status.set_text(str(e))
            return
        err = self.player.play(tmp, int(self.tune.get_value()))
        self.status.set_text(err or f"Playing subtune {int(self.tune.get_value())}")

    def _pack_now(self, *_):
        out = (self._base() / (self.out.get_text().strip() or self.path.with_suffix(".bin").name)).resolve()
        try:
            r = pack_song(self.path, out, self.options(), self.settings.goattracker_dir)
        except MusicError as e:
            self.status.set_text(str(e))
            return
        self.status.set_text(f"Packed to {out.name}: ${r.start:04X}-${r.end - 1:04X}, {r.size} bytes")


class SfxView(_MusicPage):
    """A GoatTracker instrument used as a sound effect (needs a song packed with sound effect support)."""

    kind = "sfx"

    def __init__(self, path: Path, settings, project=None, save_project=None):
        super().__init__(path, settings, project)
        self.save_project = save_project or (lambda: None)
        name = read_instrument_name(path)
        head = Adw.PreferencesGroup(title=name or path.stem, description="GoatTracker instrument, as a sound effect")
        self.page.add(head)
        link = self._link() or {}
        g = Adw.PreferencesGroup(title="Convert for this project",
                                 description="GoatTracker's ins2snd2 turns the instrument into sound effect data "
                                             "before every build. Waveforms above $81, relative notes, pulse "
                                             "modulation and filters aren't kept.")
        self.on = Adw.SwitchRow(title="Convert on every build", active=bool(link))
        default = path.with_suffix(".asm")
        self.out = Adw.EntryRow(title="Output (.asm for byte lines, or .bin)",
                                text=link.get("output") or _rel(default, self._base()))
        self.label = Adw.EntryRow(title="Label", text=link.get("label") or path.stem.replace("-", "_"))
        for w in (self.on, self.out, self.label):
            g.add(w)
            w.connect("notify::active" if isinstance(w, Adw.SwitchRow) else "changed", self._changed)
        self.page.add(g)
        self.code = self._code_group("Code to play it")
        self._update_code()
        if not project:
            self.on.set_sensitive(False)

    def _base(self) -> Path:
        return self.project.directory if self.project else self.path.parent

    def _key(self) -> str:
        return _rel(self.path, self._base())

    def _link(self) -> dict | None:
        if not self.project:
            return None
        return next((m for m in self.project.music if m.get("source") == self._key()), None)

    def _changed(self, *_):
        self._update_code()
        if not self.project:
            return
        self.project.music = [m for m in self.project.music if m.get("source") != self._key()]
        if self.on.get_active():
            self.project.music.append({"source": self._key(), "output": self.out.get_text().strip(),
                                       "label": self.label.get_text().strip()})
        self.save_project()

    def _update_code(self):
        # The song packed with sound effect support says where the player's effect entry is.
        song = next((m for m in (self.project.music if self.project else []) if m.get("sfx")), None)
        entry = PackOptions.from_dict(song).entry_points()["sfx"] if song else None
        c = "//" if self._kickass() else ";"
        ind = "    " if self._kickass() else "        "
        label = self.label.get_text().strip() or "effect"
        lines = [f"{c} Needs a song packed with sound effect support"
                 + ("" if song else " (none is set up in this project yet)"),
                 f"{ind}lda #<{label}", f"{ind}ldy #>{label}", f"{ind}ldx #14{'      ' if not self._kickass() else ''} {c} channel: 0, 7 or 14",
                 f"{ind}jsr " + (f"${entry:04X}" if entry else "musicStart+6")]
        out = self.out.get_text().strip()
        if out.lower().endswith(".bin"):
            lines = [f"{label}{':' if self._kickass() else ''}",
                     (f'{ind}.import binary "{Path(out).name}"' if self._kickass() else f"{ind}incbin {Path(out).name}"),
                     ""] + lines
        else:
            lines = [(f'#import "{Path(out).name}"' if self._kickass() else f'{ind}incasm "{Path(out).name}"'), ""] + lines
        self.code.get_buffer().set_text("\n".join(lines) + "\n")
