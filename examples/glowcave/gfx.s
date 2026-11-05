; Glowcave: the graphics, each at a fixed address where the VIC-II sees it. The project's fixed
; areas (Project > Properties > Build > Memory layout) are SPRITES ($3600) and CHARSET ($3800);
; the program is linked round them. sprites.bin and chars.bin are the sprite and character
; editors' linked exports, written each time sprites.spt or chars.cst is saved.

        .segment "SPRITES"
        .incbin "sprites.bin"           ; blocks 216-218: the player, the bat's two frames

        .segment "CHARSET"
        .incbin "chars.bin"             ; floor, wall, gem
