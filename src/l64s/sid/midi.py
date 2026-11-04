"""MIDI input for the SID Designer, as in CBM prg Studio: each SID voice listens on a MIDI channel,
and note on/off messages on that channel play the voice at that note.

MIDI note 60 is middle C, which is C-4 here (octave 4 starts at middle C, as in GoatTracker), so
note n is (n % 12, n // 12 - 1). The designer's octaves run 0-7: MIDI notes 12-107.

Each voice is monophonic with last-note priority: pressing a second key on the same channel
moves the voice to it, and letting go goes back to a key that's still held.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .designer import NOTE_NAMES

LOWEST, HIGHEST = 12, 107              # C-0 .. B-7
THROUGH = "Midi Through"


def midi_to_note(n: int) -> tuple[int, int] | None:
    """(note 0-11, octave 0-7) for a MIDI note number, or None if the designer can't play it."""
    if not LOWEST <= n <= HIGHEST:
        return None
    return n % 12, n // 12 - 1


def note_label(n: int) -> str:
    return f"{NOTE_NAMES[n % 12]}-{n // 12 - 1}"


def describe(msg) -> str:
    """The MIDI monitor's line for a message (a mido.Message or anything with .type etc.)."""
    t = msg.type
    ch = getattr(msg, "channel", None)
    where = f"channel {ch + 1}" if ch is not None else ""
    if t == "note_on" and msg.velocity:
        return f"Note on   {where}  {note_label(msg.note)} ({msg.note})  velocity {msg.velocity}"
    if t in ("note_on", "note_off"):
        return f"Note off  {where}  {note_label(msg.note)} ({msg.note})"
    if t == "control_change":
        return f"Control   {where}  controller {msg.control} = {msg.value}"
    if t == "pitchwheel":
        return f"Pitch bend  {where}  {msg.pitch}"
    if t == "program_change":
        return f"Program   {where}  {msg.program}"
    return t.replace("_", " ").capitalize() + (f"  {where}" if where else "")


@dataclass
class Change:
    voice: int
    note: tuple[int, int] | None      # (note, octave) to play, or None: gate off
    retrigger: bool                   # a new key press (restart the envelope), not a return to a held key


@dataclass
class MidiVoices:
    """Which note each SID voice is playing from MIDI."""
    channels: list[int] = field(default_factory=lambda: [0, 1, 2])   # MIDI channel (0-15) per voice; -1 = off
    held: list[list[int]] = field(default_factory=lambda: [[], [], []])

    def voices_for(self, channel: int) -> list[int]:
        return [v for v, ch in enumerate(self.channels) if ch == channel]

    def playing(self, voice: int) -> tuple[int, int] | None:
        return midi_to_note(self.held[voice][-1]) if self.held[voice] else None

    def handle(self, msg) -> list[Change]:
        """Update for a message; returns what changed."""
        t = msg.type
        if t not in ("note_on", "note_off"):
            if t == "control_change" and msg.control in (120, 123):      # all sound / all notes off
                return self._clear(self.voices_for(msg.channel))
            return []
        note_on = t == "note_on" and msg.velocity > 0
        out = []
        for v in self.voices_for(msg.channel):
            held = self.held[v]
            if note_on:
                if midi_to_note(msg.note) is None:
                    continue
                if msg.note in held:
                    held.remove(msg.note)
                held.append(msg.note)
                out.append(Change(v, midi_to_note(msg.note), True))
            elif msg.note in held:
                top = held[-1] == msg.note
                held.remove(msg.note)
                if top:
                    out.append(Change(v, self.playing(v), False))
        return out

    def _clear(self, voices) -> list[Change]:
        out = []
        for v in voices:
            if self.held[v]:
                self.held[v].clear()
                out.append(Change(v, None, False))
        return out

    def all_off(self) -> list[Change]:
        return self._clear(range(3))

    def mapping_text(self) -> str:
        return "   ".join(f"Voice {v + 1}: " + (f"channel {ch + 1}" if ch >= 0 else "off")
                          for v, ch in enumerate(self.channels))


# ---------------------------------------------------------------------- ports (mido + python-rtmidi)

class MidiUnavailable(RuntimeError):
    pass


def _mido():
    try:
        import mido
        mido.get_input_names()             # loads the rtmidi backend
        return mido
    except ImportError as e:
        raise MidiUnavailable("MIDI needs mido and python-rtmidi: sudo apt install python3-mido python3-rtmidi") \
            from e
    except Exception as e:                 # the backend failed (no ALSA sequencer?)
        raise MidiUnavailable(f"Couldn't use MIDI: {e}") from e


def input_names() -> list[str]:
    """The MIDI inputs, without duplicates."""
    return list(dict.fromkeys(_mido().get_input_names()))


def pick_device(names: list[str], exclude: tuple[str, ...] = ()) -> str | None:
    """The input CBM prg Studio's Detect Device would find: the first that isn't ALSA's Midi Through
    port (or one of ours)."""
    for n in names:
        if THROUGH not in n and not any(x in n for x in exclude):
            return n
    return None


class MidiInput:
    """One open MIDI input; callback(msg) runs on rtmidi's thread."""

    def __init__(self, callback):
        self.callback = callback
        self.port = None
        self.name: str | None = None

    def open(self, name: str) -> None:
        self.close()
        mido = _mido()
        try:
            self.port = mido.open_input(name, callback=self.callback)
        except Exception as e:
            raise MidiUnavailable(f"Couldn't open {name}: {e}") from e
        self.name = name

    def close(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.name = None

    @property
    def is_open(self) -> bool:
        return self.port is not None and not self.port.closed
