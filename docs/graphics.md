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
