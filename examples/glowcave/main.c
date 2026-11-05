/* Glowcave: gather every gem in the cave, and keep away from the bats. Joystick in port 2.
   A Linux64Studio example of a C game built with cc65, with its graphics and music at fixed
   addresses and a raster interrupt of its own. */
#include <6502.h>
#include <c64.h>
#include <conio.h>
#include <stdlib.h>
#include <string.h>
#include "game.h"
#include "music.h"

#define SCREEN      ((unsigned char *)0x0400)
#define COLOUR_RAM  ((unsigned char *)0xD800)
#define SPRITE_PTRS ((unsigned char *)0x07F8)
#define JOY2        (CIA1.pra)

enum { STOP, UP, DOWN, LEFT, RIGHT };
static const signed char dir_x[5] = { 0, 0, 0, -1, 1 };
static const signed char dir_y[5] = { 0, -1, 1, 0, 0 };
static const unsigned char reverse[5] = { STOP, DOWN, UP, RIGHT, LEFT };

struct mover {
    unsigned char cx, cy;       /* the cell it's in (or leaving) */
    unsigned char dir;
    unsigned char step;         /* 0-7: pixels on the way to the next cell */
};

enum state { TITLE, PLAYING, CAUGHT, CLEARED, GAME_OVER };

/* where everyone starts, in each cave */
static const unsigned char player_start[2] = { 19, 21 };
static const unsigned char bat_start[CAVES][BATS][2] = {
    { { 16, 10 }, { 19, 10 }, { 23, 10 } },
    { { 12, 9 }, { 19, 9 }, { 27, 9 } }
};
static const unsigned char wall_colour[CAVES] = { COLOR_BLUE, COLOR_PURPLE };

struct mover player;
struct mover bats[BATS];
unsigned int score;
unsigned char lives;
unsigned char level;            /* from 0; the caves take turns, and the bats speed up */
unsigned int gems_left;
enum state state;
unsigned char frames;
unsigned char wait;             /* frames left in CAUGHT and CLEARED */
unsigned char demo;             /* the game playing itself, from the title */
unsigned int title_frames;
unsigned char bats_asleep;      /* frames before the bats start moving: a head start */

static unsigned char *row_addr[CAVE_ROWS];

/* ------------------------------------------------------------------ the raster interrupt */
static unsigned char irq_stack[96];
static volatile unsigned char frame_ready;
static unsigned char at_top = 1;

/* Twice a frame: at line 0 the status bar's ROM characters, the music and the frame tick; at
   SPLIT_LINE the cave's characters. */
static unsigned char raster(void)
{
    if (!(VIC.irr & 0x01)) {
        return IRQ_NOT_HANDLED;
    }
    VIC.irr = 0x01;
    if (at_top) {
        VIC.addr = D018_STATUS;
        music_play();
        frame_ready = 1;
        VIC.rasterline = SPLIT_LINE;
        at_top = 0;
    } else {
        VIC.addr = D018_CAVE;
        VIC.rasterline = 0;
        at_top = 1;
    }
    return IRQ_HANDLED;
}

static void start_interrupt(void)
{
    SEI();
    set_irq(raster, irq_stack, sizeof irq_stack);
    CIA1.icr = 0x7F;                    /* the CIA timer's interrupt off: the raster's replaces it */
    (void)CIA1.icr;
    VIC.ctrl1 &= 0x7F;                  /* line 0 (bit 8 clear) */
    VIC.rasterline = 0;
    VIC.imr = 0x01;
    VIC.irr = 0x01;
    CLI();
}

static void wait_frame(void)
{
    while (!frame_ready) {
    }
    frame_ready = 0;
}

static void sound(const unsigned char *effect)
{
    music_sfx(effect, 3);
}

/* ------------------------------------------------------------------ the screen */
static void status(void)
{
    textcolor(COLOR_WHITE);
    gotoxy(0, 0);
    cprintf("glowcave  score %05u  lives %u  cave %u", score, lives, level + 1);
}

static void message(const char *text)
{
    unsigned char x;

    gotoxy(0, 1);
    for (x = 0; x < 40; ++x) {
        cputc(' ');
    }
    textcolor(COLOR_YELLOW);
    cputsxy((40 - strlen(text)) / 2, 1, text);
}

