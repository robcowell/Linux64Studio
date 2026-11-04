import shutil
import subprocess
from pathlib import Path

import pytest

from l64s.disk.d64 import IMAGE_SIZE, SECTORS_PER_TRACK, D64, DiskError, build_disk, from_petscii_name, to_petscii_name

FIXTURE = Path(__file__).parent / "fixtures" / "real-1541-allocation.txt"
needs_c1541 = pytest.mark.skipif(not shutil.which("c1541"), reason="VICE's c1541 isn't installed")


def test_blank_disk():
    d = D64()
    d.format("my game", "ab")
    assert len(d.data) == IMAGE_SIZE
    assert d.blocks_free == 664
    assert d.disk_name == "MY GAME" and d.disk_id == "AB"
    bam = d.sector(18, 0)
    assert bytes(bam[0:4]) == b"\x12\x01\x41\x00"
    assert bytes(bam[0xA5:0xA7]) == b"2A"
    assert d.entries() == []


def test_add_read_delete():
    d = D64()
    data = bytes([0x01, 0x08]) + bytes(range(256)) * 3
    e = d.add_file("game", data)
    assert e.name == "GAME" and e.file_type == "prg" and e.closed
    assert e.blocks == (len(data) + 253) // 254
    assert (e.track, e.sector) == (17, 0)
    assert d.read_file("GAME") == data
    assert d.blocks_free == 664 - e.blocks
    with pytest.raises(DiskError, match="already"):
        d.add_file("game", data)
    d.delete("game")
    assert d.find("game") is None and d.blocks_free == 664


def test_empty_and_exact_sector_files():
    d = D64()
    d.add_file("empty", b"")
    assert d.read_file("empty") == b"" and d.find("empty").blocks == 1
    d.add_file("exact", bytes(254))
    assert d.read_file("exact") == bytes(254)
    used = 664 - d.blocks_free
    d.validate()  # the DOS's extra block for an exactly-full last sector is given back
    assert 664 - d.blocks_free == used - 1


def test_names():
    assert to_petscii_name("Hello 1") == b"HELLO 1"
    assert from_petscii_name(b"HELLO\xa0\xa0") == "HELLO"
    with pytest.raises(DiskError):
        to_petscii_name("x" * 17)
    with pytest.raises(DiskError):
        to_petscii_name("tab\there")


def test_directory_grows_with_interleave_3():
    d = D64()
    for i in range(20):
        d.add_file(f"f{i}", b"\x01\x08\x00")
    chain = list(d._dir_chain())
    assert chain == [(18, 1), (18, 4), (18, 7)]
    assert len(d.entries()) == 20


def test_disk_full():
    d = D64()
    with pytest.raises(DiskError, match="needs"):
        d.add_file("huge", bytes(254 * 700))


def _parse_fixture():
    files, used, free = {}, {}, None
    for line in FIXTURE.read_text().splitlines():
        parts = line.split()
        if parts[0] == "free":
            free = int(parts[1])
        elif parts[0] == "track":
            used[int(parts[1])] = [int(x) for x in parts[3].split(",")] if len(parts) > 3 else []
        else:
            chain = [tuple(int(v) for v in ts.split("/")) for ts in parts[parts.index("chain") + 1:]]
            files[parts[0]] = (int(parts[2], 16), int(parts[4]), chain)
    return files, used, free


def test_allocation_matches_a_real_1541():
    """Replays the real-drive experiment and compares every chain and the whole BAM."""
    d = D64()
    d.format("alloc test", "at")
    sizes = [("a", 100), ("b", 7618), ("c", 760), ("d", 506), ("e", 50798), ("f", 50798),
             ("g", 50798), ("h", 20000)]
    for name, size in sizes:
        if name == "d":
            d.delete("a")
        try:
            d.add_file(name, b"\x00\x10" + bytes(size))
        except DiskError:
            assert name == "h"  # the disk fills up before H, as on the real drive
    d.validate()

    files, used, free = _parse_fixture()
    entries = {e.name: e for e in d.entries()}
    assert sorted(entries) == sorted(n.upper() for n in files)
    for name, (ftype, blocks, chain) in files.items():
        e = entries[name.upper()]
        assert (0x80 | 2, e.blocks) == (ftype, blocks)
        assert list(d._file_chain(e.track, e.sector)) == chain, name
    assert d.blocks_free == free
    for t, sectors in used.items():
        assert [s for s in range(SECTORS_PER_TRACK[t]) if not d.is_free(t, s)] == sectors, f"track {t}"


