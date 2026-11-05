/* Starfall: sound effects on the SID. */
#ifndef SOUND_H
#define SOUND_H

void sound_init(void);
void sound_blip(void);          /* a point scored */
void sound_crash(void);         /* the ship's hit */
void sound_update(void);        /* once a frame: ends the effects */

#endif
