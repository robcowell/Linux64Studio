"""The Source File Converter (Develop 64, Genesis, TASM to CBM prg Studio's dialect)."""
from l64s.asm.assembler import Assembler, Options
from l64s.srcconvert import check, convert, read_develop64, read_genesis, read_tasm

# What each should come to, written in CBM prg Studio's dialect
CBM = """*=$c000
screen = $0400
start   ldx #0
loop    lda msg,x
        beq done
        sta screen,x
        inx
        bne loop
done    rts
msg     text "hello"
        byte 0
table   word start, loop
"""


def assemble(text):
    r = Assembler(Options()).assemble_text(text)
    assert r.ok, [str(d) for d in r.diagnostics]
    return bytes(r.memory[0xC000:r.end])


WANT = assemble(CBM)


def test_tasm():
    src = """; turbo assembler
         *= $c000
screen   = $0400
start    ldx #0
loop:    lda msg,x
         beq done
         sta screen,x
         inx
         bne loop
done     rts
msg      .text "hello"
         .byte 0
table    .word start, loop
         .end
"""
    res = convert(read_tasm(src.encode()), "tasm")
    assert assemble(res.text) == WANT
    assert any(".end" in note for _n, note in res.notes) and not check(res.text)


def test_tasm_extras():
    src = "        .rta start\nstart   rts\n        .include \"lib.s\"\n        .binary \"pic.bin\"\n" \
          "        .macro add\n        adc #\\1\n        .endm\n        .weird 1\n"
    res = convert(read_tasm(src.encode()), "tasm")
    t = res.text
    assert "word start-1" in t and 'incasm "lib.s"' in t and 'incbin "pic.bin"' in t
    assert "defm add" in t and "adc #/1" in t and "endm" in t
    assert any(".weird" in note for _n, note in res.notes) and ".weird 1" in t


def test_develop64_seq():
    """A PETSCII SEQ file: upper-case letters, a CR a line, a control code in a string."""
    lines = ["*=$C000", "SCREEN EQU $0400", "START LDX #0", "LOOP LDA MSG,X", " BEQ DONE", " STA SCREEN,X",
             " INX", " BNE LOOP", "DONE RTS", 'MSG TEXT "HELLO"', " BYT 0", "TABLE WOR START,LOOP"]
    seq = b"\r".join(ln.encode("ascii") for ln in lines) + b"\r"
    got = read_develop64(seq)
    assert got[0] == "*=$c000" and got[9] == 'msg text "hello"'
    assert assemble(convert(got, "develop64").text) == WANT
    assert read_develop64(b'MSG TEXT "\x93HI\x05"\r')[0] == 'msg text "{clear}hi{white}"'
    assert convert(["   ORG $1000"], "develop64").lines[1] == "*=$1000"


def test_genesis_tokenized():
    """Source kept as a tokenized BASIC program: the OR in ORA and AND are crunched."""
    def line(link, number, body):
        return bytes([link & 255, link >> 8, number & 255, number >> 8]) + body + b"\0"
    body = [b"*=$C000", b"START LDA #1", b" \xb0A #2", b" \xaf #3", b" RTS"]   # \xb0 = OR, \xaf = AND
    prog, addr = b"", 0x0801
    chunks = []
    for i, bd in enumerate(body):
        size = 4 + len(bd) + 1
        chunks.append((addr + size, 10 * (i + 1), bd))
        addr += size
    for link, num, bd in chunks:
        prog += line(link, num, bd)
    prg = b"\x01\x08" + prog + b"\0\0"
    got = read_genesis(prg)
    assert got == ["*=$c000", "start lda #1", " ora #2", " and #3", " rts"]
    assert assemble(convert(got, "genesis").text) == bytes([0xA9, 1, 0x09, 2, 0x29, 3, 0x60])


def test_comments_and_layout():
    res = convert(["* a comment", "; another", "lbl:", "verylonglabel nop ; why"], "tasm")
    assert res.lines[1:] == ["; a comment", "; another", "lbl", "verylonglabel nop ; why"]
