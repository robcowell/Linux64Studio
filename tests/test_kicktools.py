"""Kick Assembler tools: hash tables and lists from a selection (CBM prg Studio's examples)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.kicktools import (MULTIPLE, SINGLE, STRING, KickToolError, hashtable, kick_list, parse_items,
                            parse_pairs)

PAIRS = "1 North\n2 South\n3 East\n4 West\n"
JAR = Path.home() / ".local/share/linux64studio/KickAssembler/KickAss.jar"


def test_hashtable_styles():
    p = parse_pairs(PAIRS)
    assert hashtable("DirectionTable", p, quote_values=True) == (
        '.define DirectionTable {\n    .var DirectionTable = Hashtable()\n'
        '    .eval DirectionTable.put(1, "North")\n    .eval DirectionTable.put(2, "South")\n'
        '    .eval DirectionTable.put(3, "East")\n    .eval DirectionTable.put(4, "West")\n}\n')
    assert hashtable("DirectionTable", p, SINGLE, quote_values=True) == \
        '.var DirectionTable = Hashtable().put(1,"North", 2,"South", 3,"East", 4,"West")\n'
    assert hashtable("DirectionTable", p, MULTIPLE, quote_values=True) == \
        '.var DirectionTable = Hashtable().put(1, "North").put(2, "South").put(3, "East").put(4, "West")\n'
    assert hashtable("T", parse_pairs("UP = $91\nDOWN=$11"), SINGLE, quote_keys=True) == \
        '.var T = Hashtable().put("UP",$91, "DOWN",$11)\n'


def test_lists():
    items = parse_items("North\nSouth\nEast\nWest\n")
    assert kick_list("DirectionList", items, quote=True) == (
        '.var DirectionList = List(4)\n.eval DirectionList.set(0, "North")\n.eval DirectionList.set(1, "South")\n'
        '.eval DirectionList.set(2, "East")\n.eval DirectionList.set(3, "West")\n')
    assert kick_list("DirectionList", items, STRING, quote=True) == \
        '.var DirectionList = List().add("North", "South", "East", "West")\n'
    assert kick_list("L", parse_items("$10, $20 // comment\n$30"), STRING, start=2) == \
        ".var L = List().add(0, 0, $10, $20, $30)\n"
    assert kick_list("L", ["a"], start=3).startswith(".var L = List(4)\n.eval L.set(3, a)")
    assert parse_items('"a, b", c') == ['"a, b"', "c"]


def test_errors():
    with pytest.raises(KickToolError):
        parse_pairs("lonely\n")
    with pytest.raises(KickToolError):
        hashtable("2bad", [("1", "2")])
    with pytest.raises(KickToolError):
        parse_items("\n// nothing\n")


@pytest.mark.skipif(not (JAR.exists() and shutil.which("java")), reason="needs Kick Assembler 5")
def test_kick_assembler_takes_them(tmp_path):
    p = parse_pairs(PAIRS)
    items = parse_items("North\nSouth\nEast\nWest")
    src = "\n".join([hashtable("A", p, SINGLE, quote_values=True), hashtable("B", p, MULTIPLE, quote_values=True),
                     hashtable("C", p, quote_values=True), kick_list("D", items, quote=True),
                     kick_list("E", items, STRING, quote=True, start=1),
                     '.print A.get(3) + " " + B.get(4) + " " + D.get(1) + " " + E.get(1) + " " + E.size()'])
    (tmp_path / "t.asm").write_text(src)
    r = subprocess.run(["java", "-jar", str(JAR), "t.asm"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "East West South North 5" in r.stdout
