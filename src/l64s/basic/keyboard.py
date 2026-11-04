"""The C64 keyboard, for the Screen Code Builder's virtual keyboard: where each key is, and the
PETSCII code it types alone, with SHIFT, with the Commodore key and with CTRL.

The codes are the KERNAL's own keyboard decode tables (901227-03, at $EB81, $EBC2, $EC03 and
$EC78), indexed by the key's place in the keyboard matrix, so the virtual keyboard types exactly
what a C64 would. As in the KERNAL ($EB48), CTRL wins over the Commodore key, which wins over
SHIFT, and SHIFT with the Commodore key switches between the two character sets.
"""
from __future__ import annotations

from dataclasses import dataclass

# The KERNAL's tables: 64 matrix codes each ($FF = nothing).
NORMAL = bytes.fromhex("140d1d8885868711335741345a5345013552443643465458375947384248555639494a304d4b4f4e2b504c2d"
                       "2e3a402c5c2a3b13013d5e2f315f043220025103")
SHIFT = bytes.fromhex("948d9d8c898a8b9123d7c124dad3c50125d2c426c3c6d4d827d9c728c2c8d5d629c9ca30cdcbcfcedbd0ccdd"
                      "3e5bba3ca9c05d93013dde3f215f0422a002d183")
CBM = bytes.fromhex("948d9d8c898a8b9196b3b097adaeb10198b2ac99bcbba3bd9ab7a59bbfb4b8be29a2b530a7a1b9aaa6afb6dc3e"
                    "5ba43ca8df5d93013dde3f815f0495a002ab83")
CTRL = bytes.fromhex("ffffffffffffffff1c17019f1a1305ff9c12041e030614181f19079e0208151612090a920d0b0f0eff100cff"
                     "ff1b00ff1cff1dffff1f1eff9006ff05ffff11ff")
KERNAL_TABLES = {"normal": 0xEB81, "shift": 0xEBC2, "cbm": 0xEC03, "ctrl": 0xEC78}

TOGGLE_CASE = -1           # SHIFT + Commodore: switch character set

# What's printed on each key, by matrix code.
LABELS = ["INST DEL", "RETURN", "CRSR ⇔", "F7", "F1", "F3", "F5", "CRSR ⇕",
          "3", "W", "A", "4", "Z", "S", "E", "SHIFT",
          "5", "R", "D", "6", "C", "F", "T", "X",
          "7", "Y", "G", "8", "B", "H", "U", "V",
          "9", "I", "J", "0", "M", "K", "O", "N",
          "+", "P", "L", "-", ".", ":", "@", ",",
          "£", "*", ";", "CLR HOME", "SHIFT", "=", "↑", "/",
          "1", "←", "CTRL", "2", "SPACE", "C=", "Q", "RUN STOP"]
LSHIFT, RSHIFT, CTRL_KEY, CBM_KEY = 15, 52, 58, 61
SHIFT_LOCK, RESTORE = 64, 65            # not in the matrix: shift lock holds SHIFT; RESTORE types nothing
MODIFIERS = {LSHIFT, RSHIFT, CTRL_KEY, CBM_KEY, SHIFT_LOCK}


@dataclass(frozen=True)
class Key:
    code: int              # matrix code (or SHIFT_LOCK, RESTORE)
    x: float               # position and size in key widths
    y: int
    w: float = 1.0

    @property
    def label(self) -> str:
        if self.code == SHIFT_LOCK:
            return "SHIFT LOCK"
        if self.code == RESTORE:
            return "RESTORE"
        return LABELS[self.code]


def _row(y: int, x: float, keys) -> list[Key]:
    out = []
    for k in keys:
        code, w = (k, 1.0) if isinstance(k, int) else k
        out.append(Key(code, x, y, w))
        x += w
    return out


# The C64's layout (the function keys on the right, as on the machine).
LAYOUT: list[Key] = (
    _row(0, 0, [57, 56, 59, 8, 11, 16, 19, 24, 27, 32, 35, 40, 43, 48, 51, 0])
    + _row(1, 0, [(CTRL_KEY, 1.5), 62, 9, 14, 17, 22, 25, 30, 33, 38, 41, 46, 49, 54, (RESTORE, 1.5)])
    + _row(2, 0, [63, SHIFT_LOCK, 10, 13, 18, 21, 26, 29, 34, 37, 42, 45, 50, 53, (1, 2.0)])
    + _row(3, 0, [CBM_KEY, (LSHIFT, 1.5), 12, 23, 20, 31, 28, 39, 36, 47, 44, 55, (RSHIFT, 1.5), 7, 2])
    + _row(4, 2.5, [(60, 9.0)])
    + [Key(4, 17, 0, 1.5), Key(5, 17, 1, 1.5), Key(6, 17, 2, 1.5), Key(3, 17, 3, 1.5)]
)


def decode(code: int, shift: bool = False, cbm: bool = False, ctrl: bool = False) -> int | None:
    """What a key types with these modifiers: a PETSCII code, TOGGLE_CASE, or None (nothing)."""
    if not 0 <= code < 64 or code in MODIFIERS:
        return None
    flags = (1 if shift else 0) | (2 if cbm else 0) | (4 if ctrl else 0)
    if flags == 3:
        return TOGGLE_CASE
    table = (NORMAL, SHIFT, CBM, CTRL)[min(3, flags if flags < 4 else 3)]
    v = table[code]
    return None if v == 0xFF else v


def keys_for(petscii: int) -> list[tuple[int, str]]:
    """How to type a PETSCII code: (matrix code, "", "shift", "cbm" or "ctrl"), plainest first."""
    out = []
    for name, table in (("", NORMAL), ("shift", SHIFT), ("cbm", CBM), ("ctrl", CTRL)):
        out += [(i, name) for i, v in enumerate(table) if v == petscii and i not in MODIFIERS]
    return out


# A PC keyboard: the C64 key for a key's character (letters, digits, punctuation) and for its
# other keys. As in CBM prg Studio, Tab is CTRL and Ctrl is the Commodore key.
PC_SPECIAL = {"Return": (1, False), "KP_Enter": (1, False), "BackSpace": (0, False), "Delete": (0, False),
              "Insert": (0, True), "Home": (51, False), "Down": (7, False), "Up": (7, True),
              "Right": (2, False), "Left": (2, True), "Escape": (63, False), "space": (60, False),
              "F1": (4, False), "F2": (4, True), "F3": (5, False), "F4": (5, True),
              "F5": (6, False), "F6": (6, True), "F7": (3, False), "F8": (3, True)}


def pc_key(char: str) -> tuple[int, bool] | None:
    """The C64 key (and whether SHIFT is needed) for a character typed on a PC keyboard."""
    if not char:
        return None
    c = char
    if c == "^":
        c = "↑"
    if c == "_":
        c = "←"
    if "a" <= c <= "z":
        return LABELS.index(c.upper()), False
    if "A" <= c <= "Z":
        return LABELS.index(c), True
    p = {"↑": 0x5E, "←": 0x5F, "£": 0x5C}.get(c, ord(c) if ord(c) < 0x80 else None)
    if p is None:
        return None
    for i, v in enumerate(NORMAL):
        if v == p and i not in MODIFIERS:
            return i, False
    for i, v in enumerate(SHIFT):
        if v == p and i not in MODIFIERS and not (0x41 <= p <= 0x5A):
            return i, True
    return None
