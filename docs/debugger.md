# Debugger

**Shift+F5** (Debug Project) builds the project, starts VICE with its binary monitor, and sets
the breakpoints from the editor gutter (click a line number, or press F9). When the program
stops, the Debugger tab shows the registers, the disassembly around the PC (with your labels),
and memory. The editor highlights the source line, or the line that called the macro.

| Key | |
|---|---|
| F8 | Continue |
| F10 / F11 / Shift+F11 | Step over / into / out (in C, by C line: [stepping by C line](c.md#stepping-by-c-line)) |
| Ctrl+F10 / Ctrl+F11 | Step over / into one instruction, even in C |
| F9 | Toggle breakpoint |
| Shift+F8 | Skip an instruction: move past it without running it |
| Ctrl+Shift+F5 | Debug without VICE, on the simulated C64 ([debugging without VICE](#debugging-without-vice)) |

## Joysticks

To play a game while running or debugging it, **Preferences → Emulator → Joystick in port 2** (and
port 1) chooses what drives the C64's joystick in VICE: the **keypad** (8 4 6 2 to move, 0 to fire),
one of VICE's two keysets (whose keys are set in VICE's own settings), or a real joystick or
gamepad. Most games read port 2. It's passed to VICE as `-joydev2`; a `-joydev` option typed into
the extra VICE arguments wins.

## The Breakpoints list

The **Breakpoints** tab of the bottom panel lists every breakpoint in the project, as CBM prg
Studio's Breakpoints window does: in open files and closed ones, each with its file and line, the
line's text and, after a build, the address it stops at. A breakpoint on a comment or label line
stops at the first instruction after it.

* The tick switches a breakpoint on or off. One that's off stays where it is (a hollow circle in the
  margin, its line greyed) but doesn't stop the program, so it's easy to bring back. **All On** and
  **All Off** switch every one.
* The × removes one; **Remove All** removes every breakpoint in the project.
* Double-click a breakpoint to go to its line.

Breakpoints belong to the project: they stay when a file is closed, come back when the project is
opened again, follow a file that's renamed or moved, and go when it's moved to the Trash. Their
lines move with the code as you add or remove lines above them. A debug session uses every one
that's on, whether its file is open or not, and changes take effect at once while it runs.
Breakpoints written in the source (below) come from the build, so they aren't in the list.

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

## Skipping an instruction

**Skip Instruction** (Shift+F8, the toolbar's last arrow, or **Debugger → Skip Instruction**) moves the
PC past the instruction at it without running it, as CBM prg Studio's Shift+F8 does. Registers,
flags and memory stay as they were. Use it to jump over a `jsr` to code you don't want to run yet, or
a loop that waits for something that won't happen while you're debugging.

## Memory before debugging

**Project Properties → Build → Memory before debugging** lists files to write into memory when
debugging starts, as CBM prg Studio's debugger's external files: level data, a table the program
expects, a character set from another program. They go in once the program is loaded, just before it
runs (when RUN starts it), and before a [transcript](#transcripts)'s first command.

* A `.prg` goes at its own load address.
* Any other file goes at the address given with it.
* An overlay file (`.ovl`, CBM prg Studio's format) says where its bytes go:

```
; a comment
*=c000          the address for the bytes after it (hex)
42 43 44        bytes, one or several a line
00*10           a byte repeated: $00, $10 (16) times
decimal         the numbers after this are decimal
```

CBM prg Studio can also take a VICE snapshot here. Linux64Studio can't: its RAM would overwrite the
program just loaded. Use **Debugger → Snapshots** to go back to a machine state instead. A
cartridge isn't started by RUN, so with **Run with the cartridge plugged in** the memory isn't
loaded. A program run from a disk image is loaded with LOAD first, so the memory goes in as that
LOAD starts: anywhere the loaded file covers, the file wins.

## Cycles

Under the flags, **Cycles** shows how many cycles the last run took, and a total since **Reset**.
Each count is exact, including the cycles the VIC-II takes (on a badline, or for sprites), so a step
over `lda $d012` on a badline shows the stall too.

* Without **Count all**, a single instruction's cycles are shown: a step into, or a step over
  anything but a JSR. They come from the raster position before and after, which changes nothing in
  the machine.
* With **Count all** ticked, every run is counted, however long: a continue to a breakpoint, a step
  over a subroutine, a step by C line, a pause. This uses CIA 2's two timers as a 32-bit cycle
  counter, so a program that uses CIA 2's timers itself would be disturbed. Its control registers
  are put back when you untick it, but the timers' latches are left at `$FFFF`.

To time a whole routine over many calls, [routine timing](#routine-timing) does it for every call.

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

**Debugger → Snapshots** saves and restores the whole machine (memory, registers, chips,
drives), like CBM prg Studio's State Manager. Snapshots are VICE snapshot files (`.vsf`) (the simulator's too: [below](#debugging-without-vice)), kept in
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

## Debugging without VICE

**Debugger → Debug Without VICE (simulator)** (Ctrl+Shift+F5) debugs the program on a C64 simulated
inside Linux64Studio, as CBM prg Studio's own debugger does, with no emulator started. Everything
above works the same: breakpoints and their conditions, stepping by line or instruction, C variables,
editing registers and memory, Skip Instruction and memory before debugging. There's no VICE window:
the Debugger tab has a **Screen** beside **Memory**, which draws the screen from memory, and it's
redrawn while the program runs.

What's simulated is the 6510 (from [py65](https://github.com/mnaberez/py65)) and the C64's memory.
The memory has the real BASIC, KERNAL and character ROMs, from VICE's install, banked in and out by
`$01` as on a C64. So the program is started as on a C64: the KERNAL boots to READY, the program is
loaded, and RUN is typed (a program not at `$0801` starts at its first byte, or at
`DEBUGSTARTADDRESS`). KERNAL calls run for real. Every instruction takes its exact cycles, page
crossings and branches included, so the cycle counter counts every run exactly, with no **Count
all** needed. `tests/test_sim.py` checks the counts against VICE's.

What isn't simulated: most of the VIC-II, SID and CIAs. `$D000`-`$DFFF` is memory that reads back
what was written to it, except for what makes timing and interrupts work:

* The raster line (`$D012`, and `$D011`'s top bit) counts as on a PAL C64, 63 cycles a line, so code
  that waits for a line gets there.
* The VIC-II's **raster interrupt**: when the raster reaches the line in `$D012` (and `$D011`'s top
  bit), `$D019`'s flag is set, and with it switched on in `$D01A`, there's an interrupt. Writing 1
  to `$D019` clears the flag.
* CIA 1's **timer A** (`$DC04`/`$DC05`, started and stopped with `$DC0E`) counts down a cycle at a
  time and sets `$DC0D`'s flag when it runs out, with an interrupt if `$DC0D` has it on. That's the
  KERNAL's own interrupt, 60 times a second, so its clock ticks and its cursor blinks. Reading
  `$DC0D` clears the flags (the debugger's reads don't).
* The **keyboard and joysticks**: CIA 1's ports (`$DC00`, `$DC01`) read the keys held down, through
  the keyboard matrix (a key reads as down in the column `$DC00` selects), and joystick 2 on
  `$DC00`, joystick 1 on `$DC01`. So the KERNAL's keyboard scan and a game's own both see them.

Interrupts happen as on a C64 while the program runs, through `$FFFE`, so a raster interrupt
handler, music played from one, or the KERNAL's clock all work, and a breakpoint in a handler stops
there. A single step never goes into one: Step Into and Step Over run the instruction at the PC, and
any interrupt waits until the program runs on. Stepping over a JSR runs the subroutine with
interrupts, as running does. CIA 2, its NMI, the CIAs' other timers and time-of-day clocks, and
sprite collisions aren't there. The VIC-II never takes
cycles from the CPU either, so the counts are those of a blanked screen. The screen is a picture of
memory, not an emulated VIC-II: a change made halfway down the frame shows on all of it, and sprites
are drawn in front of everything. As in CBM prg Studio, the program stops at a `BRK`, and at an
opcode the 6510 doesn't document (the simulator doesn't run those). **Skip** moves past either.

**Click the Screen to play the program**: the arrow keys or the keypad (8, 4, 6, 2) move joystick 2,
keypad 0 or Right Ctrl fires, and the other keys are the C64's (Return, Backspace for DEL, Escape for
RUN/STOP, Left Alt for the Commodore key, F1/F3/F5/F7). The program runs at a real PAL C64's speed;
tick **Full speed**, in the Debugger tab's bar, to run it as fast as the simulator can (about twice
that), to get to a breakpoint sooner.

**Skip KERNAL calls**, in the bar too, steps over JSRs into the KERNAL's jump table
(`$FF81`-`$FFF3`) as if they returned at once, as CBM prg Studio's option does. Without VICE's ROMs
there's no KERNAL to run, so it's on, and a program that isn't at `$0801` (or has a SYS line) starts
at once.

**Snapshots** work on the simulator too, in the same Snapshots list. A snapshot of the simulator is
a `.vsf` with VICE's CPU and memory parts, so it's listed and compared like VICE's, and one of its own
for the I/O area and the chips' state; restoring it puts the simulator back exactly as it was. It
says *the simulator* in the list, and double-clicking one with no debug session running starts
debugging without VICE. VICE can't load one (it has none of VICE's chips), and a VICE snapshot loads
into the simulator as its RAM, registers and processor port, with the I/O area as it was.

## Profiler

**Debugger → Profile in VICE** builds the project, runs it in VICE, and measures where the 6510's
time goes, while the program runs at its real speed. Play the game as it's measured: what you're
doing is what's measured. The **Profiler** tab fills as it goes:

* **Routines**: each routine's share of the CPU's time. For assembler, a routine is the code from
  one label to the next. Local labels (`@loop`, `!loop`) count as part of the label above them.
  For C it's the function, static ones too, plus cc65's runtime helpers (`pushax`, `ldaxysp`,
  marked `c64.lib`). Time in the ROMs is named by KERNAL routine (`KERNAL IRQ handler`,
  `KERNAL SCNKEY keyboard scan`) or `BASIC ROM`.
* **Lines**: the same by source line, with the line's text. In Kick Assembler a macro's code counts
  at the macro's own line, as in the debugger.
* **Files**: the same by source file, with the KERNAL as one.
* **Frame**: the frame from raster line 0 at the top down to the last line (311 on PAL). Each line
  is split between the routines that run while the VIC-II draws it, as the border-colour trick shows
  it, but measured. The shaded band is the screen's 25 text rows; hover over a line for its routines.
  A raster interrupt shows up as a band at its line.

Click a routine or line to go to it in the source.

**In the editor**, each line's share of the time shows in a column beside its line number. The
busiest lines are tinted orange, deeper for more: 10% of the time or more, 3%, 1% and 0.3%. Hover
over a figure for its exact share and samples. The figures fill in as the profile runs, stay after
it stops, and move with their lines as you edit. The next profile replaces them. Untick **In the
editor** to hide them, and they go when the Profiler tab is closed.

**Reset** starts the counts again from now,
for measuring one part of a game (get to the level, then Reset). **Stop** stops measuring; the
program carries on in VICE. The copy button copies the profile as text.

A main loop that waits for the next frame (for the raster line to come round, or for a flag the
interrupt sets) usually comes out on top. That's the frame's spare time: the less of it there is,
the closer the game is to slowing down. In Glowcave it's `wait_frame()`, about two thirds of the time.

How it measures: VICE's monitor only answers once a frame, so asking for the PC on a timer would
always find the same place. Instead the profiler has VICE run a random number of instructions,
from one to a few hundred, then stop. It reads where the program got to: the PC, and the raster
line and cycle. Then it lets it go on. That's about 500 samples a second. Each sample counts with
its instruction's cycles, so a share is of time, not of instructions. The raster position also says
how much time passed between samples, which keeps the program at its real speed. The sound may
crackle, as VICE stops so often. A share is an estimate, more exact the longer you let it run:
with 10,000 samples, a 10% share is within about half a percent.

### Routine timing

The profiler's shares are estimates. To find out exactly how long one routine takes, for example
whether an interrupt handler fits in the border, use the Profiler's **Timing** page. Name the
routine (a label, a C function, or an address such as `$1000`) and press **Time in VICE**. You can
also right-click in the editor and choose **Time This Routine**. That times the routine named under
the cursor if it's on a `jsr`, a `jmp`, a label's own line or, in C, a call. Otherwise it times the
routine the line is in. The program is built and run in VICE, and each call is measured to the
cycle:

* **Fewest, average, median and most cycles** a call, also as raster lines and as a share of a frame.
  A PAL frame is 19,656 cycles: 312 lines of 63.
* **Calls a frame**, and how many calls were measured and counted.
* **Starts** and **Ends**: the raster lines its calls start and end on. **Where in the frame**
  shades the lines it runs on, deeper the more of its calls run there.
* **Calls by cycles**: a histogram, to tell a routine that always takes the same time from one with
  slow cases.

A call is timed from its first instruction to the instruction it returns to: just after the `jsr`,
or for an interrupt handler the instruction the interrupt came in at. That includes the `rts`, or
for a handler that goes through the KERNAL (via `$0314`) the KERNAL's own exit. Anything that
happens meanwhile counts too, such as an interrupt arriving during the routine, because that's
time the routine really takes. A handler reached through the KERNAL's vector or the CPU's own
`$FFFE` is recognised as one. A routine that's neither called by `jsr` nor an interrupt handler
can't be timed, because where it ends isn't known.

How it measures: VICE stops at the routine's first instruction, and again where the call returns
(once the stack pointer is back where it was, so a return from something the routine calls
doesn't count). The raster position at the two stops gives the exact number of cycles; stopping
doesn't change the emulated machine. A checkpoint that doesn't stop counts every call. The time
comes from the second CIA's time-of-day clock, which runs on emulated time. Timing starts that
clock, so a program that uses CIA 2's time-of-day clock itself will see it changed. Calls are measured up
to about 60 a second, chosen at random so they're a fair share. A routine that loops back to its
own first instruction (`while (!ready) {}` in C) has every call measured. The program keeps close
to its real speed, so you can play it meanwhile. A call can take any time, a frame or more included:
the raster position goes round once a frame, so CIA 2's timers count the cycles too, as a 32-bit
count, to say how many whole frames went by. A program that uses CIA 2's timers itself will see
them changed (their latches are left at `$FFFF`).

## Transcripts

A transcript is a script of commands that sets up the machine, runs the program's routines and
checks what they did: a repeatable test. CBM prg Studio's debugger has them for its own 6510
simulator. Linux64Studio runs them in VICE, so a routine that touches the VIC-II, SID or CIAs can be
tested too. Its commands work here as they're written there.

**File → New → Transcript (tests)…** makes a `.transcript` file with the commands listed at its top.
**Debugger → Run Transcript** (or right-click in it → **Run Transcript**) builds the project and
starts VICE with no program (but with the project's disk image in drive 8, if it writes one, so the
program can load files from it). Once BASIC is READY, the program is put into memory as LOAD would
put it, without being run. Then each line runs in turn. The results stream into **Build Output**: a
tick for a check that passed, an error for one that failed (also marked in the transcript's
margin), and what every other command did. Click a row to go to its line.

```
; does add16 add, and how fast?
set num1 $34 $12
set num2 $01 $00
call add16
check word result = $1235
check cycles = #32

; Glowcave: run to the main loop, then look at the state
run until wait_frame
check $d021 & $0f = 0
```

| Command | What it does |
|---|---|
| `call <routine>` | Calls the routine as JSR would and runs it until it returns. It counts the cycles from its first instruction to its RTS, included, for `check cycles`. The PC goes back to where it was afterwards. |
| `run` / `run until <address>` | Starts the program as typing RUN would (from READY, for a program at `$0801`); with `until`, stops when the PC gets there. |
| `until <address>` | Lets the program carry on until the PC gets there. |
| `goto <address>` | Sets the PC. |
| `a`, `x`, `y`, `sp`, `p`, `pc` `<value>` | Sets a register (`a $20`, `x = #10`). |
| `set <address> <bytes>` | Puts bytes in memory: hex, `#` decimal, `"text"` as screen codes, `'text'` as PETSCII, `<label`/`>label`. |
| `fill <address> <count> <byte>` | Fills memory. |
| `check <what> <op> <value>` | What: a register, a flag (`c`, `z`, `n`, `v`, `i`, `d`), `cycles` (the last call's), `word <address>` (16 bits), or memory (one byte, or several with `=`/`<>`). Ops: `= <> < > <= >=`. `& <mask>` checks some bits: `check $d020 & $0f = 2`. |
| `show [<what> [count]]` (or `watch`) | Shows registers, or memory, in the results. |
| `step [n]`, `stepover [n]` | Runs one instruction (or n), over a JSR with `stepover`. |
| `wait <seconds>` | Lets the program run that long. |
| `joystick <port> <directions>` | On the simulator: what's pressed on joystick 1 or 2 from now on, `up`, `down`, `left`, `right` and `fire` (as many as you like), or `none`. |
| `hold <keys>`, `release [<keys>]` | On the simulator: C64 keys held down from now on, by name (`a`, `space`, `return`, `f1`, `shift`, `ctrl`, `commodore`, `stop`...); `release` on its own lets go of them all. |
| `restore <snapshot>` | Puts the machine back as a snapshot has it: a `.vsf`, or its name in the project's `snapshots` folder (a simulator's on the simulator, VICE's on either). |
| `type "<text>"` | Types keys for the program to read, with `INPUT` or `GET`: listing notation, so letters unshifted, capitals shifted, and `{return}`, `{clear}`, `{f1}` and other codes. Any length (the keyboard buffer takes 10 at a time); it goes on once the program has read them all, so follow it with `wait` before checking the answer. |
| `interrupts on` / `off` | Clears or sets the I flag: off, a call's cycles are its own, with no interrupt counted in them. |
| `timeout <seconds>` | How long a call or `until` may take before it fails (10 s at first). |
| `clearregs`, `resetstack`, `end`, `break` | As in CBM prg Studio. `break` stops the transcript there. |
| `skipkernal on` / `off` | On the simulator, steps over KERNAL calls as if they returned at once (or doesn't). In VICE it isn't needed, since VICE has the real KERNAL. |

Numbers are hex unless written otherwise, as in the debugger: `$20` and `20` are both 32, and `#20`
is 20. A label's name always means the label, even one spelled in hex digits such as `add16`. A label
may be followed by `+n`/`-n`, and C names work with or without cc65's underscore. Comments start
with `;` or `//`.

A few things to know:

* A call's cycles come from CIA 2's timers, set to count every cycle for the length of the call. Its
  control registers are put back afterwards, but its timer latches are left at `$FFFF`.
* Interrupts are on unless turned off, so a KERNAL interrupt during a call is counted in its cycles.
  Use `interrupts off` for a routine's own time.
* The VIC-II's colour registers read their unused top 4 bits as 1: `$D020` set to 2 reads `$F2`. A
  failed check on one says so; check it with `& $0f`.
* `l64test project transcript...` runs transcripts from the command line, printing a line a command.
  Its exit status is the number of failed checks, so it suits a test script or CI.
  `--vice-args="-sounddev dummy"` keeps it quiet.
* **Debugger → Run Transcript Without VICE**, or `l64test --simulate`, runs them on the
  [simulated C64](#debugging-without-vice) instead: no emulator to start, nothing on screen, so it
  suits CI with no display. Calls' cycles are exact, with no timers used, and `wait` is the C64's
  own time. Interrupts happen there too (the raster interrupt and CIA 1's timer), but a transcript
  that tests the rest of the VIC-II, the SID or the CIAs needs VICE, and so does one that loads from
  a disk. The tutorials' transcripts pass on both, but for the disk one's.

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

## Debugging in other tools (.dbg)

Kick Assembler 5's debug dump (`-debugdump`) is a `.dbg` file that tells a debugger which source
line made which bytes, and where each label is. C64 Debugger, RetroDebugger and VS64 read it to
show the source as the program runs. Kick Assembler projects always get one. For a CBM prg Studio
project, switch on **Project Properties → Build → Write a debug dump (.dbg)**, or run
`l64asm game.cbmprj --debugdump` (`--debugdump file.dbg` to name it). It's written next to the
program, with the same name.

It's in Kick Assembler's own format: for the same instructions, the rows are what Kick Assembler
5.25 writes (`tests/asm/test_debugdump.py` runs both). As in Kick Assembler's, a line in a macro
is listed at the macro's own line, not where the macro is used. Source `breakpoint` and `watch`
directives go in its Breakpoints and Watchpoints.

**Debugger → Debug in RetroDebugger / C64 Debugger** builds the project and opens the program in
RetroDebugger (or C64 Debugger, its forerunner) with the debug dump and the labels, so it shows the
source as the program runs. In RetroDebugger the source is in its own window: **C64 → Source code**.
While the program runs, the highlighted line follows the PC; pause it to step through the source. A disk image or cartridge is opened as one. For a CBM prg Studio project
without *Write a debug dump* switched on, the dump is written for it at that moment. A C (cc65)
program gets its labels only: ld65's own `.dbg` is a different format, which these debuggers don't
read. Breakpoints set in Linux64Studio's margin aren't passed on; `breakpoint` directives in the
source are, through the dump.

`tools/install-retrodebugger.sh` downloads the latest RetroDebugger for Linux into
`~/.local/share/linux64studio/RetroDebugger`, where it's found. Or name the program in **Preferences →
General → RetroDebugger / C64 Debugger**, with any extra arguments (`-layout 9` for its source view).
Otherwise the first `retrodebugger`, `RetroDebugger`, `C64Debugger` or `c64debugger` on the PATH is
used. It's started with `-wait 2000 -debuginfo game.dbg -symbols game.vs -prg game.prg -autojmp`.

## Notes on VICE

These are worked around automatically, and were found with VICE 3.7.1:

* After a register is written, VICE runs the next instruction but leaves the PC where it was, so
  that instruction would run twice: set A, step over an `inc counter`, and `counter` went up by 2.
  So after any register edit (or Skip), the debugger puts a `JMP` to the PC in the cassette buffer
  (`$033C`, its three bytes put back afterwards), points the PC at it, and runs to the PC with your
  breakpoints switched off. The JMP is what runs twice, harmlessly, and your next step runs the
  instruction once. Transcripts do the same before a `call`, `goto`, `step` or run. Earlier
  versions of Linux64Studio took an extra hidden step instead, believing VICE ignored it, which ran
  the instruction twice.
* Setting breakpoints at start-up makes VICE stop briefly. Those stops are never shown.
* VICE logs a line each time the monitor lets it carry on. Its log isn't kept (it goes to
  `/dev/null`): when it was kept in a pipe nothing read, a long session filled the pipe after about
  5,000 steps and VICE stopped dead.
* Stepping or continuing from a breakpoint runs that instruction with the breakpoint switched
  off, then switches it back on.
