;===============================================================================
; Tune: plays a GoatTracker song, a frame of it in every raster interrupt.
; Tutorial 7 (docs/tutorials/7-music.md) makes it. tune.sng is packed with
; GoatTracker's player into tune.bin on every build.

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; Start the tune, and an interrupt once a frame to play it

MUSIC   = $1000         ; the player: init at MUSIC, play at MUSIC+3
IRQVEC  = $0314         ; the KERNAL's interrupt vector
CONTROL = $D011         ; its top bit is the raster line's 9th
RASTER  = $D012         ; the line to interrupt at
IRQFLAG = $D019         ; which VIC-II interrupt happened
IRQMASK = $D01A         ; which ones are on
CIAICR  = $DC0D         ; the CIA's interrupts
KERNIRQ = $EA31         ; the KERNAL's own handler: keyboard, clock

start   lda #0          ; the song's first tune
        jsr MUSIC       ; init
        sei             ; no interrupts while they're changed
        lda #%01111111  ; the CIA's timer interrupts off
        sta CIAICR
        lda CIAICR      ; (and any that's waiting)
        lda #<irq       ; ours instead
        sta IRQVEC
        lda #>irq
        sta IRQVEC+1
        lda #0          ; at raster line 0
        sta RASTER
        lda CONTROL
        and #%01111111
        sta CONTROL
        lda #1          ; raster interrupts on
        sta IRQMASK
        cli

gMLoop  jmp gMLoop      ; the game would go here

;===============================================================================
; Once a frame, at line 0

irq     lda #1          ; this interrupt's dealt with
        sta IRQFLAG
        inc frames
        jsr MUSIC+3     ; play a frame of the tune
        jmp KERNIRQ

frames  byte 0

;===============================================================================
; The song and its player, packed by gt2reloc

*=$1000
        incbin "tune.bin"
