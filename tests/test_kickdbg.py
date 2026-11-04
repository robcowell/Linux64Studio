from pathlib import Path

import pytest

from l64s.analyser import analyse
from l64s.kickdbg import instructions, kind_of, memory_map, parse, source_map, symbols
from l64s.memmap import from_prg

BOOK = Path(__file__).parent / "book" / "c64edition-main" / "ChaptersKickAss"

DUMP = """<C64debugger version="1.0">
   <Sources values="INDEX,FILE">
      0,KickAss.jar:/include/autoinclude.asm
      1,{main}
   </Sources>
   <Segment name="Default" dest="" values="START,END,FILE_IDX,LINE1,COL1,LINE2,COL2">
      <Block name="Basic Upstart">
         $0801,$080c,0,40,2,40,6
      </Block>
      <Block name="Default">
         $c000,$c001,1,3,9,3,15
         $c002,$c004,1,4,9,4,17
         $c005,$c005,1,5,9,5,11
         $c006,$c008,1,6,6,6,20
         $c000,$c001,1,3,9,3,15
      </Block>
   </Segment>
   <Labels values="SEGMENT,ADDRESS,NAME,START,END,FILE_IDX,LINE1,COL1,LINE2,COL2">
      Default,$c000,start,1,2,1,1,2,6
      Default,$c006,table,1,6,1,6,1,6
      Default,$c005,loop,1,5,1,5,1,5
      Default,$c005,again,1,5,1,5,1,5
      Default,$d000,loop,1,9,1,9,1,9
   </Labels>
</C64debugger>
"""
SOURCE = """// test
*=$c000
start:  lda #1
        sta $d020
loop:   rts
table:  .byte 1, 2, 3
"""


@pytest.fixture
def dump(tmp_path):
    main = tmp_path / "main.asm"
    main.write_text(SOURCE)
    d = tmp_path / "main.dbg"
    d.write_text(DUMP.format(main=main))
    prg = tmp_path / "main.prg"
    prg.write_bytes(bytes([0x00, 0xC0, 0xA9, 0x01, 0x8D, 0x20, 0xD0, 0x60, 1, 2, 3]))
    return parse(d, tmp_path), prg, main


def test_parse(dump):
    info, _prg, main = dump
    assert info.sources[0] is None and info.sources[1] == str(main.resolve())
    assert len(info.entries) == 5                        # the repeated entry is dropped
    assert info.entries[1].start == 0xC000 and info.entries[1].line == 3


def test_source_map_and_symbols(dump):
    info, _prg, main = dump
    m = source_map(info)
    assert m[0xC000] == (str(main.resolve()), 3) and m[0xC004] == (str(main.resolve()), 4)
    assert 0x0801 not in m                               # Kick Assembler's own BASIC upstart
    s = symbols(info)
    assert s[0xC000] == "start" and s[0xC006] == "table"
    assert s[0xC005] == "again"                          # "loop" is used twice, "again" once


def test_kinds_instructions_and_memory_map(dump):
    info, prg, main = dump
    mem = from_prg(prg.read_bytes()).memory
    kinds = [kind_of(info, e, mem) for e in info.entries if e.file]
    assert kinds == ["code", "code", "code", "data"]
    ins = instructions(info, mem)
    assert [(i[1], i[2], i[3]) for i in ins] == [(3, "lda", "imm"), (4, "sta", "abs"), (5, "rts", "imp")]
    mm = memory_map(prg.read_bytes(), info, "main.prg")
    assert [(s.start, s.end, s.owner, s.kind) for s in mm.segments] == [
        (0xC000, 0xC005, "main.asm", "code"), (0xC006, 0xC008, "main.asm", "data")]


def test_analyser_uses_the_last_build(dump):
    info, prg, main = dump
    r = analyse([main], kickass=True, kick_build=(info, prg))
    assert r.method == "assembled (the last build)"
    assert [(i.mnemonic, i.mode) for i in r.instrs] == [("lda", "imm"), ("sta", "abs"), ("rts", "imp")]
    # an edited, unsaved file isn't what was built: read the text instead, and say why
    r2 = analyse([main], {str(main): SOURCE + "        nop\n"}, kickass=True, kick_build=(info, prg))
    assert r2.method.startswith("source text (main.asm has changed")
    # open in an editor but unchanged is still up to date
    r3 = analyse([main], {str(main): SOURCE}, kickass=True, kick_build=(info, prg))
    assert r3.method == "assembled (the last build)"


@pytest.mark.skipif(not (BOOK / "chapter16" / "output" / "gameMain.dbg").exists(), reason="book not present")
def test_book_dump_matches_its_program():
    out = BOOK / "chapter16" / "output"
    info = parse(out / "gameMain.dbg", BOOK)
    mem = from_prg((out / "gameMain.prg").read_bytes()).memory
    code = [e for e in info.entries if e.file and kind_of(info, e, mem) == "code"]
    ins = instructions(info, mem)
    assert len(code) > 1000 and len(ins) == len(code)    # every code line decodes to an opcode of its length
    for f in {e.file for e in info.entries if e.file}:
        assert Path(f).exists()                          # Windows paths found in the local copy
    mm = memory_map((out / "gameMain.prg").read_bytes(), info, "gameMain.prg")
    assert {s.kind for s in mm.segments} == {"code", "data", "binary"}


def test_build_parses_the_dump(tmp_path):
    """A Kick Assembler build passes -debugdump and reads the .dbg it writes."""
    import json
    import stat
    from l64s.project.build import build_project
    from l64s.project.model import TOOLCHAIN_KICKASS, Project
    main = tmp_path / "main.asm"
    main.write_text(SOURCE)
    (tmp_path / "KickAss.jar").write_bytes(b"")
    fake = tmp_path / "fakejava"
    fake.write_text(f"""#!/usr/bin/env python3
import json, sys, pathlib
args = sys.argv[1:]
pathlib.Path("{tmp_path}/args.json").write_text(json.dumps(args))
odir = pathlib.Path(args[args.index("-odir") + 1])
(odir / "main.prg").write_bytes(bytes([0x00, 0xC0, 0xA9, 0x01, 0x8D, 0x20, 0xD0, 0x60, 1, 2, 3]))
(odir / "main.dbg").write_text({DUMP.format(main=main)!r})
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    p = Project(path=tmp_path / "t.l64proj", name="t", toolchain=TOOLCHAIN_KICKASS, main_file="main.asm",
                kickass_jar="KickAss.jar")
    res = build_project(p, java=str(fake))
    assert res.ok and "-debugdump" in json.loads((tmp_path / "args.json").read_text())
    assert res.kick_debug is not None and res.srcmap[0xC002] == (str(main.resolve()), 4)
