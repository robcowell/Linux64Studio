import threading

import pytest

mido = pytest.importorskip("mido")

from l64s.sid.midi import (Change, MidiInput, MidiUnavailable, MidiVoices, describe, input_names,  # noqa: E402
                           midi_to_note, note_label, pick_device)


def on(note, ch=0, vel=100):
    return mido.Message("note_on", channel=ch, note=note, velocity=vel)


def off(note, ch=0):
    return mido.Message("note_off", channel=ch, note=note)


def test_note_numbers():
    assert midi_to_note(60) == (0, 4)          # middle C is C-4
    assert midi_to_note(69) == (9, 4)          # A-4, 440 Hz
    assert midi_to_note(12) == (0, 0) and midi_to_note(107) == (11, 7)
    assert midi_to_note(11) is None and midi_to_note(108) is None
    assert note_label(52) == "E-3"


def test_channels_pick_voices():
    m = MidiVoices([0, 1, 1])
    assert m.handle(on(52)) == [Change(0, (4, 3), True)]
    assert m.handle(on(64, ch=1)) == [Change(1, (4, 4), True), Change(2, (4, 4), True)]
    assert m.handle(on(64, ch=5)) == []
    assert m.handle(off(52)) == [Change(0, None, False)]
    assert m.playing(0) is None and m.playing(1) == (4, 4)


def test_last_note_priority():
    m = MidiVoices([0, -1, -1])
    m.handle(on(60))
    assert m.handle(on(64)) == [Change(0, (4, 4), True)]
    assert m.handle(off(64)) == [Change(0, (0, 4), False)]     # back to the held C, no retrigger
    assert m.handle(on(67)) == [Change(0, (7, 4), True)]
    assert m.handle(off(60)) == []                              # not the sounding note: nothing changes
    assert m.handle(off(67)) == [Change(0, None, False)]


def test_velocity_zero_is_note_off():
    m = MidiVoices()
    m.handle(on(60))
    assert m.handle(on(60, vel=0)) == [Change(0, None, False)]


def test_out_of_range_and_all_notes_off():
    m = MidiVoices()
    assert m.handle(on(5)) == []
    m.handle(on(60))
    m.handle(on(62))
    assert m.handle(mido.Message("control_change", channel=0, control=123, value=0)) == [Change(0, None, False)]
    assert m.handle(mido.Message("control_change", channel=0, control=7, value=100)) == []


def test_monitor_text():
    assert describe(on(52)) == "Note on   channel 1  E-3 (52)  velocity 100"
    assert describe(off(52, ch=9)) == "Note off  channel 10  E-3 (52)"
    assert describe(on(60, vel=0)).startswith("Note off")
    assert describe(mido.Message("control_change", channel=0, control=1, value=64)).startswith("Control")
    assert describe(mido.Message("clock")) == "Clock"
    assert MidiVoices([0, 2, -1]).mapping_text() == "Voice 1: channel 1   Voice 2: channel 3   Voice 3: off"


def test_pick_device():
    names = ["Midi Through:Midi Through Port-0 14:0", "Keystation 49:Keystation 49 MIDI 1 24:0"]
    assert pick_device(names) == names[1]
    assert pick_device(names[:1]) is None


def test_through_alsa():
    """A note sent to a virtual ALSA port arrives through MidiInput."""
    try:
        out = mido.open_output("L64S midi test", virtual=True)
    except Exception as e:
        pytest.skip(f"no ALSA sequencer: {e}")
    got, arrived = [], threading.Event()
    inp = MidiInput(lambda msg: (got.append(msg), arrived.set()))
    try:
        name = next(n for n in input_names() if "L64S midi test" in n)
        inp.open(name)
        assert inp.is_open
        out.send(on(52, ch=2))
        assert arrived.wait(2)
        assert got[0].type == "note_on" and got[0].note == 52 and got[0].channel == 2
    finally:
        inp.close()
        out.close()
    assert not inp.is_open
    with pytest.raises(MidiUnavailable):
        inp.open("No such port")
