# Memory Viewer

**Memory Viewer** in the main menu shows where everything is in the C64's 64K.

## The map

The square on the left is all of memory: one pixel per byte, 256 bytes (a page) per row,
`$0000` at the top left and `$FFFF` at the bottom right. Every source file has its own colour
(data slightly lighter, included binaries muted). The shaded bands behind are the C64's
regions: zero page and stack, the KERNAL/BASIC work area, screen RAM, the BASIC program area,
the BASIC ROM, `$C000`, I/O and the KERNAL ROM. Hover for the address, region, value, owning
file and label. Click to pick an address.

Code a macro produced counts as the file that used the macro, not the library that defines it.

## Overview

* **Segments**: each stretch of code, data or binary, with its file. Double-click one to open
  the source at the line that produced it.
* **Free**: unused space above `$0801`, with the region each gap is in.
* **Warnings** for placements that often cause trouble:
  * the zero page, stack or KERNAL/BASIC work area, which the system uses as it runs;
  * the default screen memory, which shows on screen and is erased by clearing it;
  * under the I/O area, which the CPU only reaches with I/O switched out;
  * code under the BASIC or KERNAL ROM, which the CPU doesn't run unless the ROM is banked
    out. Data there is fine, because the VIC-II reads the RAM;
  * an included binary at `$1000-$1FFF` or `$9000-$9FFF`. If it's graphics, the VIC-II can't see
    it: in VIC banks 0 and 2 it reads the character ROM there instead of RAM;
  * two files writing the same bytes.

## Views

Type an address or a label in **Address**, or click the map, then pick a view:

| View | Shows |
|---|---|
| Hex | 256 bytes, with screen-code characters |
| Screen | 1000 bytes as a 40×25 screen, using the ROM character set or your own (give its address, e.g. `3800`) |
| Characters | 256 characters (2K) as a character set |
| Sprites | 32 sprites (64 bytes each) |
| Bitmap | 8000 bytes as a hires bitmap |

Each graphics view has hires/multicolour and the four colours.

## Last build or running program

