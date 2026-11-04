# Graphics editors

The sprite, character set and screen editors read and write CBM prg Studio's `.spt`, `.cst`
and `.sdd` files, SpritePad `.spd` and CharPad `.ctm` projects. The file formats are described
in [dialect.md](dialect.md#graphics-files).

## Sprite Morph

The **Morph…** button in the sprite editor's toolbar (the shuffle icon) makes the frames that
turn one sprite into another, as CBM prg Studio's Sprite Morph Tool does. As its help says, it's
more like a dissolve: the pixels that differ between the two sprites switch from the first
sprite's value to the second's, a few more on each frame.

* **Start sprite** and **End sprite**: the start is the sprite you're editing, and the end is
  the one after it, to begin with.
* **Frames**: how many, counting the start and end sprites.
* **Function**: how fast the pixels switch over: **Linear** (evenly), **Quadratic** and
  **Cubic** (slowly at first, then faster), or **Sine** (slowly at both ends).
* **Order**: which pixels switch first: **Dissolve** (a random order, the same every time),
  **Top to bottom**, **Left to right**, or **From the centre**.

The preview plays the frames (**▶**, at the speed you choose) or steps through them, and the
strip below shows them all. Click one to see it larger. **Add** puts them in the sprite set,
either:

* **after the start sprite**: just the in-between frames, so with sprites that are next to
  each other you get start, in-betweens, end in a row, ready for an animation; or
* **at the end of the set**: the whole sequence, start and end included.

The frames are single colour or multicolour like the start sprite, with its colour and
expansion. The end sprite is read in that mode too, as in CBM prg Studio. In multicolour mode
a pixel is a pair of bits. Adding sprites clears the undo history, as deleting a sprite does,
because undo works per sprite.

`tests/test_morph.py` checks that the first and last frames are the two sprites, that each
function's frames switch the right number of pixels, that only differing pixels change, the
orders, and multicolour.

## Sprite Explosion Generator

The **Explosion Generator…** button in the sprite editor's toolbar (the storm icon) makes the
frames of an explosion, as CBM prg Studio's tool does. Choose a type:

* **Fireball**: a lumpy ball that swells, cools from the middle and breaks up into smoke.
* **Radial**: spikes that shoot out from a flash and fly off.
* **Ring**: a shock wave that grows, thins and breaks up.
* **Debris**: pieces flung out at different speeds, which slow down and fade.
* **Starburst**: a star that flashes up and dies away.
* **Plasma**: a churning cloud that grows and thins out.

Then set the parameters. CBM prg Studio's recommended ranges are in each tooltip:

* **Radius** (4-10): how big it gets, in pixels.
* **Spikes** (6-16): for radial and starburst.
* **Debris** (5-20): how many pieces fly off.
* **Turbulence** (1-3): how much the shapes wobble from frame to frame.
* **Thickness** (1-2): of the spikes, rings and pieces.
* **Number of frames**.
* **Seed**: the same seed and parameters always give the same explosion.

**Random Preset** picks everything at random, and **Mutate** makes a variation on the current
one.

**Single colour** draws the hot parts in the sprite's colour. **Multicolour** uses all three
colours: the hottest parts are **Colour 1** (%10, the sprite's own colour), then **Colour 2**
(%01, $D025), then the coolest, **Colour 3** (%11, $D026). $D025 and $D026 are shared by every
sprite. So when the set already has multicolour sprites, Colours 2 and 3 start as its own, and
they only change if you tick **Set the sprite set's multicolours to these**. The preview always
shows the colours the sprites will really have.

The preview plays the frames (**▶** and **■**, at the speed you choose) or steps through them,
and the strip shows them all. **Add** puts them after the current sprite or at the end of the
set. They're named after the type and frame. **Copy as DATA** and **Export DATA…** give them as
BASIC `DATA` lines instead, 63 bytes a frame with a `rem` before each (CBM prg Studio's
`explosion_sprites.bas`). The explosions are drawn by Linux64Studio's own generator, so they
won't match CBM prg Studio's frame for frame.

`tests/test_explode.py` checks that every type grows and dies away, multicolour, that the
seed gives the same frames, that the parameters have an effect, the random presets and
mutations, and the DATA lines.

## Import sprites from an image

The **Import from Image…** button in the sprite editor's toolbar (the picture icon) cuts sprites
out of a `.bmp`, as CBM prg Studio's *Import → From Bitmap* does, or out of a `.png` or `.gif`: a
sprite sheet from another editor, a screenshot, a drawing. The image is shown with the 24×21
cells it will be cut into (blue for those imported), and the sprites below it, before anything
is added.

* **Layout:** pixels to skip at the left and top, the gap between sprites (a sheet's grid lines
  or spacing), and *image pixels per pixel* for an image saved zoomed in (2 if each sprite pixel
  is 2×2). Take all the sprites that fit or a number of them, row by row or column by column, and
  leave out empty cells if you like.
* **Hires:** a pixel is set when it's darker than the threshold, as in CBM prg Studio, or
  lighter, for art drawn on a dark background. Transparent pixels are never set.
* **Multicolour:** each sprite pixel is two image pixels wide. Give the image colour of each
  bit pair (as `RRGGBB`, or pick it by clicking the pick button then the image); a pixel takes the
  nearest one within the tolerance, else the background. **Guess from the Image** fills them in:
  the commonest colour (or the transparent area) is the background, and the others are matched to
  the colours the sprite set already uses, so importing art for an existing set gets them right.
  One import has one sprite colour, as on the C64 for each sprite: import sprites with different
  sprite colours in separate goes.
* **Into the sprite set:** after the current sprite, at the end, or over the current sprite and
  those after it. Unlike CBM prg Studio, the sprite colour and multicolours can be set to the
  nearest C64 colours of the image's.

## Sprite scratch pad

The **Scratch Pad…** button in the sprite editor's toolbar (the grid icon) opens CBM prg Studio's
sprite scratch pad: a grid for putting sprites side by side, to see a graphic made of several of
them, or on top of each other, to see layers.

* Click a sprite on the right, then click cells to put it there (as often as you like), or drag
  a sprite onto a cell.
* Right click (or Esc) to select instead: click a cell to list its sprites, the last drawn on
  top. For the one selected, move it up to 20 pixels in its cell (the boxes, or the arrow keys),
  flip it either way, invert it, bring it forward or send it back, or remove it (Delete). A sprite
  moved past its cell's edge carries on into the next one, as on screen. None of this changes the
  sprites themselves.
* Set the grid's size and zoom in the header, and save the pad as a PNG image.

The pad shows sprites as you edit them, keeps pointing at the same sprites when others are added
or deleted, and is saved with the sprite file (in the project's settings), so closing without
saving leaves both as they were.

## Character scratch pad

The **Scratch Pad…** button in the character editor's toolbar (the grid icon) opens CBM prg
Studio's character scratch pad: a grid for designing graphics made of several characters. It
shows the characters as they're drawn in the editor.

* Paint the character selected in the editor with the left button; the right button clears
  cells. Characters can also be dragged in from the editor's character set, or put on in order
  with **Get Characters…**: a list such as `1,2,3,4-10,11,12` (`$hex` too), from a column and row,
  going across (then the next row) or down (then the next column). It says if some didn't fit.
* Shift+drag selects a block: Ctrl+C, Ctrl+X and Ctrl+V copy, cut and paste it (at the selection,
  or the cell last clicked), Delete clears it, Esc deselects. Double-click a cell to edit that
  character.
* The header shifts the pad's contents (wrapping round), sets its size and zoom, and turns the
  grid lines and character codes on or off. **Clear** empties the pad; **Clear the characters on
  it** blanks those characters in the set, to draw them afresh (one Ctrl+Z in the editor undoes it).

As in CBM prg Studio, the pad belongs to no project or character set: it's kept in the settings
folder (`char_scratchpad.json`) and is the same whichever set is open.

In the **screen designer**, the **stamp** tool (the grid icon) puts the scratch pad on the screen
with its top left where you click, in the current colour (in a CharPad map, each character's
own), as one undo step. If a block is selected in the scratch pad, only that part is stamped;
empty cells of the pad leave the screen as it is.

## Digitiser

The **digitiser** button in the screen editor's toolbar (the target icon, next to the charset)
gives the sprite coordinates of points on the screen, as CBM prg Studio's Digitiser does. Use it
to plan where sprites go: start positions, paths, and where things are on a level.

Move the mouse over the screen to see the coordinates, and click to add them to **Points**. While
the digitiser is on, clicking doesn't draw. **Clear** empties the list, and **Copy All** copies
it. The coordinates are worked out like this:

* **Offsets X, Y** are added to the pixel's position on the screen. The usual 24 and 50 give
  sprite coordinates, where a sprite at that X, Y has its top-left corner on the pixel. Points in
  the border work too.
* **MSB** takes 256 off X, for the part that goes in the sprite's X register when its bit in
  $D010 is set. A note says when X goes over 255.
* **Format** is any text with `{x}` and `{y}` in it. `{$x}` and `{$y}` give hex, and `{$X}` and
  `{$Y}` upper case hex. `\n` starts a new line. The list button has some ready-made formats,
  such as `byte {x}, {y}`.

Tick **Use sprite as the pointer** to see a sprite from one of the project's sprite files under
the mouse instead of the crosshair, with its top-left corner on the pointer. Choose the sprite
set, the sprite number, and whether it's expanded. The offsets and the format are kept for next
time. `tests/test_digitiser.py` checks the coordinates and formats; they agree with the Screen
Calculator's sprite coordinates.

## CharPad tile maps

A CharPad project (`.ctm`) that uses tiles opens with a **Map** page for editing the tile map.

* **Draw** paints the chosen tile. Right-click paints tile 0, and Ctrl+click picks up the tile
  under the pointer. **Rectangle** fills an area, and **Pick** chooses the tile under the
  pointer. Ctrl+Z and Ctrl+Shift+Z undo and redo every change, tile edits included.
* **Tiles** shows them all; tiles no map cell uses are dimmed. **New Tile** adds a copy of the
  chosen one at the end. To change a tile, click one of its cells in **Tile**, then a character
  below. The cell moves on to the next one, so a tile can be built quickly.
* **Rooms** (width × height, in tiles) draws the grid of rooms (screens) a game cuts the map
  into, numbered left to right and top to bottom, as a flip-screen game counts them. The status
  line says which room the pointer is in, and where in it.
* **Materials** tints each character by its material, the high nibble of CharPad's attribute
  byte, which games use for collision. Name the materials (solid, platform, ladder and so on)
  in the list below the characters. The names show here and on the Characters page, which has a
  **Material** control for each character beside its colour.

The room size and material names are kept in the Linux64Studio project (`charpad_views`).

### Games whose data is CharPad's binary exports

**Menu → Import CharPad Binaries…** makes a `.ctm` from a game's four files: characters (8 bytes
each), attributes (colour in the low nibble, material in the high one), tiles (8-bit, row by
row) and the map (8-bit, row by row). It guesses the files by name. Give it the tile size and
the map's width, and it shows the size of the map you'll get. The new project's exports are
linked to those same four files. Saving it writes them back byte for byte, with only your edits
changed, so the game's code and build don't change at all. Importing a game's data and saving it
straight away gives back the same four files.

`tests/test_charpad_tiles.py` checks the import, the edits, materials and that the exports are
the original files. This was also checked on a real game: 256 characters, 15 tiles and an 80×20
map. Painting a ladder into one room changed only those six bytes of `map.bin`, and the game,
rebuilt, showed the ladder in that room.
