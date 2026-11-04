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


def build_project(project: Project, overrides: dict[str, str] | None = None,
                  only_file: Path | None = None, kickass_jar: str = "", java: str = "java") -> BuildResult:
    """Build the whole project, or (CBM prg Studio's "Build Program") just `only_file`."""
    if project.toolchain == TOOLCHAIN_KICKASS:
        return _build_kickass(project, kickass_jar, java, only_file)
    return _build_cbm(project, overrides, only_file)


def _build_cbm(project: Project, overrides, only_file) -> BuildResult:
    files = [only_file] if only_file else project.build_paths()
    if not files:
        d = Diagnostic("error", "The project has no files in its build list", None)
        return BuildResult(False, None, None, [d], str(d))
    opts = Options(padding_byte=project.padding_byte)
    result = Assembler(opts).assemble_files(files, overrides)
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
