"""Data Generator: tables of values from a function of x, as CBM prg Studio's tool makes them,
for sine waves, movement paths, curves and the like.

The function uses x and can use + - * / ^ (power), brackets, pi, and sin cos tan atn (radians),
exp log sqr/sqrt abs int sgn, min max. Names are case-insensitive, so the BASIC way of
writing it (INT(100+99*SIN(X/20))) works too. x runs from the start to the end (both included)
in steps of a whole number. The output is byte or word values (rounded to the nearest whole
number) or 5-byte floats (fltp), optionally as differences (deltas) from the previous value, as
x, y pairs, and clamped to a range.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

from .cbmfloat import FloatError, to_cbm

FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "atn": math.atan, "atan": math.atan,
    "exp": math.exp, "log": math.log, "sqr": math.sqrt, "sqrt": math.sqrt, "abs": abs,
    "int": math.floor, "sgn": lambda v: (v > 0) - (v < 0), "min": min, "max": max,
    "asin": math.asin, "acos": math.acos, "floor": math.floor, "ceil": math.ceil, "round": round,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
TYPES = ("byte", "word", "float")
RANGES = {"byte": (-128, 255), "word": (-32768, 65535)}


class DataGenError(ValueError):
    pass


class Function:
    """A function of x, parsed once and evaluated many times (only arithmetic is allowed).
    `var` names the variable; with `need_var` False it may be a constant (a path's y = 5)."""

    def __init__(self, text: str, var: str = "x", need_var: bool = True):
        self.text = text.strip()
        self.var = var
        if not self.text:
            raise DataGenError(f"Enter a function with at least one {var} term, e.g. sin({var})")
        src = self.text.lower().replace("^", "**")
        try:
            tree = ast.parse(src, mode="eval")
        except SyntaxError:
            raise DataGenError(f"The function is badly formed: {self.text}") from None
        uses_x = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id == var:
                    uses_x = True
                elif node.id not in CONSTANTS and node.id not in FUNCTIONS:
                    raise DataGenError(f"Unknown name '{node.id}' in the function")
            elif isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                    raise DataGenError("Only these functions can be used: " + ", ".join(sorted(FUNCTIONS)))
                if node.keywords:
                    raise DataGenError("The function is badly formed")
            elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Load,
                                       ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
                                       ast.USub, ast.UAdd)):
                raise DataGenError(f"The function is badly formed: {self.text}")
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                raise DataGenError(f"The function is badly formed: {self.text}")
        if not uses_x and need_var:
            raise DataGenError(f"The function must contain an {var} term, e.g. sin({var})")
        self._code = compile(tree, "<function>", "eval")

    def __call__(self, x: float) -> float:
        env = {"__builtins__": {}, self.var: x, **CONSTANTS, **FUNCTIONS}
        try:
            v = eval(self._code, env)           # noqa: S307 - the tree was checked to be arithmetic only
        except ZeroDivisionError:
            raise DataGenError(f"Division by zero at {self.var}={x}") from None
        except (ValueError, OverflowError, TypeError) as e:
            raise DataGenError(f"Problem generating data at {self.var}={x}: {e}") from None
        if isinstance(v, complex) or not math.isfinite(v):
            raise DataGenError(f"Problem generating data at {self.var}={x}: the result isn't a real number")
        return float(v)


@dataclass
class Options:
    function: str = "100+99*sin(x/20)"
    start: int = 0
    end: int = 255
    step: int = 1
    type: str = "byte"
    deltas: bool = False
    include_x: bool = False
    clamp: bool = False
    clamp_min: float = 0
    clamp_max: float = 255
    per_line: int = 8
    comment: bool = True
    label: str = ""
    kickass: bool = False
    syntax: str = ""          # "ca65" or "c" (syntax.py); otherwise kickass chooses Kick or CBM


@dataclass
class Table:
    xs: list[int]
    ys: list[float]                 # the function's values, after clamping
    values: list[float]             # what's output: ys or their deltas, rounded for bytes/words


def generate(opts: Options) -> Table:
    if opts.step < 1:
        raise DataGenError("The step must be a whole number of 1 or more")
    if opts.start == opts.end:
        raise DataGenError("The start and end values can't be the same")
    if opts.start > opts.end:
        raise DataGenError("The start value must be less than the end value")
    if opts.type not in TYPES:
        raise DataGenError(f"Unknown output type {opts.type!r}")
    if opts.clamp and opts.clamp_min > opts.clamp_max:
        raise DataGenError("The clamping minimum is above the maximum")
    f = Function(opts.function)
    xs = list(range(opts.start, opts.end + 1, opts.step))
    if len(xs) > 65536:
        raise DataGenError("That's more than 65536 values: use a bigger step or a smaller range")
    ys = []
    for x in xs:
        y = f(x)
        if opts.clamp:
            y = min(max(y, opts.clamp_min), opts.clamp_max)
        ys.append(y)
    if opts.type != "float":
        ys = [_round(y) for y in ys]
    values = [ys[0]] + [b - a for a, b in zip(ys, ys[1:])] if opts.deltas else list(ys)
    if opts.type in RANGES:
        lo, hi = RANGES[opts.type]
        for x, v in zip(xs, values):
            if not lo <= v <= hi:
                raise DataGenError(f"Problem generating data at x={x}. Result too large for a "
                                   f"{opts.type} ({v:g}, which must be {lo} to {hi})"
                                   + (". Try clamping the values" if not opts.clamp else ""))
        if opts.include_x:
            for x in xs:
                if not lo <= x <= hi:
                    raise DataGenError(f"x={x} is too large for a {opts.type} (Include x values is on)")
    return Table(xs, ys, values)


