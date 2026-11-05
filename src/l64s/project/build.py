"""Build a project with its toolchain, producing a .prg plus labels/listing/source map."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..asm.assembler import Assembler, Options, Result
from ..asm.errors import Diagnostic, SourceLoc
from ..asm.output import source_map, write_outputs
from ..basic.pbasic import PBasicOptions
from .model import TOOLCHAIN_CBM, TOOLCHAIN_CC65, TOOLCHAIN_KICKASS, Project


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
    cart: Path | None = None          # the .crt written, if the project makes one
    kick_debug: object = None         # Kick Assembler builds: the parsed debug dump (kickdbg.DebugInfo)
    basic_preview: list[tuple[Path, str]] = field(default_factory=list)   # each pBASIC file, as numbered BASIC
    c_lines: list = field(default_factory=list)   # C builds: emu.clines.LineSpan per line of C, for stepping
    asm_lines: list = field(default_factory=list)  # ... and per line of the project's .s files
    c_globals: dict = field(default_factory=dict)  # ... its C variables' addresses (cc65dbg.c_globals)
    c_frames: dict = field(default_factory=dict)   # ... and its functions' stack frames (cc65dbg.c_frames)
    c_sp: int = 0x02                               # ... and where cc65's C stack pointer is (zero page)

    def run_target(self, project) -> Path | None:
        """What to run: the cartridge, the disk image or the program, as the project says."""
        if self.cart and project.run_cart:
            return self.cart
        if self.disk and project.run_from_disk:
            return self.disk
        return self.prg


def write_cartridge(project: Project, prg: Path) -> tuple[Path | None, list[Diagnostic], str]:
    """Write the project's .crt: bank 0 from the built program, further banks from data files."""
    from ..cart.crt import CartError, cartridge_from_files
    dest = project.cart_path()
    if dest is None:
        return None, [], ""
    extras = [(project.directory / b).resolve() for b in project.cart_banks]
    for p in extras:
        if not p.is_file():
            return None, [Diagnostic("error", f"Cartridge: bank file {p.name} not found", None)], ""
    try:
        cart = cartridge_from_files(project.cart_type, prg, project.cart_name or project.name, extras)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cart.save(dest)
    except (CartError, OSError) as e:
        return None, [Diagnostic("error", f"Cartridge: {e}", None)], ""
    banks = len({c.bank for c in cart.chips})
    return dest, [], (f"Wrote {dest} ({cart.type_name}, {cart.mode}, {banks} bank(s), "
                      f"{cart.size // 1024}K)")

def write_disk_image(project: Project, prg: Path) -> tuple[Path | None, list[Diagnostic], str]:
    """Write the project's .d64: the built program first, then any extra files."""
    from ..disk.image import DiskError, build_disk, file_type_for, format_for
    dest = project.disk_image_path()
    if dest is None:
        return None, [], ""
    try:
        format_for(dest)
    except DiskError as e:
        return None, [Diagnostic("error", f"Disk image: {e}", None)], ""
    program = prg
    if project.disk_program:
        program = (project.directory / expand_presets(project.disk_program, project, prg)).resolve()
        if not program.is_file():
            return None, [Diagnostic("error", f"Disk image: the program file {project.disk_program} wasn't made "
                                              f"(a post-build command should write it)", None)], ""
    name = project.disk_file_name or prg.stem
    files = [(name, program.read_bytes(), "prg")]
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
    """Add the disk image and cartridge to a successful whole-project build."""
    if not res.ok or only_file or not res.prg:
        return res
    for wanted, writer, attr in ((project.disk_image, write_disk_image, "disk"),
                                 (project.cart_type, write_cartridge, "cart")):
        if not wanted:
            continue
        out, diags, msg = writer(project, res.prg)
        res.diagnostics += diags
        if diags:
            res.ok = False
            res.log += "\n" + "\n".join(str(d) for d in diags)
            return res
        setattr(res, attr, out)
        res.log += "\n" + msg
    return res


