# Binary Import/Export

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
