;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; A ball moved by the joystick in port 2. Fire changes its colour.

SP0X    = $D000         ; sprite 0's X (low 8 bits)
SP0Y    = $D001         ; and Y
MSIGX   = $D010         ; the 9th bit of each sprite's X
SPENA   = $D015         ; which sprites are on
SP0COL  = $D027         ; sprite 0's colour
RASTER  = $D012         ; the raster line
CIAPRA  = $DC00         ; joystick 2: bits 0-4 up, down, left, right, fire (0 = pressed)
SPRPTR0 = $07F8         ; sprite 0's data pointer (64-byte blocks)

start   lda #$2000/64   ; the ball's data, at $2000
        sta SPRPTR0
        lda #1          ; sprite 0 on
        sta SPENA

frame   lda #250        ; once a frame, at line 250
@wait   cmp RASTER
        bne @wait
        lda CIAPRA      ; read the joystick
        jsr move
        jsr place
        jmp frame

; Move by the joystick bits in A: a pixel a frame each way, a new colour on fire.
move    sta joy
        lda joy
        and #%00000001  ; up?
        bne @down
        dec ypos
@down   lda joy
        and #%00000010  ; down?
        bne @left
        inc ypos
@left   lda joy
        and #%00000100  ; left?
        bne @right
        lda xpos        ; xpos is 16 bits: take 1 from both bytes
        sec
        sbc #1
        sta xpos
        lda xpos+1
        sbc #0
        sta xpos+1
@right  lda joy
        and #%00001000  ; right?
        bne @fire
        inc xpos
        bne @fire
        inc xpos+1
@fire   lda joy
        and #%00010000  ; fire?
        bne @done
        inc colour
@done   rts

; Put the sprite where xpos and ypos say, in its colour.
place   lda xpos
        sta SP0X
        lda xpos+1      ; X's 9th bit, for sprite 0: bit 0
        sta MSIGX
        lda ypos
        sta SP0Y
        lda colour
        sta SP0COL
        rts

joy     byte 0          ; the joystick bits being looked at
xpos    word 172        ; where the ball is: the middle of the screen
ypos    byte 139
colour  byte 7          ; yellow

*=$2000                 ; the ball
        byte $00,$7E,$00, $03,$FF,$C0, $07,$FF,$E0, $1F,$FF,$F8, $1F,$FF,$F8, $3F,$FF,$FC, $7F,$FF,$FE
        byte $7F,$FF,$FE, $FF,$FF,$FF, $FF,$FF,$FF, $FF,$FF,$FF, $FF,$FF,$FF, $FF,$FF,$FF, $7F,$FF,$FE
        byte $7F,$FF,$FE, $3F,$FF,$FC, $1F,$FF,$F8, $1F,$FF,$F8, $07,$FF,$E0, $03,$FF,$C0, $00,$7E,$00
