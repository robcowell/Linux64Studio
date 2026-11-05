/* Glowcave: sound effects, in GoatTracker's sound effect format (its readme, 6.3): attack/decay,
   sustain/release, pulse width (nybbles swapped), then a note ($82-$DF, D-0 to B-7) for each
   frame, each optionally followed by a waveform ($11 triangle, $41 pulse, $81 noise, with the gate
   bit), and $00 to end. The player has to be packed with sound effect support (music_sfx). An
   effect higher in memory isn't interrupted by one lower down, so the last here wins. */
#include "game.h"

const unsigned char sfx_gem[] = {
    0x06, 0x00, 0x08,
    0xBC, 0x41, 0xC0, 0xC3, 0xC8,           /* C-5 E-5 G-5 C-6, pulse */
    0x00
};

const unsigned char sfx_clear[] = {
    0x08, 0x00, 0x08,
    0xB0, 0x11, 0xB0, 0xB4, 0xB4, 0xB7, 0xB7, 0xBC, 0xBC,     /* C-4 up to C-6, triangle */
    0xC0, 0xC0, 0xC3, 0xC3, 0xC8, 0xC8, 0xC8, 0xC8,
    0x00
};

const unsigned char sfx_caught[] = {
    0x0A, 0x00, 0x08,
    0xC8, 0x81, 0xC4, 0xC0, 0xBC, 0xB8, 0xB4, 0xB0,         /* falling noise */
    0xAC, 0xA8, 0xA4, 0xA0, 0x9C, 0x98,
    0x00
};
