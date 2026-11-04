"""6502/6510 opcode table.

Addressing mode keys:
  imp  implied            acc  accumulator        imm  #immediate
  zp   zero page          zpx  zp,x               zpy  zp,y
  abs  absolute           abx  abs,x              aby  abs,y
  ind  (abs)              izx  (zp,x)             izy  (zp),y
  rel  relative branch
"""

MODE_SIZE = {
    "imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2,
    "abs": 3, "abx": 3, "aby": 3, "ind": 3, "izx": 2, "izy": 2, "rel": 2,
}

# mnemonic -> {mode: opcode}
OPCODES: dict[str, dict[str, int]] = {
    "adc": {"imm": 0x69, "zp": 0x65, "zpx": 0x75, "abs": 0x6D, "abx": 0x7D, "aby": 0x79, "izx": 0x61, "izy": 0x71},
    "and": {"imm": 0x29, "zp": 0x25, "zpx": 0x35, "abs": 0x2D, "abx": 0x3D, "aby": 0x39, "izx": 0x21, "izy": 0x31},
    "asl": {"acc": 0x0A, "zp": 0x06, "zpx": 0x16, "abs": 0x0E, "abx": 0x1E},
    "bcc": {"rel": 0x90}, "bcs": {"rel": 0xB0}, "beq": {"rel": 0xF0}, "bmi": {"rel": 0x30},
    "bne": {"rel": 0xD0}, "bpl": {"rel": 0x10}, "bvc": {"rel": 0x50}, "bvs": {"rel": 0x70},
    "bit": {"zp": 0x24, "abs": 0x2C},
    "brk": {"imp": 0x00},
    "clc": {"imp": 0x18}, "cld": {"imp": 0xD8}, "cli": {"imp": 0x58}, "clv": {"imp": 0xB8},
    "cmp": {"imm": 0xC9, "zp": 0xC5, "zpx": 0xD5, "abs": 0xCD, "abx": 0xDD, "aby": 0xD9, "izx": 0xC1, "izy": 0xD1},
    "cpx": {"imm": 0xE0, "zp": 0xE4, "abs": 0xEC},
    "cpy": {"imm": 0xC0, "zp": 0xC4, "abs": 0xCC},
    "dec": {"zp": 0xC6, "zpx": 0xD6, "abs": 0xCE, "abx": 0xDE},
    "dex": {"imp": 0xCA}, "dey": {"imp": 0x88},
    "eor": {"imm": 0x49, "zp": 0x45, "zpx": 0x55, "abs": 0x4D, "abx": 0x5D, "aby": 0x59, "izx": 0x41, "izy": 0x51},
    "inc": {"zp": 0xE6, "zpx": 0xF6, "abs": 0xEE, "abx": 0xFE},
    "inx": {"imp": 0xE8}, "iny": {"imp": 0xC8},
    "jmp": {"abs": 0x4C, "ind": 0x6C},
    "jsr": {"abs": 0x20},
    "lda": {"imm": 0xA9, "zp": 0xA5, "zpx": 0xB5, "abs": 0xAD, "abx": 0xBD, "aby": 0xB9, "izx": 0xA1, "izy": 0xB1},
    "ldx": {"imm": 0xA2, "zp": 0xA6, "zpy": 0xB6, "abs": 0xAE, "aby": 0xBE},
    "ldy": {"imm": 0xA0, "zp": 0xA4, "zpx": 0xB4, "abs": 0xAC, "abx": 0xBC},
    "lsr": {"acc": 0x4A, "zp": 0x46, "zpx": 0x56, "abs": 0x4E, "abx": 0x5E},
    "nop": {"imp": 0xEA},
    "ora": {"imm": 0x09, "zp": 0x05, "zpx": 0x15, "abs": 0x0D, "abx": 0x1D, "aby": 0x19, "izx": 0x01, "izy": 0x11},
    "pha": {"imp": 0x48}, "php": {"imp": 0x08}, "pla": {"imp": 0x68}, "plp": {"imp": 0x28},
    "rol": {"acc": 0x2A, "zp": 0x26, "zpx": 0x36, "abs": 0x2E, "abx": 0x3E},
    "ror": {"acc": 0x6A, "zp": 0x66, "zpx": 0x76, "abs": 0x6E, "abx": 0x7E},
    "rti": {"imp": 0x40}, "rts": {"imp": 0x60},
    "sbc": {"imm": 0xE9, "zp": 0xE5, "zpx": 0xF5, "abs": 0xED, "abx": 0xFD, "aby": 0xF9, "izx": 0xE1, "izy": 0xF1},
    "sec": {"imp": 0x38}, "sed": {"imp": 0xF8}, "sei": {"imp": 0x78},
    "sta": {"zp": 0x85, "zpx": 0x95, "abs": 0x8D, "abx": 0x9D, "aby": 0x99, "izx": 0x81, "izy": 0x91},
    "stx": {"zp": 0x86, "zpy": 0x96, "abs": 0x8E},
    "sty": {"zp": 0x84, "zpx": 0x94, "abs": 0x8C},
    "tax": {"imp": 0xAA}, "tay": {"imp": 0xA8}, "tsx": {"imp": 0xBA}, "txa": {"imp": 0x8A},
    "txs": {"imp": 0x9A}, "tya": {"imp": 0x98},
}

# Commonly used undocumented 6510 opcodes, only enabled on request.
ILLEGAL_OPCODES: dict[str, dict[str, int]] = {
    "lax": {"zp": 0xA7, "zpy": 0xB7, "abs": 0xAF, "aby": 0xBF, "izx": 0xA3, "izy": 0xB3},
    "sax": {"zp": 0x87, "zpy": 0x97, "abs": 0x8F, "izx": 0x83},
    "dcp": {"zp": 0xC7, "zpx": 0xD7, "abs": 0xCF, "abx": 0xDF, "aby": 0xDB, "izx": 0xC3, "izy": 0xD3},
    "isc": {"zp": 0xE7, "zpx": 0xF7, "abs": 0xEF, "abx": 0xFF, "aby": 0xFB, "izx": 0xE3, "izy": 0xF3},
    "slo": {"zp": 0x07, "zpx": 0x17, "abs": 0x0F, "abx": 0x1F, "aby": 0x1B, "izx": 0x03, "izy": 0x13},
    "rla": {"zp": 0x27, "zpx": 0x37, "abs": 0x2F, "abx": 0x3F, "aby": 0x3B, "izx": 0x23, "izy": 0x33},
    "sre": {"zp": 0x47, "zpx": 0x57, "abs": 0x4F, "abx": 0x5F, "aby": 0x5B, "izx": 0x43, "izy": 0x53},
    "rra": {"zp": 0x67, "zpx": 0x77, "abs": 0x6F, "abx": 0x7F, "aby": 0x7B, "izx": 0x63, "izy": 0x73},
    "anc": {"imm": 0x0B}, "alr": {"imm": 0x4B}, "arr": {"imm": 0x6B}, "sbx": {"imm": 0xCB},
}

# Zero-page mode -> the equivalent absolute mode, used when a value doesn't fit in a byte.
ZP_TO_ABS = {"zp": "abs", "zpx": "abx", "zpy": "aby"}


def build_reverse_table(include_illegal: bool = True) -> dict[int, tuple[str, str]]:
    """opcode byte -> (mnemonic, mode), used by the disassembler."""
    table = {}
    sources = [OPCODES] + ([ILLEGAL_OPCODES] if include_illegal else [])
    for src in sources:
        for mnem, modes in src.items():
            for mode, op in modes.items():
                table.setdefault(op, (mnem, mode))
    return table
