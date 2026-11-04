"""SID sound designer: three voices (waveform, envelope, pulse width, note), the filter and the
volume, as SID register values, saved as settings and turned into BASIC or assembler.

SID registers ($D400 = 54272), per voice v at $D400 + 7*v:
  +0/+1  frequency low/high      register = Hz * 16777216 / clock
  +2/+3  pulse width low/high (12 bits)
  +4     control: noise $80, pulse $40, sawtooth $20, triangle $10, test $08, ring $04, sync $02, gate $01
  +5     attack (high nibble), decay (low)
  +6     sustain (high nibble), release (low)
  $D415/$D416  filter cutoff: bits 0-2, then bits 3-10
  $D417  resonance (high nibble), filter voice 3/2/1 (bits 2-0), external input (bit 3)
  $D418  voice 3 off $80, high pass $40, band pass $20, low pass $10, volume (low nibble)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SID_BASE = 0xD400
PAL_CLOCK = 985248
NTSC_CLOCK = 1022727
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
WAVEFORMS = [("triangle", 0x10), ("sawtooth", 0x20), ("pulse", 0x40), ("noise", 0x80)]

# How long each envelope setting takes (from the C64 Programmer's Reference Guide).
ATTACK_MS = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]
DECAY_MS = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]

FORMAT = "linux64studio-sid"
EXTENSION = ".l64sid"


def note_hz(note: int, octave: int) -> float:
    """Equal temperament, A4 = 440 Hz; octave 4 starts at middle C."""
    midi = 12 * (octave + 1) + note
    return 440.0 * 2 ** ((midi - 69) / 12)


def freq_register(hz: float, clock: int = PAL_CLOCK) -> int:
    return max(0, min(0xFFFF, round(hz * 16777216 / clock)))


def register_hz(value: int, clock: int = PAL_CLOCK) -> float:
    return value * clock / 16777216


def note_name(note: int, octave: int) -> str:
    return f"{NOTE_NAMES[note]}-{octave}"


@dataclass
class Voice:
    note: int = 0                  # 0-11, C to B
    octave: int = 4                # 0-7
    frequency: int | None = None   # a raw frequency register value, instead of the note
    triangle: bool = False
    sawtooth: bool = False
    pulse: bool = False
    noise: bool = False
    ring: bool = False             # ring modulation by the previous voice (3 for voice 1)
    sync: bool = False             # hard sync to the previous voice
    test: bool = False
    pulse_width: int = 2048        # 0-4095; 2048 is a square wave
    attack: int = 0
    decay: int = 0
    sustain: int = 15
    release: int = 0
    filtered: bool = False         # route this voice through the filter

    def freq(self, clock: int = PAL_CLOCK) -> int:
        if self.frequency is not None:
            return self.frequency & 0xFFFF
        return freq_register(note_hz(self.note, self.octave), clock)

    def control(self, gate: bool) -> int:
        v = 0
        for name, bit in WAVEFORMS:
            if getattr(self, name):
                v |= bit
        return v | (0x08 if self.test else 0) | (0x04 if self.ring else 0) | (0x02 if self.sync else 0) | int(gate)

    @property
    def has_waveform(self) -> bool:
        return any(getattr(self, n) for n, _ in WAVEFORMS)

    def waveform_text(self) -> str:
        text = " + ".join(n for n, _ in WAVEFORMS if getattr(self, n)) or "no waveform"
        extra = [label for name, label in (("ring", "ring mod"), ("sync", "sync"), ("test", "test bit"))
                 if getattr(self, name)]
        return f"{text} ({', '.join(extra)})" if extra else text

    def copy_from(self, other: "Voice", notes: bool = True) -> None:
        for k, v in asdict(other).items():
            if notes or k not in ("note", "octave", "frequency"):
                setattr(self, k, v)


@dataclass
class Filter:
    cutoff: int = 1024             # 0-2047
    resonance: int = 0             # 0-15
    low_pass: bool = False
    band_pass: bool = False
    high_pass: bool = False
    voice3_off: bool = False
    external: bool = False         # filter the external audio input
    volume: int = 15               # 0-15

    def mode_volume(self) -> int:
        return ((0x80 if self.voice3_off else 0) | (0x40 if self.high_pass else 0) | (0x20 if self.band_pass else 0)
                | (0x10 if self.low_pass else 0) | (self.volume & 0x0F))

    def mode_text(self) -> str:
        modes = [n for n, on in (("low pass", self.low_pass), ("band pass", self.band_pass),
                                 ("high pass", self.high_pass)) if on]
        return " + ".join(modes) or "no filter mode"


@dataclass
class Sound:
    voices: list[Voice] = field(default_factory=lambda: [Voice(), Voice(), Voice()])
    filter: Filter = field(default_factory=Filter)
    ntsc: bool = False
    model: str = "6581"            # or "8580"; how it's played, not part of the code

    @property
    def clock(self) -> int:
        return NTSC_CLOCK if self.ntsc else PAL_CLOCK

    def routing(self) -> int:
        return (sum(1 << i for i, v in enumerate(self.voices) if v.filtered) | (0x08 if self.filter.external else 0)
                | ((self.filter.resonance & 0x0F) << 4))

    def voice_registers(self, i: int, gate: bool) -> list[int]:
        v = self.voices[i]
        f = v.freq(self.clock)
        pw = v.pulse_width & 0x0FFF
        return [f & 0xFF, f >> 8, pw & 0xFF, pw >> 8, v.control(gate),
                ((v.attack & 15) << 4) | (v.decay & 15), ((v.sustain & 15) << 4) | (v.release & 15)]

    def registers(self, gates: tuple[bool, bool, bool] = (False, False, False)) -> bytes:
        """All 25 write registers, $D400-$D418."""
        out: list[int] = []
        for i in range(3):
            out += self.voice_registers(i, gates[i])
        c = self.filter.cutoff & 0x7FF
        out += [c & 7, c >> 3, self.routing(), self.filter.mode_volume()]
        return bytes(out)

    # ------------------------------------------------------------------ settings files
    def to_json(self) -> str:
        return json.dumps({"format": FORMAT, "version": 1, **asdict(self)}, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "Sound":
        d = json.loads(text)
        if d.get("format") != FORMAT:
            raise ValueError("This isn't a Linux64Studio SID sound file")
        vf = Voice.__dataclass_fields__
        voices = [Voice(**{k: v for k, v in vd.items() if k in vf}) for vd in d.get("voices", [])][:3]
        while len(voices) < 3:
            voices.append(Voice())
        ff = Filter.__dataclass_fields__
        flt = Filter(**{k: v for k, v in d.get("filter", {}).items() if k in ff})
        return cls(voices, flt, bool(d.get("ntsc", False)), str(d.get("model", "6581")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: str | Path) -> "Sound":
        return cls.from_json(Path(path).read_text())


# ---------------------------------------------------------------------- code generation

@dataclass
class CodeOptions:
    voices: tuple[bool, bool, bool] = (True, False, False)
    filter: bool = True            # cutoff, resonance and routing
    mode_volume: bool = True       # $D418
    source: str = "basic"          # "basic" or "asm"
    start_line: int = 10
    step: int = 10
    use_variable: bool = True      # POKE VB+1,20 rather than POKE 54273,20
    variable: str = ""             # default VB in BASIC, SID in assembler
    comments: bool = True
    clear_sid: bool = False
    gate: bool = True              # start the sound (gate on) at the end
    kickass: bool = False


@dataclass
class _Write:
    offset: int
    value: int
    comment: str


def _writes(sound: Sound, opts: CodeOptions) -> list[_Write]:
    """The register writes, in a safe order: each voice's frequency, pulse and envelope, then the
    filter and volume, and the control registers (with the gate) last so the sound starts as set."""
    out: list[_Write] = []
    controls: list[_Write] = []
    for i, on in enumerate(opts.voices):
        if not on:
            continue
        v = sound.voices[i]
        r = sound.voice_registers(i, opts.gate)
        b = 7 * i
        f = v.freq(sound.clock)
        what = f"${f:04X}" if v.frequency is not None else f"{note_name(v.note, v.octave)}, ${f:04X}"
        out += [_Write(b, r[0], f"voice {i + 1} frequency low ({what})"),
                _Write(b + 1, r[1], f"voice {i + 1} frequency high")]
        if v.pulse:
            out += [_Write(b + 2, r[2], f"voice {i + 1} pulse width low ({v.pulse_width & 0xFFF})"),
                    _Write(b + 3, r[3], f"voice {i + 1} pulse width high")]
        out += [_Write(b + 5, r[5], f"voice {i + 1} attack {v.attack}, decay {v.decay}"),
                _Write(b + 6, r[6], f"voice {i + 1} sustain {v.sustain}, release {v.release}")]
        controls.append(_Write(b + 4, r[4], f"voice {i + 1} {v.waveform_text()}"
                                            + (", gate on" if opts.gate else ", gate off")))
    if opts.filter:
        c = sound.filter.cutoff & 0x7FF
        voices = [str(i + 1) for i, v in enumerate(sound.voices) if v.filtered] + (["ext"] if sound.filter.external else [])
        out += [_Write(0x15, c & 7, f"filter cutoff low ({c})"), _Write(0x16, c >> 3, "filter cutoff high"),
                _Write(0x17, sound.routing(), f"resonance {sound.filter.resonance}, filter "
                                              + (("voice " + ",".join(voices)) if voices else "no voices"))]
    if opts.mode_volume:
        f = sound.filter
        out.append(_Write(0x18, f.mode_volume(), f"{f.mode_text()}{', voice 3 off' if f.voice3_off else ''}, "
                                                 f"volume {f.volume}"))
    return out + controls


def generate(sound: Sound, opts: CodeOptions) -> str:
    if not any(opts.voices) and not opts.filter and not opts.mode_volume:
        raise ValueError("Choose at least one voice, the filter, or the volume to generate code for")
    return generate_basic(sound, opts) if opts.source == "basic" else generate_asm(sound, opts)


def generate_basic(sound: Sound, opts: CodeOptions) -> str:
    """A BASIC program in listing notation (lower case keywords, as the BASIC editor uses)."""
    var = (opts.variable or "vb").lower()
    lines: list[str] = []
    n = opts.start_line

    def add(text: str) -> None:
        nonlocal n
        if n > 63999:
            raise ValueError("The line numbers run past 63999: use a smaller start line or step")
        lines.append(f"{n} {text}")
        n += opts.step

    def addr(off: int) -> str:
        if opts.use_variable:
            return var if off == 0 else f"{var}+{off}"
        return str(SID_BASE + off)

    if opts.use_variable:
        add(f"{var}={SID_BASE}" + (" : rem start of the sid chip" if opts.comments else ""))
    if opts.clear_sid:
        lo, hi = (var, f"{var}+24") if opts.use_variable else (str(SID_BASE), str(SID_BASE + 24))
        add(f"for l={lo} to {hi} : poke l,0 : next" + (" : rem clear the sid chip" if opts.comments else ""))
    for w in _writes(sound, opts):
        add(f"poke {addr(w.offset)},{w.value}" + (f" : rem {w.comment}" if opts.comments else ""))
    return "\n".join(lines) + "\n"


def generate_asm(sound: Sound, opts: CodeOptions) -> str:
    c = "//" if opts.kickass else ";"
    ind = "    " if opts.kickass else "        "
    var = opts.variable or "SID"
    out: list[str] = []
    if opts.comments:
        out.append(f"{c} SID sound (made by Linux64Studio's SID Designer)")
    if opts.use_variable:
        out.append(f".const {var} = ${SID_BASE:04X}" if opts.kickass else f"{var:<15} = ${SID_BASE:04X}")

    def addr(off: int) -> str:
        if opts.use_variable:
            return var if off == 0 else f"{var}+{off}"
        return f"${SID_BASE + off:04X}"

    def line(code: str, comment: str = "") -> None:
        out.append(f"{ind}{code:<16}{c} {comment}" if comment and opts.comments else f"{ind}{code}")

    if opts.clear_sid:
        line("ldx #24", "clear the SID chip")
        line("lda #0")
        line(f"sta {addr(0)},x")
        line("dex")
        line("bpl *-4")
    a = 0 if opts.clear_sid else None
    for w in _writes(sound, opts):
        if a != w.value:
            line(f"lda #${w.value:02X}")
            a = w.value
        line(f"sta {addr(w.offset)}", w.comment)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- the PC keyboard as a piano

# Two octaves, as CBM prg Studio maps them: white keys on the Tab row, black keys on the number row.
WHITE_KEYS = ["Tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "bracketleft", "bracketright", "Return"]
BLACK_KEYS = {"1": 1, "2": 3, "4": 6, "5": 8, "6": 10, "8": 13, "9": 15, "minus": 18, "equal": 20, "BackSpace": 22}
WHITE_SEMITONES = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23]


def key_semitone(keyname: str) -> int | None:
    """Semitones above the keyboard's base C for a GDK key name, or None."""
    if keyname in BLACK_KEYS:
        return BLACK_KEYS[keyname]
    k = keyname if len(keyname) > 1 else keyname.lower()
    if k == "ISO_Left_Tab":
        k = "Tab"
    if k == "KP_Enter":
        k = "Return"
    if k in WHITE_KEYS:
        return WHITE_SEMITONES[WHITE_KEYS.index(k)]
    return None


def semitone_note(base_octave: int, semitone: int) -> tuple[int, int]:
    """(note, octave) for a semitone above C of the base octave."""
    return semitone % 12, base_octave + semitone // 12
