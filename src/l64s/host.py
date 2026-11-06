"""Running programs on the computer, from a normal install or from inside the Flatpak.

Linux64Studio runs other programs: VICE, cc65, Java (Kick Assembler), GoatTracker's tools, git,
RetroDebugger, user tools. Inside a Flatpak sandbox they aren't there (the sandbox has the GNOME
runtime, not the host's /usr), so every one is started on the host with ``flatpak-spawn --host``,
and whether one is installed is asked of the host. Outside a Flatpak all of this is the plain
subprocess and shutil calls.

Files: the home folder is shared (projects, ~/.local/share, ~/.config), so paths there are the
same inside and out. The host's /usr is seen at /run/host/usr (``host_path``), for VICE's ROMs and
cc65's headers. The sandbox's /tmp is its own, so a file handed to a host program goes in
``scratch_dir()`` instead.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

FLATPAK = Path("/.flatpak-info").exists()
_which: dict[str, str | None] = {}


def wrap(args: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None) -> list[str]:
    """The command line that runs args on the host (unchanged outside a Flatpak)."""
    if not FLATPAK:
        return [str(a) for a in args]
    out = ["flatpak-spawn", "--host"]
    if cwd is not None:
        out.append(f"--directory={cwd}")
    for k, v in (env or {}).items():
        out.append(f"--env={k}={v}")
    return out + [str(a) for a in args]


def run(args: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None,
        **kw) -> subprocess.CompletedProcess:
    """subprocess.run on the host."""
    if FLATPAK:
        return subprocess.run(wrap(args, cwd, env), **kw)
    return subprocess.run([str(a) for a in args], cwd=cwd, env={**os.environ, **env} if env else None, **kw)


def popen(args: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None,
          **kw) -> subprocess.Popen:
    """subprocess.Popen on the host. Ending the Popen (terminate, kill) ends the host program too."""
    if FLATPAK:
        return subprocess.Popen(wrap(args, cwd, env), **kw)
    return subprocess.Popen([str(a) for a in args], cwd=cwd, env={**os.environ, **env} if env else None, **kw)


def which(name: str) -> str | None:
    """Where a program is on the host (a name on the PATH, or a path to an executable file)."""
    if not name:
        return None
    if not FLATPAK:
        found = shutil.which(name)
        if found:
            return found
        p = Path(name).expanduser()
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None
    if name not in _which:
        if "/" in name:
            ok = subprocess.run(wrap(["test", "-x", str(Path(name).expanduser())]),
                                capture_output=True).returncode == 0
            _which[name] = str(Path(name).expanduser()) if ok else None
        else:
            r = subprocess.run(wrap(["sh", "-c", 'command -v "$0"', name]), capture_output=True, text=True)
            _which[name] = r.stdout.strip() or None if r.returncode == 0 else None
    return _which[name]


def host_path(path: str | Path) -> Path:
    """A host system file (under /usr or /etc) as the sandbox sees it: /run/host/usr/... in the Flatpak."""
    p = Path(path)
    if FLATPAK and p.is_absolute() and p.parts[1:2] in (("usr",), ("etc",)):
        return Path("/run/host") / p.relative_to("/")
    return p


def scratch_dir() -> Path:
    """A folder for temporary files a host program reads (the sandbox's /tmp is its own)."""
    if FLATPAK:
        d = Path.home() / ".cache" / "linux64studio"
        d.mkdir(parents=True, exist_ok=True)
        return d
    import tempfile
    return Path(tempfile.gettempdir())


def data_home() -> Path:
    """~/.local/share (or $XDG_DATA_HOME): where tools/install-*.sh put Kick Assembler and RetroDebugger.
    The Flatpak points XDG_DATA_HOME into its own folder, so the host's is used there."""
    if FLATPAK:
        return Path(os.environ.get("HOST_XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def config_home() -> Path:
    """~/.config (or $XDG_CONFIG_HOME): settings and sessions, the same in the Flatpak as out of it."""
    if FLATPAK:
        return Path(os.environ.get("HOST_XDG_CONFIG_HOME", Path.home() / ".config"))
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
