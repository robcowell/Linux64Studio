/* Score: adds up a score in a function, and shows it.
   Tutorial 5 (docs/tutorials/5-c.md) builds it, steps through it by C line and
   watches its variables. */
#include <conio.h>

#define BORDER (*(unsigned char *)0xD020)

static unsigned int score;

static void add_points(unsigned char points)
{
    score += points;
}

int main(void)
{
    unsigned char i;

    clrscr();
    cputs("score:");
    for (i = 1; i <= 10; ++i) {
        add_points(i);
        gotoxy(7, 0);
        cprintf("%u", score);
        BORDER = i;
    }
    cputs("\r\npress a key.");
    while (!kbhit()) {
    }
    return 0;
}
