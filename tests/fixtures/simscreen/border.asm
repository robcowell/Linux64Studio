; The Screen against VICE (tests/test_sim.py): ECM text with the top and bottom border opened (24
; rows between lines 247 and 251), showing the idle state's ECM byte ($39FF) and a sprite in each.
*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   sei
        lda #$7f
        sta $dc0d
        ldx #0
@fill   txa
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $06e8,x
        lsr
        sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $dae8,x
        inx
        bne @fill
        lda #$3c        ; the idle state's byte, in ECM
        sta $39ff
        lda #$5b        ; ECM text, 25 rows
        sta $d011
        lda #$c8
        sta $d016
        lda #9
        sta $d021
        lda #2
        sta $d022
        lda #5
        sta $d023
        lda #6
        sta $d024
        lda #10
        sta $d020
        lda #$80
        sta $07f8
        sta $07f9
        lda #1
        sta $d027
        lda #7
        sta $d028
        lda #100        ; sprite 0 in the bottom border, sprite 1 in the top
        sta $d000
        lda #255
        sta $d001
        lda #160
        sta $d002
        lda #20
        sta $d003
        lda #3
        sta $d015
frame   lda #249        ; 24 rows at line 249: the bottom border never starts
@w1     cmp $d012
        bne @w1
        lda #$53
        sta $d011
        lda #255        ; and back to 25 after line 251
@w2     cmp $d012
        bne @w2
        lda #$5b
        sta $d011
        jmp frame
*=$2000
        byte 255,255,255, 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1
        byte 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1
        byte 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1, 128,0,1, 255,255,255
