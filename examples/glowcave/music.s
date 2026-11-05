; music.s: a silent stand-in until the real song is added, made by Linux64Studio.
; The data goes at $1000-$1009, in the fixed area MUSIC
; (Project > Properties > Build > Memory layout). Its functions are in music.h.

        .segment "MUSIC"
        .incbin "placeholder.bin"

        .export _music_init, _music_play, _music_start, _music_stop, _music_sfx
        .import popax

        .segment "CODE"

; void __fastcall__ music_init(unsigned char tune): A = the tune, from 0
_music_init:
        jmp $1000

; void music_play(void): once a frame (if you don't use music_start)
_music_play:
        jmp $1003

; void music_start(void): play it once a frame, from a raster interrupt at line 0
_music_start:
        lda playing             ; (already playing: nothing to do)
        bne @done
        sei
        lda $0314               ; the handler it chains to: normally the KERNAL's
        sta chain
        lda $0315
        sta chain+1
        lda #<irq
        sta $0314
        lda #>irq
        sta $0315
        lda #$7F                ; the CIA timer's interrupt off: the raster's replaces it
        sta $DC0D
        lda $DC0D
        lda $D011               ; line 0 (bit 8 of the line clear)
        and #$7F
        sta $D011
        lda #0
        sta $D012
        lda #$01                ; raster interrupt on
        sta $D01A
        sta $D019
        sta playing
        cli
@done:  rts

; void music_stop(void): back to the KERNAL's interrupt, and silence
_music_stop:
        sei
        lda #0
        sta $D01A
        lda #$01
        sta $D019
        lda playing             ; (only if it was started)
        beq @off
        lda chain
        sta $0314
        lda chain+1
        sta $0315
        lda #0
        sta playing
        lda #$81                ; the CIA timer's interrupt back on
        sta $DC0D
@off:   lda #0
        sta $D418               ; volume 0
        cli
        rts

irq:    lda $D019               ; ours: the raster's (else the KERNAL's)
        and #$01
        beq @other
        sta $D019               ; acknowledge it
        jsr $1003
@other: jmp $EA31               ; on to the handler it replaced (set by music_start)
chain = @other + 1

; void __fastcall__ music_sfx(const unsigned char *effect, unsigned char voice): voice 1-3
_music_sfx:
        tay
        lda channels-1,y        ; voice 1, 2, 3 -> channel 0, 7, 14
        sta channel
        jsr popax               ; the effect: A low, X high
        pha
        txa
        tay                     ; the player takes it in A (low) and Y (high)
        pla
        ldx channel
        php                     ; (no interrupt while the player takes it: it may be playing)
        sei
        jsr $1006
        plp
        rts
channels: .byte 0, 7, 14

        .segment "BSS"
playing: .res 1
channel: .res 1
