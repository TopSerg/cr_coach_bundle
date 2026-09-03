from __future__ import annotations

from dataclasses import dataclass

import pytest

from cr_coach.engine.crbot import (
    CrBotActionRejected,
    CrBotAdapterError,
    CrBotEngineAdapter,
)
from cr_coach.replay.executor import execute_replay
from cr_coach.replay.schema import ReplayBattle, ReplayEvent


@dataclass(frozen=True, slots=True)
class FakePlayAction:
    player: int
    card_slot: int
    cell: tuple[int, int]


@dataclass(slots=True)
class FakePlayer:
    deck: tuple[str, ...]
    hand: list[str]
    draw_pile: list[str]
    elixir_milli: int = 10_000
    crowns: int = 0
    next_card_cooldown_us: int = 0


class FakeMatchRules:
    hand_size = 4


class FakeRuleset:
    tick_us = 50_000
    match = FakeMatchRules()

    @staticmethod
    def resolve_card_id(card: str) -> str:
        return card.lower().replace(" ", "-")


@dataclass(slots=True)
class FakeEvent:
    kind: str
    player: int | None = None
    reason: str | None = None

    def get(self, name: str, default=None):
        return getattr(self, name, default)


class FakeState:
    def __init__(self, players: list[FakePlayer]) -> None:
        self.tick = 0
        self.players = players

    def to_primitive(self, *, include_events: bool = False):
        return {
            "tick": self.tick,
            "players": [
                {
                    "hand": list(player.hand),
                    "draw_pile": list(player.draw_pile),
                    "elixir_milli": player.elixir_milli,
                    "crowns": player.crowns,
                }
                for player in self.players
            ],
        }


class FakeEngine:
    def __init__(self) -> None:
        self.ruleset = FakeRuleset()
        self.steps: list[tuple[int, tuple[FakePlayAction, ...]]] = []
        self.reject_player: int | None = None
        self.reject_reason = "illegal_placement"

    def new_battle(self, *, decks, seed=0, shuffle_decks=False):
        assert shuffle_decks is False
        players = [
            FakePlayer(tuple(deck), list(deck[:4]), list(deck[4:]))
            for deck in decks
        ]
        return FakeState(players)

    def step(self, state: FakeState, actions=()):
        actions = tuple(actions)
        self.steps.append((state.tick, actions))
        events = []
        if self.reject_player is not None:
            for action in actions:
                if action.player == self.reject_player:
                    events.append(
                        FakeEvent(
                            "action_rejected",
                            player=action.player,
                            reason=self.reject_reason,
                        )
                    )
        state.tick += 1
        return tuple(events)


DECK = (
    "hog-rider",
    "cannon",
    "musketeer",
    "skeletons",
    "ice-golem",
    "ice-spirit",
    "fireball",
    "the-log",
)


def make_adapter() -> tuple[CrBotEngineAdapter, FakeEngine]:
    engine = FakeEngine()
    adapter = CrBotEngineAdapter(
        engine=engine,
        decks=(DECK, DECK),
        play_action_factory=FakePlayAction,
    )
    return adapter, engine


def test_buffers_action_until_physics_tick_is_advanced():
    adapter, engine = make_adapter()

    adapter.play_card(side="team", card="Hog Rider", cell=(3, 17))

    assert adapter.tick == 0
    assert engine.steps == []

    adapter.advance_to(1)

    assert adapter.tick == 1
    assert len(engine.steps) == 1
    tick, actions = engine.steps[0]
    assert tick == 0
    assert actions == (FakePlayAction(0, 0, (3, 17)),)


def test_same_tick_actions_are_applied_in_one_engine_step():
    adapter, engine = make_adapter()

    adapter.play_card(side="team", card="hog-rider", cell=(3, 17))
    adapter.play_card(side="opponent", card="cannon", cell=(8, 13))
    adapter.advance_to(1)

    _, actions = engine.steps[0]
    assert actions == (
        FakePlayAction(0, 0, (3, 17)),
        FakePlayAction(1, 1, (8, 13)),
    )


def test_card_not_in_hand_fails_before_simulation_is_mutated():
    adapter, engine = make_adapter()

    with pytest.raises(CrBotAdapterError, match="card_not_in_hand"):
        adapter.play_card(side="team", card="fireball", cell=(5, 20))

    assert adapter.tick == 0
    assert engine.steps == []


def test_upstream_action_rejection_becomes_replay_divergence():
    adapter, engine = make_adapter()
    engine.reject_player = 0

    adapter.play_card(side="team", card="hog-rider", cell=(3, 17))
    with pytest.raises(CrBotActionRejected, match="illegal_placement"):
        adapter.advance_to(1)


def test_from_replay_requires_20hz_for_current_crbot_timebase():
    battle = ReplayBattle(
        battle_id="timebase",
        ticks_per_second=30,
        team_deck=DECK,
        opponent_deck=DECK,
    )

    with pytest.raises(ValueError, match="timebase mismatch"):
        CrBotEngineAdapter.from_replay(
            battle,
            engine=FakeEngine(),
            play_action_factory=FakePlayAction,
        )


def test_execute_replay_flushes_last_buffered_action():
    battle = ReplayBattle(
        battle_id="hog-smoke",
        team_deck=DECK,
        opponent_deck=DECK,
        events=[
            ReplayEvent(
                tick=0,
                side="team",
                event_type="card_play",
                card="hog-rider",
                x_mtile=3_500,
                y_mtile=17_500,
            )
        ],
    )
    engine = FakeEngine()
    adapter = CrBotEngineAdapter.from_replay(
        battle,
        engine=engine,
        play_action_factory=FakePlayAction,
    )

    trace = execute_replay(battle, adapter)

    assert adapter.tick == 1
    assert engine.steps[0][1] == (FakePlayAction(0, 0, (3, 17)),)
    assert trace[0]["tick"] == 0  # pre-action
    assert trace[-1]["tick"] == 1  # post-action/physics tick
    assert trace[-1]["backend"] == "cr-bot"
