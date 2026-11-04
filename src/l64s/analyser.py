"""Source Analyser: statistics about the instructions in assembler source, as CBM prg Studio's
tool gives: instruction counts, addressing modes and estimated cycle times.

For CBM prg Studio syntax the instructions come from Linux64Studio's assembler, so the
addressing modes are the real ones (zero page or absolute, after labels are known) and a macro's
instructions are counted at each line that uses it. For Kick Assembler source, which this
assembler can't build, the instructions are read from the source text: a label's value isn't
known there, so an operand that isn't a number up to $FF counts as absolute.

Cycles are static: each instruction counts once, with its base cycles and its maximum (a page
crossed by abs,X / abs,Y / (zp),Y reads, or a branch taken to another page).
"""
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .asm.opcodes import ILLEGAL_OPCODES, OPCODES

MODE_NAMES = {
    "imp": "implied", "acc": "accumulator", "imm": "immediate", "zp": "zero page", "zpx": "zero page,x",
    "zpy": "zero page,y", "abs": "absolute", "abx": "absolute,x", "aby": "absolute,y", "ind": "indirect",
    "izx": "indexed indirect (zp,x)", "izy": "indirect indexed (zp),y", "rel": "relative",
}
ZERO_PAGE_MODES = {"zp", "zpx", "zpy", "izx", "izy"}
BRANCHES = {"bcc", "bcs", "beq", "bmi", "bne", "bpl", "bvc", "bvs"}

CATEGORIES = {
    "Load / Store": "lda ldx ldy sta stx sty lax sax",
    "Arithmetic": "adc sbc inc dec inx iny dex dey isc dcp",
    "Logic": "and ora eor bit",
    "Shift / Rotate": "asl lsr rol ror slo rla sre rra",
    "Compare": "cmp cpx cpy",
    "Jump / Call": "jmp jsr rts rti " + " ".join(sorted(BRANCHES)),
    "Register Transfer": "tax tay txa tya tsx txs pha pla php plp",
    "Flags": "clc cld cli clv sec sed sei",
    "System": "brk nop",
}
CATEGORY_OF = {m: cat for cat, ms in CATEGORIES.items() for m in ms.split()}

_READS = set("adc and cmp eor lda ora sbc ldx ldy lax nop".split())        # +1 when a page is crossed
_STORES = set("sta stx sty sax".split())
_RMW = set("asl lsr rol ror inc dec slo rla sre rra dcp isc".split())


def cycles(mnemonic: str, mode: str) -> tuple[int, int]:
    """(base, maximum) cycles for an instruction."""
    m = mnemonic.lower()
    if m in BRANCHES:
        return 2, 4
    fixed = {"pha": 3, "php": 3, "pla": 4, "plp": 4, "rts": 6, "rti": 6, "brk": 7, "jsr": 6}
    if m in fixed:
        return fixed[m], fixed[m]
    if m == "jmp":
        return (5, 5) if mode == "ind" else (3, 3)
    if mode in ("imp", "acc", "imm"):
        return 2, 2
    if m in _RMW:
        c = {"zp": 5, "zpx": 6, "abs": 6, "abx": 7, "aby": 7, "izx": 8, "izy": 8}[mode]
        return c, c
    if m in _STORES:
        c = {"zp": 3, "zpx": 4, "zpy": 4, "abs": 4, "abx": 5, "aby": 5, "izx": 6, "izy": 6}[mode]
        return c, c
    base = {"zp": 3, "zpx": 4, "zpy": 4, "abs": 4, "abx": 4, "aby": 4, "izx": 6, "izy": 5}[mode]
    extra = 1 if m in _READS and mode in ("abx", "aby", "izy") else 0
    return base, base + extra


_OPCODE_TABLE = {code: (m, mode) for table in (OPCODES, ILLEGAL_OPCODES) for m, modes in table.items()
                 for mode, code in modes.items()}


def opcode(mnemonic: str, mode: str) -> int | None:
    return (OPCODES.get(mnemonic) or ILLEGAL_OPCODES.get(mnemonic) or {}).get(mode)


@dataclass
class Instr:
    file: str
    line: int
    mnemonic: str
    mode: str
    source: str = ""

    @property
    def opcode(self) -> int | None:
        return opcode(self.mnemonic, self.mode)

    @property
    def cycles(self) -> tuple[int, int]:
        return cycles(self.mnemonic, self.mode)


@dataclass
class Invalid:
    file: str
    line: int
    source: str
    reason: str


# ---------------------------------------------------------------------- from the assembler

