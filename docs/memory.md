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

**Last build** uses the program from the last successful build, with no emulator needed. Kick
Assembler builds show the whole program as one segment, since the per-file detail comes from
the built-in assembler.

**Running program (VICE)** needs a debug session (Shift+F5). It takes a snapshot of memory as
the CPU sees it, including whatever the program has drawn or changed. A running program pauses
only for the read and carries on; the debugger doesn't show a stop. With **Every second** the
snapshot keeps refreshing. Who-owns-what still comes from the build.
