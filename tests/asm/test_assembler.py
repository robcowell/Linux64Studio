import pytest

from l64s.asm.assembler import Assembler, Options
from l64s.asm.opcodes import MODE_SIZE, OPCODES


def asm(src: str, **opts):
    r = Assembler(Options(**opts)).assemble_text(src, "/tmp/t.asm")
    return r


def code(src: str, **opts) -> bytes:
    r = asm("*=$1000\n" + src, **opts)
    assert r.ok, "\n".join(map(str, r.diagnostics))
    return r.binary()


# ---------------------------------------------------------------- addressing modes

@pytest.mark.parametrize("line,expected", [
    (" lda #$10", "A9 10"),
    (" lda #-1", "A9 FF"),
    (" lda $10", "A5 10"),
    (" lda $10,x", "B5 10"),
    (" ldx $10,y", "B6 10"),
    (" lda $1234", "AD 34 12"),
    (" lda $1234,X", "BD 34 12"),
    (" lda $1234,Y", "B9 34 12"),
    (" lda $10,y", "B9 10 00"),        # no zp,y for LDA -> absolute,y
    (" lda ($10,x)", "A1 10"),
    (" lda ($10),Y", "B1 10"),
    (" jmp ($1234)", "6C 34 12"),
    (" jmp $1234", "4C 34 12"),
    (" asl", "0A"),
    (" asl a", "0A"),
    (" rol A", "2A"),
    (" rts", "60"),
    (" lda ($10+2)*2", "A5 24"),       # brackets as plain expression
    (" sta $0328", "8D 28 03"),
])
def test_addressing_modes(line, expected):
    assert code(line).hex(" ").upper() == expected


def test_every_documented_opcode_assembles():
    operand = {"imp": "", "acc": "a", "imm": "#1", "zp": "$10", "zpx": "$10,x", "zpy": "$10,y",
               "abs": "$1234", "abx": "$1234,x", "aby": "$1234,y", "ind": "($1234)",
               "izx": "($10,x)", "izy": "($10),y", "rel": "*"}
    for mnem, modes in OPCODES.items():
        for mode, op in modes.items():
            b = code(f" {mnem} {operand[mode]}")
            assert b[0] == op, (mnem, mode)
            assert len(b) == MODE_SIZE[mode], (mnem, mode)


def test_branches():
    b = code("loop nop\n bne loop\n beq fwd\n nop\nfwd rts")
    assert b.hex() == "ead0fdf001ea60"


def test_branch_out_of_range():
    r = asm("*=$1000\n bne far\n dcb 200,0\nfar rts")
    assert not r.ok and "out of range" in r.errors[0].message


# ---------------------------------------------------------------- expressions and labels

def test_numbers_and_operators():
    b = code(" byte $ff, %101, 10, 'a', 2+3*4, (2+3)*4, 1<<3, $f0>>4, $0f&3, 1|2, 7^1, -1")
    assert list(b) == [255, 5, 10, 1, 14, 20, 8, 15, 3, 3, 6, 255]


def test_hilo_default_binds_tightly():
    # Operator HiLo (default): <A+1 is (<A)+1
    assert list(code("A = $12FF\n byte <A+1-$100+1")) == [0x01]


def test_operator_calc():
    # Operator Calc: <A+1 is <(A+1)
    assert list(code("A = $12FF\nOperator Calc\n byte <A+1, >A+1")) == [0x00, 0x13]


def test_hash_inside_expression_is_ignored():
    assert code(" lda #1<<#3").hex() == "a908"


def test_star_is_pc():
    assert code(" jmp *").hex() == "4c0010"


def test_labels_case_insensitive_by_default():
    assert code("Foo = 5\n lda #foo").hex() == "a905"
    r = asm("*=$1000\nFoo = 5\n lda #foo", case_sensitive=True)
    assert not r.ok


def test_label_with_colon_and_col1_label():
    assert code("start: nop\nnext nop\n jmp start\n jmp next").hex() == "eaea4c00104c0110"


def test_forward_reference_to_zero_page_uses_zp():
    # The book defines ZeroPage constants in gameMemory.asm, after the code that uses them.
    assert code(" lda zp\nzp = $fb").hex() == "a5fb"


def test_forward_reference_absolute_when_disabled():
    assert code(" lda zp\nzp = $fb", forward_zp=False).hex() == "adfb00"


def test_local_labels_scoped_to_previous_global():
    b = code("one\n@loop dex\n bne @loop\ntwo\n@loop dey\n bne @loop")
    assert b.hex() == "cad0fd88d0fd"


def test_duplicate_label_is_error():
    r = asm("*=$1000\nfoo nop\nfoo nop")
    assert not r.ok and "already defined" in r.errors[0].message