**Last build** uses the program from the last successful build, with no emulator needed. For a
Kick Assembler 5 build, the segments, kinds and labels come from its debug dump (see
[debugger.md](debugger.md#kick-assembler-projects)). With Kick Assembler 4 there's no dump, so
the program is one segment, labelled from its VICE labels file.

**Running program (VICE)** needs a debug session (Shift+F5). It takes a snapshot of memory as
the CPU sees it, including whatever the program has drawn or changed. A running program pauses
only for the read and carries on; the debugger doesn't show a stop. With **Every second** the
snapshot keeps refreshing. Who-owns-what still comes from the build.

## Find

**Find** (the magnifier, or Ctrl+F) searches memory for bytes or text, as CBM prg Studio's Find in
Memory does. Type the values in hex (`$A9`, `0xA9`), decimal (`169`) or binary (`%10101001`),
separated by spaces or commas, and strings in quotes. You can mix them: `$A9 0 "hi"`. Choose
whether strings are **PETSCII** (as BASIC and CHROUT print them) or **screen codes** (as they
are in screen memory, and as the book's `text '…'` lines store them). The search starts at
**From** and wraps round to $0000. The bytes it finds are highlighted in the Hex view, with how
many matches there are in all. With **Next find starts after it** ticked, pressing Enter or
**Find / Next** again finds the next one. Ctrl+G goes to the address box.

## Export

**Export…** writes a block of memory out as text, as CBM prg Studio's Export Memory does. The
block starts as the found bytes, or the segment at the cursor, or else 256 bytes from it. Set:

* **Block start** and **Block end** (`$hex`, decimal or a label).
* **Format specifier**, the text before each value (`$`, `0x`), and the **Separator** between
  them.
* **Number base**: hex, decimal, octal or binary, padded to 2, 3 or 8 digits if you like. As in
  CBM prg Studio, changing the base doesn't change the format specifier.
* **Values per row**, and **Row leading** and **trailing text**, such as `byte ` before each row,
  or brackets around it. The trailing text goes on the last row too.
* **Header** and **Footer**. `%start%`, `%end%`, `%size%` and `%date%` are replaced; they're
  case-sensitive. So `; %start%-%end%, %size% bytes` becomes `; $0ACB-$0AD4, 10 bytes`.

Or export as **BASIC DATA with a loader**: DATA lines and a line that POKEs them back into
place, as CBM prg Studio's Create DATA From Memory does. The preview updates as you change things.
**Copy** it, or **Save…** it to a file.

`tests/test_memtools.py` checks the search values, PETSCII and screen code strings, wrapping,
every number base, the rows, and the header keywords. It includes the example from CBM prg
Studio's help.

# Memory Manager

**Memory Manager** in the main menu plans what the VIC-II sees, which is the part of C64 memory
that most often goes wrong: a character set that won't show, or sprites that come out as garbage.

## Choosing a layout

* **VIC-II bank**: the 16K the VIC-II reads from (`$DD00` bits 0-1).
* **Screen memory**: any 1K block in the bank. The sprite pointers are its last 8 bytes
  (screen+`$3F8`).
* **Character set**: any 2K block. In banks 0 and 2, `$1000` and `$1800` are the ROM's upper-case
  and lower-case sets.
* **Bitmap mode**: an 8K bitmap (either half of the bank) instead of a character set.
* **Sprite data**: add 64-byte blocks by address (`3000`, or a label) or pointer value (`#192`).

## What you get

* The **bank picture**: the 16K with the screen, sprite pointers, character set or bitmap and
  sprites drawn in, the character ROM hatched where the VIC-II sees it instead of RAM, and (with
  *Show the last build*) your program's bytes. Hover for what's at an address.
* The **register values**: `$DD00` bits, `$D018`, where the sprite pointers are, and the value for
  the book's `LIBSCREEN_SETCHARMEMORY` macro (14 for characters at `$3800`).
* **Issues**:
  * anything placed where the VIC-II sees the character ROM (it shows the ROM, not your data);
  * areas that overlap each other;
  * areas under the I/O area in bank 3 (the VIC-II reads the RAM; the CPU has to switch I/O out
    to write it);
  * a character set slot in bank 1 or 3 that would be the ROM in banks 0 and 2;
  * overlaps with the program's code (a warning), or the data that fills an area, e.g. "Character
    set holds an included binary from gameMemory.asm" (a note).
* **Setup code** in the project's syntax: constants (`VICBANK`, `SCREENRAM`, `SPRITEPTRS`,
  `CHARSET` or `BITMAP`), then the `$DD00` and `$D018` writes and the sprite pointers. **Copy** or
  **Insert into Editor**.

## Read from VICE

During a debug session (Shift+F5), **Read** takes the layout the running program has actually
set (bank, screen, character set or bitmap, and the pointers of the sprites that are switched on)
from a snapshot of memory, without stopping it. Use it to see why something isn't showing.

These were checked against VICE: reading chapter 17 gives bank 0, screen `$0400`, characters
`$3800` and sprite pointer 192 (data at `$3000`), and the generated setup code sets the layout it
describes (`tests/test_vicmem.py`, with `L64S_VICE_TESTS=1`).

# Screen Calculator

**Menu → Screen Calculator** works out where a character cell is in memory, as CBM prg Studio's
tool does. Click a cell on the 40×25 screen, or type its row (0-24) and column (0-39). The
results, each with a Copy button, are:

* **Screen address** and **Colour address**, in hex and decimal: base + row × 40 + column.
* **Offset** from the start of the screen.
* **Expression**, such as `$0400 + 12*40 + 20`, to paste into your source.
* **BASIC**: `poke 1524,1 : poke 55796,1`, and **Assembler**: `lda`/`sta` for the character
  and its colour. The character (a screen code) and colour come from the boxes beside the row
  and column. These three lines can also be inserted into the last source file you used.
* **Sprite X, Y** that puts a sprite's top-left corner on the cell's top-left (X = 24 + 8 ×
  column, Y = 50 + 8 × row). For X above 255, the result says to set the sprite's bit in $D010.

The screen base is `$0400` (the C64's default) unless you change it. **From…** reads it from the
running program in VICE (its `$DD00` bank and `$D018`), or from the layout planned in the Memory
Manager. You can also type it in. Colour RAM is always at `$D800` on the C64, but that can be
typed in too. Numbers can be `$hex`, `%binary` or decimal (here bare digits are decimal, so
`1064` is `$0428`).

**Find the cell** goes the other way. Type an address in screen memory or colour RAM, or a
sprite position, to select the cell it falls in. A sprite position in the border says so.
`tests/test_screencalc.py` checks the arithmetic, and assembles the generated lines.
