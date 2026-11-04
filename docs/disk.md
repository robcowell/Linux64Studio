# 1541 disk images (.d64)

## From a project

In **Project Properties → Disk Image**, switch on *Write a disk image*. Every whole-project
build (F7, Ctrl+F5) then writes the `.d64` after the `.prg`. Building just the current file
doesn't.

* **Image file**: where to write it, relative to the project.
* **Disk name / ID**: the header that `LOAD"$",8` shows (16 and 2 characters).
* **Program's name on the disk**: defaults to the `.prg`'s name, so `LOAD"GAME",8,1` works.
* **More files on the disk**: other programs or data files, written after the program.
  `.prg` files go on as PRG, `.seq` as SEQ, `.usr` as USR. A `.bin` goes on as PRG, so it
  should already start with its load address.
* **Run from the disk image**: Ctrl+F5 and debugging autostart the `.d64` instead of the
  `.prg`, like running it from a real disk.

If the disk is full or an extra file is missing, the build fails with an error in the build
output.

## Opening a .d64

`.d64` files open in a directory view, the way `LOAD"$",8` shows it. You can add files (or
drag them in), extract them, delete them, change the disk name and ID, list a program as BASIC
(double-click it), and run the disk in VICE. Ctrl+S saves the image.

## Command line

```sh
l64disk create game.d64 "my game,mg" game.prg hiscores.seq
l64disk list game.d64
l64disk add game.d64 level2.prg --name "LEVEL 2"
l64disk extract game.d64 "level 2" -o level2.prg
l64disk delete game.d64 "level 2"
l64asm game.asm --d64 game.d64 --disk-name "my game,mg"
l64bas game.bas --d64 game.d64
```

## How files are laid out

Images are standard 35-track `.d64` files (174,848 bytes). Files are allocated exactly as the
1541's DOS does it. The algorithm comes from Rift64's drive emulation:

* A new file starts at the first free sector on the track nearest the directory (17, 19,
  16, 20, …).
* Each further block is 10 sectors on. Past the end of a track it wraps round one short.
* When a track is full, allocation carries on away from the directory, and when that side
  of the disk is full, it starts again from the other side.
* Directory sectors are chained 3 apart on track 18.
* When a file exactly fills its last sector, the DOS takes one more block that no file uses.
  A finished image is validated, as with `V`, so that block is given back.

`tests/test_d64.py` replays an experiment from a real 1541 (formatting, saving eight files,
scratching one, validating) and checks that every file's sector chain and the whole BAM come
out the same. VICE's `c1541` also reads the images, and writing more files to them with
`c1541` leaves the existing ones intact.