def test_undefined_label_error_has_location():
    r = asm("*=$1000\n\n lda nowhere")
    assert not r.ok
    assert r.errors[0].loc.line == 3
    assert "nowhere" in r.errors[0].message


def test_invalid_instruction_message():
    r = asm("*=$1000\n frobnicate 1")
    assert "Invalid Instruction or Macro" in r.errors[0].message


# ---------------------------------------------------------------- data directives

def test_byte_word_dcb_text():
    b = code(" byte 1,2\n word $1234\n dcb 3, $ff\n text 'ab@ '")
    assert b.hex() == "01023412ffffff01020020"


def test_text_petscii_option():
    assert code(" text 'ab'", text_encoding="petscii").hex() == "4142"


def test_byte_out_of_range():
    r = asm("*=$1000\n byte 256")
    assert not r.ok


def test_origins_and_padding():
    r = asm("*=$0801\n byte 1\n*=$0805\n byte 2")
    assert r.ok
    assert r.prg().hex() == "0108" + "01000000" + "02"


def test_label_on_own_line_then_origin():
    b = code("tbl\n byte <tbl, >tbl")
    assert b.hex() == "0010"


def test_incbin_unquoted(tmp_path):
    (tmp_path / "data.bin").write_bytes(b"\x01\x02\x03")
    src = tmp_path / "main.asm"
    src.write_text("*=$1000\nincbin data.bin\n incbin \"data.bin\"\n")
    r = Assembler().assemble_files([src])
    assert r.ok and r.binary() == b"\x01\x02\x03\x01\x02\x03"


def test_incasm(tmp_path):
    (tmp_path / "lib.asm").write_text("libfn rts\n")
    (tmp_path / "main.asm").write_text("*=$1000\n jsr libfn\n incasm \"lib.asm\"\n")
    r = Assembler().assemble_files([tmp_path / "main.asm"])
    assert r.ok and r.binary().hex() == "20031060"


def test_multi_file_build_order(tmp_path):
    (tmp_path / "a.asm").write_text("*=$1000\n jsr later\n MYMAC $d020\n")
    (tmp_path / "b.asm").write_text("defm MYMAC\n inc /1\n endm\nlater rts\n")
    r = Assembler().assemble_files([tmp_path / "a.asm", tmp_path / "b.asm"])
    assert r.ok, r.diagnostics
    assert r.binary().hex() == "200610" "ee20d0" "60"


# ---------------------------------------------------------------- macros

MACROS = """\
defm    ADD8_AVA        ; /1 = address, /2 = value, /3 = address
        clc
        lda /1
        adc #/2
        sta /3
        endm

defm    WAITLOOP
@loop   dex
        bne @loop
        endm
"""


def test_macro_parameters():
    b = code(MACROS + " ADD8_AVA $10, 5, $11")
    assert b.hex() == "18a5106905" "8511"


def test_macro_local_labels_are_unique_per_expansion():
    b = code(MACROS + " WAITLOOP\n WAITLOOP")
    assert b.hex() == "cad0fd" "cad0fd"


def test_macro_names_are_case_sensitive_and_dont_clash_with_labels():
    # From the book: macro GAMEBULLETS_COLLIDED and label gameBullets_Collided coexist.
    src = "defm DO_IT\n jsr do_It\n endm\n DO_IT\ndo_It rts"
    assert code(src).hex() == "20031060"


def test_macro_missing_parameter():
    r = asm("*=$1000\n" + MACROS + " ADD8_AVA $10")
    assert not r.ok and "/2" in r.errors[0].message


def test_macro_division_not_mistaken_for_parameter():
    src = "defm HALF\n lda #/1/2\n endm\n HALF 10"
    assert code(src).hex() == "a905"


def test_macro_param_with_offset_and_index():
    src = "defm SETX\n sta /1+250,x\n endm\n SETX $0400"
    assert code(src).hex() == "9dfa04"


def test_conditional_assembly():
    b = code("FLAG = 1\n if FLAG = 1\n nop\n else\n brk\n endif\n ifdef NOPE\n brk\n endif")
    assert b.hex() == "ea"


def test_comments():
    b = code(" nop ; comment\n nop // c comment\n /* block\n brk */ nop\n text 'a;b'")
    assert b.hex() == "eaeaea" + "013b02"


def test_text_quotes_choose_the_encoding():
    assert code(" text 'ab'").hex() == "0102"                 # screen codes
    assert code(' text "ab"').hex() == "4142"                 # PETSCII
    assert code(' text "a", \'a\', 5').hex() == "410105"
    assert code(' text "ab"', text_encoding="screen").hex() == "0102"
