"""Commodore BASIC's 5-byte floating point format (MFLPT), as CBM prg Studio's `fltp` directive
and BASIC variables store numbers.

Byte 0 is the exponent + 128 (0 means the value is 0). Bytes 1-4 are the mantissa, high byte
first, as a fraction 0.1xxx... in binary: its top bit is always 1, so that bit holds the sign
instead (1 = negative). value = mantissa * 2^(exponent - 128), with 0.5 <= mantissa < 1.
1.0 is 81 00 00 00 00 and pi is 82 49 0F DA A2.
"""
from __future__ import annotations

import math

LARGEST = 1.70141183e38       # BASIC's largest number (about 2^127)


class FloatError(ValueError):
    pass


def to_cbm(value: float) -> bytes:
    if math.isnan(value) or math.isinf(value):
        raise FloatError(f"{value} can't be stored as a C64 number")
    if value == 0:
        return bytes(5)
    negative = value < 0
    m, e = math.frexp(abs(value))          # abs(value) = m * 2^e, 0.5 <= m < 1
    mant = round(m * 2 ** 32)
    if mant == 2 ** 32:                     # rounded up to 1.0
        mant >>= 1
        e += 1
    exp = e + 128
    if exp > 255:
        raise FloatError(f"{value} is too large for a C64 number (the largest is about {LARGEST:.8g})")
    if exp < 1:
        return bytes(5)                     # too small: BASIC stores it as 0
    b = mant.to_bytes(4, "big")
    return bytes([exp, (b[0] & 0x7F) | (0x80 if negative else 0)]) + b[1:]


def from_cbm(data: bytes) -> float:
    if len(data) != 5:
        raise FloatError("A C64 number is 5 bytes")
    if data[0] == 0:
        return 0.0
    mant = int.from_bytes(bytes([data[1] | 0x80]) + data[2:5], "big")
    v = mant / 2 ** 32 * 2.0 ** (data[0] - 128)
    return -v if data[1] & 0x80 else v
