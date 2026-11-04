"""Planning what the VIC-II sees: its 16K bank, screen, character set, bitmap and sprite blocks,
the register values that select them, and the conflicts between them and a program.

  $DD00 bits 0-1   VIC bank, inverted: %11 = $0000, %10 = $4000, %01 = $8000, %00 = $C000
  $D018 bits 4-7   screen memory, in 1K steps from the bank's start
  $D018 bits 1-3   character set, in 2K steps (bit 3 alone picks the bitmap's 8K half)
  screen+$3F8      the eight sprite pointers: sprite data address = bank + pointer * 64
In banks 0 and 2 the VIC-II sees the character ROM at bank+$1000-$1FFF, not RAM.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Layout:
    bank: int = 0                 # 0-3
    screen: int = 1               # 1K slot 0-15 within the bank ($0400 = 1)
    charset: int = 2              # 2K slot 0-7 ($1000 = ROM upper case in banks 0 and 2)
    bitmap_mode: bool = False
    bitmap: int = 0               # 8K slot 0-1
    sprites: list[int] = field(default_factory=list)   # pointer values (64-byte blocks) in use

    # ---------------------------------------------------------------- addresses
    @property
    def bank_base(self) -> int:
        return self.bank * 0x4000

    @property
    def screen_addr(self) -> int:
        return self.bank_base + self.screen * 0x0400

    @property
    def charset_addr(self) -> int:
        return self.bank_base + self.charset * 0x0800

    @property
    def bitmap_addr(self) -> int:
        return self.bank_base + self.bitmap * 0x2000

    @property
    def sprite_pointers_addr(self) -> int:
        return self.screen_addr + 0x3F8

    def sprite_addr(self, pointer: int) -> int:
        return self.bank_base + pointer * 64

    def pointer_for(self, addr: int) -> int:
        """The sprite pointer value for sprite data at addr (which must be in the bank, 64-aligned)."""
        if not self.bank_base <= addr < self.bank_base + 0x4000:
            raise ValueError(f"${addr:04X} isn't in VIC bank {self.bank} (${self.bank_base:04X}-${self.bank_base + 0x3FFF:04X})")
        if addr % 64:
            raise ValueError(f"Sprite data must start on a 64-byte boundary (${addr:04X} isn't)")
        return (addr - self.bank_base) // 64

    # ---------------------------------------------------------------- registers
    @property
    def dd00_bits(self) -> int:
        return 3 - self.bank

    @property
    def d018(self) -> int:
        low = (self.bitmap << 3) if self.bitmap_mode else (self.charset << 1)
        return (self.screen << 4) | low

    @property
    def book_charmemory_value(self) -> int:
        """The value the book's LIBSCREEN_SETCHARMEMORY macro takes (the low nibble of $D018)."""
        return self.d018 & 0x0F

    def char_rom_shadow(self) -> tuple[int, int] | None:
        """Where the VIC-II sees the character ROM instead of RAM in this bank, if anywhere."""
        if self.bank in (0, 2):
            return self.bank_base + 0x1000, self.bank_base + 0x1FFF
        return None

    def uses_rom_charset(self) -> bool:
        shadow = self.char_rom_shadow()
        return not self.bitmap_mode and shadow is not None and shadow[0] <= self.charset_addr <= shadow[1]

    # ---------------------------------------------------------------- the areas the VIC-II reads
    def areas(self) -> list[tuple[str, int, int]]:
        out = [("Screen", self.screen_addr, self.screen_addr + 999),
               ("Sprite pointers", self.sprite_pointers_addr, self.sprite_pointers_addr + 7)]
        if self.bitmap_mode:
            out.append(("Bitmap", self.bitmap_addr, self.bitmap_addr + 7999))
        elif not self.uses_rom_charset():
            out.append(("Character set", self.charset_addr, self.charset_addr + 0x7FF))
        for p in sorted(set(self.sprites)):
            a = self.sprite_addr(p)
            out.append((f"Sprite {p}", a, a + 62))
        return out

    @classmethod
    def from_registers(cls, dd00: int, d018: int, d011: int = 0x1B, pointers: list[int] | None = None,
                       spena: int = 0) -> "Layout":
        """The layout a program has actually set, from VIC-II/CIA register values."""
        bitmap_mode = bool(d011 & 0x20)
        sprites = [p for i, p in enumerate(pointers or []) if spena & (1 << i)]
        return cls(bank=3 - (dd00 & 3), screen=(d018 >> 4) & 0x0F, charset=(d018 >> 1) & 7,
                   bitmap_mode=bitmap_mode, bitmap=(d018 >> 3) & 1, sprites=sprites)


@dataclass
class Issue:
    severity: str     # "warning" or "note"
    message: str


