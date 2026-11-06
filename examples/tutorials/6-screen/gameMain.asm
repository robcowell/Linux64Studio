;===============================================================================
; Bricks: a screen designed in the screen designer, in characters drawn in the
; character set editor. Tutorial 6 (docs/tutorials/6-screen.md) makes it.

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Copy the screen and its colours in, and use our characters

SCREEN  = $0400         ; the screen's characters
COLOURS = $D800         ; and their colours
EXTCOL  = $D020         ; the border's colour
BGCOL0  = $D021         ; the background's
VMCSB   = $D018         ; where the VIC-II finds the screen and the characters

start   lda #0          ; a black border and background
        sta EXTCOL
        sta BGCOL0
        ldx #250        ; 4 x 250 = 1,000: the whole screen
@copy   lda titleChars-1,x
        sta SCREEN-1,x
        lda titleChars+249,x
        sta SCREEN+249,x
        lda titleChars+499,x
        sta SCREEN+499,x
        lda titleChars+749,x
        sta SCREEN+749,x
        lda titleColours-1,x
        sta COLOURS-1,x
        lda titleColours+249,x
        sta COLOURS+249,x
        lda titleColours+499,x
        sta COLOURS+499,x
        lda titleColours+749,x
        sta COLOURS+749,x
        dex
        bne @copy
        lda #%00011100  ; the screen at $0400 (0001), the characters at $3000 (110)
        sta VMCSB

gMLoop  jmp gMLoop

;===============================================================================
; The characters (from chars.cst) and the screen (from title.sdd)

*=$3000
        incbin "chars.bin"
titleChars incbin "title.bin"
titleColours incbin "title_colours.bin"
