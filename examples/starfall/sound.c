/* Starfall: sound effects, straight on the SID's registers. */
#include <c64.h>
#include "sound.h"

static unsigned char blip_left;     /* frames before each effect stops */
static unsigned char crash_left;

void sound_init(void)
{
    SID.amp = 0x0F;                 /* full volume, no filter */
    SID.v1.ad = 0x09;               /* voice 1: blips */
    SID.v1.sr = 0x00;
    SID.v3.ad = 0x0A;               /* voice 3: the crash */
    SID.v3.sr = 0x00;
}

void sound_blip(void)
{
    SID.v1.freq = 0x2000;
    SID.v1.ctrl = 0x11;             /* triangle, gate on */
    blip_left = 4;
}

void sound_crash(void)
{
    SID.v3.freq = 0x0800;
    SID.v3.ctrl = 0x81;             /* noise, gate on */
    crash_left = 30;
}

void sound_update(void)
{
    if (blip_left && --blip_left == 0) {
        SID.v1.ctrl = 0x10;         /* gate off: the release runs */
    }
    if (crash_left) {
        SID.v3.freq -= 0x30;        /* falling pitch */
        if (--crash_left == 0) {
            SID.v3.ctrl = 0x80;
        }
    }
}
