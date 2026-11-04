"""C64 cartridge images (.crt), as used by VICE and real-hardware cartridge loaders.

A .crt is a 64-byte header ("C64 CARTRIDGE   ", header length, version 1.0, hardware type,
EXROM and GAME line states, name) followed by CHIP packets, one per ROM chip/bank:
"CHIP", packet length, chip type (0 ROM, 2 flash), bank number, load address, size, data.
All numbers are big-endian. Layouts here match VICE's cartconv byte for byte.

Supported types (the program supplies bank 0; data files can fill further banks):

  normal8    8K at $8000 (ROML)                  EXROM 0, GAME 1
  normal16   16K at $8000-$BFFF (ROML + ROMH)    EXROM 0, GAME 0
  ultimax    4K at $F000 or 8K at $E000 (ROMH), plus an optional 8K ROML at $8000
  magicdesk  8K banks at $8000 (hardware type 19), bank number written to $DE00
  ocean      8K banks (type 5): 128K at $8000; 256K banks 16-31 at $A000; 512K all at $8000
  easyflash  64 banks of 8K ROML ($8000) + 8K ROMH ($A000, or $E000 in Ultimax mode),
             type 32. Boots in Ultimax mode from bank 0's ROMH. Erased ($FF) chips are left out.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

SIGNATURE = b"C64 CARTRIDGE   "
CHIP_ROM, CHIP_RAM, CHIP_FLASH = 0, 1, 2
BANK = 0x2000
ERASED = 0xFF


class CartError(Exception):
    pass


@dataclass(frozen=True)
class CartType:
    key: str
    label: str
    hardware: int
    exrom: int
    game: int
    max_banks: int


CART_TYPES = {t.key: t for t in [
    CartType("normal8", "Normal 8K ($8000-$9FFF)", 0, 0, 1, 1),
    CartType("normal16", "Normal 16K ($8000-$BFFF)", 0, 0, 0, 1),
    CartType("ultimax", "Ultimax (ROMH at $E000/$F000, optional ROML)", 0, 1, 0, 1),
    CartType("magicdesk", "Magic Desk (8K banks, up to 512K)", 19, 0, 1, 64),
    CartType("ocean", "Ocean type 1 (8K banks: 128K, 256K or 512K)", 5, 0, 0, 64),
    CartType("easyflash", "EasyFlash (64 banks of 16K)", 32, 1, 0, 64),
]}
HARDWARE_NAMES = {0: "Generic", 5: "Ocean", 19: "Magic Desk", 32: "EasyFlash"}


@dataclass
class Chip:
    bank: int
    address: int
    data: bytes
    chip_type: int = CHIP_ROM


@dataclass
class Cartridge:
    hardware: int
    exrom: int
    game: int
    name: str = ""
    chips: list[Chip] = field(default_factory=list)
    revision: int = 0

    def to_bytes(self) -> bytes:
        name = self.name.encode("ascii", "replace")[:32]
        out = bytearray(SIGNATURE)
        out += struct.pack(">IHHBBB5x", 0x40, 0x0100, self.hardware, self.exrom, self.game, self.revision)
        out += name + bytes(32 - len(name))
        for c in self.chips:
            out += b"CHIP" + struct.pack(">IHHHH", 0x10 + len(c.data), c.chip_type, c.bank, c.address, len(c.data))
            out += c.data
        return bytes(out)

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(self.to_bytes())

    @property
    def size(self) -> int:
        return sum(len(c.data) for c in self.chips)

    @property
    def mode(self) -> str:
        return {(0, 1): "8K game", (0, 0): "16K game", (1, 0): "Ultimax", (1, 1): "off (no ROM mapped)"}[
            (self.exrom, self.game)]

    @property
    def type_name(self) -> str:
        return HARDWARE_NAMES.get(self.hardware, f"hardware type {self.hardware}")


def load_crt(path: str | Path) -> Cartridge:
    data = Path(path).read_bytes()
    if len(data) < 0x40 or data[:16] != SIGNATURE:
        raise CartError(f"{Path(path).name} isn't a C64 cartridge (.crt) file")
    hlen, _version, hw, exrom, game, rev = struct.unpack(">IHHBBB", data[16:27])
    name = data[32:64].split(b"\0")[0].decode("ascii", "replace")
    cart = Cartridge(hw, exrom, game, name, revision=rev)
    off = max(hlen, 0x40)
    while off + 16 <= len(data):
        if data[off:off + 4] != b"CHIP":
            raise CartError(f"Bad CHIP packet at offset ${off:X}")
        plen, ctype, bank, addr, size = struct.unpack(">IHHHH", data[off + 4:off + 16])
        if plen < 16 or off + 16 + size > len(data):
            raise CartError(f"Truncated CHIP packet at offset ${off:X}")
        cart.chips.append(Chip(bank, addr, data[off + 16:off + 16 + size], ctype))
        off += plen
    return cart


# ---------------------------------------------------------------------- building

@dataclass
class Image:
    """A program's memory: 64K of bytes plus which ones it actually set."""
    memory: bytearray
    used: bytearray

    @classmethod
    def from_prg(cls, prg: bytes) -> "Image":
        if len(prg) < 3:
            raise CartError("The program is empty")
        start = prg[0] | (prg[1] << 8)
        body = prg[2:]
        if start + len(body) > 0x10000:
            raise CartError("The program runs past $FFFF")
        mem = bytearray([ERASED]) * 0x10000
        used = bytearray(0x10000)
        mem[start:start + len(body)] = body
        used[start:start + len(body)] = b"\x01" * len(body)
        return cls(mem, used)

    def any_used(self, lo: int, hi: int) -> bool:
        return any(self.used[lo:hi])

    def first_used(self) -> int | None:
        i = self.used.find(1)
        return None if i < 0 else i

    def check_inside(self, regions: list[tuple[int, int]], what: str) -> None:
        for a in range(0x10000):
            if self.used[a] and not any(lo <= a < hi for lo, hi in regions):
                areas = ", ".join(f"${lo:04X}-${hi - 1:04X}" for lo, hi in regions)
                raise CartError(f"The program has code or data at ${a:04X}, outside the {what} ROM ({areas}). "
                                f"Cartridge code must be assembled there, e.g. *=$8000")

    def block(self, lo: int, size: int = BANK) -> bytes:
        return bytes(self.memory[lo:lo + size])


