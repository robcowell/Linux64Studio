"""SYS() call generator: the bytes of a one-line BASIC program that starts a machine code program,
for the top of an assembler source (as in CBM prg Studio, and the book's "10 SYS (2064)").

A BASIC line in memory is: the address of the next line (2 bytes), the line number (2 bytes), the
tokenised text, and a 0. The program ends with a next-line address of 0. Here the program is one
line at $0801, so the next-line address points at that final 00 00.

Styles:
  decorated   10 SYS (2064)      (as the book's chapters start)
  plain       10 SYS2064
  obfuscated  10 SYS2064:REM, then DEL characters and a message. LIST prints DEL ($14) as a
              delete, so the line lists as just the message, but RUN still runs the SYS.
"""
from __future__ import annotations

from dataclasses import dataclass

from .basic.screencodes import text_to_petscii

LOAD = 0x0801
SYS, REM = 0x9E, 0x8F
DEL = 0x14
STYLES = ["decorated", "plain", "obfuscated"]


class SysError(ValueError):
    pass


@dataclass
class SysCall:
    address: int | None = None      # None: start the program right after the SYS line
    line: int = 10
    style: str = "decorated"
    message: str = ""               # what an obfuscated line lists as
    load: int = LOAD


def _text(call: SysCall, address: int) -> tuple[bytes, str]:
    """The tokenised line text, and how it lists."""
    digits = str(address).encode()
    if call.style == "decorated":
        return bytes([SYS]) + b" (" + digits + b")", f"{call.line} SYS ({address})"
    if call.style == "plain":
        return bytes([SYS]) + digits, f"{call.line} SYS{address}"
    if call.style == "obfuscated":
        if not call.message.strip():
            raise SysError("The obfuscation message can't be empty")
        try:
            msg = text_to_petscii(call.message)
        except ValueError as e:
            raise SysError(f"The message: {e}") from e
        if 0 in msg:
            raise SysError("The message can't contain a zero byte")
        if len(msg) > 60:
            raise SysError("Keep the message to 60 characters, so the line still lists on one screen line")
        # LIST prints "10 SYS2064:REM" (the line number, a space, then the text): delete all of it
        shown = len(str(call.line)) + 1 + len("SYS") + len(digits) + len(":REM")
        return bytes([SYS]) + digits + b":" + bytes([REM]) + bytes([DEL] * shown) + msg, \
            f"{call.line} SYS{address}:REM (lists as: {call.message})"
    raise SysError(f"Unknown style {call.style!r}")


def generate(call: SysCall) -> tuple[bytes, int, str]:
    """(the bytes from the load address, the SYS address, how the line lists)."""
    if not 0 <= call.line <= 63999:
        raise SysError("The line number must be 0-63999")
    if call.address is not None and not 0 <= call.address <= 0xFFFF:
        raise SysError("The start address must be $0000-$FFFF")
    address = call.address
    if address is None:
        # right after the stub; the stub's length depends on how many digits the address has
        address = call.load
        for _ in range(4):
            size = 4 + len(_text(call, address)[0]) + 1 + 2
            if call.load + size == address:
                break
            address = call.load + size
    text, listing = _text(call, address)
    end = call.load + 4 + len(text) + 1               # where the final 00 00 goes
    out = bytes([end & 0xFF, end >> 8, call.line & 0xFF, call.line >> 8]) + text + b"\0\0\0"
    if call.address is not None and call.load <= call.address < call.load + len(out):
        raise SysError(f"${call.address:04X} is inside the SYS line itself (${call.load:04X}-"
                       f"${call.load + len(out) - 1:04X}): start the program at ${call.load + len(out):04X} or later")
    return out, address, listing


def source(call: SysCall, kickass: bool = False, comments: bool = True, syntax: str | None = None) -> str:
    """Assembler for the stub: *= the load address, the bytes, and *= the program start. A C program
    doesn't need one (cc65 puts its own SYS line first), so for C it says so; for ca65 the bytes go
    in the program's first segment."""
    data, address, listing = generate(call)
    if syntax == "c":
        return (f"/* cc65 starts every C64 program with its own BASIC line ({listing.split(':', 1)[0]} SYS ...),\n"
                "   so a C program doesn't need this one. */\n")
    if syntax == "ca65":
        out = [f"; BASIC loader: {listing}"] if comments else []
        out += ["; (the first bytes of the program: the linker puts them at the load address)"] if comments else []
        for i in range(0, len(data), 8):
            out.append("        .byte " + ", ".join(f"${b:02X}" for b in data[i:i + 8]))
        if comments:
            out.append(f"; the program starts here: ${address:04X} ({address} decimal)")
        return "\n".join(out) + "\n"
    c = "//" if kickass else ";"
    ind = "    " if kickass else "        "
    byte = ".byte" if kickass else "byte"
    out = []
    if comments:
        out.append(f"{c} BASIC loader: {listing}")
    out.append(f"*=${call.load:04X}")
    for i in range(0, len(data), 8):
        out.append(f"{ind}{byte} " + ", ".join(f"${b:02X}" for b in data[i:i + 8]))
    out.append("")
    gap = address - (call.load + len(data))
    note = ("right after the SYS line" if gap == 0 else
            f"{gap} bytes after the SYS line" if gap > 0 else "before the SYS line")
    out.append(f"*=${address:04X}" + (f"{'':8}{c} the program starts here ({address} decimal, {note})"
                                      if comments else ""))
    return "\n".join(out) + "\n"
