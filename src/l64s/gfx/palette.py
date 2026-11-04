"""The C64's 16 colours (Pepto's VIC-II palette) and their names."""

COLOUR_NAMES = [
    "Black", "White", "Red", "Cyan", "Purple", "Green", "Blue", "Yellow",
    "Orange", "Brown", "Light Red", "Dark Grey", "Grey", "Light Green", "Light Blue", "Light Grey",
]

PALETTE_HEX = [
    "#000000", "#FFFFFF", "#68372B", "#70A4B2", "#6F3D86", "#588D43", "#352879", "#B8C76F",
    "#6F4F25", "#433900", "#9A6759", "#444444", "#6C6C6C", "#9AD284", "#6C5EB5", "#959595",
]

PALETTE_RGB = [tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)) for h in PALETTE_HEX]
