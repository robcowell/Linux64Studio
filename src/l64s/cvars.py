"""C variables while debugging a cc65 program: their types, from the program's C source, and their
values, from memory.

cc65 2.18's debug information has no C types: ld65's debug file gives each global variable's address
(as the label ``_name``) and each function's parameters and locals with their offset on cc65's own C
stack, but not what they are. So the types come from the declarations in the source, read by a small
C declaration reader (``parse_source``): enough for the integer types, pointers, arrays, structs,
enums and typedefs a C64 program uses. ``format_value`` shows a value as its type says.

Locals live on cc65's C stack. A function's frame starts where the C stack pointer was on entry,
after the arguments were pushed: a variable is at that base plus its offset (parameters at or above
it, locals below). cc65 makes room for a local when its declaration runs, so at the start of a line
the base is the stack pointer plus the sizes of the locals declared on the lines before
(``frame_base``). Mid-line, temporaries may also be on the stack, so locals are only exact at the
start of a line, which is where stepping by C line stops.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

_INT_SIZES = {"char": 1, "short": 2, "int": 2, "long": 4, "enum": 2, "void": 0}
# standard typedefs (stdint.h, stddef.h, stdbool.h) as cc65 defines them
_STD_TYPEDEFS = {"uint8_t": ("char", True), "int8_t": ("char", False), "uint16_t": ("int", True),
                 "int16_t": ("int", False), "uint32_t": ("long", True), "int32_t": ("long", False),
                 "size_t": ("int", True), "ptrdiff_t": ("int", False), "bool": ("char", True),
                 "_Bool": ("char", True)}
_KEYWORDS = {"static", "extern", "register", "auto", "const", "volatile", "signed", "unsigned", "char",
             "short", "int", "long", "void", "struct", "union", "enum", "typedef", "fastcall", "__fastcall__",
             "cdecl", "__cdecl__", "near", "far"}
_STATEMENT_WORDS = {"return", "if", "else", "for", "while", "do", "switch", "case", "default", "break",
                    "continue", "goto", "sizeof"}


@dataclass(frozen=True)
class CType:
    base: str                    # char, short, int, long, enum, void, struct, union
    unsigned: bool = False
    pointer: int = 0             # levels of *
    dims: tuple[int, ...] = ()   # array dimensions (0 = unknown)
    tag: str = ""                # struct/union/enum name
    signed: bool = False         # "signed char" written out (plain char is unsigned in cc65)

    @property
    def plain_char(self) -> bool:
        """A plain ``char``: a character. ``unsigned char`` / ``signed char`` are numbers (bytes)."""
        return self.base == "char" and not self.unsigned and not self.signed and not self.pointer

    def size(self, structs: dict[str, list[tuple[str, CType]]] | None = None) -> int | None:
        if self.pointer:
            one = 2
        elif self.base in ("struct", "union"):
            members = (structs or {}).get(self.tag)
            if not members:
                return None
            sizes = [t.size(structs) for _n, t in members]
            if any(s is None for s in sizes):
                return None
            one = max(sizes) if self.base == "union" else sum(sizes)
        else:
            one = _INT_SIZES.get(self.base)
            if one is None:
                return None
        for d in self.dims:
            if d <= 0:
                return None
            one *= d
        return one

    def element(self) -> CType:
        return replace(self, dims=self.dims[1:])

    def __str__(self) -> str:
        if self.base in ("struct", "union", "enum"):
            name = f"{self.base} {self.tag}".strip() if not self.tag.startswith("(") else self.base
        else:
            name = ("unsigned " if self.unsigned else "signed " if self.signed else "") + self.base
        return name + (" " + "*" * self.pointer if self.pointer else "") + "".join(f"[{d or ''}]" for d in self.dims)


@dataclass
class Function:
    name: str
    first_line: int
    last_line: int
    file: str = ""                # set by CProgram: the source file it's in
    param_lines: dict[str, int] = field(default_factory=dict)
    params: list[tuple[str, CType]] = field(default_factory=list)
    # (name, type, line declared, last line of its block): a local only takes room on the stack from
    # its declaration to the end of the block it's declared in
    locals: list[tuple[str, CType, int, int]] = field(default_factory=list)


@dataclass
class CSource:
    globals: dict[str, CType] = field(default_factory=dict)
    functions: dict[str, Function] = field(default_factory=dict)
    structs: dict[str, list[tuple[str, CType]]] = field(default_factory=dict)
    typedefs: dict[str, CType] = field(default_factory=dict)
    enums: dict[str, dict[int, str]] = field(default_factory=dict)    # tag -> {value: member}
    # every name the file declares at file level, with where, for the editor (symindex): kind is
    # function, prototype, variable, extern, typedef, struct, union, enum, enumconst or macro
    symbols: list[tuple[str, str, int]] = field(default_factory=list)

    def merge(self, other: CSource) -> None:
        for k, v in other.globals.items():
            self.globals.setdefault(k, v)
        self.functions.update(other.functions)
        for k, v in other.structs.items():
            self.structs.setdefault(k, v)
        for k, v in other.typedefs.items():
            self.typedefs.setdefault(k, v)
        for k, v in other.enums.items():
            self.enums.setdefault(k, v)


# ------------------------------------------------------------------------ reading declarations
_TOKEN = re.compile(r"[A-Za-z_]\w*|0[xX][0-9A-Fa-f]+|\d+|\S")


def _blank(text: str) -> str:
    """Comments, strings, character constants and preprocessor lines as spaces (lines kept)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(c + " " * (j - i - 2) + c if j - i >= 2 else " ")
            i = j
        elif c == "#" and (i == 0 or text[i - 1] == "\n" or text[:i].rsplit("\n", 1)[-1].strip() == ""):
            j = i
            while True:                          # a directive, with its \\ continuation lines
                k = text.find("\n", j)
                k = n if k < 0 else k
                if k > 0 and text[k - 1] == "\\" and k < n:
                    j = k + 1
                    continue
                break
            out.append(re.sub(r"[^\n]", " ", text[i:k]))
            i = k
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _tokens(text: str) -> list[tuple[str, int]]:
    out = []
    for n, line in enumerate(_blank(text).split("\n"), start=1):
        out.extend((m.group(0), n) for m in _TOKEN.finditer(line))
    return out


