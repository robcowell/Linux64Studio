"""l64asm builds every kind of project, as the IDE does: CBM prg Studio projects with the built-in
assembler, Kick Assembler workspaces with Kick Assembler, C projects with cc65."""
import shutil
from pathlib import Path

import pytest

from l64s.asm.cli import main
from l64s.project.build import default_kickass_jar

ROOT = Path(__file__).parent.parent.parent
JAR = default_kickass_jar()


@pytest.mark.skipif(not (JAR and shutil.which("java")), reason="needs Kick Assembler 5 and Java")
def test_a_kick_assembler_workspace(tmp_path, capsys):
    (tmp_path / "main.asm").write_text('*= $0801 "Basic"\n    BasicUpstart(start)\n'
                                       '*= $0810 "Code"\nstart: inc $d020\n    jmp start\n')
    ws = tmp_path / "Ch1.code-workspace"
    ws.write_text('{"folders": [{"path": "."}], "settings": {"kickassembler.startup": "main.asm"}}')
    assert main([str(ws)]) == 0
    built = capsys.readouterr().out.strip().splitlines()[-1]
    assert built.endswith(": built")
    prg = Path(built.removesuffix(": built"))
    assert prg.read_bytes()[:2] == b"\x01\x08" and b"\xee\x20\xd0" in prg.read_bytes()   # inc $d020


@pytest.mark.skipif(not shutil.which("cl65"), reason="cc65 isn't installed")
def test_a_c_project(tmp_path):
    shutil.copytree(ROOT / "examples" / "tutorials" / "5-c", tmp_path / "c")
    assert main(["-q", str(tmp_path / "c" / "score.l64proj")]) == 0
    assert (tmp_path / "c" / "build" / "score.prg").is_file()


def test_a_cbm_prg_studio_project_still_uses_the_built_in_assembler(tmp_path, capsys):
    shutil.copytree(ROOT / "examples" / "tutorials" / "2-assembler", tmp_path / "a")
    assert main([str(tmp_path / "a" / "flash.l64proj")]) == 0
    assert "(38 bytes" in capsys.readouterr().out
    assert (tmp_path / "a" / "flash.prg").is_file()
