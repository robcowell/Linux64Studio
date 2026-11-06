// Bars: colour bars and a message, in Kick Assembler.

.const SCREEN = $0400
.const COLOURS = $d800
.const BORDER = $d020
.const BACKGROUND = $d021
.const CLEAR = $e544            // the KERNAL's screen clear

// Copy a piece of text to the screen (a macro: its code is put in where it's used)
.macro copyText(text, length, where) {
    ldx #length - 1
!loop:
    lda text,x
    sta where,x
    dex
    bpl !loop-
}

*= $0801 "Basic Loader"
    BasicUpstart(main)

*= $0810 "Code"
main:
    jsr CLEAR
    lda #BLACK                  // Kick Assembler knows the colours' names
    sta BORDER
    sta BACKGROUND
    ldx #39
!loop:
    lda #160                    // a solid block on rows 0 and 1
    sta SCREEN,x
    sta SCREEN + 40,x
    lda bars,x                  // in each column's colour
    sta COLOURS,x
    sta COLOURS + 40,x
    lda #WHITE                  // and the message's row white
    sta COLOURS + 3 * 40,x
    dex
    bpl !loop-
    copyText(message, messageEnd - message, SCREEN + 3 * 40 + 8)
loop:
    jmp loop

bars:
    .fill 40, floor(i / 5) + 2  // 5 columns each of colours 2 to 9: worked out as it's built
message:
    .text "made with kick assembler"
messageEnd:
