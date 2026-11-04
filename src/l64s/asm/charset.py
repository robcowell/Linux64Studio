"""Character conversions between source text and C64 byte values."""
from __future__ import annotations


def char_to_screencode(ch: str) -> int:
    """Screen code of a source character, matching CBM prg Studio's 'a' -> 1 convention.

    Lower-case source letters are the C64's default (upper-case) letters, screen codes 1-26.
    Upper-case source letters map to the shifted letters, screen codes 65-90.
    """
    o = ord(ch)
    if ch == "@":
        return 0
    if "a" <= ch <= "z":
        return o - ord("a") + 1
    if "A" <= ch <= "Z":
        return o - ord("A") + 65
    if ch == "[":
        return 27
    if ch == "£":
        return 28
    if ch == "]":
        return 29
    if ch == "^":
        return 30
    if ch == "_":
        return 31  # left-arrow
    if 32 <= o <= 63:
        return o
    return o & 0xFF


def char_to_petscii(ch: str) -> int:
    """PETSCII value of a source character (lower-case source = unshifted letters)."""
    o = ord(ch)
    if "a" <= ch <= "z":
        return o - ord("a") + 0x41
    if "A" <= ch <= "Z":
        return o - ord("A") + 0xC1
    if ch == "£":
        return 0x5C
    return o & 0xFF
