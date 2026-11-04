"""SID Designer: set up the three SID voices and the filter, hear them through VICE's reSID
(an idle vsid we write the registers into), and generate BASIC POKEs or assembler for them.
Like CBM prg Studio's SID tool, with the GoatTracker and .sid pages alongside it."""
from __future__ import annotations

import copy
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from ..sid.designer import (ATTACK_MS, DECAY_MS, EXTENSION, NOTE_NAMES, WAVEFORMS, WHITE_KEYS,  # noqa: E402
                            WHITE_SEMITONES, BLACK_KEYS, CodeOptions, Sound, generate, key_semitone,
                            note_name, register_hz, semitone_note)
from ..sid.live import LiveError, LiveSid  # noqa: E402
from ..sid.midi import MidiInput, MidiUnavailable, MidiVoices, describe, input_names, note_label, pick_device  # noqa: E402
from .editor import EditorPage  # noqa: E402

KEY_LABELS = {"Tab": "Tab", "bracketleft": "[", "bracketright": "]", "Return": "Ret", "minus": "-", "equal": "=",
              "BackSpace": "Bk"}


def _ms(ms: int) -> str:
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:g} s"


class Piano(Gtk.DrawingArea):
    """Two octaves. Press and hold a key (mouse or PC keyboard) to play it."""

    __gsignals__ = {"note-on": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
                    "note-off": (GObject.SignalFlags.RUN_FIRST, None, ())}
    WHITE_W = 34
    HEIGHT = 120

    def __init__(self):
        super().__init__(content_width=14 * self.WHITE_W + 1, content_height=self.HEIGHT, halign=Gtk.Align.START)
        self.down: int | None = None
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, _n, x, y: self._press(self._hit(x, y)))
        click.connect("released", lambda *_: self.release())
        self.add_controller(click)
        self._labels = {WHITE_SEMITONES[i]: KEY_LABELS.get(k, k.upper()) for i, k in enumerate(WHITE_KEYS)}
        self._labels.update({s: KEY_LABELS.get(k, k) for k, s in BLACK_KEYS.items()})

    def _black_keys(self):
        bw = self.WHITE_W * 0.6
        for w in range(13):
            if w % 7 in (2, 6):          # no black key after E or B
                continue
            yield WHITE_SEMITONES[w] + 1, (w + 1) * self.WHITE_W - bw / 2, bw

    def _hit(self, x: float, y: float) -> int | None:
        if y < self.HEIGHT * 0.6:
            for semi, bx, bw in self._black_keys():
                if bx <= x < bx + bw:
                    return semi
        w = int(x // self.WHITE_W)
        return WHITE_SEMITONES[w] if 0 <= w < 14 else None

    def _press(self, semi: int | None):
        if semi is None:
            return
        self.down = semi
        self.queue_draw()
        self.emit("note-on", semi)

    def press(self, semi: int):
        if semi != self.down:
            self._press(semi)

    def release(self):
        if self.down is not None:
            self.down = None
            self.queue_draw()
            self.emit("note-off")

    def _draw(self, _w, cr, _width, _height):
        h = self.HEIGHT
        cr.select_font_face("Sans")
        cr.set_font_size(10)
        for w in range(14):
            semi = WHITE_SEMITONES[w]
            x = w * self.WHITE_W
            cr.rectangle(x + 0.5, 0.5, self.WHITE_W, h - 1)
            cr.set_source_rgb(*((0.55, 0.75, 1.0) if semi == self.down else (0.97, 0.97, 0.95)))
            cr.fill_preserve()
            cr.set_source_rgb(0.2, 0.2, 0.2)
            cr.set_line_width(1)
            cr.stroke()
            label = self._labels[semi]
            cr.move_to(x + 4, h - 22)
            cr.show_text(label)
            cr.set_source_rgb(0.45, 0.45, 0.45)
            cr.move_to(x + 4, h - 8)
            cr.show_text(NOTE_NAMES[semi % 12])
        for semi, bx, bw in self._black_keys():
            cr.rectangle(bx, 0, bw, h * 0.6)
            cr.set_source_rgb(*((0.3, 0.5, 0.9) if semi == self.down else (0.12, 0.12, 0.12)))
            cr.fill()
            cr.set_source_rgb(0.85, 0.85, 0.85)
            cr.move_to(bx + 3, h * 0.6 - 6)
            cr.show_text(self._labels[semi])


class SidDesigner(EditorPage):
    kind = "siddesigner"

    def __init__(self, settings, kickass: bool = False, project_dir: Path | None = None, insert_cb=None,
                 path: Path | None = None):
        super().__init__(path)
        self.settings = settings
        self.kickass = kickass
        self.project_dir = project_dir
        self.insert_cb = insert_cb
        self.sound = Sound()
        self.file: Path | None = None
        self.gates = [False, False, False]      # the Play toggles
        self.held: set[int] = set()             # voices held by the 1/2/3 keys
        self.piano_note: tuple[int, int, int] | None = None   # (voice, note, octave) being played
        self.live: LiveSid | None = None
        self._starting = False
        self._loading = False
        channels = list(getattr(settings, "sid_midi_channels", None) or [1, 2, 3])[:3]
        self.midi = MidiVoices([c - 1 if 1 <= c <= 16 else -1 for c in channels + [1, 2, 3][len(channels):]])
        self.midi_in = MidiInput(lambda msg: GLib.idle_add(self._on_midi, msg))
        self.connect("unrealize", lambda *_: (self._stop_live(), self.midi_in.close()))

        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        for icon, tip, cb in (("document-open-symbolic", "Load settings…", self._load_dialog),
                              ("document-save-symbolic", "Save settings…", self._save_dialog)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", cb)
            bar.append(b)
        self.keyboard_btn = Gtk.ToggleButton(label="Keyboard", tooltip_text="Show a two-octave keyboard to play")
        self.keyboard_btn.connect("toggled", lambda b: self.piano_revealer.set_reveal_child(b.get_active()))
        bar.append(self.keyboard_btn)
        silence = Gtk.Button(label="Silence", tooltip_text="Gate off all voices")
        silence.connect("clicked", lambda *_: self._silence())
        bar.append(silence)
        self.midi_btn = Gtk.ToggleButton(label="MIDI", tooltip_text="Play the voices from a MIDI keyboard")
        self.midi_btn.connect("toggled", lambda b: self.midi_revealer.set_reveal_child(b.get_active()))
        bar.append(self.midi_btn)
        bar.append(Gtk.Label(label="SID", margin_start=12))
        self.model = Gtk.DropDown.new_from_strings(["6581", "8580"])
        self.model.set_tooltip_text("The SID chip VICE plays the sound with")
        self.model.connect("notify::selected", self._model_changed)
        bar.append(self.model)
        self.ntsc = Gtk.DropDown.new_from_strings(["PAL", "NTSC"])
        self.ntsc.set_tooltip_text("The C64's clock, which sets the note frequencies")
        self.ntsc.connect("notify::selected", lambda *_: self._changed())
        bar.append(self.ntsc)
        self.stack = Adw.ViewStack(vexpand=True)
        bar.append(Gtk.Box(hexpand=True))
        bar.append(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.append(bar)

        self.piano_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        prow = Gtk.Box(spacing=10, margin_start=8, margin_end=8, margin_bottom=6)
        pctl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        pctl.append(Gtk.Label(label="Octave", xalign=0))
        self.base_octave = Gtk.SpinButton.new_with_range(0, 6, 1)
        self.base_octave.set_value(3)
        pctl.append(self.base_octave)
        pctl.append(Gtk.Label(label="Voice", xalign=0))
        self.piano_voice = Gtk.DropDown.new_from_strings(["1", "2", "3"])
        pctl.append(self.piano_voice)
        prow.append(pctl)
        self.piano = Piano()
        self.piano.connect("note-on", self._piano_on)
        self.piano.connect("note-off", lambda *_: self._piano_off())
        prow.append(Gtk.ScrolledWindow(child=self.piano, hexpand=True, vscrollbar_policy=Gtk.PolicyType.NEVER))
        self.piano_revealer.set_child(prow)
        self.append(self.piano_revealer)
        self.midi_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.midi_revealer.set_child(self._midi_row())
        self.append(self.midi_revealer)

        self.stack.add_titled_with_icon(self._sound_page(), "sound", "Voices & Filter", "audio-x-generic-symbolic")
        self.stack.add_titled_with_icon(self._code_page(), "code", "Code Generation", "text-x-generic-symbolic")
        self.append(self.stack)
        self.status = Gtk.Label(xalign=0, margin_start=10, margin_bottom=6, wrap=True, css_classes=["dim-label"],
                                label="Press 1, 2 or 3 to play a voice; give it a waveform first")
        self.append(self.status)

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key_pressed)
        keys.connect("key-released", self._key_released)
        self.add_controller(keys)
        self._load_widgets()
        if path:
            self.load_file(path)
        self._detect_midi(quiet=True)

    @property
    def title(self) -> str:
        return self.file.name if self.file else "SID Designer"

    def save(self) -> None:
        if self.file:
            self.sound.save(self.file)
            self.set_modified(False)

    # ================================================================== widgets
    def _spin_scale(self, lo, hi, tip="", spin=True):
        """A scale, with a spin button for the wide ranges; returns (box, adjustment)."""
        adj = Gtk.Adjustment(lower=lo, upper=hi, step_increment=1, page_increment=max(1, (hi - lo) // 16))
        scale = Gtk.Scale(adjustment=adj, hexpand=True, draw_value=False, digits=0)
        scale.set_size_request(90, -1)
        box = Gtk.Box(spacing=4, tooltip_text=tip or None, hexpand=True)
        box.append(scale)
        if spin:
            box.append(Gtk.SpinButton(adjustment=adj, numeric=True, width_chars=5))
        adj.connect("value-changed", lambda *_: self._changed())
        return box, adj

    def _sound_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=8, margin_end=8,
                        margin_bottom=8)
        voices = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, min_children_per_line=3,
                             homogeneous=True, column_spacing=8, row_spacing=8)
        self.vw: list[dict] = []
        for i in range(3):
            voices.append(self._voice_box(i))
        outer.append(voices)
        outer.append(self._filter_box())
        self.reg_label = Gtk.Label(xalign=0, selectable=True, css_classes=["monospace", "dim-label"], wrap=True)
        outer.append(self.reg_label)
        return Gtk.ScrolledWindow(child=outer, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)

    def _voice_box(self, i: int):
        w: dict = {}
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["card"])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=10, margin_end=10,
                        margin_top=8, margin_bottom=10)
        frame.append(inner)
        head = Gtk.Box(spacing=6)
        head.append(Gtk.Label(label=f"<b>Voice {i + 1}</b>", use_markup=True, xalign=0, hexpand=True))
        play = Gtk.ToggleButton(icon_name="media-playback-start-symbolic",
                                tooltip_text=f"Play voice {i + 1} (gate on) until untoggled; or hold {i + 1}")
        play.connect("toggled", lambda b, i=i: self._gate(i, b.get_active()))
        w["play"] = play
        head.append(play)
        copy_btn = Gtk.MenuButton(icon_name="edit-copy-symbolic", tooltip_text="Copy this voice to another")
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=6, margin_end=6, margin_top=6,
                       margin_bottom=6)
        w["copy_notes"] = Gtk.CheckButton(label="Copy the note too", active=True)
        pbox.append(w["copy_notes"])
        for j in range(3):
            if j != i:
                b = Gtk.Button(label=f"Copy to voice {j + 1}", css_classes=["flat"])
                b.connect("clicked", lambda _b, i=i, j=j, p=pop: (p.popdown(), self._copy_voice(i, j)))
                pbox.append(b)
        pop.set_child(pbox)
        copy_btn.set_popover(pop)
        head.append(copy_btn)
        inner.append(head)

        note = Gtk.Box(spacing=6)
        note.append(Gtk.Label(label="Note"))
        w["note"] = Gtk.DropDown.new_from_strings(NOTE_NAMES)
        w["note"].connect("notify::selected", lambda *_: self._changed())
        note.append(w["note"])
        note.append(Gtk.Label(label="Octave"))
        w["octave"] = Gtk.SpinButton.new_with_range(0, 7, 1)
        w["octave"].connect("value-changed", lambda *_: self._changed())
        note.append(w["octave"])
        inner.append(note)
        w["freq"] = Gtk.Label(xalign=0, css_classes=["dim-label", "monospace"])
        inner.append(w["freq"])

        waves = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                             homogeneous=True)
        for name, _bit in WAVEFORMS:
            w[name] = Gtk.CheckButton(label=name.capitalize())
            w[name].connect("toggled", lambda *_: self._changed())
            waves.append(w[name])
        other = "voice 3" if i == 0 else f"voice {i}"
        for name, label, tip in (("ring", "Ring", f"Ring modulate the triangle with {other}"),
                                 ("sync", "Sync", f"Hard sync to {other}"),
                                 ("test", "Test", "The test bit: silences and resets the oscillator"),
                                 ("filtered", "Filter", "Send this voice through the filter")):
            w[name] = Gtk.CheckButton(label=label, tooltip_text=tip)
            w[name].connect("toggled", lambda *_: self._changed())
            waves.append(w[name])
        inner.append(waves)

        inner.append(Gtk.Label(label="Pulse width", xalign=0))
        box, w["pw"] = self._spin_scale(0, 4095, "0-4095: 2048 is a square wave")
        inner.append(box)
        w["pw_label"] = Gtk.Label(xalign=0, css_classes=["dim-label"])
        inner.append(w["pw_label"])

        grid = Gtk.Grid(column_spacing=6, row_spacing=2)
        for r, (key, label) in enumerate((("attack", "Attack"), ("decay", "Decay"), ("sustain", "Sustain"),
                                          ("release", "Release"))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            box, w[key] = self._spin_scale(0, 15, spin=False)
            grid.attach(box, 1, r, 1, 1)
            w[key + "_label"] = Gtk.Label(xalign=0, width_chars=11, css_classes=["monospace"])
            grid.attach(w[key + "_label"], 2, r, 1, 1)
        inner.append(grid)
        self.vw.append(w)
        return frame

    def _filter_box(self):
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
        g = Gtk.Grid(column_spacing=8, row_spacing=6, margin_start=10, margin_end=10, margin_top=8, margin_bottom=10)
        frame.append(g)
        g.attach(Gtk.Label(label="<b>Filter and volume</b>", use_markup=True, xalign=0), 0, 0, 3, 1)
        self.fw: dict = {}
        g.attach(Gtk.Label(label="Cutoff", xalign=0), 0, 1, 1, 1)
        box, self.fw["cutoff"] = self._spin_scale(0, 2047, "0-2047 (11 bits)")
        g.attach(box, 1, 1, 1, 1)
        g.attach(Gtk.Label(label="Resonance", xalign=0), 0, 2, 1, 1)
        box, self.fw["resonance"] = self._spin_scale(0, 15)
        g.attach(box, 1, 2, 1, 1)
        g.attach(Gtk.Label(label="Volume", xalign=0), 0, 3, 1, 1)
        box, self.fw["volume"] = self._spin_scale(0, 15)
        g.attach(box, 1, 3, 1, 1)
        modes = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5, min_children_per_line=2)
        for key, label, tip in (("low_pass", "Low pass", ""), ("band_pass", "Band pass", ""),
                                ("high_pass", "High pass", ""),
                                ("voice3_off", "Voice 3 off", "Mute voice 3 (it can still ring modulate or sync)"),
                                ("external", "Filter external input", "")):
            self.fw[key] = Gtk.CheckButton(label=label, tooltip_text=tip or None)
            self.fw[key].connect("toggled", lambda *_: self._changed())
            modes.append(self.fw[key])
        g.attach(modes, 0, 4, 3, 1)
        return frame

    def _code_page(self):
        outer = Gtk.Box(spacing=12, margin_start=8, margin_end=8, margin_bottom=8)
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.cw: dict = {}

        def check(key, label, active, tip=None):
            self.cw[key] = Gtk.CheckButton(label=label, active=active, tooltip_text=tip)
            self.cw[key].connect("toggled", lambda *_: self._update_code())
            opts.append(self.cw[key])

        opts.append(Gtk.Label(label="<b>Include</b>", use_markup=True, xalign=0))
        for i in range(3):
            check(f"v{i}", f"Voice {i + 1}", i == 0)
        check("filter", "Filter (cutoff, resonance, routing)", True)
        check("mode_volume", "Filter mode and volume", True)
        opts.append(Gtk.Label(label="<b>Source type</b>", use_markup=True, xalign=0, margin_top=6))
        self.source = Gtk.DropDown.new_from_strings(["BASIC", "Assembler"])
        self.source.connect("notify::selected", lambda *_: self._update_code())
        opts.append(self.source)
        opts.append(Gtk.Label(label="<b>BASIC options</b>", use_markup=True, xalign=0, margin_top=6))
        lines = Gtk.Box(spacing=6)
        lines.append(Gtk.Label(label="Start line"))
        self.start_line = Gtk.SpinButton.new_with_range(0, 63999, 10)
        self.start_line.set_value(10)
        self.start_line.connect("value-changed", lambda *_: self._update_code())
        lines.append(self.start_line)
        lines.append(Gtk.Label(label="Step"))
        self.step = Gtk.SpinButton.new_with_range(1, 1000, 1)
        self.step.set_value(10)
        self.step.connect("value-changed", lambda *_: self._update_code())
        lines.append(self.step)
        opts.append(lines)
        opts.append(Gtk.Label(label="<b>Other options</b>", use_markup=True, xalign=0, margin_top=6))
        self.use_var = Gtk.CheckButton(label="Use a variable name", active=True)
        self.use_addr = Gtk.CheckButton(label="Use addresses", group=self.use_var)
        self.use_var.connect("toggled", lambda *_: self._update_code())
        vrow = Gtk.Box(spacing=6)
        vrow.append(self.use_var)
        self.var_name = Gtk.Entry(placeholder_text="VB / SID", width_chars=8, max_length=16)
        self.var_name.connect("changed", lambda *_: self._update_code())
        vrow.append(self.var_name)
        opts.append(vrow)
        opts.append(self.use_addr)
        check("comments", "Add comments", True)
        check("clear_sid", "Clear SID chip first", False)
        check("gate", "Start the sound (gate on)", True,
              "Write each voice's control register with the gate bit set, last")
        outer.append(Gtk.ScrolledWindow(child=opts, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        btns = Gtk.Box(spacing=6)
        cp = Gtk.Button(label="Copy", tooltip_text="Copy the code to the clipboard")
        cp.connect("clicked", lambda *_: self._copy_code())
        btns.append(cp)
        ins = Gtk.Button(label="Insert into Editor", tooltip_text="Insert at the cursor in the last source file used")
        ins.connect("clicked", lambda *_: self._insert_code())
        btns.append(ins)
        right.append(btns)
        self.code = Gtk.TextView(editable=False, monospace=True, top_margin=8, bottom_margin=8, left_margin=8,
                                 css_classes=["card", "monospace"])
        right.append(Gtk.ScrolledWindow(child=self.code, vexpand=True, hexpand=True))
        outer.append(right)
        return outer

    # ================================================================== model <-> widgets
    def _load_widgets(self):
        self._loading = True
        try:
            s = self.sound
            for v, w in zip(s.voices, self.vw):
                w["note"].set_selected(v.note)
                w["octave"].set_value(v.octave)
                for name in ("triangle", "sawtooth", "pulse", "noise", "ring", "sync", "test", "filtered"):
                    w[name].set_active(getattr(v, name))
                w["pw"].set_value(v.pulse_width)
                for k in ("attack", "decay", "sustain", "release"):
                    w[k].set_value(getattr(v, k))
            f = s.filter
            for k in ("cutoff", "resonance", "volume"):
                self.fw[k].set_value(getattr(f, k))
            for k in ("low_pass", "band_pass", "high_pass", "voice3_off", "external"):
                self.fw[k].set_active(getattr(f, k))
            self.model.set_selected(1 if s.model == "8580" else 0)
            self.ntsc.set_selected(1 if s.ntsc else 0)
        finally:
            self._loading = False
        self._changed(modified=False)

    def _read_widgets(self):
        s = self.sound
        for v, w in zip(s.voices, self.vw):
            if (w["note"].get_selected(), w["octave"].get_value_as_int()) != (v.note, v.octave):
                v.frequency = None
            v.note = w["note"].get_selected()
            v.octave = w["octave"].get_value_as_int()
            for name in ("triangle", "sawtooth", "pulse", "noise", "ring", "sync", "test", "filtered"):
                setattr(v, name, w[name].get_active())
            v.pulse_width = int(w["pw"].get_value())
            for k in ("attack", "decay", "sustain", "release"):
                setattr(v, k, int(w[k].get_value()))
        f = s.filter
        for k in ("cutoff", "resonance", "volume"):
            setattr(f, k, int(self.fw[k].get_value()))
        for k in ("low_pass", "band_pass", "high_pass", "voice3_off", "external"):
            setattr(f, k, self.fw[k].get_active())
        s.ntsc = self.ntsc.get_selected() == 1
        s.model = "8580" if self.model.get_selected() == 1 else "6581"

    def _changed(self, modified: bool = True):
        if self._loading:
            return
        self._read_widgets()
        s = self.sound
        for v, w in zip(s.voices, self.vw):
            f = v.freq(s.clock)
            w["freq"].set_text(f"{register_hz(f, s.clock):.2f} Hz   ${f:04X}")
            pw = v.pulse_width
            w["pw_label"].set_text(f"{pw * 100 / 4096:.1f}% duty" + ("" if v.pulse else "  (pulse waveform is off)"))
            w["attack_label"].set_text(f"{v.attack:>2}  {_ms(ATTACK_MS[v.attack])}")
            w["decay_label"].set_text(f"{v.decay:>2}  {_ms(DECAY_MS[v.decay])}")
            w["sustain_label"].set_text(f"{v.sustain:>2}  {v.sustain * 100 // 15}%")
            w["release_label"].set_text(f"{v.release:>2}  {_ms(DECAY_MS[v.release])}")
        regs = self._registers()
        self.reg_label.set_text("$D400  " + " ".join(f"{b:02X}" for b in regs[:7]) + "    $D407  "
                                + " ".join(f"{b:02X}" for b in regs[7:14]) + "    $D40E  "
                                + " ".join(f"{b:02X}" for b in regs[14:21]) + "    $D415  "
                                + " ".join(f"{b:02X}" for b in regs[21:]))
        if modified and self.file:
            self.set_modified(True)
        self._update_code()
        self._send()

    def _copy_voice(self, i: int, j: int):
        self.sound.voices[j].copy_from(self.sound.voices[i], notes=self.vw[i]["copy_notes"].get_active())
        self._load_widgets()
        self.status.set_text(f"Copied voice {i + 1} to voice {j + 1}")
        if self.file:
            self.set_modified(True)

    # ================================================================== code
    def code_options(self) -> CodeOptions:
        asm = self.source.get_selected() == 1
        return CodeOptions(voices=tuple(self.cw[f"v{i}"].get_active() for i in range(3)),
                           filter=self.cw["filter"].get_active(), mode_volume=self.cw["mode_volume"].get_active(),
                           source="asm" if asm else "basic", start_line=self.start_line.get_value_as_int(),
                           step=self.step.get_value_as_int(), use_variable=self.use_var.get_active(),
                           variable=self.var_name.get_text().strip(), comments=self.cw["comments"].get_active(),
                           clear_sid=self.cw["clear_sid"].get_active(), gate=self.cw["gate"].get_active(),
                           kickass=self.kickass)

    def _update_code(self):
        if self._loading or not hasattr(self, "code"):
            return
        try:
            text = generate(self.sound, self.code_options())
        except ValueError as e:
            text = f"({e})"
        self.code.get_buffer().set_text(text)

    def code_text(self) -> str:
        b = self.code.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def _copy_code(self):
        Gdk.Display.get_default().get_clipboard().set(self.code_text())
        self.status.set_text("Copied the code")

    def _insert_code(self):
        if not self.insert_cb:
            return
        where = self.insert_cb(self.code_text())
        self.status.set_text(f"Inserted into {where}" if where else "Open a source file to insert into")

    # ================================================================== playing
    def _registers(self, gates=None) -> bytes:
        s = self.sound
        g = list(gates if gates is not None else self._gates())
        played = self._played()
        if played:
            s = copy.deepcopy(s)
            for voice, (note, octave) in played.items():
                s.voices[voice].note, s.voices[voice].octave, s.voices[voice].frequency = note, octave, None
        return s.registers(tuple(g))

    def _played(self) -> dict[int, tuple[int, int]]:
        """The notes being played from MIDI or the piano, by voice (the piano wins)."""
        out = {v: n for v in range(3) if (n := self.midi.playing(v))}
        if self.piano_note:
            voice, note, octave = self.piano_note
            out[voice] = (note, octave)
        return out

    def _gates(self) -> list[bool]:
        played = self._played()
        return [self.gates[i] or i in self.held or i in played for i in range(3)]

    def _send(self, retrigger: int | None = None):
        live = self.live
        if not live or not live.running:
            return
        try:
            if retrigger is not None:
                regs = self._registers()
                off = 7 * retrigger + 4
                live.write(bytes([regs[off] & 0xFE]), off)      # gate off, so the envelope restarts
            live.write(self._registers())
        except LiveError as e:
            self.status.set_text(str(e))

    def _ensure_live(self, then=None):
        """Start vsid if it isn't running, then call `then` (on the main thread)."""
        if self.live and self.live.running:
            if then:
                then()
            return
        if self._starting:
            return
        self._starting = True
        self.status.set_text("Starting VICE's vsid for the sound…")
        self.live = LiveSid(self.settings.vsid if self.settings else "", self.sound.model)

        def run():
            try:
                self.live.start()
                err = None
            except LiveError as e:
                err = str(e)
            GLib.idle_add(done, err)

        def done(err):
            self._starting = False
            if err:
                self.status.set_text(err)
                return False
            self.status.set_text(f"Playing through vsid (reSID {self.sound.model})")
            self._send()
            if then:
                then()
            return False

        threading.Thread(target=run, daemon=True).start()

    def _gate(self, i: int, on: bool, retrigger: bool = True):
        if self._loading:
            return
        self.gates[i] = on
        if on and not self.sound.voices[i].has_waveform:
            self.status.set_text(f"Voice {i + 1} has no waveform, so it makes no sound: tick one")
        if on:
            self._ensure_live(lambda: self._send(retrigger=i if retrigger else None))
        else:
            self._send()

    def _silence(self):
        self.held.clear()
        self.piano_note = None
        self.midi.all_off()
        self._loading = True
        for i, w in enumerate(self.vw):
            w["play"].set_active(False)
            self.gates[i] = False
        self._loading = False
        self.piano.release()
        self._send()

    def _model_changed(self, *_):
        if self._loading:
            return
        self._changed()
        if self.live and self.live.model != self.sound.model:
            self._stop_live()
            if any(self._gates()):
                self._ensure_live()

    def _stop_live(self):
        live, self.live = self.live, None
        if live:
            threading.Thread(target=live.stop, daemon=True).start()

    def _piano_on(self, _p, semi: int):
        voice = self.piano_voice.get_selected()
        note, octave = semitone_note(self.base_octave.get_value_as_int(), semi)
        if octave > 7:
            return
        self.piano_note = (voice, note, octave)
        self.status.set_text(f"Voice {voice + 1}: {note_name(note, octave)}"
                             + ("" if self.sound.voices[voice].has_waveform else " (no waveform set: silent)"))
        self._ensure_live(lambda: self._send(retrigger=voice))

    def _piano_off(self):
        self.piano_note = None
        self._send()

    # ================================================================== MIDI
    def _midi_row(self):
        row = Gtk.Box(spacing=8, margin_start=8, margin_end=8, margin_bottom=6)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        line = Gtk.Box(spacing=6)
        line.append(Gtk.Label(label="Input"))
        self.midi_names = Gtk.StringList()
        self.midi_device = Gtk.DropDown(model=self.midi_names, hexpand=True)
        self.midi_device.set_size_request(220, -1)
        self.midi_device.connect("notify::selected", lambda *_: self._choose_device())
        line.append(self.midi_device)
        detect = Gtk.Button(label="Detect Device", tooltip_text="Look again for MIDI inputs (after plugging one in)")
        detect.connect("clicked", lambda *_: self._detect_midi())
        line.append(detect)
        col.append(line)
        chans = Gtk.Box(spacing=6)
        self.midi_spins = []
        for v in range(3):
            chans.append(Gtk.Label(label=f"Voice {v + 1} channel", margin_start=0 if v == 0 else 8))
            spin = Gtk.SpinButton.new_with_range(0, 16, 1)
            spin.set_value(self.midi.channels[v] + 1)
            spin.set_tooltip_text("The MIDI channel this voice plays (0 = not from MIDI)")
            spin.connect("output", self._channel_text)
            spin.connect("value-changed", lambda *_: self._channels_changed())
            self.midi_spins.append(spin)
            chans.append(spin)
        col.append(chans)
        row.append(col)
        mon = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, css_classes=["card"])
        mon.append(Gtk.Label(label="<b>MIDI monitor</b>", use_markup=True, xalign=0, margin_start=8, margin_top=4))
        self.midi_last = Gtk.Label(label="No messages yet", xalign=0, margin_start=8, css_classes=["monospace"],
                                   selectable=True)
        mon.append(self.midi_last)
        self.midi_map = Gtk.Label(xalign=0, margin_start=8, margin_bottom=4, css_classes=["dim-label"])
        mon.append(self.midi_map)
        row.append(mon)
        self.midi_map.set_text(self.midi.mapping_text())
        return row

    @staticmethod
    def _channel_text(spin):
        v = spin.get_value_as_int()
        spin.set_text("Off" if v == 0 else str(v))
        return True

    def _channels_changed(self):
        self.midi.channels = [s.get_value_as_int() - 1 for s in self.midi_spins]
        self.midi.all_off()
        self.midi_map.set_text(self.midi.mapping_text())
        self._send()
        if self.settings is not None:
            self.settings.sid_midi_channels = [s.get_value_as_int() for s in self.midi_spins]
            try:
                self.settings.save()
            except OSError:
                pass

    def _detect_midi(self, quiet: bool = False):
        """List the MIDI inputs and open one, as CBM prg Studio's Detect Device does."""
        try:
            names = input_names()
        except MidiUnavailable as e:
            if not quiet:
                self.status.set_text(str(e))
            self._midi_names_set([])
            return
        self._midi_names_set(names)
        wanted = getattr(self.settings, "sid_midi_device", "") if self.settings else ""
        name = wanted if wanted in names else pick_device(names)
        if name is None:
            self.midi_in.close()
            if not quiet:
                self.status.set_text("No MIDI device found (only ALSA's Midi Through port): plug one in and press "
                                     "Detect Device")
            return
        self._loading_midi = True
        self.midi_device.set_selected(names.index(name))
        self._loading_midi = False
        self._open_midi(name, quiet)

    def _midi_names_set(self, names):
        self._loading_midi = True
        self.midi_names.splice(0, self.midi_names.get_n_items(), names)
        self._loading_midi = False

    def _choose_device(self):
        if getattr(self, "_loading_midi", False):
            return
        item = self.midi_device.get_selected_item()
        if item is not None:
            self._open_midi(item.get_string())

    def _open_midi(self, name: str, quiet: bool = False):
        if self.midi_in.is_open and self.midi_in.name == name:
            if not quiet:
                self.status.set_text(f"MIDI: listening to {name}")
            return
        self._release_midi()
        try:
            self.midi_in.open(name)
        except MidiUnavailable as e:
            self.status.set_text(str(e))
            return
        if self.settings is not None and getattr(self.settings, "sid_midi_device", None) != name:
            self.settings.sid_midi_device = name
            try:
                self.settings.save()
            except OSError:
                pass
        self.midi_last.set_text(f"Listening to {name}")
        if not quiet:
            self.status.set_text(f"MIDI: listening to {name}")
        else:
            self.midi_btn.set_active(True)          # a device was there when the designer opened: show the monitor

    def _release_midi(self):
        if self.midi.all_off():
            self._send()

    def _on_midi(self, msg):
        if not self.get_realized():
            return False
        self.midi_last.set_text(describe(msg))
        for ch in self.midi.handle(msg):
            if ch.note is not None and ch.retrigger:
                if not self.sound.voices[ch.voice].has_waveform:
                    self.status.set_text(f"Voice {ch.voice + 1} has no waveform, so it makes no sound: tick one")
                else:
                    self.status.set_text(f"MIDI: voice {ch.voice + 1} plays {note_label(12 * (ch.note[1] + 1) + ch.note[0])}")
                self._ensure_live(lambda v=ch.voice: self._send(retrigger=v))
            else:
                self._send()
        return False

    # ================================================================== keys
    def _typing(self) -> bool:
        focus = self.get_root().get_focus() if self.get_root() else None
        return isinstance(focus, (Gtk.Text, Gtk.Entry, Gtk.TextView)) and not isinstance(focus, Gtk.SpinButton) \
            and focus.get_ancestor(Gtk.SpinButton) is None

    def _key_pressed(self, _c, keyval, _code, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK) or self._typing():
            return False
        name = Gdk.keyval_name(keyval) or ""
        if self.piano_revealer.get_reveal_child():
            semi = key_semitone(name)
            if semi is not None:
                self.piano.press(semi)
                return True
            return False
        if name in ("1", "2", "3", "KP_1", "KP_2", "KP_3"):
            i = int(name[-1]) - 1
            if i not in self.held:                 # ignore key repeat
                self.held.add(i)
                self._gate_held(i)
            return True
        return False

    def _gate_held(self, i: int):
        if not self.sound.voices[i].has_waveform:
            self.status.set_text(f"Voice {i + 1} has no waveform, so it makes no sound: tick one")
        self._ensure_live(lambda: self._send(retrigger=i))

    def _key_released(self, _c, keyval, _code, _state):
        name = Gdk.keyval_name(keyval) or ""
        if self.piano_revealer.get_reveal_child():
            semi = key_semitone(name)
            if semi is not None and semi == self.piano.down:
                self.piano.release()
            return
        if name in ("1", "2", "3", "KP_1", "KP_2", "KP_3"):
            self.held.discard(int(name[-1]) - 1)
            self._send()

    # ================================================================== files
    def load_file(self, path: Path):
        try:
            self.sound = Sound.load(path)
        except (OSError, ValueError) as e:
            self.status.set_text(f"Couldn't load {path.name}: {e}")
            return
        self.file = path
        self._load_widgets()
        self.set_modified(False)
        self.status.set_text(f"Loaded {path.name}")
        self.emit("modified-changed")      # the tab title shows the file name

    def _dialog(self, title: str) -> Gtk.FileDialog:
        dlg = Gtk.FileDialog(title=title)
        folder = self.file.parent if self.file else self.project_dir
        if folder:
            dlg.set_initial_folder(Gio.File.new_for_path(str(folder)))
        flt = Gtk.FileFilter(name="SID sounds (*" + EXTENSION + ")")
        flt.add_pattern("*" + EXTENSION)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        dlg.set_filters(filters)
        return dlg

    def _load_dialog(self, *_):
        dlg = self._dialog("Load SID settings")

        def done(d, res):
            try:
                self.load_file(Path(d.open_finish(res).get_path()))
            except GLib.Error:
                pass
        dlg.open(self.get_root(), None, done)

    def _save_dialog(self, *_):
        dlg = self._dialog("Save SID settings")
        dlg.set_initial_name(self.file.name if self.file else "sound" + EXTENSION)

        def done(d, res):
            try:
                dest = Path(d.save_finish(res).get_path())
            except GLib.Error:
                return
            if dest.suffix.lower() != EXTENSION:
                dest = dest.with_name(dest.name + EXTENSION)
            self.sound.save(dest)
            self.file = dest
            self.set_modified(False)
            self.emit("modified-changed")
            self.status.set_text(f"Saved {dest.name}")
        dlg.save(self.get_root(), None, done)
