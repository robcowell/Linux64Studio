"""Styles of writing control codes in BASIC listings: {clear}, {clr} or {147}. CBM prg Studio
offers two, BasText and Tok64 (Preferences → BASIC code generation); Linux64Studio has its own
long names too. All three are read back whichever is chosen (petscii.py), so only the writing
differs.

* standard (Linux64Studio): {clear}, {reverse on}, {cbm-a}, {shift-+}, {$xx}; repeats {3 down}.
* tok64: as VICE's petcat writes them (petcat follows Tok64): {clr}, {rvon}, {wht}, {CBM-A},
  {SHIFT-POUND}, {CTRL-A}, {$xx}; £ and π as \\ and ~.
* bastext: long names, the Commodore, SHIFT and CTRL keys as {cm a}, {sh pound}, {ct a}, {pound},
  {arrow left}, and other codes as three decimal digits, {092}, as CBM prg Studio writes them.

The tok64 table is petcat's (checked against petcat itself in the tests). CBM prg Studio's
BasText table isn't published; these names are the ones its program uses (its strings: white,
reverse on, light blue, cm k, sh pound, ct a, pound, arrow left, sh space, sh return, lowercase,
escape, {092}...), applied to every code. In bastext and tok64 a run is written as CBM prg
Studio's Screen Code Builder writes it: {down*3}, and {a*3} for three of a letter.
"""
from __future__ import annotations

from .petscii import CBM_KEYS, SHIFT_KEYS, petscii_to_text

STYLES = {"standard": "Linux64Studio ({clear}, {cbm-a})", "bastext": "BasText ({clear}, {cm a})",
          "tok64": "Tok64, as VICE's petcat ({clr}, {CBM-A})"}

TOK64 = {
    0x03: "stop", 0x05: "wht", 0x08: "dish", 0x09: "ensh", 0x0E: "swlc", 0x11: "down", 0x12: "rvon",
    0x13: "home", 0x14: "del", 0x1B: "esc", 0x1C: "red", 0x1D: "rght", 0x1E: "grn", 0x1F: "blu",
    0x81: "orng", 0x85: "f1", 0x86: "f3", 0x87: "f5", 0x88: "f7", 0x89: "f2", 0x8A: "f4", 0x8B: "f6",
    0x8C: "f8", 0x8D: "sret", 0x8E: "swuc", 0x90: "blk", 0x91: "up", 0x92: "rvof", 0x93: "clr",
    0x94: "inst", 0x95: "brn", 0x96: "lred", 0x97: "gry1", 0x98: "gry2", 0x99: "lgrn", 0x9A: "lblu",
    0x9B: "gry3", 0x9C: "pur", 0x9D: "left", 0x9E: "yel", 0x9F: "cyn",
}
BASTEXT = {
    0x05: "white", 0x08: "switch off", 0x09: "switch on", 0x0E: "lowercase", 0x11: "down", 0x12: "reverse on",
    0x13: "home", 0x14: "delete", 0x1B: "escape", 0x1C: "red", 0x1D: "right", 0x1E: "green", 0x1F: "blue",
    0x5C: "pound", 0x5F: "arrow left", 0x81: "orange", 0x85: "f1", 0x86: "f3", 0x87: "f5", 0x88: "f7",
    0x89: "f2", 0x8A: "f4", 0x8B: "f6", 0x8C: "f8", 0x8D: "sh return", 0x8E: "uppercase", 0x90: "black",
    0x91: "up", 0x92: "reverse off", 0x93: "clear", 0x94: "insert", 0x95: "brown", 0x96: "pink",
    0x97: "dark grey", 0x98: "grey", 0x99: "light green", 0x9A: "light blue", 0x9B: "light grey",
    0x9C: "purple", 0x9D: "left", 0x9E: "yellow", 0x9F: "cyan", 0xA0: "sh space", 0xFF: "pi",
}
_SPOKEN = {"£": "pound", "*": "asterisk"}
for _k, _v in CBM_KEYS.items():
    TOK64.setdefault(_v, "CBM-" + ("POUND" if _k == "£" else _k.upper()))
    BASTEXT.setdefault(_v, "cm " + _SPOKEN.get(_k, _k))
for _k, _v in SHIFT_KEYS.items():
    if "a" <= _k <= "z" or _k == "^":
        continue                       # shifted letters are capitals; SHIFT-↑ is π
    TOK64.setdefault(_v, "SHIFT-" + ("POUND" if _k == "£" else _k.upper()))
    BASTEXT.setdefault(_v, "sh " + _SPOKEN.get(_k, _k))
for _c in range(1, 27):
    if _c not in (0x0A, 0x0D):        # petcat writes line feed and return by number
        TOK64.setdefault(_c, f"CTRL-{chr(0x40 + _c)}")
    BASTEXT.setdefault(_c, f"ct {chr(0x60 + _c)}")


def _literal(code: int) -> str | None:
    """A code written as itself: letters (shifted ones as capitals), digits and punctuation."""
    if 0x41 <= code <= 0x5A:
        return chr(code + 32)
    if 0xC1 <= code <= 0xDA:
        return chr(code - 0x80)
    if 0x20 <= code <= 0x40 and code != 0x22 or code in (0x5B, 0x5D, 0x5E):
        return chr(code)
    return None


def code_text(code: int, style: str = "standard") -> str:
    """One code, as it's written inside a string in this style."""
    if style == "standard":
        return petscii_to_text(code, True)
    lit = _literal(code)
    if style == "tok64":
        if lit is not None:
            return lit
        if code in (0x5C, 0x5F, 0xFF):
            return {0x5C: "\\", 0x5F: "_", 0xFF: "~"}[code]
        return "{" + TOK64[code] + "}" if code in TOK64 else f"{{${code:02x}}}"
    if code == 0x22:
        return "{034}"
    if code in BASTEXT:
        return "{" + BASTEXT[code] + "}"
    if lit is not None:
        return lit
    return f"{{{code:03d}}}"


def string_text(petscii: bytes, style: str = "standard") -> str:
    """A whole string, with runs written once and counted."""
    if style == "standard":
        parts = [petscii_to_text(p, True) if p != 0x22 else "{$22}" for p in petscii]
        out: list[list] = []
        for p in parts:
            if out and p.startswith("{") and out[-1][0] == p:
                out[-1][1] += 1
            else:
                out.append([p, 1])
        return "".join(p if n == 1 else f"{{{n} {p[1:-1]}}}" for p, n in out)
    runs: list[list] = []
    for p in petscii:
        if runs and runs[-1][0] == p:
            runs[-1][1] += 1
        else:
            runs.append([p, 1])
    text = []
    for p, n in runs:
        t = code_text(p, style)
        if p == 0x22 and style == "tok64":
            t = "{$22}"
        braced = t.startswith("{") and t.endswith("}")
        if n >= 2 and braced:
            text.append("{" + t[1:-1] + f"*{n}}}")
        elif n >= 3 and len(t) == 1 and t not in "{}*":
            text.append("{" + ("space" if t == " " else t) + f"*{n}}}")
        else:
            text.append(t * n)
    return "".join(text)
