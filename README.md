# Linux64Studio

A Commodore 64 development environment for Linux (GTK4/libadwaita), modelled on
CBM prg Studio. It was built so the *Retro Game Dev C64 Edition* books by Derek Morris
can be followed on Linux.

* **Assembler** compatible with CBM prg Studio's syntax (macros with `/1`, `@locals`,
  `Operator Calc`, `incbin`, `repeat`, `relocate`, `func`, `generateto`, debugger `breakpoint`
  and `watch` directives, …). All 12 Vol 1 chapter projects build byte-for-byte
  identical to the book's `.prg` files. See [docs/dialect.md](docs/dialect.md).
* **Projects**: opens CBM prg Studio `.cbmprj` files directly, using the same build order.
  Also opens VS Code + Kick Assembler workspaces (Vol 2) and its own `.l64proj` files.
  **C projects** build with cc65: errors you can click, run in VICE and debug by C line, with
  breakpoints on C lines, stepping over and into C lines, and the C variables (locals and
  globals, with their types) at every stop. In the editor, C gets auto-complete, Go to Definition
  (including `#include`s) and the Project Information panel, and ca65 assembler files get their
  own highlighting and completion ([docs/c.md](docs/c.md)).
  **Continue where you left off**: at start it opens the last project again, with the same files in
  tabs, the same tab in front and the cursor where it was (Preferences → Editor to turn it off;
  a file named on the command line opens instead) ([session](docs/dialect.md#continue-where-you-left-off)).
  A **menu bar** laid out like CBM prg Studio's (File, Edit, Project, Build, Debugger, Tools, Git,
  Window, Help) and toolbar row ([menus](docs/dialect.md#menus)), the **Project Information**
  panel of labels, variables and macros by file ([project information](docs/dialect.md#project-information)),
  and CBM's **status bar** under source files (CAPS, INS/OVR, word wrap, line and column, auto line
  numbering, Git) ([status bar](docs/dialect.md#status-bar)).
  **Light or dark mode** from a toolbar button or Window → Appearance (or follow the system).
  The sidebar shows the project's files as an expandable **folder tree**, as in VS Code, where files
  and folders are made, renamed and trashed and the build order set, as in CBM's Project Explorer
  ([project files](docs/dialect.md#project-files), [managing files](docs/dialect.md#managing-files)). Each project reopens with the **tabs and folders
  it had open** when you left it ([per project](docs/dialect.md#each-projects-tabs-and-folders)).
  Right-click a tab to **Close Others**, **Close to the Right** or **Reveal File** in the file
  manager ([tab menu](docs/dialect.md#tab-menu)).
  Projects can run **build events** before and after a build (e.g. crunch with exomizer), as in
  CBM prg Studio ([docs/dialect.md](docs/dialect.md#projects)).
* **Editor** with 6502 syntax highlighting, error navigation and breakpoints in the gutter.
  **Auto-complete** offers the project's labels, constants and macros (with where each is
  defined), instructions and directives; **Go to Definition** (F12 or Ctrl+click, Alt+Left back)
  works for both assembler dialects, include lines and BASIC line numbers
  ([details](docs/dialect.md#auto-complete-and-go-to-definition-in-the-editor)).
  A **Tasks** panel lists every TODO, FIXME and HACK in the project ([tasks](docs/dialect.md#tasks-todo)).
  **Find and Replace** in the file (Ctrl+F, Ctrl+H) ([find and replace](docs/dialect.md#find-and-replace)), and
  **Find in Files** (Ctrl+Shift+F) across the project into a Find Results tab, both with match case,
  whole word and regular expressions ([find in files](docs/dialect.md#find-in-files)).
  `#region` … `#endregion` blocks fold away, as in CBM prg Studio ([folding](docs/dialect.md#folding-regions)).
  Source files can be **printed** (or previewed as a PDF) in their syntax colours ([printing](docs/dialect.md#printing)).
  A **source converter** turns Develop 64, Genesis and TASM sources into CBM prg Studio's dialect
  ([converting](docs/dialect.md#converting-sources-from-other-assemblers)).
  A selection becomes a Kick Assembler **Hashtable** or **List** ([kick tools](docs/dialect.md#kick-assembler-hash-tables-and-lists)).
  A **UTF-8 check** finds (and replaces) curly quotes, dashes and other non-ASCII characters pasted
  into source ([utf-8](docs/dialect.md#utf-8-check)).
  **Git**: create a repository with an ignore list, see each file's state in the file list, status,
  changes and history, add and commit ([git](docs/dialect.md#git)).
  **Tools → User Tools** runs your own programs with arguments naming the project's files
  ([user tools](docs/dialect.md#user-tools)).
  Hover over a number to see it in hex, decimal and binary, and right-click it to convert it
  ([base conversion](docs/dialect.md#base-conversion-in-the-editor)).
* **Sprite, character set and screen editors** that read and write CBM prg Studio's
  `.spt`, `.cst` and `.sdd` files, SpritePad `.spd` and CharPad `.ctm` projects (Vol 2), and
  export `.bin` for `incbin` / `.import binary` or `byte` source. The sprite editor's
  **Morph** makes the frames that turn one sprite into another, and the **Explosion
  Generator** makes explosion animations. **Import from Image** cuts sprites out of a `.bmp`,
  `.png` or `.gif` sprite sheet or screenshot, hires or multicolour, and the **Scratch Pad** lays
  sprites out side by side and in layers; both import characters and sprites **from a listing**
  (BASIC DATA or byte lines) and **from memory** (the last build, the running program, a file, the
  character ROM); and its **Scratch Pad** builds graphics
  from several characters, which the screen designer can stamp, and **Animation** plays a run of
  characters (or 2×2 blocks) looped or ping-pong. Screen **paths** turn points drawn on a screen into
  movement data (assembler or BASIC). The screen editor's **digitiser** gives the sprite
  coordinates of points on the screen ([docs/graphics.md](docs/graphics.md)).
  CharPad tile maps can be painted and their tiles edited, with a room grid and a materials
  view, and **Import CharPad Binaries** turns a game's char/attribute/tile/map files into an
  editable project that writes them back ([docs/graphics.md](docs/graphics.md#charpad-tile-maps)).
* **Linked exports**: saving a graphics file can rewrite its `.bin` exports, so you don't have
  to export by hand after every change. A link is switched on automatically only when the
  `.bin` already matches the source, so unrelated files are never overwritten.
* **BASIC V2**: `.bas` files with highlighting, a tokenizer that crunches exactly like the
  C64's ROM, `{clear}`/`{white}`/`{3 down}`-style control codes, automatic line numbers as you type
  (Return starts the next numbered line), CBM prg Studio's reformatting (spaces, REMs, DATA zeros,
  case) and Compress/Uncompress of keyword abbreviations, **token files** for BASIC extensions'
  keywords (`tokenfile`), renumbering that updates
  GOTO/GOSUB/THEN targets, and listing any `.prg` back to source, with control codes in
  Linux64Studio's, CBM prg Studio's BasText or Tok64 (petcat) style (all three are read). A project can mix BASIC and
  assembly: the BASIC goes at `$0801`, the assembly anywhere above it. **pBASIC** (`.pbas`) is
  BASIC with `@labels` instead of line numbers, numbered when it's built, with Create Label and
  Remove Line Numbers to convert a program. See [docs/basic.md](docs/basic.md).
* **Memory Viewer**: a map of all 64K showing which file put what where (code, data, included
  binaries) over the C64's regions, with free space and warnings for common mistakes such as
  graphics where the VIC-II can't see them. Any address can be viewed as hex, screen text,
  characters, sprites or a bitmap, from the last build or a live snapshot of the program
  running in VICE. **Find** bytes or text in it, and **Export** any block as formatted text or
  BASIC DATA. See [docs/memory.md](docs/memory.md).
* **Disassembler**: an interactive listing of a file, the last build or the running program.
  Mark code and data, name labels, add comments, follow jumps and see what refers to what. I/O
  registers and KERNAL routines get their standard names (EXTCOL, SCROLX, CHROUT). Export source
  that reassembles to the same bytes. See [docs/binary.md](docs/binary.md#disassembler).
* **Binary Import/Export**: turn any `.bin` or `.prg` into source, as a disassembly that
  reassembles to the same bytes (traced from the entry points to keep code and data apart),
  `byte` lines or BASIC DATA statements with a loader. Write any range of the last build out as
  `.bin` or `.prg`. See [docs/binary.md](docs/binary.md).
* **Snapshots**: save the whole machine at any moment of a debug session (VICE snapshots, kept in
  the project), double-click one to go back there (it starts a debug session if none is running),
  and compare two to see what changed. See [docs/debugger.md](docs/debugger.md#snapshots).
* **Memory Manager**: plan what the VIC-II sees (bank, screen, character set or bitmap, sprite
  data), get the `$DD00`/`$D018` values, sprite pointers and setup code, and see conflicts with
  your program and the character ROM. **Read from VICE** shows the layout a running program has
  actually set. See [docs/memory.md](docs/memory.md#memory-manager).
* **Screen Code Builder**: build PRINT strings with colours, cursor moves, reverse and
  Commodore/SHIFT graphics by clicking (on a **virtual C64 keyboard** that types what the
  KERNAL would, or a key map and code list), see exactly what they do on a C64 screen, and insert
  them as a BASIC PRINT line, PETSCII bytes for CHROUT, or screen codes (and colours) for
  screen memory. See [docs/basic.md](docs/basic.md#screen-code-builder).
* **Screen Calculator**: click a cell to get its screen and colour memory addresses, a source
  expression, BASIC POKEs, assembler, and the sprite X/Y over it; or find the cell at an address
  or under a sprite. The screen base can come from VICE or the Memory Manager. See
  [docs/memory.md](docs/memory.md#screen-calculator).
* **Code Snippets**: a library of BASIC and assembler routines (sprites, characters, hi-res,
  sound, joystick, raster interrupts…) to insert into a program. BASIC is numbered to fit after
  your program, with `!1`-style labels for GOTO targets. Kept in CBM prg Studio's
  `Snippets.xml` format, so you can import CBM's own snippets. See
  [docs/basic.md](docs/basic.md#code-snippets).
* **SYS() call generator**: the BASIC `10 SYS (2064)` line that starts your machine code, as
  `byte` lines for the top of your source, in decorated, plain or obfuscated style (it lists as
  a message of your own). See [docs/basic.md](docs/basic.md#sys-call-generator).
* **Data Generator**: byte, word or 5-byte float tables (sine waves, paths, curves) from a function
  of x, with a graph, deltas, x/y pairs and clamping. See [docs/binary.md](docs/binary.md#data-generator).
* **String Formatter**: split long strings into lines of a set length, as BASIC `a$=a$+"…"`
  lines or `text` lines (PETSCII or screen codes), with case changes and regular-expression find
  and replace. See [docs/basic.md](docs/basic.md#string-formatter).
* **Source Analyser**: instruction counts, addressing modes and estimated cycles for a project,
  file or selection, from the assembled code (real zero page/absolute modes, macros counted
  where they're used), with filters, a footprint, charts, metrics, and text/HTML export. See
  [docs/binary.md](docs/binary.md#source-analyser).
* **Statistics (BASIC)**: the variables a BASIC program sets and where, the names that are
  really the same variable (only two characters count), names the C64 reads as keywords
  (`score` is `SC OR E`), and jumps to missing lines. See [docs/basic.md](docs/basic.md#statistics).
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
  address you choose, with ready-to-paste player code. The **SID Designer** (CBM prg Studio's
  SID tool) sets up the three voices and the filter, plays them live through VICE's reSID, with
  a two-octave keyboard or a MIDI keyboard, and generates BASIC POKEs or assembler. See [docs/music.md](docs/music.md).
* **Run and debug in VICE**: breakpoints (kept with the project, switched on and off in a
  **Breakpoints** list: [breakpoints](docs/debugger.md#the-breakpoints-list)), step into/over/out, disassembly with labels,
  and the current source line highlighted. You can **edit registers and flags** and **edit
  memory** in a hex editor (type over bytes, go to an address or label, write byte lists or
  text); changes since the last stop are highlighted. Uses VICE's binary monitor. See
  [docs/debugger.md](docs/debugger.md). Builds can also write a Kick Assembler-style `.dbg` debug dump
  for C64 Debugger, RetroDebugger or VS64.

## Install

```sh
sudo apt install vice gir1.2-gtksource-5 gir1.2-adw-1 python3-gi python3-gi-cairo
sudo apt install python3-mido python3-rtmidi   # optional: MIDI keyboards in the SID Designer
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
.venv/bin/l64bin import game.prg --as disasm --trace -o game.asm   # also --as data / basic, and export
.venv/bin/l64bas game.bas                      # tokenize BASIC -> game.prg
.venv/bin/l64bas --list game.prg               # list a program as BASIC source
.venv/bin/l64bas --renumber game.bas --start 100 --step 10
```

## Retro Game Dev, Volume 2

Volume 2 uses **Kick Assembler** with VS Code, not CBM prg Studio. Kick Assembler is a Java
program that already runs on Linux. Open a chapter's `.code-workspace` file, then set the
path to `KickAss.jar` (included in the book's `Tools/KickAssembler` folder) under
Preferences → Kick Assembler. Or run `tools/install-kickassembler.sh`, which downloads the
latest Kick Assembler (5.25) from its official site, for Linux64Studio to use whenever
Preferences doesn't name one. Kick Assembler 5 builds get source-level debugging
([docs/debugger.md](docs/debugger.md#kick-assembler-projects)).

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
