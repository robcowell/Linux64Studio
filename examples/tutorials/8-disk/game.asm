;===============================================================================
; Game: the program the intro loads from the disk. It goes at $C000, out of
; BASIC's way, and has no BASIC loader: the intro starts it with jmp.

*=$C000

CHROUT  = $FFD2         ; print the character in A
EXTCOL  = $D020         ; the border's colour

gameStart
        lda #5          ; a green border: we're in the game
        sta EXTCOL
        ldx #0
@print  lda message,x
        beq gMLoop
        jsr CHROUT
        inx
        jmp @print

gMLoop  jmp gMLoop      ; the game would go here

message text "the game is running."
        byte 13, 0
