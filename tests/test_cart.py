import shutil
import subprocess

import pytest

from l64s.cart.crt import CART_TYPES, CartError, Image, build_cartridge, cartridge_from_files, load_crt

needs_cartconv = pytest.mark.skipif(not shutil.which("cartconv"), reason="VICE's cartconv isn't installed")


def pattern(kb: int) -> bytes:
    return bytes((i // 1024 + i // 8192 * 7) & 255 for i in range(kb * 1024))


def image(*regions) -> Image:
    mem, used = bytearray([0xFF]) * 0x10000, bytearray(0x10000)
    for addr, data in regions:
        mem[addr:addr + len(data)] = data
        used[addr:addr + len(data)] = b"\x01" * len(data)
    return Image(mem, used)


def our_cart(kind: str, b: bytes, name: str) -> bytes:
    if kind == "ultimax":
        regions = {4096: [(0xF000, b)], 8192: [(0xE000, b)]}.get(len(b), [(0x8000, b[:8192]), (0xE000, b[8192:])])
        return build_cartridge(kind, image(*regions), name).to_bytes()
    if kind == "easyflash":
        return build_cartridge(kind, image((0x8000, b[:8192]), (0xE000, b[8192:16384])), name, [b[16384:]]).to_bytes()
    if kind in ("normal8", "normal16"):
        return build_cartridge(kind, image((0x8000, b)), name).to_bytes()
    return build_cartridge(kind, image((0x8000, b[:8192])), name, [b[8192:]] if len(b) > 8192 else []).to_bytes()


@needs_cartconv
@pytest.mark.parametrize("kind,cartconv_type,kb", [
    ("normal8", "normal", 8), ("normal16", "normal", 16), ("ultimax", "ulti", 4), ("ultimax", "ulti", 8),
    ("ultimax", "ulti", 16), ("magicdesk", "md", 32), ("magicdesk", "md", 128), ("magicdesk", "md", 512),
    ("ocean", "ocean", 128), ("ocean", "ocean", 256), ("ocean", "ocean", 512), ("easyflash", "easy", 1024),
])
def test_matches_vice_cartconv(tmp_path, kind, cartconv_type, kb):
    b = pattern(kb)
    (tmp_path / "in.bin").write_bytes(b)
    subprocess.run(["cartconv", "-q", "-t", cartconv_type, "-i", str(tmp_path / "in.bin"),
                    "-o", str(tmp_path / "out.crt"), "-n", "Test Cart"], check=True, capture_output=True)
    assert our_cart(kind, b, "Test Cart") == (tmp_path / "out.crt").read_bytes()


@needs_cartconv
def test_easyflash_leaves_out_erased_chips_like_cartconv(tmp_path):
    b = bytearray(b"\xff" * 1048576)
    b[:16384] = pattern(16)
    (tmp_path / "in.bin").write_bytes(bytes(b))
    subprocess.run(["cartconv", "-q", "-t", "easy", "-i", str(tmp_path / "in.bin"), "-o", str(tmp_path / "o.crt"),
                    "-n", "X"], check=True, capture_output=True)
    assert our_cart("easyflash", bytes(b), "X") == (tmp_path / "o.crt").read_bytes()


def test_header_and_reload(tmp_path):
    cart = build_cartridge("ocean", image((0x8000, pattern(8))), "My Game", [pattern(8) * 20])
    cart.save(tmp_path / "g.crt")
    raw = (tmp_path / "g.crt").read_bytes()
    assert raw[:16] == b"C64 CARTRIDGE   " and raw[16:20] == b"\0\0\0\x40" and raw[20:22] == b"\x01\x00"
    back = load_crt(tmp_path / "g.crt")
    assert (back.hardware, back.exrom, back.game, back.name) == (5, 0, 0, "My Game")
    assert len(back.chips) == 32 and back.chips[16].address == 0xA000     # 256K Ocean
    assert back.chips[1].data == pattern(8)


@pytest.mark.parametrize("kind,regions,msg", [
    ("normal8", [(0x0801, b"\x00")], "outside the 8K cartridge ROM"),
    ("normal8", [(0x8000, bytes(8193))], "outside"),
    ("ultimax", [(0x8000, b"\x00")], "needs code at $E000"),
    ("easyflash", [(0x8000, b"\x00")], "Ultimax mode"),
])
def test_errors(kind, regions, msg):
    with pytest.raises(CartError, match=msg.replace("$", r"\$")):
        build_cartridge(kind, image(*regions))


def test_too_many_banks():
    with pytest.raises(CartError, match="too many"):
        build_cartridge("ocean", image((0x8000, b"\x00")), "", [bytes(8192 * 64)])
    with pytest.raises(CartError, match="no room"):
        build_cartridge("normal8", image((0x8000, b"\x00")), "", [b"\x00"])
    with pytest.raises(CartError, match="Unknown"):
        build_cartridge("nes", image((0x8000, b"\x00")))


def test_banks_from_prg_files_drop_the_load_address(tmp_path):
    prg = tmp_path / "boot.prg"
    prg.write_bytes(b"\x00\x80" + b"\xEA" * 10)
    level = tmp_path / "level.prg"
    level.write_bytes(b"\x00\x80" + b"\x2A" * 100)
    cart = cartridge_from_files("magicdesk", prg, "t", [level])
    assert cart.chips[1].data[:100] == b"\x2A" * 100 and cart.chips[1].data[100] == 0xFF
    assert len(cart.chips) == 4  # padded to 32K


def test_template_project_builds_a_cartridge(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import new_project
    proj = new_project(tmp_path / "c", "mycart", cartridge=True)
    res = build_project(proj)
    assert res.ok, res.log
    cart = load_crt(res.cart)
    assert (cart.hardware, cart.exrom, cart.game) == (0, 0, 1)
    assert cart.chips[0].data[4:9] == b"\xc3\xc2\xcd\x38\x30"          # CBM80
    assert res.run_target(proj) == res.cart


def test_cartridge_problems_fail_the_build(tmp_path):
    from l64s.project.build import build_project
    from l64s.project.model import Project
    (tmp_path / "m.asm").write_text("*=$0801\n rts\n")
    proj = Project(path=tmp_path / "t.l64proj", name="t", build_list=["m.asm"], executable="t.prg",
                   cart_type="normal8")
    res = build_project(proj)
    assert not res.ok and "outside the 8K cartridge ROM" in res.diagnostics[-1].message


def test_cbmprj_cartridge_settings_are_imported(tmp_path):
    from l64s.project.model import load_project
    (tmp_path / "c.cbmprj").write_text("""<?xml version="1.0" encoding="utf-8"?>
<Project><Executable>c.prg</Executable><Cartridge><CrtBuildingCartridge>True</CrtBuildingCartridge>
<CrtName>MY CART</CrtName><CrtCartType>0</CrtCartType><CrtEXROMActive>True</CrtEXROMActive>
<CrtGAMEActive>True</CrtGAMEActive></Cartridge><BuildList><FileName>m.asm</FileName></BuildList></Project>""")
    p = load_project(tmp_path / "c.cbmprj")
    assert (p.cart_type, p.cart_name) == ("normal16", "MY CART")


def test_l64cart_cli(tmp_path, capsys):
    from l64s.cart.cli import main
    prg = tmp_path / "c.prg"
    prg.write_bytes(b"\x00\x80" + bytes(100))
    assert main(["make", "normal8", str(prg), "-o", str(tmp_path / "c.crt"), "--name", "Hi"]) == 0
    assert main(["info", str(tmp_path / "c.crt")]) == 0
    out = capsys.readouterr().out
    assert "8K game" in out and "bank 0" in out
    assert main(["make", "ultimax", str(prg)]) == 1
    assert set(CART_TYPES) == {"normal8", "normal16", "ultimax", "magicdesk", "ocean", "easyflash"}
