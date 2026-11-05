/* Starfall: what the game's files share. */
#ifndef GAME_H
#define GAME_H

#define ROCKS       3           /* rocks falling at once (sprites 1-3) */
#define STAR_SPRITE 4           /* the bonus star */

#define SHIP_Y      229         /* the ship's row (sprite Y) */
#define SHIP_MIN_X  24
#define SHIP_MAX_X  320
#define TOP_Y       30          /* where rocks start */
#define BOTTOM_Y    250         /* where they leave the screen */

/* sprite blocks in the cassette buffer ($0340-$03FF), which the VIC-II sees in bank 0 */
#define BLOCK_SHIP  13
#define BLOCK_ROCK  14
#define BLOCK_STAR  15

enum state { TITLE, PLAYING, GAME_OVER };

struct rock {
    unsigned int  x;            /* 0-343: sprite X, 9 bits */
    unsigned char y;
    unsigned char speed;        /* pixels a frame */
};

extern struct rock rocks[ROCKS];
extern unsigned int score;
extern unsigned int best;

#endif
