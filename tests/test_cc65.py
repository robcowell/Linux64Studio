import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.cc65dbg import DebugFileError, parses, source_map
from l64s.project import cc65
from l64s.project.model import TOOLCHAIN_CC65, Project

HAVE_CC65 = shutil.which("cl65") is not None


def project(tmp_path, **kw) -> Project:
    return Project(path=tmp_path / "game.l64proj", name="game", toolchain=TOOLCHAIN_CC65, **kw)


# ------------------------------------------------------------------------ messages
def test_compiler_and_assembler_messages(tmp_path):
    out = ("bad.c(3): Error: ';' expected\n"
           "bad.c(5): Warning: 'unused' is defined but never used\n"
           "lib/x.s(2): Error: ':' expected\n"
           "other.c:7: Warning: old style\n")
    d = cc65.parse_output(out, tmp_path)
    assert [(x.severity, Path(x.loc.file).name, x.loc.line, x.message) for x in d] == [
        ("error", "bad.c", 3, "';' expected"), ("warning", "bad.c", 5, "'unused' is defined but never used"),
        ("error", "x.s", 2, "':' expected"), ("warning", "other.c", 7, "old style")]
    assert d[2].loc.file == str((tmp_path / "lib" / "x.s").resolve())


def test_unresolved_external_names_the_c_file(tmp_path):
    out = ("Unresolved external '_g' referenced in:\n  link.s(27)\n  more.s(3)\n"
           "ld65: Error: 1 unresolved external(s) found - cannot create output file\n")
    d = cc65.parse_output(out, tmp_path, {"link.s": tmp_path / "link.c", "more.s": tmp_path / "more.c"})
    assert len(d) == 1 and d[0].severity == "error" and d[0].loc is None
    assert d[0].message.startswith("'g' isn't defined anywhere (used in link.c, more.c)")


def test_other_linker_errors_are_kept(tmp_path):
    d = cc65.parse_output("ld65: Error: Memory area overflow in 'MAIN'\n", tmp_path)
    assert [(x.severity, x.message, x.loc) for x in d] == [("error", "Memory area overflow in 'MAIN'", None)]


# ------------------------------------------------------------------------ commands
def test_commands(tmp_path):
    p = project(tmp_path, build_list=["main.c", "../lib/util.c"], lib_dirs=["../lib"], assembler_args=["-O"],
                output_dir="build", executable="game.prg")
    out = cc65.output_paths(p)
    assert out["prg"] == (tmp_path / "build" / "game.prg").resolve() and out["dbg"].name == "game.dbg"
    obj = cc65.object_for(p, tmp_path / "main.c")
    assert obj == (tmp_path / "build" / "obj" / "main.o").resolve()
    ext = cc65.object_for(p, tmp_path.parent / "lib" / "util.c")
    assert ext.parent.parent.name == "_ext" and ext.name == "util.o"
    cmd = cc65.compile_command(p, tmp_path / "main.c", obj)
    lib = str((tmp_path.parent / "lib").resolve())
    assert cmd[:4] == ["cl65", "-t", "c64", "-g"] and ["-I", lib, "--asm-include-dir", lib] == cmd[4:8]
    assert cmd[8:] == ["-O", "-c", "-o", str(obj), str(tmp_path / "main.c")]
    link = cc65.link_command(p, [obj])
    assert "-Ln" in link and f"--dbgfile,{out['dbg']}" in link and link[-1] == str(obj)


# ------------------------------------------------------------------------ debug file
DBG = """version\tmajor=2,minor=0
info\tcsym=0,file=3,lib=0,line=4,mod=1,scope=1,seg=2,span=3,sym=1,type=1
file\tid=0,name="main.s",size=10,mtime=0x0,mod=0
file\tid=1,name="main.c",size=10,mtime=0x0,mod=0
file\tid=2,name="fast.s",size=10,mtime=0x0,mod=0
line\tid=0,file=0,line=40,span=0
line\tid=1,file=1,line=5,type=1,span=0+1
line\tid=2,file=2,line=3,span=2
line\tid=3,file=1,line=9,type=1,span=3
seg\tid=0,name="CODE",start=0x000810,size=0x0040,addrsize=absolute,type=ro,oname="x.prg",ooffs=15
seg\tid=1,name="DATA",start=0x001000,size=0x0010,addrsize=absolute,type=rw,oname="x.prg",ooffs=79
span\tid=0,seg=0,start=0,size=3
span\tid=1,seg=0,start=8,size=2
span\tid=2,seg=0,start=32,size=4
span\tid=3,seg=1,start=0,size=0
sym\tid=0,name="_main",addrsize=absolute,scope=0,def=0,val=0x810,seg=0,type=lab
"""