@needs_c1541
def test_vice_c1541_reads_our_images(tmp_path):
    prg = bytes([0x01, 0x08]) + bytes(range(256)) * 40
    seq = b"hello\r" * 100
    img = tmp_path / "t.d64"
    build_disk(img, "test disk", "td", [("game", prg, "prg"), ("hiscores", seq, "seq")])
    listing = subprocess.run(["c1541", "-attach", str(img), "-list"], capture_output=True, text=True).stdout
    assert '"test disk ' in listing.lower() and "game" in listing.lower() and "hiscores" in listing.lower()
    blocks_free = 664 - (len(prg) + 253) // 254 - (len(seq) + 253) // 254
    assert f"{blocks_free} blocks free" in listing.lower()
    out = tmp_path / "game.prg"
    subprocess.run(["c1541", "-attach", str(img), "-read", "game", str(out)], check=True, capture_output=True)
    assert out.read_bytes() == prg
    # c1541 writing another file must not touch our blocks (so our BAM is right).
    extra = tmp_path / "extra.prg"
    extra.write_bytes(bytes([0x00, 0xC0]) + bytes(5000))
    subprocess.run(["c1541", "-attach", str(img), "-write", str(extra), "extra"], check=True, capture_output=True)
    again = D64.load(img)
    assert again.read_file("game") == prg and again.read_file("hiscores") == seq
    assert again.read_file("extra") == extra.read_bytes()


def test_project_build_writes_disk_image(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text('10 print "hi"\n')
    (tmp_path / "scores.seq").write_bytes(b"100\r200\r")
    proj = Project(path=tmp_path / "t.l64proj", name="my game", build_list=["main.bas"], executable="game.prg",
                   disk_image="out/game.d64", disk_id="mg",
                   disk_extra_files=[{"file": "scores.seq", "name": "scores", "type": "seq"}])
    res = build_project(proj)
    assert res.ok, res.log
    assert res.disk == (tmp_path / "out" / "game.d64").resolve()
    d = D64.load(res.disk)
    assert d.disk_name == "MY GAME" and d.disk_id == "MG"
    names = [(e.name, e.file_type) for e in d.entries()]
    assert names == [("GAME", "prg"), ("SCORES", "seq")]
    assert d.read_file("game") == res.prg.read_bytes()
    assert "blocks free" in res.log


def test_project_disk_errors_fail_the_build(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text('10 print "hi"\n')
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas"], executable="t.prg",
                   disk_image="t.d64", disk_extra_files=[{"file": "missing.seq", "name": "x"}])
    res = build_project(proj)
    assert not res.ok and "missing.seq" in res.diagnostics[-1].message


def test_single_file_build_skips_disk_image(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "main.bas").write_text('10 print "hi"\n')
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["main.bas"], executable="t.prg",
                   disk_image="t.d64")
    res = build_project(proj, only_file=tmp_path / "main.bas")
    assert res.ok and res.disk is None and not (tmp_path / "t.d64").exists()


def test_l64disk_cli(tmp_path, capsys):
    from l64s.disk.cli import main
    prg = tmp_path / "game.prg"
    prg.write_bytes(b"\x01\x08" + bytes(600))
    img = tmp_path / "g.d64"
    assert main(["create", str(img), "test,ab", str(prg)]) == 0
    assert main(["add", str(img), str(prg), "--name", "copy"]) == 0
    assert main(["list", str(img)]) == 0
    out = capsys.readouterr().out
    assert '"GAME"' in out and '"COPY"' in out and "BLOCKS FREE" in out
    assert main(["extract", str(img), "copy", "-o", str(tmp_path / "c.prg")]) == 0
    assert (tmp_path / "c.prg").read_bytes() == prg.read_bytes()
    assert main(["delete", str(img), "copy"]) == 0
    assert D64.load(img).find("copy") is None
    assert main(["extract", str(img), "nope"]) == 1