def from_listing(listing, only: dict[str, tuple[int, int] | None] | None = None) -> list[Instr]:
    """Instructions from an assembler listing. A macro's instructions are counted at the line
    that uses the macro. `only` limits it to some files ({path: None} for all of a file, or
    {path: (first line, last line)})."""
    out = []
    for e in listing:
        if e.kind != "instr" or not e.data:
            continue
        hit = _OPCODE_TABLE.get(e.data[0])
        if not hit:
            continue
        where = e.called_from or e.loc
        if only is not None:
            key = str(Path(where.file).resolve())
            if key not in only:
                continue
            rng = only[key]
            if rng and not rng[0] <= where.line <= rng[1]:
                continue
        out.append(Instr(str(where.file), where.line, hit[0], hit[1], e.source.strip()))
    return out


# ---------------------------------------------------------------------- from source text (Kick Assembler)

_ALL_MNEMONICS = set(OPCODES) | set(ILLEGAL_OPCODES)


def _strip_comments(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return [re.split(r"//|;", line, maxsplit=1)[0] for line in text.split("\n")]


def _number(t: str) -> int | None:
    t = t.strip()
    try:
        if t.startswith("$"):
            return int(t[1:], 16)
        if t.startswith("%"):
            return int(t[1:], 2)
        if t.isdigit():
            return int(t)
    except ValueError:
        pass
    return None


def _mode(mn: str, operand: str, symbols: dict[str, int]) -> str | None:
    op = operand.strip()
    modes = OPCODES.get(mn) or ILLEGAL_OPCODES.get(mn) or {}
    if not op or op.lower() == "a":
        return "acc" if "acc" in modes else "imp"
    if "rel" in modes:
        return "rel"
    if op.startswith("#"):
        return "imm"

    def small(expr: str) -> bool:
        e = expr.strip()
        if e.startswith("<") or e.startswith(">"):
            return True
        v = _number(e)
        if v is None:
            v = symbols.get(e.lower())
        return v is not None and v <= 0xFF

    m = re.fullmatch(r"\((.+),\s*[xX]\s*\)", op)
    if m:
        return "izx"
    m = re.fullmatch(r"\((.+)\)\s*,\s*[yY]", op)
    if m:
        return "izy"
    if re.fullmatch(r"\(.+\)", op) and mn == "jmp":
        return "ind"
    m = re.fullmatch(r"(.+?)\s*,\s*([xXyY])", op)
    if m:
        reg = m.group(2).lower()
        zp, ab = ("zpx", "abx") if reg == "x" else ("zpy", "aby")
        return zp if small(m.group(1)) and zp in modes else ab
    return "zp" if small(op) and "zp" in modes else "abs"


def from_text(text: str, filename: str, symbols: dict[str, int] | None = None,
              lines: tuple[int, int] | None = None) -> tuple[list[Instr], list[Invalid]]:
    """Instructions read from source text (either syntax). Labels and directives are skipped;
    a line that starts like an instruction but can't be one is reported as invalid."""
    syms = {k.lower(): v for k, v in (symbols or {}).items()}
    out, bad = [], []
    for n, line in enumerate(_strip_comments(text), start=1):
        if lines and not lines[0] <= n <= lines[1]:
            continue
        code = line.strip()
        if not code:
            continue
        # labels: "name:" or "!name:" (Kick Assembler), or a name in column 1 (CBM)
        code = re.sub(r"^!?[A-Za-z_@][\w.@]*:\s*", "", code)
        words = code.split(None, 1)
        if not words:
            continue
        first = words[0].lower()
        if first not in _ALL_MNEMONICS and not line[:1].isspace() and len(words) > 1:
            rest = words[1].split(None, 1)
            first, words = rest[0].lower(), rest              # a CBM label in column 1
        mn = first.split(".")[0]                               # Kick Assembler's lda.abs etc.
        if mn not in _ALL_MNEMONICS:
            continue
        operand = words[1] if len(words) > 1 else ""
        mode = _mode(mn, operand, syms)
        if mode is None or opcode(mn, mode) is None:
            bad.append(Invalid(filename, n, line.strip(), f"{mn.upper()} has no {MODE_NAMES.get(mode, mode)} mode"))
            continue
        if first.endswith(".abs") and mode.startswith("zp"):
            mode = {"zp": "abs", "zpx": "abx", "zpy": "aby"}[mode]
        out.append(Instr(filename, n, mn, mode, line.strip()))
    return out, bad


# ---------------------------------------------------------------------- statistics

@dataclass
class Report:
    instrs: list[Instr]
    invalid: list[Invalid] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    method: str = "assembled"            # or "source text"

    def counts(self) -> Counter:
        return Counter((i.mnemonic, i.mode) for i in self.instrs)

    def by_mnemonic(self) -> Counter:
        return Counter(i.mnemonic for i in self.instrs)

    def by_mode(self) -> Counter:
        return Counter(i.mode for i in self.instrs)

    def by_category(self) -> Counter:
        return Counter(CATEGORY_OF.get(i.mnemonic, "System") for i in self.instrs)

    def cycles_by_mnemonic(self) -> Counter:
        c = Counter()
        for i in self.instrs:
            c[i.mnemonic] += i.cycles[0]
        return c

    def cycle_distribution(self) -> Counter:
        return Counter(i.cycles[0] for i in self.instrs)

    def by_file(self) -> dict[str, tuple[int, int, int]]:
        """file -> (instructions, base cycles, max cycles)."""
        d = defaultdict(lambda: [0, 0, 0])
        for i in self.instrs:
            b, m = i.cycles
            d[i.file][0] += 1
            d[i.file][1] += b
            d[i.file][2] += m
        return {f: tuple(v) for f, v in d.items()}

    def metrics(self) -> list[tuple[str, str]]:
        n = len(self.instrs)
        base = sum(i.cycles[0] for i in self.instrs)
        mx = sum(i.cycles[1] for i in self.instrs)
        memory = [i for i in self.instrs if i.mode not in ("imp", "acc", "imm", "rel")]
        zp = sum(1 for i in memory if i.mode in ZERO_PAGE_MODES)
        mn = self.by_mnemonic().most_common(1)
        top = self.cycles_by_mnemonic().most_common(1)

        def pct(a, b):
            return f"{a} ({100 * a / b:.1f}%)" if b else str(a)
        return [
            ("Files analysed", str(len(self.files) or len({i.file for i in self.instrs}))),
            ("Instructions", str(n)),
            ("Unique mnemonics", str(len(self.by_mnemonic()))),
            ("Unique opcodes", str(len(self.counts()))),
            ("Average base cycles", f"{base / n:.2f}" if n else "0"),
            ("Average maximum cycles", f"{mx / n:.2f}" if n else "0"),
            ("Estimated base cycles", str(base)),
            ("Estimated maximum cycles", str(mx)),
            ("Zero-page usage", pct(zp, len(memory)) + " of the instructions that use memory"),
            ("Branch instructions", pct(sum(1 for i in self.instrs if i.mnemonic in BRANCHES), n)),
            ("Variable timing", pct(sum(1 for i in self.instrs if i.cycles[1] > i.cycles[0]), n)),
            ("Subroutine calls", str(sum(1 for i in self.instrs if i.mnemonic == "jsr"))),
            ("Returns", str(sum(1 for i in self.instrs if i.mnemonic in ("rts", "rti")))),
            ("Most used instruction", f"{mn[0][0].upper()} ({mn[0][1]})" if mn else "-"),
            ("Largest cycle consumer", f"{top[0][0].upper()} ({top[0][1]} cycles)" if top else "-"),
            ("Invalid instructions", str(len(self.invalid))),
        ]

    def rows(self) -> list[tuple[str, str, int | None, int, int, int]]:
        """(mnemonic, mode, opcode, count, base cycles, max cycles), most used first."""
        out = []
        for (m, mode), count in self.counts().most_common():
            b, x = cycles(m, mode)
            out.append((m, mode, opcode(m, mode), count, b, x))
        return out


# ---------------------------------------------------------------------- export

def to_text(r: Report, title: str = "Source analysis") -> str:
    out = [title, "=" * len(title), f"(from the {r.method} code)", ""]
    w = max((len(k) for k, _ in r.metrics()), default=10)
    out += [f"{k:<{w}}  {v}" for k, v in r.metrics()]
    out += ["", "Instruction  Mode                        Opcode  Count  Cycles  Max  Total",
            "-----------  --------------------------  ------  -----  ------  ---  -----"]
    for m, mode, op, count, b, x in r.rows():
        opc = f"${op:02X}" if op is not None else "-"
        out.append(f"{m.upper():<11}  {MODE_NAMES[mode]:<26}  {opc:<6}  {count:>5}  {b:>6}  {x:>3}  {count * b:>5}")
    out += ["", "By file", "-------"]
    for f, (n, b, x) in sorted(r.by_file().items()):
        out.append(f"{Path(f).name}: {n} instructions, {b} to {x} cycles")
    if r.invalid:
        out += ["", "Invalid", "-------"] + [f"{Path(i.file).name}:{i.line}: {i.source}  ({i.reason})" for i in r.invalid]
    return "\n".join(out) + "\n"


def to_html(r: Report, title: str = "Source analysis") -> str:
    e = html.escape

    def table(head, rows):
        h = "".join(f"<th>{e(c)}</th>" for c in head)
        body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)}</title>",
             "<style>body{font-family:sans-serif;margin:2em}table{border-collapse:collapse;margin:1em 0}"
             "td,th{border:1px solid #bbb;padding:3px 8px;text-align:left}th{background:#eee}</style></head><body>",
             f"<h1>{e(title)}</h1><p>From the {e(r.method)} code.</p>",
             "<h2>Metrics</h2>", table(["Metric", "Value"], r.metrics()),
             "<h2>Instructions</h2>",
             table(["Instruction", "Mode", "Opcode", "Count", "Cycles", "Max", "Total"],
                   [(m.upper(), MODE_NAMES[mode], f"${op:02X}" if op is not None else "-", c, b, x, c * b)
                    for m, mode, op, c, b, x in r.rows()]),
             "<h2>By file</h2>",
             table(["File", "Instructions", "Base cycles", "Max cycles"],
                   [(Path(f).name, n, b, x) for f, (n, b, x) in sorted(r.by_file().items())])]
    if r.invalid:
        parts += ["<h2>Invalid</h2>", table(["File", "Line", "Source", "Why"],
                                            [(Path(i.file).name, i.line, i.source, i.reason) for i in r.invalid])]
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------- analysing a project, file or selection

