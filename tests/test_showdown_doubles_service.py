from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace

from bot.showdown_battle.models import BattleSession, PlayerState
from bot.showdown_battle.protocol import PublicBattleView


def _install_test_stubs() -> None:
    decorators = ModuleType("bot.handlers.decorators")

    def _identity_decorator(_bot=None):
        def decorator(func):
            return func

        return decorator

    decorators.user_not_banned = _identity_decorator
    decorators.user_registered = _identity_decorator
    sys.modules.setdefault("bot.handlers.decorators", decorators)

    db_module = ModuleType("bot.mechanics.db")
    db_module.db = SimpleNamespace()
    sys.modules.setdefault("bot.mechanics.db", db_module)

    team_image = ModuleType("bot.image_generation.team_image")

    async def _create_team_image(_team):
        return None

    team_image.create_team_image = _create_team_image
    sys.modules.setdefault("bot.image_generation.team_image", team_image)

    analyzer = ModuleType("bot.team_analysis.analyzer")
    analyzer.analyze_team_coverage = lambda _team: {}
    analyzer.format_analysis_caption = lambda _name, _team, _analysis: ""
    sys.modules.setdefault("bot.team_analysis.analyzer", analyzer)

    presenter = ModuleType("bot.team_analysis.presenter")
    presenter.build_team_from_showdown_request = lambda _request: []
    presenter.format_team_detail_text = lambda _name, _team: ""
    sys.modules.setdefault("bot.team_analysis.presenter", presenter)


_install_test_stubs()

from bot.showdown_battle.service import ShowdownChallengeService


class FakeBridge:
    def __init__(self) -> None:
        self.choices: list[tuple[str, str]] = []

    async def choose(self, slot: str, choice: str) -> None:
        self.choices.append((slot, choice))

    async def forfeit(self, slot: str) -> None:  # pragma: no cover
        raise AssertionError("forfeit should not be called in these tests")


def build_battle() -> BattleSession:
    return BattleSession(
        battle_id="battle-test",
        chat_id=1,
        public_message_id=1,
        format_id="gen9doublescustomgame",
        format_label="Test Doubles",
        battle_kind="doubles",
        players={
            "p1": PlayerState(slot="p1", user_id=1, name="Alice"),
            "p2": PlayerState(slot="p2", user_id=2, name="Bob"),
        },
        public_view=PublicBattleView(player_names={"p1": "Alice", "p2": "Bob"}, gametype="doubles"),
    )


class ShowdownDoublesServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = ShowdownChallengeService(bot=None)
        self.battle = build_battle()
        self.bridge = FakeBridge()
        self.battle.bridge = self.bridge
        self.player = self.battle.players["p1"]

    async def test_force_switch_pass_keeps_last_reserve_assignable(self) -> None:
        request = {
            "forceSwitch": [True, True],
            "side": {
                "pokemon": [
                    {"details": "Gengar, L100", "condition": "0 fnt", "active": True},
                    {"details": "Dragonite, L100", "condition": "0 fnt", "active": True},
                    {"details": "Metagross, L100", "condition": "100/100", "active": False},
                ]
            },
        }
        self.player.current_request = request

        specs = self.service.doubles_button_specs(self.battle, self.player, request)
        labels = {label for row in specs for label, _data in row}
        self.assertIn("PASS", labels)

        await self.service.apply_doubles_player_action(self.battle, self.player, request, "p")
        self.assertEqual(self.player.doubles_draft.focus, 1)

        await self.service.apply_doubles_player_action(self.battle, self.player, request, "s3")
        self.assertEqual(self.bridge.choices, [("p1", "pass, switch 3")])

    async def test_locked_phantom_force_submits_without_target(self) -> None:
        request = {
            "active": [
                {
                    "maybeLocked": True,
                    "moves": [{"move": "Phantom Force", "id": "phantomforce"}],
                },
                {
                    "moves": [{"move": "Protect", "id": "protect", "target": "self", "disabled": False}],
                },
            ],
            "side": {
                "pokemon": [
                    {"details": "Dragapult, L100", "condition": "100/100", "active": True},
                    {"details": "Amoonguss, L100", "condition": "0 fnt", "active": True},
                ]
            },
        }
        self.player.current_request = request

        await self.service.apply_doubles_player_action(self.battle, self.player, request, "m1")

        self.assertEqual(self.bridge.choices, [("p1", "move 1, pass")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
