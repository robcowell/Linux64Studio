"""Screen designer paths (CBM prg Studio's Screen Designer → Path): a line of points drawn on a
screen, describing how something (an enemy sprite, say) moves round it, turned into data for the
code to follow.

Points are pixels of the text screen (0,0 is its top left; 320×200 on a 40×25 screen). The data
is a point every `step` pixels along each line of the path (or just the points themselves), as
x, y pairs or as separate x and y tables, after an optional transform of each (x+24 to turn screen
pixels into sprite coordinates), as assembler bytes or words or BASIC DATA lines.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..datagen import DataGenError, Function

Point = tuple[int, int]


class PathError(ValueError):
    pass


@dataclass
class ScreenPath:
    points: list[Point] = field(default_factory=list)
    width: int = 0                  # CBM prg Studio's <Width>, kept as it was

    # ---------------------------------------------------------------- editing
    def add(self, p: Point) -> int:
        self.points.append(p)
        return len(self.points) - 1

    def insert_after(self, i: int, p: Point | None = None) -> int:
        """A new point after point i: halfway to the next one (or `p`)."""
        if p is None:
            a = self.points[i]
            b = self.points[i + 1] if i + 1 < len(self.points) else (a[0] + 8, a[1])
            p = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        self.points.insert(i + 1, p)
        return i + 1

    def move(self, i: int, p: Point):
        self.points[i] = p

    def delete(self, i: int):
        del self.points[i]

    def subdivide(self):
        """A point halfway along every line, for a smoother (with moving) or finer path."""
        out: list[Point] = []
        for a, b in zip(self.points, self.points[1:]):
            out += [a, ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)]
        if self.points:
            out.append(self.points[-1])
        self.points = out

    def nearest(self, p: Point, radius: float) -> int | None:
        best, best_d = None, radius
        for i, q in enumerate(self.points):
            d = math.hypot(q[0] - p[0], q[1] - p[1])
            if d <= best_d:
                best, best_d = i, d
        return best

    @property
    def lines(self) -> int:
        return max(0, len(self.points) - 1)


def _line(a: Point, b: Point, step: int) -> list[Point]:
    """Points every `step` pixels from a to b (a included, b not), along the longer axis."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = max(abs(dx), abs(dy))
    if n == 0:
        return []
    return [(a[0] + round(dx * k / n), a[1] + round(dy * k / n)) for k in range(0, n, max(1, step))]


def interpolate(path: ScreenPath, step: int = 1, first: int = 1, last: int | None = None,
                only_points: bool = False) -> list[Point]:
    """The positions to move through: lines `first` to `last` (1 is from point 0 to point 1)."""
    pts = path.points
    if len(pts) < 2:
        return list(pts)
    last = path.lines if last is None or last <= 0 else min(last, path.lines)
    first = max(1, first)
    if first > last:
        raise PathError(f"Line {first} comes after line {last}")
    if only_points:
        return list(pts[first - 1:last + 1])
    out: list[Point] = []
    for i in range(first, last + 1):
        out += _line(pts[i - 1], pts[i], step)
    out.append(pts[last])
    return out


def transform(points: list[Point], fx: str = "x", fy: str = "y") -> list[tuple[int, int]]:
    """Each point through the x and y transforms (x only uses x, y only y), rounded."""
    try:
        tx = Function(fx or "x", "x", need_var=False)
        ty = Function(fy or "y", "y", need_var=False)
        return [(math.floor(tx(x) + 0.5), math.floor(ty(y) + 0.5)) for x, y in points]
    except DataGenError as e:
        raise PathError(str(e)) from None


def function_points(expr: str, x0: int, x1: int, step: int = 1) -> list[Point]:
    """A path from y = f(x), x from x0 to x1 (Use Function). Screen y runs downwards, so negate
    the function to draw it the right way up."""
    try:
        f = Function(expr, "x")
        step = max(1, step) * (1 if x1 >= x0 else -1)
        return [(x, math.floor(f(x) + 0.5)) for x in range(x0, x1 + (1 if step > 0 else -1), step)]
    except DataGenError as e:
        raise PathError(str(e)) from None


