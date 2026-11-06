from pathlib import Path

from l64s import host


def test_outside_a_flatpak_commands_run_as_they_are(monkeypatch):
    monkeypatch.setattr(host, "FLATPAK", False)
    assert host.wrap(["x64sc", Path("/home/me/game.prg")], cwd="/home/me") == ["x64sc", "/home/me/game.prg"]
    assert host.host_path("/usr/share/cc65/include") == Path("/usr/share/cc65/include")
    assert host.run(["sh", "-c", "echo $X"], env={"X": "hi"}, capture_output=True, text=True).stdout == "hi\n"
    assert host.which("sh") and host.which("no-such-program-l64s") is None


def test_inside_one_they_go_to_the_host(monkeypatch):
    monkeypatch.setattr(host, "FLATPAK", True)
    assert host.wrap(["x64sc", "-autostart", Path("/home/me/game.prg")], cwd="/home/me", env={"A": "1"}) == [
        "flatpak-spawn", "--host", "--directory=/home/me", "--env=A=1", "x64sc", "-autostart", "/home/me/game.prg"]
    assert host.host_path("/usr/share/cc65/include") == Path("/run/host/usr/share/cc65/include")
    assert host.host_path("/home/me/x") == Path("/home/me/x")             # (home is shared)
    assert host.data_home().name == "share" and host.config_home().name == ".config"
