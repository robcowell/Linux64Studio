from pathlib import Path

from l64s.project import fileops
from l64s.project.model import Project


def project(tmp_path, **kw) -> Project:
    return Project(path=tmp_path / "game.l64proj", name="game", **kw)


def test_check_name(tmp_path):
    (tmp_path / "main.asm").write_text("")
    assert fileops.check_name(tmp_path, "") == "Enter a name"
    assert fileops.check_name(tmp_path, "a/b.asm").startswith("A name can't")
    assert fileops.check_name(tmp_path, "main.asm") == "main.asm already exists"
    assert fileops.check_name(tmp_path, "new.asm") is None
    # renaming a file to itself, or changing only its case, isn't a clash
    assert fileops.check_name(tmp_path, "main.asm", current=tmp_path / "main.asm") is None
    assert fileops.check_name(tmp_path, "Main.asm", current=tmp_path / "main.asm") is None


def test_rename_file_updates_every_setting(tmp_path):
    p = project(tmp_path, build_list=["main.asm", "gfx/sprites.asm"], main_file="main.asm",
                exports={"gfx/sprites.spt": {"bin": "gfx/sprites.bin"}},
                disk_extra_files=[{"file": "main.asm", "name": "SRC", "type": "seq"}],
                music=[{"source": "music/tune.sng", "output": "music.bin"}],
                sprite_pads={"gfx/sprites.spt": {"w": 1}})
    assert fileops.rename(p, tmp_path / "main.asm", tmp_path / "game.asm") == 3
    assert p.build_list == ["game.asm", "gfx/sprites.asm"] and p.main_file == "game.asm"
    assert p.disk_extra_files[0]["file"] == "game.asm"
    assert p.exports == {"gfx/sprites.spt": {"bin": "gfx/sprites.bin"}}       # untouched


def test_rename_folder_moves_everything_inside(tmp_path):
    p = project(tmp_path, build_list=["main.asm", "gfx/sprites.asm"],
                exports={"gfx/sprites.spt": {"bin": "gfx/sprites.bin", "asm": ""}},
                sprite_pads={"gfx/sprites.spt": {"w": 1}}, music=[{"source": "music/tune.sng"}])
    n = fileops.rename(p, tmp_path / "gfx", tmp_path / "graphics")
    assert n == 4
    assert p.build_list == ["main.asm", "graphics/sprites.asm"]
    assert p.exports == {"graphics/sprites.spt": {"bin": "graphics/sprites.bin", "asm": ""}}
    assert list(p.sprite_pads) == ["graphics/sprites.spt"]
    assert p.music[0]["source"] == "music/tune.sng"


def test_rename_handles_windows_separators_from_cbmprj(tmp_path):
    p = project(tmp_path, build_list=["src\\main.asm"])
    fileops.rename(p, tmp_path / "src", tmp_path / "code")
    assert p.build_list == ["code/main.asm"]


def test_forget_drops_inputs_only(tmp_path):
    p = project(tmp_path, build_list=["main.asm", "gfx/a.asm", "b.asm"], main_file="gfx/a.asm",
                exports={"gfx/s.spt": {"bin": "s.bin"}, "c.cst": {"bin": "gfx/c.bin"}},
                music=[{"source": "gfx/t.sng", "output": "m.bin"}, {"source": "x.sng", "output": "gfx/n.bin"}],
                cart_banks=["gfx/bank1.bin", "bank2.bin"])
    assert fileops.forget(p, tmp_path / "gfx") == 5
    assert p.build_list == ["main.asm", "b.asm"] and p.main_file == ""
    assert p.exports == {"c.cst": {"bin": "gfx/c.bin"}}          # its output folder went; the build remakes it
    assert p.music == [{"source": "x.sng", "output": "gfx/n.bin"}]
    assert p.cart_banks == ["bank2.bin"]


def test_build_list(tmp_path):
    p = project(tmp_path, build_list=["a.asm", "b.asm", "c.asm"])
    assert fileops.build_index(p, tmp_path / "b.asm") == 1
    assert fileops.build_add(p, tmp_path / "lib" / "d.asm") and p.build_list[-1] == "lib/d.asm"
    assert not fileops.build_add(p, tmp_path / "a.asm")
    assert fileops.build_move(p, tmp_path / "c.asm", -1) and p.build_list[:3] == ["a.asm", "c.asm", "b.asm"]
    assert not fileops.build_move(p, tmp_path / "a.asm", -1)            # already first
    assert fileops.build_remove(p, tmp_path / "c.asm") and p.build_list == ["a.asm", "b.asm", "lib/d.asm"]
    assert not fileops.build_remove(p, tmp_path / "zzz.asm")


def test_including_lines(tmp_path):
    lib = tmp_path / "lib.asm"
    texts = {str(tmp_path / "main.asm"): 'start   rts\n        incasm "lib.asm"\n  incbin "lib.asm"\n',
             str(tmp_path / "k.asm"): '#import "lib.asm"\n#import "other.asm"\n'}
    assert fileops.including_lines(texts, lib) == [(str(tmp_path / "main.asm"), 2), (str(tmp_path / "main.asm"), 3),
                                                  (str(tmp_path / "k.asm"), 1)]
    assert fileops.including_lines(texts, Path(tmp_path / "nothing.asm")) == []


def test_check_move(tmp_path):
    (tmp_path / "gfx" / "old").mkdir(parents=True)
    (tmp_path / "main.asm").write_text("")
    (tmp_path / "gfx" / "main.asm").write_text("")
    assert fileops.check_move(tmp_path / "main.asm", tmp_path) == ""                 # already there
    assert fileops.check_move(tmp_path / "gfx" / "main.asm", tmp_path) == f"{tmp_path.name} already has something called main.asm"
    assert fileops.check_move(tmp_path / "gfx", tmp_path / "gfx" / "old") == "Can't move gfx into itself"
    assert fileops.check_move(tmp_path / "gfx", tmp_path / "gfx") == "Can't move gfx into itself"
    assert fileops.check_move(tmp_path / "main.asm", tmp_path / "gfx" / "old") is None
