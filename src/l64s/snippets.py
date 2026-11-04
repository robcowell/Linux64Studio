"""Code snippets: small, often-needed routines to paste into a program, kept in CBM prg Studio's
Snippets.xml format so the two can share them.

  <snippets>
    <snippet>
      <type>0</type>                  0 Sprites, 1 Characters, 2 Hi-res, 3 Sound, 4 Misc, 5 Machine Code
      <description>…</description>
      <code><line>…</line>…</code>
    </snippet>
  </snippets>

Machine Code snippets are assembler; the rest are BASIC, written without line numbers. BASIC
snippets may use labels !1-!9: a line starting "!n " is label n, and "!n" elsewhere (after GOTO,
GOSUB, THEN…) becomes that line's number when the snippet is numbered.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

TYPES = ["Sprites", "Characters", "Hi-res", "Sound", "Misc", "Machine Code"]
MACHINE_CODE = 5
BUILTIN = Path(__file__).parent / "data" / "snippets.xml"


class SnippetError(ValueError):
    pass


@dataclass
class Snippet:
    type: int
    description: str
    lines: list[str] = field(default_factory=list)

    @property
    def is_basic(self) -> bool:
        return self.type != MACHINE_CODE

    @property
    def code(self) -> str:
        return "\n".join(self.lines)

    @code.setter
    def code(self, text: str) -> None:
        self.lines = text.replace("\r\n", "\n").rstrip("\n").split("\n") if text.strip() else []

    @property
    def key(self) -> tuple[int, str]:
        return self.type, self.description.strip().lower()


# ---------------------------------------------------------------------- files

def parse(text: str) -> list[Snippet]:
    try:
        root = ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError as e:
        raise SnippetError(f"Not a snippets file: {e}") from e
    if root.tag != "snippets":
        raise SnippetError("Not a snippets file (it should start with <snippets>)")
    out = []
    for s in root.findall("snippet"):
        try:
            kind = int((s.findtext("type") or "4").strip())
        except ValueError:
            kind = 4
        if not 0 <= kind < len(TYPES):
            kind = 4
        lines = [ln.text or "" for ln in s.findall("code/line")]
        out.append(Snippet(kind, (s.findtext("description") or "").strip(), lines))
    return out


def load(path: str | Path) -> list[Snippet]:
    return parse(Path(path).read_text(encoding="utf-8-sig"))


def to_xml(snippets: list[Snippet]) -> str:
    root = ET.Element("snippets")
    for sn in snippets:
        s = ET.SubElement(root, "snippet")
        ET.SubElement(s, "type").text = str(sn.type)
        ET.SubElement(s, "description").text = sn.description
        code = ET.SubElement(s, "code")
        for line in sn.lines:
            ET.SubElement(code, "line").text = line
    ET.indent(root, "  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def save(snippets: list[Snippet], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(to_xml(snippets), encoding="utf-8")
    tmp.replace(p)


def builtin() -> list[Snippet]:
    return load(BUILTIN)


def merge(into: list[Snippet], new: list[Snippet]) -> int:
    """Add the snippets that aren't already there (same type and description); returns how many."""
    have = {s.key for s in into}
    added = 0
    for s in new:
        if s.key not in have:
            into.append(s)
            have.add(s.key)
            added += 1
    return added


# ---------------------------------------------------------------------- expanding

_LABEL_DEF = re.compile(r"^\s*!([1-9])(?=\s|$)\s?")
_LABEL_REF = re.compile(r"!([1-9])")


def _outside_strings(line: str, fn) -> str:
    """Apply fn to the parts of a BASIC line outside quotes (and before a REM)."""
    out = []
    parts = re.split(r'("[^"]*"?)', line)
    rem = False
    for part in parts:
        if rem or part.startswith('"'):
            out.append(part)
            continue
        m = re.search(r"\brem\b", part, re.I)
        if m:
            out.append(fn(part[:m.start()]) + part[m.start():])
            rem = True
        else:
            out.append(fn(part))
    return "".join(out)


