# Glowcave

A C game for the C64, built with cc65 in Linux64Studio: gather every gem in the cave, and keep away
from the bats. Joystick in port 2. Leave the title screen for six seconds and the game plays itself.

Open `glowcave.l64proj` and press Ctrl+F5. To play it with the keyboard, set Preferences → Emulator →
**Joystick in port 2** to the keypad (8 4 6 2 move, 0 fires).

What it uses:

* **Fixed areas** (Project → Properties → Build → Memory layout): `MUSIC` at `$1000`, `SPRITES` at
  `$3600` and `CHARSET` at `$3800`. The program is linked round them, starting at `$4000`, and the
  Memory Viewer shows what's in each.
* `chars.cst` and `sprites.spt`, drawn in the character and sprite editors. Saving them writes
  `chars.bin` and `sprites.bin` (their linked exports), and `gfx.s` puts each in its area with
  `.incbin`, where the VIC-II sees it.
* A raster interrupt in C (`set_irq` from `<6502.h>`). It runs twice a frame. At line 0 it switches
  to the ROM characters for the status bar, plays the music and ticks the frame. At line 64 it
  switches to the cave's own characters.
* `music.s` and `music.h`: the music, with C functions to start it and to play sound effects
  (`sfx.c`, written in GoatTracker's sound effect format). The game plays the music from its own
  interrupt, so it calls `music_play()` instead of `music_start()`.
* `maze.c`: the two caves, as text.

## The music

The project starts with a silent stand-in (`placeholder.bin`), so it builds and runs without a song.
To put in a real one:

1. Make a song in SidMonkey or GoatTracker (Tools → Music), and save it in the project folder.
2. Open the `.sng`. Leave the player address at `1000`, and switch on **Sound effect support**: the
   game plays its effects through the player.
3. Under **Use it from C**, press **Add to Project**. That replaces `music.s` and `music.h`, resizes the
   `MUSIC` area to fit the song, and packs the song before every build.
4. Delete `placeholder.bin`.

Without sound effect support, `music.h` has no `music_sfx`, and the build stops with an error saying so.
