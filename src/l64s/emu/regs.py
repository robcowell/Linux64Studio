"""Setting the PC (or any register) so the next instruction runs once.

VICE 3.7.1 runs the first instruction after a register is written through the binary monitor, but
leaves the PC where it was: step once after setting the PC to an `inc $d020` and the border goes up
by one with the PC still on the inc; step again and it goes up again. Carrying on (resume) does the
same, so whatever was written, the instruction at the PC would run twice.

``land`` gets round it: it puts a JMP to the address in the cassette buffer, points the PC at the
JMP and runs until the PC gets to the address. The JMP may run twice, which does nothing; the
instruction at the address then runs once, when the program next goes on. The three bytes the JMP
borrows are put back.
"""
from __future__ import annotations

TRAMPOLINE = 0x033C        # the cassette buffer ($033C-$03FB), unused while no tape is in use


def land(monitor, pc: int, run_until_stopped) -> None:
    """Make the PC ``pc``, ready to run its instruction once. VICE must be stopped; registers other
    than the PC may have been written already. ``run_until_stopped()`` resumes VICE and waits for
    it to stop again (the caller's own event handling)."""
    m = monitor
    pc &= 0xFFFF
    saved = m.read_memory(TRAMPOLINE, TRAMPOLINE + 2)
    m.write_memory(TRAMPOLINE, bytes([0x4C, pc & 0xFF, pc >> 8]))
    cid = m.add_checkpoint(pc).id
    try:
        m.set_register("PC", TRAMPOLINE)
        run_until_stopped()
    finally:
        m.delete_checkpoint(cid)
        m.write_memory(TRAMPOLINE, saved)
