"""Foldable regions (#region ... #endregion)."""
from l64s.asm.assembler import Assembler, Options
from l64s.basic.pbasic import to_basic
from l64s.basic.renumber import renumber
from l64s.basic.tokenizer import tokenize
from l64s.regions import Region, find_regions, is_marker, wrap


def test_find_regions():
    lines = ["#region setup", "  lda #1", "  #region inner", "  nop", "  #endregion", "#endregion",
             "; #region kick style", "rts", "// #endregion", "#endregion", "#region never closed",
             "10 rem #region basic", "20 print", "30 rem #endregion"]
    assert find_regions(lines) == [Region(0, 5, "setup", 0), Region(2, 4, "inner", 1),
                                   Region(6, 8, "kick style", 0), Region(11, 13, "basic", 1)]   # inside the unclosed one
    assert is_marker("  #REGION x") and is_marker("#endregion") and not is_marker("; #region")


def test_wrap():
    assert wrap(["a", "  b", "c"], 1, 1, "x") == ["a", "#region x", "  b", "#endregion", "c"]
    assert wrap(["a", "  b"], 1, 1, comment="//") == ["a", "  // #region", "  b", "  // #endregion"]


def test_not_code():
    r = Assembler(Options()).assemble_text("*=$c000\n#region init\n        lda #1\n#endregion\n        rts\n")
    assert r.ok and bytes(r.memory[0xC000:r.end]) == bytes([0xA9, 1, 0x60])
    assert tokenize("#region main\n10 print 1\n#endregion\n").prg() == tokenize("10 print 1\n").prg()
    assert to_basic("#region x\nprint 1\n#endregion\n").text == "10 print 1\n"


def test_renumber_keeps_them():
    text, _ = renumber("#region a\n10 print\n15 goto 10\n#endregion\n20 end\n#region b\n#endregion\n")
    assert text == "#region a\n10 print\n20 goto 10\n#endregion\n30 end\n#region b\n#endregion\n"