def expand_presets(text: str, project: Project, prg: Path | None) -> str:
    """CBM prg Studio's build event presets, in a command."""
    out_prg = prg or project.output_path()
    values = {"[ProjectDir]": str(project.directory), "[ProjectName]": project.name,
              "[prg]": str(out_prg), "[prgName]": out_prg.name, "[prgDir]": str(out_prg.parent),
              "[OutputDir]": str((project.directory / project.output_dir).resolve())}
    for k, v in values.items():
        text = text.replace(k, v)
    return text


def build_events(project: Project, commands: list[str], prg: Path | None, which: str) -> tuple[bool, list[str]]:
    """Run build event commands; returns (all succeeded, log lines).

    One command a line, run in the project folder. As in CBM prg Studio, a line starting with ;
    is switched off and `echo text` writes to the build output. Commands run directly, not through
    a shell, so use sh -c "..." for pipes and redirection.
    """
    import shlex
    log: list[str] = []
    for raw in commands:
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        line = expand_presets(line, project, prg)
        if line.lower() == "echo" or line.lower().startswith("echo "):
            log.append(line[5:])
            continue
        try:
            argv = shlex.split(line)
        except ValueError as e:
            log.append(f"{which} command can't be read ({e}): {line}")
            return False, log
        log.append(f"> {line}")
        try:
            proc = subprocess.run(argv, cwd=project.directory, capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            log.append(f"{which} command not found: {argv[0]}")
            return False, log
        except (OSError, subprocess.TimeoutExpired) as e:
            log.append(f"{which} command failed: {e}")
            return False, log
        out = (proc.stdout + proc.stderr).rstrip()
        if out:
            log.append(out)
        if proc.returncode != 0:
            log.append(f"{which} command failed (exit code {proc.returncode}): {line}")
            return False, log
    return True, log


def build_project(project: Project, overrides: dict[str, str] | None = None,
                  only_file: Path | None = None, kickass_jar: str = "", java: str = "java",
                  goattracker_dir: str = "", pbasic: PBasicOptions | None = None) -> BuildResult:
    """Build the whole project, or (CBM prg Studio's "Build Program") just `only_file`.
    `pbasic` numbers the .pbas files (CBM prg Studio's pBASIC settings)."""
    music_log, music_diags = prepare_music(project, goattracker_dir)
    if any(d.severity == "error" for d in music_diags):
        return BuildResult(False, None, None, music_diags, "\n".join([music_log] + [str(d) for d in music_diags]))
    pre_log: list[str] = []
    if project.pre_build:
        ok, pre_log = build_events(project, project.pre_build, None, "Pre-build")
        if not ok:
            d = Diagnostic("error", pre_log[-1], None)
            return BuildResult(False, None, None, [d], "\n".join(pre_log))
    if project.toolchain == TOOLCHAIN_KICKASS:
        jar = str((project.directory / project.kickass_jar).resolve()) if project.kickass_jar else \
            (kickass_jar or default_kickass_jar())
        res = _build_kickass(project, jar, java, only_file)
    elif project.toolchain == TOOLCHAIN_CC65:
        res = _build_cc65(project, only_file)
    else:
        res = _build_cbm(project, overrides, only_file, pbasic)
    if pre_log:
        res.log = "\n".join(pre_log) + "\n" + res.log
    if project.post_build and not only_file and (res.ok or project.post_build_always):
        ok, post_log = build_events(project, project.post_build, res.prg, "Post-build")
        res.log += "\n" + "\n".join(post_log)
        if not ok:
            res.ok = False
            res.diagnostics.append(Diagnostic("error", post_log[-1], None))
    res = _with_disk(project, res, only_file)
    if music_log:
        res.log = music_log + "\n" + res.log
    return res


def prepare_music(project: Project, goattracker_dir: str = "") -> tuple[str, list[Diagnostic]]:
    """Pack each linked GoatTracker song and convert each sound effect, ready for the code to include."""
    from ..sid.goattracker import MusicError, PackOptions, convert_sfx, pack_song
    lines: list[str] = []
    for link in project.music:
        src = (project.directory / link.get("source", "")).resolve()
        out = (project.directory / link.get("output", "")).resolve()
        where = SourceLoc(str(src), 1)
        try:
            if src.suffix.lower() == ".ins":
                data = convert_sfx(src, out, link.get("label", ""), goattracker_dir,
                                   kickass=project.toolchain == TOOLCHAIN_KICKASS)
                lines.append(f"Sound effect {src.name} -> {out.name} ({len(data)} bytes)")
            else:
                r = pack_song(src, out, PackOptions.from_dict(link), goattracker_dir)
                lines.append(f"Packed {src.name} -> {out.name} (${r.start:04X}-${r.end - 1:04X}, {r.size} bytes)")
        except MusicError as e:
            return "\n".join(lines), [Diagnostic("error", f"Music: {e}", where)]
    return "\n".join(lines), []


BASIC_EXTS = {".bas", ".pbas"}


def _read_source(path: Path, overrides: dict[str, str] | None) -> str:
    for k, v in (overrides or {}).items():
        if Path(k).resolve() == path.resolve():
            return v
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _tokenize_basic(files: list[Path], overrides, pbasic: PBasicOptions | None = None,
                    previews: list | None = None) -> tuple[object | None, list[Diagnostic]]:
    """Tokenize the project's BASIC files, numbering pBASIC ones first (each numbered program is
    added to `previews`). Returns (TokenizeResult or None, diagnostics)."""
    from ..basic.pbasic import to_basic
    from ..basic.tokenizer import BasicErrors, tokenize_files
    diags: list[Diagnostic] = []
    sources = []
    numbered = {}                    # pBASIC file -> PBasicResult, to give errors their pBASIC lines

    def loc(err, fname=None):
        f = err.file or fname
        line = numbered[f].source_line(err.line) if f in numbered else err.line
        return SourceLoc(f, line) if f and line else None
    for p in files:
        try:
            text = _read_source(p, overrides)
        except OSError as e:
            diags.append(Diagnostic("error", f"Can't read {p}: {e.strerror}", None))
            continue
        if p.suffix.lower() == ".pbas":
            try:
                conv = to_basic(text, pbasic)
            except BasicErrors as e:
                diags += [Diagnostic("error", err.message, SourceLoc(str(p), err.line) if err.line else
                                     SourceLoc(str(p), 1)) for err in e.errors]
                continue
            text = conv.text
            if previews is not None:
                previews.append((p, text))
            sources.append((str(p), text))
            numbered[str(p)] = conv
        else:
            sources.append((str(p), text))
    if diags:
        return None, diags
    try:
        res = tokenize_files(sources)
    except BasicErrors as e:
        return None, [Diagnostic("error", err.message, loc(err)) for err in e.errors]
    return res, [Diagnostic("warning", w.message, loc(w)) for w in res.warnings]


def _build_cbm(project: Project, overrides, only_file, pbasic: PBasicOptions | None = None) -> BuildResult:
    files = [only_file] if only_file else project.build_paths()
    if not files:
        d = Diagnostic("error", "The project has no files in its build list", None)
        return BuildResult(False, None, None, [d], str(d))
    basic_files = [Path(f) for f in files if Path(f).suffix.lower() in BASIC_EXTS]
    asm_files = [f for f in files if Path(f).suffix.lower() not in BASIC_EXTS]
    opts = Options(padding_byte=project.padding_byte)
    result = Assembler(opts).assemble_files(asm_files, overrides)
    # EXPORT: labels the BASIC can use by name (10 sys start), so the BASIC is read after the code
    basic_overrides = overrides
    if basic_files and result.exports:
        basic_overrides = dict(overrides or {})
        for p in basic_files:
            try:
                basic_overrides[str(p)] = substitute_exports(_read_source(p, overrides), result.exports)
            except OSError:
                pass
    previews: list[tuple[Path, str]] = []
    basic, basic_diags = _tokenize_basic(basic_files, basic_overrides, pbasic, previews) \
        if basic_files else (None, [])
    result.diagnostics[:0] = basic_diags
    if basic_files and basic is None:
        result.ok = False
    elif basic is not None:
        _merge_basic(result, basic)
    if only_file:
        out = Path(only_file).with_suffix(".prg")
    else:
        out = project.output_path()
    gen = result.generate_to
    no_output = bool(gen) and gen[0].upper() == "NULL"
    p00_name = None
    if gen and not no_output:
        # GENERATETO: the program file, always in the project folder (CBM prg Studio)
        out = (project.directory / Path(gen[0]).name).resolve()
        if out.suffix.lower() == ".p00":
            p00_name = gen[1] if len(gen) > 1 else out.stem
    labels = out.with_suffix(".vs")
    log = [f"Building {'file ' + Path(only_file).name if only_file else 'project ' + project.name}"]
    log += [str(d) for d in result.diagnostics]
    log += [f"debug: {m}" for m in result.messages]
    if result.ok and no_output:
        log.append("GENERATETO NULL: no program file written")
        return BuildResult(True, None, None, result.diagnostics, "\n".join(log),
                           srcmap=source_map(result), asm_result=result, basic_preview=previews)
    if result.ok:
        dbg = out.with_suffix(".dbg") if project.debug_dump else None
        write_outputs(result, out, labels=labels, lst=out.with_suffix(".lst"), dbg=dbg)
        if dbg:
            log.append(f"Wrote the debug dump {dbg.name}")
        if p00_name is not None:
            out.write_bytes(p00(result.prg(), p00_name))
            log.append(f"Wrote {out.name} as a PC64 .p00 file named {p00_name.upper()[:16]}")
        if gen and len(gen) >= 3 and Path(gen[1]).suffix.lower() in (".d64", ".d71", ".d81"):
            log.append(_generate_to_disk(project, out, result.prg(), gen))
        if result.start is not None:
            log.append(f"Wrote {out} (${result.start:04X}-${result.end - 1:04X}, "
                       f"{result.end - result.start} bytes)")
        else:
            log.append(f"Wrote {out} (empty)")
    else:
        log.append(f"Build failed: {len(result.errors)} error(s)")
    return BuildResult(result.ok, out if result.ok else None, labels if result.ok else None,
                       result.diagnostics, "\n".join(log),
                       srcmap=source_map(result) if result.ok else {}, asm_result=result, basic_preview=previews)


def substitute_exports(text: str, exports: dict[str, int]) -> str:
    """Put exported labels' values into BASIC source (10 sys start -> 10 sys 32768): whole words,
    in any case, outside strings and REMs."""
    if not exports:
        return text
    names = {k.lower(): v for k, v in exports.items()}
    word = re.compile(r"(?<![A-Za-z0-9_$])([A-Za-z_][A-Za-z0-9_]*\$?)(?![A-Za-z0-9_])")
    out_lines = []
    for line in text.split("\n"):
        parts = re.split(r'("[^"]*"?)', line)
        rem = False
        for i, part in enumerate(parts):
            if rem or part.startswith('"'):
                continue
            m = re.search(r"\brem\b", part, re.I)
            head, tail = (part[:m.start()], part[m.start():]) if m else (part, "")
            head = word.sub(lambda w: str(names[w.group(1).lower()]) if w.group(1).lower() in names
                            else w.group(1), head)
            parts[i] = head + tail
            rem = bool(m)
        out_lines.append("".join(parts))
    return "\n".join(out_lines)


def p00(prg: bytes, name: str) -> bytes:
    """A PC64 .p00 file: "C64File", the 16-character name, then the program with its load address."""
    raw = name.upper().encode("ascii", "replace")[:16].ljust(17, b"\0")
    return b"C64File\0" + raw + b"\0" + prg


def _generate_to_disk(project: Project, prg_path: Path, prg: bytes, gen: list[str]) -> str:
    """GENERATETO prg, disk, name[, append]: the program on a disk image, new or added to."""
    from ..disk.image import DiskError, DiskImage, build_disk
    disk = (project.directory / Path(gen[1]).name).resolve()
    name = prg_path.stem[:16]
    try:
        if len(gen) > 3 and gen[3].lower() == "append" and disk.exists():
            d = DiskImage.load(disk)
            d.add_file(name, prg, "prg", replace=True)
            d.save(disk)
            return f"Added {name} to {disk.name}"
        build_disk(disk, gen[2][:16], "00", [(name, prg, "prg")])
        return f"Wrote {disk.name} with {name}"
    except DiskError as e:
        return f"GENERATETO couldn't write {disk.name}: {e}"


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


def default_kickass_jar() -> str:
    """The Kick Assembler tools/install-kickassembler.sh installs, if it's there."""
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    jar = base / "linux64studio" / "KickAssembler" / "KickAss.jar"
    return str(jar) if jar.is_file() else ""


_KA_WRITING = re.compile(r"^Writing (prg|Vice symbol|Symbol) file: (.+)$", re.I)


def _written(output: str, folders: list[Path]) -> dict[str, Path]:
    """The files Kick Assembler says it wrote ("Writing prg file: ..."), by kind. A relative path
    is tried against each folder in turn."""
    out: dict[str, Path] = {}
    for line in output.splitlines():
        m = _KA_WRITING.match(line.strip())
        if not m:
            continue
        p = Path(m.group(2).strip())
        candidates = [p] if p.is_absolute() else [f / p for f in folders]
        hit = next((c for c in candidates if c.exists()), None)
        if hit:
            out[m.group(1).lower()] = hit.resolve()
    return out


_KA_VERSIONS: dict[tuple[str, float], tuple[int, int] | None] = {}


def kickass_version(java: str, jar: str) -> tuple[int, int] | None:
    """Kick Assembler's version, from the banner it prints (remembered until the jar changes)."""
    try:
        key = (str(Path(jar).resolve()), Path(jar).stat().st_mtime)
    except OSError:
        return None
    if key not in _KA_VERSIONS:
        try:
            proc = subprocess.run([java, "-jar", jar], capture_output=True, text=True, timeout=60)
            m = re.search(r"Kick Assembler v(\d+)\.(\d+)", proc.stdout + proc.stderr)
            _KA_VERSIONS[key] = (int(m.group(1)), int(m.group(2))) if m else None
        except (OSError, subprocess.TimeoutExpired):
            _KA_VERSIONS[key] = None
    return _KA_VERSIONS[key]


def _build_kickass(project: Project, jar: str, java: str, only_file) -> BuildResult:
    if not jar or not Path(jar).is_file():
        d = Diagnostic("error", "Kick Assembler isn't set up: choose KickAss.jar in Preferences, or run "
                                   "tools/install-kickassembler.sh", None)
        return BuildResult(False, None, None, [d], str(d))
    if not shutil.which(java):
        d = Diagnostic("error", f"Java runtime '{java}' not found", None)
        return BuildResult(False, None, None, [d], str(d))
    main = Path(only_file) if only_file else project.directory / project.main_file
    out_dir = (project.directory / project.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # -odir relative to the main file's folder: Kick Assembler 4 adds even an absolute path to that
    # folder (writing to <source dir>/home/...); Kick Assembler 5 takes either
    odir = os.path.relpath(out_dir, main.resolve().parent)
    cmd = [java, "-jar", jar, str(main), "-odir", odir, "-vicesymbols", "-symbolfile"]
    version = kickass_version(java, jar)
    if version is None or version >= (5, 0):
        cmd.append("-debugdump")            # source lines for the debugger (Kick Assembler 5 and later)
    for lib in project.lib_dirs:
        cmd += ["-libdir", str((project.directory / lib).resolve())]
    prg_name = main.with_suffix(".prg").name
    if project.executable and not only_file and Path(project.executable).name != prg_name:
        prg_name = Path(project.executable).name
        # Kick Assembler 5 reads -o from the folder it runs in (the project's), not from -odir
        cmd += ["-o", os.path.relpath(out_dir / prg_name, project.directory)]
    cmd += list(project.assembler_args)
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
    # Where the files went, as Kick Assembler reports them (its versions put them in different
    # places), else where they should be
    written = _written(proc.stdout + proc.stderr, [project.directory, out_dir, main.resolve().parent])
    prg = written.get("prg") or out_dir / prg_name
    ok = proc.returncode == 0 and prg.exists()
    if not ok and not diags:
        diags.append(Diagnostic("error", f"Kick Assembler failed (exit code {proc.returncode})", None))
    labels = written.get("vice symbol") or next(
        (p for p in (prg.with_suffix(".vs"), out_dir / main.with_suffix(".vs").name) if p.exists()), None)
    res = BuildResult(ok, prg if ok else None, labels if labels and labels.exists() else None, diags, log)
    # -debugdump writes <program>.dbg next to the program (Kick Assembler 5)
    dbg = next((p for p in (prg.with_suffix(".dbg"), out_dir / main.with_suffix(".dbg").name) if p.exists()),
               prg.with_suffix(".dbg"))
    if ok and dbg.exists():
        # -debugdump: which line made which bytes, for source-level debugging and the memory tools
        from ..kickdbg import DebugDumpError, parse, source_map
        try:
            res.kick_debug = parse(dbg, project.directory)
            res.srcmap = source_map(res.kick_debug)
        except DebugDumpError as e:
            res.log += f"\n{e}"
    return res


def _build_cc65(project: Project, only_file) -> BuildResult:
    """A C project: each file on the build list compiled (cc65/ca65) into <output>/obj, then linked
    (ld65) with a VICE label file and a debug file. ``only_file``: just compile that one, to check it."""
    from . import cc65
    cl65 = shutil.which(cc65.CL65)
    if not cl65:
        d = Diagnostic("error", "cc65 isn't installed: sudo apt install cc65", None)
        return BuildResult(False, None, None, [d], str(d))
    sources = [Path(only_file)] if only_file else project.build_paths()
    if not sources:
        d = Diagnostic("error", "The build list is empty: right-click a .c file in the file tree and choose "
                                "Add to Build", None)
        return BuildResult(False, None, None, [d], str(d))
    out = cc65.output_paths(project)
    log: list[str] = []
    diags: list[Diagnostic] = []
    objs: list[Path] = []
    compiled: dict[str, Path] = {}
    failed = False

    def run(cmd: list[str]) -> tuple[int, str]:
        try:
            proc = subprocess.run(cmd, cwd=project.directory, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            return -1, f"Couldn't run cl65: {e}"
        return proc.returncode, proc.stdout + proc.stderr

    for src in sources:
        src = src.resolve()
        if not src.is_file():
            diags.append(Diagnostic("error", f"{src.name} is on the build list but doesn't exist", None))
            failed = True
            continue
        if not cc65.is_source(src):
            diags.append(Diagnostic("warning", f"{src.name} isn't C (.c) or assembler (.s), so it isn't built",
                                    SourceLoc(str(src), 1)))
            continue
        obj = cc65.object_for(project, src)
        obj.parent.mkdir(parents=True, exist_ok=True)
        cmd = cc65.compile_command(project, src, obj, cl65)
        code, text = run(cmd)
        log.append(" ".join(cmd))
        if text.strip():
            log.append(text.rstrip())
        diags += cc65.parse_output(text, project.directory)
        if code != 0:
            failed = True
            if not any(d.severity == "error" for d in diags):
                diags.append(Diagnostic("error", f"Compiling {src.name} failed (exit code {code})", None))
        if src.suffix.lower() in cc65.C_EXTS:
            compiled[src.with_suffix(".s").name] = src
        objs.append(obj)
    if failed or only_file:
        if only_file and not failed:
            log.append(f"{Path(only_file).name} compiles (Build Project links the program)")
        return BuildResult(not failed, None, None, diags, "\n".join(log))
    cmd = cc65.link_command(project, objs, cl65)
    code, text = run(cmd)
    log.append(" ".join(cmd))
    if text.strip():
        log.append(text.rstrip())
    diags += cc65.parse_output(text, project.directory, compiled)
    prg = out["prg"]
    ok = code == 0 and prg.is_file()
    if not ok and not any(d.severity == "error" for d in diags):
        diags.append(Diagnostic("error", f"Linking failed (exit code {code})", None))
    res = BuildResult(ok, prg if ok else None, out["labels"] if ok and out["labels"].is_file() else None,
                      diags, "\n".join(log))
    if ok and out["dbg"].is_file():
        from ..cc65dbg import DebugFileError, c_frames, c_globals, c_line_spans, parse, source_map
        try:
            info = parse(out["dbg"])
            res.srcmap = source_map(info, project.directory)
            res.c_lines = c_line_spans(info, project.directory)
            res.asm_lines = c_line_spans(info, project.directory, line_type=0)
            res.c_globals, res.c_frames = c_globals(info), c_frames(info)
            res.c_sp = cc65.stack_pointer(out["labels"])
        except DebugFileError as e:
            res.log += f"\n{e}"
        res.log += f"\nWrote {prg} ({prg.stat().st_size} bytes)"
    return res
