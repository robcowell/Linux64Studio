; Starfall: the sprites, drawn in Linux64Studio's sprite editor (sprites.spt). Saving there
; writes sprites.bin (the editor's linked export), which is included here as it is.

        .export _sprite_data

        .segment "RODATA"
_sprite_data:
        .incbin "sprites.bin"           ; ship, rock, star: 64 bytes each
