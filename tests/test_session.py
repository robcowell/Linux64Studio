from l64s.session import OpenFile, Session


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = Session("/p/game.cbmprj", [OpenFile("/p/main.asm", 42, 7), OpenFile("/p/sprites.spt", 0, 0)], 1)
    s.save()
    assert Session.load() == s


def test_nothing_saved_or_bad_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert Session.load().empty
    Session.file().parent.mkdir(parents=True)
    Session.file().write_text("{not json")
    assert Session.load().empty


def test_restorable_leaves_out_what_has_gone(tmp_path):
    proj = tmp_path / "game.l64proj"
    proj.write_text("{}")
    a, c = tmp_path / "a.asm", tmp_path / "c.asm"
    a.write_text("")
    c.write_text("")
    s = Session(str(proj), [OpenFile(str(a)), OpenFile(str(tmp_path / "b.asm")), OpenFile(str(c), 5)], 2)
    r, missing = s.restorable()
    assert r.project == str(proj)
    assert [f.path for f in r.files] == [str(a), str(c)]
    assert r.selected == 1                       # still c.asm, which moved up a place
    assert missing == ["b.asm"]


def test_restorable_selected_file_gone(tmp_path):
    a = tmp_path / "a.asm"
    a.write_text("")
    r, missing = Session("", [OpenFile(str(a)), OpenFile(str(tmp_path / "gone.asm"))], 1).restorable()
    assert r.selected == 0 and missing == ["gone.asm"]


def test_restorable_project_gone(tmp_path):
    r, missing = Session(str(tmp_path / "old.cbmprj"), [], -1).restorable()
    assert r.empty and missing == ["old.cbmprj"]
