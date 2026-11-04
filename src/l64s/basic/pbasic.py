"""pBASIC: CBM prg Studio's BASIC V2 without line numbers.

Jump targets are labels: a line holding only `@name` labels the line after it, and `goto @name`
(gosub, then, on ... goto, run, list) refers to it. Generating the program numbers every line from
a start and step, then puts the numbers in place of the labels. `namespace name` ... `namespace end`
makes the labels in between local to that block.

There are also the two editing tools CBM prg Studio has for turning a numbered program into
pBASIC: Create Label (name the line a jump goes to) and Remove Line Numbers.

Linux64Studio adds two things to CBM prg Studio's version: code in a namespace can use the
global labels (when it has no label of that name), and `@block.name` names a label in another
namespace.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .renumber import find_line_refs
from .tokenizer import KEYWORDS, MAX_LINE_NUMBER, BasicError, BasicErrors, parse_source

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_NUMBERED_RE = re.compile(r"^(\s*)(\d+)\s?(.*)$")
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+(\S+)\s*$", re.I)
_REGION = re.compile(r"^\s*#(end)?region\b", re.I)


@dataclass
class PBasicOptions:
    start: int = 10
    step: int = 10
    prefix: str = "@"


@dataclass
class PBasicResult:
    text: str                                   # the numbered BASIC program
    source_lines: list[int]                     # the pBASIC source line of each generated line
    labels: dict[str, int] = field(default_factory=dict)   # "name" or "block.name" -> line number
    warnings: list[BasicError] = field(default_factory=list)

    def source_line(self, generated_line: int | None) -> int | None:
        """The pBASIC line for a 1-based line of the generated text."""
        if generated_line and 1 <= generated_line <= len(self.source_lines):
            return self.source_lines[generated_line - 1]
        return generated_line


def _label_re(prefix: str) -> re.Pattern:
    return re.compile(rf"^\s*{re.escape(prefix)}({_NAME})\s*$")


def label_refs(body: str, prefix: str = "@") -> list[tuple[int, int, str]]:
    """The labels a line uses: (start, end, name), where start is at the prefix. Like the ROM's
    tokenizer, strings, REM and DATA are skipped, so a prefix there is just a character."""
    out: list[tuple[int, int, str]] = []
    low = body.lower()
    n, i = len(body), 0
    in_quote = in_data = False
    ref = re.compile(rf"{re.escape(prefix)}({_NAME}(?:\.{_NAME})?)")
    while i < n:
        ch = low[i]
        if ch == '"':
            in_quote = not in_quote
            i += 1
            continue
        if in_quote:
            i += 1
            continue
        if ch == "{":
            close = body.find("}", i)
            i = n if close == -1 else close + 1
            continue
        if in_data:
            in_data = ch != ":"
            i += 1
            continue
        if body.startswith(prefix, i):
            m = ref.match(body, i)
            if m:
                out.append((i, m.end(), m.group(1)))
                i = m.end()
                continue
        kw = next((k for k in KEYWORDS if low.startswith(k, i)), None)
        if kw is None:
            i += 1
            continue
        i += len(kw)
        if kw == "rem":
            break
        if kw == "data":
            in_data = True
    return out


def to_basic(text: str, options: PBasicOptions | None = None) -> PBasicResult:
    """Number a pBASIC program and put the line numbers in place of its labels.
    Raises BasicErrors (with pBASIC source lines) for everything wrong."""
    o = options or PBasicOptions()
    if o.start < 0 or o.step < 1:
        raise BasicErrors([BasicError("The pBASIC start line must be 0 or more and the step at least 1")])
    if not o.prefix or o.prefix.isalnum() or any(c.isspace() for c in o.prefix):
        raise BasicErrors([BasicError(f"{o.prefix!r} can't be the pBASIC label prefix")])
    label_re = _label_re(o.prefix)
    errors: list[BasicError] = []
    lines: list[tuple[str, int, str]] = []             # (code, source line, namespace)
    labels: dict[tuple[str, str], int] = {}            # (namespace, name) -> line number
    where: dict[tuple[str, str], int] = {}             # ... -> source line, for duplicates
    pending: list[tuple[tuple[str, str], int]] = []
    ns = ""
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or _REGION.match(line):     # an editor fold, not code
            continue
        m = _NAMESPACE_RE.match(line)
        if m:
            name = m.group(1)
            if name.lower() == "end":
                if not ns:
                    errors.append(BasicError("'namespace end' without a namespace", n))
                ns = ""
            elif not re.fullmatch(_NAME, name):
                errors.append(BasicError(f"{name!r} isn't a namespace name", n))
            else:
                if ns:
                    errors.append(BasicError(f"Namespace {name} starts inside namespace {ns} "
                                             f"(they can't be nested)", n))
                ns = name.lower()
            continue
        m = label_re.match(line)
        if m:
            key = (ns, m.group(1).lower())
            if key in where:
                errors.append(BasicError(f"Label {o.prefix}{m.group(1)} is defined twice "
                                         f"(also on line {where[key]})", n))
            else:
                where[key] = n
                pending.append((key, n))
            continue
        first = label_refs(line.lstrip(), o.prefix)[:1]
        if first and first[0][0] == 0:            # no statement starts with a label
            errors.append(BasicError(f"A label must be on a line of its own: put the code after "
                                     f"{line.split()[0]} on the next line", n))
            continue
        if _NUMBERED_RE.match(line):
            errors.append(BasicError("pBASIC lines don't have line numbers (right-click → Remove Line Numbers)",
                                     n))
            continue
        number = o.start + o.step * len(lines)
        for key, _src in pending:
            labels[key] = number
        pending = []
        lines.append((line.strip(), n, ns))
    for (_ns, name), src in pending:
        errors.append(BasicError(f"Label {o.prefix}{name} has no line after it", src))
    if ns:
        errors.append(BasicError(f"Namespace {ns} has no 'namespace end'", None))
    last = o.start + o.step * (len(lines) - 1)
    if lines and last > MAX_LINE_NUMBER:
        errors.append(BasicError(f"The program needs line {last}, above {MAX_LINE_NUMBER}; use a smaller "
                                 f"start or step", None))
    out: list[str] = []
    for i, (code, src, lns) in enumerate(lines):
        pieces, pos = [], 0
        for start, end, name in label_refs(code, o.prefix):
            low = name.lower()
            if "." in low:
                key = tuple(low.split(".", 1))
            else:
                key = (lns, low) if (lns, low) in labels else ("", low)
            if key not in labels:
                errors.append(BasicError(f"There's no label {o.prefix}{name}"
                                         + (f" in namespace {lns}" if lns and "." not in low else ""), src))
                continue
            pieces += [code[pos:start], str(labels[key])]
            pos = end
        pieces.append(code[pos:])
        out.append(f"{o.start + o.step * i} {''.join(pieces)}")
    if errors:
        raise BasicErrors(errors)
    names = {(f"{k[0]}.{k[1]}" if k[0] else k[1]): v for k, v in labels.items()}
    return PBasicResult("\n".join(out) + ("\n" if out else ""), [src for _c, src, _n in lines], names)


# ---------------------------------------------------------------------- editing tools
def _split(line: str) -> tuple[str, str, str] | None:
    """(indent and number, the gap, the code) for a numbered line, or None."""
    m = _NUMBERED_RE.match(line)
    return (m.group(1) + m.group(2), " " if line[m.end(2):m.start(3)] else "", m.group(3)) if m else None


def jump_target_at(line: str, column: int) -> int | None:
    """The line number a jump at `column` of this line goes to (the number under the cursor)."""
    parts = _split(line)
    head = len(parts[0]) + len(parts[1]) if parts else 0
    body = parts[2] if parts else line
    for r in find_line_refs(body):
        if head + r.start <= column <= head + r.end:
            return int(body[r.start:r.end])
    return None


def create_label(text: str, target: int, name: str, prefix: str = "@") -> tuple[str, int]:
    """Name line `target`: put a label line above it and the label in place of every jump to it.
    Returns (new text, how many jumps were changed)."""
    if not re.fullmatch(_NAME, name):
        raise BasicError(f"{name!r} isn't a label name: use letters, digits and _, starting with a letter")
    label_re = _label_re(prefix)
    lines = text.split("\n")
    at = None
    for i, line in enumerate(lines):
        m = label_re.match(line)
        if m and m.group(1).lower() == name.lower():
            nxt = next((j for j in range(i + 1, len(lines)) if lines[j].strip()), None)
            if nxt is None or (_split(lines[nxt]) or ("",))[0].strip() != str(target):
                raise BasicError(f"Label {prefix}{name} is already used for another line")
        parts = _split(line)
        if parts and int(parts[0]) == target and at is None:
            at = i
    if at is None:
        raise BasicError(f"There's no line {target}")
    changed = 0
    for i, line in enumerate(lines):
        if label_re.match(line):
            continue
        parts = _split(line)
        head, gap, body = parts if parts else ("", "", line)
        pieces, pos = [], 0
        for r in find_line_refs(body):
            if int(body[r.start:r.end]) == target:
                pieces += [body[pos:r.start], prefix + name]
                pos = r.end
                changed += 1
        if pos:
            pieces.append(body[pos:])
            lines[i] = head + gap + "".join(pieces)
    above = next((lines[j] for j in range(at - 1, -1, -1) if lines[j].strip()), "")
    m = label_re.match(above)
    if not (m and m.group(1).lower() == name.lower()):
        lines.insert(at, prefix + name)
    return "\n".join(lines), changed


def remove_line_numbers(text: str, prefix: str = "@") -> tuple[str, list[BasicError]]:
    """Take the line numbers off. Warns about jumps still going to a line number (they'd have
    nowhere to go), and, as CBM prg Studio does, when there are no labels at all."""
    label_re = _label_re(prefix)
    warnings: list[BasicError] = []
    out = []
    has_label = False
    for n, line in enumerate(text.split("\n"), start=1):
        if label_re.match(line):
            has_label = True
            out.append(line)
            continue
        parts = _split(line)
        body = parts[2] if parts else line
        for r in find_line_refs(body):
            warnings.append(BasicError(f"This line still jumps to line {body[r.start:r.end]}: "
                                       f"create a label for it first", n))
        out.append(body if parts else line)
    if not has_label:
        warnings.insert(0, BasicError("No labels are defined, so any GOTO or GOSUB has nowhere to go "
                                      "(fine if the program has no jumps)"))
    return "\n".join(out), warnings


def from_basic(text: str, prefix: str = "@") -> tuple[str, list[BasicError]]:
    """A whole numbered BASIC program as pBASIC: a label (`line100`) for every line a jump
    goes to, then no line numbers."""
    entries, warnings = parse_source(text)
    numbers = {num for num, _b, _s in entries}
    targets = set()
    for num, body, src in entries:
        for r in find_line_refs(body):
            t = int(body[r.start:r.end])
            if t in numbers:
                targets.add(t)
            else:
                warnings.append(BasicError(f"Line {num} jumps to line {t}, which doesn't exist", src))
    out = []
    for num, body, _src in entries:
        if num in targets:
            out.append(f"{prefix}line{num}")
        pieces, pos = [], 0
        for r in find_line_refs(body):
            t = int(body[r.start:r.end])
            if t in targets:
                pieces += [body[pos:r.start], f"{prefix}line{t}"]
                pos = r.end
        pieces.append(body[pos:])
        out.append("".join(pieces))
    return "\n".join(out) + "\n", warnings
