"""Build a project with its toolchain, producing a .prg plus labels/listing/source map."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..asm.assembler import Assembler, Options, Result
from ..asm.errors import Diagnostic, SourceLoc
from ..asm.output import source_map, write_outputs
from .model import TOOLCHAIN_CBM, TOOLCHAIN_KICKASS, Project


@dataclass
class BuildResult:
    ok: bool
    prg: Path | None
    labels: Path | None
    diagnostics: list[Diagnostic]
    log: str
    srcmap: dict[int, tuple[str, int]] = field(default_factory=dict)
    asm_result: Result | None = None
    disk: Path | None = None          # the .d64 written, if the project makes one


def write_disk_image(project: Project, prg: Path) -> tuple[Path | None, list[Diagnostic], str]:
    """Write the project's .d64: the built program first, then any extra files."""
    from ..disk.d64 import DiskError, build_disk, file_type_for
    dest = project.disk_image_path()
    if dest is None:
        return None, [], ""
    name = project.disk_file_name or prg.stem
    files = [(name, prg.read_bytes(), "prg")]
    for extra in project.disk_extra_files:
        rel = extra.get("file", "")
        src = (project.directory / rel).resolve()
        try:
            data = src.read_bytes()
        except OSError as e:
            return None, [Diagnostic("error", f"Disk image: can't read {rel}: {e.strerror}", None)], ""
        files.append((extra.get("name") or src.stem, data, extra.get("type") or file_type_for(src)))
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        disk = build_disk(dest, project.disk_name or project.name, project.disk_id or "00", files)
    except DiskError as e:
        return None, [Diagnostic("error", f"Disk image: {e}", None)], ""
    return dest, [], f"Wrote {dest} ({len(files)} file(s), {disk.blocks_free} blocks free)"


def _with_disk(project: Project, res: BuildResult, only_file) -> BuildResult:
    """Add the disk image to a successful whole-project build."""
    if not res.ok or only_file or not project.disk_image or not res.prg:
        return res
    disk, diags, msg = write_disk_image(project, res.prg)
    res.diagnostics += diags
    if diags:
        res.ok = False
        res.log += "\n" + "\n".join(str(d) for d in diags)
    else:
        res.disk = disk
        res.log += "\n" + msg
    return res


def build_project(project: Project, overrides: dict[str, str] | None = None,
                  only_file: Path | None = None, kickass_jar: str = "", java: str = "java") -> BuildResult:
    """Build the whole project, or (CBM prg Studio's "Build Program") just `only_file`."""
    if project.toolchain == TOOLCHAIN_KICKASS:
        res = _build_kickass(project, kickass_jar, java, only_file)
    else:
        res = _build_cbm(project, overrides, only_file)
    return _with_disk(project, res, only_file)


BASIC_EXTS = {".bas"}


def _read_source(path: Path, overrides: dict[str, str] | None) -> str:
    for k, v in (overrides or {}).items():
        if Path(k).resolve() == path.resolve():
            return v
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _tokenize_basic(files: list[Path], overrides) -> tuple[object | None, list[Diagnostic]]:
    """Tokenize the project's BASIC files. Returns (TokenizeResult or None, diagnostics)."""
    from ..basic.tokenizer import BasicErrors, tokenize_files
    diags: list[Diagnostic] = []
    sources = []
    for p in files:
        try:
            sources.append((str(p), _read_source(p, overrides)))
        except OSError as e:
            diags.append(Diagnostic("error", f"Can't read {p}: {e.strerror}", None))
    if diags:
        return None, diags

    def loc(err):
        return SourceLoc(err.file, err.line) if err.file and err.line else None
    try:
        res = tokenize_files(sources)
    except BasicErrors as e:
        return None, [Diagnostic("error", err.message, loc(err)) for err in e.errors]
    return res, [Diagnostic("warning", w.message, loc(w)) for w in res.warnings]


