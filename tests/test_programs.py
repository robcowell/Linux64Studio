import json

import pytest

from l64s.project.model import (Project, TOOLCHAIN_CC65, add_program, current_program, each_program, load_project,
                                program_names, remove_program, rename_program, select_program)


def project(tmp_path) -> Project:
    p = Project(path=tmp_path / "demos.l64proj", name="demos", toolchain=TOOLCHAIN_CC65,
                build_list=["../lib/ultimate_lib.c", "u-shell.c"], executable="u-shell.prg", assembler_args=["-O"])
    return p


def test_one_program_until_you_add_another(tmp_path):
    p = project(tmp_path)
    assert program_names(p) == ["demos"] and current_program(p) == "demos" and p.programs == []


def test_add_select_and_save(tmp_path):
    p = project(tmp_path)
    add_program(p, "u-term64")
    assert program_names(p) == ["demos", "u-term64"] and current_program(p) == "u-term64"
    assert p.build_list == ["../lib/ultimate_lib.c", "u-shell.c"] and p.executable == "u-term64.prg"
    p.build_list = ["../lib/ultimate_lib.c", "screen_utility.c", "ultimateterm.c"]
    p.assembler_args = ["-O", "-DTERM"]
    assert select_program(p, "demos")
    assert p.build_list == ["../lib/ultimate_lib.c", "u-shell.c"] and p.executable == "u-shell.prg"
    assert p.assembler_args == ["-O"]
    select_program(p, "u-term64")
    assert p.build_list[-1] == "ultimateterm.c" and p.assembler_args == ["-O", "-DTERM"]
    assert not select_program(p, "nope")
    p.save()
    again = load_project(p.path)
    assert program_names(again) == ["demos", "u-term64"] and current_program(again) == "u-term64"
    assert again.build_list[-1] == "ultimateterm.c"
    select_program(again, "demos")
    assert again.executable == "u-shell.prg"
    saved = json.loads(p.path.read_text())
    assert [x["name"] for x in saved["programs"]] == ["demos", "u-term64"]


def test_empty_build_list_and_names(tmp_path):
    p = project(tmp_path)
    add_program(p, "blank", copy_build_list=False)
    assert p.build_list == [] and p.executable == "blank.prg"
    with pytest.raises(ValueError, match="already a program called blank"):
        add_program(p, "blank")
    with pytest.raises(ValueError, match="Enter a name"):
        add_program(p, "  ")


def test_rename_and_remove(tmp_path):
    p = project(tmp_path)
    add_program(p, "two")
    rename_program(p, "two", "second")
    assert program_names(p) == ["demos", "second"] and current_program(p) == "second"
    remove_program(p, "second")                     # the current one: back to the other, and to one program
    assert p.programs == [] and current_program(p) == "demos" and p.executable == "u-shell.prg"
    with pytest.raises(ValueError, match="at least one program"):
        remove_program(p, "demos")


def test_each_program_for_build_all(tmp_path):
    p = project(tmp_path)
    add_program(p, "b", copy_build_list=False)
    p.build_list = ["b.c"]
    progs = each_program(p)
    assert [(n, q.build_list, q.executable) for n, q in progs] == [
        ("demos", ["../lib/ultimate_lib.c", "u-shell.c"], "u-shell.prg"), ("b", ["b.c"], "b.prg")]
    assert current_program(p) == "b" and p.build_list == ["b.c"]           # the project itself is unchanged


def test_renames_and_deletes_reach_every_program(tmp_path):
    from l64s.project import fileops
    p = project(tmp_path)
    add_program(p, "two")                                   # copies the build list
    fileops.rename(p, tmp_path / "u-shell.c", tmp_path / "shell.c")
    assert p.build_list[-1] == "shell.c"
    select_program(p, "demos")
    assert p.build_list[-1] == "shell.c"
    fileops.forget(p, tmp_path / "shell.c")
    select_program(p, "two")
    assert p.build_list == ["../lib/ultimate_lib.c"]


@pytest.mark.skipif(__import__("shutil").which("cl65") is None, reason="cc65 isn't installed")
def test_build_all_puts_every_program_on_the_disk(tmp_path):
    from l64s.disk.image import DiskImage
    from l64s.project.build import build_all
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "util.c").write_text("int twice(int x) { return x * 2; }\n")
    (tmp_path / "one.c").write_text("int twice(int x);\nint main(void) { return twice(1); }\n")
    (tmp_path / "two.c").write_text("int twice(int x);\nint main(void) { return twice(2); }\n")
    (tmp_path / "bad.c").write_text("int main(void) { return oops; }\n")
    p = Project(path=tmp_path / "demos.l64proj", name="one", toolchain=TOOLCHAIN_CC65, output_dir="build",
                build_list=["lib/util.c", "one.c"], executable="one.prg", assembler_args=["-O"],
                disk_image="build/demos.d64", disk_name="DEMOS")
    add_program(p, "two")
    p.build_list = ["lib/util.c", "two.c"]
    res, each = build_all(p)
    assert res.ok, res.log
    assert [(n, r.ok, r.prg.name) for n, r in each] == [("one", True, "one.prg"), ("two", True, "two.prg")]
    assert res.prg.name == "two.prg"                           # the current program's, for Run and Debug
    names = [e.name for e in DiskImage.load(res.disk).entries()]
    assert names == ["ONE", "TWO"] or names == ["one", "two"]
    assert res.run_target(p) == res.prg
    p.run_from_disk = True
    assert res.run_target(p) == f"{res.disk}:two"
    add_program(p, "bad", copy_build_list=False)
    p.build_list = ["bad.c"]
    res, each = build_all(p)
    assert not res.ok and [r.ok for _n, r in each] == [True, True, False]
    assert any(d.message.startswith("bad: ") for d in res.diagnostics) and "2 of 3 programs built" in res.log
