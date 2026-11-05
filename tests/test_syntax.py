from l64s.syntax import C, CA65, CBM, KICK, number, origin, resolve, table


def test_resolve():
    assert resolve() == CBM and resolve(kickass=True) == KICK and resolve("c") == C and resolve("ca65", True) == CA65


def test_tables_in_each_syntax():
    data = [0x00, 0x18, 0xFF]
    assert table(CBM, "ship", data, comment_text="the ship") == \
        "; the ship\nship\n        byte $00, $18, $FF\n"
    assert table(KICK, "ship", data) == "ship:\n    .byte $00, $18, $FF\n"
    assert table(CA65, "ship", data, per_line=2) == "ship:\n        .byte $00, $18\n        .byte $FF\n"
    assert table(C, "ship", data, per_line=2, comment_text="the ship") == (
        "// the ship\nconst unsigned char ship[3] = {\n    0x00, 0x18,\n    0xFF\n};\n")


def test_c_types_and_numbers():
    assert table(C, "wave", [-1, 5], width=2, radix="dec").startswith("const int wave[2] = {\n    -1, 5\n")
    assert table(C, "w", [1000], width=2).splitlines()[1] == "    0x03E8"
    assert table(C, "s", [-3]).startswith("const signed char s[1]")
    assert number(5, radix="bin") == "%00000101" and number(5, radix="bin", syntax=C) == "0x05"
    assert table(C, "", [1]).startswith("const unsigned char data[1]")


def test_row_comments():
    assert table(CBM, "chars", [1, 2], per_line=1, row_comments=["char 0", "char 1"]).splitlines()[1:] == [
        "        byte $01 ; char 0", "        byte $02 ; char 1"]
    assert table(C, "chars", [1, 2], per_line=1, row_comments=["char 0", "char 1"]).splitlines()[1] == \
        "    0x01,    /* char 0 */"


def test_origin():
    assert origin(CBM, 0xC000) == "*=$C000" and origin(KICK, 0xC000) == "*= $C000"
    assert origin(C, 0xC000).startswith("// ") and origin(CA65, 0xC000).startswith("; ")


def test_generators_write_c_and_ca65():
    from l64s.basic.screencodes import to_petscii_bytes
    from l64s.binconv import Binary, to_asm_data
    from l64s.datagen import Options, source
    from l64s.gfx.charset import Charset
    from l64s.gfx.sprite import Sprite, SpriteSet
    assert to_petscii_bytes(b"\x48\x49", "msg", syntax=C).splitlines()[1] == "const unsigned char msg[3] = {"
    assert to_petscii_bytes(b"\x48", "msg", syntax=CA65).splitlines()[1:] == ["msg:", "        .byte $48, $00"]
    assert "byte $48" in to_petscii_bytes(b"\x48", "msg")                          # CBM as before
    b = Binary(0xC000, b"", "tune.bin")
    text = to_asm_data(b, "tune", syntax=C)
    assert text.startswith("// (at $C000") and "const unsigned char tune[2] = {" in text
    d = source(Options(function="x*2", start=0, end=3, type="word", label="twice", syntax=C, comment=False))
    assert d == "const unsigned int twice[4] = {\n    0x0000, 0x0002, 0x0004, 0x0006\n};\n"
    f = source(Options(function="x/2", start=0, end=1, type="float", label="halves", syntax=CA65, comment=False))
    assert f.splitlines()[1] == "halves:" and len(f.splitlines()[2].split(",")) == 10      # 2 floats, 5 bytes each
    sprites = SpriteSet([Sprite(description="ship"), Sprite(multi=True)])
    c_src = sprites.to_source("sprites", C)
    assert c_src.splitlines()[1] == "const unsigned char sprites[128] = {" and "/* sprite 0: ship */" in c_src
    assert "/* sprite 1 (multicolour) */" in c_src
    cs = Charset()
    assert cs.to_source("font", 2, CA65).splitlines()[2].endswith("; char 0")


def test_string_formatter_in_c_and_ca65():
    from l64s.strformat import Options, assembler
    text = assembler("Hi there{clear}", Options(width=8, label="msg", syntax=C))
    lines = text.splitlines()
    assert lines[0] == "// PETSCII, for CHROUT" and lines[1] == "const unsigned char msg[9] = {"
    assert lines[2] == "    0xC8, 0x49, 0x20,    /* Hi  */" and lines[3].endswith("0x93    /* there{clear} */")
    assert lines[-1] == "};"
    sc = assembler("ab", Options(label="t", syntax=CA65, petscii=False)).splitlines()
    assert sc[1:] == ["t:", "        .byte $01, $02 ; ab"]


