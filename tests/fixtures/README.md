# Test fixtures

`real-1541-allocation.txt` comes from Rift64 (`tests/fixtures/allocation/real-1541.txt`). It is
where a real 1541's DOS put everything (run by VICE 3.7.1's true drive emulation) after this
BASIC program: format the disk as `ALLOC TEST,AT`, save files `A` to `H` of 100, 7618, 760, 506,
50798, 50798, 50798 and 20000 bytes from $1000 (each plus its 2-byte load address), scratch `A`
after the first three are saved, then validate. The disk fills up before `H` is finished.

Each line is a file's directory type, block count and sector chain, then the free block
count, then the sectors marked used in the BAM for each track.
