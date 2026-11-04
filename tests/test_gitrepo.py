"""Git for a project."""
import pytest

from l64s.gitrepo import GitError, Repo, available

pytestmark = pytest.mark.skipif(not available(), reason="git isn't installed")


def repo(tmp_path):
    (tmp_path / "game").mkdir()
    r = Repo(tmp_path / "game", "Test Author", "test@example.com")
    return r


def test_init_and_ignore(tmp_path):
    r = repo(tmp_path)
    assert not r.is_repo()
    r.init("My Game", "Rob", "", "# {project} by {author}\n*.prg\n")
    assert r.is_repo() and r.root == (tmp_path / "game").resolve()
    assert (tmp_path / "game" / ".gitignore").read_text() == "# My Game by Rob\n*.prg\n"
    assert r.log() == [] and r.diff() == ""


def test_status_add_commit_log_diff(tmp_path):
    r = repo(tmp_path)
    r.init("g")
    main = tmp_path / "game" / "main.asm"
    main.write_text("        rts\n")
    (tmp_path / "game" / "game.prg").write_bytes(b"\x01\x08")              # ignored
    st = r.status()
    assert {p.name: s.letter for p, s in st.items()} == {"main.asm": "?", ".gitignore": "?"}
    assert "untracked" in st[main.resolve()].description
    assert "+        rts" in r.diff(main)
    r.add([main])
    assert r.status()[main.resolve()].letter == "A"
    h = r.commit("First", [main])
    assert len(h) >= 7 and main.resolve() not in r.status()
    log = r.log()
    assert [(c.subject, c.author) for c in log] == [("First", "Test Author")]
    main.write_text("        nop\n        rts\n")
    assert r.status()[main.resolve()].letter == "M"
    assert "+        nop" in r.diff() and "+        nop" in r.diff(main)
    r.commit("Second")                                                     # add_first stages the change
    assert [c.subject for c in r.log(main)] == ["Second", "First"]
    with pytest.raises(GitError, match="message"):
        r.commit("  ")


def test_add_all_and_remove(tmp_path):
    r = repo(tmp_path)
    r.init("g")
    a, b = tmp_path / "game" / "a.asm", tmp_path / "game" / "b.asm"
    a.write_text("a\n")
    b.write_text("b\n")
    r.add_all()
    r.commit("both")
    r.remove([b])
    assert r.status()[b.resolve()].staged == "D" and b.exists()              # kept on disk
    r.commit("drop b")
    assert r.status()[b.resolve()].letter == "?"


def test_sub_folder_of_a_repository(tmp_path):
    r = repo(tmp_path)
    r.init("g")
    sub = tmp_path / "game" / "levels"
    sub.mkdir()
    inner = Repo(sub)
    assert inner.is_repo() and inner.root == (tmp_path / "game").resolve()
