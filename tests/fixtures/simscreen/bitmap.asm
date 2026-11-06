; The Screen against VICE (tests/test_sim.py): a multicolour bitmap with 25 rows not scrolled (so
; the last lines are idle, showing $3FFF), multicolour and expanded sprites, and sprite 0 behind the
; bitmap hiding sprite 1 (in front of it but behind sprite 0) where sprite 0 is.
*=$0801
        byte $0B, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00
*=$080D
start   sei
        lda #$7f
        sta $dc0d
        lda #$20        ; a bitmap at $2000-$3F3F, a pattern in it
        sta $fc
        lda #0
        sta $fb
        ldy #0
@page   tya
        eor $fc
        asl
        eor #$5a
        sta ($fb),y
        iny
        bne @page
        inc $fc
        lda $fc
        cmp #$40
        bne @page
        ldx #0          ; its colours: screen memory and colour RAM
@col    txa
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $06e8,x
        eor #$07
        sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $dae8,x
        inx
        bne @col
        lda #$aa        ; the idle state's byte
        sta $3fff
        lda #$30        ; multicolour bitmap, 25 rows, not scrolled
        sta $d011
        lda #$18
        sta $d016
        lda #$18        ; screen $0400, bitmap $2000
        sta $d018
        lda #11
        sta $d021
        lda #14
        sta $d020
        ldx #15
@pos    lda where,x
        sta $d000,x
        dex
        bpl @pos
        lda #$30        ; sprite data at $0C00
        ldx #3
@ptr    sta $07f8,x
        dex
        bpl @ptr
        ldx #62
@spr    txa
        ora #$81
        sta $0c00,x
        dex
        bpl @spr
        lda #1
        sta $d027
        lda #2
        sta $d028
        lda #7
        sta $d029
        lda #13
        sta $d02a
        lda #3
        sta $d025
        lda #4
        sta $d026
        lda #%00000101  ; sprites 0 and 2 multicolour
        sta $d01c
        lda #%00000011  ; 0 and 1 twice as wide and tall
        sta $d01d
        sta $d017
        lda #%00000001  ; 0 behind the bitmap: so 1, under it, is hidden where 0 is
        sta $d01b
        lda #%00001111
        sta $d015
loop    jmp loop
where   byte 100,100, 112,110, 200,236, 250,40
