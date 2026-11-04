"""Importing characters or sprites from memory (CBM prg Studio's Import → From Memory, and From
File): the 64K a build makes, a running program's (VICE's), or a file, read from an address.

The address can be given as the VIC-II sees it: a character set is 2K, at one of the eight places
in a 16K VIC bank (the value $D018 picks); a sprite is 64 bytes at the block its pointer names
(pointer × 64 in the bank).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CHAR_BYTES, SPRITE_BYTES = 8, 64


class MemoryImportError(ValueError):
    pass


@dataclass
class Memory:
    """64K, and which bytes are known (a file only covers its own part)."""
    data: bytes
    known: bytes            # 1 for a byte that's there
    what: str = ""

    def read(self, addr: int, length: int) -> bytes:
        """Up to `length` bytes from addr, as far as the known bytes go (a file's end, a gap in a
        build)."""
        if not 0 <= addr <= 0xFFFF:
            raise MemoryImportError(f"${addr:X} isn't an address")
        if not self.known[addr]:
            raise MemoryImportError(f"Nothing is at ${addr:04X} in {self.what or 'this memory'}")
        end = addr
        stop = min(0x10000, addr + length)
        while end < stop and self.known[end]:
            end += 1
        return bytes(self.data[addr:end])


def from_bytes(data: bytes, what: str = "") -> Memory:
    data = bytes(data[:0x10000]).ljust(0x10000, b"\0")
    return Memory(data, b"\x01" * 0x10000, what)


def from_file(path: Path, load_address: bool | None = None, base: int = 0) -> Memory:
    """A file's bytes in memory: a .prg (or `load_address`) at the address its first two bytes
    give, anything else at `base`."""
    raw = Path(path).read_bytes()
    if load_address is None:
        load_address = Path(path).suffix.lower() == ".prg"
    if load_address:
        if len(raw) < 3:
            raise MemoryImportError(f"{Path(path).name} is too short to have a load address")
        base, raw = raw[0] | raw[1] << 8, raw[2:]
    data = bytearray(0x10000)
    known = bytearray(0x10000)
    n = min(len(raw), 0x10000 - base)
    data[base:base + n] = raw[:n]
    known[base:base + n] = b"\x01" * n
    return Memory(bytes(data), bytes(known), f"{Path(path).name} (${base:04X}-${base + n - 1:04X})")


def rom_charset(uppercase: bool = True) -> Memory:
    """The C64's character ROM, as if at address 0 (2K; upper case and graphics, or lower case)."""
    from .charset import rom_charset as rom
    chars = rom(uppercase)
    if not chars:
        raise MemoryImportError("The character ROM isn't installed (VICE's chargen file)")
    flat = bytes(b for c in chars for b in c)
    data = flat.ljust(0x10000, b"\0")
    known = (b"\x01" * len(flat)).ljust(0x10000, b"\0")
    return Memory(data, known, "the character ROM (" + ("upper case" if uppercase else "lower case") + ")")


def charset_address(bank: int, slot: int) -> int:
    """Where character set `slot` (0-7, $D018 bits 1-3) is in VIC bank `bank` (0-3)."""
    return (bank & 3) * 0x4000 + (slot & 7) * 0x800


def sprite_address(bank: int, pointer: int) -> int:
    """Where the sprite a pointer (0-255) names is in VIC bank `bank`."""
    return (bank & 3) * 0x4000 + (pointer & 0xFF) * SPRITE_BYTES


def rom_shadow(bank: int, slot: int) -> bool:
    """In VIC banks 0 and 2 the VIC-II sees the character ROM at $1000-$1FFF, not RAM."""
    return bank in (0, 2) and slot in (2, 3)


def chars(mem: Memory, addr: int, count: int) -> list[list[int]]:
    data = mem.read(addr, count * CHAR_BYTES)
    return [list(data[i:i + 8]) for i in range(0, len(data) - 7, 8)][:count]


def sprites(mem: Memory, addr: int, count: int) -> list[bytes]:
    data = mem.read(addr, count * SPRITE_BYTES)
    return [data[i:i + 63] for i in range(0, len(data) - 62, SPRITE_BYTES)][:count]
