"""User preferences, stored in ~/.config/linux64studio/settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "linux64studio"


@dataclass
class Settings:
    emulator: str = "x64sc"
    emulator_args: list[str] = field(default_factory=list)
    kickass_jar: str = ""
    goattracker_dir: str = ""     # folder with goattrk2, sidmonkey, gt2reloc, ins2snd2 ("" = find them)
    vsid: str = "vsid"            # VICE's SID player
    sid_midi_channels: list[int] = field(default_factory=lambda: [1, 2, 3])   # per SID voice, 1-16 (0 = off)
    sid_midi_device: str = ""     # the MIDI input the SID Designer last used
    digitiser_x_offset: int = 24  # the screen designer's digitiser
    digitiser_y_offset: int = 50
    digitiser_format: str = "{x}, {y}"
    java: str = "java"
    font: str = "Monospace 11"
    tab_width: int = 8
    insert_spaces: bool = True
    dark_mode: str = "system"     # system | light | dark
    save_before_build: bool = True
    auto_complete: bool = True
    basic_code_style: str = "standard"
    basic_auto_number: bool = True       # Return at the end of a BASIC line starts the next numbered line
    basic_number_step: int = 10
    basic_uncompress_lowercase: bool = True
    user_tools: list[dict] = field(default_factory=list)
    git_author: str = ""            # for commits ("" = git's own user.name)
    git_email: str = ""
    git_auto_add: bool = True       # add changed files before committing (CBM prg Studio's option)
    git_ignore: str = ""            # the ignore list a new repository starts with ("" = the default)   # usertools.UserTool.to_dict(), for Tools → User   # Uncompress writes keywords in lower case (else upper)   # control codes in BASIC listings: standard, bastext or tok64    # suggest names while typing (Ctrl+Space always does)
    pbasic_start: int = 10        # pBASIC: the first line number, the step and the label prefix
    pbasic_step: int = 10
    pbasic_prefix: str = "@"
    pbasic_preview: bool = False  # show each pBASIC file's numbered BASIC after building
    recent_projects: list[str] = field(default_factory=list)
    window_width: int = 1280
    window_height: int = 820

    @classmethod
    def load(cls) -> "Settings":
        p = config_dir() / "settings.json"
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").write_text(json.dumps(asdict(self), indent=2) + "\n")

    def pbasic_options(self):
        from .basic.pbasic import PBasicOptions
        return PBasicOptions(self.pbasic_start, self.pbasic_step, self.pbasic_prefix or "@")

    def add_recent(self, path: str) -> None:
        if path in self.recent_projects:
            self.recent_projects.remove(path)
        self.recent_projects.insert(0, path)
        del self.recent_projects[10:]
