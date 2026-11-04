"""Multi-pass 6502 assembler for the CBM prg Studio dialect."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..cbmfloat import FloatError, to_cbm
from .charset import char_to_petscii, char_to_screencode
from .errors import AsmError, Diagnostic, SourceLoc
from .expr import Evaluator, Undefined
from .opcodes import ILLEGAL_OPCODES, MODE_SIZE, OPCODES, ZP_TO_ABS
from .source import Line, SourceLoader, first_word, split_label, split_top_level, unquote

MAX_PASSES = 24
STICKY_AFTER = 8  # after this many passes instruction sizes may only grow (forces convergence)


@dataclass
class Options:
    illegal_opcodes: bool = False
    case_sensitive: bool = False  # CBM prg Studio labels are case-insensitive
    # Zero-page addressing for forward-referenced symbols whose final value is < $100.
    forward_zp: bool = True
    text_encoding: str = "auto"    # TEXT: "auto" ("..." PETSCII, '...' screen codes), "screen" or "petscii"
    padding_byte: int = 0


@dataclass
class Statement:
    """A pre-parsed source line."""
    line: Line
    label: str | None
    kind: str            # none, const, origin, instr, data, dcb, text, incbin, operator, align, if, else, endif, ignore
    mnem: str = ""
    mode: str = ""       # instr: operand shape (imp, acc, imm, plain, x, y, izx, izy, ind)
    operand: str = ""
    args: list[str] = field(default_factory=list)
    width: int = 1       # data: 1 = byte, 2 = word


@dataclass
class ListingEntry:
    address: int
    data: bytes
    loc: SourceLoc
    called_from: SourceLoc | None
    source: str
    kind: str = ""          # the statement kind: "instr", "data", "text", "dcb", "incbin", "fltp", "align"


@dataclass
class Result:
    ok: bool
    diagnostics: list[Diagnostic]
    memory: bytearray
    used: bytearray
    start: int | None
    end: int | None            # exclusive
    symbols: dict[str, int]
    listing: list[ListingEntry]
    passes: int
    names: dict[str, str] = field(default_factory=dict)  # symbol key -> name as first written

    def binary(self) -> bytes:
        if self.start is None:
            return b""
        return bytes(self.memory[self.start:self.end])

    def prg(self) -> bytes:
        if self.start is None:
            return b""
        return bytes([self.start & 0xFF, self.start >> 8]) + self.binary()

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


_IZX_RE = re.compile(r"^\((.*),\s*[xX]\s*\)$", re.S)
_IZY_RE = re.compile(r"^\((.*)\)\s*,\s*[yY]$", re.S)


def _matching_paren(s: str, start: int) -> int:
    depth, quote = 0, None
    for i in range(start, len(s)):
        c = s[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def parse_operand(op: str) -> tuple[str, str]:
    """Classify an instruction operand into (shape, expression)."""
    op = op.strip()
    if not op:
        return "imp", ""
    if op.lower() == "a":
        return "acc", ""
    if op.startswith("#"):
        return "imm", op[1:].strip()
    if op.startswith("("):
        close = _matching_paren(op, 0)
        m = _IZX_RE.match(op)
        if m and close == len(op) - 1:
            return "izx", m.group(1).strip()
        m = _IZY_RE.match(op)
        if m and close == len(m.group(1)) + 1:
            return "izy", m.group(1).strip()
        if close == len(op) - 1:
            return "ind", op[1:-1].strip()
    parts = split_top_level(op)
    if len(parts) == 2 and parts[1].lower() in ("x", "y"):
        return parts[1].lower(), parts[0]
    return "plain", op


class Assembler:
    def __init__(self, options: Options | None = None):
        self.opt = options or Options()
        self.opcodes = dict(OPCODES)
        if self.opt.illegal_opcodes:
            self.opcodes.update(ILLEGAL_OPCODES)

    # ------------------------------------------------------------------ entry points
    def assemble_files(self, paths: list[Path | str], overrides: dict[str, str] | None = None) -> Result:
        loader = SourceLoader(self.opt.illegal_opcodes, overrides)
        lines = loader.load([Path(p) for p in paths])
        return self._assemble(lines, loader)

    def assemble_text(self, text: str, filename: str = "<source>") -> Result:
        return self.assemble_files([filename], overrides={filename: text})

    # ------------------------------------------------------------------ parsing
    def _parse(self, lines: list[Line], loader: SourceLoader) -> list[Statement]:
        stmts: list[Statement] = []
        kw = loader.kw
        for ln in lines:
            try:
                stmts.append(self._parse_line(ln, kw))
            except AsmError as e:
                self.diags.append(Diagnostic("error", e.message, ln.loc))
        return stmts

    def _parse_line(self, ln: Line, kw) -> Statement:
        label, rest = split_label(ln.code, kw)
        if not rest:
            return Statement(ln, label, "none")
        if rest.startswith("="):
            if not label:
                raise AsmError("'=' without a name")
            return Statement(ln, label, "const", operand=rest[1:].strip())
        if rest.startswith("*"):
            m = re.match(r"\*\s*=\s*(.+)$", rest)
            if not m:
                raise AsmError(f"Bad origin '{rest}'")
            return Statement(ln, label, "origin", operand=m.group(1).strip())
        word, args = first_word(rest)
        w = word.lower()
        if not w:
            raise AsmError(f"Can't parse '{rest}'")
        if w in self.opcodes:
            shape, expr = parse_operand(args)
            return Statement(ln, label, "instr", mnem=w, mode=shape, operand=expr)
        if w == "equ":
            if not label:
                raise AsmError("EQU without a name")
            return Statement(ln, label, "const", operand=args)
        if w in ("byte", "byt", "db", "dfb"):
            return Statement(ln, label, "data", args=split_top_level(args), width=1)
        if w in ("word", "wor", "dw"):
            return Statement(ln, label, "data", args=split_top_level(args), width=2)
        if w == "text":
            return Statement(ln, label, "text", args=split_top_level(args))
        if w == "fltp":
            return Statement(ln, label, "fltp", args=split_top_level(args))
        if w == "dcb":
            a = split_top_level(args)
            if len(a) != 2:
                raise AsmError("DCB needs a count and a value: dcb <count>, <value>")
            return Statement(ln, label, "dcb", args=a)
        if w == "incbin":
            return Statement(ln, label, "incbin", args=split_top_level(args))
        if w == "operator":
            mode = args.strip().lower()
            if mode not in ("calc", "hilo"):
                raise AsmError("OPERATOR must be followed by CALC or HILO")
            return Statement(ln, label, "operator", operand=mode)
        if w == "align":
            return Statement(ln, label, "align", operand=args)
        if w == "org":
            return Statement(ln, label, "origin", operand=args)
        if w in ("if", "ifdef", "ifndef"):
            return Statement(ln, label, "if", mnem=w, operand=args)
        if w == "else":
            return Statement(ln, label, "else")
        if w == "endif":
            return Statement(ln, label, "endif")
        if w in ("generateto", "watch"):
            self.diags.append(Diagnostic("warning", f"{word.upper()} is ignored by Linux64Studio", ln.loc))
            return Statement(ln, label, "none")
        raise AsmError(f"Invalid Instruction or Macro '{word}'")

    # ------------------------------------------------------------------ passes
    def _assemble(self, lines: list[Line], loader: SourceLoader) -> Result:
        self.diags: list[Diagnostic] = list(loader.diagnostics)
        stmts = self._parse(lines, loader)
        self.prev_symbols: dict[str, int] = {}
        self.sizes: dict[int, int] = {}
        passes = 0
        for passes in range(1, MAX_PASSES + 1):
            state = self._run_pass(stmts, passes, final=False)
            stable = (not state["undefined"] and state["symbols"] == self.prev_symbols
                      and not state["size_changed"])
            self.prev_symbols = state["symbols"]
            if stable:
                break
        state = self._run_pass(stmts, passes + 1, final=True)
        diags = self.diags + state["diags"]
        res = Result(
            ok=not any(d.severity == "error" for d in diags),
            diagnostics=diags,
            memory=state["mem"],
            used=state["used"],
            start=state["start"],
            end=state["end"],
            symbols=state["symbols"],
            listing=state["listing"],
            passes=passes + 1,
            names=state["names"],
        )
        return res

    def _key(self, name: str) -> str:
        return name if self.opt.case_sensitive else name.lower()

    def _run_pass(self, stmts: list[Statement], pass_no: int, final: bool) -> dict:
        opt = self.opt
        symbols: dict[str, int] = {}
        names: dict[str, str] = {}
        mem = bytearray([opt.padding_byte & 0xFF]) * 0x10000
        used = bytearray(0x10000)
        diags: list[Diagnostic] = []
        listing: list[ListingEntry] = []
        st = {"pc": None, "calc": False, "scope": "", "undefined": False, "size_changed": False,
              "lo": None, "hi": None}
        cond_stack: list[bool] = []  # True = currently assembling

        def resolve_name(name: str) -> str:
            if name.startswith("@") and "__m" not in name:
                name = st["scope"] + name
            return self._key(name)

        def lookup(name: str) -> int:
            key = resolve_name(name)
            if key in symbols:
                return symbols[key]
            if key in self.prev_symbols:
                st["forward"] = True
                return self.prev_symbols[key]
            raise Undefined(name)

        def evaluate(text: str) -> int:
            return Evaluator(lookup, st["pc"], st["calc"]).evaluate(text)

        def define(label: str, value: int, loc: SourceLoc):
            key = resolve_name(label)
            if key in symbols:
                diags.append(Diagnostic("error", f"Label '{label}' is already defined", loc))
                return
            symbols[key] = value
            names.setdefault(key, label if not label.startswith("@") else key)

        def emit(data: bytes | bytearray | list[int], stmt: Statement):
            pc = st["pc"]
            if pc is None:
                raise AsmError("No origin set: add a line like *=$0801 before any code or data")
            if pc + len(data) > 0x10000:
                raise AsmError("Code runs past $FFFF")
            if final:
                for i, b in enumerate(data):
                    a = pc + i
                    if used[a]:
                        diags.append(Diagnostic("warning", f"Overwriting memory at ${a:04X}", stmt.line.loc))
                    mem[a] = b & 0xFF
                    used[a] = 1
                listing.append(ListingEntry(pc, bytes(b & 0xFF for b in data), stmt.line.loc,
                                            stmt.line.called_from, stmt.line.code, stmt.kind))
            if data:
                st["lo"] = pc if st["lo"] is None else min(st["lo"], pc)
                end = pc + len(data)
                st["hi"] = end if st["hi"] is None else max(st["hi"], end)
            st["pc"] = pc + len(data)

        for idx, s in enumerate(stmts):
            loc = s.line.loc
            # Conditional assembly
            if s.kind in ("if", "else", "endif"):
                try:
                    if s.kind == "if":
                        active = all(cond_stack)
                        if not active:
                            cond_stack.append(False)
                        elif s.mnem == "if":
                            cond_stack.append(self._eval_cond(evaluate, s.operand))
                        else:
                            key = resolve_name(s.operand.strip())
                            defined = key in symbols or key in self.prev_symbols
                            cond_stack.append(defined if s.mnem == "ifdef" else not defined)
                    elif s.kind == "else":
                        if not cond_stack:
                            raise AsmError("ELSE without IF")
                        cond_stack[-1] = not cond_stack[-1]
                    else:
                        if not cond_stack:
                            raise AsmError("ENDIF without IF")
                        cond_stack.pop()
                except Undefined as u:
                    st["undefined"] = True
                    cond_stack.append(False)
                    if final:
                        diags.append(Diagnostic("error", f"Undefined symbol '{u.name}' in IF", loc))
                except AsmError as e:
                    if final:
                        diags.append(Diagnostic("error", e.message, loc))
                continue
            if cond_stack and not all(cond_stack):
                continue

            try:
                if s.label and s.kind != "const":
                    if st["pc"] is None:
                        raise AsmError(f"Label '{s.label}' defined before any origin (*=)")
                    define(s.label, st["pc"], loc)
                    if not s.label.startswith("@"):
                        st["scope"] = s.label
                k = s.kind
                if k == "none":
                    pass
                elif k == "const":
                    try:
                        define(s.label, evaluate(s.operand), loc)
                    except Undefined:
                        st["undefined"] = True
                        if final:
                            raise
                elif k == "origin":
                    st["pc"] = evaluate(s.operand) & 0xFFFF
                elif k == "operator":
                    st["calc"] = s.operand == "calc"
                elif k == "instr":
                    emit(self._encode(s, idx, evaluate, st, final, pass_no), s)
                elif k == "data":
                    out = []
                    for a in s.args:
                        if len(a) > 3 and a[0] in "'\"" and a[-1] == a[0]:
                            out.extend(char_to_screencode(c) for c in a[1:-1])
                            continue
                        v = self._value(evaluate, a, final)
                        if s.width == 1:
                            self._check_range(v, -128, 255, "Byte", final, diags, loc)
                            out.append(v & 0xFF)
                        else:
                            self._check_range(v, -32768, 65535, "Word", final, diags, loc)
                            out.extend([v & 0xFF, (v >> 8) & 0xFF])
                    emit(out, s)
                elif k == "text":
                    out = []
                    for a in s.args:
                        if len(a) >= 2 and a[0] in "'\"" and a[-1] == a[0]:
                            # as CBM prg Studio: "double quotes" give PETSCII, 'single quotes' screen codes
                            petscii = (opt.text_encoding == "petscii"
                                       or (opt.text_encoding == "auto" and a[0] == '"'))
                            conv = char_to_petscii if petscii else char_to_screencode
                            out.extend(conv(c) for c in a[1:-1])
                        else:
                            out.append(self._value(evaluate, a, final) & 0xFF)
                    emit(out, s)
                elif k == "fltp":
                    out = []
                    for a in s.args:
                        try:
                            v = float(a.strip())
                        except ValueError:
                            if not a.strip():
                                raise AsmError("FLTP needs a number, such as fltp 3.14159265") from None
                            v = self._value(evaluate, a, final)
                        try:
                            out.extend(to_cbm(v))
                        except FloatError as e:
                            raise AsmError(str(e)) from None
                    emit(out, s)
                elif k == "dcb":
                    count = evaluate(s.args[0])
                    value = self._value(evaluate, s.args[1], final)
                    if count < 0 or count > 0x10000:
                        raise AsmError(f"DCB count {count} out of range")
                    emit([value & 0xFF] * count, s)
                elif k == "incbin":
                    emit(self._incbin(s, evaluate), s)
                elif k == "align":
                    n = evaluate(s.operand)
                    if n <= 0:
                        raise AsmError("ALIGN needs a positive value")
                    pc = st["pc"] or 0
                    pad = (-pc) % n
                    emit([opt.padding_byte] * pad, s)
            except Undefined as u:
                st["undefined"] = True
                if final:
                    diags.append(Diagnostic("error", f"Undefined label or constant '{u.name}'", loc))
            except AsmError as e:
                if final:
                    diags.append(Diagnostic("error", e.message, e.loc or loc))
            except RecursionError:
                if final:
                    diags.append(Diagnostic("error", "Expression too deeply nested", loc))

        if cond_stack and final:
            diags.append(Diagnostic("error", "IF without ENDIF", None))
        return {"symbols": symbols, "undefined": st["undefined"], "size_changed": st["size_changed"],
                "mem": mem, "used": used, "start": st["lo"], "end": st["hi"], "diags": diags,
                "listing": listing, "names": names}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _eval_cond(evaluate, text: str) -> bool:
        return evaluate(text) != 0

    @staticmethod
    def _value(evaluate, text: str, final: bool) -> int:
        try:
            return evaluate(text)
        except Undefined:
            if final:
                raise
            return 0  # placeholder in early passes; the pass is marked unstable by lookup failure

    @staticmethod
    def _check_range(v, lo, hi, what, final, diags, loc):
        if final and not (lo <= v <= hi):
            diags.append(Diagnostic("error", f"{what} value {v} (${v & 0xFFFFFFFF:X}) out of range", loc))

    def _incbin(self, s: Statement, evaluate) -> bytes:
        if not s.args or not s.args[0]:
            raise AsmError("INCBIN needs a file name")
        name = unquote(s.args[0])
        path = Path(s.line.loc.file).parent / name
        try:
            data = path.read_bytes()
        except OSError:
            raise AsmError(f"INCBIN can't read '{name}' (looked in {path.parent})")
        skip = evaluate(s.args[1]) if len(s.args) > 1 else 0
        length = evaluate(s.args[2]) if len(s.args) > 2 else len(data) - skip
        return data[skip:skip + length]

    def _encode(self, s: Statement, idx: int, evaluate, st: dict, final: bool, pass_no: int) -> list[int]:
        modes = self.opcodes[s.mnem]
        shape = s.mode
        name = s.mnem.upper()

        if shape in ("imp", "acc"):
            if shape in modes:
                return [modes[shape]]
            if shape == "imp" and "acc" in modes:
                return [modes["acc"]]
            raise AsmError(f"{name} needs an operand")

        if "rel" in modes:
            if shape != "plain":
                raise AsmError(f"{name} only takes a branch target")
            try:
                target = evaluate(s.operand)
            except Undefined:
                if final:
                    raise
                target = st["pc"] or 0
            offset = target - ((st["pc"] or 0) + 2)
            if not -128 <= offset <= 127:
                if final:
                    raise AsmError(f"Branch out of range by {abs(offset) - (128 if offset < 0 else 127)} bytes")
                offset = 0
            return [modes["rel"], offset & 0xFF]

        if shape == "imm":
            if "imm" not in modes:
                raise AsmError(f"{name} doesn't support immediate (#) addressing")
            v = self._value(evaluate, s.operand, final)
            if final and not -128 <= v <= 255:
                raise AsmError(f"Immediate value {v} out of range")
            return [modes["imm"], v & 0xFF]

        st["forward"] = False
        unknown = False
        try:
            v = evaluate(s.operand)
        except Undefined:
            if final:
                raise
            v, unknown = 0x1000, True
        forward = st.pop("forward", False)
        if final and not 0 <= v <= 0xFFFF:
            raise AsmError(f"Address {v} out of range")
        v &= 0xFFFF

        if shape in ("izx", "izy"):
            if shape not in modes:
                raise AsmError(f"{name} doesn't support ({'zp,x' if shape == 'izx' else 'zp),y'} addressing")
            if final and v > 0xFF:
                raise AsmError(f"Indirect address ${v:04X} must be in zero page")
            return [modes[shape], v & 0xFF]
        if shape == "ind":
            if "ind" in modes:
                return [modes["ind"], v & 0xFF, v >> 8]
            shape = "plain"  # e.g. lda (expr) is just an expression in brackets

        zp_mode, abs_mode = {"plain": ("zp", "abs"), "x": ("zpx", "abx"), "y": ("zpy", "aby")}[shape]
        want_zp = (not unknown and v < 0x100 and zp_mode in modes
                   and (self.opt.forward_zp or not forward))
        floor = self.sizes.get(idx, 0)
        if want_zp and pass_no > STICKY_AFTER and floor == 3 and abs_mode in modes:
            want_zp = False
        if want_zp:
            mode = zp_mode
        elif abs_mode in modes:
            mode = abs_mode
        elif zp_mode in modes:
            if final and v > 0xFF:
                raise AsmError(f"{name} {'zp,y' if shape == 'y' else 'zp,x'} needs a zero-page address")
            mode = zp_mode
        else:
            raise AsmError(f"{name} doesn't support that addressing mode")
        size = MODE_SIZE[mode]
        if not final:
            if floor and floor != size:
                st["size_changed"] = True
            self.sizes[idx] = size
        if size == 2:
            return [modes[mode], v & 0xFF]
        return [modes[mode], v & 0xFF, v >> 8]
