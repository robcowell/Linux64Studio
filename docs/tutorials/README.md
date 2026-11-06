# Tutorials

Fifteen short tutorials to get started, each ten or fifteen minutes long. Each has a finished project in
`examples/tutorials/` to compare with yours. In Linux64Studio, **Help → Tutorials** shows them
beside your work, with a button that opens a copy of the example project.

1. [Your first BASIC program](1-basic.md): a number-guessing game. Typing BASIC, building and
   running it in VICE, and the keyword help.
2. [Your first assembler program](2-assembler.md): a flashing border. The BASIC SYS line that
   starts machine code, building, and debugging with breakpoints, steps and the cycle counter.
3. [Sprites](3-sprites.md): a ball drawn in the sprite editor, moving across the screen.
4. [Testing with a transcript](4-transcripts.md): checking that a routine works, and timing it,
   from the IDE and from the command line.
5. [C with cc65](5-c.md): a C program, stepped through line by line, with its variables.
6. [Characters and a screen](6-screen.md): a character drawn in the character set editor, a screen
   of it in the screen designer, and a program that shows it.
7. [Music](7-music.md): a GoatTracker song packed on every build and played from a raster interrupt.
8. [A game on a disk](8-disk.md): two programs on one disk image, the intro loading the game with the
   KERNAL.
9. [Finding what's slow](9-profiler.md): the profiler and routine timing, to make a routine twice as
   fast.
10. [Debugging without VICE](10-simulator.md): the simulated C64, for debugging and for tests that
    run without a screen.
11. [Raster interrupts](11-raster.md): a screen split into two colours by interrupts from the VIC-II.
12. [A scrolling message](12-scroll.md): text gliding across the screen a pixel at a time.
13. [Moving with the joystick](13-joystick.md): a ball moved with joystick 2, and its controls
    tested by a transcript that pushes the joystick.
14. [A sound effect](14-sound.md): a bang designed in the SID Designer, played on a key.
15. [Kick Assembler](15-kickass.md): colour bars written with Kick Assembler, the assembler of the
    books' second volume, and debugged line by line.

You'll need VICE for running and debugging: `sudo apt install vice`. The C tutorial also needs
cc65: `sudo apt install cc65`, the music tutorial GoatTracker GTK Edition's tools
([music](../music.md)), and the Kick Assembler one Java and Kick Assembler (it says how).

Once you're done, the Retro Game Dev books carry on from here. Their projects open as they are:
open a chapter's `.cbmprj` with **File → Open Project**.
