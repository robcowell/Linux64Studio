;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; A bang each time a key is pressed: a sound made in the SID Designer.

EXTCOL  = $D020         ; the border's colour
CHROUT  = $FFD2         ; print the character in A
GETIN   = $FFE4         ; a key from the keyboard buffer in A (0: none)

start   lda #0          ; a black border
        sta EXTCOL
        ldx #0          ; and the message
@print  lda message,x
        beq loop
        jsr CHROUT
        inx
        jmp @print

loop    jsr GETIN       ; wait for a key
        beq loop
        jsr bang
        inc EXTCOL      ; (and flash the border)
        jmp loop

bang    lda #0          ; the gate off first, so the sound starts again
        sta $D404
; SID sound (made by Linux64Studio's SID Designer)
SID             = $D400
        lda #$B4
        sta SID         ; voice 1 frequency low (C-3, $08B4)
        lda #$08
        sta SID+1       ; voice 1 frequency high
        lda #$09
        sta SID+5       ; voice 1 attack 0, decay 9
        sta SID+6       ; voice 1 sustain 0, release 9
        lda #$0F
        sta SID+24      ; no filter mode, volume 15
        lda #$81
        sta SID+4       ; voice 1 noise, gate on
        rts

message byte 147        ; {clear}
        text "press a key for a bang"
        byte 0
