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
    # Assemble an address written with 4 digits but under $100 (lda $0002,x) as zero page, as CBM
    # prg Studio does by default; the ZPOPT directive switches it for part of a file
    zp_optimise: bool = True


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
    # What the source asks for, beyond the code (CBM prg Studio's directives)
    no_load_address: bool = False                 # NOLOADADDR: write the file without its load address
    save_block: tuple[int, int] | None = None     # SAVEBLOCK: write only this block (first, last)
    padding: int | None = None                    # PADBYTE
    exports: dict[str, int] = field(default_factory=dict)          # EXPORT: name -> value, for BASIC
    watches: list[tuple[str, int, str]] = field(default_factory=list)   # WATCH: (name, address, comment)
    breakpoints: list[tuple[int, str]] = field(default_factory=list)     # BREAKPOINT: (address, condition)
    debug_start: int | None = None                # DEBUGSTARTADDRESS
    generate_to: list[str] | None = None          # GENERATETO's arguments
    messages: list[str] = field(default_factory=list)              # DEBUG output
    target: str = "TGT_C64"
    label_locs: dict[str, SourceLoc] = field(default_factory=dict)  # address label key -> where it's defined

    def binary(self) -> bytes:
        if self.save_block is not None:
            a, b = self.save_block
            return bytes(self.memory[a:b + 1])
        if self.start is None:
            return b""
        return bytes(self.memory[self.start:self.end])

    def prg(self) -> bytes:
        """The program file: a load address then the code, unless NOLOADADDR says otherwise."""
        start = self.save_block[0] if self.save_block is not None else self.start
        if start is None:
            return b""
        if self.no_load_address:
            return self.binary()
        return bytes([start & 0xFF, start >> 8]) + self.binary()

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
        if w in ("dcb", "dcw"):
            a = split_top_level(args)
            if len(a) < 2 or not all(a):
                raise AsmError(f"{w.upper()} needs a count and then values: {w} <count>, <value>[, ...]")
            return Statement(ln, label, "dcb", args=a, width=1 if w == "dcb" else 2)
        if w == "bits":
            if not args.strip():
                raise AsmError("BITS needs a pattern, such as bits ..@@@@..")
            return Statement(ln, label, "bits", operand=args.strip())
        if w in ("bytes", "words"):
            return Statement(ln, label, "blist", args=split_top_level(args), width=1 if w == "bytes" else 2)
        if w in ("null", "ptext"):
            a = split_top_level(args)
            if len(a) != 1 or len(a[0]) < 2 or a[0][0] not in "'\"" or a[0][-1] != a[0][0]:
                raise AsmError(f"{w.upper()} takes one string in quotes")
            return Statement(ln, label, "str", mnem=w, args=a)
        if w in ("long", "longs"):
            raise AsmError(f"{w.upper()} is for the 65816 only: Linux64Studio assembles 6502 code for the C64")
        if w in ("func", "funcw"):
            a = split_top_level(args)
            if len(a) < 4:
                raise AsmError(f"{w.upper()} needs a start, end, step and function: {w} 1,10,1,x*5")
            return Statement(ln, label, "func", args=a[:3] + [",".join(a[3:])], width=1 if w == "func" else 2)
        if w in ("random", "randomw"):
            a = split_top_level(args)
            if not 3 <= len(a) <= 4:
                raise AsmError(f"{w.upper()} needs a count, a lowest and a highest value, and an optional seed")
            return Statement(ln, label, "random", args=a, width=1 if w == "random" else 2)
        if w == "relocate":
            return Statement(ln, label, "relocate", operand=args.strip())
        if w == "noloadaddr":
            return Statement(ln, label, "noloadaddr")
        if w == "saveblock":
            a = split_top_level(args)
            if len(a) != 2:
                raise AsmError("SAVEBLOCK needs a start and an end address")
            return Statement(ln, label, "saveblock", args=a)
        if w == "padbyte":
            return Statement(ln, label, "padbyte", operand=args.strip())
        if w == "target":
            return Statement(ln, label, "none")        # handled before the passes
        if w == "charmap":
            return Statement(ln, label, "none")        # global: handled before the passes
        if w == "charset":
            if args.strip() not in ("1", "2"):
                raise AsmError("CHARSET must be followed by 1 or 2")
            return Statement(ln, label, "charset", operand=args.strip())
        if w in ("zpopt", "warning"):
            v = args.strip().lower()
            if v not in ("on", "off"):
                raise AsmError(f"{w.upper()} must be followed by ON or OFF")
            return Statement(ln, label, w, operand=v)
        if w == "debug":
            return Statement(ln, label, "debug", operand=args.strip())
        if w == "export":
            return Statement(ln, label, "export", args=split_top_level(args))
        if w == "watch":
            a = split_top_level(args)
            if not a or not a[0]:
                raise AsmError("WATCH needs a label, variable or address")
            return Statement(ln, label, "watch", args=[a[0], ",".join(a[1:]).strip()])
        if w == "breakpoint":
            return Statement(ln, label, "breakpoint", operand=args.strip())
        if w == "debugstartaddress":
            return Statement(ln, label, "debugstart", operand=args.strip())
        if w == "generateto":
            return Statement(ln, label, "generateto", args=split_top_level(args))
        if w == "checksum":
            return Statement(ln, label, "none")        # CBM prg Studio's own debugging aid
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
        raise AsmError(f"Invalid Instruction or Macro '{word}'")

    # ------------------------------------------------------------------ passes
    _TARGETS = {"TGT_C128", "TGT_C16", "TGT_C64", "TGT_PETBV2", "TGT_PETBV4", "TGT_PLUS4", "TGT_VIC20",
                "TGT_VIC20_3K", "TGT_VIC20_8K"}

    def _prescan(self, lines: list[Line], loader: SourceLoader) -> None:
        """TARGET and CHARMAP apply to the whole project (CBM prg Studio reads them first)."""
        self.target = "TGT_C64"
        self.charmap: dict[str, tuple[int, int]] = {}
        self.charmap_on = True
        for ln in lines:
            _label, rest = split_label(ln.code, loader.kw)
            word, args = first_word(rest)
            w = word.lower()
            if w == "target":
                t = args.strip().upper()
                if t not in self._TARGETS:
                    self.diags.append(Diagnostic("error", f"Unknown TARGET '{args.strip()}' (TGT_C64, TGT_VIC20, ...)",
                                                 ln.loc))
                    continue
                self.target = t
                if t != "TGT_C64":
                    self.diags.append(Diagnostic("warning", f"TARGET {t}: Linux64Studio builds for the C64; "
                                                            f"{t} is defined for IFDEF, but the code is still 6502 "
                                                            f"for a C64", ln.loc))
            elif w == "charmap":
                a = split_top_level(args)
                if len(a) == 1 and a[0].lower() in ("on", "off"):
                    self.charmap_on = a[0].lower() == "on"
                elif len(a) == 3 and len(a[0]) == 1:
                    try:
                        self.charmap[a[0]] = (int(a[1].lstrip("$"), 16 if a[1].startswith("$") else 10) & 0xFF,
                                              int(a[2].lstrip("$"), 16 if a[2].startswith("$") else 10) & 0xFF)
                    except ValueError:
                        self.diags.append(Diagnostic("error", "CHARMAP needs a character, a PETSCII value and a "
                                                              "screen code: charmap a,3,5", ln.loc))
                else:
                    self.diags.append(Diagnostic("error", "CHARMAP needs ON, OFF, or a character, a PETSCII value "
                                                          "and a screen code: charmap a,3,5", ln.loc))

    def _assemble(self, lines: list[Line], loader: SourceLoader) -> Result:
        self.diags: list[Diagnostic] = list(loader.diagnostics)
        self._prescan(lines, loader)
        self._random_cache: dict[int, list[int]] = {}
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
            no_load_address=state["no_load_address"],
            save_block=state["save_block"],
            padding=state["padding"],
            exports=state["exports"],
            watches=state["watches"],
            breakpoints=state["breakpoints"],
            debug_start=state["debug_start"],
            generate_to=state["generate_to"],
            messages=state["messages"],
            target=self.target,
            label_locs=state["label_locs"],
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
              "lo": None, "hi": None,
              "delta": 0,                 # RELOCATE: bytes are stored at pc + delta
              "zpopt": opt.zp_optimise, "charset": 1, "warnings": True, "file": "",
              "debug": {"pass": None, "auto": False, "hex": True},
              "no_load_address": False, "save_block": None, "padding": None, "exports": {}, "watches": [],
              "breakpoints": [], "debug_start": None, "generate_to": None, "messages": [], "label_locs": {}}
        cond_stack: list[bool] = []  # True = currently assembling
        owner: dict[str, str] = {}   # label key -> the file that defined it first
        # A plain label is local to its file (CBM prg Studio): the same name in another file is a
        # different label, kept as "<file>::name". A reference looks in its own file first.

        def resolve_name(name: str) -> str:
            if name.startswith("@") and "__m" not in name:
                name = st["scope"] + name
            return self._key(name)

        def scoped(key: str) -> str:
            return f"{st['file']}::{key}"

        def lookup(name: str) -> int:
            key = resolve_name(name)
            for k in ((scoped(key), key) if not key.endswith("$") else (key,)):
                if k in symbols:
                    return symbols[k]
            for k in ((scoped(key), key) if not key.endswith("$") else (key,)):
                if k in self.prev_symbols:
                    st["forward"] = True
                    return self.prev_symbols[k]
            raise Undefined(name)

        def char_value(quote: str, ch: str) -> int:
            if self.charmap_on and ch in self.charmap:
                petscii, screen = self.charmap[ch]
                return petscii if quote == '"' else screen
            if quote == '"':
                return ord(ch) & 0xFF
            return screen_code(ch)

        def screen_code(ch: str) -> int:
            """A single-quoted character: CHARSET 1 (the default) treats both cases as the C64's
            letters ('A' and 'a' are 1); CHARSET 2 makes capitals the shifted letters (65)."""
            if self.charmap_on and ch in self.charmap:
                return self.charmap[ch][1]
            return char_to_screencode(ch.lower() if st["charset"] == 1 else ch)

        def petscii(ch: str) -> int:
            if self.charmap_on and ch in self.charmap:
                return self.charmap[ch][0]
            return char_to_petscii(ch)

        def evaluate(text: str) -> int:
            return Evaluator(lookup, st["pc"], st["calc"], char_value).evaluate(text)

        def define(label: str, value: int, loc: SourceLoc, address: bool = False):
            """Set a label (`address`: one on a line of code, not NAME = value)."""
            key = resolve_name(label)
            if key in symbols:
                if (not key.endswith("$") and not key.startswith(owner.get(key, st["file"]) + "::")
                        and owner.get(key) != st["file"] and "@" not in key):
                    key = scoped(key)               # the same name in another file: its own label
                    if key not in symbols:
                        symbols[key] = value
                        names.setdefault(key, label)
                        if address:
                            st["label_locs"].setdefault(key, loc)
                        return
                diags.append(Diagnostic("error", f"Label '{label}' is already defined", loc))
                return
            symbols[key] = value
            owner[key] = st["file"]
            names.setdefault(key, label if not label.startswith("@") else key)
            if address:
                st["label_locs"].setdefault(key, loc)

        def emit(data: bytes | bytearray | list[int], stmt: Statement):
            pc = st["pc"]
            if pc is None:
                raise AsmError("No origin set: add a line like *=$0801 before any code or data")
            at = pc + st["delta"]                   # where the bytes go (RELOCATE moves the labels only)
            if not 0 <= at or at + len(data) > 0x10000:
                raise AsmError("Code runs past $FFFF")
            if final:
                for i, b in enumerate(data):
                    a = at + i
                    if used[a]:
                        diags.append(Diagnostic("warning", f"Overwriting memory at ${a:04X}", stmt.line.loc))
                    mem[a] = b & 0xFF
                    used[a] = 1
                listing.append(ListingEntry(at, bytes(b & 0xFF for b in data), stmt.line.loc,
                                            stmt.line.called_from, stmt.line.code, stmt.kind))
            if data:
                st["lo"] = at if st["lo"] is None else min(st["lo"], at)
                end = at + len(data)
                st["hi"] = end if st["hi"] is None else max(st["hi"], end)
            st["pc"] = pc + len(data)

        def message(text: str):
            if final and (st["debug"]["pass"] is None):
                st["messages"].append(text)
            elif st["debug"]["pass"] == pass_no:
                st["messages"].append(text)

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
                            if key.upper() == self.target.upper() or key in (t.lower() for t in self._TARGETS
                                                                               if t == self.target):
                                defined = True
                            else:
                                defined = any(k in symbols or k in self.prev_symbols for k in (key, scoped(key)))
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

            st["file"] = (s.line.called_from or loc).file
            n_diags = len(diags)
            try:
                if s.label and s.kind != "const":
                    if st["pc"] is None:
                        raise AsmError(f"Label '{s.label}' defined before any origin (*=)")
                    define(s.label, st["pc"], loc, address=True)
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
                    for w in st.pop("warn", []):
                        diags.append(Diagnostic("warning", w, loc))
                elif k == "data":
                    out = []
                    for a in s.args:
                        if len(a) > 3 and a[0] in "'\"" and a[-1] == a[0]:
                            out.extend(screen_code(c) for c in a[1:-1])
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
                            is_petscii = (opt.text_encoding == "petscii"
                                          or (opt.text_encoding == "auto" and a[0] == '"'))
                            conv = petscii if is_petscii else screen_code
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
                    values = [self._value(evaluate, a, final) for a in s.args[1:]]
                    if count < 0 or count * len(values) * s.width > 0x10000:
                        raise AsmError(f"DCB count {count} out of range")
                    emit(self._pack(values * count, s.width, final, diags, loc), s)
                elif k == "bits":
                    pattern = unquote(s.operand)
                    bits = "".join("0" if c in "0." else "1" for c in pattern if not c.isspace())
                    bits = bits.zfill((len(bits) + 7) // 8 * 8)
                    emit([int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)], s)
                elif k == "blist":
                    values = []
                    for a in s.args:
                        parts = split_top_level(a, "*")
                        if len(parts) == 2 and all(parts):
                            value, count = self._value(evaluate, parts[0], final), evaluate(parts[1])
                        else:
                            value, count = 0, evaluate(a)
                        if not 0 <= count <= 0x10000:
                            raise AsmError(f"Count {count} out of range in '{a}'")
                        values += [value] * count
                    emit(self._pack(values, s.width, final, diags, loc), s)
                elif k == "str":
                    a = s.args[0]
                    is_petscii = opt.text_encoding == "petscii" or (opt.text_encoding == "auto" and a[0] == '"')
                    body = [(petscii if is_petscii else screen_code)(c) for c in a[1:-1]]
                    if s.mnem == "null":
                        emit(body + [0], s)
                    else:
                        if len(body) > 255:
                            raise AsmError("A PTEXT string must be shorter than 256 characters")
                        emit([len(body)] + body, s)
                elif k == "func":
                    from ..datagen import DataGenError, Function
                    start, end, step = (evaluate(a) for a in s.args[:3])
                    if step == 0:
                        raise AsmError("FUNC's step can't be 0")
                    try:
                        f = Function(s.args[3])
                        xs = range(start, end + (1 if step > 0 else -1), step)
                        values = [int(round(f(x))) for x in xs]
                    except DataGenError as e:
                        raise AsmError(str(e)) from None
                    emit(self._pack(values, s.width, final, diags, loc), s)
                elif k == "random":
                    import random as _random
                    count, lo, hi = (evaluate(a) for a in s.args[:3])
                    limit = 0xFF if s.width == 1 else 0xFFFF
                    if not (0 <= lo <= hi <= limit):
                        raise AsmError(f"RANDOM's limits must be within 0-{limit} and the lowest first")
                    if not 0 <= count <= 0x10000:
                        raise AsmError(f"RANDOM count {count} out of range")
                    if idx not in self._random_cache or len(self._random_cache[idx]) != count:
                        # the same values on every pass (and, with a seed, every build)
                        rng = _random.Random(evaluate(s.args[3])) if len(s.args) > 3 else _random.Random()
                        self._random_cache[idx] = [rng.randint(lo, hi) for _ in range(count)]
                    emit(self._pack(self._random_cache[idx], s.width, final, diags, loc), s)
                elif k == "relocate":
                    if st["pc"] is None:
                        raise AsmError("RELOCATE needs an origin (*=) first")
                    actual = st["pc"] + st["delta"]
                    if s.operand.lower() == "off":
                        st["pc"], st["delta"] = actual, 0
                    else:
                        new = evaluate(s.operand) & 0xFFFF
                        st["pc"], st["delta"] = new, actual - new
                elif k == "noloadaddr":
                    st["no_load_address"] = True
                elif k == "saveblock":
                    a, b = (evaluate(x) for x in s.args)
                    if not 0 <= a <= b <= 0xFFFF:
                        raise AsmError("SAVEBLOCK's start must be before its end, within $0000-$FFFF")
                    st["save_block"] = (a, b)
                elif k == "padbyte":
                    v = evaluate(s.operand)
                    if not 0 <= v <= 255:
                        raise AsmError("PADBYTE must be 0-255")
                    st["padding"] = v
                elif k == "charset":
                    st["charset"] = int(s.operand)
                elif k == "zpopt":
                    st["zpopt"] = s.operand == "on"
                elif k == "warning":
                    st["warnings"] = s.operand == "on"
                elif k == "debug":
                    self._debug(s.operand, st, evaluate, message, pass_no)
                elif k == "export":
                    for name in s.args:
                        if name:
                            st["exports"][name] = self._value(evaluate, name, final)
                elif k == "watch":
                    st["watches"].append((s.args[0], self._value(evaluate, s.args[0], final) & 0xFFFF, s.args[1]))
                elif k == "breakpoint":
                    st["breakpoints"].append(self._breakpoint(s.operand, st, evaluate, final))
                elif k == "debugstart":
                    st["debug_start"] = self._value(evaluate, s.operand, final) & 0xFFFF
                elif k == "generateto":
                    st["generate_to"] = [unquote(a) for a in s.args]
                elif k == "incbin":
                    emit(self._incbin(s, evaluate), s)
                elif k == "align":
                    n = evaluate(s.operand)
                    if n <= 0:
                        raise AsmError("ALIGN needs a positive value")
                    pc = st["pc"] or 0
                    pad = (-pc) % n
                    emit([opt.padding_byte if st["padding"] is None else st["padding"]] * pad, s)
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
            if not st["warnings"]:
                diags[n_diags:] = [d for d in diags[n_diags:] if d.severity != "warning"]

        if cond_stack and final:
            diags.append(Diagnostic("error", "IF without ENDIF", None))
        if st["padding"] is not None and st["padding"] != opt.padding_byte:
            for a in range(0x10000):                 # PADBYTE: the gaps take its value
                if not used[a]:
                    mem[a] = st["padding"]
        out = {k: st[k] for k in ("no_load_address", "save_block", "padding", "exports", "watches", "breakpoints",
                                  "debug_start", "generate_to", "messages", "label_locs")}
        return {"symbols": symbols, "undefined": st["undefined"], "size_changed": st["size_changed"],
                "mem": mem, "used": used, "start": st["lo"], "end": st["hi"], "diags": diags,
                "listing": listing, "names": names, **out}

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

    def _pack(self, values: list[int], width: int, final: bool, diags, loc) -> list[int]:
        out: list[int] = []
        for v in values:
            if width == 1:
                self._check_range(v, -128, 255, "Byte", final, diags, loc)
                out.append(v & 0xFF)
            else:
                self._check_range(v, -32768, 65535, "Word", final, diags, loc)
                out += [v & 0xFF, (v >> 8) & 0xFF]
        return out

    _BP_RE = re.compile(r"^(?:(?P<label>[^\s=!<>]+)\s+)?(?P<reg>X|Y|A|PC)\s*(?P<op>==|!=|>=|<=|>|<)\s*(?P<val>.+)$", re.I)

    def _breakpoint(self, text: str, st: dict, evaluate, final: bool) -> tuple[int, str]:
        """BREAKPOINT [label] [X|Y|A|PC op value]: (address, VICE condition or "")."""
        here = st["pc"]
        if not text:
            if here is None:
                raise AsmError("BREAKPOINT on its own needs an origin (*=) first")
            return here, ""
        m = self._BP_RE.match(text)
        if m:
            addr = self._value(evaluate, m.group("label"), final) if m.group("label") else here
            v = self._value(evaluate, m.group("val"), final)
            reg = m.group("reg").upper()
            if final and not 0 <= v <= (0xFFFF if reg == "PC" else 0xFF):
                raise AsmError(f"BREAKPOINT value {v} is out of range for {reg}")
            if addr is None:
                raise AsmError("BREAKPOINT needs an address or an origin (*=) first")
            return addr & 0xFFFF, f"{reg} {m.group('op')} ${v:X}"
        return self._value(evaluate, text, final) & 0xFFFF, ""

    def _debug(self, text: str, st: dict, evaluate, message, pass_no: int) -> None:
        """DEBUG "message" | label | option pass n | auto on|off | base hex|decimal | highlight on|off"""
        d = st["debug"]
        low = text.lower()
        if low.startswith("option"):
            words = low.split()[1:]
            if len(words) == 2 and words[0] == "pass" and words[1].isdigit():
                d["pass"] = int(words[1])
            elif len(words) == 2 and words[0] == "auto":
                d["auto"] = words[1] == "on"
            elif len(words) == 2 and words[0] == "base":
                d["hex"] = words[1].startswith("hex")
            elif not (len(words) == 2 and words[0] == "highlight"):
                raise AsmError(f"Unknown DEBUG option '{text}'")
            return
        if len(text) >= 2 and text[0] == text[-1] == '"':
            message(text[1:-1])
            return
        try:
            v = evaluate(text)
        except Undefined:
            message(f"{text} = (not defined yet)")
            return
        shown = f"${v & 0xFFFF:04X}" if d["hex"] else str(v)
        message(f"{text} = {shown}" if d["auto"] else shown)

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
                if final and (v & 0xFF) == 0xFF and not unknown:
                    st.setdefault("warn", []).append(
                        f"JMP (${v:04X}) reads its high byte from ${v & 0xFF00:04X}, not ${v + 1 & 0xFFFF:04X} "
                        f"(the 6502's page-boundary bug)")
                return [modes["ind"], v & 0xFF, v >> 8]
            shape = "plain"  # e.g. lda (expr) is just an expression in brackets

        zp_mode, abs_mode = {"plain": ("zp", "abs"), "x": ("zpx", "abx"), "y": ("zpy", "aby")}[shape]
        want_zp = (not unknown and v < 0x100 and zp_mode in modes
                   and (self.opt.forward_zp or not forward))
        # An address written with two bytes ($0002) is optimised to zero page unless ZPOPT is off
        written_long = bool(re.fullmatch(r"\$0{2}[0-9A-Fa-f]{2}", s.operand.strip()))
        if written_long and want_zp and not st.get("zpopt", True) and abs_mode in modes:
            want_zp = False
            if final:
                st.setdefault("warn", []).append(f"{name} {s.operand.strip()} could be zero page (ZPOPT is off)")
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