def _build_cbm(project: Project, overrides, only_file) -> BuildResult:
    files = [only_file] if only_file else project.build_paths()
    if not files:
        d = Diagnostic("error", "The project has no files in its build list", None)
        return BuildResult(False, None, None, [d], str(d))
    basic_files = [Path(f) for f in files if Path(f).suffix.lower() in BASIC_EXTS]
    asm_files = [f for f in files if Path(f).suffix.lower() not in BASIC_EXTS]
    basic, basic_diags = _tokenize_basic(basic_files, overrides) if basic_files else (None, [])
    opts = Options(padding_byte=project.padding_byte)
    result = Assembler(opts).assemble_files(asm_files, overrides)
    result.diagnostics[:0] = basic_diags
    if basic_files and basic is None:
        result.ok = False
    elif basic is not None:
        _merge_basic(result, basic)
    if only_file:
        out = Path(only_file).with_suffix(".prg")
    else:
        out = project.output_path()
    labels = out.with_suffix(".vs")
    log = [f"Building {'file ' + Path(only_file).name if only_file else 'project ' + project.name}"]
    log += [str(d) for d in result.diagnostics]
    if result.ok:
        write_outputs(result, out, labels=labels, lst=out.with_suffix(".lst"))
        if result.start is not None:
            log.append(f"Wrote {out} (${result.start:04X}-${result.end - 1:04X}, "
                       f"{result.end - result.start} bytes)")
        else:
            log.append(f"Wrote {out} (empty)")
    else:
        log.append(f"Build failed: {len(result.errors)} error(s)")
    return BuildResult(result.ok, out if result.ok else None, labels if result.ok else None,
                       result.diagnostics, "\n".join(log),
                       srcmap=source_map(result) if result.ok else {}, asm_result=result)


def _merge_basic(result: Result, basic) -> None:
    """Put the tokenized BASIC program at its load address, under any assembled code."""
    lo, hi = basic.start, basic.end
    for a in range(lo, hi):
        if result.used[a]:
            result.diagnostics.append(Diagnostic(
                "error", f"Assembly code at ${a:04X} overlaps the BASIC program (${lo:04X}-${hi - 1:04X}). "
                         f"Start the code after the BASIC program, e.g. *=${(hi + 0xFF) & 0xFF00:04X}", None))
            result.ok = False
            return
    result.memory[lo:hi] = basic.program
    result.used[lo:hi] = b"\x01" * (hi - lo)
    result.start = lo if result.start is None else min(result.start, lo)
    result.end = hi if result.end is None else max(result.end, hi)
    # Debugger/listing: map each BASIC line's bytes to its source line.
    from ..asm.assembler import ListingEntry
    addr = lo
    for ln in basic.lines:
        size = 5 + len(ln.data)
        result.listing.insert(0, ListingEntry(addr, basic.program[addr - lo:addr - lo + size],
                                              SourceLoc(ln.file or "", ln.source_line), None,
                                              f"{ln.number} (BASIC)"))
        addr += size


# Kick Assembler error lines look like:  "Error: Unknown symbol 'foo'" ... "at line 12, column 5 in gameMain.asm"
_KA_AT = re.compile(r"at line (\d+), column (\d+) in (.+)$")


def _build_kickass(project: Project, jar: str, java: str, only_file) -> BuildResult:
    if not jar or not Path(jar).is_file():
        d = Diagnostic("error", "Kick Assembler isn't set up: choose KickAss.jar in Preferences", None)
        return BuildResult(False, None, None, [d], str(d))
    if not shutil.which(java):
        d = Diagnostic("error", f"Java runtime '{java}' not found", None)
        return BuildResult(False, None, None, [d], str(d))
    main = Path(only_file) if only_file else project.directory / project.main_file
    out_dir = (project.directory / project.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [java, "-jar", jar, str(main), "-odir", str(out_dir), "-vicesymbols", "-symbolfile"]
    for lib in project.lib_dirs:
        cmd += ["-libdir", str((project.directory / lib).resolve())]
    try:
        proc = subprocess.run(cmd, cwd=project.directory, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        d = Diagnostic("error", f"Couldn't run Kick Assembler: {e}", None)
        return BuildResult(False, None, None, [d], str(d))
    log = " ".join(cmd) + "\n" + proc.stdout + proc.stderr
    diags: list[Diagnostic] = []
    pending = None
    for line in (proc.stdout + proc.stderr).splitlines():
        s = line.strip()
        if s.lower().startswith("error:"):
            pending = s[6:].strip()
            diags.append(Diagnostic("error", pending, None))
        m = _KA_AT.search(s)
        if m and diags and diags[-1].loc is None:
            f = Path(m.group(3))
            if not f.is_absolute():
                f = (project.directory / f).resolve()
            diags[-1] = Diagnostic("error", diags[-1].message, SourceLoc(str(f), int(m.group(1))))
    prg = out_dir / main.with_suffix(".prg").name
    ok = proc.returncode == 0 and prg.exists()
    if not ok and not diags:
        diags.append(Diagnostic("error", f"Kick Assembler failed (exit code {proc.returncode})", None))
    labels = prg.with_suffix(".vs")
    return BuildResult(ok, prg if ok else None, labels if labels.exists() else None, diags, log)
