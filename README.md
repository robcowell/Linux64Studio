# Linux64Studio

A Commodore 64 development environment for Linux (GTK4/libadwaita), modelled on
CBM prg Studio. It was built so the *Retro Game Dev C64 Edition* books by Derek Morris
can be followed on Linux.

* **Assembler** compatible with CBM prg Studio's syntax (macros with `/1`, `@locals`,
  `Operator Calc`, `incbin`, …). All 12 Vol 1 chapter projects build byte-for-byte
  identical to the book's `.prg` files. See [docs/dialect.md](docs/dialect.md).
* **Projects**: opens CBM prg Studio `.cbmprj` files directly, using the same build order.
  Also opens VS Code + Kick Assembler workspaces (Vol 2) and its own `.l64proj` files.
* **Editor** with 6502 syntax highlighting, error navigation and breakpoints in the gutter.
* **Sprite, character set and screen editors** that read and write CBM prg Studio's
  `.spt`, `.cst` and `.sdd` files, SpritePad `.spd` and CharPad `.ctm` projects (Vol 2), and
  export `.bin` for `incbin` / `.import binary` or `byte` source.
* **Linked exports**: saving a graphics file can rewrite its `.bin` exports, so you don't have
  to export by hand after every change. A link is switched on automatically only when the
  `.bin` already matches the source, so unrelated files are never overwritten.
* **BASIC V2**: `.bas` files with highlighting, a tokenizer that crunches exactly like the
  C64's ROM, `{clear}`/`{white}`/`{3 down}`-style control codes, renumbering that updates
  GOTO/GOSUB/THEN targets, and listing any `.prg` back to source. A project can mix BASIC and
  assembly: the BASIC goes at `$0801`, the assembly anywhere above it. See
  [docs/basic.md](docs/basic.md).
* **Disk images**: a project can write a `.d64` (1541), `.d71` (1571) or `.d81` (1581) on every
  build (Project Properties → Disk Image), with the program first and any extra files after
  it, and run or debug from the disk on the matching drive. Disk images open in a directory
  view where you can add, extract and delete files. Files are laid out exactly as the real
  drive lays them out. See [docs/disk.md](docs/disk.md).
* **Cartridges**: a project can write a `.crt` on every build: normal 8K/16K, Ultimax, and
  the bank-switched Magic Desk, Ocean and EasyFlash. The program is bank 0, and data files fill
  further banks. Output matches VICE's `cartconv` byte for byte, and there's a cartridge
  project template. See [docs/cartridge.md](docs/cartridge.md).
* **SID music**: `.sid` files open with their header, play in VICE's `vsid`, and extract for
  `incbin`. Songs and sound effects from [GoatTracker GTK Edition and SidMonkey](https://github.com/robcowell/goattracker)
  open in those editors and are packed with GoatTracker's `gt2reloc` before every build, at the
  address you choose, with ready-to-paste player code. See [docs/music.md](docs/music.md).
* **Run and debug in VICE**: breakpoints, step into/over/out, registers, disassembly
  with labels, memory view, and the current source line highlighted. Uses VICE's
  binary monitor.

## Install

```sh
sudo apt install vice gir1.2-gtksource-5 gir1.2-adw-1 python3-gi python3-gi-cairo
uv venv --system-site-packages .venv
uv pip install --python .venv -e .
.venv/bin/linux64studio                       # the IDE
.venv/bin/linux64studio path/to/chapter17.cbmprj
tools/install-desktop.sh                      # optional: add it to your app launcher
```

Without `gir1.2-gtksource-5` the IDE still works, but the editor has no highlighting,
line numbers or gutter breakpoints (F9 still sets breakpoints).

## Keyboard shortcuts (same as CBM prg Studio where it has one)

| Key | Action |
|---|---|
| Ctrl+F5 | Build project and run |
| F5 | Build current file and run |
| F7 / Shift+F7 | Build project / current file |
| Shift+F5 | Debug project |
| F9 | Toggle breakpoint |
| F8 / F10 / F11 / Shift+F11 | Continue / step over / step into / step out |

## Command-line assembler

```sh
.venv/bin/l64asm chapter17.cbmprj                    # build a CBM prg Studio project
.venv/bin/l64asm gameMain.asm -o game.prg -l game.vs --list game.lst
.venv/bin/l64asm chapter17.cbmprj --d64 game.d64 --disk-name "my game,mg"
.venv/bin/l64disk list game.d64                # also: create, add, extract, delete (.d64/.d71/.d81)
.venv/bin/l64cart make normal8 cart.prg -o game.crt   # also: info, types (--bank for banked carts)
.venv/bin/l64sid pack tune.sng music.bin --address 1000   # also: info, extract, sfx
.venv/bin/l64bas game.bas                      # tokenize BASIC -> game.prg
.venv/bin/l64bas --list game.prg               # list a program as BASIC source
.venv/bin/l64bas --renumber game.bas --start 100 --step 10
```

## Retro Game Dev, Volume 2

Volume 2 uses **Kick Assembler** with VS Code, not CBM prg Studio. Kick Assembler is a Java
program that already runs on Linux. Open a chapter's `.code-workspace` file, then set the
path to `KickAss.jar` (included in the book's `Tools/KickAssembler` folder) under
Preferences → Kick Assembler.

The `Chapters/Content` folder appears in the project's file list, because the code imports
from it. Open `BeachBarSprites*.spd` in the sprite editor, or `BeachBarScreens.ctm` in the
CharPad editor (it has Characters and Map pages). When you save, the `.bin` files the chapters
import are rewritten: `BeachBarSprites1.bin`, `BeachBarScreensCharset.bin`,
`BeachBarScreensColors.bin`, and `BeachBarScreenTopLeft.bin` for the map. The sync button in
the editor's toolbar shows these links and lets you change them.

Supported: SpritePad format version 1 (SpritePad 2.0, as in the book) and CharPad CTM version 5
(CharPad 2.0–2.3), with up to 256 characters. In CharPad projects that use tiles (the book's
don't), you can edit the characters but the map is view-only. The tiles are kept intact when
you save.

## Tests

```sh
unzip c64edition-main.zip -d tests/book       # the book downloads (optional): Vol 1 sources
unzip c64editionvol2-main.zip -d tests/book   # and Vol 2's SpritePad/CharPad files
.venv/bin/python -m pytest
```