def test_debug_file(tmp_path):
    for name in ("main.c", "fast.s"):               # main.s (cc65's own assembly) is gone
        (tmp_path / name).write_text("")
    info = parses(DBG)
    assert info.segs == {0: 0x810, 1: 0x1000} and info.symbols == {0x810: "_main"}
    m = source_map(info, tmp_path)
    c, s = str((tmp_path / "main.c").resolve()), str((tmp_path / "fast.s").resolve())
    assert m == {0x810: (c, 5), 0x818: (c, 5), 0x830: (s, 3)}     # main.s left out, an empty span too
    from l64s.cc65dbg import c_line_spans
    spans = sorted((x.start, x.end, Path(x.file).name, x.line) for x in c_line_spans(info, tmp_path))
    assert spans == [(0x810, 0x813, "main.c", 5), (0x818, 0x81A, "main.c", 5)]     # C lines only
    with pytest.raises(DebugFileError):
        parses("not a debug file")


# ------------------------------------------------------------------------ a real build
@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_real_cl65_build(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "util.h").write_text("int twice(int x);\n")
    (tmp_path / "lib" / "util.c").write_text('#include "util.h"\nint twice(int x) {\n    return x * 2;\n}\n')
    (tmp_path / "main.c").write_text('#include "util.h"\nint n;\nint main(void) {\n    n = twice(21);\n'
                                     '    return 0;\n}\n')
    p = project(tmp_path, build_list=["main.c", "lib/util.c"], lib_dirs=["lib"], assembler_args=["-O"],
                output_dir="build", executable="t.prg")
    objs = []
    for src in p.build_paths():
        obj = cc65.object_for(p, src)
        obj.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(cc65.compile_command(p, src.resolve(), obj), cwd=tmp_path, check=True)
        objs.append(obj)
    subprocess.run(cc65.link_command(p, objs), cwd=tmp_path, check=True)
    out = cc65.output_paths(p)
    assert out["prg"].read_bytes()[:2] == b"\x01\x08"          # loads at $0801, with its BASIC SYS line
    assert not list(tmp_path.glob("*.o")) and not list((tmp_path / "lib").glob("*.o"))
    from l64s.cc65dbg import parse
    m = source_map(parse(out["dbg"]), tmp_path)
    lines = {(Path(f).name, ln) for f, ln in m.values()}
    assert ("main.c", 4) in lines and ("util.c", 3) in lines


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_new_c_project_builds(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import new_project
    p = new_project(tmp_path, "hello", TOOLCHAIN_CC65)
    assert p.build_list == ["main.c"] and p.output_dir == "build" and p.assembler_args == ["-O"]
    res = build_project(p)
    assert res.ok, res.log
    assert res.prg == (tmp_path / "build" / "hello.prg").resolve() and res.labels.name == "hello.lbl"
    assert any(Path(f).name == "main.c" for f, _ln in res.srcmap.values())
    # a second project in the same folder doesn't overwrite main.c and starts with it
    (tmp_path / "main.c").write_text("int main(void) { return 1; }\n")
    q = new_project(tmp_path, "other", TOOLCHAIN_CC65)
    assert q.build_list == ["main.c"] and (tmp_path / "main.c").read_text().startswith("int main")


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_build_errors_and_compile_only(tmp_path):
    from l64s.project.build import build_project
    (tmp_path / "main.c").write_text("void g(void);\nint main(void) {\n    int x = 1\n    return 0;\n}\n")
    p = project(tmp_path, build_list=["main.c"], output_dir="build", executable="t.prg")
    res = build_project(p)
    assert not res.ok and res.prg is None
    err = next(d for d in res.diagnostics if d.severity == "error")
    assert Path(err.loc.file).name == "main.c" and err.loc.line == 4
    (tmp_path / "main.c").write_text("void g(void);\nint main(void) {\n    g();\n    return 0;\n}\n")
    res = build_project(p)
    assert not res.ok and "'g' isn't defined anywhere (used in main.c)" in res.diagnostics[0].message
    res = build_project(p, only_file=tmp_path / "main.c")           # compiles: g is only missing at link
    assert res.ok and res.prg is None and "compiles" in res.log
    assert not build_project(project(tmp_path, output_dir="build")).ok   # nothing on the build list


def test_tasks_in_c():
    from l64s.tasks import scan
    text = 'int x = 1; /* TODO tidy */\nfoo(); // FIXME: off by one\ntodo not a directive in C;\nx = 2; HACK\n'
    assert [(t.line, t.kind, t.text) for t in scan(text, "a.c", c=True)] == [(1, "TODO", "tidy"),
                                                                           (2, "FIXME", "off by one")]


def test_stack_pointer_from_labels(tmp_path):
    (tmp_path / "a.lbl").write_text("al 00FFD2 .BSOUT\nal 000002 .sp\n")
    (tmp_path / "b.lbl").write_text("al 000022 .c_sp\n")
    assert cc65.stack_pointer(tmp_path / "a.lbl") == 2 and cc65.stack_pointer(tmp_path / "b.lbl") == 0x22
    assert cc65.stack_pointer(tmp_path / "none.lbl") == 2


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_the_starfall_example_builds(tmp_path):
    import shutil as sh
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    src = Path(__file__).parent.parent / "examples" / "starfall"
    sh.copytree(src, tmp_path / "starfall", ignore=sh.ignore_patterns("build"))
    p = load_project(tmp_path / "starfall" / "starfall.l64proj")
    res = build_project(p)
    assert res.ok, res.log
    assert res.prg.name == "starfall.prg" and res.disk.name == "starfall.d64"
    assert {"rocks", "score", "state"} <= set(res.c_globals) and res.c_lines and res.asm_lines


@pytest.mark.skipif(not HAVE_CC65, reason="cc65 isn't installed (sudo apt install cc65)")
def test_memory_map_of_a_c_build(tmp_path):
    import shutil as sh
    from l64s import memmap
    from l64s.cc65dbg import memory_map
    from l64s.project.build import build_project
    from l64s.project.model import load_project
    sh.copytree(Path(__file__).parent.parent / "examples" / "starfall", tmp_path / "sf",
                ignore=sh.ignore_patterns("build"))
    p = load_project(tmp_path / "sf" / "starfall.l64proj")
    res = build_project(p)
    m = memory_map(res.prg.read_bytes(), res.c_debug, p.directory, res.prg.name, res.labels)
    kinds = {(s.owner, s.kind) for s in m.segments}
    assert {("main.c", "code"), ("sound.c", "code"), ("main.c", "data"), ("sprites.s", "binary"),
            ("main.c", "variables"), ("c64.lib", "code"), ("C stack", "stack")} <= kinds
    sprites = next(s for s in m.segments if s.kind == "binary")
    assert sprites.size == 192 and sprites.lines[0][1] == 8 and sprites.lines[0][0].endswith("sprites.s")
    main = next(s for s in m.segments if (s.owner, s.kind) == ("main.c", "code"))
    assert main.lines[0][0].endswith("main.c")
    assert m.owner_of(res.c_addresses["rocks"]).kind == "variables"          # (over the start-up code)
    assert all(m.taken(a) for a in range(0xC800, 0xD000))                    # the stack isn't free
    assert all(lo > 0x1800 and hi < 0xC800 or lo >= 0xD000 for lo, hi in m.free_ranges())
    assert not any("written by both" in w.message for w in memmap.warnings(m))


def test_a_segment_s_last_label_runs_to_its_end():
    from l64s.cc65dbg import c_globals
    text = ('version\tmajor=2,minor=0\n'
            'seg\tid=1,name="RODATA",start=0x001000,size=0x00C0,addrsize=absolute,type=ro\n'
            'seg\tid=2,name="BSS",start=0x002000,size=0x0004,addrsize=absolute,type=rw\n'
            'sym\tid=1,name="_sprite_data",addrsize=absolute,val=0x1000,seg=1,type=lab\n'
            'sym\tid=2,name="_a",addrsize=absolute,val=0x2000,seg=2,type=lab\n'
            'sym\tid=3,name="_b",addrsize=absolute,val=0x2002,seg=2,type=lab\n')
    assert c_globals(parses(text)) == {"sprite_data": (0x1000, 192), "a": (0x2000, 2), "b": (0x2002, 2)}
