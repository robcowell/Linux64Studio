"""Kick Assembler tools (CBM prg Studio's Tools → Kick Assembler Tools): turn a selection into a
Kick Assembler Hashtable or List.

The selection is one item a line. For a hash table each line is a key and a value, separated by
`=`, `,`, `:`, a tab or spaces (`1 North`, `UP = 1`); for a list a line may also hold several items
separated by commas. Comments (`//`, `;`) and blank lines are skipped. Items already in quotes keep
them; Add Quotes puts them round the others.
"""
from __future__ import annotations

import re

TABLE, SINGLE, MULTIPLE = "table", "single", "multiple"      # hash table output
LIST, STRING = "list", "string"                              # list output


class KickToolError(ValueError):
    pass


def _lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = re.split(r"\s(?://|;)|^(?://|;)", line, maxsplit=1)[0].strip()
        if s:
            out.append(s)
    return out


def _split_commas(s: str) -> list[str]:
    """Items separated by commas, outside quotes and brackets."""
    out, cur, q, depth = [], "", False, 0
    for ch in s:
        if ch == '"':
            q = not q
        elif not q and ch in "([{":
            depth += 1
        elif not q and ch in ")]}":
            depth -= 1
        if ch == "," and not q and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_pairs(text: str) -> list[tuple[str, str]]:
    """Key-value pairs, one a line."""
    pairs = []
    for line in _lines(text):
        m = re.match(r'^("[^"]*"|[^=,:\t ]+)\s*(?:=|,|:|\t|\s)\s*(.+)$', line)
        if not m:
            raise KickToolError(f"No value for {line!r}: write a key and a value on each line (1 North, UP=1)")
        pairs.append((m.group(1), m.group(2).strip()))
    if not pairs:
        raise KickToolError("Select some lines, a key and a value on each")
    return pairs


def parse_items(text: str) -> list[str]:
    items = [it for line in _lines(text) for it in _split_commas(line)]
    if not items:
        raise KickToolError("Select some items, one a line (or separated by commas)")
    return items


def _quote(s: str, on: bool) -> str:
    if not on or (len(s) >= 2 and s[0] == s[-1] == '"'):
        return s
    return '"' + s.replace('"', "'") + '"'


def _name(name: str) -> str:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise KickToolError(f"{name!r} isn't a name Kick Assembler takes: letters, digits and _")
    return name


def hashtable(name: str, pairs: list[tuple[str, str]], style: str = TABLE, quote_keys: bool = False,
              quote_values: bool = False, indent: str = "    ") -> str:
    """A Kick Assembler Hashtable of the pairs."""
    name = _name(name)
    kv = [(_quote(k, quote_keys), _quote(v, quote_values)) for k, v in pairs]
    if style == TABLE:
        body = [f"{indent}.var {name} = Hashtable()"] + [f"{indent}.eval {name}.put({k}, {v})" for k, v in kv]
        return f".define {name} {{\n" + "\n".join(body) + "\n}\n"
    if style == SINGLE:
        return f".var {name} = Hashtable().put(" + ", ".join(f"{k},{v}" for k, v in kv) + ")\n"
    if style == MULTIPLE:
        return f".var {name} = Hashtable()" + "".join(f".put({k}, {v})" for k, v in kv) + "\n"
    raise KickToolError(f"Unknown style {style}")


def kick_list(name: str, items: list[str], style: str = LIST, quote: bool = False, start: int = 0) -> str:
    """A Kick Assembler List of the items, from index `start`."""
    name = _name(name)
    if start < 0:
        raise KickToolError("The start index can't be negative")
    vals = [_quote(i, quote) for i in items]
    if style == LIST:
        return f".var {name} = List({start + len(vals)})\n" + "".join(
            f".eval {name}.set({start + n}, {v})\n" for n, v in enumerate(vals))
    if style == STRING:
        pad = ", ".join(["0"] * start)
        return f".var {name} = List().add(" + (pad + ", " if pad else "") + ", ".join(vals) + ")\n"
    raise KickToolError(f"Unknown style {style}")
