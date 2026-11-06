;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; A split screen: two raster interrupts a frame, one at line 50 making the
; border and background blue, one at line 150 making them red.

EXTCOL  = $D020         ; the border's colour
BGCOL0  = $D021         ; the background's
SCROLY  = $D011         ; bit 7: the top bit of the raster line
RASTER  = $D012         ; the raster line (read), the interrupt's line (write)
VICIRQ  = $D019         ; the VIC-II's interrupt flags (write 1 to clear)
IRQMSK  = $D01A         ; which of them interrupt
CIAICR  = $DC0D         ; CIA 1's interrupt control
CINV    = $0314         ; where the KERNAL's interrupt goes on to
TOP     = 50            ; the split's lines
MIDDLE  = 150

start   sei             ; no interrupts while they're set up
        lda #$7f        ; CIA 1's timer: no more interrupts from it
        sta CIAICR
        lda CIAICR      ; (one waiting is cleared by reading)
        lda #<irqTop    ; the first handler
        sta CINV
        lda #>irqTop
        sta CINV+1
        lda #TOP        ; at line 50
        sta RASTER
        lda SCROLY      ; (lines below 256: bit 7 clear)
        and #$7f
        sta SCROLY
        lda #1          ; raster interrupts on
        sta IRQMSK
        cli

gMLoop  jmp gMLoop      ; the main program: nothing, here

irqTop  lda #6          ; blue from line 50
        sta EXTCOL
        sta BGCOL0
        lda #<irqMiddle ; the next interrupt: the other handler, at line 150
        sta CINV
        lda #>irqMiddle
        sta CINV+1
        lda #MIDDLE
        sta RASTER
        inc frames      ; (a count of frames, to test)
        lda #1          ; acknowledge it
        sta VICIRQ
        jmp $EA31       ; the KERNAL's own work, once a frame: keys, its clock

irqMiddle lda #2          ; red from line 150
        sta EXTCOL
        sta BGCOL0
        lda #<irqTop
        sta CINV
        lda #>irqTop
        sta CINV+1
        lda #TOP
        sta RASTER
        lda #1
        sta VICIRQ
        jmp $EA81       ; back to the program

frames  byte 0
