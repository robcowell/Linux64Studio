"""Source File Converter (CBM prg Studio's External Tools → Source File Converter): turn sources
from other C64 assemblers into CBM prg Studio's dialect.

* Develop 64: a SEQ file (PETSCII text, a CR at the end of each line) or a text file.
* Genesis: a .prg, the source kept as a tokenized BASIC program (line numbers, and any keyword in
  it crunched: the OR in ORA, AND); it's listed back (BASIC V2's and BASIC 3.5's keywords) without
  the line numbers.
* TASM (Turbo Assembler): a text file.

Then each line's directives are put in CBM prg Studio's words (`.byte`/`BYT`/`dfb` → `byte`,
`.word`/`WOR` → `word`, `.text`/`.asc` → `text`, `ORG`/`.org` → `*=`, `EQU` → `=`, `.include` →
`incasm`, `.binary` → `incbin`, `.macro`/`.endm` → `defm`/`endm` with `\\1` → `/1`, `.rta x` → `word
x-1`, the conditionals), labels lose a trailing `:`, and PETSCII control codes in strings are written
`{codes}`. What CBM prg Studio's assembler has no use for (`.end`, listing control, `.block`) is
turned into a comment, and anything not understood is kept, with a note, for you to look at.

None of the three assemblers' manuals were to hand, so the rules follow what CBM prg Studio's own
converter shows of them and the assemblers' usual syntax; the converted file is assembled to check it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FORMATS = {"develop64": "Develop 64", "genesis": "Genesis", "tasm": "TASM (Turbo Assembler)"}

# BASIC 3.5's keywords after BASIC V2's ($CC-$FD), for listing Genesis files
BASIC35 = ["rgr", "rclr", "rlum", "joy", "rdot", "dec", "hex$", "err$", "instr", "else", "resume", "trap", "tron",
           "troff", "sound", "vol", "auto", "pudef", "graphic", "paint", "char", "box", "circle", "gshape",
           "sshape", "draw", "locate", "color", "scnclr", "scale", "help", "do", "loop", "exit", "directory",
           "dsave", "dload", "header", "scratch", "collect", "copy", "rename", "backup", "delete", "renumber",
           "key", "monitor", "using", "until", "while"]

DIRECTIVES = {
    "byte": "byte", "byt": "byte", "by": "byte", "db": "byte", "dfb": "byte", "dc.b": "byte",
    "word": "word", "wor": "word", "wo": "word", "dw": "word", "dc.w": "word", "addr": "word",
    "text": "text", "tx": "text", "asc": "text", "ascii": "text", "pet": "text", "petscii": "text", "txt": "text",
    "null": "null", "screen": "text", "scr": "text",
    "include": "incasm", "inc": "incasm", "lib": "incasm", "src": "incasm",
    "binary": "incbin", "bin": "incbin", "incbin": "incbin",
    "if": "if", "ifdef": "ifdef", "ifndef": "ifndef", "else": "else", "endif": "endif", "fi": "endif",
    "ifne": "if", "macro": "defm", "mac": "defm", "endm": "endm", "endmacro": "endm", "endmac": "endm",
    "align": "align", "dsb": "dcb", "fill": "dcb", "res": "dcb",
}
DROPPED = {"end", "block", "bend", "offs", "pron", "proff", "hidemac", "showmac", "page", "list", "nolist",
           "skip", "title", "sym", "nosym", "opt", "cpu", "setcpu", "bank", "local", "here", "eject"}


@dataclass
class Result:
    lines: list[str]
    notes: list[tuple[int, str]] = field(default_factory=list)      # (converted line, what to look at)

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


# ---------------------------------------------------------------- reading the files
def _petscii_line(data: bytes) -> str:
    """A line of PETSCII as source: letters lower case (upper for shifted), control codes {named}."""
    from .basic.petscii import CODE_TO_NAME
    out, in_q = [], False
    for b in data:
        if b == 0x22:
            in_q = not in_q
            out.append('"')
        elif 0x41 <= b <= 0x5A:
            out.append(chr(b + 32))
        elif 0xC1 <= b <= 0xDA:
            out.append(chr(b - 0x80))
        elif 0x20 <= b <= 0x40 or b in (0x5B, 0x5D):
            out.append(chr(b))
        elif b == 0x5C:
            out.append("£")
        elif b == 0x5E:
            out.append("^")
        elif b == 0x5F:
            out.append("_")
        elif b == 0xA0:
            out.append(" ")
        elif in_q:
            out.append("{" + CODE_TO_NAME.get(b, f"${b:02x}") + "}")
        elif b in (0x09,):
            out.append("        ")
    return "".join(out)


def _is_petscii(data: bytes) -> bool:
    """A SEQ (CR between lines, no LF) rather than a PC text file."""
    return b"\r" in data and b"\n" not in data


def read_develop64(data: bytes) -> list[str]:
    if _is_petscii(data):
        return [_petscii_line(ln) for ln in data.rstrip(b"\r").split(b"\r")]
    return data.decode("utf-8", errors="replace").splitlines()


def read_genesis(data: bytes) -> list[str]:
    """A tokenized BASIC program, listed back (V2 and BASIC 3.5 keywords), without line numbers."""
    from .basic.tokenizer import KEYWORDS
    if len(data) < 4:
        raise ValueError("The file is too short to be a program")
    start = data[0] | data[1] << 8
    mem = data[2:]
    words = list(KEYWORDS) + BASIC35
    out, off, guard = [], 0, 0
    while off + 4 <= len(mem):
        link = mem[off] | mem[off + 1] << 8
        if link == 0:
            break
        end = mem.find(b"\0", off + 4)
        if end < 0:
            raise ValueError("A line has no end: this isn't a tokenized program")
        body = bytearray()
        for b in mem[off + 4:end]:
            if 0x80 <= b < 0x80 + len(words):
                body += words[b - 0x80].upper().encode("latin-1")
            else:
                body.append(b)
        out.append(_petscii_line(bytes(body)))
        nxt = link - start
        off = nxt if nxt > off else end + 1
        guard += 1
        if guard > 20000:
            raise ValueError("The program's lines loop back on themselves")
    return out


def read_tasm(data: bytes) -> list[str]:
    if _is_petscii(data):
        return [_petscii_line(ln) for ln in data.rstrip(b"\r").split(b"\r")]
    return data.decode("utf-8", errors="replace").splitlines()


def read(path: Path, fmt: str) -> list[str]:
    data = Path(path).read_bytes()
    return {"develop64": read_develop64, "genesis": read_genesis, "tasm": read_tasm}[fmt](data)


# ---------------------------------------------------------------- converting lines
_SPLIT = re.compile(r'^(?P<code>(?:[^;"\']|"[^"]*"|\'[^\']*\')*)(?P<comment>;.*)?$')


def _directive(word: str) -> str | None:
    w = word.lower().lstrip(".!")
    return DIRECTIVES.get(w)


def convert_line(line: str, n: int, notes: list) -> list[str]:
    raw = line.rstrip()
    if not raw.strip():
        return [""]
    if raw.lstrip().startswith(("*", ";")) and not re.match(r"^\s*\*\s*=", raw):
        return [";" + raw.lstrip()[1:] if raw.lstrip().startswith("*") else raw]   # a whole-line comment
    m = _SPLIT.match(raw)
    code, comment = (m.group("code"), m.group("comment") or "") if m else (raw, "")
    comment = (" " + comment) if comment and code.strip() else comment
    label = ""
    rest = code
    if code and not code[0].isspace():
        lm = re.match(r"^([A-Za-z_@.][\w.@]*):?(.*)$", code)
        if lm:
            label, rest = lm.group(1), lm.group(2)
    rest = rest.strip()
    word, _, operand = rest.partition(" ")
    operand = operand.strip()
    low = word.lower().lstrip(".!")
    # label = value / label EQU value / .equ / .set
    if low in ("equ", "=", "set", "eqa") and label:
        return [f"{label} = {operand}{comment}"]
    if not word and label and re.match(r"^\s*=", code[len(label):].lstrip(":")):
        return [f"{label} {code[len(label):].lstrip(':').strip()}{comment}"]
    if low in ("org", "*=") or rest.startswith("*="):
        addr = operand if low == "org" else rest[2:].strip()
        out = [f"*={addr}{comment}"]
        return ([label] if label else []) + out
    lead = (label.ljust(8) if label else "        ")
    if label and len(label) >= 8:
        lead = label + " "
    if not word:
        return [(label + comment) if label else comment.lstrip()]
    if low == "rta":
        items = [f"{x.strip()}-1" for x in operand.split(",")]
        return [f"{lead}word {', '.join(items)}{comment}"]
    if low in DROPPED:
        notes.append((n, f"{word} has no use in CBM prg Studio: made a comment"))
        return [f"; {rest}{comment}"]
    d = _directive(word)
    if d is not None:
        if d == "defm":
            name = operand.split()[0].rstrip(",") if operand else (label or "macro")
            return [f"        defm {name}{comment}"]
        if d in ("incasm", "incbin") and operand and not operand.startswith('"'):
            operand = f'"{operand}"' if d == "incasm" else operand
        return [f"{lead}{d}{(' ' + operand) if operand else ''}{comment}"]
    if word.startswith(".") and len(word) > 1:
        notes.append((n, f"{word} isn't a directive CBM prg Studio knows: left as it was"))
        return [raw]
    # an instruction (or a macro call): macro parameters \1 / ?1 become /1
    operand = re.sub(r"[\\?](\d)", r"/\1", operand)
    return [f"{lead}{word.lower() if len(word) == 3 else word}{(' ' + operand) if operand else ''}{comment}"]


def convert(lines: list[str], fmt: str) -> Result:
    res = Result([f"; converted from {FORMATS[fmt]} by Linux64Studio"])
    for n, line in enumerate(lines, start=1):
        for out in convert_line(line, n, res.notes):
            res.lines.append(out)
    return res


def convert_file(path: Path, fmt: str) -> Result:
    return convert(read(path, fmt), fmt)


def check(text: str) -> list[str]:
    """What CBM prg Studio's assembler says about the converted source (errors only)."""
    from .asm.assembler import Assembler, Options
    try:
        r = Assembler(Options()).assemble_text(text)
    except Exception as e:
        return [str(e)]
    return [f"line {d.loc.line}: {d.message}" if d.loc else d.message for d in r.diagnostics if d.severity == "error"]
