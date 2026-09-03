from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from cr_coach.replay.schema import ReplayBattle


class CrBotAdapterError(RuntimeError):
    """Base error raised by the cr-bot backend adapter."""


class CrBotDependencyError(CrBotAdapterError):
    """Raised when the upstream cr-bot package is not importable."""


@dataclass(slots=True)
class CrBotActionRejected(CrBotAdapterError):
    tick: int
    player: int
    reason: str

    def __str__(self) -> str:
        return (
            f"cr-bot rejected action at tick={self.tick}, "
            f"player={self.player}: {self.reason}"
        )


PlayActionFactory = Callable[[int, int, tuple[int, int]], Any]


def _load_default_engine() -> Any:
    try:
        from simulator.engine import BattleEngine
    except ImportError as exc:  # pragma: no cover - depends on upstream checkout
        raise CrBotDependencyError(
            "cannot import upstream cr-bot. Initialize the upstream/cr-bot "
            "submodule and make its repository root importable (so "
            "`import simulator` works)."
        ) from exc
    return BattleEngine()


def _load_play_action_factory() -> PlayActionFactory:
    try:
        from simulator.actions import PlayCardAction
    except ImportError as exc:  # pragma: no cover - depends on upstream checkout
        raise CrBotDependencyError(
            "cannot import simulator.actions.PlayCardAction from upstream cr-bot"
        ) from exc
    return PlayCardAction


def _event_field(event: Any, name: str, default: Any = None) -> Any:
    if hasattr(event, name):
        return getattr(event, name)
    if isinstance(event, dict):
        if name in event:
            return event[name]
        data = event.get("data")
        if isinstance(data, dict):
            return data.get(name, default)
    getter = getattr(event, "get", None)
    if callable(getter):
        return getter(name, default)
    return default


