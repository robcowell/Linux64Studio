"""User tools (CBM prg Studio's Tools → User menu): programs of your own to run from the IDE, an
editor, a cruncher, another emulator, with arguments that name the project's files.

Arguments take CBM prg Studio's presets: [prg] [prgName] [prgDir] (the program built),
[ProjectDir] [ProjectName] [OutputDir] [OutputDirFull], [CurrentFile] [CurrentDir] (the file being
edited), [Date], [Version], [Target] [TargetFull] and [System]. The arguments are split into words
(with quotes, as a shell would) before the presets are put in, so a path with spaces in it stays
one argument.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PRESETS = ["[prg]", "[prgName]", "[prgDir]", "[ProjectDir]", "[ProjectName]", "[OutputDir]", "[OutputDirFull]",
           "[CurrentFile]", "[CurrentDir]", "[Date]", "[Version]", "[Target]", "[TargetFull]", "[System]"]


class ToolError(ValueError):
    pass


@dataclass
class UserTool:
    name: str
    command: str                  # the program (a name on the PATH, or a path)
    arguments: str = ""
    folder: str = ""              # where to run it; presets allowed; "" = the project folder (or the file's)
    capture: bool = False         # run it and put what it prints in the build output, else just start it

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UserTool":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Context:
    """What the presets stand for when a tool is run."""
    values: dict[str, str] = field(default_factory=dict)

    @classmethod
    def make(cls, project=None, current_file: Path | None = None, prg: Path | None = None) -> "Context":
        from . import __version__ as version
        v = {"[Date]": time.strftime("%Y-%m-%d"), "[Version]": version, "[Target]": "C64",
             "[TargetFull]": "Commodore 64", "[System]": str(Path(shutil.which("sh") or "/bin/sh").parent)}
        if project is not None:
            out = prg or project.output_path()
            v.update({"[ProjectDir]": str(project.directory), "[ProjectName]": project.name,
                      "[prg]": str(out), "[prgName]": out.name, "[prgDir]": str(out.parent),
                      "[OutputDir]": project.output_dir or ".",
                      "[OutputDirFull]": str((project.directory / project.output_dir).resolve())})
        if current_file is not None:
            v.update({"[CurrentFile]": str(current_file), "[CurrentDir]": str(current_file.parent)})
        return cls(v)

    def expand(self, text: str) -> str:
        for k in PRESETS:
            if k in text:
                if k not in self.values:
                    raise ToolError(f"{k} has no value here ({'no project open' if 'Project' in k or 'prg' in k or 'Output' in k else 'no file being edited'})")
                text = text.replace(k, self.values[k])
        return text


def argv(tool: UserTool, ctx: Context) -> list[str]:
    """The command line to run."""
    if not tool.command.strip():
        raise ToolError(f"{tool.name} has no program to run")
    try:
        words = shlex.split(tool.arguments)
    except ValueError as e:
        raise ToolError(f"{tool.name}'s arguments can't be read: {e}") from None
    return [ctx.expand(tool.command.strip())] + [ctx.expand(w) for w in words]


def folder(tool: UserTool, ctx: Context) -> Path:
    if tool.folder.strip():
        return Path(ctx.expand(tool.folder.strip())).expanduser()
    for k in ("[ProjectDir]", "[CurrentDir]"):
        if k in ctx.values:
            return Path(ctx.values[k])
    return Path.home()


def run(tool: UserTool, ctx: Context, timeout: int = 300) -> tuple[bool, str]:
    """Run a tool. With `capture`, waits and returns (succeeded, what it printed); otherwise starts
    it on its own and returns at once."""
    cmd, cwd = argv(tool, ctx), folder(tool, ctx)
    if shutil.which(cmd[0]) is None and not Path(cmd[0]).expanduser().exists():
        raise ToolError(f"{tool.name}: can't find the program {cmd[0]}")
    if not cwd.is_dir():
        raise ToolError(f"{tool.name}: the folder {cwd} doesn't exist")
    if not tool.capture:
        try:
            subprocess.Popen(cmd, cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            raise ToolError(f"{tool.name}: {e.strerror}") from None
        return True, ""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{tool.name} was still running after {timeout} seconds, so it was stopped"
    except OSError as e:
        raise ToolError(f"{tool.name}: {e.strerror}") from None
    out = (p.stdout + p.stderr).rstrip()
    if p.returncode != 0:
        out += f"\n{tool.name} finished with exit code {p.returncode}"
    return p.returncode == 0, out
