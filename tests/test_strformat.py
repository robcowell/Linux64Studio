import pytest

from l64s.asm.assembler import Assembler, Options as AsmOptions
from l64s.asm.charset import char_to_petscii, char_to_screencode
from l64s.basic.tokenizer import tokenize
from l64s.strformat import (FormatError, Options, assembler, basic, find, length, lower, mixed, replace, split,
                            upper)

TEXT = "{white}welcome to the caves of doom. press fire to begin your quest!"


def test_length_counts_c64_characters():
    assert length("{white}ab") == 3
    assert length("{3 down}x") == 4
    with pytest.raises(FormatError):
        length("{white")


def test_split_keeps_words_and_codes():
    pieces = split(TEXT, 20)
    assert "".join(pieces) == TEXT
    assert all(length(p) <= 20 for p in pieces)
    assert pieces[0] == "{white}welcome to the "
    assert pieces[1].startswith("caves")
    hard = split("abcdefgh", 3, words=False)
    assert hard == ["abc", "def", "gh"]
    assert split("abcdefghij", 4) == ["abcd", "efgh", "ij"]          # one long word is split anyway
    with pytest.raises(FormatError):
        split("x", 0)


def test_case():
    assert upper("hi {white}there") == "HI {white}THERE"
    assert lower("HI {WHITE}THERE") == "hi {WHITE}there"
    assert mixed("HELLO THERE. WHO? me!") == "Hello there. Who? Me!"


def test_find_and_replace():
    assert [(m.position, m.text) for m in find("a cat, a hat", r"[ch]at")] == [(2, "cat"), (9, "hat")]
    assert replace("a cat, a hat", r"[ch]at", "dog") == ("a dog, a dog", 2)
    with pytest.raises(FormatError, match="Invalid"):
        find("x", "(")


def test_basic_output():
    code, warnings = basic(TEXT, Options(width=20, start_line=100, step=5, variable="T$"))
    lines = code.splitlines()
    assert lines[0] == '100 t$="{white}welcome to the "'
    assert lines[1].startswith('105 t$=t$+"caves')
    assert not warnings
    assert not tokenize(code).warnings
    no_init, _ = basic("abc def", Options(width=4, initialise=False))
    assert no_init.splitlines() == ['10 a$=a$+"abc "', '20 a$=a$+"def"']


def test_basic_errors_and_warnings():
    with pytest.raises(FormatError, match="chr"):
        basic('say "hi"', Options())
    with pytest.raises(FormatError):
        basic("x", Options(variable="a"))
    _, warnings = basic("x" * 300, Options(width=100))
    assert any("80" in w for w in warnings) and any("255" in w for w in warnings)


def _assemble(text: str) -> bytes:
    res = Assembler(AsmOptions()).assemble_text("*=$c000\n" + text)
    assert res.ok, [str(d) for d in res.diagnostics]
    return bytes(res.memory[0xC000:res.end])


def test_assembler_petscii():
    out = assembler(TEXT, Options(width=20, label="intro"))
    assert out.splitlines()[0] == "intro"
    assert out.splitlines()[1] == '        text $05, "welcome to the "'
    data = _assemble(out)
    plain = TEXT.replace("{white}", "")
    assert data == bytes([0x05]) + bytes(char_to_petscii(c) for c in plain)


def test_assembler_screen_codes():
    out = assembler("press fire", Options(petscii=False))
    assert out.strip() == "text 'press fire'"
    assert _assemble(out) == bytes(char_to_screencode(c) for c in "press fire")
    with pytest.raises(FormatError, match="PETSCII"):
        assembler("{white}x", Options(petscii=False))


def test_quotes_inside():
    out = assembler('say "hi"', Options())
    assert _assemble(out) == bytes(char_to_petscii(c) for c in 'say "hi"')


def test_kickass():
    out = assembler("{white}hello", Options(kickass=True))
    lines = out.splitlines()
    assert lines[0] == '    .encoding "petscii_mixed"'
    assert lines[1] == "    .byte $05" and lines[2] == '    .text "hello"'
    assert lines[-1].startswith('    .encoding "screencode_mixed"')
    assert assembler("hi", Options(kickass=True, petscii=False)).splitlines() == [
        '    .encoding "screencode_mixed"', '    .text "hi"']


def _screen_after(prg: bytes, tmp_path) -> bytes | None:
    import os
    import time
    if os.environ.get("L64S_VICE_TESTS") != "1":
        pytest.skip("set L64S_VICE_TESTS=1 to run VICE")
    from l64s.emu.binmon import BinaryMonitor
    from l64s.emu.vice import free_port, launch, wait_for_port
    p = tmp_path / "s.prg"
    p.write_bytes(prg)
    port = free_port()
    proc = launch(p, monitor_port=port, extra_args=["-warp", "-sounddev", "dummy"])
    try:
        assert wait_for_port(port)
        mon = BinaryMonitor()
        mon.connect(port=port)
        screen = None
        for _ in range(40):
            mon.resume()
            time.sleep(0.5)
            if mon.read_memory(2, 2)[0] == 42:
                screen = mon.read_memory(0x0400, 0x07E7)
                break
        mon.quit()
        return screen
    finally:
        proc.terminate()
        proc.wait(5)


MESSAGE = "the quick brown fox jumps over the lazy dog, again and again."
# what the message looks like in screen memory (the upper case set): letters 1-26, the rest as they are
SHOWN = bytes(char_to_screencode(c) for c in MESSAGE)


def test_basic_output_prints_in_vice(tmp_path):
    code, _ = basic("{clear}" + MESSAGE, Options(width=16))
    prg = tokenize(code + "500 print a$;\n510 poke 2,42\n").prg()
    screen = _screen_after(prg, tmp_path)
    assert screen[:len(SHOWN)] == SHOWN


def test_petscii_text_prints_in_vice(tmp_path):
    data = assembler("{clear}" + MESSAGE, Options(width=16, label="message"))
    src = ("*=$0801\n        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00\n*=$080d\n"
           "        ldx #0\nloop    lda message,x\n        jsr $ffd2\n        inx\n"
           f"        cpx #{length(MESSAGE) + 1}\n        bne loop\n        lda #42\n        sta 2\n"
           "        jmp *\n" + data)
    res = Assembler(AsmOptions()).assemble_text(src)
    assert res.ok, [str(d) for d in res.diagnostics]
    screen = _screen_after(bytes([1, 8]) + bytes(res.memory[0x0801:res.end]), tmp_path)
    assert screen[:len(SHOWN)] == SHOWN
