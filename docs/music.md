# Music and sound effects

The SID tool brings C64 music into a project in three ways: SID files, GoatTracker songs and
GoatTracker sound effects. Alongside them, the **SID Designer** (below) sets up the SID chip's
voices and filter by hand and writes the code for them, as CBM prg Studio's SID tool does. Songs and sound effects come from
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

## SID Designer

**Menu → SID Designer** opens CBM prg Studio's SID tool, in two tabs.

**Voices & Filter**: each of the three voices has a note and octave (shown as Hz and as the
frequency register value), waveforms (triangle, sawtooth, pulse, noise), ring modulation, sync,
the test bit, the pulse width, the ADSR envelope (with how long each setting takes) and whether
it goes through the filter. Below them are the filter cutoff, resonance, low/band/high pass,
voice 3 off and the volume, and a line showing all 25 register values. **Copy** copies one voice
to another, with or without its note. Choose PAL or NTSC to set the note frequencies.

To hear a voice, toggle its ▶ button, or hold **1**, **2** or **3**. A voice needs a waveform
before it makes any sound, and none is set at first. **Keyboard** shows a two-octave piano:
click and hold a key, or use the PC keys as CBM prg Studio maps them (Tab Q W E R T Y U I O P [
] Return for the white keys, 1 2 4 5 6 8 9 - = Backspace for the black ones). Choose the voice
and the base octave on the left. You can change the settings while the piano is open.

The sound is VICE's reSID, so it is the real chip's sound. The first time you play, the designer
starts VICE's `vsid` (minimised, with no tune loaded) and writes the registers into it through
VICE's binary monitor. Every change you make is heard straight away. **SID** picks the 6581 or
the 8580. **Silence** gates every voice off. vsid closes with the designer's tab.

**Code Generation** (the code updates as you change things):

* **Include**: any of the three voices, the filter settings ($D415-$D417), and the filter mode
  and volume ($D418).
* **Source type**: BASIC or assembler. BASIC comes out in the BASIC editor's listing notation
  (lower case keywords) from the start line, in steps. Assembler is in the project's syntax
  (CBM prg Studio or Kick Assembler) and loads A only when the value changes.
* **Use a variable name** (`10 vb=54272`, `poke vb+1,10`, or `SID = $D400` in assembler; type
  your own name) or **Use addresses** (`poke 54273,10`, `sta $D401`).
* **Add comments** says what each value does. **Clear SID chip first** zeroes all 25 registers.
  **Start the sound** writes each voice's control register last, with the gate bit set.

**Copy** puts the code on the clipboard, and **Insert into Editor** puts it on a new line at the
cursor of the last source file you used.

**Save** and **Load** keep the settings in a `.l64sid` file (JSON). These files open in the
designer from the project's Music group. CBM prg Studio saves its own `.stf` files, but their
format isn't documented, so Linux64Studio doesn't read them. The settings are only a few
numbers, though, and are quick to set again by hand.

Notes are equal-tempered with A-4 at 440 Hz, and octave 4 starts at middle C, as in GoatTracker.
The frequency register is Hz × 16777216 / clock, with a clock of 985248 Hz (PAL) or 1022727 Hz
(NTSC).

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

`tests/test_sid_designer.py` checks the register values, the settings files and the code
generator, and compares the note frequencies with GoatTracker's table (within 0.05%). Its
opt-in VICE tests (`L64S_VICE_TESTS=1`) run the generated BASIC and the generated assembler in
`x64sc` and read the SID registers back, and write registers into a live `vsid`. The designer was
also driven through the GUI with vsid recording to a WAV file: the toggled voice and the piano
key each sounded with their attack, decay, sustain and release.
