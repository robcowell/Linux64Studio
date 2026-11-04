"""Character animation preview (CBM prg Studio's Character Editor → Animation): which characters
make each frame and the order frames are shown in.

A frame is one character, or a block of `across` × `down` characters that follow one another in
the set (row by row), as games often animate a 2×2 graphic by stepping 4 characters a frame.
"""
from __future__ import annotations

LOOP, PING_PONG = "loop", "ping-pong"
PAL_FPS = 50


def frame_starts(first: int, last: int, per_frame: int = 1) -> list[int]:
    """The first character of each frame, from `first` to `last` (backwards if last < first),
    stepping a frame's worth of characters each time. Frames running past 255 are left out."""
    per_frame = max(1, per_frame)
    step = per_frame if last >= first else -per_frame
    out, ch = [], first
    while (ch <= last if step > 0 else ch >= last) and 0 <= ch and ch + per_frame - 1 <= 255:
        out.append(ch)
        ch += step
    return out


def order(n: int, mode: str = LOOP) -> list[int]:
    """The frame numbers shown, once round: a loop goes 0..n-1, ping-pong 0..n-1 then back to 1."""
    if n <= 0:
        return []
    if mode == PING_PONG and n > 2:
        return list(range(n)) + list(range(n - 2, 0, -1))
    return list(range(n))


def frame_chars(start: int, across: int = 1, down: int = 1) -> list[list[int]]:
    """The characters of the frame starting at `start`, as rows."""
    return [[start + r * across + c for c in range(across)] for r in range(down)]


def describe_speed(delay: int) -> str:
    """`delay` C64 frames (1/50 s) between animation frames."""
    fps = PAL_FPS / max(1, delay)
    return f"every {delay} frame{'s' if delay != 1 else ''} ({fps:.3g} a second)"
