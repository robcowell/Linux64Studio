"""Standard names for the C64's I/O registers, vectors and KERNAL routines, as in "Mapping the
Commodore 64" (the names the Retro Game Dev books use, e.g. EXTCOL, SCROLX, CHROUT)."""
from __future__ import annotations

C64_NAMES: dict[int, str] = {
    # 6510 port
    0x0000: "D6510", 0x0001: "R6510",
    # system vectors and variables programs often touch
    0x0286: "COLOR", 0x0288: "HIBASE", 0x028D: "SHFLAG", 0x0314: "CINV", 0x0316: "CBINV", 0x0318: "NMINV",
    0x0326: "IBSOUT",
    # hardware vectors
    0xFFFA: "NMIVEC", 0xFFFC: "RESVEC", 0xFFFE: "IRQVEC",
}

# VIC-II
for _i in range(8):
    C64_NAMES[0xD000 + 2 * _i] = f"SP{_i}X"
    C64_NAMES[0xD001 + 2 * _i] = f"SP{_i}Y"
    C64_NAMES[0xD027 + _i] = f"SP{_i}COL"
C64_NAMES.update({
    0xD010: "MSIGX", 0xD011: "SCROLY", 0xD012: "RASTER", 0xD013: "LPENX", 0xD014: "LPENY", 0xD015: "SPENA",
    0xD016: "SCROLX", 0xD017: "YXPAND", 0xD018: "VMCSB", 0xD019: "VICIRQ", 0xD01A: "IRQMSK", 0xD01B: "SPBGPR",
    0xD01C: "SPMC", 0xD01D: "XXPAND", 0xD01E: "SPSPCL", 0xD01F: "SPBGCL", 0xD020: "EXTCOL", 0xD021: "BGCOL0",
    0xD022: "BGCOL1", 0xD023: "BGCOL2", 0xD024: "BGCOL3", 0xD025: "SPMC0", 0xD026: "SPMC1",
})
# SID
for _v, _base in ((1, 0xD400), (2, 0xD407), (3, 0xD40E)):
    for _o, _n in enumerate(("FRELO", "FREHI", "PWLO", "PWHI", "VCREG", "ATDCY", "SUREL")):
        C64_NAMES[_base + _o] = f"{_n}{_v}"
C64_NAMES.update({0xD415: "CUTLO", 0xD416: "CUTHI", 0xD417: "RESON", 0xD418: "SIGVOL", 0xD419: "POTX",
                  0xD41A: "POTY", 0xD41B: "RANDOM", 0xD41C: "ENV3"})
# CIA 1 and 2
for _o, (_a, _b) in enumerate((("CIAPRA", "CI2PRA"), ("CIAPRB", "CI2PRB"), ("CIDDRA", "C2DDRA"), ("CIDDRB", "C2DDRB"),
                               ("TIMALO", "TI2ALO"), ("TIMAHI", "TI2AHI"), ("TIMBLO", "TI2BLO"), ("TIMBHI", "TI2BHI"),
                               ("TODTEN", "TO2TEN"), ("TODSEC", "TO2SEC"), ("TODMIN", "TO2MIN"), ("TODHRS", "TO2HRS"),
                               ("CIASDR", "CI2SDR"), ("CIAICR", "CI2ICR"), ("CIACRA", "CI2CRA"), ("CIACRB", "CI2CRB"))):
    C64_NAMES[0xDC00 + _o] = _a
    C64_NAMES[0xDD00 + _o] = _b
# KERNAL jump table
C64_NAMES.update({
    0xFF81: "CINT", 0xFF84: "IOINIT", 0xFF87: "RAMTAS", 0xFF8A: "RESTOR", 0xFF8D: "VECTOR", 0xFF90: "SETMSG",
    0xFF93: "SECOND", 0xFF96: "TKSA", 0xFF99: "MEMTOP", 0xFF9C: "MEMBOT", 0xFF9F: "SCNKEY", 0xFFA2: "SETTMO",
    0xFFA5: "ACPTR", 0xFFA8: "CIOUT", 0xFFAB: "UNTLK", 0xFFAE: "UNLSN", 0xFFB1: "LISTEN", 0xFFB4: "TALK",
    0xFFB7: "READST", 0xFFBA: "SETLFS", 0xFFBD: "SETNAM", 0xFFC0: "OPEN", 0xFFC3: "CLOSE", 0xFFC6: "CHKIN",
    0xFFC9: "CHKOUT", 0xFFCC: "CLRCHN", 0xFFCF: "CHRIN", 0xFFD2: "CHROUT", 0xFFD5: "LOAD", 0xFFD8: "SAVE",
    0xFFDB: "SETTIM", 0xFFDE: "RDTIM", 0xFFE1: "STOP", 0xFFE4: "GETIN", 0xFFE7: "CLALL", 0xFFEA: "UDTIM",
    0xFFED: "SCREEN", 0xFFF0: "PLOT", 0xFFF3: "IOBASE",
})
