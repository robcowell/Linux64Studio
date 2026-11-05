"""Interactive disassembly: a session of marks (code/data), labels and comments over a binary,
producing a listing and source that reassembles to the same bytes."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .asm.opcodes import ILLEGAL_OPCODES, OPCODES
from .asm.source import DIRECTIVES
from .binconv import _ABS_TO_ZP, _BRANCH_END, _decode, _instruction_text, Binary
from .c64symbols import C64_NAMES

_RESERVED = {m.lower() for m in OPCODES} | {m.lower() for m in ILLEGAL_OPCODES} | {d.lower() for d in DIRECTIVES} | {"a", "x", "y"}
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class SessionError(ValueError):
    pass


@dataclass
class Line:
    addr: int
    size: int
    kind: str              # "code" or "data"
    label: str
    text: str              # instruction or data directive, as it goes in the source
    comment: str
    raw: bytes
    target: int | None = None   # where the operand points (for following jumps)


@dataclass
class Session:
    binary: Binary
    entries: list[int] = field(default_factory=list)
    trace: bool = True
    code_marks: set[int] = field(default_factory=set)        # addresses forced to start code
    data_ranges: list[tuple[int, int]] = field(default_factory=list)  # inclusive ranges forced to data
    labels: dict[int, str] = field(default_factory=dict)     # user labels (in or outside the binary)
    comments: dict[int, str] = field(default_factory=dict)
    use_c64_names: bool = True

    # ---------------------------------------------------------------- editing
    def in_range(self, a: int) -> bool:
        return self.binary.start <= a < self.binary.end

    def is_data(self, a: int) -> bool:
        return any(lo <= a <= hi for lo, hi in self.data_ranges)

    def mark_code(self, a: int):
        """Code from here: the rest of any data range around `a` stops being data."""
        for lo, hi in list(self.data_ranges):
            if lo <= a <= hi:
                self.data_ranges = _subtract(self.data_ranges, a, hi)
        self.code_marks.add(a)

    def mark_data(self, lo: int, hi: int):
        self.code_marks = {c for c in self.code_marks if not lo <= c <= hi}
        self.data_ranges = _merge(self.data_ranges + [(lo, hi)])

    def set_label(self, a: int, name: str):
        name = name.strip()
        if not name:
            self.labels.pop(a, None)
            return
        if not _NAME_RE.match(name):
            raise SessionError(f"'{name}' isn't a valid label: letters, digits and _, not starting with a digit")
        if name.lower() in _RESERVED:
            raise SessionError(f"'{name}' is a mnemonic, directive or register name")
        for other, n in self.labels.items():
            if other != a and n.lower() == name.lower():
                raise SessionError(f"'{name}' is already the label of ${other:04X}")
        if re.fullmatch(r"L[0-9A-Fa-f]{4}", name) and int(name[1:], 16) != a:
            raise SessionError(f"'{name}' looks like the automatic label of another address")
        self.labels[a] = name

    def set_comment(self, a: int, text: str):
        if text.strip():
            self.comments[a] = text.strip()
        else:
            self.comments.pop(a, None)

    # ---------------------------------------------------------------- analysis
    def code_addresses(self) -> set[int] | None:
        """Instruction starts found by tracing, or None in linear mode (everything decodable)."""
        if not self.trace:
            return None
        b = self.binary
        seen: set[int] = set()
        todo = [e for e in list(self.entries) + sorted(self.code_marks) if self.in_range(e)]
        while todo:
            a = todo.pop()
            while self.in_range(a) and a not in seen and not self.is_data(a):
                u = _decode(b.data, b.start, a - b.start)
                if u is None or any(x in seen or self.is_data(x) for x in range(a + 1, a + u.size)):
                    break
                seen.add(a)
                if u.mode == "rel" or (u.mnem in ("jsr", "jmp") and u.mode == "abs"):
                    todo.append(u.operand)
                if u.mnem in _BRANCH_END:
                    break
                a += u.size
        return seen

    def lines(self) -> list[Line]:
        b = self.binary
        mem = b.data
        code_at = self.code_addresses()
        units = []
        off = 0
        while off < len(mem):
            a = b.start + off
            u = None
            if not self.is_data(a) and (code_at is None or a in code_at):
                u = _decode(mem, b.start, off)
                if u is not None and any(self.is_data(x) for x in range(a, a + u.size)):
                    u = None
            if u is None:
                units.append((a, 1, None))
                off += 1
            else:
                units.append((a, u.size, u))
                off += u.size
        starts = {a: (size, u) for a, size, u in units}
        # automatic labels for targets inside the binary
        names: dict[int, str] = {}
        # entry points and code you marked are always labelled
        for e in list(self.entries) + sorted(self.code_marks):
            if self.in_range(e) and e in starts:
                names[e] = f"L{e:04X}"
        for a, size, u in units:
            if u and u.mode not in ("imp", "acc", "imm") and self.in_range(u.operand) and u.operand in starts:
                names.setdefault(u.operand, f"L{u.operand:04X}")
        # Standard C64 names: inside the binary they replace automatic labels (e.g. the KERNAL's
        # own jump table); outside, they're equates. Your own label names always win.
        taken = {n.lower() for n in self.labels.values()}
        self._c64 = {}
        if self.use_c64_names:
            self._c64 = {a: n for a, n in C64_NAMES.items() if n.lower() not in taken}
            for a in list(names):
                if a in self._c64:
                    names[a] = self._c64[a]
        names.update({a: n for a, n in self.labels.items()})
        self._names = names

        def name_for(v: int) -> str | None:
            if v in names and (not self.in_range(v) or v in starts):
                return names[v]
            if not self.in_range(v) and v in self._c64:
                return self._c64[v]
            return None

        def operand_text(u) -> str:
            v = u.operand
            n = name_for(v)
            if n:
                return n
            for back in (1, 2):
                base = v - back
                if base in starts and starts[base][0] > back and name_for(base):
                    return f"{name_for(base)}+{back}"
            return f"${v:02X}" if u.mode in ("zp", "zpx", "zpy", "izx", "izy") else f"${v:04X}"

        out: list[Line] = []
        i = 0
        while i < len(units):
            a, size, u = units[i]
            label = names.get(a, "")
            comment = self.comments.get(a, "")
            if u is None:
                run = [units[i]]
                while (i + len(run) < len(units) and units[i + len(run)][2] is None and len(run) < 8
                       and units[i + len(run)][0] not in names and units[i + len(run)][0] not in self.comments):
                    run.append(units[i + len(run)])
                raw = bytes(mem[x[0] - b.start] for x in run)
                out.append(Line(a, len(run), "data", label, "byte " + ", ".join(f"${x:02X}" for x in raw), comment, raw))
                i += len(run)
                continue
            raw = bytes(mem[a - b.start:a - b.start + size])
            text = _instruction_text(u, operand_text)
            target = u.operand if u.mode not in ("imp", "acc", "imm") else None
            if u.mode in _ABS_TO_ZP and u.operand < 0x100 and _ABS_TO_ZP[u.mode] in OPCODES[u.mnem]:
                # an assembler would choose zero page: keep the bytes, show the instruction
                comment = (text + " (absolute)") + (f"  {comment}" if comment else "")
                text = "byte " + ", ".join(f"${x:02X}" for x in raw)
            out.append(Line(a, size, "code", label, text, comment, raw, target))
            i += 1
        return out

    def xrefs(self) -> dict[int, list[int]]:
        """address -> instructions that refer to it."""
        refs: dict[int, list[int]] = {}
        for ln in self.lines():
            if ln.target is not None:
                refs.setdefault(ln.target, []).append(ln.addr)
        return refs

    # ---------------------------------------------------------------- output
    def source(self, kickass: bool = False, syntax: str | None = None) -> str:
        """The disassembly as source: CBM prg Studio's or Kick Assembler's, or ca65's (for a C
        project too: code that's been disassembled can only be assembler)."""
        from .syntax import CA65, C, resolve
        ca65 = resolve(syntax, kickass) in (CA65, C)
        if ca65:
            kickass = False
        lines = self.lines()
        b = self.binary
        c = "//" if kickass else ";"
        out = [f"{c} {b.name or 'binary'}: ${b.start:04X}-${b.end - 1:04X}, disassembled by Linux64Studio", ""]
        # Names used for addresses outside the binary become equates.
        used: dict[str, int] = {}
        for ln in lines:
            if ln.target is None or self.in_range(ln.target):
                continue
            for v in (ln.target, ln.target - 1, ln.target - 2):
                n = self.labels.get(v) or self._c64.get(v)
                if n and not self.in_range(v) and re.search(rf"\b{re.escape(n)}\b", ln.text):
                    used[n] = v
        if used:
            for n, v in sorted(used.items(), key=lambda kv: kv[1]):
                val = f"${v:02X}" if v < 0x100 else f"${v:04X}"
                out.append(f".const {n} = {val}" if kickass else f"{n:<15} = {val}")
            out.append("")
        if ca65:
            out.append(f"        .org ${b.start:04X}          ; assembled for this address")
        else:
            out.append(f"*= ${b.start:04X}" if kickass else f"*=${b.start:04X}")
        out.append("")
        for ln in lines:
            text = ln.text
            if ca65 and text.startswith("byte "):
                text = "." + text
            if kickass:
                if text.startswith("byte "):
                    text = "." + text
                elif text.endswith(" a") and text.split()[0] in ("asl", "lsr", "rol", "ror"):
                    text = text[:-2]    # Kick Assembler writes accumulator mode without the "a"
            head = (f"{ln.label}:" if kickass or ca65 else ln.label) if ln.label else ""
            if len(head) >= 8:
                out.append(head)
                head = ""
            row = f"{head:<8}{text}"
            if ln.comment:
                row = f"{row:<40}{c} {ln.comment}"
            out.append(row.rstrip())
        return "\n".join(out) + "\n"

    # ---------------------------------------------------------------- saving
    def to_json(self) -> str:
        return json.dumps({
            "start": self.binary.start, "entries": self.entries, "trace": self.trace,
            "code_marks": sorted(self.code_marks), "data_ranges": self.data_ranges,
            "labels": {f"{a:04X}": n for a, n in sorted(self.labels.items())},
            "comments": {f"{a:04X}": t for a, t in sorted(self.comments.items())},
            "use_c64_names": self.use_c64_names,
        }, indent=1)

    def apply_json(self, text: str):
        d = json.loads(text)
        self.entries = [int(e) for e in d.get("entries", self.entries)]
        self.trace = bool(d.get("trace", True))
        self.code_marks = {int(c) for c in d.get("code_marks", [])}
        self.data_ranges = [tuple(r) for r in d.get("data_ranges", [])]
        self.labels = {int(a, 16): n for a, n in d.get("labels", {}).items()}
        self.comments = {int(a, 16): t for a, t in d.get("comments", {}).items()}
        self.use_c64_names = bool(d.get("use_c64_names", True))


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _subtract(ranges: list[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    out = []
    for a, b in ranges:
        if b < lo or a > hi:
            out.append((a, b))
            continue
        if a < lo:
            out.append((a, lo - 1))
        if b > hi:
            out.append((hi + 1, b))
    return out


def sidecar_path(binary_file: Path) -> Path:
    """Where a session for a file is kept: next to it, as <name>.l64dis."""
    return binary_file.with_name(binary_file.name + ".l64dis")
