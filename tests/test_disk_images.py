"""D64, D71 and D81 images, checked against real 1541, 1571 and 1581 drives (fixtures from Rift64)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.disk.image import (D64_FORMAT, D71_FORMAT, D81_FORMAT, FORMATS, DiskError, DiskImage, build_disk,
                             detect_format, format_for)

FIXTURES = Path(__file__).parent / "fixtures"
needs_c1541 = pytest.mark.skipif(not shutil.which("c1541"), reason="VICE's c1541 isn't installed")

STEPS = [("format", "alloc test", "at"),
         ("save", "a", 100), ("save", "b", 7618), ("save", "c", 760), ("scratch", "a"),
         ("save", "d", 506), ("save", "e", 50798), ("save", "f", 50798), ("save", "g", 50798),
         ("save", "h", 20000), ("validate",)]
STEPS_1581 = ([("format", "alloc81", "a8")] + [("save", f"s{i}", 100) for i in range(1, 21)]
              + [("scratch", "s3"), ("scratch", "s7")] + [("save", f"big{i}", 50798) for i in range(1, 5)]
              + [("validate",)])


def replay(kind, steps):
    d = DiskImage(FORMATS[kind])
    for step in steps:
        if step[0] == "format":
            d.format(step[1], step[2])
        elif step[0] == "save":
            try:
                d.add_file(step[1], b"\x00\x10" + bytes(step[2]))   # SAVE from $1000
            except DiskError:
                pass  # disk full: the real drive's partial file is removed by the validate
        elif step[0] == "scratch":
            d.delete(step[1])
        elif step[0] == "validate":
            d.validate()
    return d


@pytest.mark.parametrize("kind,steps,fixture", [
    ("d64", STEPS, "real-1541-allocation.txt"),
    ("d71", STEPS, "real-1571-allocation.txt"),
    ("d81", STEPS_1581, "real-1581-allocation.txt"),
])
def test_allocation_matches_real_drive(kind, steps, fixture):
    """Every file's sector chain, the free count and the whole BAM, line for line."""
    assert replay(kind, steps).allocation_map() == (FIXTURES / fixture).read_text()


@pytest.mark.parametrize("fmt,size,free,dos", [
    (D64_FORMAT, 174848, 664, b"2A"), (D71_FORMAT, 349696, 1328, b"2A"), (D81_FORMAT, 819200, 3160, b"3D"),
])
def test_blank_disks(fmt, size, free, dos):
    d = DiskImage(fmt)
    d.format("blank disk", "bd")
    assert len(d.data) == size == fmt.image_size
    assert d.blocks_free == free == fmt.total_free
    assert d.disk_name == "BLANK DISK" and d.disk_id == "BD"
    assert d.entries() == []
    hdr = d.sector(*fmt.header)
    assert bytes(hdr[fmt.dos_type_offset:fmt.dos_type_offset + 2]) == dos


def test_d71_header_and_side_two_bam():
    d = DiskImage(D71_FORMAT)
    d.format("two sides", "ts")
    hdr = d.sector(18, 0)
    assert hdr[3] == 0x80                                    # double-sided flag
    assert hdr[0xDD] == 21 and hdr[0xDD + 17] == 0             # track 36 free; track 53 kept in use
    assert all(not d.is_free(53, s) for s in range(19))


def test_d81_header_and_bam_sectors():
    d = DiskImage(D81_FORMAT)
    d.format("big disk", "bd")
    hdr = d.sector(40, 0)
    assert bytes(hdr[0:3]) == b"\x28\x03\x44"                # directory at 40/3, "D"
    for s, link in ((1, b"\x28\x02"), (2, b"\x00\xff")):
        bam = d.sector(40, s)
        assert bytes(bam[0:7]) == link + b"\x44\xbb" + b"BD" + b"\xc0"
    assert [s for s in range(40) if not d.is_free(40, s)] == [0, 1, 2, 3]


@pytest.mark.parametrize("kind", ["d64", "d71", "d81"])
def test_roundtrip_and_reload(tmp_path, kind):
    prg = b"\x01\x08" + bytes(range(256)) * 200      # 202 blocks
    path = tmp_path / f"x.{kind}"
    build_disk(path, "round trip", "rt", [("game", prg, "prg"), ("data", b"x" * 1000, "seq")])
    d = DiskImage.load(path)
    assert d.fmt.kind == kind
    assert d.read_file("game") == prg and d.read_file("data") == b"x" * 1000
    assert d.blocks_free == FORMATS[kind].total_free - 202 - 4


def test_large_file_only_fits_bigger_disks(tmp_path):
    big = b"\x00\x10" + bytes(254 * 1000)          # 1001 blocks: too big for a 1541
    with pytest.raises(DiskError):
        build_disk(tmp_path / "x.d64", "x", "00", [("big", big, "prg")])
    for kind in ("d71", "d81"):
        d = build_disk(tmp_path / f"x.{kind}", "x", "00", [("big", big, "prg")])
        assert d.read_file("big") == big


def test_d81_directory_grows_one_sector_at_a_time():
    d = DiskImage(D81_FORMAT)
    for i in range(20):
        d.add_file(f"f{i}", b"\x01\x08\x00")
    assert list(d._dir_chain()) == [(40, 3), (40, 4), (40, 5)]


def test_format_detection():
    assert format_for("a.D71") is D71_FORMAT
    with pytest.raises(DiskError):
        format_for("a.t64")
    assert detect_format(bytes(174848)) is D64_FORMAT
    assert detect_format(bytes(175531)) is D64_FORMAT        # with error bytes
    assert detect_format(bytes(349696)) is D71_FORMAT
    assert detect_format(bytes(819200)) is D81_FORMAT
    with pytest.raises(DiskError):
        detect_format(bytes(1000))


@needs_c1541
@pytest.mark.parametrize("kind,free", [("d71", 1328), ("d81", 3160)])
def test_vice_c1541_reads_d71_and_d81(tmp_path, kind, free):
    prg = b"\x01\x08" + bytes(range(256)) * 300
    img = tmp_path / f"t.{kind}"
    build_disk(img, "test disk", "td", [("game", prg, "prg")])
    listing = subprocess.run(["c1541", "-attach", str(img), "-list"], capture_output=True, text=True).stdout.lower()
    blocks = (len(prg) + 253) // 254
    assert '"game"' in listing and f"{free - blocks} blocks free" in listing, listing
    out = tmp_path / "game.prg"
    subprocess.run(["c1541", "-attach", str(img), "-read", "game", str(out)], check=True, capture_output=True)
    assert out.read_bytes() == prg
    extra = tmp_path / "extra.prg"
    extra.write_bytes(b"\x00\xc0" + bytes(30000))
    subprocess.run(["c1541", "-attach", str(img), "-write", str(extra), "extra"], check=True, capture_output=True)
    again = DiskImage.load(img)
    assert again.read_file("game") == prg and again.read_file("extra") == extra.read_bytes()


def test_project_writes_d81(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text('10 print "hi"\n')
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas"], executable="t.prg",
                   disk_image="t.d81")
    res = build_project(proj)
    assert res.ok and res.disk.suffix == ".d81"
    assert DiskImage.load(res.disk).fmt is D81_FORMAT


def test_project_rejects_unknown_image_type(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text('10 print "hi"\n')
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas"], executable="t.prg",
                   disk_image="t.dsk")
    res = build_project(proj)
    assert not res.ok and ".d64, .d71 or .d81" in res.diagnostics[-1].message
