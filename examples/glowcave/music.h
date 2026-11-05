/* music.h: a silent stand-in until the real song is added, made by Linux64Studio. The data is at $1000; the code in music.s. */
#ifndef MUSIC_H
#define MUSIC_H

void __fastcall__ music_init(unsigned char tune);    /* once, first: the tune, from 0 */
void music_start(void);    /* play it once a frame, from a raster interrupt */
void music_stop(void);     /* stop playing, and silence the SID */
void music_play(void);     /* or call this once a frame yourself, instead of music_start */
void __fastcall__ music_sfx(const unsigned char *effect, unsigned char voice);    /* voice 1-3 */

#endif
