import datetime

import pytest

from l64s.memtools import ExportOptions, MemToolError, count, export, find, keywords, parse_find

MEM = bytearray(0x10000)
MEM[0x1000:0x1005] = b"\xa9\x01\x8d\x20\xd0"         # lda #1 : sta $d020
MEM[0x2000:0x2005] = bytes([8, 5, 12, 12, 15])     # "hello" in screen codes
MEM[0x3000:0x3005] = b"HELLO"                      # and in PETSCII
MEM[0x4000:0x4002] = b"\xa9\x01"


def test_parse_find():
    assert parse_find("$A9 1") == b"\xa9\x01"
    assert parse_find("169,1, %10001101 0x20") == b"\xa9\x01\x8d\x20"
    assert parse_find('"hello"') == b"HELLO"
    assert parse_find('"hello"', strings="screen") == bytes([8, 5, 12, 12, 15])
    assert parse_find("'ab' $0d") == b"AB\r"
    for bad in ("", "$1G", "256", '"open', '""'):
        with pytest.raises(MemToolError):
            parse_find(bad)


def test_find_and_wrap():
    p = parse_find("$a9 $01")
    assert find(MEM, p) == 0x1000
    assert find(MEM, p, 0x1001) == 0x4000                  # the next one
    assert find(MEM, p, 0x4001) == 0x1000                  # wraps round
    assert find(MEM, p, 0x4001, wrap=False) is None
    assert find(MEM, parse_find('"hello"', "screen")) == 0x2000
    assert find(MEM, parse_find('"hello"')) == 0x3000
    assert count(MEM, p) == 2


def test_keywords():
    now = datetime.datetime(2012, 2, 27, 15, 9, 50)
    hdr = "// Start address %start%, end address %end%, size %size%, on %date%"
    # the example in CBM prg Studio's help
    assert keywords(hdr, 0x22, 0x24, now) == "// Start address $0022, end address $0024, size 3, on 27/02/2012 15:09:50"
    assert keywords("%START%", 1, 2, now) == "%START%"      # case-sensitive, as in CBM prg Studio


def test_export_hex():
    text = export(MEM, ExportOptions(start=0x1000, end=0x1004, per_row=3, row_lead="  byte ", header="; %size% bytes"))
    assert text.splitlines() == ["; 5 bytes", "  byte $A9, $01, $8D", "  byte $20, $D0"]


def test_export_bases():
    o = ExportOptions(start=0x1000, end=0x1001, prefix="", separator=" ")
    assert export(MEM, o).strip() == "A9 01"
    o.base, o.prefix = 10, ""
    assert export(MEM, o).strip() == "169 1"
    o.base, o.prefix = 8, "0"
    assert export(MEM, o).strip() == "0251 0001"
    o.base, o.prefix = 2, "%"
    assert export(MEM, o).strip() == "%10101001 %00000001"
    o.pad = False
    assert export(MEM, o).strip() == "%10101001 %1"


def test_export_rows_and_trailer():
    text = export(MEM, ExportOptions(start=0x2000, end=0x2004, per_row=2, prefix="0x", separator=",",
                                     row_lead="{", row_trail="},", footer="// end %end%"))
    assert text.splitlines() == ["{0x08,0x05},", "{0x0C,0x0C},", "{0x0F},", "// end $2004"]


def test_export_errors():
    with pytest.raises(MemToolError):
        export(MEM, ExportOptions(start=0x2000, end=0x1000))
    with pytest.raises(MemToolError):
        export(MEM, ExportOptions(per_row=0))
