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
  `.spt`, `.cst` and `.sdd` files, and export `.bin` for `incbin` or `byte` source.
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
```

## Retro Game Dev, Volume 2

Volume 2 uses **Kick Assembler** with VS Code, not CBM prg Studio. Kick Assembler is a Java
program that already runs on Linux. Open a chapter's `.code-workspace` file, then set the
path to `KickAss.jar` (included in the book's `Tools/KickAssembler` folder) under
Preferences → Kick Assembler. SpritePad (`.spd`) and CharPad (`.ctm`) files aren't
supported yet. Use their `.bin` exports.

## Tests

```sh
unzip c64edition-main.zip -d tests/book    # the book's Vol 1 download (optional)
.venv/bin/python -m pytest
```
