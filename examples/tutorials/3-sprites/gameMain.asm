;===============================================================================
; Ball: a sprite drawn in the sprite editor (sprites.spt, exported as
; sprites.bin) floats across the screen, a pixel a frame.
; Tutorial 3 (docs/tutorials/3-sprites.md) makes it.

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Initialize

SP0X    = $D000         ; sprite 0's x position (the low 8 bits)
SP0Y    = $D001         ; and y
RASTER  = $D012         ; the line the VIC-II is drawing
SPENA   = $D015         ; which sprites are on, a bit each
SP0COL  = $D027         ; sprite 0's colour
SPRPTR0 = $07F8         ; sprite 0's data: block number (address / 64)

start   lda #SPRITES/64 ; the ball's data, at $2000: block 128
        sta SPRPTR0
        lda #7          ; yellow
        sta SP0COL
        lda #100
        sta SP0Y
        lda #24         ; the screen's left edge
        sta SP0X
        lda #%00000001  ; sprite 0 on
        sta SPENA

;===============================================================================
; Once a frame: move the ball a pixel to the right

gMLoop  lda #250        ; wait for line 250, below the screen
gMWait  cmp RASTER
        bne gMWait
        inc SP0X
gMLeave cmp RASTER      ; then for line 250 to end, so it's once a frame
        beq gMLeave
        jmp gMLoop

;===============================================================================
; The sprite data, from the sprite editor (Export > Binary, or the link in its
; toolbar that writes sprites.bin every time sprites.spt is saved)

*=$2000
SPRITES
        incbin "sprites.bin"
