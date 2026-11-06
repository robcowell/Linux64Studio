;===============================================================================
; Flash: the border flashes through the C64's 16 colours.
; Tutorial 2 (docs/tutorials/2-assembler.md) builds, runs and debugs it, and
; tutorial 4 tests flash with a transcript (tests.transcript).

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Initialize

EXTCOL  = $D020         ; the border's colour
BGCOL0  = $D021         ; the background's

start   lda #0
        sta BGCOL0      ; a black background

gMLoop
        jsr flash
        jmp gMLoop

;===============================================================================
; flash: the next colour in the border, then wait a while

flash   inc EXTCOL
        ldy #64         ; 64 x 256 times round the inner loop
flWait  dex
        bne flWait
        dey
        bne flWait
        rts
