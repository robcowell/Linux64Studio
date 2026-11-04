import os
import re
from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler, Options
from l64s.basic.tokenizer import tokenize
from l64s.sid.designer import (CodeOptions, Filter, Sound, Voice, freq_register, generate, key_semitone,
                               note_hz, semitone_note)

GOATTRACKER = Path.home() / "goattracker/src/gplay.c"


def tutorial_sound() -> Sound:
    """CBM prg Studio's tutorial 13: voice 1, ADSR 3,5,12,5, pulse, note E octave 3."""
    s = Sound()
    v = s.voices[0]
    v.attack, v.decay, v.sustain, v.release = 3, 5, 12, 5
    v.pulse = True
    v.note, v.octave = 4, 3
    return s


def test_note_frequencies():
    assert note_hz(9, 4) == pytest.approx(440.0)
    assert freq_register(440.0) == 7493            # A-4 on a PAL C64 (985248 Hz)
    assert freq_register(440.0, 1022727) == 7218   # and NTSC


@pytest.mark.skipif(not GOATTRACKER.exists(), reason="GoatTracker source not present")
def test_frequencies_agree_with_goattrackers_table():
    src = GOATTRACKER.read_text()

    def table(name):
        body = re.search(name + r"\[\] = \{(.*?)\};", src, re.S).group(1)
        return [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", body)]

    gt = [lo | hi << 8 for lo, hi in zip(table("freqtbllo"), table("freqtblhi"))][:96]
    for i, value in enumerate(gt):
        assert freq_register(note_hz(i % 12, i // 12)) == pytest.approx(value, rel=0.0005, abs=1), i


def test_registers():
    s = tutorial_sound()
    s.filter = Filter(cutoff=0x5A3, resonance=7, low_pass=True, volume=15)
    s.voices[0].filtered = True
    r = s.registers((True, False, False))
    assert len(r) == 25
    f = freq_register(note_hz(4, 3))
    assert r[0:7] == bytes([f & 0xFF, f >> 8, 0x00, 0x08, 0x41, 0x35, 0xC5])
    assert r[7 + 4] == 0                             # voice 2: no waveform, gate off
    assert r[0x15:0x19] == bytes([0x03, 0xB4, 0x71, 0x1F])


def test_control_bits():
    v = Voice(triangle=True, sawtooth=True, ring=True, sync=True, test=True)
    assert v.control(True) == 0x3F
    assert v.waveform_text() == "triangle + sawtooth (ring mod, sync, test bit)"
    assert Voice().waveform_text() == "no waveform"


def test_save_and_load(tmp_path):
    s = tutorial_sound()
    s.voices[2].frequency = 0x1234
    s.filter.band_pass = True
    s.model = "8580"
    p = tmp_path / "boom.l64sid"
    s.save(p)
    assert Sound.load(p) == s
    with pytest.raises(ValueError):
        Sound.from_json('{"voices": []}')


def test_copy_voice():
    s = tutorial_sound()
    s.voices[1].note = 0
    s.voices[1].copy_from(s.voices[0], notes=False)
    assert s.voices[1].pulse and s.voices[1].attack == 3 and s.voices[1].note == 0
    s.voices[1].copy_from(s.voices[0])
    assert s.voices[1] == s.voices[0]


def test_basic_with_variable_matches_cbm_style():
    code = generate(tutorial_sound(), CodeOptions(comments=False, clear_sid=True))
    lines = code.splitlines()
    assert lines[0] == "10 vb=54272"
    assert lines[1] == "20 for l=vb to vb+24 : poke l,0 : next"
    assert "poke vb+5,53" in code and "poke vb+6,197" in code
    assert lines[-1] == "130 poke vb+4,65"      # the control register, gate on, is last


def test_basic_with_addresses_and_comments():
    code = generate(tutorial_sound(), CodeOptions(use_variable=False, start_line=1000, step=5))
    assert code.splitlines()[0].startswith("1000 poke 54272,")
    assert "1020 poke 54277,53 : rem voice 1 attack 3, decay 5" in code
    assert "rem voice 1 pulse, gate on" in code


def test_basic_tokenizes():
    code = generate(tutorial_sound(), CodeOptions(clear_sid=True))
    result = tokenize(code)
    assert not result.warnings
    assert len(result.lines) == len(code.splitlines())


def test_line_numbers_run_out():
    with pytest.raises(ValueError):
        generate(tutorial_sound(), CodeOptions(start_line=63990, step=10))


def test_nothing_chosen():
    with pytest.raises(ValueError):
        generate(Sound(), CodeOptions(voices=(False, False, False), filter=False, mode_volume=False))


def _assemble(tmp_path, code: str) -> bytes:
    src = tmp_path / "sound.asm"
    src.write_text("*=$c000\n" + code + "        rts\n")
    res = Assembler(Options()).assemble_files([src])
    assert res.ok, res.diagnostics
    return bytes(res.memory[0xC000:0xC000 + 200])


def test_assembler_output_assembles(tmp_path):
    s = tutorial_sound()
    s.voices[1].triangle = True
    code = generate(s, CodeOptions(source="asm", voices=(True, True, False), clear_sid=True))
    assert "SID             = $D400" in code
    assert "sta SID+4" in code
    out = _assemble(tmp_path, code)
    assert out[:9] == bytes([0xA2, 24, 0xA9, 0, 0x9D, 0x00, 0xD4, 0xCA, 0x10]) and out[9] == 0xFA


def test_assembler_reuses_a():
    s = Sound()
    s.voices[0].sustain, s.voices[0].release = 0, 0
    code = generate(s, CodeOptions(source="asm", use_variable=False, comments=False, filter=False,
                                   mode_volume=False, gate=False))
    # frequency high, AD, SR and control can share loads: count them
    assert code.count("lda") < code.count("sta")
    assert "sta $D404" in code


def test_kickass_output():
    code = generate(tutorial_sound(), CodeOptions(source="asm", kickass=True))
    assert code.startswith("// SID sound")
    assert ".const SID = $D400" in code
    assert "    sta SID+4" in code


def test_piano_keys():
    assert key_semitone("Tab") == 0 and key_semitone("ISO_Left_Tab") == 0
    assert key_semitone("1") == 1 and key_semitone("q") == 2 and key_semitone("Q") == 2
    assert key_semitone("u") == 12 and key_semitone("Return") == 23 and key_semitone("BackSpace") == 22
    assert key_semitone("3") is None and key_semitone("a") is None
    assert semitone_note(3, 14) == (2, 4)


@pytest.mark.skipif(os.environ.get("L64S_VICE_TESTS") != "1", reason="set L64S_VICE_TESTS=1 to run VICE")
def test_live_sid_writes_registers():
    from l64s.sid.live import LiveSid
    live = LiveSid()
    live.start()
    try:
        regs = tutorial_sound().registers((True, False, False))
        live.write(regs)
        got = live.mon.read_memory(0xD400, 0xD418)
        live.mon.resume()
        assert got[:7] == regs[:7]
        live.silence()
    finally:
        live.stop()
    assert not live.running


def _run_and_read_sid(prg_path: Path, expect: bytes) -> bytes:
    """Run a program in x64sc and read the SID registers back once the program has set them."""
    import time
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    port = free_port()
    proc = launch(prg_path, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy"])
    try:
        assert wait_for_port(port)
        mon = BinaryMonitor()
        mon.connect(port=port)
        got = b""
        for _ in range(40):
            mon.resume()
            time.sleep(0.5)
            got = mon.read_memory(0xD400, 0xD418)
            if got == expect:
                break
        mon.quit()
        return got
    finally:
        proc.terminate()
        proc.wait(5)


def _expected(sound: Sound) -> bytes:
    regs = bytearray(sound.registers((True, False, False)))
    regs[7:21] = bytes(14)          # voices 2 and 3 cleared, not set
    return bytes(regs)


@pytest.mark.skipif(os.environ.get("L64S_VICE_TESTS") != "1", reason="set L64S_VICE_TESTS=1 to run VICE")
def test_generated_basic_runs_in_vice(tmp_path):
    s = tutorial_sound()
    s.filter = Filter(cutoff=700, resonance=9, low_pass=True, volume=12)
    s.voices[0].filtered = True
    code = generate(s, CodeOptions(clear_sid=True))
    prg = tmp_path / "sound.prg"
    prg.write_bytes(tokenize(code).prg())
    assert _run_and_read_sid(prg, _expected(s)) == _expected(s)


@pytest.mark.skipif(os.environ.get("L64S_VICE_TESTS") != "1", reason="set L64S_VICE_TESTS=1 to run VICE")
def test_generated_assembler_runs_in_vice(tmp_path):
    s = tutorial_sound()
    s.filter = Filter(cutoff=1500, resonance=3, band_pass=True, volume=9)
    code = generate(s, CodeOptions(source="asm", clear_sid=True))
    src = tmp_path / "sound.asm"
    src.write_text("*=$0801\n        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00\n"
                   "*=$080d\n" + code + "        jmp *\n")
    res = Assembler(Options()).assemble_files([src])
    assert res.ok, res.diagnostics
    prg = tmp_path / "sound.prg"
    prg.write_bytes(bytes([0x01, 0x08]) + bytes(res.memory[0x0801:res.end]))
    assert _run_and_read_sid(prg, _expected(s)) == _expected(s)
