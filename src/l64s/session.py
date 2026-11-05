"""Continue where you left off: what was open when the IDE was closed (the project, the files in
tabs, the tab in front and each source file's cursor), saved to ~/.config/linux64studio/session.json
and opened again at the next start (Preferences → "Continue where I left off").

Only files are kept: tool pages (calculators, the disassembler, ...) aren't. Files that have since
gone are left out when the session is opened again, and so is a project that's gone.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .settings import config_dir


@dataclass
class OpenFile:
    path: str
    line: int = 1          # 1-based; 0 = not a text file
    column: int = 0        # 0-based, in characters


@dataclass
class Session:
    project: str = ""                                   # "" = no project was open
    files: list[OpenFile] = field(default_factory=list)
    selected: int = -1                                  # index into files of the tab in front

    # ---------------------------------------------------------------- storing it
    @staticmethod
    def file() -> Path:
        return config_dir() / "session.json"

    @classmethod
    def load(cls) -> "Session":
        try:
            data = json.loads(cls.file().read_text())
            files = [OpenFile(str(f["path"]), int(f.get("line", 1)), int(f.get("column", 0)))
                     for f in data.get("files", []) if isinstance(f, dict) and f.get("path")]
            return cls(str(data.get("project") or ""), files, int(data.get("selected", -1)))
        except (OSError, ValueError, TypeError, KeyError):
            return cls()

    def save(self) -> None:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        self.file().write_text(json.dumps(asdict(self), indent=2) + "\n")

    @property
    def empty(self) -> bool:
        return not self.project and not self.files

    # ---------------------------------------------------------------- opening it again
    def restorable(self) -> tuple["Session", list[str]]:
        """This session without what no longer exists, and the names of what was left out."""
        missing = []
        project = self.project
        if project and not Path(project).exists():
            missing.append(Path(project).name)
            project = ""
        files, selected = [], -1
        for i, f in enumerate(self.files):
            if Path(f.path).is_file():
                if i == self.selected:
                    selected = len(files)
                files.append(f)
            else:
                missing.append(Path(f.path).name)
        if selected < 0 and files:
            selected = len(files) - 1
        return Session(project, files, selected), missing


# -------------------------------------------------------------------- per project
# What each project had open (whichever way it's opened again): the sidebar's open folders and
# the files in tabs, in ~/.config/linux64studio/projects.json as {project path: ProjectState}.
# The most recent projects are kept, as many as the recent-projects list.
MAX_PROJECTS = 10


@dataclass
class ProjectState:
    folders: list[str] | None = None                    # None = never recorded (show the default)
    files: list[OpenFile] = field(default_factory=list)
    selected: int = -1

    def restorable(self) -> tuple[list[OpenFile], int, list[str]]:
        """The files that still exist, the one in front among them, and the names of those gone."""
        s, missing = Session("", self.files, self.selected).restorable()
        return s.files, s.selected, missing


def _projects_file() -> Path:
    return config_dir() / "projects.json"


def _load_all_states() -> dict[str, dict]:
    try:
        data = json.loads(_projects_file().read_text())
    except (OSError, ValueError):
        data = {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def load_project_state(project: str) -> ProjectState | None:
    """What ``project`` had open when it was last left, or None if it never was."""
    d = _load_all_states().get(project)
    if d is None:
        return None
    try:
        folders = d.get("folders")
        files = [OpenFile(str(f["path"]), int(f.get("line", 1)), int(f.get("column", 0)))
                 for f in d.get("files", []) if isinstance(f, dict) and f.get("path")]
        return ProjectState([str(f) for f in folders] if isinstance(folders, list) else None,
                            files, int(d.get("selected", -1)))
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def save_project_state(project: str, state: ProjectState) -> None:
    data = _load_all_states()
    data.pop(project, None)
    st = asdict(state)
    if st["folders"] is not None:
        st["folders"] = sorted(st["folders"])
    data = dict(list({project: st, **data}.items())[:MAX_PROJECTS])     # most recent first
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        _projects_file().write_text(json.dumps(data, indent=2) + "\n")
    except OSError:
        pass
