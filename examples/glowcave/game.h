/* Glowcave: what the game's files share. */
#ifndef GAME_H
#define GAME_H

#define CAVES       2           /* maze.c */
#define CAVE_ROWS   23          /* screen rows 2-24 (rows 0-1 are the status bar) */
#define CAVE_COLS   40
#define TOP_ROWS    2

#define BATS        3           /* sprites 1-3; the player is sprite 0 */

/* the custom characters (chars.cst, at $3800 in the CHARSET fixed area) */
#define CH_FLOOR    0
#define CH_WALL     1
#define CH_GEM      2

/* sprite blocks: sprites.spt is at $3600 in the SPRITES fixed area, $3600 / 64 = 216 */
#define BLOCK_PLAYER    216
#define BLOCK_BAT_UP    217
#define BLOCK_BAT_DOWN  218

/* $D018: the screen at $0400 with the ROM's characters (the status bar) or ours at $3800 */
#define D018_STATUS 0x14
#define D018_CAVE   0x1E
#define SPLIT_LINE  64          /* the raster line where the cave's characters take over */

extern const char * const caves[CAVES][CAVE_ROWS];

/* sfx.c: sound effects in GoatTracker's format, played by the music's player */
extern const unsigned char sfx_gem[];
extern const unsigned char sfx_caught[];
extern const unsigned char sfx_clear[];

#endif
