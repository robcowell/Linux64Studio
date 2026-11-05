"""C projects, built with cc65 (cl65), as Kick Assembler projects are built with KickAss.jar.

A C project builds one program for the C64 from its build list: .c files (compiled by cc65) and .s
files (assembled by ca65), linked by ld65 with the C64 runtime. Each file is compiled on its own
into <output>/obj (so no .o files are left beside the sources, and errors come file by file), then
the objects are linked with debug information: a VICE label file (-Ln) and ld65's debug file
(--dbgfile, read by cc65dbg) for C source-level debugging.

The project's extra source folders (lib_dirs, e.g. ../lib) are include paths for both #include
and .include, and its assembler options (assembler_args, e.g. -O or -DDEBUG) go to every compile.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..asm.errors import Diagnostic, SourceLoc
from .model import Project

CL65 = "cl65"
TARGET = "c64"
C_EXTS = (".c",)
ASM_EXTS = (".s", ".asm")          # ca65 sources
DEFAULT_ARGS = ["-O"]              # what a new C project compiles with

# cc65/ca65: "main.c(12): Error: ';' expected" (and "main.c:12: Warning: ..." from some versions)
_MSG = re.compile(r"^(?P<file>[^\s(:][^(]*?)(?:\((?P<line>\d+)\)|:(?P<line2>\d+)):\s*"
                  r"(?P<sev>Error|Warning|Fatal|Note):\s*(?P<msg>.*)$")
_UNRESOLVED = re.compile(r"^Unresolved external [`'](?P<sym>[^`']+)' referenced in:")
_REFERENCED = re.compile(r"^\s+(?P<file>\S+?)\((?P<line>\d+)\)\s*$")
_AT_LINE = re.compile(r"^(?P<file>[^\s(][^(]*)\((?P<line>\d+)\):\s*(?P<msg>.*)$")
_LD65 = re.compile(r"^(?:ld65|ca65|cc65|cl65): (?P<sev>Error|Warning|Fatal): (?P<msg>.*)$")


def is_source(path: Path) -> bool:
    return path.suffix.lower() in C_EXTS + ASM_EXTS


def output_paths(project: Project) -> dict[str, Path]:
    """Where a build puts the program, its object files, label, debug and map files."""
    out = (project.directory / project.output_dir).resolve()
    prg = out / (project.executable or project.name + ".prg")
    return {"dir": out, "obj": out / "obj", "prg": prg, "labels": prg.with_suffix(".lbl"),
            "dbg": prg.with_suffix(".dbg"), "map": prg.with_suffix(".map")}


def _includes(project: Project) -> list[str]:
    args = []
    for d in project.lib_dirs:
        p = str((project.directory / d).resolve())
        args += ["-I", p, "--asm-include-dir", p]
    return args


def object_for(project: Project, src: Path) -> Path:
    """The object file for a source: under <output>/obj, keeping the source's folder (so two
    files with the same name in different folders don't collide)."""
    obj_dir = output_paths(project)["obj"]
    src = src.resolve()
    try:
        rel = src.relative_to(project.directory.resolve())
    except ValueError:                       # a shared library folder outside the project
        rel = Path("_ext") / src.parent.name / src.name
    else:
        rel = Path(*[p if p != ".." else "_up" for p in rel.parts])
    return obj_dir / rel.with_suffix(".o")


def compile_command(project: Project, src: Path, obj: Path, cl65: str = CL65) -> list[str]:
    return [cl65, "-t", TARGET, "-g", *_includes(project), *project.assembler_args, "-c", "-o", str(obj), str(src)]


def link_command(project: Project, objs: list[Path], cl65: str = CL65, config: Path | None = None) -> list[str]:
    out = output_paths(project)
    cfg = ["-C", str(config)] if config else []
    return [cl65, "-t", TARGET, *cfg, "-g", "-o", str(out["prg"]), "-Ln", str(out["labels"]), "-m", str(out["map"]),
            "-Wl", f"--dbgfile,{out['dbg']}", *[str(o) for o in objs]]


