# Music and sound effects

The SID tool brings C64 music into a project in three ways: SID files, GoatTracker songs and
GoatTracker sound effects. Songs and sound effects come from
[GoatTracker GTK Edition and SidMonkey](https://github.com/robcowell/goattracker). Linux64Studio
runs their command-line tools (`gt2reloc`, `ins2snd2`) and opens their editors (`goattrk2`,
`sidmonkey`). It finds them in the folder set in **Preferences → Music**, then in
`~/goattracker/linux`, then on the `PATH`. Playback uses VICE's `vsid`.

## SID files (.sid)

Opening a `.sid` shows its header: name, author, memory range, init and play addresses, tunes,
PAL/NTSC and SID model. You can play any tune in `vsid`, or extract the music as `.bin` (to
`incbin` at the load address) or `.prg`. The page also shows the code to include and play it:

```
*=$1000
        incbin Calypso_Bar.bin

        lda #0          ; tune number - 1
        jsr $1000       ; init, once
        ...
        jsr $1003       ; play, once a frame (e.g. in a raster interrupt)
```

In Kick Assembler projects (Retro Game Dev Vol 2) it shows the book's way instead:
`.import binary "Calypso_Bar.sid", $7E`, which skips the header and load address.

## GoatTracker songs (.sng)

Opening a `.sng` shows the song, with **Edit in SidMonkey** and **Edit in GoatTracker** (the
song opens in that program; save there) and **Play** (packed with your settings, then played
in `vsid`).

Switch on **Pack on every build** and every build first runs `gt2reloc`, so the code can
include the result. The settings are kept in the project:

* **Output**: `.bin` (data only), `.prg` (with load address) or `.sid`. The format follows the extension.
* **Player address**: where the playroutine goes. It must start a page, e.g. `1000`.
* **Zeropage**: two consecutive bytes the player may use.
* **Sound effect support**: adds an effect entry point at `start+6`, as Vol 2's games use.
* **Volume change support**, **NTSC timing**.

The page shows the entry points for those settings:

| Call | Address | Registers |
|---|---|---|
| Init | start | A = subtune, from 0 |
| Play (each frame) | start+3 | |
| Sound effect | start+6 | A/Y = effect address, X = 0, 7 or 14 (voice 1–3) |
| Volume | start+6, or +9 with sound effects | A = 0–15 |

**Compose in SidMonkey** and **Open GoatTracker** in the main menu start those programs in the
project folder.

## Sound effects (.ins)

A GoatTracker instrument can be a sound effect for a song packed with sound effect support.
Switch on **Convert on every build** and `ins2snd2` turns it into data before each build: as
`byte` lines (`.asm`, in the project's syntax, with a label) or as raw `.bin`. `ins2snd2`'s own
source output is DASM syntax, so Linux64Studio writes the byte lines itself. Waveforms above
$81, relative notes, pulse modulation and filters don't carry over into sound effects.

## Command line

```sh
l64sid info tune.sid
l64sid extract tune.sid -o music.bin
l64sid pack song.sng music.bin --address 1000 --zeropage fc --sfx
l64sid sfx gun.ins gun.asm --label gunSound
```

## Checks

`tests/test_sid.py` reads the book's `.sid` files, packs real songs with `gt2reloc` (checking
the player's jump table and the SID header), converts sound effects with `ins2snd2`, and builds
a project whose code includes music that only exists once the build has packed it. A program
built that way, with a raster interrupt calling play, ran in VICE with its sound recorded to a
WAV file, and the music was there.

`gt2reloc` doesn't report a missing song file as an error: it packs an empty song instead. So
Linux64Studio checks the song exists before packing.