ASM_EXTS = {".asm", ".s", ".a", ".inc", ".a65"}


class AnalyseError(ValueError):
    pass


def analyse(files: list[Path], overrides: dict[str, str] | None = None, kickass: bool = False,
            scope: Path | None = None, lines: tuple[int, int] | None = None, padding_byte: int = 0) -> Report:
    """Analyse assembler files (a project's build list, in order). With `scope`, count only that
    file (and with `lines`, only those lines of it); the whole list is still assembled, so
    labels and macros from the other files are known."""
    from .asm.assembler import Assembler, Options
    overrides = overrides or {}
    asm = [Path(f) for f in files if Path(f).suffix.lower() in ASM_EXTS]
    if scope is not None and scope.resolve() not in {f.resolve() for f in asm}:
        asm = [scope]                                   # not in the build: analyse it on its own
    if not asm:
        raise AnalyseError("There are no assembler files to analyse")

    def text_of(p: Path) -> str:
        return overrides.get(str(p), None) or p.read_text(encoding="utf-8", errors="replace")

    targets = [scope] if scope is not None else asm
    note = ""
    symbols: dict[str, int] = {}
    for f in asm:                                  # constants from every file, for zero page vs absolute
        try:
            symbols.update(constants(text_of(f)))
        except OSError:
            pass
    if not kickass:
        res = Assembler(Options(padding_byte=padding_byte)).assemble_files(asm, overrides)
        if res.ok:
            only = {str(t.resolve()): lines for t in targets}
            return Report(from_listing(res.listing, only), files=[str(t) for t in targets], method="assembled")
        first = next((d for d in res.diagnostics if d.severity == "error"), None)
        note = f" (it doesn't assemble: {first})" if first else " (it doesn't assemble)"
    instrs, invalid = [], []
    for t in targets:
        i, bad = from_text(text_of(t), str(t), symbols, lines=lines)
        instrs += i
        invalid += bad
    return Report(instrs, invalid, files=[str(t) for t in targets], method="source text" + note)