def to_cells(path: ScreenPath, cols: int, rows: int) -> list[tuple[int, int]]:
    """The character cells the path runs through, in order (Convert To Characters)."""
    out, seen = [], set()
    for x, y in interpolate(path, 1):
        c = (x // 8, y // 8)
        if 0 <= c[0] < cols and 0 <= c[1] < rows and c not in seen:
            seen.add(c)
            out.append(c)
    return out


@dataclass
class GenOptions:
    step: int = 1
    first: int = 1
    last: int = 0                  # 0 = to the end
    only_points: bool = False
    separate: bool = False         # x table then y table, instead of x, y pairs
    fx: str = "x"
    fy: str = "y"
    output: str = "bytes"          # bytes, words or basic
    label: str = "path"
    kickass: bool = False
    basic_start: int = 1000
    basic_step: int = 10
    per_line: int = 8
    comments: bool = True


def generate(path: ScreenPath, o: GenOptions) -> tuple[str, list[str]]:
    """The data, and warnings (values that don't fit a byte)."""
    if len(path.points) < 1:
        raise PathError("The path has no points: click on the screen in path mode to add some")
    pts = transform(interpolate(path, o.step, o.first, o.last or None, o.only_points), o.fx, o.fy)
    warnings = []
    lo = min(min(p) for p in pts)
    hi = max(max(p) for p in pts)
    if o.output in ("bytes", "basic") and (lo < 0 or hi > 255):
        warnings.append(f"Values run from {lo} to {hi}, outside a byte (0-255): use words, or a transform")
    if o.output == "words" and (lo < -32768 or hi > 65535):
        warnings.append(f"Values run from {lo} to {hi}, outside a word")
    tables = [("x", [p[0] for p in pts]), ("y", [p[1] for p in pts])] if o.separate else \
        [("", [v for p in pts for v in p])]
    what = (f"{len(pts)} points" + (f", every {o.step} pixel{'s' if o.step != 1 else ''}" if not o.only_points else
                                    ", the path's own points") +
            (" (x, then y)" if o.separate else " (x, y pairs)") +
            (f", x = {o.fx}" if o.fx.strip() not in ("", "x") else "") +
            (f", y = {o.fy}" if o.fy.strip() not in ("", "y") else ""))
    per = max(1, o.per_line) * (1 if o.separate else 2)
    out: list[str] = []
    if o.output == "basic":
        n = o.basic_start
        if o.comments:
            out.append(f"{n} rem path: {what}")
            n += o.basic_step
        for _name, vals in tables:
            for i in range(0, len(vals), per):
                out.append(f"{n} data " + ",".join(str(v) for v in vals[i:i + per]))
                n += o.basic_step
        if n - o.basic_step > 63999:
            raise PathError("The BASIC needs line numbers above 63999: start lower or use a smaller step")
        return "\n".join(out) + "\n", warnings
    c = "//" if o.kickass else ";"
    ind = "    " if o.kickass else "        "
    directive = ("." if o.kickass else "") + ("byte" if o.output == "bytes" else "word")
    width = 2 if o.output == "bytes" else 4
    if o.comments:
        out.append(f"{c} path: {what}")
    for name, vals in tables:
        if o.label:
            lab = o.label + (f"_{name}" if name else "")
            out.append(f"{lab}:" if o.kickass else lab)
        for i in range(0, len(vals), per):
            out.append(f"{ind}{directive} " + ", ".join(str(v) if v < 0 else f"${v:0{width}X}"
                                                         for v in vals[i:i + per]))
    if o.comments:
        out.append(f"{c} {len(pts)} points, {len(pts) * (1 if o.output == 'bytes' else 2) * 2} bytes")
    return "\n".join(out) + "\n", warnings


# ---------------------------------------------------------------- .sdd files
def parse_point(el) -> Point | None:
    """A <Point> as CBM prg Studio may write it: "x,y", "{X=x,Y=y}", <X>/<Y> children or x/y
    attributes. (No file with points was at hand to confirm which.)"""
    import re
    for a, b in (("X", "Y"), ("x", "y")):
        if el.get(a) is not None and el.get(b) is not None:
            return int(el.get(a)), int(el.get(b))
        if el.findtext(a) is not None and el.findtext(b) is not None:
            return int(el.findtext(a)), int(el.findtext(b))
    nums = re.findall(r"-?\d+", el.text or "")
    return (int(nums[0]), int(nums[1])) if len(nums) >= 2 else None