def _split(data: bytes, size: int) -> list[bytes]:
    if not data:
        return []
    n = (len(data) + size - 1) // size
    data = data + bytes([ERASED]) * (n * size - len(data))
    return [data[i * size:(i + 1) * size] for i in range(n)]


def _strip_prg(path: Path, data: bytes) -> bytes:
    return data[2:] if path.suffix.lower() == ".prg" else data


def build_cartridge(kind: str, image: Image, name: str = "",
                    extra_banks: list[bytes] | None = None) -> Cartridge:
    """Make a cartridge of type `kind` from a program image (bank 0) plus extra bank data.

    Each item of extra_banks is split into banks (8K, or 16K for EasyFlash) and they follow
    bank 0 in order.
    """
    if kind not in CART_TYPES:
        raise CartError(f"Unknown cartridge type '{kind}'")
    t = CART_TYPES[kind]
    extra = extra_banks or []
    if extra and t.max_banks == 1:
        raise CartError(f"A {t.label} cartridge has no room for extra banks")
    cart = Cartridge(t.hardware, t.exrom, t.game, name[:32])  # case kept, as cartconv does

    if kind == "normal8":
        image.check_inside([(0x8000, 0xA000)], "8K cartridge")
        cart.chips = [Chip(0, 0x8000, image.block(0x8000))]
    elif kind == "normal16":
        image.check_inside([(0x8000, 0xC000)], "16K cartridge")
        cart.chips = [Chip(0, 0x8000, image.block(0x8000, 0x4000))]
    elif kind == "ultimax":
        image.check_inside([(0x8000, 0xA000), (0xE000, 0x10000)], "Ultimax cartridge")
        if not image.any_used(0xE000, 0x10000):
            raise CartError("An Ultimax cartridge needs code at $E000-$FFFF (with the reset vector at $FFFC)")
        chips = []
        if image.any_used(0x8000, 0xA000):
            chips.append(Chip(0, 0x8000, image.block(0x8000)))
        if chips or image.any_used(0xE000, 0xF000):
            chips.append(Chip(0, 0xE000, image.block(0xE000)))
        else:
            chips.append(Chip(0, 0xF000, image.block(0xF000, 0x1000)))
        cart.chips = chips
    elif kind in ("magicdesk", "ocean"):
        image.check_inside([(0x8000, 0xA000)], f"{t.label} bank 0")
        banks = [image.block(0x8000)] + [b for d in extra for b in _split(d, BANK)]
        if kind == "ocean":
            size = next((n for n in (16, 32, 64) if len(banks) <= n), None)
            if size is None:
                raise CartError(f"{len(banks)} banks is too many for an Ocean cartridge (64 at most, 512K)")
            banks += [bytes([ERASED]) * BANK] * (size - len(banks))
            if size == 64:
                cart.game = 1  # 512K Ocean carts run in 8K mode
            cart.chips = [Chip(i, 0xA000 if size == 32 and i >= 16 else 0x8000, b) for i, b in enumerate(banks)]
        else:
            size = next((n for n in (4, 8, 16, 32, 64) if len(banks) <= n), None)
            if size is None:
                raise CartError(f"{len(banks)} banks is too many for a Magic Desk cartridge (64 at most, 512K)")
            banks += [bytes([ERASED]) * BANK] * (size - len(banks))
            cart.chips = [Chip(i, 0x8000, b) for i, b in enumerate(banks)]
    elif kind == "easyflash":
        # Bank 0's ROMH is assembled where the CPU sees it at reset: $E000-$FFFF (Ultimax mode).
        image.check_inside([(0x8000, 0xA000), (0xE000, 0x10000)], "EasyFlash bank 0")
        if not image.any_used(0xE000, 0x10000):
            raise CartError("EasyFlash starts in Ultimax mode: bank 0 needs code at $E000-$FFFF "
                            "(with the reset vector at $FFFC)")
        banks = [image.block(0x8000) + image.block(0xE000)] + [b for d in extra for b in _split(d, 2 * BANK)]
        if len(banks) > 64:
            raise CartError(f"{len(banks)} banks is too many for EasyFlash (64 at most, 1MB)")
        for i, b in enumerate(banks):
            for half, addr in ((b[:BANK], 0x8000), (b[BANK:], 0xA000)):
                if any(x != ERASED for x in half):   # erased chips are left out, as cartconv does
                    cart.chips.append(Chip(i, addr, half, CHIP_FLASH))
    return cart


def cartridge_from_files(kind: str, prg: Path, name: str, extra_files: list[Path]) -> Cartridge:
    image = Image.from_prg(prg.read_bytes())
    extra = [_strip_prg(p, p.read_bytes()) for p in extra_files]
    return build_cartridge(kind, image, name, extra)
