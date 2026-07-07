from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from bot.bridge.showdown_bridge import ShowdownBattleProcess
from bot.showdown_battle.doubles import DoublesDraft


@dataclass
class PendingChallenge:
    challenge_id: str
    chat_id: int
    public_message_id: int
    challenger_id: int
    challenger_name: str
    mode: str = "owned"
    format_key: str = ""
    visuals_enabled: bool = False
    format_id: str = ""
    format_label: str = ""
    battle_kind: str = "singles"
    settings_enabled: bool = True
    opponent_id: int | None = None
    opponent_name: str | None = None
    source_message_id: int = 0
    state: str = "open"
    expires_at: float = 0.0
    expiry_task: asyncio.Task[None] | None = None


@dataclass
class PendingFfaChallenge:
    challenge_id: str
    chat_id: int
    public_message_id: int
    challenger_id: int
    challenger_name: str
    source_message_id: int = 0
    mode: str = "owned"
    format_key: str = ""
    visuals_enabled: bool = False
    format_id: str = ""
    format_label: str = ""
    battle_kind: str = "freeforall"
    settings_enabled: bool = True
    slots: dict[str, tuple[int, str]] = field(default_factory=dict)
    state: str = "open"
    expires_at: float = 0.0
    expiry_task: asyncio.Task[None] | None = None


@dataclass
class PlayerState:
    slot: str
    user_id: int
    name: str
    ko_count: int = 0
    active_pokemon_key: str | None = None
    move_catalog: list[dict[str, Any]] = field(default_factory=list)
    revealed_moves: dict[int, dict[str, Any]] = field(default_factory=dict)
    last_submitted_move_index: int | None = None
    current_request: dict[str, Any] | None = None
    request_token: int = 0
    locked_choice: str | None = None
    last_error: str | None = None
    primed_action: str | None = None
    pending_target: dict[str, Any] | None = None
    doubles_draft: DoublesDraft = field(default_factory=DoublesDraft)
    used_primary_gimmick: str | None = None
    next_action_at: float = 0.0


@dataclass
class BattleSession:
    battle_id: str
    chat_id: int
    public_message_id: int
    format_id: str
    format_label: str
    players: dict[str, PlayerState]
    public_view: Any
    battle_kind: str = "singles"
    bridge: ShowdownBattleProcess | None = None
    finished: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    runner_task: asyncio.Task[None] | None = None
    last_visual_scene_fingerprint: str = ""
    winner_reward: int | None = None
    loser_reward: int | None = None

    def player_for_user(self, user_id: int) -> PlayerState | None:
        for player in self.players.values():
            if player.user_id == user_id:
                return player
        return None
