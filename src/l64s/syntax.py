"""The four kinds of source the code tools write: CBM prg Studio's assembler, Kick Assembler's, ca65's
(cc65's assembler) and C (cc65). Each tool used to choose between the first two with a ``kickass``
flag; ``resolve`` turns that flag (or a syntax name) into one of these, and ``table`` writes a data
table in any of them, the way each one's programs are written:

CBM::

    ; comment
    label
            byte $00, $18

Kick::

    // comment
    label:
        .byte $00, $18

ca65::

    ; comment
    label:
            .byte $00, $18

C::

    // comment
    const unsigned char label[2] = {
        0x00, 0x18
    };
"""
from __future__ import annotations

CBM, KICK, CA65, C = "cbm", "kick", "ca65", "c"
SYNTAXES = (CBM, KICK, CA65, C)
NAMES = {CBM: "CBM prg Studio", KICK: "Kick Assembler", CA65: "ca65", C: "C"}


def resolve(syntax: str | None = None, kickass: bool = False) -> str:
    """The syntax to write: ``syntax`` if given, else Kick or CBM as the old ``kickass`` flag says."""
    if syntax in SYNTAXES:
        return syntax
    return KICK if kickass else CBM


def is_asm(syntax: str) -> bool:
    return syntax != C


def comment(syntax: str, text: str) -> str:
    return ("// " if syntax in (KICK, C) else "; ") + text


def indent(syntax: str) -> str:
    return "    " if syntax in (KICK, C) else "        "


def label_line(syntax: str, name: str) -> str | None:
    """The line that puts a label on what follows (none for C: the array is named instead)."""
    if not name or syntax == C:
        return None
    return name if syntax == CBM else f"{name}:"


def directive(syntax: str, width: int = 1) -> str:
    word = "byte" if width == 1 else "word"
    return word if syntax == CBM else "." + word


def origin(syntax: str, address: int) -> str:
    """Where the code goes. ca65 and C programs are placed by the linker, so for them it's a comment."""
    if syntax == CBM:
        return f"*=${address:04X}"
    if syntax == KICK:
        return f"*= ${address:04X}"
    return comment(syntax, f"(at ${address:04X}: the linker places it)")


def number(value: int, width: int = 1, radix: str = "hex", syntax: str = CBM) -> str:
    """A value as the syntax writes it: $1F / 0x1F, decimal, %00011111 (C has no binary: hex). ca65
    takes no negative .byte/.word, so there a negative value is its two's complement ($FC18 for -1000)."""
    if value < 0 and syntax == CA65:
        value &= (1 << 8 * width) - 1
        if radix == "dec":
            radix = "hex"
    if radix == "dec" or value < 0:
        return str(value)
    digits = 2 if width == 1 else 4
    if radix == "bin" and syntax != C:
        return "%" + format(value & ((1 << 8 * width) - 1), f"0{8 * width}b")
    return (f"0x{value:0{digits}X}" if syntax == C else f"${value:0{digits}X}")


def c_type(values, width: int = 1) -> str:
    """The C element type for the values: unsigned unless any is negative."""
    negative = any(v < 0 for v in values)
    if width == 1:
        return "signed char" if negative else "unsigned char"
    return "int" if negative else "unsigned int"


def table(syntax: str, label: str, values, width: int = 1, per_line: int = 16, radix: str = "hex",
          comment_text: str | None = None, row_comments: list[str] | None = None) -> str:
    """A data table: ``values`` (bytes or words) ``per_line`` to a line, with an optional comment
    first and one per line after (``row_comments``, e.g. "char 3")."""
    values = list(values)
    per = max(1, per_line)
    rows = [values[i:i + per] for i in range(0, len(values), per)]
    out = []
    if comment_text:
        out.append(comment(syntax, comment_text))
    if syntax == C:
        name = label or "data"
        out.append(f"const {c_type(values, width)} {name}[{len(values)}] = {{")
        for n, row in enumerate(rows):
            line = "    " + ", ".join(number(v, width, radix, C) for v in row) + ("," if n < len(rows) - 1 else "")
            if row_comments and n < len(row_comments) and row_comments[n]:
                line += f"    /* {row_comments[n]} */"
            out.append(line)
        out.append("};")
        return "\n".join(out) + "\n"
    lab = label_line(syntax, label)
    if lab:
        out.append(lab)
    ind, d = indent(syntax), directive(syntax, width)
    for n, row in enumerate(rows):
        line = f"{ind}{d} " + ", ".join(number(v, width, radix, syntax) for v in row)
        if row_comments and n < len(row_comments) and row_comments[n]:
            line += " " + comment(syntax, row_comments[n])
        out.append(line)
    return "\n".join(out) + "\n"


def for_file(path, project_syntax: str = CBM) -> str:
    """The syntax a source file name means: .c/.h C, .s/.inc ca65 (cc65's assembler), anything else
    the project's own assembler (CBM or Kick)."""
    from pathlib import Path
    sfx = Path(path).suffix.lower()
    if sfx in (".c", ".h"):
        return C
    if sfx in (".s", ".inc"):
        return CA65
    return project_syntax if project_syntax in (CBM, KICK) else CBM


def identifier(name: str) -> str:
    """A name usable as a label or C identifier: my-sprites -> my_sprites."""
    import re
    ident = re.sub(r"\W", "_", name) or "data"
    return ident if not ident[0].isdigit() else "_" + ident
