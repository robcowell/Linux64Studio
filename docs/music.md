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

**Tools → Music → Compose in SidMonkey** and **Open GoatTracker** start those programs in the
project folder.

## Sound effects (.ins)

A GoatTracker instrument can be a sound effect for a song packed with sound effect support.
Switch on **Convert on every build** and `ins2snd2` turns it into data before each build: as
`byte` lines (`.asm`, in the project's syntax, with a label) or as raw `.bin`. `ins2snd2`'s own
source output is DASM syntax, so Linux64Studio writes the byte lines itself. Waveforms above
$81, relative notes, pulse modulation and filters don't carry over into sound effects.

## Music in C projects

In a C project, the SID file and GoatTracker song pages have **Use it from C → Add to Project**. It does
four things:

* makes a fixed area `MUSIC` at the tune's address, the size of the tune rounded up to a page
  ([memory layout](c.md#memory-layout-and-linker-configs)), so the program is linked round it;
* writes `music.s`, which puts the tune's data in that area and has C functions round the player;
* writes `music.h`, which declares them;
* puts `music.s` on the build list.

For a song, it also switches on **Pack on every build**. From then on each build brings `music.s`,
`music.h` and the area up to date with the packing settings: switch on sound effect support, and
`music_sfx` appears. For a `.sid`, it extracts the music as `<name>.bin` beside the project.

```c
#include "music.h"

    music_init(0);          /* the tune, from 0 */
    music_start();          /* plays once a frame from now on */
    ...
    music_sfx(gun, 3);      /* a sound effect on voice 3 (songs packed with sound effect support) */
    music_volume(8);        /* 0-15 (songs packed with volume change support) */
    music_stop();           /* stop, and silence the SID */
```

`music_start` plays the tune from a raster interrupt at line 0, in the border and out of a game's
way. The interrupt goes on to the KERNAL's handler, so the keyboard and the clock still work. It
takes over from the CIA timer's interrupt, so the KERNAL's handler runs 50 times a second on PAL
instead of 60. Call `music_play()` once a frame yourself instead, if the program has its own
interrupt. A tune whose `.sid` has no play address plays itself once `music_init` has started it.

There's one `music.s` per project: adding another tune replaces it. `music.s` and `music.h` say
they were made by Linux64Studio. If you write a `music.s` of your own, Add to Project won't
overwrite it. With a linker config of your own, the area isn't made: the page says which lines to
add to the config instead.

A sound effect (`.ins`) in a C project converts to a C array (output `.c`, the default) or an
exported ca65 table (`.s`), named with the **Label**. Switching on **Convert on every build** puts
the file on the build list. Use it from C with `extern const unsigned char gun[];`.

## SID Designer

**Tools → Music → SID Designer** opens CBM prg Studio's SID tool, in two tabs.

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

**MIDI**: a MIDI keyboard can play the voices, as in CBM prg Studio. Each voice listens on a MIDI
channel (1, 2 and 3 to start with, or Off). A note on that channel plays the voice at that note,
and the gate is held until the key is let go. Each voice plays one note at a time. A second key on
the same channel moves the voice to the new note, and letting go goes back to a key that's still
held. MIDI note 60 (middle C) is C-4. Notes outside C-0 to B-7 are ignored, and so is velocity.
"All notes off" and "all sound off" messages release the voices.

The **MIDI** button shows the input, **Detect Device** and the channels, beside the MIDI monitor
(the last message, and which voice is on which channel). If a device is plugged in when the
designer opens, it connects to it and shows the monitor. Otherwise plug one in and press
**Detect Device**. Detect Device picks the device you used last, or else the first input that
isn't ALSA's "Midi Through" port. Choose another from the list at any time. The channels and the
device are kept in the preferences. Software keyboards that make an ALSA MIDI port (VMPK, for
example) work too. Remember that a voice needs a waveform before it makes a sound. Because vsid
plays the sound, there's a short delay, as with CBM prg Studio's SID emulation.

MIDI needs `python3-mido` and `python3-rtmidi` (see the README's install line). Without them, the
rest of the designer works and the MIDI row says what to install.

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
`x64sc` and read the SID registers back, and write registers into a live `vsid`. `tests/test_sid_midi.py` checks the channel mapping, last-note priority and the monitor text, and
sends a note through a virtual ALSA MIDI port. The designer was
also driven through the GUI with vsid recording to a WAV file: the toggled voice and the piano
key each sounded with their attack, decay, sustain and release. A virtual MIDI keyboard was
also played into the designer, and the SID registers in vsid were read after each message: the
right voice played the right note, went back to a held key, and released.
