"""Linux64Studio projects.

A project is a folder of sources plus a settings file. Three formats can be opened:

* `.l64proj`  native JSON project
* `.cbmprj`   CBM prg Studio project (Vol 1 of the book), opened in place
* `.code-workspace`  VS Code + Kick Assembler workspace (Vol 2 of the book)

A project's toolchain is the built-in assembler, Kick Assembler, or cc65 for C (project/cc65.py).

Opening a .cbmprj or .code-workspace never rewrites it. Linux64Studio settings for it are
saved alongside as `<name>.l64proj`, which takes precedence the next time it's opened.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .cbmprj import load_cbmprj

# Kick Assembler `.import binary "x"`, `#import "x"`, and CBM prg Studio `incbin "x"`.
_IMPORT_RE = re.compile(r'(?:\.import\s+(?:binary|source|c64|text)\s+|#import\s+|incbin\s+)"([^"]+)"', re.I)

TOOLCHAIN_CBM = "cbm"          # built-in CBM prg Studio-compatible assembler
TOOLCHAIN_KICKASS = "kickass"  # external Kick Assembler (java -jar KickAss.jar)
TOOLCHAIN_CC65 = "cc65"        # C with cc65 (cl65): see project/cc65.py

SOURCE_EXTS = {".asm", ".s", ".a", ".inc", ".bas", ".pbas", ".txt", ".tkn", ".c", ".h", ".cfg"}
MUSIC_EXTS = {".sng", ".ins", ".sid"}
GFX_EXTS = {".spt", ".cst", ".sdd", ".spr", ".chr", ".bin", ".l64spr", ".l64chr", ".l64scr", ".spd", ".ctm", ".prg",
            ".d64", ".d71", ".d81", ".crt"}


@dataclass
class Project:
    path: Path                         # the file the project was opened from
    name: str
    toolchain: str = TOOLCHAIN_CBM
    build_list: list[str] = field(default_factory=list)  # cbm: files assembled together, in order
    main_file: str = ""               # kickass: the file passed to the assembler
    executable: str = ""              # output .prg name
    output_dir: str = "."             # relative to the project directory
    lib_dirs: list[str] = field(default_factory=list)   # kickass -libdir
    padding_byte: int = 0
    vice_args: list[str] = field(default_factory=list)
    imported_from: str = ""           # original .cbmprj / .code-workspace, if any
    # Linked exports: graphics file (relative path) -> {export kind: .bin path ("" = off)}
    exports: dict[str, dict[str, str]] = field(default_factory=dict)
    # Disk image output: "" = off, else the .d64 to write (relative to the project directory)
    disk_image: str = ""
    disk_name: str = ""              # default: project name
    disk_id: str = "00"
    disk_file_name: str = ""         # name of the program on the disk; default: executable's name
    # More files for the disk: [{"file": relative path, "name": name on disk, "type": prg/seq/usr}]
    disk_extra_files: list[dict] = field(default_factory=list)
    run_from_disk: bool = False      # autostart the .d64 instead of the .prg
    # Cartridge output: "" = off, else a type from l64s.cart.crt.CART_TYPES (normal8, ocean, ...)
    cart_type: str = ""
    cart_file: str = ""              # default: <executable>.crt
    cart_name: str = ""              # name in the .crt header; default: project name
    cart_banks: list[str] = field(default_factory=list)  # data files for banks 1, 2, ... (banked carts)
    run_cart: bool = False           # run and debug with the cartridge plugged in
    # Music made with GoatTracker/SidMonkey, packed (songs) or converted (sound effects) before
    # every build: [{"source": "music/tune.sng", "output": "music.bin", "address": 4096, ...}]
    music: list[dict] = field(default_factory=list)
    # Kick Assembler: the project's own KickAss.jar (relative path; "" = the one in Preferences), and
    # more command-line options, one per item (e.g. ["-define", "DEBUG"])
    kickass_jar: str = ""
    assembler_args: list[str] = field(default_factory=list)
    # Build events, as in CBM prg Studio: commands run in the project folder before and after a build,
    # one a line, with presets such as [prg] and [ProjectDir] (see build.build_events)
    pre_build: list[str] = field(default_factory=list)
    post_build: list[str] = field(default_factory=list)
    post_build_always: bool = False  # run the post-build commands even when the build fails
    # Built-in assembler: also write a debug dump (.dbg) in Kick Assembler's format, for debuggers
    # such as C64 Debugger, RetroDebugger and VS64
    debug_dump: bool = False
    # The file to put on the disk image as the program, instead of the built .prg (e.g. a crunched
    # copy a post-build command makes); "" = the built program
    disk_program: str = ""
    # CharPad projects' view settings, by .ctm (relative path): {"room": [w, h] in tiles, "materials": [names]}
    charpad_views: dict[str, dict] = field(default_factory=dict)
    # Sprite scratch pads, by sprite file (relative path): gfx.scratchpad.ScratchPad.to_dict()
    sprite_pads: dict[str, dict] = field(default_factory=dict)
    # Several programs in one project (see "Programs" below): each {"name", and PROGRAM_FIELDS}. Empty:
    # the project is one program. The fields above always hold the current program's values.
    programs: list[dict] = field(default_factory=list)
    current_program: str = ""
    # C projects: the linker config (relative .cfg; "" = cc65's standard C64 layout, or one made from
    # c_areas), and fixed areas for things at set addresses: [{"name": "MUSIC", "start": 4096,
    # "size": 2048}] (see project.ldcfg)
    linker_config: str = ""
    c_areas: list[dict] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        return self.path.parent

    def build_paths(self) -> list[Path]:
        return [self.directory / n for n in self.build_list]

    def output_path(self) -> Path:
        exe = self.executable or (self.name + ".prg")
        return (self.directory / self.output_dir / exe).resolve()

    def cart_path(self) -> Path | None:
        if not self.cart_type:
            return None
        name = self.cart_file or Path(self.executable or self.name + ".prg").with_suffix(".crt").name
        return (self.directory / name).resolve()

    def disk_image_path(self) -> Path | None:
        return (self.directory / self.disk_image).resolve() if self.disk_image else None

    def settings_path(self) -> Path:
        return self.path if self.path.suffix == ".l64proj" else self.path.with_suffix(".l64proj")

    def identity(self) -> str:
        """One name for the project however it was opened: an imported .cbmprj or .code-workspace
        and the .l64proj its settings go to are the same project (for remembering its tabs)."""
        return str(self.settings_path().resolve())

    def old_identities(self) -> list[str]:
        """Names it may have been remembered under before ``identity`` (the imported file's path)."""
        if not self.imported_from:
            return []
        return [str((self.directory / self.imported_from).resolve())]

    def referenced_dirs(self) -> list[Path]:
        """Folders that the project's sources import files from (e.g. Vol 2's ../../Content)."""
        dirs: list[Path] = []
        roots = [self.directory] + [(self.directory / d).resolve() for d in self.lib_dirs]
        for root in roots:
            if not root.is_dir():
                continue
            for src in root.rglob("*.asm"):
                try:
                    text = src.read_text(errors="replace")
                except OSError:
                    continue
                for m in _IMPORT_RE.finditer(text):
                    target = (src.parent / m.group(1).replace("\\", "/")).resolve()
                    d = target.parent
                    if d.is_dir() and d not in dirs and not any(d == r or r in d.parents for r in roots):
                        dirs.append(d)
        return dirs

    def all_files(self) -> list[Path]:
        """Every source and graphics file in the project folder, library dirs and imported-data dirs."""
        roots = [self.directory] + [(self.directory / d).resolve() for d in self.lib_dirs]
        roots += self.referenced_dirs()
        seen, out = set(), []
        for root in roots:
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if (p.is_file() and p.suffix.lower() in SOURCE_EXTS | GFX_EXTS | MUSIC_EXTS and p not in seen
                        and not p.name.startswith(".")):
                    if any(part.startswith(".") or part in ("Output", "build") for part in p.relative_to(root).parts[:-1]):
                        continue
                    seen.add(p)
                    out.append(p)
        return out

    def all_folders(self) -> list[Path]:
        """Every folder in the project folder (empty ones too), skipping hidden, Output and build."""
        out = []
        for p in sorted(self.directory.rglob("*")):
            if p.is_dir() and not any(part.startswith(".") or part in ("Output", "build")
                                      for part in p.relative_to(self.directory).parts):
                out.append(p)
        return out

    def save(self) -> Path:
        store_program(self)
        data = asdict(self)
        data.pop("path")
        dest = self.settings_path()
        dest.write_text(json.dumps(data, indent=2) + "\n")
        return dest


def load_project(path: str | Path) -> Project:
    path = Path(path).resolve()
    sfx = path.suffix.lower()
    if sfx != ".l64proj" and path.with_suffix(".l64proj").exists():
        return load_project(path.with_suffix(".l64proj"))
    if sfx == ".l64proj":
        data = json.loads(path.read_text())
        data.pop("path", None)
        known = {f for f in Project.__dataclass_fields__}
        return Project(path=path, **{k: v for k, v in data.items() if k in known})
    if sfx == ".cbmprj":
        c = load_cbmprj(path)
        return Project(path=path, name=path.stem, toolchain=TOOLCHAIN_CBM, build_list=c.build_list,
                       executable=c.executable, padding_byte=c.padding_byte, imported_from=path.name,
                       cart_type=c.cart_type, cart_name=c.cart_name)
    if sfx == ".code-workspace":
        return _load_vscode_workspace(path)
    if sfx == ".c":                          # a C file on its own: a C project of one file
        from .cc65 import DEFAULT_ARGS
        return Project(path=path, name=path.stem, toolchain=TOOLCHAIN_CC65, build_list=[path.name],
                       main_file=path.name, executable=path.stem + ".prg", output_dir="build",
                       assembler_args=list(DEFAULT_ARGS))
    if sfx in (".asm", ".s", ".bas"):
        return Project(path=path, name=path.stem, build_list=[path.name], executable=path.stem + ".prg")
    raise ValueError(f"Don't know how to open {path.name}")


def _load_vscode_workspace(path: Path) -> Project:
    # VS Code allows comments and trailing commas in workspace files.
    text = re.sub(r"^\s*//.*$", "", path.read_text(), flags=re.M)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    data = json.loads(text)
    settings = data.get("settings", {})
    folders = [f.get("path", ".") for f in data.get("folders", [])]
    lib_dirs = [f.replace("//", "/") for f in folders if f not in (".", "./")]
    main = settings.get("kickassembler.startup", "")
    out_dir = settings.get("kickassembler.outputDirectory", "./Output").replace("//", "/")
    return Project(
        path=path, name=path.stem, toolchain=TOOLCHAIN_KICKASS, main_file=main,
        executable=Path(main).with_suffix(".prg").name if main else path.stem + ".prg",
        output_dir=out_dir, lib_dirs=lib_dirs, imported_from=path.name,
    )


def new_project(directory: Path, name: str, toolchain: str = TOOLCHAIN_CBM, basic: bool = False,
                cartridge: bool = False) -> Project:
    """Create a new project with a starter program that builds and runs."""
    directory.mkdir(parents=True, exist_ok=True)
    if cartridge:
        main_name, starter = "cartMain.asm", STARTER_CART
        toolchain = TOOLCHAIN_CBM
    elif basic:
        main_name, starter = "main.bas", STARTER_BASIC
        toolchain = TOOLCHAIN_CBM
    elif toolchain == TOOLCHAIN_CC65:
        return _new_c_project(directory, name)
    else:
        main_name = "gameMain.asm"
        starter = STARTER_CBM if toolchain == TOOLCHAIN_CBM else STARTER_KICKASS
    main = directory / main_name
    if not main.exists():
        main.write_text(starter)
    proj = Project(path=directory / f"{name}.l64proj", name=name, toolchain=toolchain,
                   build_list=[main_name], main_file=main_name, executable=f"{name}.prg")
    if cartridge:
        proj.cart_type, proj.cart_name, proj.run_cart = "normal8", name, True
    proj.save()
    return proj


def _new_c_project(directory: Path, name: str) -> Project:
    """A C project. In a folder that already has C files, none is written and the build list starts
    empty (or with main.c, if there is one): add the program's files to it from the file tree."""
    from .cc65 import DEFAULT_ARGS
    existing = sorted(directory.glob("*.c"))
    if not existing:
        (directory / "main.c").write_text(STARTER_C.replace("{name}", name))
        build = ["main.c"]
    else:
        build = ["main.c"] if (directory / "main.c").exists() else []
    proj = Project(path=directory / f"{name}.l64proj", name=name, toolchain=TOOLCHAIN_CC65,
                   build_list=build, main_file=build[0] if build else "", executable=f"{name}.prg",
                   output_dir="build", assembler_args=list(DEFAULT_ARGS))
    proj.save()
    return proj


STARTER_C = """\
/* {name}: a C program for the C64, built with cc65.
   Lower-case letters in strings show as capitals on the C64's start-up character set. */
#include <conio.h>

#define BORDER (*(unsigned char *)0xD020)

int main(void)
{
    unsigned int i;

    clrscr();
    cputs("hello from c!\\r\\n");
    cputs("press a key to stop.");
    while (!kbhit()) {
        ++BORDER;
        for (i = 0; i < 2000; ++i) {
        }
    }
    cgetc();
    return 0;
}
"""

STARTER_CBM = """\
;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Initialize

EXTCOL  = $D020
BGCOL0  = $D021

        lda #0
        sta EXTCOL
        sta BGCOL0

gMLoop
        inc EXTCOL
        jmp gMLoop
"""

STARTER_CART = """\
;===============================================================================
; An 8K cartridge. The C64 finds the "CBM80" signature at $8004 when it's
; switched on and jumps to the address at $8000 instead of starting BASIC.

*=$8000
        word cartCold           ; cold start (power on / reset)
        word cartWarm           ; warm start (RUN/STOP + RESTORE)
        byte $C3, $C2, $CD, $38, $30    ; "CBM80"

EXTCOL  = $D020
BGCOL0  = $D021

cartCold
        sei
        ldx #$FF
        txs
        cld
        jsr $FDA3               ; IOINIT: set up the CIAs
        jsr $FD50               ; RAMTAS: clear and test RAM
        jsr $FD15               ; RESTOR: KERNAL vectors
        jsr $FF5B               ; CINT: screen editor and VIC-II
        cli

        ldx #0                  ; text gives screen codes, so write them
cMsg    lda cartText,x          ; straight into screen memory
        beq cartWarm
        sta $0400,x
        inx
        bne cMsg

cartWarm
        inc EXTCOL
        jmp cartWarm

cartText
        text 'hello from a cartridge!'
        byte 0
"""

STARTER_BASIC = """\
10 rem *** hello from linux64studio ***
20 print "{clear}{white}hello, world!"
30 for i=0 to 15:poke 53280,i:for d=1 to 100:next d,i
40 goto 30
"""

STARTER_KICKASS = """\
*= $0801 "Basic Loader"
    BasicUpstart(main)

*= $0810 "Code"
main:
    lda #0
    sta $d020
    sta $d021
loop:
    inc $d020
    jmp loop
"""


# ------------------------------------------------------------------------ programs
# A project can build several programs that share its source folders, output folder and disk image
# (a library's demos, say), each with its own build list, .prg name, options and (Kick) main file.
# One program is current: it's what Build, Run and Debug use, and its values are in the project's
# own fields, so everything that reads project.build_list works on it unchanged.
PROGRAM_FIELDS = ("build_list", "main_file", "executable", "assembler_args", "linker_config", "c_areas")


def _values(project: Project) -> dict:
    import copy
    return {f: copy.deepcopy(getattr(project, f)) for f in PROGRAM_FIELDS}


def program_names(project: Project) -> list[str]:
    return [p["name"] for p in project.programs] or [project.name]


def current_program(project: Project) -> str:
    return project.current_program if project.programs else project.name


def store_program(project: Project) -> None:
    """Keep the current program's values (in the project's fields) in its entry."""
    for prog in project.programs:
        if prog["name"] == project.current_program:
            prog.update(_values(project))


def select_program(project: Project, name: str) -> bool:
    """Make ``name`` the current program. False if there's no such program."""
    if name == current_program(project):
        return True
    prog = next((p for p in project.programs if p["name"] == name), None)
    if prog is None:
        return False
    store_program(project)
    for f in PROGRAM_FIELDS:
        v = prog.get(f, getattr(Project, f, None) if not isinstance(getattr(project, f), list) else [])
        setattr(project, f, __import__("copy").deepcopy(v) if isinstance(v, list) else (v or ""))
    project.current_program = name
    return True


def check_program_name(project: Project, name: str) -> str | None:
    name = name.strip()
    if not name:
        return "Enter a name"
    if name in program_names(project):
        return f"There's already a program called {name}"
    if any(c in name for c in '/\\:*?"<>|'):
        return "A name can't contain / \\ : * ? \" < > |"
    return None


def add_program(project: Project, name: str, copy_build_list: bool = True) -> None:
    """A new program, made current: the build list copied from the current one (a shared library's
    files, say), or empty. Its .prg is named after it."""
    why = check_program_name(project, name)
    if why:
        raise ValueError(why)
    if not project.programs:                     # the project's one program becomes the first of several
        project.programs = [{"name": project.name, **_values(project)}]
        project.current_program = project.name
    store_program(project)
    values = _values(project)
    new = {"name": name, **values, "executable": f"{name}.prg",
           "build_list": list(values["build_list"]) if copy_build_list else [],
           "main_file": values["main_file"] if copy_build_list else ""}
    project.programs.append(new)
    select_program(project, name)


def rename_program(project: Project, old: str, new: str) -> None:
    if old == new:
        return
    why = check_program_name(project, new)
    if why:
        raise ValueError(why)
    if not project.programs:
        project.programs = [{"name": project.name, **_values(project)}]
        project.current_program = project.name
    for prog in project.programs:
        if prog["name"] == old:
            prog["name"] = new
    if project.current_program == old:
        project.current_program = new


def remove_program(project: Project, name: str) -> None:
    """Remove a program (not the last one); if it was current, the first of the rest is."""
    if len(project.programs) <= 1:
        raise ValueError("A project needs at least one program")
    if name == project.current_program:
        rest = [p["name"] for p in project.programs if p["name"] != name]
        select_program(project, rest[0])
    project.programs = [p for p in project.programs if p["name"] != name]
    if len(project.programs) == 1:              # back to one program: the project's own fields
        select_program(project, project.programs[0]["name"])
        project.programs, project.current_program = [], ""


def program_project(project: Project, name: str) -> Project:
    """A copy of the project with ``name`` current, to build it (Build All Programs)."""
    from copy import deepcopy
    copy = deepcopy(project)
    select_program(copy, name)
    return copy


def each_program(project: Project) -> list[tuple[str, Project]]:
    store_program(project)
    return [(name, program_project(project, name)) for name in program_names(project)]
