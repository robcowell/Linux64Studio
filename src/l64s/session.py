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


# -------------------------------------------------------------------- open folders, per project
# The sidebar's open folders, remembered for each project (whichever way it's opened again), in
# ~/.config/linux64studio/folders.json as {project path: [folder paths]}. The most recent projects
# are kept, as many as the recent-projects list.
MAX_PROJECTS = 10


def _folders_file() -> Path:
    return config_dir() / "folders.json"


def _load_all_folders() -> dict[str, list[str]]:
    try:
        data = json.loads(_folders_file().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): [str(f) for f in v] for k, v in data.items() if isinstance(v, list)}


def load_open_folders(project: str) -> list[str] | None:
    """The folders open when ``project`` was last shown, or None if it never was."""
    return _load_all_folders().get(project)


def save_open_folders(project: str, folders: list[str]) -> None:
    data = _load_all_folders()
    data.pop(project, None)
    data = {project: sorted(folders), **data}                # most recent first
    data = dict(list(data.items())[:MAX_PROJECTS])
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        _folders_file().write_text(json.dumps(data, indent=2) + "\n")
    except OSError:
        pass