def test_code_writers_for_c_and_ca65():
    from l64s.disassembler import Session
    from l64s.binconv import Binary, disassemble_to_source
    from l64s.screencalc import results
    from l64s.sid.designer import CodeOptions, Sound, generate_asm
    from l64s.snippets import to_ca65
    from l64s.vicmem import Layout, setup_code
    c = setup_code(Layout(), syntax=C)
    assert "#define SCREENRAM   0x0400" in c and "*(unsigned char *)0xD018 = " in c
    assert "lda $DD00" in setup_code(Layout(), syntax=CA65) and "VICBANK         = $00" in setup_code(Layout(), syntax=CA65)
    r = {x.label: x.text for x in results(1, 2, syntax=C)}
    assert r["C"].startswith("*(unsigned char *)0x042A = 1;") and "Assembler" not in r
    sid = generate_asm(Sound(), CodeOptions(source="asm", syntax=C))
    assert "#define SID_REGS ((unsigned char *)0xD400)" in sid and "SID_REGS[1] = 0x11;" in sid
    assert "lda #$11" in generate_asm(Sound(), CodeOptions(source="asm", syntax=CA65))
    src = disassemble_to_source(Binary(0xC000, b"\xa9\x00\x4c\x00\xc0"), [0xC000], syntax=C).source
    assert "        .org $C000" in src and "LC000:  lda #$00" in src and "jmp LC000" in src
    assert to_ca65("start   lda #1  ; go\n        byte 1, 2\nSCREEN = $0400\n*=$c000\n        text \"hi\"").splitlines() == [
        "start:      lda #1  ; go", "            .byte 1, 2", "SCREEN = $0400", "            .org $c000",
        '            .byte "hi"']


import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402


def _all_outputs(sx):
    """What every code tool writes in ``sx``: (name, text, is a statement rather than a declaration)."""
    from l64s.basic.screencodes import to_petscii_bytes
    from l64s.binconv import Binary, to_asm_data
    from l64s.datagen import Options as DOpts, source
    from l64s.gfx.charset import Charset
    from l64s.gfx.paths import GenOptions, ScreenPath, generate
    from l64s.gfx.sprite import Sprite, SpriteSet
    from l64s.screencalc import results
    from l64s.sid.designer import CodeOptions, Sound, generate_asm
    from l64s.strformat import Options as SOpts, assembler
    from l64s.vicmem import Layout, setup_code
    yield "sprites", SpriteSet([Sprite(description="ship")]).to_source("sprites", sx), False
    yield "chars", Charset().to_source("font", 4, sx), False
    yield "petscii", to_petscii_bytes(b"\x48\x49", "msg", syntax=sx), False
    yield "binary", to_asm_data(Binary(0xC000, b"\x01\x02"), "blob", syntax=sx), False
    yield "sine", source(DOpts(label="sine", syntax=sx)), False
    yield "words", source(DOpts(label="wave", type="word", function="x*300-1000", end=20, syntax=sx)), False
    yield "floats", source(DOpts(label="halves", type="float", function="x/2", end=3, syntax=sx)), False
    yield "path", generate(ScreenPath(points=[(10, 20), (30, 40)]), GenOptions(label="route", syntax=sx))[0], False
    yield "text", assembler("Hello there{clear}", SOpts(width=8, label="greeting", syntax=sx)), False
    if sx == C:
        yield "vic", setup_code(Layout(), syntax=sx), True
        yield "sid", generate_asm(Sound(), CodeOptions(source="asm", syntax=sx)), True
        yield "screen", {r.label: r.text for r in results(3, 4, syntax=sx)}["C"], True


@pytest.mark.skipif(shutil.which("cl65") is None, reason="cc65 isn't installed")
def test_every_c_output_compiles(tmp_path):
    decls, stmts = [], []
    for name, text, statement in _all_outputs(C):
        (stmts if statement else decls).append(f"/* --- {name} */\n{text}")
    body = "\n".join(s for s in stmts if not s.lstrip().startswith("#")) 
    # (#defines go before the function; the rest inside it)
    defines = [ln for s in stmts for ln in s.splitlines() if ln.startswith("#define")]
    code = [ln for s in stmts for ln in s.splitlines() if not ln.startswith("#define")]
    src = "#include <string.h>\n" + "\n".join(decls) + "\n" + "\n".join(defines) + \
          "\nvoid setup(void) {\n" + "\n".join(code) + "\n}\n"
    (tmp_path / "all.c").write_text(src)
    r = subprocess.run(["cl65", "-t", "c64", "-c", "-o", str(tmp_path / "all.o"), str(tmp_path / "all.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr + "\n" + src


@pytest.mark.skipif(shutil.which("ca65") is None, reason="cc65 isn't installed")
def test_every_ca65_output_assembles(tmp_path):
    from l64s.snippets import to_ca65
    parts = [text for _name, text, _s in _all_outputs(CA65)]
    parts.append(to_ca65("loop    lda #1\n        sta $d020\n        jmp loop\n        byte 1, 2"))
    from l64s.vicmem import Layout, setup_code
    parts.append(setup_code(Layout(), syntax=CA65))
    (tmp_path / "all.s").write_text("\n".join(parts) + "\n")
    r = subprocess.run(["ca65", "-t", "c64", "-o", str(tmp_path / "all.o"), str(tmp_path / "all.s")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
