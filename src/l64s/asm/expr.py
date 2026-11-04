"""Expression lexer and evaluator for the CBM prg Studio dialect.

Supported:
  numbers   $FF  %1010  255  'a' (screen code of the character)
  symbols   labels/constants, '*' (current program counter)
  unary     -  ~  !  <  (low byte)  >  (high byte)  #  (no-op, seen as `#1<<#/1` in the book)
  binary    * / %   + -   << >>   < > <= >=   = == <> !=   &   ^   |

`Operator HiLo` (the default) makes `<`/`>` bind tightly: `<A+1` is `(<A)+1`.
`Operator Calc` evaluates the rest of the expression first: `<A+1` is `<(A+1)`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .errors import AsmError
from .charset import char_to_screencode


class Undefined(Exception):
    """A symbol isn't defined (yet). Raised during early passes."""

    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


@dataclass
class Tok:
    kind: str  # num, sym, op, pc, end
    value: object
    pos: int


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<hex>\$[0-9A-Fa-f]+)
  | (?P<bin>%[01]+)
  | (?P<dec>[0-9]+)
  | (?P<chr>'(?:[^']|'')'|"(?:[^"])")
  | (?P<sym>[@A-Za-z_][A-Za-z0-9_.@]*)
  | (?P<op><<|>>|<=|>=|<>|!=|==|[-+*/%&|^~!<>=()#])
    """,
    re.VERBOSE,
)


def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise AsmError(f"Unexpected character {text[pos]!r} in expression '{text}'")
        kind = m.lastgroup
        s = m.group(kind)
        if kind == "hex":
            toks.append(Tok("num", int(s[1:], 16), pos))
        elif kind == "bin":
            toks.append(Tok("num", int(s[1:], 2), pos))
        elif kind == "dec":
            toks.append(Tok("num", int(s), pos))
        elif kind == "chr":
            ch = s[1:-1]
            if ch == "''":
                ch = "'"
            toks.append(Tok("num", char_to_screencode(ch), pos))
        elif kind == "sym":
            toks.append(Tok("sym", s, pos))
        elif kind == "op":
            toks.append(Tok("op", s, pos))
        pos = m.end()
    toks.append(Tok("end", None, len(text)))
    return toks


# Binary operator precedence (higher binds tighter).
_BINARY = {
    "|": 1, "^": 2, "&": 3,
    "=": 4, "==": 4, "<>": 4, "!=": 4,
    "<": 5, ">": 5, "<=": 5, ">=": 5,
    "<<": 6, ">>": 6,
    "+": 7, "-": 7,
    "*": 8, "/": 8, "%": 8,
}
_UNARY_PREC = 9


def _apply(op: str, a: int, b: int) -> int:
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if op == "/":
        if b == 0:
            raise AsmError("Division by zero")
        return int(a / b)
    if op == "%":
        if b == 0:
            raise AsmError("Division by zero")
        return a % b
    if op == "<<": return a << b
    if op == ">>": return a >> b
    if op == "&": return a & b
    if op == "|": return a | b
    if op == "^": return a ^ b
    if op in ("=", "=="): return int(a == b)
    if op in ("<>", "!="): return int(a != b)
    if op == "<": return int(a < b)
    if op == ">": return int(a > b)
    if op == "<=": return int(a <= b)
    if op == ">=": return int(a >= b)
    raise AsmError(f"Unknown operator {op}")


class Evaluator:
    """Pratt-parser evaluator. `lookup(name)` returns a value or raises Undefined."""

    def __init__(self, lookup: Callable[[str], int], pc: int | None, calc_mode: bool):
        self.lookup = lookup
        self.pc = pc
        self.calc_mode = calc_mode

    def evaluate(self, text: str) -> int:
        self.text = text
        self.toks = tokenize(text)
        self.i = 0
        if self.toks[0].kind == "end":
            raise AsmError("Missing expression")
        value = self._expr(0)
        if self._peek().kind != "end":
            raise AsmError(f"Unexpected '{self._peek().value}' in expression '{text}'")
        return value

    def _peek(self) -> Tok:
        return self.toks[self.i]

    def _next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def _expr(self, min_prec: int) -> int:
        left = self._unary()
        while True:
            t = self._peek()
            if t.kind != "op" or t.value not in _BINARY:
                return left
            prec = _BINARY[t.value]
            if prec <= min_prec:
                return left
            self._next()
            right = self._expr(prec)
            left = _apply(t.value, left, right)

    def _unary(self) -> int:
        t = self._peek()
        if t.kind == "op":
            if t.value in ("<", ">"):
                self._next()
                # Calc mode: low/high byte of the whole remaining expression.
                v = self._expr(0) if self.calc_mode else self._unary()
                return (v & 0xFF) if t.value == "<" else ((v >> 8) & 0xFF)
            if t.value == "-":
                self._next()
                return -self._unary()
            if t.value in ("~", "!"):
                self._next()
                v = self._unary()
                return (~v) & 0xFFFF if t.value == "~" else int(v == 0)
            if t.value == "#":
                self._next()
                return self._unary()
            if t.value == "+":
                self._next()
                return self._unary()
        return self._primary()

    def _primary(self) -> int:
        t = self._next()
        if t.kind == "num":
            return t.value
        if t.kind == "sym":
            return self.lookup(t.value)
        if t.kind == "op" and t.value == "*":
            if self.pc is None:
                raise AsmError("'*' used before an origin is set")
            return self.pc
        if t.kind == "op" and t.value == "(":
            v = self._expr(0)
            close = self._next()
            if close.kind != "op" or close.value != ")":
                raise AsmError(f"Missing ')' in expression '{self.text}'")
            return v
        if t.kind == "end":
            raise AsmError(f"Expression '{self.text}' ends unexpectedly")
        raise AsmError(f"Unexpected '{t.value}' in expression '{self.text}'")


def symbols_in(text: str) -> list[str]:
    """Names of all symbols referenced by an expression (best effort)."""
    try:
        return [t.value for t in tokenize(text) if t.kind == "sym"]
    except AsmError:
        return []
