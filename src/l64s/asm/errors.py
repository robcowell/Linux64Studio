"""Diagnostics shared by the assembler modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLoc:
    file: str
    line: int  # 1-based
    macro: str | None = None  # name of the macro this line was expanded from

    def __str__(self) -> str:
        s = f"{self.file}:{self.line}"
        if self.macro:
            s += f" (in macro {self.macro})"
        return s


class AsmError(Exception):
    """An assembly error. `loc` is filled in by the assembler if the raiser doesn't know it."""

    def __init__(self, message: str, loc: SourceLoc | None = None):
        super().__init__(message)
        self.message = message
        self.loc = loc

    def __str__(self) -> str:
        return f"{self.loc}: error: {self.message}" if self.loc else self.message


@dataclass
class Diagnostic:
    severity: str  # "error" | "warning"
    message: str
    loc: SourceLoc | None

    def __str__(self) -> str:
        where = f"{self.loc}: " if self.loc else ""
        return f"{where}{self.severity}: {self.message}"
