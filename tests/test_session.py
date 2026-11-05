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


def test_project_state(tmp_path, monkeypatch):
    from l64s.session import MAX_PROJECTS, ProjectState, load_project_state, save_project_state
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load_project_state("/p/a.cbmprj") is None
    a = ProjectState(["/p/Gfx", "/p/Code"], [OpenFile("/p/main.asm", 12, 3), OpenFile("/p/s.spt", 0, 0)], 1)
    save_project_state("/p/a.cbmprj", a)
    save_project_state("/q/b.l64proj", ProjectState([], [], -1))
    got = load_project_state("/p/a.cbmprj")
    assert got.folders == ["/p/Code", "/p/Gfx"] and got.files == a.files and got.selected == 1
    assert load_project_state("/q/b.l64proj").folders == []      # all closed, not "never seen"
    for i in range(MAX_PROJECTS):
        save_project_state(f"/r/{i}.l64proj", ProjectState())
    assert load_project_state("/p/a.cbmprj") is None             # the oldest is dropped
    assert load_project_state(f"/r/{MAX_PROJECTS - 1}.l64proj").folders is None


def test_project_state_leaves_out_files_gone(tmp_path):
    from l64s.session import ProjectState
    a, b = tmp_path / "a.asm", tmp_path / "b.asm"
    b.write_text("")
    files, selected, missing = ProjectState(None, [OpenFile(str(a)), OpenFile(str(b))], 1).restorable()
    assert [f.path for f in files] == [str(b)] and selected == 0 and missing == ["a.asm"]