_CONST = re.compile(r"^\s*(?:\.(?:const|label|var)\s+)?([A-Za-z_][\w]*)\s*(?:=|\bequ\b)\s*([$%]?[0-9A-Fa-f]+)\s*$",
                    re.I | re.M)


def constants(text: str) -> dict[str, int]:
    """Names given a plain number: .const/.label/.var NAME = value, or NAME = value / NAME equ value."""
    out = {}
    for line in _strip_comments(text):
        m = _CONST.match(line)
        if m:
            v = _number(m.group(2))
            if v is not None:
                out[m.group(1).lower()] = v
    return out


_IMPORT = re.compile(r'^\s*(?:#import|#include|\.import\s+source)\s+"([^"]+)"', re.M | re.I)


def _find_case_insensitive(path: Path) -> Path | None:
    """The file, or a file whose path differs only in case (sources written on Windows)."""
    if path.exists():
        return path
    cur = Path(path.anchor) if path.is_absolute() else Path(".")
    for part in path.parts[1 if path.is_absolute() else 0:]:
        if part in ("..", "."):
            cur = cur / part
            continue
        try:
            match = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
        except OSError:
            return None
        if match is None:
            return None
        cur = match
    return cur


def kickass_sources(main: Path, lib_dirs: list[Path] | None = None) -> list[Path]:
    """The main file and everything it #imports (Kick Assembler), in the order they're met."""
    seen: list[Path] = []
    keys: set[Path] = set()

    def visit(f: Path):
        k = f.resolve()
        if k in keys:
            return
        keys.add(k)
        seen.append(f)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for name in _IMPORT.findall("\n".join(_strip_comments(text))):
            for base in [f.parent] + list(lib_dirs or []):
                hit = _find_case_insensitive(base / name)
                if hit is not None:
                    visit(hit)
                    break
    visit(main)
    return seen