static void draw_cave(void)
{
    const char * const *rows = caves[level % CAVES];
    unsigned char x, y;
    unsigned char *s, *c;
    const char *r;

    gems_left = 0;
    for (y = 0; y < CAVE_ROWS; ++y) {
        r = rows[y];
        s = row_addr[y];
        c = s - SCREEN + COLOUR_RAM;
        for (x = 0; x < CAVE_COLS; ++x) {
            if (r[x] == '#') {
                s[x] = CH_WALL;
                c[x] = wall_colour[level % CAVES];
            } else if (r[x] == '.') {
                s[x] = CH_GEM;
                c[x] = COLOR_YELLOW;
                ++gems_left;
            } else {
                s[x] = CH_FLOOR;
            }
        }
    }
}

static void put_sprite(unsigned char n, const struct mover *m)
{
    unsigned int x = 24 + m->cx * 8 + dir_x[m->dir] * m->step;
    unsigned char y = 50 + (m->cy + TOP_ROWS) * 8 + dir_y[m->dir] * m->step;

    VIC.spr_pos[n].x = (unsigned char)x;
    if (x > 255) {
        VIC.spr_hi_x |= 1 << n;
    } else {
        VIC.spr_hi_x &= ~(1 << n);
    }
    VIC.spr_pos[n].y = y;
}

/* ------------------------------------------------------------------ moving */
static unsigned char open(const struct mover *m, unsigned char dir)
{
    return row_addr[m->cy + dir_y[dir]][m->cx + dir_x[dir]] != CH_WALL;
}

static void eat(void)
{
    unsigned char *cell = row_addr[player.cy] + player.cx;

    if (*cell == CH_GEM) {
        *cell = CH_FLOOR;
        score += 10;
        --gems_left;
        sound(sfx_gem);
        status();
    }
}

static unsigned char stick(void)
{
    unsigned char joy = ~JOY2;          /* (pressed is 0) */

    if (joy & 0x01) {
        return UP;
    }
    if (joy & 0x02) {
        return DOWN;
    }
    if (joy & 0x04) {
        return LEFT;
    }
    if (joy & 0x08) {
        return RIGHT;
    }
    return STOP;
}

/* The demo's player: at a junction, towards a gem next door if there is one, else anywhere but
   back the way it came. */
static unsigned char demo_stick(void)
{
    unsigned char d, n = 0;
    unsigned char options[4];

    for (d = UP; d <= RIGHT; ++d) {
        if (d != reverse[player.dir] && open(&player, d)) {
            if (row_addr[player.cy + dir_y[d]][player.cx + dir_x[d]] == CH_GEM) {
                return d;
            }
            options[n++] = d;
        }
    }
    return n ? options[rand() % n] : reverse[player.dir];
}

static void move_player(void)
{
    unsigned char want;

    if (player.step == 0) {
        want = demo ? demo_stick() : stick();
        if (want != STOP && open(&player, want)) {
            player.dir = want;
        } else if (player.dir != STOP && !open(&player, player.dir)) {
            player.dir = STOP;
        }
    }
    if (player.dir != STOP && ++player.step == 8) {
        player.cx += dir_x[player.dir];
        player.cy += dir_y[player.dir];
        player.step = 0;
        eat();
    }
    put_sprite(0, &player);
}

/* At a junction a bat goes towards the player half the time, and anywhere it can the rest; it
   only turns back at a dead end. */
static void steer(struct mover *b)
{
    unsigned char options[4];
    unsigned char n = 0, d, best = STOP;
    int dx = (int)player.cx - b->cx, dy = (int)player.cy - b->cy;

    for (d = UP; d <= RIGHT; ++d) {
        if (d != reverse[b->dir] && open(b, d)) {
            options[n++] = d;
            if ((d == LEFT && dx < 0) || (d == RIGHT && dx > 0) || (d == UP && dy < 0) || (d == DOWN && dy > 0)) {
                best = d;
            }
        }
    }
    if (n == 0) {
        b->dir = reverse[b->dir];
    } else if (best != STOP && (rand() & 1)) {
        b->dir = best;
    } else {
        b->dir = options[rand() % n];
    }
}