def _round(y: float) -> int:
    return math.floor(y + 0.5)          # halves round up, as INT(Y+.5) does


def _fmt_int(v: float, typ: str) -> str:
    v = int(v)
    return str(v) if v < 0 else (f"${v:02X}" if typ == "byte" else f"${v:04X}")


def source(opts: Options, table: Table | None = None) -> str:
    t = table or generate(opts)
    from .syntax import CA65, C, resolve
    sx = resolve(opts.syntax or None, opts.kickass)
    if sx in (CA65, C):
        return _source_ca65_c(opts, t, sx)
    c = "//" if opts.kickass else ";"
    ind = "    " if opts.kickass else "        "
    out = []
    if opts.comment:
        what = "deltas of " if opts.deltas else ""
        pairs = "x, y pairs: " if opts.include_x else ""
        clamp = f", clamped to {opts.clamp_min:g}..{opts.clamp_max:g}" if opts.clamp else ""
        out.append(f"{c} {pairs}{what}y = {opts.function} for x = {opts.start} to {opts.end} step {opts.step}"
                   f"{clamp} ({len(t.xs)} values)")
    if opts.label:
        out.append(f"{opts.label}:" if opts.kickass else opts.label)
    per = max(1, opts.per_line)
    if opts.type == "float":
        items = []
        for x, v in zip(t.xs, t.values):
            if opts.include_x:
                items.append(float(x))
            items.append(v)
        for i in range(0, len(items), per):
            chunk = items[i:i + per]
            if opts.kickass:
                try:
                    data = b"".join(to_cbm(v) for v in chunk)
                except FloatError as e:
                    raise DataGenError(str(e)) from None
                out.append(f"{ind}.byte " + ", ".join(f"${b:02X}" for b in data)
                           + f"    // {', '.join(f'{v:.9g}' for v in chunk)}")
            else:
                for v in chunk:                     # check they fit before writing them
                    try:
                        to_cbm(v)
                    except FloatError as e:
                        raise DataGenError(str(e)) from None
                out.append(f"{ind}fltp " + ", ".join(f"{v:.9g}" for v in chunk))
        return "\n".join(out) + "\n"
    directive = ("." if opts.kickass else "") + ("byte" if opts.type == "byte" else "word")
    items = []
    for x, v in zip(t.xs, t.values):
        if opts.include_x:
            items.append(_fmt_int(x, opts.type))
        items.append(_fmt_int(v, opts.type))
    for i in range(0, len(items), per):
        out.append(f"{ind}{directive} " + ", ".join(items[i:i + per]))
    return "\n".join(out) + "\n"


def _source_ca65_c(opts: Options, t: Table, sx: str) -> str:
    """The table in ca65 (.byte/.word) or C (an array). Floats are each 5 bytes, as CBM BASIC holds them."""
    from .syntax import table as write_table
    note = None
    if opts.comment:
        what = "deltas of " if opts.deltas else ""
        pairs = "x, y pairs: " if opts.include_x else ""
        clamp = f", clamped to {opts.clamp_min:g}..{opts.clamp_max:g}" if opts.clamp else ""
        note = (f"{pairs}{what}y = {opts.function} for x = {opts.start} to {opts.end} step {opts.step}"
                f"{clamp} ({len(t.xs)} values)")
    if opts.type == "float":
        data = bytearray()
        for x, v in zip(t.xs, t.values):
            for f in ([float(x)] if opts.include_x else []) + [v]:
                try:
                    data += to_cbm(f)
                except FloatError as e:
                    raise DataGenError(str(e)) from None
        return write_table(sx, opts.label, data, 1, max(1, opts.per_line) * 5,
                           comment_text=(note + ", as 5-byte CBM floats") if note else "5-byte CBM floats")
    values = []
    for x, v in zip(t.xs, t.values):
        if opts.include_x:
            values.append(int(x))
        values.append(int(v))
    return write_table(sx, opts.label, values, 1 if opts.type == "byte" else 2, max(1, opts.per_line),
                       comment_text=note)


def label_ok(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))
