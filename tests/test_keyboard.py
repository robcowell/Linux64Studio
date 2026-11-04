"""The C64 keyboard model behind the Screen Code Builder's virtual keyboard."""
from pathlib import Path

import pytest

from l64s.basic.keyboard import (CBM, CTRL, KERNAL_TABLES, LABELS, LAYOUT, NORMAL, RESTORE, SHIFT, SHIFT_LOCK,
                                 TOGGLE_CASE, decode, keys_for, pc_key)
from l64s.basic.petscii import NAME_TO_CODE

KERNAL = [Path.home() / ".local/share/vice/C64/kernal-901227-03.bin",
          Path.home() / ".local/share/vice/C128/kernal64-901227-03.bin",
          Path("/usr/share/vice/C64/kernal-901227-03.bin"), Path("/usr/lib/vice/C64/kernal-901227-03.bin")]


def key(label):
    return LABELS.index(label)


def test_tables_are_the_kernals():
    rom = next((p for p in KERNAL if p.exists()), None)
    if rom is None:
        pytest.skip("no C64 KERNAL ROM (VICE's) to compare with")
    data = rom.read_bytes()
    for name, table in (("normal", NORMAL), ("shift", SHIFT), ("cbm", CBM), ("ctrl", CTRL)):
        a = KERNAL_TABLES[name] - 0xE000
        assert data[a:a + 64] == table, name


def test_decode():
    assert decode(key("A")) == 0x41 and decode(key("A"), shift=True) == 0xC1
    assert decode(key("A"), cbm=True) == NAME_TO_CODE["cbm-a"]
    assert decode(key("CLR HOME")) == NAME_TO_CODE["home"] and decode(key("CLR HOME"), shift=True) == NAME_TO_CODE["clear"]
    assert decode(key("1"), ctrl=True) == NAME_TO_CODE["black"] and decode(key("8"), ctrl=True) == NAME_TO_CODE["yellow"]
    assert decode(key("1"), cbm=True) == NAME_TO_CODE["orange"] and decode(key("8"), cbm=True) == NAME_TO_CODE["light grey"]
    assert decode(key("9"), ctrl=True) == NAME_TO_CODE["reverse on"] and decode(key("0"), ctrl=True) == 0x92
    assert decode(key("1"), shift=True) == ord("!") and decode(key("F1"), shift=True) == NAME_TO_CODE["f2"]
    assert decode(key("CRSR ⇕"), shift=True) == NAME_TO_CODE["up"]
    assert decode(key("A"), shift=True, cbm=True) == TOGGLE_CASE
    assert decode(key("A"), ctrl=True, cbm=True) == 0x01                       # CTRL wins
    assert decode(key("3"), ctrl=True, shift=True) == NAME_TO_CODE["red"]
    assert decode(key("A"), ctrl=True) == 0x01 and decode(key("0"), shift=True) == 0x30
    assert decode(key("SHIFT")) is None and decode(RESTORE) is None and decode(SHIFT_LOCK) is None


def test_layout():
    codes = [k.code for k in LAYOUT]
    assert sorted(c for c in codes if c < 64) == list(range(64))             # every key, once
    assert SHIFT_LOCK in codes and RESTORE in codes
    rows = {}
    for k in LAYOUT:
        if k.x < 17:
            rows.setdefault(k.y, []).append(k)
    for y, ks in rows.items():
        ks.sort(key=lambda k: k.x)
        for a, b in zip(ks, ks[1:]):
            assert a.x + a.w <= b.x + 1e-9, (y, a.label, b.label)             # no overlaps


def test_typing_on_a_pc():
    assert pc_key("a") == (key("A"), False) and pc_key("A") == (key("A"), True)
    assert pc_key("!") == (key("1"), True) and pc_key("[") == (key(":"), True)
    assert pc_key("^") == (key("↑"), False) and pc_key("£") == (key("£"), False)
    assert pc_key("?") == (key("/"), True) and pc_key("é") is None
    assert keys_for(NAME_TO_CODE["clear"]) == [(key("CLR HOME"), "shift"), (key("CLR HOME"), "cbm")]   # as the KERNAL has it
