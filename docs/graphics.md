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
