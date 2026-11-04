"""User tools (CBM prg Studio's Tools → User)."""
import pytest

from l64s.project.model import Project
from l64s.usertools import Context, ToolError, UserTool, argv, folder, run


def project(tmp_path):
    return Project(path=tmp_path / "My Game.l64proj", name="My Game", build_list=["main.asm"], executable="game.prg")


def test_presets(tmp_path):
    ctx = Context.make(project(tmp_path), tmp_path / "src dir" / "main.asm")
    t = UserTool("crunch", "exomizer", 'sfx sys -o "[prgDir]/[ProjectName].exo" [prg] -n')
    assert argv(t, ctx) == ["exomizer", "sfx", "sys", "-o", f"{tmp_path}/My Game.exo", str(tmp_path / "game.prg"), "-n"]
    t = UserTool("edit", "gedit", "[CurrentFile]")
    assert argv(t, ctx) == ["gedit", str(tmp_path / "src dir" / "main.asm")]     # one argument, spaces and all
    assert folder(UserTool("x", "ls"), ctx) == tmp_path
    assert folder(UserTool("x", "ls", folder="[CurrentDir]"), ctx) == tmp_path / "src dir"
    with pytest.raises(ToolError, match="no project"):
        argv(UserTool("x", "ls", "[prg]"), Context.make(None, tmp_path / "a.asm"))
    with pytest.raises(ToolError):
        argv(UserTool("x", "ls", 'unclosed "quote'), ctx)


def test_run(tmp_path):
    (tmp_path / "game.prg").write_bytes(b"\x01\x08")
    ctx = Context.make(project(tmp_path))
    ok, out = run(UserTool("size", "wc", "-c [prgName]", capture=True), ctx)
    assert ok and out.split()[0] == "2"
    ok, out = run(UserTool("fail", "sh", '-c "echo bad >&2; exit 3"', capture=True), ctx)
    assert not ok and "bad" in out and "exit code 3" in out
    with pytest.raises(ToolError, match="can't find"):
        run(UserTool("nope", "no-such-program-here"), ctx)
    marker = tmp_path / "started"
    assert run(UserTool("touch", "touch", str(marker)), ctx) == (True, "")     # started on its own
    import time
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.exists()


def test_round_trip():
    t = UserTool("a", "b", "c", "d", True)
    assert UserTool.from_dict(t.to_dict() | {"unknown": 1}) == t
