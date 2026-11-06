"""Git for a project (CBM prg Studio's Git: status, init, log, commit, add, add all, remove, diff,
and the ignore list), using the `git` command.

A project's repository is the one its folder is in (it may be higher up). Commits use the author and
email from Preferences when they're set, otherwise git's own settings. As in CBM prg Studio, a new
ignore list (.gitignore) is made from a template whose {now}, {author}, {comment} and {project}
are filled in.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import host

DEFAULT_IGNORE = """# {project}: Git ignore list, made {now}
# Files Git leaves alone: what the build makes, and backups.
*.prg
*.vs
*.lst
*.dbg
*.p00
*.bak
*.exo
"""

STATES = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "?": "untracked",
          "U": "conflicted", "T": "changed type"}


class GitError(RuntimeError):
    pass


@dataclass
class FileStatus:
    path: Path             # absolute
    staged: str            # git's two status letters: what's added for the next commit...
    unstaged: str          # ...and what's changed since

    @property
    def letter(self) -> str:
        """One letter for the file list: ? untracked, A added, M modified, D deleted, U conflict."""
        if self.staged == "?":
            return "?"
        if "U" in (self.staged, self.unstaged):
            return "U"
        if self.staged == "A":
            return "A"
        if "D" in (self.staged, self.unstaged):
            return "D"
        return "M"

    @property
    def description(self) -> str:
        if self.staged == "?":
            return "untracked (not in the repository)"
        parts = []
        if self.staged.strip():
            parts.append(f"{STATES.get(self.staged, self.staged)}, staged")
        if self.unstaged.strip():
            parts.append(f"{STATES.get(self.unstaged, self.unstaged)}, not staged")
        return "; ".join(parts)


@dataclass
class Commit:
    hash: str
    author: str
    date: str
    subject: str


def available() -> bool:
    return host.which("git") is not None


class Repo:
    def __init__(self, folder: Path, author: str = "", email: str = ""):
        self.folder = Path(folder)
        self.author, self.email = author.strip(), email.strip()

    # ---------------------------------------------------------------- running git
    def _git(self, *args: str, check: bool = True, identity: bool = False) -> str:
        if not available():
            raise GitError("git isn't installed (sudo apt install git)")
        cmd = ["git"]
        if identity:
            if self.author:
                cmd += ["-c", f"user.name={self.author}"]
            if self.email:
                cmd += ["-c", f"user.email={self.email}"]
        cmd += list(args)
        try:
            p = host.run(cmd, cwd=self.folder, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise GitError(f"git {args[0]} didn't run: {e}") from None
        if check and p.returncode != 0:
            msg = (p.stderr or p.stdout).strip()
            if "Please tell me who you are" in msg or "empty ident" in msg:
                msg = "Git needs your name and email for commits: set them in Preferences → Git"
            raise GitError(msg or f"git {args[0]} failed")
        return p.stdout

    @property
    def root(self) -> Path | None:
        """The top of the repository the folder is in, or None if it isn't in one."""
        if not available() or not self.folder.is_dir():
            return None
        try:
            out = self._git("rev-parse", "--show-toplevel")
        except GitError:
            return None
        return Path(out.strip())

    def is_repo(self) -> bool:
        return self.root is not None

    def _rel(self, paths) -> list[str]:
        return [str(Path(p)) for p in paths]

    # ---------------------------------------------------------------- what's there
    def branch(self) -> str:
        out = self._git("branch", "--show-current", check=False).strip()
        return out or "(no branch)"

    def status(self) -> dict[Path, FileStatus]:
        """Files that differ from the last commit (or aren't in it), by absolute path."""
        root = self.root
        if root is None:
            return {}
        out = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        result: dict[Path, FileStatus] = {}
        items = out.split("\0")
        i = 0
        while i < len(items):
            e = items[i]
            if len(e) < 4:
                i += 1
                continue
            x, y, name = e[0], e[1], e[3:]
            if x in "RC":                    # a rename: the old name comes next
                i += 1
            key = (root / name).resolve()
            if not (key in result and x == "?"):     # removed from the repository but kept: show the removal
                result[key] = FileStatus(key, x, y)
            i += 1
        return result

    def log(self, path: Path | None = None, count: int = 100) -> list[Commit]:
        if self._git("rev-parse", "--verify", "HEAD", check=False).strip() == "":
            return []                        # nothing committed yet
        args = ["log", f"-{count}", "--date=format:%Y-%m-%d %H:%M", "--pretty=format:%h%x1f%an%x1f%ad%x1f%s"]
        if path is not None:
            args += ["--follow", "--", str(path)]
        out = self._git(*args)
        return [Commit(*ln.split("\x1f", 3)) for ln in out.splitlines() if ln.count("\x1f") == 3]

    def diff(self, path: Path | None = None) -> str:
        """Changes not yet committed (staged and not), against the last commit."""
        has_head = self._git("rev-parse", "--verify", "HEAD", check=False).strip() != ""
        args = ["diff", "HEAD"] if has_head else ["diff", "--cached"]
        if path is not None:
            args += ["--", str(path)]
        out = self._git(*args)
        if path is not None and not out:
            st = self.status().get(Path(path).resolve())
            if st and st.staged == "?":
                text = Path(path).read_text(errors="replace")
                return f"New file {Path(path).name} (untracked):\n" + "".join("+" + ln for ln in text.splitlines(True))
        return out

    # ---------------------------------------------------------------- changing it
    def init(self, project_name: str = "", author: str = "", comment: str = "",
             ignore_template: str = DEFAULT_IGNORE) -> str:
        out = self._git("init")
        ignore = self.folder / ".gitignore"
        if not ignore.exists() and ignore_template.strip():
            text = (ignore_template.replace("{now}", time.strftime("%Y-%m-%d %H:%M"))
                    .replace("{author}", author or self.author).replace("{comment}", comment)
                    .replace("{project}", project_name or self.folder.name))
            ignore.write_text(text if text.endswith("\n") else text + "\n")
        return out.strip()

    def add(self, paths) -> None:
        self._git("add", "--", *self._rel(paths))

    def add_all(self) -> None:
        self._git("add", "--all")

    def remove(self, paths) -> None:
        """Take files out of the repository (from the next commit on), keeping them on disk."""
        self._git("rm", "--cached", "--quiet", "--", *self._rel(paths))

    def commit(self, message: str, paths=None, add_first: bool = True) -> str:
        """Commit the staged changes, or just `paths` (added first if `add_first`). Returns the
        new commit's short hash."""
        if not message.strip():
            raise GitError("Write a message for the commit")
        if paths:
            if add_first:
                self.add(paths)
            self._git("commit", "-m", message, "--", *self._rel(paths), identity=True)
        else:
            if add_first:
                self._git("add", "--update")         # changes to files already in the repository
            self._git("commit", "-m", message, identity=True)
        return self._git("rev-parse", "--short", "HEAD").strip()