def cbm_case(text: str) -> str:
    """CBM prg Studio's snippets are written in capitals, which in a BASIC listing are shifted
    characters. Text with no lower case letters is turned into lower case (control codes in
    braces are left alone)."""
    if re.search(r"[a-z]", re.sub(r"\{[^}]*\}", "", text)):
        return text
    return re.sub(r"\{[^}]*\}|[^{]+", lambda m: m.group(0) if m.group(0).startswith("{") else m.group(0).lower(), text)


def number_basic(lines: list[str], start: int = 1000, step: int = 10) -> list[str]:
    """Number a BASIC snippet's lines and resolve its !n labels."""
    if step < 1:
        raise SnippetError("The step must be at least 1")
    code = [ln for ln in lines if ln.strip()]
    labels: dict[str, int] = {}
    bodies = []
    for i, ln in enumerate(code):
        n = start + i * step
        m = _LABEL_DEF.match(ln)
        if m:
            if m.group(1) in labels:
                raise SnippetError(f"Label !{m.group(1)} is used for two lines")
            labels[m.group(1)] = n
            ln = ln[m.end():]
        bodies.append((n, ln.strip()))
    if code and bodies[-1][0] > 63999:
        raise SnippetError(f"The line numbers run past 63999 (to {bodies[-1][0]}): start lower or use a smaller step")

    def resolve(part: str) -> str:
        def ref(m):
            if m.group(1) not in labels:
                raise SnippetError(f"!{m.group(1)} is used but no line is labelled !{m.group(1)}")
            return str(labels[m.group(1)])
        return _LABEL_REF.sub(ref, part)

    return [f"{n} {_outside_strings(body, resolve)}" for n, body in bodies]


def expand(snippet: Snippet, start: int = 1000, step: int = 10, kickass: bool = False) -> str:
    """The snippet as it's pasted: numbered BASIC in listing case, or assembler."""
    if snippet.is_basic:
        return "\n".join(number_basic([cbm_case(ln) for ln in snippet.lines], start, step)) + "\n"
    text = snippet.code + "\n"
    return to_kickass(text) if kickass else text


# ---------------------------------------------------------------------- CBM -> Kick Assembler

_DIRECTIVES = {"byte": ".byte", "byt": ".byte", "db": ".byte", "word": ".word", "dw": ".word", "text": ".text"}


def to_kickass(text: str) -> str:
    """A light conversion of simple CBM-syntax assembler to Kick Assembler: comments, labels
    in column 1 (given a colon), `*=`, constants and data directives. Macros aren't converted."""
    from .asm.opcodes import OPCODES
    out = []
    for line in text.split("\n"):
        code, sep, comment = line.partition(";")
        comment = ("//" + comment) if sep else ""
        stripped = code.strip()
        if not stripped:
            out.append((code + comment).rstrip())
            continue
        m = re.match(r"^\*\s*=\s*(.+)$", stripped)
        if m:
            out.append(f"*= {m.group(1).strip()}" + (f"  {comment}" if comment else ""))
            continue
        m = re.match(r"^([A-Za-z_][\w]*)\s*=\s*(.+)$", stripped)
        if m:
            out.append(f".const {m.group(1)} = {m.group(2).strip()}" + (f"  {comment}" if comment else ""))
            continue
        label = ""
        rest = code
        if code and not code[0].isspace():
            first, _, rest = code.partition(" ")
            first = first.rstrip(":")
            if first.lower() in OPCODES or first.lower() in _DIRECTIVES:
                rest, first = code, ""
            label = f"{first}:" if first else ""
        words = rest.strip().split(None, 1)
        if words and words[0].lower() in _DIRECTIVES:
            rest = _DIRECTIVES[words[0].lower()] + (" " + words[1] if len(words) > 1 else "")
        else:
            rest = rest.strip()
        body = f"{label:<12}{rest}" if label else f"            {rest}" if rest else label
        out.append((body + (f"  {comment}" if comment else "")).rstrip())
    return "\n".join(out)
