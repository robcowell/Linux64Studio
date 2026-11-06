;===============================================================================
; Intro: says it's loading, loads the game from the disk, and starts it.
; Tutorial 8 (docs/tutorials/8-disk.md) puts both programs on a disk.

;===============================================================================
; BASIC Loader

*=$0801 ; 10 SYS (2064)

        byte $0E, $08, $0A, $00, $9E, $20, $28, $32
        byte $30, $36, $34, $29, $00, $00, $00

;===============================================================================
; The KERNAL's routines for files

CHROUT  = $FFD2         ; print the character in A
SETLFS  = $FFBA         ; file number, device, secondary address
SETNAM  = $FFBD         ; the file's name: A its length, X/Y its address
LOAD    = $FFD5         ; load it (A = 0)
EXTCOL  = $D020         ; the border's colour
GAME    = $C000         ; where the game starts

start   ldx #0
@print  lda message,x
        beq loadGame
        jsr CHROUT
        inx
        jmp @print

loadGame lda #1         ; file 1
        ldx #8          ; on device 8, the disk drive
        ldy #1          ; secondary address 1: load it where the file says
        jsr SETLFS
        lda #4          ; the name, 4 letters long
        ldx #<name
        ldy #>name
        jsr SETNAM
        lda #0          ; 0 to load (1 would verify)
        jsr LOAD
        bcs failed      ; the carry's set if it didn't load
        jmp GAME

failed  inc EXTCOL      ; flash the border: something's wrong
        jmp failed

name    text "game"
message byte 147        ; {clear}
        text "loading the game..."
        byte 13, 0