def linker_config(project: Project) -> Path | None:
    """The config to link with: the project's own .cfg, else one made from its fixed areas (written
    into the output folder), else None (cc65's standard C64 layout). Raises ldcfg.LayoutError."""
    from . import ldcfg
    if project.linker_config:
        return (project.directory / project.linker_config).resolve()
    if not project.c_areas:
        return None
    text = ldcfg.generate([ldcfg.Area.from_dict(a) for a in project.c_areas],
                          title=f"{project.executable or project.name}: made from the project's fixed areas")
    out = output_paths(project)["prg"].with_suffix(".cfg")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists() or out.read_text() != text:
        out.write_text(text)
    return out


def parse_output(text: str, cwd: Path, compiled: dict[str, Path] | None = None) -> list[Diagnostic]:
    """cc65, ca65 and ld65 messages as diagnostics, with file and line where they give them.
    ``compiled`` maps the assembly file cc65 made from a C file (main.s) to that C file, for the
    linker, which names the generated assembly when a function or variable is missing."""
    compiled = {k.lower(): v for k, v in (compiled or {}).items()}
    out: list[Diagnostic] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].rstrip()
        i += 1
        m = _MSG.match(s)
        if m:
            f = Path(m.group("file"))
            f = f if f.is_absolute() else (cwd / f).resolve()
            sev = "warning" if m.group("sev") in ("Warning", "Note") else "error"
            out.append(Diagnostic(sev, m.group("msg").strip(), SourceLoc(str(f), int(m.group("line") or m.group("line2")))))
            continue
        m = _UNRESOLVED.match(s)
        if m:
            sym = m.group("sym")
            name = sym[1:] if sym.startswith("_") else sym      # C names have a leading _ in the object code
            where, loc = [], None
            while i < len(lines) and _REFERENCED.match(lines[i]):
                r = _REFERENCED.match(lines[i])
                i += 1
                src = compiled.get(Path(r.group("file")).name.lower())
                if src is not None:
                    where.append(src.name)
                else:
                    f = Path(r.group("file"))
                    f = f if f.is_absolute() else (cwd / f).resolve()
                    where.append(f.name)
                    if loc is None and f.exists():
                        loc = SourceLoc(str(f), int(r.group("line")))
            used = f" (used in {', '.join(dict.fromkeys(where))})" if where else ""
            if sym.startswith("__") and sym.endswith("__"):
                out.append(Diagnostic("error", f"{sym} comes from the linker config, which doesn't define it{used}: "
                                               "cc65's runtime needs the memory areas and segments of the standard "
                                               "C64 config (with define = yes)", loc))
                continue
            out.append(Diagnostic("error", f"'{name}' isn't defined anywhere{used}: is a file missing from the "
                                           "build list, or a name misspelt?", loc))
            continue
        m = _LD65.match(s)
        if m:
            msg = m.group("msg").strip()
            if "unresolved external" in msg and any("isn't defined anywhere" in d.message for d in out):
                continue                     # already said, name by name
            loc = None
            at = _AT_LINE.match(msg)         # the linker config's own errors: game.cfg(21): ...
            if at:
                f = Path(at.group("file"))
                f = f if f.is_absolute() else (cwd / f).resolve()
                if f.exists():
                    loc, msg = SourceLoc(str(f), int(at.group("line"))), f"{f.name}: {at.group('msg')}"
            out.append(Diagnostic("warning" if m.group("sev") == "Warning" else "error", msg, loc))
    return out


def stack_pointer(labels: Path) -> int:
    """Where cc65's C stack pointer is (two bytes in zero page), from the VICE label file: ``sp``
    (``c_sp`` in newer cc65). $02 if the file doesn't say."""
    try:
        text = Path(labels).read_text(errors="replace")
    except OSError:
        return 0x02
    m = re.search(r"^al\s+([0-9A-Fa-f]+)\s+\.(?:c_)?sp\s*$", text, re.M)
    return int(m.group(1), 16) if m else 0x02
