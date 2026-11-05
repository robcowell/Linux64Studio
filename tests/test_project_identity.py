from l64s.project.model import load_project


def test_workspace_and_its_l64proj_are_one_project(tmp_path):
    ws = tmp_path / "Ch1.code-workspace"
    ws.write_text('{"folders": [{"path": "."}], "settings": {"kickassembler.startup": "main.asm"}}')
    before = load_project(ws)                    # no .l64proj yet: the workspace itself
    assert before.path == ws
    before.save()                                # settings saved: Ch1.l64proj now exists
    after_ws, after_proj = load_project(ws), load_project(tmp_path / "Ch1.l64proj")
    assert after_ws.path.suffix == ".l64proj"
    assert before.identity() == after_ws.identity() == after_proj.identity() == str(tmp_path / "Ch1.l64proj")
    assert before.old_identities() == [str(ws)]   # what it was remembered under before


def test_cbmprj(tmp_path):
    prj = tmp_path / "game.cbmprj"
    prj.write_text('<?xml version="1.0"?><Project><Files><Assembly><File>main.asm</File></Assembly></Files>'
                   '<BuildList><File>main.asm</File></BuildList></Project>')
    p = load_project(prj)
    assert p.identity() == str(tmp_path / "game.l64proj")
    assert p.old_identities() == [str(prj)]


def test_recent_projects_list_one_entry_per_project():
    from l64s.settings import Settings
    s = Settings(recent_projects=["/a/other.cbmprj", "/v/Ch1.code-workspace", "/b/x.l64proj"])
    s.add_recent("/v/Ch1.l64proj")               # its settings were saved since: replaces the workspace
    assert s.recent_projects == ["/v/Ch1.l64proj", "/a/other.cbmprj", "/b/x.l64proj"]
    s.add_recent("/a/other.cbmprj")
    assert s.recent_projects == ["/a/other.cbmprj", "/v/Ch1.l64proj", "/b/x.l64proj"]
    s.add_recent("/c/other.cbmprj")              # same name, another folder: a different project
    assert len(s.recent_projects) == 4
    for i in range(12):
        s.add_recent(f"/r/{i}.l64proj")
    assert len(s.recent_projects) == 10
