# Starfall

A small C game for the C64, built with cc65 in Linux64Studio: dodge the falling rocks, catch the star
for 10 points. Joystick in port 2.

Open `starfall.l64proj` and press Ctrl+F5. To play it with the keyboard, set Preferences → Emulator →
**Joystick in port 2** to the keypad (4 and 6 move, 0 fires).

What it uses:

* `main.c`: the game: sprites through the VIC-II's registers, the joystick from CIA 1, the
  raster line for timing, and the VIC-II's sprite collision register.
* `sound.c`: sound effects straight on the SID.
* `sprites.spt`: the ship, a rock and the star, drawn in the sprite editor. Saving it there writes
  `sprites.bin` (its linked export), which `sprites.s` (ca65) brings in with `.incbin`; the game
  copies the three sprites to the cassette buffer ($0340), where the VIC-II can see them.
* The build writes `build/starfall.prg` and a disk image, `build/starfall.d64`.
