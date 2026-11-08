"""A panel of the main window that collapses and comes back at the size it had, as VS Code's sidebars do."""
from __future__ import annotations

from gi.repository import Gtk

from ..zoom import Panel, restored


class CollapsiblePane:
    """``child``, one side of ``paned``. Its size is measured from the window's edge, so a panel on
    the right or at the bottom comes back the same size even if the window changed while it was gone.
    ``size`` is where it starts from if it's collapsed before it's ever been shown (None: GTK decides)."""

    def __init__(self, paned: Gtk.Paned, child: Gtk.Widget, follow: Panel, at_end: bool = False,
                 size: int | None = None):
        self.paned, self.child, self.follow, self.at_end = paned, child, follow, at_end
        self.size = size              # while collapsed

    @property
    def open(self) -> bool:
        return self.child.get_visible()

    def _total(self) -> int:
        horizontal = self.paned.get_orientation() == Gtk.Orientation.HORIZONTAL
        return self.paned.get_width() if horizontal else self.paned.get_height()

    def _current(self) -> int:
        position = self.paned.get_position()
        return self._total() - position if self.at_end else position

    def _place(self, size: int):
        self.paned.set_position(self._total() - size if self.at_end else size)

    def collapse(self):
        if self.open and self._total() > 0:       # (not yet on screen: there's nothing to measure)
            self.size = self._current()
        self.child.set_visible(False)

    def restore(self):
        if self.open:
            return
        self.child.set_visible(True)
        if self.size is None or self._total() <= 0:
            return
        size = self.size
        self._place(restored(size, self._total()))
        # If the window changed size while the panel was gone, GTK's next layout moves the divider by
        # the difference, and this one's own total may be stale too (a neighbour has just come back).
        # So place it again once that layout has happened: the second tick is the frame after it.
        ticks = [2]

        def settle(_widget, _clock):
            if not self.open:
                return False
            self._place(restored(size, self._total()))
            ticks[0] -= 1
            return ticks[0] > 0
        self.paned.add_tick_callback(settle)

    def zoomed(self, old: float, new: float):
        """The text has gone from ``old`` to ``new`` times normal."""
        if self.open:
            self._place(self.follow.resized(self._current(), self._total(), old, new))
        elif self.size is not None:
            self.size = self.follow.resized(self.size, self._total(), old, new)
