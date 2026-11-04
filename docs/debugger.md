# Debugger

**Shift+F5** (Debug Project) builds the project, starts VICE with its binary monitor, and sets
the breakpoints from the editor gutter (click a line number, or press F9). When the program
stops, the Debugger tab shows the registers, the disassembly around the PC (with your labels),
and memory. The editor highlights the source line, or the line that called the macro.

| Key | |
|---|---|
| F8 | Continue |
| F10 / F11 / Shift+F11 | Step over / into / out |
| F9 | Toggle breakpoint |

## Breakpoints and watches in the source

As in CBM prg Studio, the source can set up the debugger:

```
        breakpoint loop X == 20     ; stop at loop, but only when X is 20
        breakpoint                  ; stop at the next instruction
        watch score, player score   ; show score's byte at every stop
        debugstartaddress start     ; begin debugging at start
```

These breakpoints are added to the ones set in the gutter. A condition is VICE's, so it can
test `A`, `X`, `Y`, `SP` and `PC` (`PC == $1000`); decimal numbers are converted to hex for
VICE. Watches appear under the registers.

## Editing registers

PC, A, X, Y and SP are text fields. Type a value and press **Enter** to set it, or **Escape**
to put it back. Values can be hex (`1F`, `$1F`, `0x1F`), binary (`%00011111`), decimal (`#31`
or `31.`) or a label, with an offset if you like (`gMLoop`, `SCREENRAM+$28`). Setting PC to
a label is a quick way to run a routine again. The flag buttons (N V – B D I Z C) toggle each
status bit. Registers and flags that changed since the program last stopped are highlighted,
so after a step you can see what the instruction did.

## Editing memory

The hex view shows 256 bytes, with the screen-code characters beside them.

* **Go to**: type an address or a label in the Memory box and press Enter.
* **Move**: click, use the arrow keys, Home/End and Page Up/Down, or scroll the wheel.
* **Change a byte**: type two hex digits. Each byte is written to the C64 as soon as it's
  complete.
* **Write several bytes**: type into the box beside Memory and press Enter. It accepts
  `a9 00 8d 20 d0`, `$01,%10,#3`, `<label` / `>label` (an address's low or high byte),
  `"text"` (screen codes, for screen memory) and `'text'` (PETSCII). They're written at the
  cursor.

The status line shows the byte under the cursor in hex, decimal and binary, with its label.
Bytes that changed since the last stop are highlighted.

Writes to `$D000-$DFFF` reach the chips, so writing `02` to `$D020` turns the border red.
Code, the screen and the disassembly refresh after every change.

## Snapshots

**Snapshots** in the main menu saves and restores the whole machine (memory, registers, chips,
drives), like CBM prg Studio's State Manager. Snapshots are VICE snapshot files (`.vsf`), kept in
the project's `snapshots` folder with a small `.json` beside each for its name, note, PC and which
build it came from.

* **Take Snapshot** (during a debug session) saves the machine now, under the name you type. A
  running program pauses only for the save and carries on.
* **Double-click** a snapshot (or **Restore**) to load it: the machine goes back to that moment and
  the debugger stops there. With no debug session running, one is started for the project and the
  snapshot loaded as soon as VICE is ready, which is a quick way back to the middle of a game.
* Each snapshot shows its registers and the label at its PC, and takes a **note**. It warns if the
  program has been rebuilt since, as source lines may no longer match.
* Select **two** (Ctrl+click) to **compare** them: the time between them in cycles, the registers
  that changed, and every changed memory range with its region, the file it belongs to and the
  bytes before and after. Double-click a range to see it in the Memory Viewer.

The snapshot files are read directly for listing and comparing, without VICE (`tests/test_snapshot.py`;
the save and restore round trip through VICE runs with `L64S_VICE_TESTS=1`).

## Kick Assembler projects

Kick Assembler projects (Vol 2, or your own) get the same source-level debugging: breakpoints in
the gutter, the current line highlighted as you step, and stepping into other files. Kick
Assembler 5 and later write a debug dump (`-debugdump`, a `.dbg` file of which line made which
bytes), and Linux64Studio passes that option and reads the file after every build. A line inside a
macro is shown at the macro's own line, where the code is written, rather than where it's used.
The labels come from the dump too. When two labels share an address, the more specific one is
used (`active` rather than the `player_state` block it starts).

Kick Assembler 4 can't write the dump, so with it you get VICE and its monitor with your
labels, but no source lines. Run `tools/install-kickassembler.sh` to get the latest Kick
Assembler (5.25 at the time of writing). It goes in `~/.local/share/linux64studio/KickAssembler/`,
which Linux64Studio uses when Preferences doesn't name a `KickAss.jar` and the project doesn't
bring its own.

## Notes on VICE

These are worked around automatically, and were found with VICE 3.7.1:

* After a register is written, VICE ignores the next step, and if a breakpoint is active at
  the PC meanwhile, the step after that stops on it without running anything. The debugger
  finds out at start-up whether this VICE does that (it writes A back to itself during the
  KERNAL's reset and sees whether a step moves the PC). If it does, each register edit is
  followed by the step VICE ignores, with any breakpoint at the PC switched off, so your next
  step runs exactly one instruction.
* Setting breakpoints at start-up makes VICE stop briefly. Those stops are never shown.
* Stepping or continuing from a breakpoint runs that instruction with the breakpoint switched
  off, then switches it back on.