static void move_bats(void)
{
    unsigned char i;
    struct mover *b;
    /* cave 1: three frames in four; after that, every frame */
    unsigned char moving = level > 0 || (frames & 3) != 0;

    if (bats_asleep) {
        --bats_asleep;
        moving = 0;
    }

    for (i = 0; i < BATS; ++i) {
        b = &bats[i];
        if (moving) {
            if (b->step == 0) {
                steer(b);
            }
            if (++b->step == 8) {
                b->cx += dir_x[b->dir];
                b->cy += dir_y[b->dir];
                b->step = 0;
            }
        }
        put_sprite(1 + i, b);
        SPRITE_PTRS[1 + i] = (frames & 8) ? BLOCK_BAT_UP : BLOCK_BAT_DOWN;
    }
}

/* ------------------------------------------------------------------ the game */
static void place_everyone(void)
{
    unsigned char i;

    player.cx = player_start[0];
    player.cy = player_start[1];
    player.dir = STOP;
    player.step = 0;
    for (i = 0; i < BATS; ++i) {
        bats[i].cx = bat_start[level % CAVES][i][0];
        bats[i].cy = bat_start[level % CAVES][i][1];
        bats[i].dir = STOP;
        bats[i].step = 0;
        put_sprite(1 + i, &bats[i]);
    }
    put_sprite(0, &player);
    VIC.spr0_color = COLOR_YELLOW;
    bats_asleep = 100;
    i = VIC.spr_coll;                   /* reading clears it */
}

static void new_cave(void)
{
    draw_cave();
    row_addr[player_start[1]][player_start[0]] = CH_FLOOR;     /* (no gem under the start) */
    --gems_left;
    place_everyone();
    status();
    message("");
}

static void start_game(void)
{
    score = 0;
    lives = 3;
    level = 0;
    new_cave();
    VIC.spr_ena = 0x0F;
    state = PLAYING;
}

static void title(void)
{
    demo = 0;
    level = 0;
    VIC.spr_ena = 0;
    draw_cave();
    status();
    message("joystick in port 2: press fire");
    title_frames = 0;
    state = TITLE;
}

static void check_bats(void)
{
    unsigned char hit = VIC.spr_coll;   /* which sprites touched (and clear it) */

    if ((hit & 0x01) && (hit & 0x0E)) {
        sound(sfx_caught);
        if (demo) {
            title();
            return;
        }
        --lives;
        status();
        message(lives ? "caught!" : "game over");
        wait = 90;
        state = lives ? CAUGHT : GAME_OVER;
    }
}

static unsigned char fire(void)
{
    return !(JOY2 & 0x10);
}

static void setup(void)
{
    unsigned char i;

    for (i = 0; i < CAVE_ROWS; ++i) {
        row_addr[i] = SCREEN + (i + TOP_ROWS) * 40;
    }
    VIC.bordercolor = COLOR_BLACK;
    VIC.bgcolor0 = COLOR_BLACK;
    clrscr();
    SPRITE_PTRS[0] = BLOCK_PLAYER;
    for (i = 1; i <= BATS; ++i) {
        (&VIC.spr0_color)[i] = COLOR_PURPLE;
        SPRITE_PTRS[i] = BLOCK_BAT_UP;
    }
    music_init(0);
    start_interrupt();
}

int main(void)
{
    setup();
    title();
    for (;;) {
        wait_frame();
        ++frames;
        switch (state) {
        case TITLE:
            if (fire()) {
                start_game();
            } else if (++title_frames == 300) {         /* six seconds: a demo */
                start_game();
                demo = 1;
                message("demo: press fire to play");
            }
            break;
        case PLAYING:
            if (demo && fire()) {
                demo = 0;
                start_game();
                break;
            }
            move_player();
            move_bats();
            check_bats();
            if (state == PLAYING && gems_left == 0) {
                sound(sfx_clear);
                message("cave clear!");
                wait = 120;
                state = CLEARED;
            }
            break;
        case CAUGHT:
            VIC.spr0_color = (frames & 4) ? COLOR_RED : COLOR_YELLOW;
            if (--wait == 0) {
                place_everyone();
                message("");
                state = PLAYING;
            }
            break;
        case CLEARED:
            if (demo) {
                title();
            } else if (--wait == 0) {
                ++level;
                new_cave();
                state = PLAYING;
            }
            break;
        case GAME_OVER:
            VIC.spr0_color = (frames & 4) ? COLOR_RED : COLOR_YELLOW;
            if (wait) {
                --wait;
            } else if (fire()) {
                start_game();
            }
            break;
        }
    }
    return 0;
}
