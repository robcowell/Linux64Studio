;===============================================================================
; Fill: fills the screen with a character, a different one every 8 frames.
; Tutorial 9 (docs/tutorials/9-profiler.md) profiles it, finds fill is slow,
; and speeds it up. This is the fast fill; the slow one is below, unused.

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Once a frame: work out the character, and fill the screen with it

SCREEN  = $0400
RASTER  = $D012         ; the line the VIC-II is drawing
ptr     = $FB           ; two bytes on zero page: an address

gMLoop  lda #250        ; wait for line 250, below the screen
gMWait  cmp RASTER
        bne gMWait
gMLeave cmp RASTER      ; then for it to end
        beq gMLeave
        inc frames
        lda frames
        lsr             ; frames / 8
        lsr
        lsr
        sta char
        jsr fill
        jmp gMLoop

;===============================================================================
; fill: put char in all 1,000 places on the screen, 4 at a time

fill    lda char
        ldx #250
@loop   sta SCREEN-1,x
        sta SCREEN+249,x
        sta SCREEN+499,x
        sta SCREEN+749,x
        dex
        bne @loop
        rts

;===============================================================================
; slowFill: the first fill, a row at a time through a pointer (12,000 cycles or
; so, against fill's 6,261)

slowFill
        lda #<SCREEN    ; ptr: the start of the row
        sta ptr
        lda #>SCREEN
        sta ptr+1
        ldx #25         ; 25 rows
@row    lda char
        ldy #39         ; 40 places in a row, from the right
@place  sta (ptr),y
        dey
        bpl @place
        lda ptr         ; ptr + 40: the next row
        clc
        adc #40
        sta ptr
        bcc @next
        inc ptr+1
@next   dex
        bne @row
        rts

frames  byte 0
char    byte 0