class CrBotEngineAdapter:
    """Adapter from our replay boundary to Keschler/cr-bot's BattleEngine.

    Important timing contract
    -------------------------
    ``BattleState.tick`` in cr-bot is the *next* physics tick to execute.
    Replay actions are therefore buffered for the current tick and are passed
    together to ``BattleEngine.step`` when ``advance_to`` crosses from tick N
    to N+1. This preserves cr-bot's normal phase ordering:

        elixir/card-cycle -> actions -> deploy -> target -> move -> combat

    It also lets both players act on the same replay tick without accidentally
    advancing the simulation between their actions.
    """

    def __init__(
        self,
        *,
        engine: Any | None = None,
        state: Any | None = None,
        decks: tuple[tuple[str, ...], tuple[str, ...]] | None = None,
        seed: int = 0,
        shuffle_decks: bool = False,
        play_action_factory: PlayActionFactory | None = None,
    ) -> None:
        self._engine = engine or _load_default_engine()
        if state is None:
            if decks is None:
                raise ValueError("decks are required when state is not supplied")
            state = self._engine.new_battle(
                decks=decks,
                seed=seed,
                shuffle_decks=shuffle_decks,
            )
        self._state = state
        self._play_action_factory = play_action_factory or _load_play_action_factory()
        self._pending_actions: dict[int, dict[int, Any]] = {}

    @classmethod
    def from_replay(
        cls,
        battle: ReplayBattle,
        *,
        engine: Any | None = None,
        seed: int = 0,
        play_action_factory: PlayActionFactory | None = None,
    ) -> "CrBotEngineAdapter":
        """Create a deterministic cr-bot battle matching a canonical replay.

        When an exact initial queue has been reconstructed, that queue is used
        as cr-bot's unshuffled draw order. Otherwise the declared deck order is
        used as a deterministic placeholder until hand reconstruction is
        available.
        """

        battle.validate()
        team = cls._queue_or_deck(
            "team", battle.team_initial_queue, battle.team_deck
        )
        opponent = cls._queue_or_deck(
            "opponent", battle.opponent_initial_queue, battle.opponent_deck
        )
        adapter = cls(
            engine=engine,
            decks=(team, opponent),
            seed=seed,
            shuffle_decks=False,
            play_action_factory=play_action_factory,
        )
        adapter.assert_timebase(battle.ticks_per_second)
        return adapter

    @staticmethod
    def _queue_or_deck(
        side: str,
        queue: tuple[str, ...] | None,
        deck: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(deck) != 8:
            raise ValueError(f"{side} deck must contain exactly 8 cards")
        if queue is None:
            return tuple(deck)
        if len(queue) != 8:
            raise ValueError(f"{side} initial queue must contain exactly 8 cards")
        if sorted(queue) != sorted(deck):
            raise ValueError(f"{side} initial queue must be a permutation of its deck")
        return tuple(queue)

    @property
    def tick(self) -> int:
        return int(self._state.tick)

    @property
    def state(self) -> Any:
        """Expose the authoritative state for diagnostics, not policy input."""

        return self._state

    @property
    def engine(self) -> Any:
        return self._engine

    def assert_timebase(self, ticks_per_second: int) -> None:
        tick_us = int(self._engine.ruleset.tick_us)
        if ticks_per_second <= 0:
            raise ValueError("ticks_per_second must be positive")
        if tick_us * ticks_per_second != 1_000_000:
            raise ValueError(
                "replay/cr-bot timebase mismatch: "
                f"replay={ticks_per_second} ticks/s, cr-bot tick_us={tick_us}"
            )

    def advance_to(self, tick: int) -> None:
        if type(tick) is not int or tick < 0:
            raise ValueError("target tick must be a non-negative integer")
        if tick < self.tick:
            raise ValueError(
                f"cannot rewind cr-bot from tick {self.tick} to tick {tick}"
            )

        while self.tick < tick:
            current_tick = self.tick
            pending = self._pending_actions.pop(current_tick, {})
            actions = tuple(pending[player] for player in sorted(pending))
            events = self._engine.step(self._state, actions)
            self._raise_on_rejected_actions(current_tick, pending, events)

    def play_card(
        self,
        *,
        side: str,
        card: str,
        cell: tuple[int, int],
    ) -> None:
        player = self._player(side)
        pending = self._pending_actions.setdefault(self.tick, {})
        if player in pending:
            raise CrBotAdapterError(
                f"multiple replay actions for {side} at tick={self.tick}"
            )

        card_id = self._resolve_card_id(card)
        slot = self._slot_available_on_current_tick(player, card_id)
        if slot is None:
            hand = list(self._state.players[player].hand)
            raise CrBotAdapterError(
                f"card_not_in_hand at tick={self.tick}, side={side}, "
                f"card={card_id}, hand={hand}"
            )

        pending[player] = self._play_action_factory(player, slot, cell)

    def activate_ability(self, *, side: str, card: str | None) -> None:
        # cr-bot currently exposes UseAbilityAction in its schema, but its
        # scheduler intentionally rejects it as ability_not_supported. Fail
        # before mutating state so the replay divergence is explicit.
        raise NotImplementedError(
            f"cr-bot ability replay is not supported yet: "
            f"tick={self.tick}, side={side}, card={card!r}"
        )

    def snapshot(self) -> dict[str, Any]:
        if hasattr(self._state, "to_primitive"):
            payload = self._state.to_primitive(include_events=False)
        else:  # test/fallback backend
            payload = {
                "tick": self.tick,
                "players": [
                    {
                        "hand": list(getattr(player, "hand", ())),
                        "draw_pile": list(getattr(player, "draw_pile", ())),
                        "elixir_milli": getattr(player, "elixir_milli", None),
                        "crowns": getattr(player, "crowns", None),
                    }
                    for player in getattr(self._state, "players", ())
                ],
            }
        payload = dict(payload)
        payload["backend"] = "cr-bot"
        return payload

    def _player(self, side: str) -> int:
        if side == "team":
            return 0
        if side == "opponent":
            return 1
        raise ValueError(f"unknown replay side: {side!r}")

    def _resolve_card_id(self, card: str) -> str:
        resolver = getattr(self._engine.ruleset, "resolve_card_id", None)
        if callable(resolver):
            return str(resolver(card))
        return card

    def _slot_available_on_current_tick(self, player: int, card_id: str) -> int | None:
        player_state = self._state.players[player]
        hand = list(player_state.hand)
        if card_id in hand:
            return hand.index(card_id)

        # cr-bot advances the next-card cooldown immediately before applying
        # actions. Account for the narrow boundary where the replay card is the
        # next draw and becomes playable at the start of this exact tick.
        hand_size = int(self._engine.ruleset.match.hand_size)
        draw_pile = list(getattr(player_state, "draw_pile", ()))
        if len(hand) >= hand_size or not draw_pile or draw_pile[0] != card_id:
            return None

        cooldown = int(getattr(player_state, "next_card_cooldown_us", 0))
        tick_us = int(self._engine.ruleset.tick_us)
        if cooldown == 0 or cooldown <= tick_us:
            return len(hand)
        return None

    def _raise_on_rejected_actions(
        self,
        tick: int,
        pending: dict[int, Any],
        events: Any,
    ) -> None:
        if not pending:
            return
        pending_players = set(pending)
        for event in events:
            kind = _event_field(event, "kind")
            if kind != "action_rejected":
                continue
            player = _event_field(event, "player")
            if player not in pending_players:
                continue
            reason = str(_event_field(event, "reason", "unknown"))
            raise CrBotActionRejected(tick=tick, player=int(player), reason=reason)
