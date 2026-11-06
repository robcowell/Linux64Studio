# Test fixtures

`real-1541-allocation.txt` comes from Rift64 (`tests/fixtures/allocation/real-1541.txt`). It is
where a real 1541's DOS put everything (run by VICE 3.7.1's true drive emulation) after this
BASIC program: format the disk as `ALLOC TEST,AT`, save files `A` to `H` of 100, 7618, 760, 506,
50798, 50798, 50798 and 20000 bytes from $1000 (each plus its 2-byte load address), scratch `A`
after the first three are saved, then validate. The disk fills up before `H` is finished.

Each line is a file's directory type, block count and sector chain, then the free block
count, then the sectors marked used in the BAM for each track.

`real-1571-allocation.txt` is the same experiment on a 1571 in double-sided mode (the
program first sends `U0>M1`), where file `H` fits by crossing onto side two.
`real-1581-allocation.txt` is from a 1581: format as `ALLOC81,A8`, save twenty 100-byte
files `S1` to `S20`, scratch `S3` and `S7`, save four 50798-byte files `BIG1` to `BIG4`
(which fill the gaps and cross tracks), then validate. Both also come from Rift64
(`tests/fixtures/allocation/`), recorded with VICE 3.7.1's true drive emulation.

`simscreen/` holds three programs that each draw a steady frame (text with both scrolls, 24 rows
and 38 columns; a multicolour bitmap with expanded sprites; ECM with the top and bottom border
opened). `tests/test_sim.py` checks the simulator's Screen against VICE 3.7.1's picture of each,
pixel for pixel, and keeps a digest of each so the check also runs without VICE.
