from l64s.breakpoints import Breakpoint, Breakpoints, address_for, line_addresses


def test_by_file_and_line(tmp_path):
    a, b = tmp_path / "main.asm", tmp_path / "lib.asm"
    bps = Breakpoints()
    bps.set_file(a, [(30, True), (10, False)])
    bps.set_file(b, [(5, True)])
    assert [(x.file[-8:], x.line, x.enabled) for x in bps.all()] == [
        ("/lib.asm", 5, True), ("main.asm", 10, False), ("main.asm", 30, True)]
    assert bps.for_file(a) == [(10, False), (30, True)]
    assert [x.line for x in bps.enabled()] == [5, 30] and len(bps) == 3
    bps.set_file(a, [])
    assert bps.for_file(a) == [] and len(bps) == 1


def test_on_off_remove(tmp_path):
    a = tmp_path / "main.asm"
    bps = Breakpoints([Breakpoint(str(a), 1), Breakpoint(str(a), 2)])
    assert bps.set_enabled(a, 2, False) and not bps.set_enabled(a, 99, False)
    assert bps.for_file(a) == [(1, True), (2, False)]
    bps.set_all_enabled(False)
    assert bps.enabled() == []
    bps.set_all_enabled(True)
    assert bps.remove(a, 1) and not bps.remove(a, 1)
    bps.clear()
    assert len(bps) == 0


def test_rename_and_forget_follow_files(tmp_path):
    bps = Breakpoints([Breakpoint(str(tmp_path / "gfx" / "a.asm"), 3), Breakpoint(str(tmp_path / "b.asm"), 4)])
    bps.rename(tmp_path / "gfx", tmp_path / "code")
    assert bps.for_file(tmp_path / "code" / "a.asm") == [(3, True)]
    bps.rename(tmp_path / "b.asm", tmp_path / "c.asm")
    assert bps.for_file(tmp_path / "c.asm") == [(4, True)]
    bps.forget(tmp_path / "code")
    assert [x.line for x in bps.all()] == [4]


def test_round_trip_and_bad_entries(tmp_path):
    bps = Breakpoints([Breakpoint(str(tmp_path / "a.asm"), 7, False)])
    again = Breakpoints.from_list(bps.to_list() + [{"line": 3}, {"file": "x", "line": "?"}, "junk"])
    assert again.all() == bps.all()


def test_addresses(tmp_path):
    f = str(tmp_path / "main.asm")
    la = line_addresses({0x0810: (f, 12), 0x0812: (f, 13), 0x0815: (f, 13), 0x0820: (f, 40)})
    assert la[(f, 13)] == 0x0812                          # the first byte from the line
    assert address_for(la, f, 12) == 0x0810
    assert address_for(la, f, 11) == 0x0810              # a comment above: the code below it
    assert address_for(la, f, 14) is None                # nothing within 20 lines... (40 is 26 on)
    assert address_for(la, f, 25) == 0x0820