def check(layout: Layout, memmap=None) -> list[Issue]:
    """Conflicts between the VIC-II's areas, the character ROM, the I/O area and a program."""
    out: list[Issue] = []
    areas = layout.areas()
    shadow = layout.char_rom_shadow()
    for i, (name, lo, hi) in enumerate(areas):
        if shadow and lo <= shadow[1] and hi >= shadow[0] and name != "Sprite pointers":
            out.append(Issue("warning", f"{name} (${lo:04X}) is where the VIC-II sees the character ROM in bank "
                                        f"{layout.bank}: it shows the ROM, not your data. Move it, or use bank 1 or 3"))
        for name2, lo2, hi2 in areas[i + 1:]:
            if lo <= hi2 and lo2 <= hi and {name, name2} != {"Screen", "Sprite pointers"}:
                out.append(Issue("warning", f"{name} (${lo:04X}-${hi:04X}) overlaps {name2} (${lo2:04X}-${hi2:04X})"))
        if layout.bank == 3 and lo <= 0xDFFF and hi >= 0xD000:
            out.append(Issue("note", f"{name} is under the I/O area: the VIC-II reads the RAM there, but the CPU "
                                     f"must switch I/O out ($01) to write it"))
    if layout.uses_rom_charset():
        which = "upper case/graphics" if layout.charset_addr - layout.bank_base == 0x1000 else "lower/upper case"
        out.append(Issue("note", f"The character set is the ROM's ({which})"))
    elif not layout.bitmap_mode and layout.bank in (1, 3) and layout.charset_addr - layout.bank_base in (0x1000, 0x1800):
        out.append(Issue("note", f"Bank {layout.bank} has no character ROM: ${layout.charset_addr:04X} must hold your "
                                 f"own character set"))
    if memmap is not None:
        for name, lo, hi in areas:
            owners = {}
            for s in memmap.segments:
                if s.start <= hi and s.end >= lo:
                    owners.setdefault((s.owner, s.kind), (max(lo, s.start), min(hi, s.end)))
            for (owner, kind), (a, b) in owners.items():
                if kind == "code":
                    out.append(Issue("warning", f"{name} (${lo:04X}-${hi:04X}) overlaps code from {owner} "
                                                f"(${a:04X}-${b:04X})"))
                else:
                    out.append(Issue("note", f"{name} holds {'data' if kind == 'data' else 'an included binary'} "
                                             f"from {owner} (${a:04X}-${b:04X})"))
    return out


def setup_code(layout: Layout, kickass: bool = False, sprite_numbers: dict[int, int] | None = None) -> str:
    """Assembler that switches the VIC-II to this layout (and constants for the addresses)."""
    c = "//" if kickass else ";"
    ind = "    " if kickass else "        "

    def const(name, value, comment=""):
        v = f"${value:04X}" if value > 0xFF else f"${value:02X}"
        line = f".const {name} = {v}" if kickass else f"{name:<15} = {v}"
        return line + (f"    {c} {comment}" if comment else "")

    out = [f"{c} VIC-II memory layout (made by Linux64Studio's Memory Manager)",
           const("VICBANK", layout.bank_base, f"bank {layout.bank}"),
           const("SCREENRAM", layout.screen_addr),
           const("SPRITEPTRS", layout.sprite_pointers_addr, "the 8 sprite pointers")]
    if layout.bitmap_mode:
        out.append(const("BITMAP", layout.bitmap_addr))
    else:
        out.append(const("CHARSET", layout.charset_addr, "ROM character set" if layout.uses_rom_charset() else ""))
    out += ["", f"{c} Select VIC bank {layout.bank} (${layout.bank_base:04X}-${layout.bank_base + 0x3FFF:04X})",
            f"{ind}lda $DD00", f"{ind}and #%11111100", f"{ind}ora #%{layout.dd00_bits:02b}", f"{ind}sta $DD00",
            "", f"{c} Screen at ${layout.screen_addr:04X}, "
                + (f"bitmap at ${layout.bitmap_addr:04X}" if layout.bitmap_mode else f"characters at ${layout.charset_addr:04X}"),
            f"{ind}lda #%{layout.d018:08b}", f"{ind}sta $D018"]
    if layout.bitmap_mode:
        out += [f"{ind}lda $D011", f"{ind}ora #%00100000   {c} bitmap mode on", f"{ind}sta $D011"]
    nums = sprite_numbers or {}
    for i, p in enumerate(sorted(set(layout.sprites))[:8]):
        n = nums.get(p, i)
        if i == 0:
            out += ["", f"{c} Sprite pointers: data address = VICBANK + pointer * 64"]
        out += [f"{ind}lda #{p}{'' if kickass else ''}      {c} sprite data at ${layout.sprite_addr(p):04X}",
                f"{ind}sta SPRITEPTRS+{n}"]
    return "\n".join(out) + "\n"
