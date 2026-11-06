; The Screen against VICE (tests/test_sim.py): text, 24 rows scrolled down 5, 38 columns scrolled
; right 3, the idle state's byte ($3FFF), sprite 0 behind the characters, sprite 2 partly under the
; border, and a character in row 0 changed after the VIC-II read the row, and back before it does.
*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   sei
        lda #$7f        ; no CIA interrupts
        sta $dc0d
        ldx #0          ; characters and colours all over
@fill   txa
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $06e8,x
        and #$0f
        sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $dae8,x
        inx
        bne @fill
        lda #$55        ; the idle state's pattern
        sta $3fff
        lda #$15        ; 24 rows, scrolled down 5
        sta $d011
        lda #$c3        ; 38 columns, scrolled right 3
        sta $d016
        lda #6
        sta $d020
        lda #0
        sta $d021
        ldx #15         ; sprites 0-3
@pos    lda where,x
        sta $d000,x
        dex
        bpl @pos
        lda #$80        ; their data at $2000
        ldx #3
@ptr    sta $07f8,x
        dex
        bpl @ptr
        lda #1
        sta $d027
        lda #2
        sta $d028
        lda #7
        sta $d029
        lda #5
        sta $d02a
        lda #%00000001  ; sprite 0 behind the characters
        sta $d01b
        lda #%00001111
        sta $d015
frame   lda #20         ; at line 20: a block in row 0
@w1     cmp $d012
        bne @w1
        lda #160        ; (a solid block)
        sta $0402
        lda #150        ; at line 150: a space there (but row 0 was read with the block)
@w2     cmp $d012
        bne @w2
        lda #32         ; (a space)
        sta $0402
loop    jmp frame
where   byte 60,70, 66,76, 10,120, 200,240
*=$2000
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
        byte 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255, 255,255,255