def _number(tok: str) -> int:
    try:
        return int(tok, 16) if tok.lower().startswith("0x") else int(tok)
    except ValueError:
        return 0


_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+([^\n]*?)[ \t]*(?://.*|/\*.*)?$", re.M)
_MACRO_NAME = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", re.M)
_ARITH = re.compile(r"^[\s\d()+\-*/%xXa-fA-F<>]*$")


def defines(text: str) -> dict[str, str]:
    """The source's ``#define NAME value`` lines (for array sizes such as ``char buf[BUFSIZE]``)."""
    return {m.group(1): m.group(2) for m in _DEFINE.finditer(text)}


def constant(expr: str, macros: dict[str, str], depth: int = 0) -> int:
    """An integer constant expression, with macros put in: 40 * 25, (BUFSIZE + 1), 0x100. 0 if it's
    anything else."""
    if depth > 8:
        return 0
    def sub(m):
        name = m.group(0)
        if name in macros:
            return f"({constant(macros[name], macros, depth + 1)})"
        return name
    text = re.sub(r"(?<![0-9xX])[A-Za-z_]\w*", sub, expr)
    text = re.sub(r"\b(0[xX][0-9A-Fa-f]+|\d+)[uUlL]*\b", lambda m: str(_number(m.group(1))), text)
    if not text.strip() or not _ARITH.match(text) or re.search(r"[A-Za-z_]", text.replace("x", "").replace("X", "")):
        return 0
    try:
        v = eval(text.replace("/", "//"), {"__builtins__": {}}, {})       # digits and operators only
    except Exception:
        return 0
    return v if isinstance(v, int) and v > 0 else 0


class _Reader:
    def __init__(self, text: str, macros: dict[str, str] | None = None):
        self.toks = _tokens(text)
        self.src = CSource()
        self.macros = {**(macros or {}), **defines(text)}
        for m in _MACRO_NAME.finditer(text):
            self.src.symbols.append((m.group(1), "macro", text.count("\n", 0, m.start(1)) + 1))

    # specifiers: storage, qualifiers and the base type. Returns (type, is_typedef, next index) or None
    def specifiers(self, i: int) -> tuple[CType, bool, int] | None:
        toks = self.toks
        base, unsigned, tag, seen, typedef, signed = None, False, "", False, False, False
        longs = 0
        while i < len(toks):
            t = toks[i][0]
            if t in ("static", "extern", "register", "auto", "const", "volatile", "fastcall", "__fastcall__",
                     "cdecl", "__cdecl__", "near", "far"):
                i += 1
            elif t == "typedef":
                typedef = True
                i += 1
            elif t in ("signed", "unsigned"):
                unsigned, signed, seen = t == "unsigned", t == "signed", True
                i += 1
            elif t in ("char", "short", "int", "void"):
                if not (t == "int" and base in ("short", "long")):
                    base = t
                seen = True
                i += 1
            elif t == "long":
                longs += 1
                base, seen = "long", True
                i += 1
            elif t in ("struct", "union", "enum"):
                base, seen = t, True
                i += 1
                tag_line = 0
                if i < len(toks) and re.match(r"[A-Za-z_]", toks[i][0]) and toks[i][0] not in _KEYWORDS:
                    tag, tag_line = toks[i]
                    i += 1
                if i < len(toks) and toks[i][0] == "{":
                    if tag:
                        self.src.symbols.append((tag, base, tag_line))
                    elif base == "enum":             # typedef enum { ... } name: give it a name of its own
                        tag = f"(enum at line {toks[i][1]})"
                    i = self.struct_body(i, base, tag)
            elif not seen and (t in self.src.typedefs or t in _STD_TYPEDEFS):
                if t in self.src.typedefs:
                    td = self.src.typedefs[t]
                    base, unsigned, tag, signed = td.base, td.unsigned, td.tag, td.signed
                    if td.pointer or td.dims:
                        return td, typedef, i + 1
                else:
                    base, unsigned = _STD_TYPEDEFS[t]
                seen = True
                i += 1
            else:
                break
        if not seen:
            return None
        return CType(base or "int", unsigned, 0, (), tag, signed), typedef, i

    def struct_body(self, i: int, kind: str, tag: str) -> int:
        """At '{' of a struct/union/enum body: read its members, return the index after '}'."""
        depth, j = 0, i
        while j < len(self.toks):
            if self.toks[j][0] == "{":
                depth += 1
            elif self.toks[j][0] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if kind == "enum":                          # its constants: each name after '{' or ','
            depth, value, names = 0, -1, {}
            for k in range(i, j):
                t, line = self.toks[k]
                depth += t in "({["
                depth -= t in ")}]"
                if depth == 1 and self.toks[k - 1][0] in ("{", ",") and re.match(r"[A-Za-z_]", t):
                    self.src.symbols.append((t, "enumconst", line))
                    value += 1
                    if k + 1 < j and self.toks[k + 1][0] == "=":     # NAME = value
                        e = k + 2
                        while e < j and self.toks[e][0] not in (",", "}"):
                            e += 1
                        expr = " ".join(x for x, _l in self.toks[k + 2:e])
                        known = {**self.macros, **{n: str(v) for v, n in names.items()}}
                        value = constant(expr, known) if expr.strip() not in ("0", "0x0", "0X0") else 0
                    names[value] = t
            if tag:
                self.src.enums[tag] = names
        if kind != "enum" and tag:
            members: list[tuple[str, CType]] = []
            k = i + 1
            while k < j:
                spec = self.specifiers(k)
                if spec is None:
                    k += 1
                    continue
                for name, ctype, _line, k in self.declarators(spec[0], spec[2], j):
                    members.append((name, ctype))
            self.src.structs[tag] = members
        return j + 1

    def declarators(self, base: CType, i: int, end: int):
        """Each `*name[N]` after the specifiers, up to ';' (skipping initialisers). Yields
        (name, type, line, index after it)."""
        toks = self.toks
        while i < end and toks[i][0] != ";":
            pointer = 0
            while i < end and toks[i][0] == "*":
                pointer += 1
                i += 1
            while i < end and toks[i][0] in ("const", "volatile", "near", "far"):
                i += 1
            if i >= end or not re.match(r"[A-Za-z_]", toks[i][0]):
                return
            name, line = toks[i]
            i += 1
            if i < end and toks[i][0] == "(":           # a function (prototype or definition): not data
                return
            dims = []
            while i < end and toks[i][0] == "[":
                j = i + 1
                while j < end and toks[j][0] != "]":
                    j += 1
                dims.append(constant(" ".join(t for t, _l in toks[i + 1:j]), self.macros))
                i = j + 1
            if i < end and toks[i][0] == "=":            # initialiser: to the next ',' or ';' at depth 0
                depth = 0
                while i < end:
                    t = toks[i][0]
                    if t in "({[":
                        depth += 1
                    elif t in ")}]":
                        depth -= 1
                    elif depth == 0 and t in ",;":
                        break
                    i += 1
                if dims and dims[0] == 0:
                    dims[0] = 0
            ctype = replace(base, pointer=base.pointer + pointer, dims=base.dims + tuple(dims))
            yield name, ctype, line, i
            if i < end and toks[i][0] == ",":
                i += 1

    def read(self) -> CSource:
        toks, i = self.toks, 0
        while i < len(toks):
            spec = self.specifiers(i)
            if spec is None:
                i += 1
                continue
            base, typedef, j = spec
            # a function definition: specifiers, *name ( params ) {
            k = j
            while k < len(toks) and toks[k][0] == "*":
                k += 1
            if k + 1 < len(toks) and re.match(r"[A-Za-z_]", toks[k][0]) and toks[k + 1][0] == "(":
                close = self.matching(k + 1)
                if close + 1 < len(toks) and toks[close + 1][0] == "{":
                    i = self.function(toks[k][0], toks[k][1], k + 1, close, close + 1)
                    continue
                self.src.symbols.append((toks[k][0], "prototype", toks[k][1]))
                i = close + 1                              # a prototype
                continue
            end = j
            while end < len(toks) and toks[end][0] != ";":
                end += 1
            extern = any(toks[x][0] == "extern" for x in range(i, j))
            for name, ctype, line, _k in self.declarators(base, j, end):
                if typedef:
                    self.src.typedefs[name] = ctype
                    self.src.symbols.append((name, "typedef", line))
                else:
                    if not extern or name not in self.src.globals:
                        self.src.globals[name] = ctype
                    self.src.symbols.append((name, "extern" if extern else "variable", line))
            i = end + 1
        return self.src

    def matching(self, i: int) -> int:
        """The index of the bracket closing the one at i."""
        pairs = {"(": ")", "{": "}", "[": "]"}
        open_, close, depth = self.toks[i][0], pairs[self.toks[i][0]], 0
        while i < len(self.toks):
            if self.toks[i][0] == open_:
                depth += 1
            elif self.toks[i][0] == close:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return len(self.toks) - 1

    def function(self, name: str, line: int, lp: int, rp: int, lb: int) -> int:
        rb = self.matching(lb)
        fn = Function(name, line, self.toks[rb][1])
        self.src.symbols.append((name, "function", line))
        # parameters: comma-separated declarations between the parentheses
        start = lp + 1
        for k in range(lp + 1, rp + 1):
            if self.toks[k][0] in (",", ")") and self.depth_between(lp + 1, k) == 0:
                spec = self.specifiers(start)
                if spec is not None:
                    for pname, ptype, pline, _k in self.declarators(spec[0], spec[2], k):
                        if not (ptype.base == "void" and not ptype.pointer):
                            fn.params.append((pname, ptype))
                            fn.param_lines[pname] = pline
                start = k + 1
        # locals: a declaration starts a statement (after '{', ';' or '}')
        k = lb + 1
        while k < rb:
            prev = self.toks[k - 1][0]
            if prev in ("{", ";", "}") and self.toks[k][0] not in _STATEMENT_WORDS:
                spec = self.specifiers(k)
                if spec is not None and not spec[1]:
                    end = spec[2]
                    while end < rb and self.toks[end][0] != ";":
                        end += 1
                    decl_line = self.toks[k][1]
                    block_end = self.toks[self.matching(self.enclosing_brace(k, lb))][1]
                    static = any(self.toks[x][0] == "static" for x in range(k, spec[2]))
                    for lname, ltype, _l, _k in self.declarators(spec[0], spec[2], end):
                        if not static:
                            fn.locals.append((lname, ltype, decl_line, block_end))
                    k = end + 1
                    continue
            k += 1
        self.src.functions[name] = fn
        return rb + 1

    def enclosing_brace(self, k: int, outer: int) -> int:
        """The '{' of the innermost block holding token k (no further out than ``outer``)."""
        depth = 0
        for j in range(k - 1, outer, -1):
            t = self.toks[j][0]
            if t == "}":
                depth += 1
            elif t == "{":
                if depth == 0:
                    return j
                depth -= 1
        return outer

    def depth_between(self, a: int, b: int) -> int:
        depth = 0
        for k in range(a, b):
            t = self.toks[k][0]
            depth += t in "([{"
            depth -= t in ")]}"
        return depth


def parse_source(text: str, macros: dict[str, str] | None = None) -> CSource:
    """The declarations in one C file. ``macros``: #defines from elsewhere (its headers), for sizes."""
    return _Reader(text, macros).read()


# ------------------------------------------------------------------------ showing values
def _int(data: bytes, signed: bool) -> int:
    return int.from_bytes(data, "little", signed=signed)


def _char(b: int) -> str:
    """A byte as the C64 shows it, for a char: PETSCII letters and printable characters."""
    if 0x41 <= b <= 0x5A:
        return chr(b + 32)                     # PETSCII lower-case letters (shown in the default set)
    if 0xC1 <= b <= 0xDA:
        return chr(b - 0x80)                   # shifted: capitals
    if 0x20 <= b <= 0x3F or b in (0x5B, 0x5D):
        return chr(b)
    return ""


def format_value(ctype: CType, data: bytes, structs: dict | None = None, enums: dict | None = None) -> str:
    """The value as its type says: numbers in decimal (and hex), a plain char with its character, an
    enum by its name, pointers as addresses, char arrays as text, unsigned/signed char arrays as bytes,
    other arrays and structs as {…}. Bytes it doesn't know how to show are shown in hex."""
    structs, enums = structs or {}, enums or {}
    if ctype.dims:
        elem = ctype.element()
        size = elem.size(structs)
        if not size:
            return data.hex(" ").upper()
        if elem.base == "char" and not elem.pointer and not elem.dims:
            if elem.plain_char:                     # text
                text = data.split(b"\0", 1)[0]
                shown = "".join(_char(b) or "." for b in text[:40])
                return f'"{shown}"' + ("…" if len(text) > 40 else "")
            return data[:16].hex(" ").upper() + (" …" if len(data) > 16 else "")     # data: bytes
        items = [format_value(elem, data[i:i + size], structs, enums)
                 for i in range(0, min(len(data), size * 8), size)]
        more = len(data) // size > 8
        return "{" + ", ".join(items) + (", …" if more else "") + "}"
    if ctype.pointer:
        v = _int(data[:2], False)
        return "NULL" if v == 0 else f"${v:04X}"
    if ctype.base in ("struct", "union"):
        members = structs.get(ctype.tag)
        if not members:
            return data.hex(" ")
        out, off = [], 0
        for name, mtype in members:
            size = mtype.size(structs) or 0
            out.append(f"{name} = {format_value(mtype, data[off:off + size], structs, enums)}")
            if ctype.base == "struct":
                off += size
        return "{" + ", ".join(out) + "}"
    size = ctype.size(structs)
    if not size or len(data) < size:
        return data.hex(" ")
    # (cc65's plain char is unsigned; enums are signed ints)
    v = _int(data[:size], signed=not ctype.unsigned and not ctype.plain_char)
    hexed = f"${_int(data[:size], False):0{size * 2}X}"
    if ctype.base == "enum" and v in enums.get(ctype.tag, {}):
        return f"{enums[ctype.tag][v]} ({v})"
    if ctype.plain_char:
        ch = _char(data[0])
        return f"{v} ({hexed}{', ' + repr(ch) if ch else ''})"
    return f"{v} ({hexed})"


# ------------------------------------------------------------------------ where locals are
def frame_base(sp: int, fn: Function, line: int, offsets: dict[str, int]) -> int:
    """Where ``fn``'s frame starts (the C stack pointer on entry), stopped at the start of ``line``:
    the stack pointer plus the room taken by the locals declared before that line. (Offsets count
    down from the base, so the room taken is the deepest offset of those locals.)"""
    taken = 0
    for name, _t, decl, block_end in fn.locals:
        if decl < line <= block_end and name in offsets:
            taken = max(taken, -offsets[name])
    return sp + taken


def local_address(base: int, offset: int | None) -> int:
    return (base + (offset or 0)) & 0xFFFF


# ------------------------------------------------------------------------ a program's variables at a stop
@dataclass
class Variable:
    group: str                    # "param", "local" or "global"
    name: str
    ctype: CType | None           # None: not declared where the reader could find it
    address: int | None           # None: not on the stack at this point
    size: int
    note: str = ""                # why there's no value, if there isn't

    @property
    def type_name(self) -> str:
        return str(self.ctype) if self.ctype else "?"


class CProgram:
    """What the Debugger's Variables list needs from a C build: the types from its source files and
    the addresses from ld65's debug file (cc65dbg.c_globals and c_frames)."""

    def __init__(self, sources: dict[str, str], globals_: dict[str, tuple[int, int]],
                 frames: dict[str, dict[str, int | None]]):
        self.source = CSource()
        self.functions: list[Function] = []          # every file's (two files may each have a main())
        macros: dict[str, str] = {}
        for text in sources.values():
            macros.update(defines(text))
        for file, text in sources.items():
            src = parse_source(text, macros)
            for fn in src.functions.values():
                fn.file = file
                self.functions.append(fn)
            self.source.merge(src)
        self.globals, self.frames = globals_, frames

    def function_at(self, file: str, line: int) -> Function | None:
        best = None
        for fn in self.functions:
            if fn.file == file and fn.first_line <= line <= fn.last_line:
                if best is None or fn.first_line > best.first_line:
                    best = fn
        return best

    def _size(self, ctype: CType | None, fallback: int) -> int:
        size = ctype.size(self.source.structs) if ctype else None
        return size if size else fallback

    def variables(self, here: tuple[str, int] | None, sp: int) -> tuple[Function | None, list[Variable]]:
        """The current function's parameters and locals (stopped at the start of C line ``here``,
        with the C stack pointer ``sp``), then the globals."""
        out: list[Variable] = []
        fn = self.function_at(*here) if here else None
        if fn is not None:
            offsets = self.frames.get(fn.name, {})
            line = here[1]
            started = line > fn.first_line      # on its first line the arguments aren't in place yet
            base = frame_base(sp, fn, line, offsets)
            for name, ctype in fn.params:
                size = self._size(ctype, 2)
                if name not in offsets:
                    out.append(Variable("param", name, ctype, None, size, "no debug information"))
                elif not started:
                    out.append(Variable("param", name, ctype, None, size, "set up as the function starts"))
                else:
                    out.append(Variable("param", name, ctype, local_address(base, offsets[name]), size))
            for name, ctype, decl, end in fn.locals:
                size = self._size(ctype, 2)
                if name not in offsets:
                    out.append(Variable("local", name, ctype, None, size, "no debug information"))
                elif not decl < line <= end:
                    out.append(Variable("local", name, ctype, None, size,
                                        "not declared yet" if line <= decl else "out of scope"))
                else:
                    out.append(Variable("local", name, ctype, local_address(base, offsets[name]), size))
        for name in sorted(self.globals, key=str.lower):
            addr, gap = self.globals[name]
            ctype = self.source.globals.get(name)
            out.append(Variable("global", name, ctype, addr, self._size(ctype, gap)))
        return fn, out

    def show(self, var: Variable, data: bytes) -> str:
        """``var``'s value from its bytes (and for a pointer, what it points to)."""
        if var.ctype is None:
            return data.hex(" ")
        text = format_value(var.ctype, data, self.source.structs, self.source.enums)
        if var.ctype.pointer and not var.ctype.dims and len(data) >= 2:
            target = self.points_to(int.from_bytes(data[:2], "little"))
            if target:
                text += f" → {target}"
        return text

    def points_to(self, address: int) -> str | None:
        """What's at ``address``, by name: a global, an element of a global array (rocks[1]) or a
        member of one (rocks[1].y). None if it isn't in a global."""
        if address == 0:
            return None
        for name, (start, gap) in self.globals.items():
            ctype = self.source.globals.get(name)
            size = self._size(ctype, gap)
            if not start <= address < start + size:
                continue
            off = address - start
            if ctype is None or off == 0 and not ctype.dims:
                return name if off == 0 else f"{name}+{off}"
            if not ctype.dims:
                return name + self._member(ctype, off)
            elem = ctype.element()
            esize = elem.size(self.source.structs) or 1
            return f"{name}[{off // esize}]" + self._member(elem, off % esize)
        return None

    def _member(self, ctype: CType, off: int) -> str:
        """``.member`` for an offset into a struct (empty at its start, or for anything else)."""
        if off == 0 or ctype.base != "struct" or ctype.pointer:
            return f"+{off}" if off else ""
        at = 0
        for mname, mtype in self.source.structs.get(ctype.tag, []):
            size = mtype.size(self.source.structs) or 0
            if at <= off < at + size:
                return f".{mname}" + (f"+{off - at}" if off > at else "")
            at += size
        return f"+{off}"


# ------------------------------------------------------------------------ setting values
def _petscii(ch: str) -> int:
    """A character as cc65 puts it in a C string: lower-case letters $41-$5A, capitals $C1-$DA."""
    if "a" <= ch <= "z":
        return ord(ch) - 32
    if "A" <= ch <= "Z":
        return ord(ch) + 0x80
    if ch == "\n":
        return 0x0D
    if 0x20 <= ord(ch) <= 0x3F or ch in "[]":
        return ord(ch)
    raise ValueError(f"{ch!r} has no PETSCII code")


def _parse_int(text: str) -> int:
    t = text.strip()
    neg = t.startswith("-")
    if neg:
        t = t[1:].strip()
    if len(t) == 3 and t[0] == t[2] == "'":
        v = _petscii(t[1])
    elif t.startswith("$"):
        v = int(t[1:], 16)
    elif t.lower().startswith("0x"):
        v = int(t[2:], 16)
    elif t.startswith("%"):
        v = int(t[1:], 2)
    elif t.isdigit():
        v = int(t)
    else:
        raise ValueError(f"{text.strip()!r} isn't a number (decimal, $hex, 0x hex, %binary or 'c')")
    return -v if neg else v


def _int_bytes(v: int, size: int, unsigned: bool) -> bytes:
    lo, hi = (0, (1 << 8 * size) - 1) if unsigned else (-(1 << (8 * size - 1)), (1 << 8 * size) - 1)
    if not lo <= v <= hi:
        raise ValueError(f"{v} doesn't fit in {size} byte{'s' if size > 1 else ''}")
    return (v & ((1 << 8 * size) - 1)).to_bytes(size, "little")


def _hex_bytes(text: str, size: int) -> bytes:
    parts = text.replace(",", " ").split()
    try:
        data = bytes(int(p.lstrip("$"), 16) for p in parts)
    except ValueError:
        raise ValueError("Give the bytes in hex, e.g. 05 00 FE FF") from None
    if len(data) != size:
        raise ValueError(f"It's {size} byte{'s' if size != 1 else ''}: give {size} (you gave {len(data)})")
    return data


def encode_value(ctype: CType | None, text: str, size: int, structs: dict | None = None,
                 enums: dict | None = None) -> bytes:
    """``text`` (as edit_text writes it) as the variable's bytes, or ValueError saying what's wrong."""
    structs, enums = structs or {}, enums or {}
    text = text.strip()
    if not text:
        raise ValueError("Type a value")
    if ctype is None or ctype.base in ("struct", "union") and not ctype.pointer and not ctype.dims:
        return _hex_bytes(text, size)
    if ctype.dims:
        elem = ctype.element()
        esize = elem.size(structs)
        if elem.base == "char" and not elem.pointer and not elem.dims and text.startswith('"'):
            if not elem.plain_char:
                raise ValueError("Give the bytes in hex, e.g. 05 00 FE FF (it's an array of numbers)")
            if len(text) < 2 or not text.endswith('"'):
                raise ValueError('A string goes in quotes: "hello"')
            data = bytes(_petscii(c) for c in text[1:-1])
            if len(data) >= size:
                raise ValueError(f"That's {len(data)} characters: there's room for {size - 1} and the 0 at the end")
            return data + bytes(size - len(data))           # the rest zeroed
        if not esize or elem.dims or elem.base in ("struct", "union"):
            return _hex_bytes(text, size)
        if elem.base == "char" and not elem.plain_char and "," not in text:    # bytes, as they're shown
            data = _hex_bytes(text, len(text.replace(",", " ").split()))
            if len(data) > size:
                raise ValueError(f"There's room for {size} bytes")
            return data + bytes(size - len(data))
        items = [x for x in text.strip("{}").split(",") if x.strip()]
        if len(items) * esize > size:
            raise ValueError(f"There's room for {size // esize} item{'s' if size // esize != 1 else ''}")
        data = b"".join(encode_value(elem, x, esize, structs, enums) for x in items)
        return data + bytes(size - len(data))
    if ctype.pointer:
        if text.upper() == "NULL":
            return b"\0\0"
        return _int_bytes(_parse_int(text), 2, True)
    csize = ctype.size(structs) or size
    names = {n: v for v, n in enums.get(ctype.tag, {}).items()} if ctype.base == "enum" else {}
    v = names[text] if text in names else _parse_int(text)
    unsigned = ctype.unsigned or ctype.plain_char
    if v < 0 and unsigned:
        raise ValueError(f"{str(ctype)} can't be negative")
    return _int_bytes(v, csize, unsigned)


def edit_text(ctype: CType | None, data: bytes, structs: dict | None = None, enums: dict | None = None) -> str:
    """The value as it's typed when setting it (encode_value reads it back)."""
    structs, enums = structs or {}, enums or {}
    if ctype is None or ctype.base in ("struct", "union") and not ctype.pointer and not ctype.dims:
        return data.hex(" ").upper()
    if ctype.dims:
        elem = ctype.element()
        esize = elem.size(structs)
        if elem.base == "char" and not elem.pointer and not elem.dims:
            if not elem.plain_char:
                return data.hex(" ").upper()
            text = data.split(b"\0", 1)[0]
            if all(_char(b) for b in text):
                return '"' + "".join(_char(b) for b in text) + '"'
        if not esize or elem.dims or elem.base in ("struct", "union"):
            return data.hex(" ").upper()
        return ", ".join(edit_text(elem, data[i:i + esize], structs, enums) for i in range(0, len(data), esize))
    if ctype.pointer:
        v = int.from_bytes(data[:2], "little")
        return "NULL" if v == 0 else f"${v:04X}"
    size = ctype.size(structs) or len(data)
    v = int.from_bytes(data[:size], "little", signed=not ctype.unsigned and not ctype.plain_char)
    if ctype.base == "enum" and v in enums.get(ctype.tag, {}):
        return enums[ctype.tag][v]
    return str(v)
