import json
import os
import stat
from pathlib import Path

from l64s.project.build import build_events, build_project, expand_presets
from l64s.project.model import TOOLCHAIN_KICKASS, Project, load_project


def cbm_project(tmp_path: Path, **kw) -> Project:
    (tmp_path / "main.asm").write_text("*=$0801\n        byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,0,0,0\n"
                                       "*=$080d\n        rts\n")
    p = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.asm"], executable="t.prg", **kw)
    return p


def test_presets(tmp_path):
    p = cbm_project(tmp_path)
    prg = tmp_path / "t.prg"
    assert expand_presets("[prg] [prgName] [ProjectName] [ProjectDir]", p, prg) == \
        f"{prg} t.prg t {tmp_path}"


def test_events_run_in_order_with_echo_and_disabled_lines(tmp_path):
    p = cbm_project(tmp_path)
    ok, log = build_events(p, ["echo Crunching [prgName]...", "; touch never", "touch made.txt",
                               'sh -c "echo hi > hello.txt"'], tmp_path / "t.prg", "Post-build")
    assert ok
    assert log[0] == "Crunching t.prg..."
    assert (tmp_path / "made.txt").exists() and not (tmp_path / "never").exists()
    assert (tmp_path / "hello.txt").read_text() == "hi\n"


def test_failing_and_missing_commands(tmp_path):
    p = cbm_project(tmp_path)
    ok, log = build_events(p, ["false", "touch after"], None, "Pre-build")
    assert not ok and "exit code 1" in log[-1] and not (tmp_path / "after").exists()
    ok, log = build_events(p, ["no-such-command-l64s"], None, "Pre-build")
    assert not ok and "not found" in log[-1]


def test_build_runs_pre_and_post_and_puts_the_crunched_file_on_disk(tmp_path):
    p = cbm_project(tmp_path, pre_build=["touch pre.txt"],
                    post_build=['sh -c "cat [prg] [prg] > [prgDir]/t.big"'],
                    disk_image="t.d64", disk_program="t.big", disk_file_name="t")
    res = build_project(p)
    assert res.ok, res.log
    assert (tmp_path / "pre.txt").exists()
    big = (tmp_path / "t.big").read_bytes()
    assert big == (tmp_path / "t.prg").read_bytes() * 2
    from l64s.disk.image import DiskImage
    d = DiskImage.load(tmp_path / "t.d64")
    assert d.read_file("t") == big


def test_a_disk_made_after_the_build_is_run_and_not_written(tmp_path):
    p = cbm_project(tmp_path, post_build=['sh -c "echo mine > made.d64"'], disk_image="made.d64",
                    disk_from_post_build=True, run_from_disk=True)
    res = build_project(p)
    assert res.ok, res.log
    assert (tmp_path / "made.d64").read_text() == "mine\n"
    assert res.disk == (tmp_path / "made.d64").resolve()
    assert res.run_target(p) == res.disk
    assert "made by the post-build commands" in res.log


def test_a_disk_the_post_build_commands_did_not_make_fails_the_build(tmp_path):
    res = build_project(cbm_project(tmp_path, disk_image="made.d64", disk_from_post_build=True))
    assert not res.ok and any("wasn't made" in str(d) for d in res.diagnostics)


def test_post_build_only_after_a_good_build(tmp_path):
    p = cbm_project(tmp_path, post_build=["touch post.txt"])
    (tmp_path / "main.asm").write_text("*=$c000\n        lda nosuchlabel\n")
    res = build_project(p)
    assert not res.ok and not (tmp_path / "post.txt").exists()
    p.post_build_always = True
    build_project(p)
    assert (tmp_path / "post.txt").exists()


def test_failing_post_build_fails_the_build(tmp_path):
    res = build_project(cbm_project(tmp_path, post_build=["false"]))
    assert not res.ok and any("Post-build" in str(d) for d in res.diagnostics)


def fake_java(tmp_path: Path) -> Path:
    """Stands in for java -jar KickAss.jar: records its arguments and writes the .prg it's asked for."""
    script = tmp_path / "fakejava"
    script.write_text("""#!/usr/bin/env python3
import json, sys, pathlib
args = sys.argv[1:]
pathlib.Path(__file__).with_name("args.json").write_text(json.dumps(args))
odir = pathlib.Path(args[args.index("-odir") + 1])
name = args[args.index("-o") + 1] if "-o" in args else pathlib.Path(args[2]).with_suffix(".prg").name
(odir / name).write_bytes(b"\\x01\\x08\\x60")
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_kickass_uses_the_projects_jar_args_and_output_name(tmp_path):
    (tmp_path / "game.asm").write_text("// game\n")
    (tmp_path / "KickAss.jar").write_bytes(b"not run")
    p = Project(path=tmp_path / "g.l64proj", name="g", toolchain=TOOLCHAIN_KICKASS, main_file="game.asm",
                executable="game_debug.prg", kickass_jar="KickAss.jar", assembler_args=["-define", "DEBUG"])
    res = build_project(p, kickass_jar="/elsewhere/KickAss.jar", java=str(fake_java(tmp_path)))
    assert res.ok, res.log
    args = json.loads((tmp_path / "args.json").read_text())
    assert args[:3] == ["-jar", str((tmp_path / "KickAss.jar").resolve()), str(tmp_path / "game.asm")]
    assert args[args.index("-o") + 1] == "game_debug.prg"
    assert args[-2:] == ["-define", "DEBUG"]
    assert res.prg == (tmp_path / "game_debug.prg").resolve()


def test_new_fields_save_and_load(tmp_path):
    p = cbm_project(tmp_path, kickass_jar="KickAss.jar", assembler_args=["-define", "DEBUG"],
                    pre_build=["echo hi"], post_build=["exomizer sfx basic -n [prg] -o [prg].exo"],
                    post_build_always=True, disk_program="t.prg.exo", disk_from_post_build=True)
    p.save()
    q = load_project(p.path)
    for f in ("kickass_jar", "assembler_args", "pre_build", "post_build", "post_build_always", "disk_program",
              "disk_from_post_build"):
        assert getattr(q, f) == getattr(p, f), f
