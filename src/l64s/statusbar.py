"""The editor's status bar, as CBM prg Studio's: CAPS, INS/OVR, word wrap, the cursor's line and
column, BASIC auto line numbering, the target machine, Git, and which assembler and debugger build
and run the project. ``fields`` says what each part shows; ui/statusbar.py draws them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    text: str
    tooltip: str = ""
    lit: bool = True            # False: shown dimmed (CAPS when Caps Lock is off)
    toggle: bool = False        # clicking it switches the setting


@dataclass
class EditorState:
    caps_lock: bool = False
    overwrite: bool = False
    word_wrap: bool = False
    line: int = 1               # 1-based, as in the gutter
    column: int = 0             # 0-based characters from the start of the line, as CBM prg Studio counts
    basic: bool = False         # a BASIC file (not pBASIC): auto line numbering applies
    auto_line_numbers: bool = True
    kickass: bool = False       # the project builds with Kick Assembler
    cc65: bool = False          # the project is C, built with cc65
    git_branch: str | None = None   # None: the project isn't in a Git repository
    has_project: bool = False


def on_off(b: bool) -> str:
    return "On" if b else "Off"


def fields(s: EditorState) -> list[Field]:
    out = [
        Field("caps", "CAPS", "Caps Lock is " + ("on" if s.caps_lock else "off"), lit=s.caps_lock),
        Field("overwrite", "OVR" if s.overwrite else "INS",
              ("Overwrite" if s.overwrite else "Insert") + " mode (Insert key, or click, to switch)", toggle=True),
        Field("wrap", f"Word Wrap: {on_off(s.word_wrap)}", "Click to switch word wrap", toggle=True),
        Field("line", f"Line: {s.line}"),
        Field("column", f"Col: {s.column}"),
    ]
    if s.basic:
        out.append(Field("autonum", f"Auto Line Num: {on_off(s.auto_line_numbers)}",
                         "Return at the end of a numbered line starts the next one. Click to switch", toggle=True))
    out.append(Field("target", "Target: C64"))
    if s.has_project:
        out.append(Field("git", f"Git: {s.git_branch}" if s.git_branch else "Git Repo: No",
                         "The project's Git branch" if s.git_branch else "The project isn't in a Git repository"))
        if s.cc65:
            out.append(Field("assembler", "Using cc65", "cc65 (cl65) compiles and links this C project"))
        else:
            out.append(Field("assembler", "Using Kick Assembler" if s.kickass else "Using native assembler",
                             "Kick Assembler (KickAss.jar) builds this project" if s.kickass
                             else "Linux64Studio's CBM prg Studio-compatible assembler builds this project"))
    out.append(Field("debugger", "Using VICE debugger", "Debugging runs in VICE, over its binary monitor"))
    return out
