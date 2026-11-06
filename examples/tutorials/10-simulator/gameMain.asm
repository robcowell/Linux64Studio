;===============================================================================
; Frames: prints a message with the KERNAL, then counts frames by the raster
; line and moves the border on a colour a second.
; Tutorial 10 (docs/tutorials/10-simulator.md) debugs it without VICE.

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Print the message

CHROUT  = $FFD2         ; the KERNAL's: print the character in A
EXTCOL  = $D020         ; the border's colour
RASTER  = $D012         ; the line the VIC-II is drawing

start   ldx #0
print   lda message,x
        beq gMLoop      ; the 0 at its end
        jsr CHROUT
        inx
        jmp print

;===============================================================================
; Once a frame: count it, and every 50 frames (a second) change the border

gMLoop  lda #250        ; wait for line 250, below the screen
gMWait  cmp RASTER
        bne gMWait
gMLeave cmp RASTER      ; then for it to end
        beq gMLeave
        inc frames
        lda frames
        cmp #50
        bne gMLoop
        lda #0
        sta frames
        inc EXTCOL
        inc seconds
        jmp gMLoop

frames  byte 0
seconds byte 0
message byte 147        ; {clear}
        text "counting frames by the raster line."
        byte 0
