# Binary Import/Export and the Disassembler

**Binary Import/Export** in the main menu, or **Import as Source** when you open a `.bin` from
the sidebar.

## Import

Choose a file. A `.prg` says where it loads. For other files, give a **Load address**
(`C000` by default). **Skip** and **Length** take part of the file. Then pick what to make
of it:

* **Disassembly**: 6502 source that reassembles to exactly the same bytes.
  * **Trace code from the entry points** follows the code from where it starts (a BASIC
    loader's `SYS` address, or the load address, or the **Entry points** you list), through
    branches, `JSR` and `JMP`, so tables and graphics stay as data instead of turning into
    nonsense instructions. Without tracing, everything that decodes is treated as code.
  * Branch, jump and data targets inside the file get labels (`L0810`); a target inside an
    instruction (self-modifying code) is written `L0810+1`.
  * Anything an assembler would encode differently is kept as `byte` lines with the
    instruction in a comment: absolute addressing of a zero-page address (`lda $0010`), and
    undocumented opcodes.
* **Assembler data**: `byte` lines (`.byte` in Kick Assembler projects) in hex, decimal or
  binary, with a label and a `*=` origin.
* **BASIC DATA statements**: decimal `DATA` lines from a chosen line number and step,
  optionally with a loader line (`FOR`/`READ`/`POKE`) that puts the bytes back where they load.

**Copy**, **Save As…**, or **Insert into Editor** (on its own line in the source file you last
worked on).

## Export

Writes part of the last build's memory to a file: give **From** and **To** as addresses or
labels (e.g. `SPRITEDATA` to `SPRITEDATA+$3FF`). Switch on **Add a load address** for a `.prg`.
The page shows how many of those bytes the program actually set.

## Command line

```sh
l64bin import game.prg --as disasm --trace -o game.asm
l64bin import data.bin --load c000 --as data --label table --per-line 8
l64bin import data.bin --load c000 --as basic --line 1000 --step 10
l64bin export game.prg --from 3000 --to 37ff -o sprites.bin
```

## Checks

`tests/test_binconv.py` disassembles all 43 `.prg` files in the two book downloads (Vol 1, its
Kick Assembler versions, and Vol 2), both traced and linear, and requires the built-in
assembler to rebuild each one byte for byte. With `L64S_VICE_TESTS=1`, it also runs a generated
BASIC loader in VICE and checks that it `POKE`s the right bytes into memory.

# Disassembler

**Disassembler** in the main menu, or **Disassemble** when you open a `.prg` from the sidebar.
Where Binary Import turns a whole file into source in one go, the Disassembler is for working
through a program and improving the result as you go.

## Sources

* **File**: any `.prg`, or another file with a load address (`C000` by default).
* **Last build**: the range **From**–**To** of the last build's memory, with the build's labels.
* **Running program (VICE)**: the same range from a snapshot of a debug session (Shift+F5). This
  is how to look at code the program built or loaded itself, or at the ROMs.

**Entry points** say where code starts (`auto` is a BASIC loader's `SYS` address, or the start).
With **Trace code**, only code reachable from them and from your code marks is disassembled.
**C64 names** names I/O registers, vectors and KERNAL routines, using the names in *Mapping the
Commodore 64* (`EXTCOL`, `SCROLX`, `CIAICR`, `CHROUT`).

## Keys in the listing

| Key | |
|---|---|
| C | Code from here (also clears the rest of a data range) |
| D | Data: the line, or every line in the selection |
| N | Name the address (empty removes the label) |
| ; | Comment |
| Enter | Follow the jump or branch on this line |
| Esc / Backspace | Back to where you followed from |
| G | Go to an address or label |

The side panel shows the current address, what refers to it, and every label. Click any of them
to go there.

Labels must be valid and unique (the assembler ignores case), and can't be a mnemonic, directive
or `A`/`X`/`Y`. Labelling an address outside the file names it in the source as an equate, which
is handy for zero-page variables (`temp = $FB`). Your own names win over the C64 names.

## Saving and exporting

For a file, the session (marks, labels, comments) is saved after every change next to it as
`<file>.l64dis`, and comes back when you open the file again.

**Export Source…**, **Copy** or **Insert into Editor** give source in the project's syntax: names
used outside the file as equates (`EXTCOL = $D020`, or `.const` for Kick Assembler), then the
code and data. It reassembles to exactly the same bytes, whatever you've marked or named. The
KERNAL ROM, traced from its vectors and jump table, comes out as `CHROUT  jmp (IBSOUT)` and so on,
and rebuilds byte for byte (`tests/test_disassembler.py`).

# Data Generator

**Menu → Data Generator** makes a table of values from a function of x, as in CBM prg Studio. It's
useful for sine waves, movement paths, curves and look-up tables. Type the function (`y =`), and
choose where x starts and ends (both are included) and its step (a whole number). The graph
shows the values with the origin at the top left and y growing downwards, like screen
coordinates, as CBM prg Studio's preview does. The source underneath updates as you type.

The function can use `x`, `+ - * / ^` (power), brackets, `pi`, `sin cos tan atn` (in radians),
`exp log sqr abs int sgn min max`. Names are case-insensitive, so the BASIC way of writing it,
`INT(100+99*SIN(X/20))`, works. The list button has some examples. It must use x.

* **Bytes** or **Words**: the values are rounded to the nearest whole number. A value that
  doesn't fit (bytes -128 to 255, words -32768 to 65535) is an error that says at which x. Turn
  on **Clamp y to a range** to limit the values instead.
* **Floats**: `fltp` lines (Commodore BASIC's 5-byte numbers; see the
  [dialect](dialect.md)). In a Kick Assembler project, which has no `fltp`, it writes the
  5 bytes of each value as `.byte` lines, with the values in a comment.
* **As deltas**: each value minus the one before it (the first value is as it is), for
  movement by steps.
* **Include x values**: x, y pairs.
* **Values per line**, an optional **Label**, and **Add comment**, which describes the function and
  range above the data.

**Copy** puts the data on the clipboard, and **Insert into Editor** puts it at the cursor of the
last source file you used.

`tests/test_datagen.py` checks the function parser (it accepts arithmetic only), the tables, the
range errors, clamping, deltas, pairs and the output in both syntaxes, and assembles the result.
The 5-byte floats are checked against values the C64 stores itself: an opt-in VICE test
(`L64S_VICE_TESTS=1`) runs a BASIC program that sets variables and reads them back from memory.
