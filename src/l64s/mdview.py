"""Reading the tutorials' Markdown for the Tutorials tab: the few kinds of block they use (headings,
paragraphs, bullet and numbered lists, code blocks, pictures), each with its inline runs (plain,
bold, italic, code, links).

Not a general Markdown reader: just enough for docs/tutorials, which keep to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

def _data_root() -> Path:
    """Where docs/ and examples/ are: beside the source (a checkout), or installed with the package
    (the Flatpak puts them in /app/share/linux64studio; a pip install under <prefix>/share)."""
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[4] / "share" / "linux64studio" if len(here.parents) > 4 else None):
        if root is not None and (root / "docs" / "tutorials").is_dir():
            return root
    return here.parents[2]


DOCS = _data_root() / "docs"
TUTORIALS = DOCS / "tutorials"
EXAMPLES = _data_root() / "examples" / "tutorials"


@dataclass
class Run:
    text: str
    style: str = ""          # "", "bold", "italic", "code", "link"
    url: str = ""


@dataclass
class Block:
    kind: str                # heading, para, bullet, number, code, image
    runs: list[Run] = field(default_factory=list)
    level: int = 0           # a heading's level; a list item's number
    text: str = ""           # a code block's text; an image's alt text
    url: str = ""            # an image's file


_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|(?<![\w*])\*([^*\s][^*]*?)\*(?!\w)")


def inline(text: str) -> list[Run]:
    """Bold (**), code (`), links ([text](url)) and italic (*) in a line of text."""
    out: list[Run] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(Run(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(Run(m.group(1), "bold"))
        elif m.group(2) is not None:
            out.append(Run(m.group(2), "code"))
        elif m.group(3) is not None:
            out.append(Run(m.group(3), "link", m.group(4)))
        else:
            out.append(Run(m.group(5), "italic"))
        pos = m.end()
    if pos < len(text):
        out.append(Run(text[pos:]))
    return out


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    lines = text.splitlines()
    i = 0
    para: list[str] = []

    def flush():
        if para:
            blocks.append(Block("para", inline(" ".join(s.strip() for s in para))))
            para.clear()
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append(Block("code", text="\n".join(body)))
            i += 1
            continue
        if not stripped or stripped.startswith("<!--"):
            flush()
            i += 1
            continue
        m = re.match(r"(#{1,6})\s+(.*)", stripped)
        if m:
            flush()
            blocks.append(Block("heading", inline(m.group(2)), level=len(m.group(1))))
            i += 1
            continue
        m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if m:
            flush()
            blocks.append(Block("image", text=m.group(1), url=m.group(2)))
            i += 1
            continue
        m = re.match(r"(\s*)([*-]|\d+\.)\s+(.*)", line)
        if m and not line.startswith("    " * 2):
            flush()
            item = [m.group(3)]
            i += 1
            while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() and \
                    not re.match(r"\s*([*-]|\d+\.)\s", lines[i]):
                item.append(lines[i].strip())                   # the item's next lines
                i += 1
            number = int(m.group(2)[:-1]) if m.group(2)[0].isdigit() else 0
            blocks.append(Block("number" if number else "bullet", inline(" ".join(item)), level=number))
            continue
        para.append(line)
        i += 1
    flush()
    return blocks


def example_of(text: str) -> str | None:
    """The example project a tutorial names (<!-- example: 2-assembler -->)."""
    m = re.search(r"<!--\s*example:\s*(\S+)\s*-->", text)
    return m.group(1) if m else None


def title_of(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def tutorials() -> list[Path]:
    """The tutorials, in order (the index first)."""
    if not TUTORIALS.is_dir():
        return []
    def number(p: Path):
        head = p.name.split("-", 1)[0]
        return (int(head) if head.isdigit() else 999, p.name)       # 10-... after 9-...
    files = sorted((p for p in TUTORIALS.glob("*.md") if p.name != "README.md"), key=number)
    index = TUTORIALS / "README.md"
    return ([index] if index.exists() else []) + files
