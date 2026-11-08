"""The sizes of the IDE's text zoom (Ctrl+Shift+plus and minus), as percentages, and how panels follow it.
The GTK side is ui/textzoom.py."""
from __future__ import annotations

NORMAL = 100
STEPS = (75, 90, 100, 110, 125, 150, 175, 200, 250, 300)


def valid(percent) -> int:
    """A size to use from what the settings file holds: the nearest step, or normal if it's nonsense."""
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return NORMAL
    return min(STEPS, key=lambda s: abs(s - percent))


def larger(percent: int) -> int:
    """The next size up (the largest stays the largest)."""
    return next((s for s in STEPS if s > percent), STEPS[-1])


def smaller(percent: int) -> int:
    """The next size down (the smallest stays the smallest)."""
    return next((s for s in reversed(STEPS) if s < percent), STEPS[0])


def fitted(normal: float, total: int, factor: float, most: float = 0.4) -> int:
    """A panel's size when the text is ``factor`` times normal and the panel ``normal`` at normal size.
    It grows with the text up to ``most`` of the ``total`` space, so the editor beside it isn't squeezed out."""
    return round(min(normal * factor, max(normal, total * most)))


class Panel:
    """A panel that follows the text size. It remembers its size at normal text, so zooming in and
    back puts it where it was even if its limit was reached on the way; dragging it starts afresh."""

    def __init__(self, most: float = 0.4):
        self.most = most
        self.normal: float | None = None
        self.last: int | None = None

    def resized(self, size: int, total: int, old: float, new: float) -> int:
        """The panel is ``size`` and the text goes from ``old`` to ``new`` times normal: its new size."""
        if self.normal is None or size != self.last:
            self.normal = size / old
        self.last = fitted(self.normal, total, new, self.most)
        return self.last
