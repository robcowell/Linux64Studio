;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; A message scrolling across the middle of the screen, a pixel a frame.

EXTCOL  = $D020         ; the border's colour
BGCOL0  = $D021         ; the background's
RASTER  = $D012         ; the raster line
SCROLX  = $D016         ; bits 0-2: the fine scroll across; bit 3: 40 columns (1) or 38
CLEAR   = $E544         ; the KERNAL's screen clear
ROW     = $0400+12*40   ; row 12 of the screen
ROWCOL  = $D800+12*40   ; and its colours

start   jsr CLEAR
        lda #0          ; black
        sta EXTCOL
        sta BGCOL0
        lda #7          ; the row in yellow
        ldx #39
@colour sta ROWCOL,x
        dex
        bpl @colour

frame   lda #250        ; wait for line 250, below the text
@wait   cmp RASTER
        bne @wait
        dec fine        ; one pixel further left
        bpl setScroll
        lda #7          ; 8 pixels gone: back to 7, and the row moves a whole
        sta fine        ; character left
        jsr shift
setScroll lda fine
        ora #%11000000  ; 38 columns (bit 3 clear), so the edges are hidden
        sta SCROLX
        jmp frame

shift   ldx #0          ; each character one place left
@move   lda ROW+1,x
        sta ROW,x
        inx
        cpx #39
        bne @move
        ldy next        ; and the message's next letter on the right
        lda message,y
        bne @put
        ldy #0          ; (at its end, back to the start)
        lda message
@put    sta ROW+39
        iny
        sty next
        rts

fine    byte 7          ; the fine scroll: 7 to 0
next    byte 0          ; the message's next letter
message text 'hello from linux64studio! this message scrolls a pixel at a time ...    '
        byte 0
