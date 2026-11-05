from pathlib import Path

import pytest

from l64s.project.filetree import build_tree


def shape(node, depth=0):
    out = []
    for c in node.children:
        out.append("  " * depth + c.name + ("/" if c.is_dir else ""))
        if c.is_dir:
            out += shape(c, depth + 1)
    return out


def test_folders_first_then_files_by_name(tmp_path):
    p = tmp_path / "game"
    files = [p / "main.asm", p / "Gfx" / "sprites.spt", p / "a.asm", p / "Gfx" / "Old" / "x.cst", p / "code" / "b.asm"]
    tree = build_tree(p, files)
    assert tree.name == "game"
    assert shape(tree) == ["code/", "  b.asm", "Gfx/", "  Old/", "    x.cst", "  sprites.spt", "a.asm", "main.asm"]


def test_build_list_first_in_build_order(tmp_path):
    p = tmp_path / "game"
    files = [p / n for n in ("zz.asm", "libA.asm", "main.asm", "notes.asm")]
    order = {(p / "main.asm").resolve(): 0, (p / "zz.asm").resolve(): 1, (p / "libA.asm").resolve(): 2}
    assert shape(build_tree(p, files, order)) == ["main.asm", "zz.asm", "libA.asm", "notes.asm"]


def test_library_outside_the_project_is_a_top_level_folder(tmp_path):
    p, lib = tmp_path / "Chapter1", tmp_path / "Library"
    files = [p / "Code" / "gameMain.asm", lib / "libMath.asm", lib / "Sub" / "libX.asm", p / "top.asm"]
    tree = build_tree(p, files, roots=[p, lib])
    assert shape(tree) == ["Code/", "  gameMain.asm", "../Library/", "  Sub/", "    libX.asm", "  libMath.asm",
                           "top.asm"]
    assert tree.find(lib.resolve()).name == "../Library"
    assert tree.find((lib / "Sub" / "libX.asm").resolve()).name == "libX.asm"


def test_book_vol2_workspace():
    ws = Path(__file__).parent / "book" / "c64editionvol2-main" / "Chapters" / "Chapter1" / "Ch1.code-workspace"
    if not ws.exists():
        pytest.skip("book corpus not present")
    from l64s.project.model import load_project
    proj = load_project(ws)
    tree = build_tree(proj.directory, proj.all_files(),
                      roots=[proj.directory] + [(proj.directory / d) for d in proj.lib_dirs] + proj.referenced_dirs())
    top = [c.name for c in tree.children]
    assert top[:2] == ["Code", "../Library"]


def test_empty_folders_are_shown(tmp_path):
    p = tmp_path / "game"
    tree = build_tree(p, [p / "main.asm"], folders=[p / "gfx", p / "gfx" / "new", p / "music"])
    assert shape(tree) == ["gfx/", "  new/", "music/", "main.asm"]


def test_project_all_folders_skips_hidden_and_output(tmp_path):
    from l64s.project.model import Project
    for d in ("gfx/new", ".git/objects", "Output", "build/x", "music"):
        (tmp_path / d).mkdir(parents=True)
    proj = Project(path=tmp_path / "g.l64proj", name="g")
    assert [f.relative_to(tmp_path).as_posix() for f in proj.all_folders()] == ["gfx", "gfx/new", "music"]
