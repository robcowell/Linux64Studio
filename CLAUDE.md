# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Linux64Studio is a GTK4/libadwaita C64 IDE modelled on CBM prg Studio (Windows-only), built so
Derek Morris's *Retro Game Dev C64 Edition* books (Vols 1 and 2) can be followed on Linux. The
hard requirement: **the assembler accepts CBM prg Studio's syntax exactly**, so the book's
sources build unchanged. `docs/dialect.md` is the spec of that dialect.

## Rules

- **Missing libraries:** if a library, package or tool you need isn't installed (a Python
  module, a GObject typelib, a system package), stop and ask Rob to install it, with the exact
  command (e.g. `! sudo apt install python3-numpy`). Don't work around it by writing a
  substitute, picking a weaker approach, or vendoring code.
- Running Kick Assembler (`java -jar KickAss.jar`, the book's copy or a project's own) is fine:
  use it to build and test Kick Assembler projects. CBM prg Studio's Windows files (extracted in
  the scratchpad) are only read and analysed, not run.

## Commands

```sh
uv venv --system-site-packages .venv && uv pip install --python .venv -e .   # PyGObject comes from the system
.venv/bin/python -m pytest                                    # all tests
.venv/bin/python -m pytest tests/test_sid_designer.py -k basic   # one file / one test
L64S_VICE_TESTS=1 .venv/bin/python -m pytest                  # also the opt-in tests that launch VICE
.venv/bin/linux64studio [project.cbmprj]                      # the IDE
.venv/bin/l64asm chapter17.cbmprj                             # CLIs: l64asm l64bas l64disk l64cart l64sid l64bin l64test
tools/install-kickassembler.sh   # Kick Assembler 5.25 into ~/.local/share/linux64studio (the default jar)
```

There's no lint config in the repo; `uvx ruff check --line-length 120 <files>` works but its
style findings (noqa/UP037) aren't enforced.

**Book corpus:** `tests/book/` (gitignored) holds the unzipped book downloads (`c64edition-main`,
`c64editionvol2-main`). Tests that use them skip when absent. They are the final authority on
dialect questions: all 12 Vol 1 chapters must assemble byte-identical to the shipped `.prg`s.

## Architecture

`src/l64s/` is split into GTK-free layers (pure Python, tested headless) and `ui/`, which is the
only package that imports GTK. Put logic in a model module with tests, and keep the UI page thin.

- `asm/`: the assembler. `source.py` (`SourceLoader`) does includes, `defm`/`endm` macros
  (`/1`..`/9` parameters, `@local` labels unique per expansion) and conditionals. `assembler.py`
  runs multiple passes until sizes are stable (forward references choose zero page vs absolute
  sizing) and returns a `Result` (`memory`, `used`, `symbols`, `listing`, `diagnostics`). Labels
  are case-insensitive, macro names case-sensitive. `disasm.py` is shared by the disassembler
  tools.
- `project/`: `model.py` loads `.l64proj` (JSON), CBM `.cbmprj` (XML, via `cbmprj.py`) and VS
  Code + Kick Assembler `.code-workspace` (Vol 2). `build.py` (`build_project`) assembles the
  **build list in order** (as CBM does), merges BASIC at `$0801`, packs GoatTracker music, and
  writes `.prg` plus optional disk image / cartridge; `BuildResult.run_target` is what VICE runs.
  Kick Assembler is an external tool (`toolchain == TOOLCHAIN_KICKASS`), and so is cc65 for C
  (`TOOLCHAIN_CC65`: `project/cc65.py` builds with `cl65`, `cc65dbg.py` reads ld65's `--dbgfile`).
- `emu/`: VICE integration. `vice.py` launches `x64sc`; `binmon.py` is a client for VICE's binary
  monitor protocol (TCP, API v2). `sim.py` is Debug Without VICE: py65's 6510 with the C64's memory
  and ROMs, the raster interrupt and the cycles the VIC-II takes, both CIAs (`simcia.py`: timers,
  clocks, IRQ and NMI), behind `SimMonitor` (binmon's methods), so the
  debugger and transcripts drive either; `simdrive.py` is its drive 8, a 1541's DOS answering the
  KERNAL's serial routines (taken over at their entry points), ported from Rift64's
  (`~/code/Rift64/public/js/c64-disk.js`); `simscreen.py` draws its screen. `ui/debugger.py` (`DebugSession`) works around VICE 3.7.1
  quirks (calibrated quiet step after register writes, ignoring start-up stops, breakpoint
  disabling around writes); read its comments before changing stepping.
- Formats, each with a model and CLI: `gfx/` (CBM `.spt`/`.cst`/`.sdd`, SpritePad `.spd`,
  CharPad `.ctm`, Pepto palette), `basic/` (ROM-exact tokenizer, PETSCII, renumber, screen codes),
  `disk/` (D64/D71/D81 with DOS-exact allocation matching real-drive fixtures in
  `tests/fixtures/`), `cart/` (`.crt`, matches `cartconv`), `sid/` (PSID, GoatTracker via its
  `gt2reloc`/`ins2snd2` tools from `~/goattracker/linux`, the SID Designer model, and `live.py`,
  which plays sound by writing SID registers into an idle `vsid` over the binary monitor).
- Top-level analysis modules used by tool pages: `memmap.py`, `vicmem.py` (VIC bank/screen/charset
  layouts and `$D018`/`$DD00` values), `disassembler.py`, `binconv.py`, `snapshot.py` (VICE
  `.vsf`), `screencalc.py`, `c64symbols.py`.
- `ui/window.py` (`MainWindow`) owns the tabs, menu, actions, builds and the debugger panel.
  Every tab is an `EditorPage` (`ui/editor.py`). File types open by suffix in `open_file`.
  **Tool pages** follow one pattern: an `EditorPage` subclass with a `kind` (mapped to an icon
  in `_add_page`), a `title` property and a no-op `save()`; a menu item `win.<action>`; an
  `open_<tool>()` that reuses an existing tab; assembler output in the project's syntax
  (`kickass` flag); Copy plus **Insert into Editor** via `MainWindow._insert_into_last_source`.
  Live data comes through callbacks such as `lambda: self.debug` and `self._memory_of_last_build`.

## Conventions

- Generated BASIC is in listing notation: **lower-case keywords**. Capitals are shifted PETSCII
  and won't tokenise as keywords. Control codes are written `{clear}`, `{3 down}`.
- In the debugger and monitor views, bare digits are hex (as in VICE's monitor,
  `emu/values.py`). Calculator-style tools parse bare digits as decimal.
- Verify features against VICE (opt-in tests, or by reading registers/memory over the binary
  monitor) and the book corpus, not only unit tests. GUI changes are checked by driving the app
  with `GLib.timeout_add` steps and rendering screenshots (`Gtk.WidgetPaintable` →
  `render_texture`) into the scratchpad.
- Each feature has a user doc in `docs/` (dialect, basic, disk, cartridge, music, debugger,
  memory, binary, c) plus a README bullet; update them with the feature.
- `docs/tutorials/` are step-by-step guides, each with a project in `examples/tutorials/` and a
  transcript there that `tests/test_tutorials.py` runs in VICE: keep them true when the IDE changes.
