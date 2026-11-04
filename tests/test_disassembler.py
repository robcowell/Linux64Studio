from pathlib import Path

import pytest

from l64s.asm.assembler import Assembler
from l64s.binconv import Binary, load_binary
from l64s.disassembler import Session, SessionError, sidecar_path

KERNAL = Path("/usr/share/vice/C64/kernal-901227-03.bin")
CH17 = Path(__file__).parent / "book" / "c64edition-main" / "prgs" / "chapter17.prg"


def reassembles(s: Session, tmp_path) -> bool:
    r = Assembler().assemble_text(s.source(), str(tmp_path / "re.asm"))
    assert r.ok, [str(e) for e in r.errors[:5]]
    return r.start == s.binary.start and r.binary() == s.binary.data


@pytest.mark.skipif(not KERNAL.is_file(), reason="VICE's KERNAL ROM image not installed")
def test_kernal_rom_round_trip_with_c64_names(tmp_path):
    k = KERNAL.read_bytes()
    vec = lambda a: k[a - 0xE000] | (k[a - 0xE000 + 1] << 8)  # noqa: E731
    s = Session(Binary(0xE000, k, "kernal"), [vec(0xFFFC), vec(0xFFFE), vec(0xFFFA)] + list(range(0xFF81, 0xFFF6, 3)))
    src = s.source()
    assert reassembles(s, tmp_path)
    assert "CHROUT  jmp (IBSOUT)" in src and "IBSOUT          = $0326" in src
    assert "CIAICR          = $DC0D" in src


def program() -> Binary:
    # $C000: jsr $C006 / jmp $C000 / data / $C006: lda $D020 / sta $FB / rts / data
    return Binary(0xC000, bytes([0x20, 0x06, 0xC0, 0x4C, 0x00, 0xC0, 0xAD, 0x20, 0xD0, 0x85, 0xFB, 0x60,
                                 0x01, 0x02, 0x03]), "t.prg")


def test_marks_labels_and_comments_still_reassemble(tmp_path):
    s = Session(program(), [0xC000])
    s.set_label(0xC006, "readBorder")
    s.set_label(0x00FB, "temp")
    s.set_comment(0xC000, "main loop")
    s.mark_data(0xC003, 0xC005)       # make the jmp data
    src = s.source()
    assert "jsr readBorder" in src and "lda EXTCOL" in src and "sta temp" in src
    assert "temp            = $FB" in src and "EXTCOL          = $D020" in src
    assert "; main loop" in src and "byte $4C, $00, $C0" in src
    assert reassembles(s, tmp_path)
    s.mark_code(0xC003)
    assert "jmp LC000" in s.source() and reassembles(s, tmp_path)


def test_label_rules():
    s = Session(program(), [0xC000])
    for bad in ("lda", "a", "X", "9lives", "two words", "byte", "LC003"):
        with pytest.raises(SessionError):
            s.set_label(0xC006, bad)
    s.set_label(0xC006, "ok_name")
    with pytest.raises(SessionError, match="already"):
        s.set_label(0xC000, "OK_NAME")              # the assembler ignores case
    s.set_label(0xC006, "")
    assert 0xC006 not in s.labels


def test_own_label_beats_a_c64_name(tmp_path):
    s = Session(program(), [0xC000])
    s.set_label(0xC006, "EXTCOL")                   # same name as $D020's
    src = s.source()
    assert "EXTCOL          = $D020" not in src and "lda $D020" in src
    assert reassembles(s, tmp_path)


def test_xrefs_and_targets():
    s = Session(program(), [0xC000])
    refs = s.xrefs()
    assert refs[0xC006] == [0xC000] and refs[0xC000] == [0xC003] and refs[0xD020] == [0xC006]
    ln = next(x for x in s.lines() if x.addr == 0xC000)
    assert ln.target == 0xC006


def test_kickass_output():
    s = Session(Binary(0xC000, bytes([0x0A, 0xAD, 0x20, 0xD0, 0x60, 0xFF])), [0xC000])
    src = s.source(kickass=True)
    assert ".const EXTCOL = $D020" in src and "*= $C000" in src and "LC000:" in src
    assert "        asl\n" in src.replace("LC000:  ", "        ") and ".byte $FF" in src


def test_session_json_round_trip(tmp_path):
    s = Session(program(), [0xC000])
    s.set_label(0xC006, "readBorder")
    s.set_comment(0xC009, "save it")
    s.mark_data(0xC00C, 0xC00E)
    s2 = Session(program(), [0xC000])
    s2.apply_json(s.to_json())
    assert s2.source() == s.source()
    assert sidecar_path(Path("x/game.prg")) == Path("x/game.prg.l64dis")


@pytest.mark.skipif(not CH17.is_file(), reason="book downloads not present")
def test_chapter17_annotated_round_trip(tmp_path):
    b = load_binary(CH17)
    s = Session(b, [0x0810])
    s.set_label(0x0888, "gameLoop")
    s.set_comment(0x0810, "start")
    s.mark_data(0x3000, 0x3B1E)                     # sprites and characters
    assert reassembles(s, tmp_path)
    s.trace = False
    assert reassembles(s, tmp_path)
