from l64s.statusbar import EditorState, fields


def texts(s):
    return [f.text for f in fields(s)]


def test_assembler_file_in_a_cbm_project_with_git():
    s = EditorState(line=12, column=4, git_branch="master", has_project=True)
    assert texts(s) == ["CAPS", "INS", "Word Wrap: Off", "Line: 12", "Col: 4", "Target: C64", "Git: master",
                        "Using native assembler", "Using VICE debugger"]
    caps = fields(s)[0]
    assert not caps.lit and "off" in caps.tooltip


def test_basic_file_shows_auto_line_numbers():
    s = EditorState(basic=True, auto_line_numbers=False, caps_lock=True, overwrite=True, word_wrap=True,
                    kickass=True, has_project=True)
    t = texts(s)
    assert t[:3] == ["CAPS", "OVR", "Word Wrap: On"] and fields(s)[0].lit
    assert "Auto Line Num: Off" in t and "Git Repo: No" in t and "Using Kick Assembler" in t


def test_no_project_leaves_out_project_fields():
    t = texts(EditorState())
    assert "Auto Line Num: On" not in t
    assert not any(x.startswith(("Git", "Using native", "Using Kick")) for x in t)
    assert t[-1] == "Using VICE debugger"


def test_toggles():
    assert {f.key for f in fields(EditorState(basic=True)) if f.toggle} == {"overwrite", "wrap", "autonum"}
