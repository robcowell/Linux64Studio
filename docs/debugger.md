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
