/* Starfall: dodge the falling rocks, catch the star for points.
   Joystick in port 2. A Linux64Studio example of a C game built with cc65. */
#include <c64.h>
#include <conio.h>
#include <stdlib.h>
#include <string.h>
#include "game.h"
#include "sound.h"

#define SCREEN      ((unsigned char *)0x0400)
#define COLOUR_RAM  ((unsigned char *)0xD800)
#define SPRITE_PTRS ((unsigned char *)0x07F8)
#define SPRITE_MEM  ((unsigned char *)0x0340)
#define SPR_X(n)    (*(unsigned char *)(0xD000 + 2 * (n)))
#define SPR_Y(n)    (*(unsigned char *)(0xD001 + 2 * (n)))
#define SPR_COL(n)  (*(unsigned char *)(0xD027 + (n)))
#define JOY2        (*(unsigned char *)0xDC00)

#define STICK_LEFT    0x04
#define STICK_RIGHT   0x08
#define STICK_FIRE    0x10

extern const unsigned char sprite_data[];      /* sprites.s */

struct rock rocks[ROCKS];
unsigned int score;
unsigned int best;
unsigned int ship_x;
unsigned int star_x;
unsigned char star_y;
enum state state;
unsigned char frames;           /* counts up every frame */

/* ------------------------------------------------------------------ the screen */
static void wait_frame(void)
{
    while (VIC.rasterline != 250) {
    }
    while (VIC.rasterline == 250) {
    }
}

static void put_sprite(unsigned char n, unsigned int x, unsigned char y)
{
    SPR_X(n) = (unsigned char)x;
    if (x > 255) {
        VIC.spr_hi_x |= 1 << n;
    } else {
        VIC.spr_hi_x &= ~(1 << n);
    }
    SPR_Y(n) = y;
}

static void show_score(void)
{
    gotoxy(1, 0);
    cprintf("score %5u   best %5u", score, best);
}

static void setup(void)
{
    unsigned char i;

    memcpy(SPRITE_MEM, sprite_data, 3 * 64);
    VIC.bordercolor = COLOR_BLACK;
    VIC.bgcolor0 = COLOR_BLACK;
    SPRITE_PTRS[0] = BLOCK_SHIP;
    SPR_COL(0) = COLOR_CYAN;
    for (i = 1; i <= ROCKS; ++i) {
        SPRITE_PTRS[i] = BLOCK_ROCK;
        SPR_COL(i) = COLOR_BROWN;
    }
    SPRITE_PTRS[STAR_SPRITE] = BLOCK_STAR;
    SPR_COL(STAR_SPRITE) = COLOR_YELLOW;
    sound_init();
}

/* ------------------------------------------------------------------ the game */
static void new_rock(struct rock *r)
{
    r->x = SHIP_MIN_X + rand() % (SHIP_MAX_X - SHIP_MIN_X);
    r->y = TOP_Y;
    r->speed = 1 + rand() % (2 + score / 20);
}

static void new_star(void)
{
    star_x = SHIP_MIN_X + rand() % (SHIP_MAX_X - SHIP_MIN_X);
    star_y = TOP_Y;
}

static void start_game(void)
{
    unsigned char i;

    clrscr();
    textcolor(COLOR_WHITE);
    score = 0;
    ship_x = (SHIP_MIN_X + SHIP_MAX_X) / 2;
    for (i = 0; i < ROCKS; ++i) {
        new_rock(&rocks[i]);
        rocks[i].y -= i * 70;               /* spread them out */
    }
    new_star();
    VIC.spr_ena = 0x1F;                     /* the ship, the rocks and the star */
    i = VIC.spr_coll;                       /* reading clears it */
    show_score();
    state = PLAYING;
}

static void move_ship(void)
{
    unsigned char joy = ~JOY2;              /* (pressed is 0) */

    if ((joy & STICK_LEFT) && ship_x > SHIP_MIN_X) {
        ship_x -= 2;
    }
    if ((joy & STICK_RIGHT) && ship_x < SHIP_MAX_X) {
        ship_x += 2;
    }
    put_sprite(0, ship_x, SHIP_Y);
}

static void move_rocks(void)
{
    unsigned char i;
    struct rock *r;

    for (i = 0; i < ROCKS; ++i) {
        r = &rocks[i];
        r->y += r->speed;
        if (r->y >= BOTTOM_Y) {
            new_rock(r);
            ++score;
            show_score();
        }
        put_sprite(1 + i, r->x, r->y);
    }
}

static void move_star(void)
{
    star_y += 1;
    if (star_y >= BOTTOM_Y) {
        new_star();
    }
    put_sprite(STAR_SPRITE, star_x, star_y);
}

static void check_hits(void)
{
    unsigned char hit = VIC.spr_coll;       /* which sprites touched (and clear it) */

    if (!(hit & 0x01)) {
        return;                             /* nothing touched the ship */
    }
    if (hit & (1 << STAR_SPRITE)) {
        score += 10;
        sound_blip();
        show_score();
        new_star();
    }
    if (hit & 0x0E) {                       /* a rock */
        sound_crash();
        state = GAME_OVER;
    }
}

static void title(void)
{
    clrscr();
    VIC.spr_ena = 0;
    textcolor(COLOR_YELLOW);
    gotoxy(15, 8);
    cputs("starfall");
    textcolor(COLOR_GRAY3);
    gotoxy(6, 12);
    cputs("dodge the rocks, catch the star");
    gotoxy(8, 14);
    cputs("joystick in port 2: fire");
    if (best) {
        gotoxy(13, 18);
        cprintf("best score %u", best);
    }
    while (!(~JOY2 & STICK_FIRE)) {
        rand();                             /* (stirs the random numbers while waiting) */
    }
    start_game();
}

static void game_over(void)
{
    unsigned char wait;

    if (score > best) {
        best = score;
    }
    show_score();
    textcolor(COLOR_LIGHTRED);
    gotoxy(15, 12);
    cputs("game over");
    for (wait = 0; wait < 120; ++wait) {    /* two seconds */
        wait_frame();
        sound_update();
    }
    state = TITLE;
}

int main(void)
{
    setup();
    state = TITLE;
    for (;;) {
        switch (state) {
        case TITLE:
            title();
            break;
        case PLAYING:
            wait_frame();
            ++frames;
            move_ship();
            move_rocks();
            move_star();
            check_hits();
            sound_update();
            break;
        case GAME_OVER:
            game_over();
            break;
        }
    }
    return 0;
}
