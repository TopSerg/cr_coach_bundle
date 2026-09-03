from __future__ import annotations
from typing import Protocol, Any


class EngineAdapter(Protocol):
    """Backend-neutral replay execution boundary.

    ``tick`` is the next physics tick to execute. ``play_card`` and
    ``activate_ability`` schedule an action for the current tick; a backend may
    buffer that action until ``advance_to`` crosses to a later tick. This lets
    both sides submit actions on the same replay tick before physics advances.
    """

    @property
    def tick(self) -> int: ...

    def advance_to(self, tick: int) -> None:
        """Execute physics ticks until ``self.tick == tick``."""
        ...

    def play_card(self, *, side: str, card: str, cell: tuple[int, int]) -> None:
        """Schedule one card play for the adapter's current tick."""
        ...

    def activate_ability(self, *, side: str, card: str | None) -> None:
        """Schedule an ability activation for the adapter's current tick."""
        ...

    def snapshot(self) -> dict[str, Any]: ...
