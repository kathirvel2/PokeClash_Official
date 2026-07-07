from __future__ import annotations

import asyncio
import html
import re
import secrets
from typing import Any

from telebot import types
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import ApiTelegramException

from bot.bridge.showdown_bridge import ShowdownBattleProcess, ShowdownBridgeError
from bot.bridge.showdown_team_packer import pack_team
from bot.handlers.decorators import user_not_banned, user_registered
from bot.handlers.handler_utils import CallbackRateLimiter
from bot.image_generation.team_image import create_team_image
from bot.mechanics.db import db
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID
from bot.mechanics.ranking import calculate_elo_change
from bot.showdown_battle.formats import (
    DOUBLES_BATTLE_KIND,
    FREEFORALL_BATTLE_KIND,
    MULTI_RANDOM_BATTLE_FORMAT_ID,
    OWNED_MODE,
    RANDOM_MODE,
    SINGLES_BATTLE_KIND,
    default_format_option,
    format_options_for,
    normalize_battle_kind,
    normalize_mode,
    resolve_format_option,
)
from bot.showdown_battle.models import BattleSession, PendingChallenge, PendingFfaChallenge, PlayerState
from bot.showdown_battle.doubles import (
    decode_target_location,
    doubles_slot_label,
    encode_target_location,
    is_doubles_battle_kind,
)
from bot.showdown_battle.protocol import (
    PublicBattleView,
    clean_error,
    details_name,
    fainted,
    ident_name,
    ident_side,
    parse_condition,
    protocol_parts,
)
from bot.showdown_battle.visuals import BattleVisualRenderer
from bot.showdown_config import BOT_DIR, SHOWDOWN_DIR
from bot.team_analysis.analyzer import analyze_team_coverage, format_analysis_caption
from bot.team_analysis.presenter import build_team_from_showdown_request, format_team_detail_text


ACTION_COOLDOWN_SECONDS = 1.0
CHALLENGE_EXPIRY_SECONDS = 60.0
BATTLE_STATS_REVEAL_SECONDS = 180.0
POPUP_LIMIT = 195
EVENT_BATCH_WINDOW_SECONDS = 0.12
PRIMARY_GIMMICK_ACTIONS = {"terastallize", "mega", "megax", "megay", "dynamax"}
PRIMARY_GIMMICK_LABELS = {
    "terastallize": "Tera",
    "mega": "Mega",
    "megax": "Mega X",
    "megay": "Mega Y",
    "dynamax": "Dynamax",
}
SIGNATURE_ZMOVES = {
    "10,000,000 volt thunderbolt": "10000000voltthunderbolt.png",
    "catastropika": "catastropika.png",
    "clangorous soulblaze": "clangoroussoulblaze.png",
    "extreme evoboost": "extremeevoboost.png",
    "genesis supernova": "genesissupernova.png",
    "guardian of alola": "guardianofalola.png",
    "let's snuggle forever": "letssnuggleforever.png",
    "light that burns the sky": "lightthatburnsthesky.png",
    "malicious moonsault": "maliciousmoonsault.png",
    "menacing moonraze maelstrom": "menacingmoonrazemaelstrom.png",
    "oceanic operetta": "oceanicoperetta.png",
    "pulverizing pancake": "pulverizingpancake.png",
    "searing sunraze smash": "searingsunrazesmash.png",
    "sinister arrow raid": "sinisterarrowraid.png",
    "soul-stealing 7-star strike": "soulstealing7starstrike.png",
    "splintered stormshards": "splinteredstormshards.png",
    "stoked sparksurfer": "stokedsparksurfer.png",
}
RANDOM_BATTLE_GENERATION_KEYS: dict[str, dict[int, str]] = {
    SINGLES_BATTLE_KIND: {
        9: "randombattle",
        8: "gen8randombattle",
        7: "gen7randombattle",
        6: "gen6randombattle",
        5: "gen5randombattle",
        4: "gen4randombattle",
        3: "gen3randombattle",
        2: "gen2randombattle",
        1: "gen1randombattle",
    },
    DOUBLES_BATTLE_KIND: {
        9: "randomdoubles",
        8: "gen8randomdoubles",
    },
}

ACTIVE_SHOWDOWN_SERVICE: "ShowdownChallengeService | None" = None


def compact_text(text: str, limit: int = POPUP_LIMIT) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean
    if limit <= 3:
        return clean[:limit]
    return clean[: limit - 3].rstrip() + "..."


def hp_bar_ascii(percent: int | None, width: int = 9) -> str:
    if percent is None:
        return "[" + ("?" * width) + "]"
    bounded = max(0, min(100, percent))
    filled = round((bounded / 100) * width)
    return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"


def normalized(value: str) -> str:
    return "".join(char for char in str(value or "").lower() if char.isalnum())


SPECIES_BY_NORMALIZED_NAME = {
    normalized(species_data.get("name", "")): species_data
    for species_data in SPECIES_BY_ID.values()
}


def mention_html(user_id: int | None, label: str) -> str:
    safe_label = html.escape(label or "Trainer")
    if not user_id:
        return safe_label
    return f'<a href="tg://user?id={user_id}">{safe_label}</a>'


def format_types(types_list: list[str] | None) -> str:
    if not types_list:
        return "Unknown"
    return "/".join(types_list)


def bool_label(value: bool) -> str:
    return "On" if value else "Off"


def chunk_specs(specs: list[tuple[str, str]], per_row: int) -> list[list[tuple[str, str]]]:
    return [specs[index:index + per_row] for index in range(0, len(specs), per_row)]


class ShowdownChallengeService:
    def __init__(self, bot: AsyncTeleBot) -> None:
        self.bot = bot
        self.visual_renderer = BattleVisualRenderer()
        self.pending_by_id: dict[str, PendingChallenge] = {}
        self.pending_ffa_by_id: dict[str, PendingFfaChallenge] = {}
        self.pending_by_user: dict[int, set[str]] = {}
        self.battles_by_id: dict[str, BattleSession] = {}
        self.active_by_user: dict[int, str] = {}
        self.battle_stats_reveals: dict[str, dict[str, Any]] = {}

    def normalize_challenge_mode(self, value: str | None) -> str:
        return normalize_mode(value, battle_kind=SINGLES_BATTLE_KIND)

    def battle_kind_label(self, battle_kind: str) -> str:
        return {
            SINGLES_BATTLE_KIND: "Singles",
            DOUBLES_BATTLE_KIND: "Doubles",
            FREEFORALL_BATTLE_KIND: "Free-For-All",
        }.get(normalize_battle_kind(battle_kind), "Battle")

    def challenge_mode_label(self, mode: str, battle_kind: str = SINGLES_BATTLE_KIND) -> str:
        normalized_mode = normalize_mode(mode, battle_kind=battle_kind)
        kind = normalize_battle_kind(battle_kind)
        if normalized_mode == RANDOM_MODE:
            return "Randoms"
        if kind == SINGLES_BATTLE_KIND:
            return "Competitive"
        return "Owner Team"

    def challenge_status_label(self, challenge: PendingChallenge) -> str:
        return {
            "open": "waiting",
            "starting": "preparing",
            "expired": "expired",
            "declined": "declined",
            "cancelled": "cancelled",
        }.get(challenge.state, challenge.state)

    def mode_options(self, battle_kind: str) -> tuple[tuple[str, str], ...]:
        kind = normalize_battle_kind(battle_kind)
        if kind == FREEFORALL_BATTLE_KIND:
            return ((OWNED_MODE, "Owner Team"), (RANDOM_MODE, "Randoms"))
        if kind == DOUBLES_BATTLE_KIND:
            return ((OWNED_MODE, "Owner Team"), (RANDOM_MODE, "Randoms"))
        return ((OWNED_MODE, "Competitive"), (RANDOM_MODE, "Randoms"))

    def update_challenge_format(self, challenge: PendingChallenge | PendingFfaChallenge) -> None:
        challenge.battle_kind = normalize_battle_kind(challenge.battle_kind)
        challenge.mode = normalize_mode(challenge.mode, battle_kind=challenge.battle_kind)
        option = resolve_format_option(challenge.battle_kind, challenge.mode, challenge.format_key)
        challenge.format_key = option.key
        challenge.format_id = option.format_id
        challenge.format_label = option.label

    def _reserve_pending_user(self, user_id: int, challenge_id: str) -> None:
        self.pending_by_user.setdefault(user_id, set()).add(challenge_id)

    def _release_pending_user(self, user_id: int, challenge_id: str) -> None:
        pending = self.pending_by_user.get(user_id)
        if not pending:
            return
        pending.discard(challenge_id)
        if not pending:
            self.pending_by_user.pop(user_id, None)

    def _register_pending_challenge(self, challenge: PendingChallenge) -> None:
        if challenge.expires_at <= 0:
            challenge.expires_at = asyncio.get_running_loop().time() + CHALLENGE_EXPIRY_SECONDS
        self.pending_by_id[challenge.challenge_id] = challenge
        self._reserve_pending_user(challenge.challenger_id, challenge.challenge_id)
        if challenge.opponent_id is not None:
            self._reserve_pending_user(challenge.opponent_id, challenge.challenge_id)
        challenge.expiry_task = asyncio.create_task(self._expire_pending_challenge_later(challenge.challenge_id))

    def _release_pending_challenge(self, challenge: PendingChallenge, *, cancel_expiry_task: bool = True) -> None:
        self.pending_by_id.pop(challenge.challenge_id, None)
        self._release_pending_user(challenge.challenger_id, challenge.challenge_id)
        if challenge.opponent_id is not None:
            self._release_pending_user(challenge.opponent_id, challenge.challenge_id)
        if cancel_expiry_task and challenge.expiry_task is not None and not challenge.expiry_task.done():
            challenge.expiry_task.cancel()
        challenge.expiry_task = None

    def _register_pending_ffa(self, challenge: PendingFfaChallenge) -> None:
        if challenge.expires_at <= 0:
            challenge.expires_at = asyncio.get_running_loop().time() + CHALLENGE_EXPIRY_SECONDS
        self.pending_ffa_by_id[challenge.challenge_id] = challenge
        for user_id, _name in challenge.slots.values():
            self._reserve_pending_user(user_id, challenge.challenge_id)
        challenge.expiry_task = asyncio.create_task(self._expire_pending_challenge_later(challenge.challenge_id))

    def _release_pending_ffa(self, challenge: PendingFfaChallenge, *, cancel_expiry_task: bool = True) -> None:
        self.pending_ffa_by_id.pop(challenge.challenge_id, None)
        for user_id, _name in challenge.slots.values():
            self._release_pending_user(user_id, challenge.challenge_id)
        if cancel_expiry_task and challenge.expiry_task is not None and not challenge.expiry_task.done():
            challenge.expiry_task.cancel()
        challenge.expiry_task = None

    def set_ffa_slot(self, challenge: PendingFfaChallenge, slot: str, user_id: int, name: str) -> None:
        previous = challenge.slots.get(slot)
        if previous and previous[0] != user_id:
            self._release_pending_user(previous[0], challenge.challenge_id)
        challenge.slots[slot] = (user_id, name)
        self._reserve_pending_user(user_id, challenge.challenge_id)

    def clear_ffa_slot(self, challenge: PendingFfaChallenge, slot: str) -> None:
        previous = challenge.slots.pop(slot, None)
        if previous:
            self._release_pending_user(previous[0], challenge.challenge_id)

    def _register_active_battle(self, battle: BattleSession) -> None:
        for player in battle.players.values():
            if player.user_id > 0:
                self.active_by_user[player.user_id] = battle.battle_id

    def _release_active_battle(self, battle: BattleSession) -> None:
        for player in battle.players.values():
            if player.user_id > 0 and self.active_by_user.get(player.user_id) == battle.battle_id:
                self.active_by_user.pop(player.user_id, None)

    def showdown_lock_reason(self, user_id: int) -> str | None:
        if user_id in self.active_by_user:
            return "You are already in another PvP battle."
        if self.pending_by_user.get(user_id):
            return "You already have a pending PvP challenge."
        return None

    async def expire_pending_challenges_for_users(
        self,
        user_ids: list[int],
        *,
        keep_challenge_id: str | None = None,
        reason: str,
    ) -> None:
        unique_ids = {int(user_id) for user_id in user_ids if int(user_id) > 0}
        if not unique_ids:
            return

        direct_to_expire: list[PendingChallenge] = []
        ffa_to_expire: list[PendingFfaChallenge] = []
        seen: set[str] = set()
        for challenge in list(self.pending_by_id.values()):
            if keep_challenge_id and challenge.challenge_id == keep_challenge_id:
                continue
            participants = {challenge.challenger_id}
            if challenge.opponent_id is not None:
                participants.add(challenge.opponent_id)
            if participants.isdisjoint(unique_ids):
                continue
            if challenge.challenge_id in seen:
                continue
            seen.add(challenge.challenge_id)
            direct_to_expire.append(challenge)

        for challenge in list(self.pending_ffa_by_id.values()):
            if keep_challenge_id and challenge.challenge_id == keep_challenge_id:
                continue
            participants = {user_id for user_id, _name in challenge.slots.values()}
            if participants.isdisjoint(unique_ids):
                continue
            if challenge.challenge_id in seen:
                continue
            seen.add(challenge.challenge_id)
            ffa_to_expire.append(challenge)

        for challenge in direct_to_expire:
            challenge.state = "expired"
            self._release_pending_challenge(challenge)
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                reason,
                reply_markup=None,
            )
        for challenge in ffa_to_expire:
            challenge.state = "expired"
            self._release_pending_ffa(challenge)
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                reason,
                reply_markup=None,
            )

    def active_battle_for_user(self, user_id: int) -> BattleSession | None:
        battle_id = self.active_by_user.get(user_id)
        if not battle_id:
            return None
        return self.battles_by_id.get(battle_id)

    def is_passive_action_token(self, action_code: str) -> bool:
        return action_code in {"vm", "vt", "vc", "ta", "td", "cx"}

    def is_read_only_callback_data(self, data: str) -> bool:
        parts = str(data or "").split(":")
        return len(parts) == 6 and parts[1] == "a" and self.is_passive_action_token(parts[5])

    def team_snapshot_from_request(self, request: dict[str, Any]) -> list[Any]:
        try:
            return build_team_from_showdown_request(request)
        except Exception:
            return []

    def team_choice_popup_text(self, player: PlayerState, request: dict[str, Any]) -> str:
        if self.is_doubles_request(request) or (request.get("teamPreview") and int(request.get("maxChosenTeamSize") or 0) > 1):
            self.ensure_doubles_draft(player, request)
            draft = player.doubles_draft
            if player.locked_choice:
                return compact_text(f"Locked In\n{player.locked_choice}", limit=POPUP_LIMIT)
            lines = ["Current Choices"]
            for index, description in enumerate(draft.descriptions):
                lines.append(f"{doubles_slot_label(index)}: {description or 'pending'}")
            return compact_text("\n".join(lines), limit=POPUP_LIMIT)
        if player.locked_choice:
            return compact_text(f"Locked In\n{player.locked_choice}", limit=POPUP_LIMIT)
        return compact_text("No action locked in yet.", limit=POPUP_LIMIT)

    def team_analysis_caption_text(self, team_name: str, request: dict[str, Any]) -> str:
        team = self.team_snapshot_from_request(request)
        analysis = analyze_team_coverage(team)
        return format_analysis_caption(team_name, team, analysis)

    def team_detail_message_text(self, team_name: str, request: dict[str, Any]) -> str:
        return format_team_detail_text(team_name, self.team_snapshot_from_request(request))

    async def deliver_team_analysis(
        self,
        player: PlayerState,
        request: dict[str, Any],
        *,
        source_chat_id: int,
        source_message_id: int,
        prefer_private: bool,
    ) -> str:
        team = self.team_snapshot_from_request(request)
        if not team:
            return "Team analysis is unavailable right now."

        team_name = f"{player.name}'s Team"
        caption = self.team_analysis_caption_text(team_name, request)
        image_bytes = await create_team_image(team)
        target_chat_id = player.user_id if prefer_private else source_chat_id
        button_target = "dm" if prefer_private else "chat"
        detail_markup = types.InlineKeyboardMarkup()
        detail_markup.row(
            types.InlineKeyboardButton(
                "TEAM DETAIL",
                callback_data=f"teamview_detail_showdown_{button_target}_{player.user_id}",
            )
        )

        try:
            if image_bytes:
                await self.bot.send_photo(
                    target_chat_id,
                    photo=image_bytes,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=detail_markup,
                    reply_to_message_id=None if prefer_private else source_message_id,
                )
            else:
                await self.bot.send_message(
                    target_chat_id,
                    caption,
                    parse_mode="HTML",
                    reply_markup=detail_markup,
                    reply_to_message_id=None if prefer_private else source_message_id,
                )
        except Exception:
            if prefer_private:
                return "I couldn't send your team analysis to DM. Start the bot in private and try again."
            return "I couldn't send the team analysis right now."

        if prefer_private:
            return "Team analysis sent to your DM."
        return "Team analysis sent."

    async def deliver_team_detail(
        self,
        player: PlayerState,
        request: dict[str, Any],
        *,
        source_chat_id: int,
        source_message_id: int,
        prefer_private: bool,
    ) -> str:
        detail_text = self.team_detail_message_text(f"{player.name}'s Team", request)
        target_chat_id = player.user_id if prefer_private else source_chat_id
        try:
            await self.bot.send_message(
                target_chat_id,
                detail_text,
                reply_to_message_id=None if prefer_private else source_message_id,
            )
        except Exception:
            if prefer_private:
                return "I couldn't send your team detail to DM. Start the bot in private and try again."
            return "I couldn't send the team detail right now."
        if prefer_private:
            return "Team detail sent to your DM."
        return "Team detail sent."

    def is_doubles_battle(self, battle: BattleSession) -> bool:
        if is_doubles_battle_kind(getattr(battle, "battle_kind", "")):
            return True
        return str(getattr(battle.public_view, "gametype", "")).strip().lower() == "doubles"

    def is_multi_battle(self, battle: BattleSession) -> bool:
        return str(getattr(battle.public_view, "gametype", "")).strip().lower() == "multi"

    def is_freeforall_battle(self, battle: BattleSession) -> bool:
        return str(getattr(battle.public_view, "gametype", "")).strip().lower() == "freeforall"

    def supports_manual_target_selection(self, battle: BattleSession) -> bool:
        return self.is_multi_battle(battle) or self.is_freeforall_battle(battle)

    def is_doubles_request(self, request: dict[str, Any]) -> bool:
        return len(request.get("active") or []) > 1 or len(request.get("forceSwitch") or []) > 1

    def side_active_states(self, battle: BattleSession, side: str) -> list[dict[str, Any]]:
        return [
            battle.public_view.active.get(slot) or {}
            for slot in battle.public_view.active_slots_for_side(side)
        ]

    def primary_active_state(self, battle: BattleSession, side: str) -> dict[str, Any]:
        return battle.public_view.active_for_side(side, 0) or {}

    def challenge_visuals_label(self, enabled: bool) -> str:
        label = bool_label(bool(enabled))
        if enabled and not self.visual_renderer.available:
            return f"{label} [renderer unavailable]"
        return label

    def random_battle_generation_options(
        self,
        challenge: PendingChallenge | PendingFfaChallenge,
    ) -> list[tuple[int, Any]]:
        if normalize_mode(challenge.mode, battle_kind=challenge.battle_kind) != RANDOM_MODE:
            return []
        key_map = RANDOM_BATTLE_GENERATION_KEYS.get(normalize_battle_kind(challenge.battle_kind), {})
        if challenge.format_key not in set(key_map.values()):
            return []
        options: list[tuple[int, Any]] = []
        for generation, format_key in sorted(key_map.items(), reverse=True):
            options.append(
                (
                    generation,
                    resolve_format_option(challenge.battle_kind, challenge.mode, format_key),
                )
            )
        return options

    def current_random_battle_generation(
        self,
        challenge: PendingChallenge | PendingFfaChallenge,
    ) -> int | None:
        for generation, option in self.random_battle_generation_options(challenge):
            if option.key == challenge.format_key:
                return generation
        return None

    def _default_challenge_preferences(self, battle_kind: str) -> tuple[str, str, bool]:
        mode = RANDOM_MODE if normalize_battle_kind(battle_kind) == DOUBLES_BATTLE_KIND else OWNED_MODE
        option = default_format_option(battle_kind, mode)
        return mode, option.key, False

    def _challenge_preferences_for_user(self, user_id: int, battle_kind: str) -> tuple[str, str, bool]:
        visuals = db.get_battle_visuals_setting(user_id)
        default_mode, default_format_key, _default_visuals = self._default_challenge_preferences(battle_kind)
        saved_mode, saved_format_key = db.get_showdown_challenge_preferences(user_id, battle_kind)
        mode = normalize_mode(saved_mode or default_mode, battle_kind=battle_kind)
        option = resolve_format_option(battle_kind, mode, saved_format_key or default_format_key)
        return mode, option.key, visuals

    def _save_challenge_preferences(
        self,
        user_id: int,
        *,
        battle_kind: str | None = None,
        mode: str | None = None,
        format_key: str | None = None,
        visuals_enabled: bool | None = None,
    ) -> None:
        if battle_kind is not None and (mode is not None or format_key is not None):
            current_mode, current_format_key, _current_visuals = self._challenge_preferences_for_user(user_id, battle_kind)
            normalized_mode = normalize_mode(mode or current_mode, battle_kind=battle_kind)
            option = resolve_format_option(battle_kind, normalized_mode, format_key or current_format_key)
            db.set_showdown_challenge_preferences(
                user_id,
                battle_kind,
                mode=normalized_mode,
                format_key=option.key,
            )
        if visuals_enabled is not None:
            db.set_battle_visuals_setting(user_id, bool(visuals_enabled))

    def _user_battle_gate(self, user_id: int, name: str, *, require_team: bool) -> str | None:
        if not db.get_user_by_id(user_id):
            return f"{name} has not started the bot yet."
        ban_status = db.get_user_ban_status(user_id)
        if ban_status.get("is_banned"):
            return f"{name} is banned from the bot."
        if ban_status.get("is_battle_banned"):
            return f"{name} is banned from battling."
        if not require_team:
            return None
        active_team = db.get_active_team(user_id)
        if not active_team or not active_team[3]:
            return f"{name} does not have an active team selected."
        collection = db.get_collection(user_id)
        pokemon_map = {pokemon.pokemon_uuid: pokemon for pokemon in collection}
        team_members = [pokemon_map[uuid] for uuid in active_team[3] if uuid in pokemon_map]
        if not team_members:
            return f"{name}'s active team is empty."
        for pokemon in team_members:
            if not pokemon.moves:
                return f"{name}'s {pokemon.name} does not have any moves."
        return None

    async def _build_owned_team(self, user_id: int, trainer_name: str, format_id: str) -> str:
        gate = self._user_battle_gate(user_id, trainer_name, require_team=True)
        if gate:
            raise ShowdownBridgeError(gate)

        active_team = db.get_active_team(user_id)
        team_uuids = list(active_team[3] or [])
        collection = db.get_collection(user_id)
        pokemon_map = {pokemon.pokemon_uuid: pokemon for pokemon in collection}
        team_payload: list[dict[str, Any]] = []

        for pokemon_uuid in team_uuids:
            pokemon = pokemon_map.get(pokemon_uuid)
            if pokemon is None:
                continue
            species_data = SPECIES_BY_ID.get(pokemon.id, {})
            move_names = []
            for move_id in pokemon.moves:
                move_info = MOVE_BY_ID.get(move_id)
                move_names.append(move_info["name"] if move_info else str(move_id))
            team_payload.append(
                {
                    "name": pokemon.name,
                    "species": species_data.get("name", pokemon.name),
                    "item": pokemon.item or "",
                    "ability": pokemon.ability or "",
                    "moves": move_names,
                    "nature": pokemon.nature or "Serious",
                    "level": pokemon.level or 100,
                    "teraType": pokemon.tera_type or (species_data.get("types") or ["Normal"])[0],
                    "shiny": bool(getattr(pokemon, "is_shiny", False)),
                    "evs": {
                        "hp": pokemon.evs.hp,
                        "atk": pokemon.evs.atk,
                        "def": pokemon.evs.def_,
                        "spa": pokemon.evs.spa,
                        "spd": pokemon.evs.spd,
                        "spe": pokemon.evs.spe,
                    },
                    "ivs": {
                        "hp": pokemon.ivs.hp,
                        "atk": pokemon.ivs.atk,
                        "def": pokemon.ivs.def_,
                        "spa": pokemon.ivs.spa,
                        "spd": pokemon.ivs.spd,
                        "spe": pokemon.ivs.spe,
                    },
                }
            )

        if not team_payload:
            raise ShowdownBridgeError(f"{trainer_name}'s active team is empty.")

        packed = await pack_team(
            bot_dir=BOT_DIR,
            showdown_dir=SHOWDOWN_DIR,
            format_id=format_id,
            team=team_payload,
        )
        problems = [str(problem).strip() for problem in list(packed.get("problems") or []) if str(problem).strip()]
        if problems:
            raise ShowdownBridgeError(compact_text(f"{trainer_name}'s team is invalid: {'; '.join(problems)}", 600))
        packed_team = str(packed.get("packedTeam") or "").strip()
        if not packed_team:
            raise ShowdownBridgeError(f"Could not build {trainer_name}'s team.")
        return packed_team

    async def _issue_group_challenge(self, message: types.Message, *, battle_kind: str = SINGLES_BATTLE_KIND) -> None:
        if message.chat.type == "private":
            command_name = "/doubles" if is_doubles_battle_kind(battle_kind) else "/challenge"
            await self.bot.reply_to(message, f"Use {command_name} in a group chat.")
            return
        if not message.reply_to_message or not message.reply_to_message.from_user:
            command_name = "/doubles" if is_doubles_battle_kind(battle_kind) else "/challenge"
            await self.bot.reply_to(message, f"Reply to another player's message with {command_name}.")
            return

        challenger = message.from_user
        opponent = message.reply_to_message.from_user
        if opponent.is_bot:
            await self.bot.reply_to(message, "Battle challenges must target another user, not a bot.")
            return
        if challenger.id == opponent.id:
            await self.bot.reply_to(message, "You cannot challenge yourself.")
            return

        challenger_lock = self.showdown_lock_reason(challenger.id)
        if challenger_lock:
            await self.bot.reply_to(message, challenger_lock)
            return
        opponent_lock = self.showdown_lock_reason(opponent.id)
        if opponent_lock:
            await self.bot.reply_to(message, "That trainer is already busy with another PvP battle.")
            return
        legacy_challenger_lock = self.legacy_lock_reason(challenger.id)
        if legacy_challenger_lock:
            await self.bot.reply_to(message, legacy_challenger_lock)
            return
        legacy_opponent_lock = self.legacy_lock_reason(opponent.id)
        if legacy_opponent_lock:
            await self.bot.reply_to(message, f"{opponent.first_name} is already in another PvP battle.")
            return

        mode, format_key, visuals_enabled = self._challenge_preferences_for_user(challenger.id, battle_kind)
        settings_enabled = True
        require_team = mode == OWNED_MODE
        challenger_gate = self._user_battle_gate(challenger.id, challenger.first_name or "Challenger", require_team=require_team)
        if challenger_gate:
            await self.bot.reply_to(message, challenger_gate)
            return
        opponent_gate = self._user_battle_gate(opponent.id, opponent.first_name or "Opponent", require_team=require_team)
        if opponent_gate:
            await self.bot.reply_to(message, opponent_gate)
            return

        challenge = PendingChallenge(
            challenge_id=secrets.token_hex(4),
            chat_id=message.chat.id,
            public_message_id=0,
            source_message_id=message.message_id,
            challenger_id=challenger.id,
            challenger_name=challenger.first_name or "Trainer",
            opponent_id=opponent.id,
            opponent_name=opponent.first_name or "Trainer",
            mode=mode,
            format_key=format_key,
            visuals_enabled=visuals_enabled,
            battle_kind=battle_kind,
            settings_enabled=settings_enabled,
        )
        self.update_challenge_format(challenge)

        await self.expire_pending_challenges_for_users(
            [challenger.id, opponent.id],
            reason="This challenge expired because another challenge replaced it.",
        )

        sent = await self.bot.reply_to(
            message,
            self.challenge_text(challenge),
            parse_mode="HTML",
            reply_markup=self.challenge_buttons(challenge),
            disable_web_page_preview=True,
        )
        challenge.public_message_id = sent.message_id
        self._register_pending_challenge(challenge)

    async def on_challenge_command(self, message: types.Message) -> None:
        await self._issue_group_challenge(message, battle_kind=SINGLES_BATTLE_KIND)

    async def on_doubles_command(self, message: types.Message) -> None:
        await self._issue_group_challenge(message, battle_kind=DOUBLES_BATTLE_KIND)

    async def on_ffa_command(self, message: types.Message) -> None:
        if message.chat.type == "private":
            await self.bot.reply_to(message, "Use /ffa in a group chat.")
            return

        challenger = message.from_user
        challenger_lock = self.showdown_lock_reason(challenger.id)
        if challenger_lock:
            await self.bot.reply_to(message, challenger_lock)
            return
        legacy_challenger_lock = self.legacy_lock_reason(challenger.id)
        if legacy_challenger_lock:
            await self.bot.reply_to(message, legacy_challenger_lock)
            return

        mode, format_key, visuals_enabled = self._challenge_preferences_for_user(challenger.id, FREEFORALL_BATTLE_KIND)
        require_team = mode == OWNED_MODE
        challenger_gate = self._user_battle_gate(challenger.id, challenger.first_name or "Challenger", require_team=require_team)
        if challenger_gate:
            await self.bot.reply_to(message, challenger_gate)
            return

        challenge = PendingFfaChallenge(
            challenge_id=secrets.token_hex(4),
            chat_id=message.chat.id,
            public_message_id=0,
            source_message_id=message.message_id,
            challenger_id=challenger.id,
            challenger_name=challenger.first_name or "Trainer",
            mode=mode,
            format_key=format_key,
            visuals_enabled=visuals_enabled,
            slots={"p1": (challenger.id, challenger.first_name or "Trainer")},
        )
        self.update_challenge_format(challenge)

        await self.expire_pending_challenges_for_users(
            [challenger.id],
            reason="This challenge expired because another challenge replaced it.",
        )

        sent = await self.bot.send_message(
            message.chat.id,
            self.ffa_text(challenge),
            parse_mode="HTML",
            reply_markup=self.ffa_buttons(challenge),
            disable_web_page_preview=True,
            reply_to_message_id=message.message_id,
        )
        challenge.public_message_id = sent.message_id
        self._register_pending_ffa(challenge)

    async def handle_callback(self, call: types.CallbackQuery) -> None:
        data = str(call.data or "")
        if data.startswith("sdb:c:"):
            await self.handle_challenge_callback(call, data)
            return
        if data.startswith("sdb:f:"):
            await self.handle_ffa_callback(call, data)
            return
        if data.startswith("sdb:a:"):
            await self.handle_action_callback(call, data)
            return
        if data.startswith("sdb:bs:"):
            await self.handle_battle_stats_callback(call, data)
            return
        await self._answer(call.id, "Unknown battle button.", show_alert=True)

    async def on_exit_command(self, message: types.Message) -> None:
        cleared = await self.clear_user_state(message.from_user.id, actor_name=message.from_user.first_name or "Trainer")
        if cleared:
            await self.bot.reply_to(message, "\n".join(cleared))
            return
        await self.bot.reply_to(message, "No active battle state was found for you.")

    async def on_battle_stats_command(self, message: types.Message) -> None:
        battle = self.active_battle_for_user(message.from_user.id)
        if battle is None:
            await self.bot.reply_to(message, "No active battle found. Use /battle_stats during a battle.")
            return
        player = battle.player_for_user(message.from_user.id)
        if player is None:
            await self.bot.reply_to(message, "Only the active battler can use /battle_stats here.")
            return
        bridge = battle.bridge
        if bridge is None:
            await self.bot.reply_to(message, "The battle is still starting. Try /battle_stats again in a moment.")
            return
        try:
            snapshot = await bridge.battlefield_stats(player.slot)
        except ShowdownBridgeError as exc:
            await self.bot.reply_to(message, f"Could not load active battle stats.\n{compact_text(str(exc), 300)}")
            return
        await self.bot.reply_to(
            message,
            self.battle_stats_text(snapshot),
            parse_mode="HTML",
            reply_markup=self.battle_stats_buttons(message.from_user.id, snapshot),
        )

    async def handle_battle_stats_callback(self, call: types.CallbackQuery, data: str) -> None:
        parts = data.split(":")
        if len(parts) < 3:
            await self._answer(call.id, "Invalid stats button.", show_alert=True)
            return
        self.cleanup_battle_stats_reveals()
        reveal = self.battle_stats_reveals.get(parts[2])
        if not reveal:
            await self._answer(call.id, "This Tera reveal expired. Use /battle_stats again.", show_alert=True)
            return
        if int(reveal.get("user_id") or 0) != call.from_user.id:
            await self._answer(call.id, "Only the trainer who used /battle_stats can reveal this.", show_alert=True)
            return
        await self._answer(call.id, str(reveal.get("text") or "No Tera type is available."), show_alert=True)

    def battle_stats_buttons(self, user_id: int, snapshot: dict[str, Any]) -> types.InlineKeyboardMarkup | None:
        reveal_text = self.battle_stats_tera_reveal_text(snapshot)
        if not reveal_text:
            return None
        self.cleanup_battle_stats_reveals()
        token = secrets.token_urlsafe(8)
        self.battle_stats_reveals[token] = {
            "user_id": user_id,
            "expires_at": asyncio.get_running_loop().time() + BATTLE_STATS_REVEAL_SECONDS,
            "text": compact_text(reveal_text, POPUP_LIMIT),
        }
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.row(types.InlineKeyboardButton("Tera Type", callback_data=f"sdb:bs:{token}"))
        return markup

    def cleanup_battle_stats_reveals(self) -> None:
        now = asyncio.get_running_loop().time()
        expired = [
            token
            for token, reveal in self.battle_stats_reveals.items()
            if float(reveal.get("expires_at") or 0) <= now
        ]
        for token in expired:
            self.battle_stats_reveals.pop(token, None)

    def parse_test_battle_image_species(self, raw_text: str) -> tuple[str, str, bool, bool]:
        text = str(raw_text or "").strip()
        if not text:
            return "Pikachu", "Charizard", False, False
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return "Pikachu", "Charizard", False, False
        query = parts[1].strip()
        for separator in ("|", " vs ", ","):
            if separator in query:
                left, right = query.split(separator, 1)
                player_species, player_dynamaxed = self.parse_test_sprite_token(left.strip() or "Pikachu")
                opponent_species, opponent_dynamaxed = self.parse_test_sprite_token(right.strip() or "Charizard")
                return player_species, opponent_species, player_dynamaxed, opponent_dynamaxed
        player_species, player_dynamaxed = self.parse_test_sprite_token(query)
        return player_species, "Charizard", player_dynamaxed, False

    def parse_test_sprite_token(self, value: str) -> tuple[str, bool]:
        text = str(value or "").strip()
        dynamaxed = False
        for suffix in ("-dynamax", "-dyna", "-max"):
            if text.lower().endswith(suffix):
                text = text[: -len(suffix)].strip()
                dynamaxed = True
                break
        return text or "Pikachu", dynamaxed

    async def on_test_battle_image_command(self, message: types.Message) -> None:
        if not self.visual_renderer.available:
            await self.bot.reply_to(message, "Battle visuals are unavailable. Install Pillow first.")
            return
        player_species, opponent_species, player_dynamaxed, opponent_dynamaxed = self.parse_test_battle_image_species(message.text)
        payload = self.visual_renderer.render_preview(
            player_species=player_species,
            opponent_species=opponent_species,
            player_dynamaxed=player_dynamaxed,
            opponent_dynamaxed=opponent_dynamaxed,
            highlight_slot="p1",
        )
        if payload is None:
            await self.bot.reply_to(message, "Could not build a test battle image right now.")
            return
        file_obj, _ = payload
        await self.bot.send_photo(
            message.chat.id,
            photo=file_obj,
            caption=(
                "Battle sprite test\n"
                f"Player: {player_species}{' (Dynamax)' if player_dynamaxed else ''}\n"
                f"Opponent: {opponent_species}{' (Dynamax)' if opponent_dynamaxed else ''}\n"
                "Try: /testsprite Pikachu-dynamax | Charizard\n"
                "Edit bot/showdown_battle/visuals.py.\n"
                "Tune PLAYER_LAYOUT, OPPONENT_LAYOUT, PLAYER_PLATFORM, and OPPONENT_PLATFORM."
            ),
            reply_to_message_id=message.message_id,
        )

    async def clear_user_state(self, user_id: int, *, actor_name: str) -> list[str]:
        messages: list[str] = []
        related_challenges = [
            challenge
            for challenge in list(self.pending_by_id.values())
            if challenge.challenger_id == user_id or challenge.opponent_id == user_id
        ]
        for challenge in related_challenges:
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                f"Challenge cancelled because {actor_name} used /exit.",
                reply_markup=None,
            )
            self._release_pending_challenge(challenge)
            messages.append("Cancelled your pending PvP challenge.")

        related_ffa_challenges = [
            challenge
            for challenge in list(self.pending_ffa_by_id.values())
            if any(slot_user_id == user_id for slot_user_id, _name in challenge.slots.values())
        ]
        for challenge in related_ffa_challenges:
            if challenge.challenger_id == user_id:
                await self._edit_message(
                    challenge.chat_id,
                    challenge.public_message_id,
                    f"FFA lobby cancelled because {actor_name} used /exit.",
                    reply_markup=None,
                )
                self._release_pending_ffa(challenge)
                messages.append("Cancelled your pending FFA lobby.")
                continue
            slot_to_clear = next(
                (slot for slot, (slot_user_id, _name) in challenge.slots.items() if slot_user_id == user_id),
                None,
            )
            if slot_to_clear:
                self.clear_ffa_slot(challenge, slot_to_clear)
                await self._edit_message(
                    challenge.chat_id,
                    challenge.public_message_id,
                    self.ffa_text(challenge),
                    reply_markup=self.ffa_buttons(challenge),
                    parse_mode="HTML",
                )
                messages.append("Left your pending FFA lobby.")

        battle_id = self.active_by_user.get(user_id)
        if battle_id is not None:
            battle = self.battles_by_id.get(battle_id)
            if battle is None:
                self.active_by_user.pop(user_id, None)
                messages.append("Cleared a stale PvP battle reservation.")
            else:
                exiting_player = battle.player_for_user(user_id)
                leaver_name = exiting_player.name if exiting_player is not None else actor_name
                async with battle.lock:
                    battle.finished = True
                    await self._edit_message(
                        battle.chat_id,
                        battle.public_message_id,
                        f"Battle closed because {leaver_name} used /exit.",
                        reply_markup=None,
                    )
                    self.battles_by_id.pop(battle.battle_id, None)
                    self._release_active_battle(battle)
                    if battle.bridge is not None:
                        await battle.bridge.close()
                messages.append("Closed your active PvP battle.")

        try:
            from bot.battle.battle_engine import active_battles
            from bot.battle.battle_handlers import pending_challenges
        except Exception:
            return messages

        legacy_challenge_ids = [
            challenge_id
            for challenge_id, challenge in list(pending_challenges.items())
            if user_id in {challenge.get("challenger_id"), challenge.get("opponent_id")}
        ]
        for challenge_id in legacy_challenge_ids:
            challenge = pending_challenges.pop(challenge_id, None)
            if not challenge:
                continue
            target_message_id = int(challenge.get("challenge_message_id") or 0)
            cancel_text = f"Legacy /clash challenge cancelled because {actor_name} used /exit."
            if target_message_id:
                try:
                    await self.bot.edit_message_text(
                        cancel_text,
                        chat_id=challenge["chat_id"],
                        message_id=target_message_id,
                        reply_markup=None,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            else:
                try:
                    await self.bot.send_message(challenge["chat_id"], cancel_text)
                except Exception:
                    pass
            messages.append("Cancelled your pending /clash challenge.")

        for chat_id, raw_chat_battles in list(active_battles.items()):
            chat_battles = raw_chat_battles if isinstance(raw_chat_battles, list) else [raw_chat_battles]
            for battle in list(chat_battles):
                if user_id not in {battle.player1.user_id, battle.player2.user_id}:
                    continue
                if battle.timer_task:
                    battle.timer_task.cancel()
                battle.state = "finished"
                try:
                    if battle.message_id:
                        await self.bot.edit_message_caption(
                            f"Battle closed because {actor_name} used /exit.",
                            chat_id=battle.chat_id,
                            message_id=battle.message_id,
                            reply_markup=None,
                            parse_mode="HTML",
                        )
                except Exception:
                    try:
                        if battle.message_id:
                            await self.bot.edit_message_text(
                                f"Battle closed because {actor_name} used /exit.",
                                chat_id=battle.chat_id,
                                message_id=battle.message_id,
                                reply_markup=None,
                                parse_mode="HTML",
                            )
                    except Exception:
                        pass
                if battle in chat_battles:
                    chat_battles.remove(battle)
                messages.append("Closed your active /clash battle.")
            if not chat_battles:
                active_battles.pop(chat_id, None)
            elif isinstance(raw_chat_battles, list):
                active_battles[chat_id] = chat_battles
            else:
                active_battles[chat_id] = chat_battles[0]
        return messages

    def challenge_text(self, challenge: PendingChallenge) -> str:
        challenger_link = mention_html(challenge.challenger_id, challenge.challenger_name)
        opponent_link = mention_html(challenge.opponent_id, challenge.opponent_name or "Trainer")
        text = (
            f"🎫 <b>BATTLE ISSUED</b>\n"
            f"<b>Type:</b> {html.escape(self.battle_kind_label(challenge.battle_kind))}\n"
            f"<b>Challenger:</b> {challenger_link}\n"
            f"<b>Opponent:</b> {opponent_link}\n\n"
            f"<b>Match Settings:</b>\n"
            f"├ <b>Mode:</b> {html.escape(self.challenge_mode_label(challenge.mode, challenge.battle_kind))}\n"
            f"├ <b>Filter:</b> {html.escape(resolve_format_option(challenge.battle_kind, challenge.mode, challenge.format_key).label)}\n"
            f"├ <b>Format:</b> {html.escape(challenge.format_label)}\n"
            f"└ <b>Visuals:</b> {html.escape(self.challenge_visuals_label(challenge.visuals_enabled))}\n\n"
            f"🟡 <i>Status: {html.escape(self.challenge_status_label(challenge))}</i>"
        )
        return text

    def challenge_buttons(self, challenge: PendingChallenge) -> types.InlineKeyboardMarkup | None:
        if challenge.state != "open":
            return None
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.row(
            types.InlineKeyboardButton("Accept", callback_data=f"sdb:c:{challenge.challenge_id}:accept"),
            types.InlineKeyboardButton("Decline", callback_data=f"sdb:c:{challenge.challenge_id}:decline"),
        )
        if challenge.settings_enabled:
            markup.row(types.InlineKeyboardButton("Settings", callback_data=f"sdb:c:{challenge.challenge_id}:settings"))
        return markup

    def challenge_settings_text(
        self,
        challenge: PendingChallenge | PendingFfaChallenge,
        *,
        view: str = "root",
        page: int = 0,
    ) -> str:
        lines = ["Challenge settings", ""]
        lines.append(f"Battle type: {self.battle_kind_label(challenge.battle_kind)}")
        lines.append(f"Main mode: {self.challenge_mode_label(challenge.mode, challenge.battle_kind)}")
        lines.append(f"Filter: {resolve_format_option(challenge.battle_kind, challenge.mode, challenge.format_key).label}")
        lines.append(f"Format preview: {challenge.format_label}")
        current_generation = self.current_random_battle_generation(challenge)
        if current_generation is not None:
            lines.append(f"Generation: Gen {current_generation}")
        lines.append(f"Visuals: {self.challenge_visuals_label(challenge.visuals_enabled)}")
        lines.append("")
        if view == "mode":
            lines.append("Choose the main mode.")
        elif view == "filters":
            options = format_options_for(challenge.battle_kind, challenge.mode)
            total_pages = max(1, (len(options) + 7) // 8)
            lines.append(f"Choose the format filter. Page {page + 1}/{total_pages}.")
        elif view == "visuals":
            lines.append("Choose whether battles should render a pixel battle scene.")
            if not self.visual_renderer.available:
                lines.append("The renderer will activate after Pillow is installed on this host.")
        elif view == "generation":
            generation_options = self.random_battle_generation_options(challenge)
            if generation_options:
                lines.append("Choose a generation for this random battle format.")
            else:
                lines.append("Generation selection is not available for this format.")
        else:
            lines.append("Change the main mode first, then pick the matching filter.")
        lines.append("")
        lines.append("Changes save automatically.")
        return "\n".join(lines)

    def _settings_callback_prefix(self, challenge: PendingChallenge | PendingFfaChallenge) -> str:
        return f"sdb:{'f' if isinstance(challenge, PendingFfaChallenge) else 'c'}:{challenge.challenge_id}:settings"

    def challenge_settings_buttons(
        self,
        challenge: PendingChallenge | PendingFfaChallenge,
        *,
        view: str = "root",
        page: int = 0,
    ) -> types.InlineKeyboardMarkup:
        challenge_id = challenge.challenge_id
        prefix = self._settings_callback_prefix(challenge)
        markup = types.InlineKeyboardMarkup(row_width=2)

        if view == "mode":
            buttons = []
            for mode, label in self.mode_options(challenge.battle_kind):
                buttons.append(
                    types.InlineKeyboardButton(
                        f"{label} *" if challenge.mode == mode else label,
                        callback_data=f"{prefix}:setmode:{mode}",
                    )
                )
            markup.row(*buttons)
            markup.row(types.InlineKeyboardButton("Back", callback_data=f"{prefix}"))
            return markup

        if view == "visuals":
            markup.row(
                types.InlineKeyboardButton(
                    "On *" if challenge.visuals_enabled else "On",
                    callback_data=f"{prefix}:setvisuals:on",
                ),
                types.InlineKeyboardButton(
                    "Off *" if not challenge.visuals_enabled else "Off",
                    callback_data=f"{prefix}:setvisuals:off",
                ),
            )
            markup.row(types.InlineKeyboardButton("Back", callback_data=f"{prefix}"))
            return markup

        if view == "generation":
            generation_specs = [
                (
                    f"Gen {generation} *" if option.key == challenge.format_key else f"Gen {generation}",
                    f"{prefix}:setgen:{generation}",
                )
                for generation, option in self.random_battle_generation_options(challenge)
            ]
            for row in chunk_specs(generation_specs, per_row=3):
                markup.row(*(types.InlineKeyboardButton(label, callback_data=data) for label, data in row))
            markup.row(types.InlineKeyboardButton("Back", callback_data=f"{prefix}"))
            return markup

        if view == "filters":
            options = list(format_options_for(challenge.battle_kind, challenge.mode))
            start = max(0, page) * 8
            page_options = options[start:start + 8]
            for row in chunk_specs(
                [
                    (
                        f"{option.short_label} *" if option.key == challenge.format_key else option.short_label,
                        f"{prefix}:setfilter:{option.key}:{page}",
                    )
                    for option in page_options
                ],
                per_row=4,
            ):
                markup.row(*(types.InlineKeyboardButton(label, callback_data=data) for label, data in row))
            total_pages = max(1, (len(options) + 7) // 8)
            nav: list[types.InlineKeyboardButton] = []
            if page > 0:
                nav.append(types.InlineKeyboardButton("Prev", callback_data=f"{prefix}:filters:{page - 1}"))
            if page + 1 < total_pages:
                nav.append(types.InlineKeyboardButton("Next", callback_data=f"{prefix}:filters:{page + 1}"))
            if nav:
                markup.row(*nav)
            markup.row(types.InlineKeyboardButton("Back", callback_data=f"{prefix}"))
            return markup

        markup.row(
            types.InlineKeyboardButton("Main Mode", callback_data=f"{prefix}:mode"),
            types.InlineKeyboardButton("Filters", callback_data=f"{prefix}:filters:0"),
        )
        if len(self.random_battle_generation_options(challenge)) > 1:
            markup.row(types.InlineKeyboardButton("Generation", callback_data=f"{prefix}:generation"))
        markup.row(types.InlineKeyboardButton("Visuals", callback_data=f"{prefix}:visuals"))
        markup.row(types.InlineKeyboardButton("Reset", callback_data=f"{prefix}:reset"))
        markup.row(types.InlineKeyboardButton("Back", callback_data=f"{prefix}:back"))
        return markup

    def ffa_text(self, challenge: PendingFfaChallenge) -> str:
        required_players = 4
        lines = [
            "🎫 <b>FFA LOBBY</b>",
            f"<b>Type:</b> {html.escape(self.battle_kind_label(challenge.battle_kind))}",
            f"<b>Host:</b> {mention_html(challenge.challenger_id, challenge.challenger_name)}",
            "",
            "<b>Match Settings:</b>",
            f"├ <b>Mode:</b> {html.escape(self.challenge_mode_label(challenge.mode, challenge.battle_kind))}",
            f"├ <b>Filter:</b> {html.escape(resolve_format_option(challenge.battle_kind, challenge.mode, challenge.format_key).label)}",
            f"├ <b>Format:</b> {html.escape(challenge.format_label)}",
            f"└ <b>Visuals:</b> {html.escape(self.challenge_visuals_label(challenge.visuals_enabled))}",
            "",
            "<b>Players</b>",
        ]
        joined = 0
        for slot in ("p1", "p2", "p3", "p4"):
            occupant = challenge.slots.get(slot)
            if occupant:
                joined += 1
                lines.append(f"{slot[1:]}. {mention_html(occupant[0], occupant[1])}")
            else:
                lines.append(f"{slot[1:]}. <i>Open</i>")
        if challenge.format_id == MULTI_RANDOM_BATTLE_FORMAT_ID:
            lines.append("")
            lines.append("<i>Team order: 1 + 2 vs 3 + 4.</i>")
        lines.extend(
            [
                "",
                f"🟡 <i>Status: {html.escape(self.challenge_status_label(challenge))}</i>",
                f"<i>{joined}/{required_players} joined. The host can start once all {required_players} players are in.</i>",
            ]
        )
        return "\n".join(lines)

    def ffa_buttons(self, challenge: PendingFfaChallenge) -> types.InlineKeyboardMarkup | None:
        if challenge.state != "open":
            return None
        markup = types.InlineKeyboardMarkup(row_width=2)
        for row_slots in (("p1", "p2"), ("p3", "p4")):
            buttons = []
            for slot in row_slots:
                occupant = challenge.slots.get(slot)
                label = f"{slot[1:]} {'🟢' if occupant else '🔴'}"
                buttons.append(types.InlineKeyboardButton(label, callback_data=f"sdb:f:{challenge.challenge_id}:slot:{slot}"))
            markup.row(*buttons)
        markup.row(
            types.InlineKeyboardButton("Start", callback_data=f"sdb:f:{challenge.challenge_id}:start"),
            types.InlineKeyboardButton("Cancel", callback_data=f"sdb:f:{challenge.challenge_id}:cancel"),
        )
        markup.row(types.InlineKeyboardButton("Settings", callback_data=f"sdb:f:{challenge.challenge_id}:settings"))
        return markup

    async def handle_settings_callback(
        self,
        call: types.CallbackQuery,
        challenge: PendingChallenge | PendingFfaChallenge,
        parts: list[str],
        *,
        close_text: str,
        close_markup: types.InlineKeyboardMarkup | None,
    ) -> bool:
        if not challenge.settings_enabled:
            await self._answer(call.id, "Settings are disabled for this challenge.", show_alert=True)
            return True
        if call.from_user.id != challenge.challenger_id:
            await self._answer(call.id, "Only the challenge host can change settings.", show_alert=True)
            return True

        view = "root"
        page = 0
        if len(parts) >= 5:
            subaction = parts[4]
            if subaction == "back":
                await self._edit_message(
                    challenge.chat_id,
                    challenge.public_message_id,
                    close_text,
                    reply_markup=close_markup,
                    parse_mode="HTML",
                )
                await self._answer(call.id)
                return True
            if subaction == "mode":
                view = "mode"
            elif subaction == "filters":
                view = "filters"
                if len(parts) >= 6:
                    try:
                        page = max(0, int(parts[5]))
                    except ValueError:
                        page = 0
            elif subaction == "visuals":
                view = "visuals"
            elif subaction == "generation":
                view = "generation"
            elif subaction == "reset":
                challenge.mode, challenge.format_key, default_visuals = self._default_challenge_preferences(challenge.battle_kind)
                challenge.visuals_enabled = default_visuals
                self.update_challenge_format(challenge)
                self._save_challenge_preferences(
                    challenge.challenger_id,
                    battle_kind=challenge.battle_kind,
                    mode=challenge.mode,
                    format_key=challenge.format_key,
                    visuals_enabled=challenge.visuals_enabled,
                )
            elif subaction == "setmode" and len(parts) >= 6:
                challenge.mode = normalize_mode(parts[5], battle_kind=challenge.battle_kind)
                challenge.format_key = default_format_option(challenge.battle_kind, challenge.mode).key
                self.update_challenge_format(challenge)
                self._save_challenge_preferences(
                    challenge.challenger_id,
                    battle_kind=challenge.battle_kind,
                    mode=challenge.mode,
                    format_key=challenge.format_key,
                )
                view = "mode"
            elif subaction == "setfilter" and len(parts) >= 6:
                challenge.format_key = parts[5].strip().lower()
                if len(parts) >= 7:
                    try:
                        page = max(0, int(parts[6]))
                    except ValueError:
                        page = 0
                self.update_challenge_format(challenge)
                self._save_challenge_preferences(
                    challenge.challenger_id,
                    battle_kind=challenge.battle_kind,
                    mode=challenge.mode,
                    format_key=challenge.format_key,
                )
                view = "filters"
            elif subaction == "setgen" and len(parts) >= 6:
                try:
                    generation = int(parts[5])
                except ValueError:
                    await self._answer(call.id, "That generation is not valid.", show_alert=True)
                    return True
                generation_options = {
                    available_generation: option
                    for available_generation, option in self.random_battle_generation_options(challenge)
                }
                option = generation_options.get(generation)
                if option is None:
                    await self._answer(call.id, "That generation is not available for this format.", show_alert=True)
                    return True
                challenge.format_key = option.key
                self.update_challenge_format(challenge)
                self._save_challenge_preferences(
                    challenge.challenger_id,
                    battle_kind=challenge.battle_kind,
                    mode=challenge.mode,
                    format_key=challenge.format_key,
                )
                view = "generation"
            elif subaction == "setvisuals" and len(parts) >= 6:
                challenge.visuals_enabled = parts[5].strip().lower() == "on"
                self._save_challenge_preferences(challenge.challenger_id, visuals_enabled=challenge.visuals_enabled)
                view = "visuals"
            else:
                await self._answer(call.id, "Unknown settings action.", show_alert=True)
                return True

        await self._edit_message(
            challenge.chat_id,
            challenge.public_message_id,
            self.challenge_settings_text(challenge, view=view, page=page),
            reply_markup=self.challenge_settings_buttons(challenge, view=view, page=page),
        )
        await self._answer(call.id)
        return True

    async def handle_challenge_callback(self, call: types.CallbackQuery, data: str) -> None:
        parts = data.split(":")
        if len(parts) < 4:
            await self._answer(call.id, "Invalid challenge button.", show_alert=True)
            return

        challenge = self.pending_by_id.get(parts[2])
        if not challenge:
            await self._answer(call.id, "That challenge is no longer active.", show_alert=True)
            return
        if self._is_challenge_expired(challenge):
            challenge.state = "expired"
            self._release_pending_challenge(challenge)
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                self.challenge_text(challenge),
                reply_markup=None,
                parse_mode="HTML",
            )
            await self._answer(call.id, "Challenge expired.", show_alert=True)
            return
        if challenge.state != "open":
            await self._answer(call.id, f"This challenge is already {self.challenge_status_label(challenge)}.", show_alert=True)
            return

        action = parts[3]
        if action == "decline":
            if call.from_user.id == challenge.challenger_id:
                challenge.state = "cancelled"
                self._release_pending_challenge(challenge)
                await self._edit_message(challenge.chat_id, challenge.public_message_id, "Challenge cancelled.", reply_markup=None)
                await self._answer(call.id, "Cancelled.")
                return
            if call.from_user.id != challenge.opponent_id:
                await self._answer(call.id, "Only the invited trainer can decline this challenge.", show_alert=True)
                return
            challenge.state = "declined"
            self._release_pending_challenge(challenge)
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                self.challenge_text(challenge),
                reply_markup=None,
                parse_mode="HTML",
            )
            await self._answer(call.id, "Declined.")
            return

        if action == "settings":
            await self.handle_settings_callback(
                call,
                challenge,
                parts,
                close_text=self.challenge_text(challenge),
                close_markup=self.challenge_buttons(challenge),
            )
            return

        if action != "accept":
            await self._answer(call.id, "Unknown challenge action.", show_alert=True)
            return
        if call.from_user.id == challenge.challenger_id:
            await self._answer(call.id, "You cannot accept your own challenge.", show_alert=True)
            return
        if call.from_user.id != challenge.opponent_id:
            await self._answer(call.id, "This challenge is for someone else.", show_alert=True)
            return

        require_team = challenge.mode == "owned"
        challenger_legacy_lock = self.legacy_lock_reason(challenge.challenger_id)
        if challenger_legacy_lock:
            self._release_pending_challenge(challenge)
            await self._edit_message(challenge.chat_id, challenge.public_message_id, challenger_legacy_lock, reply_markup=None)
            await self._answer(call.id, "Challenge failed.", show_alert=True)
            return
        opponent_legacy_lock = self.legacy_lock_reason(challenge.opponent_id or 0)
        if opponent_legacy_lock:
            self._release_pending_challenge(challenge)
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                f"{challenge.opponent_name or 'Trainer'} is already in another PvP battle.",
                reply_markup=None,
            )
            await self._answer(call.id, "Challenge failed.", show_alert=True)
            return
        challenger_gate = self._user_battle_gate(challenge.challenger_id, challenge.challenger_name, require_team=require_team)
        if challenger_gate:
            self._release_pending_challenge(challenge)
            await self._edit_message(challenge.chat_id, challenge.public_message_id, challenger_gate, reply_markup=None)
            await self._answer(call.id, "Challenge failed.", show_alert=True)
            return
        opponent_gate = self._user_battle_gate(challenge.opponent_id or 0, challenge.opponent_name or "Trainer", require_team=require_team)
        if opponent_gate:
            self._release_pending_challenge(challenge)
            await self._edit_message(challenge.chat_id, challenge.public_message_id, opponent_gate, reply_markup=None)
            await self._answer(call.id, "Challenge failed.", show_alert=True)
            return

        challenge.state = "starting"
        await self._edit_message(
            challenge.chat_id,
            challenge.public_message_id,
            self.challenge_text(challenge),
            reply_markup=None,
            parse_mode="HTML",
        )
        await self._answer(call.id, "Preparing battle...")
        await self.expire_pending_challenges_for_users(
            [challenge.challenger_id, challenge.opponent_id or 0],
            keep_challenge_id=challenge.challenge_id,
            reason="This challenge expired because another battle was accepted.",
        )
        await self.start_challenge(challenge)

    async def handle_ffa_callback(self, call: types.CallbackQuery, data: str) -> None:
        parts = data.split(":")
        if len(parts) < 4:
            await self._answer(call.id, "Invalid FFA button.", show_alert=True)
            return

        challenge = self.pending_ffa_by_id.get(parts[2])
        if not challenge:
            await self._answer(call.id, "That FFA lobby is no longer active.", show_alert=True)
            return
        if self._is_challenge_expired(challenge):
            challenge.state = "expired"
            self._release_pending_ffa(challenge)
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                self.ffa_text(challenge),
                reply_markup=None,
                parse_mode="HTML",
            )
            await self._answer(call.id, "FFA lobby expired.", show_alert=True)
            return
        if challenge.state != "open":
            await self._answer(call.id, f"This FFA lobby is already {self.challenge_status_label(challenge)}.", show_alert=True)
            return

        action = parts[3]
        if action == "settings":
            await self.handle_settings_callback(
                call,
                challenge,
                parts,
                close_text=self.ffa_text(challenge),
                close_markup=self.ffa_buttons(challenge),
            )
            return

        if action == "cancel":
            if call.from_user.id != challenge.challenger_id:
                await self._answer(call.id, "Only the host can cancel this FFA lobby.", show_alert=True)
                return
            challenge.state = "cancelled"
            self._release_pending_ffa(challenge)
            await self._edit_message(challenge.chat_id, challenge.public_message_id, "FFA lobby cancelled.", reply_markup=None)
            await self._answer(call.id, "Cancelled.")
            return

        if action == "slot" and len(parts) >= 5:
            slot = parts[4]
            if slot not in {"p1", "p2", "p3", "p4"}:
                await self._answer(call.id, "Unknown FFA slot.", show_alert=True)
                return
            occupant = challenge.slots.get(slot)
            if occupant and occupant[0] == call.from_user.id:
                if slot == "p1":
                    await self._answer(call.id, "The host stays in slot 1.", show_alert=True)
                    return
                self.clear_ffa_slot(challenge, slot)
                await self._edit_message(
                    challenge.chat_id,
                    challenge.public_message_id,
                    self.ffa_text(challenge),
                    reply_markup=self.ffa_buttons(challenge),
                    parse_mode="HTML",
                )
                await self._answer(call.id, "Left the FFA lobby.")
                return
            if occupant:
                await self._answer(call.id, "That slot is already taken.", show_alert=True)
                return
            if any(user_id == call.from_user.id for user_id, _name in challenge.slots.values()):
                await self._answer(call.id, "You are already in this FFA lobby.", show_alert=True)
                return
            join_lock = self.showdown_lock_reason(call.from_user.id)
            if join_lock:
                await self._answer(call.id, join_lock, show_alert=True)
                return
            legacy_lock = self.legacy_lock_reason(call.from_user.id)
            if legacy_lock:
                await self._answer(call.id, legacy_lock, show_alert=True)
                return
            require_team = challenge.mode == OWNED_MODE
            gate = self._user_battle_gate(call.from_user.id, call.from_user.first_name or "Trainer", require_team=require_team)
            if gate:
                await self._answer(call.id, gate, show_alert=True)
                return
            self.set_ffa_slot(challenge, slot, call.from_user.id, call.from_user.first_name or "Trainer")
            await self._edit_message(
                challenge.chat_id,
                challenge.public_message_id,
                self.ffa_text(challenge),
                reply_markup=self.ffa_buttons(challenge),
                parse_mode="HTML",
            )
            await self._answer(call.id, f"Joined slot {slot[1:]}.")
            return

        if action != "start":
            await self._answer(call.id, "Unknown FFA action.", show_alert=True)
            return
        if call.from_user.id != challenge.challenger_id:
            await self._answer(call.id, "Only the host can start this FFA lobby.", show_alert=True)
            return
        if len(challenge.slots) < 4:
            await self._answer(call.id, "All 4 players must join before this lobby can start.", show_alert=True)
            return

        challenge.state = "starting"
        await self._edit_message(
            challenge.chat_id,
            challenge.public_message_id,
            self.ffa_text(challenge),
            reply_markup=None,
            parse_mode="HTML",
        )
        await self._answer(call.id, "Preparing FFA battle...")
        await self.expire_pending_challenges_for_users(
            [user_id for user_id, _name in challenge.slots.values()],
            keep_challenge_id=challenge.challenge_id,
            reason="This challenge expired because another battle was accepted.",
        )
        await self.start_ffa_challenge(challenge)

    async def start_challenge(self, challenge: PendingChallenge) -> None:
        participants = {
            "p1": (challenge.challenger_id, challenge.challenger_name),
            "p2": (challenge.opponent_id or 0, challenge.opponent_name or "Trainer"),
        }
        self._release_pending_challenge(challenge)
        await self.start_battle_from_participants(
            challenge_id=challenge.challenge_id,
            chat_id=challenge.chat_id,
            public_message_id=challenge.public_message_id,
            source_message_id=challenge.source_message_id,
            participants=participants,
            format_id=challenge.format_id,
            format_label=challenge.format_label,
            battle_kind=challenge.battle_kind,
            mode=challenge.mode,
            visuals_enabled=challenge.visuals_enabled,
        )

    async def start_ffa_challenge(self, challenge: PendingFfaChallenge) -> None:
        self._release_pending_ffa(challenge)
        await self.start_battle_from_participants(
            challenge_id=challenge.challenge_id,
            chat_id=challenge.chat_id,
            public_message_id=challenge.public_message_id,
            source_message_id=challenge.source_message_id,
            participants=dict(sorted(challenge.slots.items(), key=lambda item: self.slot_sort_key(item[0]))),
            format_id=challenge.format_id,
            format_label=challenge.format_label,
            battle_kind=challenge.battle_kind,
            mode=challenge.mode,
            visuals_enabled=challenge.visuals_enabled,
        )

    async def start_battle_from_participants(
        self,
        *,
        challenge_id: str,
        chat_id: int,
        public_message_id: int,
        source_message_id: int,
        participants: dict[str, tuple[int, str]],
        format_id: str,
        format_label: str,
        battle_kind: str,
        mode: str,
        visuals_enabled: bool,
    ) -> None:
        display_slot_order = sorted(participants, key=self.slot_sort_key)
        if format_id == MULTI_RANDOM_BATTLE_FORMAT_ID and all(slot in participants for slot in ("p1", "p2", "p3", "p4")):
            participants = {
                "p1": participants["p1"],
                "p3": participants["p2"],
                "p2": participants["p3"],
                "p4": participants["p4"],
            }
            display_slot_order = ["p1", "p3", "p2", "p4"]
        packed_teams: dict[str, str | None] = {slot: None for slot in participants}
        if mode == OWNED_MODE:
            try:
                for slot, (user_id, trainer_name) in participants.items():
                    packed_teams[slot] = await self._build_owned_team(user_id, trainer_name, format_id)
            except ShowdownBridgeError as exc:
                await self._edit_message(
                    chat_id,
                    public_message_id,
                    compact_text(str(exc), 700),
                    reply_markup=None,
                )
                return

        battle = BattleSession(
            battle_id=challenge_id,
            chat_id=chat_id,
            public_message_id=public_message_id,
            format_id=format_id,
            format_label=format_label,
            players={
                slot: PlayerState(slot=slot, user_id=user_id, name=name)
                for slot, (user_id, name) in participants.items()
            },
            public_view=PublicBattleView({slot: name for slot, (_user_id, name) in participants.items()}),
            battle_kind=battle_kind,
            metadata={
                "visuals_enabled": bool(visuals_enabled),
                "battle_kind": battle_kind,
                "display_slot_order": display_slot_order,
                "origin_message_id": public_message_id,
                "reply_source_message_id": source_message_id,
                "challenge_message_id": public_message_id,
            },
        )
        self._register_active_battle(battle)
        try:
            await self._start_battle_session(
                battle,
                player_teams=packed_teams,
                failure_chat_id=chat_id,
                failure_message_id=public_message_id,
            )
        except Exception:
            self._release_active_battle(battle)

    async def _start_battle_session(
        self,
        battle: BattleSession,
        *,
        player_teams: dict[str, str | None],
        failure_chat_id: int,
        failure_message_id: int,
    ) -> None:
        if not SHOWDOWN_DIR.exists():
            await self._edit_message(
                failure_chat_id,
                failure_message_id,
                f"Showdown server directory not found: {SHOWDOWN_DIR}",
                reply_markup=None,
            )
            raise ShowdownBridgeError("Showdown server directory not found.")

        battle.bridge = ShowdownBattleProcess(
            battle_id=battle.battle_id,
            bot_dir=BOT_DIR,
            showdown_dir=SHOWDOWN_DIR,
            format_id=battle.format_id,
            players={
                slot: {
                    "name": player.name,
                    "team": player_teams.get(slot),
                }
                for slot, player in battle.players.items()
            },
            seed=[secrets.randbelow(0x10000) for _ in range(4)],
        )
        try:
            await battle.bridge.start()
        except Exception as exc:
            await self._edit_message(
                failure_chat_id,
                failure_message_id,
                f"Battle startup failed.\n{compact_text(str(exc), 600)}",
                reply_markup=None,
            )
            raise

        self.battles_by_id[battle.battle_id] = battle
        battle.runner_task = asyncio.create_task(self.run_battle_loop(battle))

    async def run_battle_loop(self, battle: BattleSession) -> None:
        assert battle.bridge is not None
        try:
            while True:
                event = await battle.bridge.next_event()
                batch = await self.collect_battle_event_batch(battle, event)
                should_render = False
                mega_notifications: list[tuple[str, str, str]] = []
                zmove_notifications: list[tuple[str, str, str]] = []
                async with battle.lock:
                    for event in batch:
                        event_type = event["type"]
                        if event_type == "public":
                            battle.public_view.apply_lines(event["lines"])
                            self.record_public_revealed_moves(battle, event["lines"])
                            self.record_public_kos(battle, event["lines"])
                            mega_notifications.extend(self.extract_mega_notifications(event["lines"]))
                            zmove_notifications.extend(self.extract_zmove_notifications(event["lines"]))
                        elif event_type == "request":
                            player = battle.players[event["slot"]]
                            player.current_request = event["request"]
                            player.pending_target = None
                            player.doubles_draft.clear()
                            battle.public_view.apply_request(player.slot, player.current_request)
                            self.sync_player_move_catalog(battle, player, player.current_request)
                            player.request_token += 1
                            if not player.current_request.get("wait"):
                                player.locked_choice = None
                                player.primed_action = None
                                if not player.current_request.get("update"):
                                    player.last_error = None
                            should_render = not self.should_defer_request_render(battle) or should_render
                        elif event_type == "error":
                            player = battle.players[event["slot"]]
                            player.last_error = clean_error(event["message"])
                            player.locked_choice = None
                            player.primed_action = None
                            player.pending_target = None
                            player.doubles_draft.clear()
                            should_render = True
                        elif event_type == "bridge_error":
                            raise ShowdownBridgeError(event["message"])
                        elif event_type == "ended":
                            battle.finished = True
                            battle.public_view.winner = event.get("winner")
                            battle.public_view.tie = bool(event.get("tie"))
                            should_render = True
                ended_in_batch = any(item["type"] == "ended" for item in batch)
                if ended_in_batch:
                    self.apply_battle_rewards(battle)
                if should_render:
                    await self.render_public_message(battle)
                if mega_notifications:
                    await self.send_mega_notifications(battle, mega_notifications)
                if zmove_notifications:
                    await self.send_zmove_notifications(battle, zmove_notifications)
                if ended_in_batch:
                    break
        except EOFError:
            if not battle.finished:
                battle.finished = True
                battle.metadata["crash_error"] = "The local Showdown worker closed unexpectedly."
                await self._edit_message(
                    battle.chat_id,
                    battle.public_message_id,
                    "The local Showdown worker closed unexpectedly.",
                    reply_markup=None,
                )
        except Exception as exc:
            battle.finished = True
            battle.metadata["crash_error"] = str(exc)
            details = compact_text(str(exc), 600)
            note = ""
            if "Stack overflow" in str(exc):
                note = "\n\nLikely simulator recursion, commonly from an item/event loop. The battle was cleaned up; rebuild or patch the local Showdown data if this repeats with the same item."
            await self._edit_message(
                battle.chat_id,
                battle.public_message_id,
                f"The simulator bridge crashed.\n{details}{note}",
                reply_markup=None,
            )
        finally:
            if battle.bridge is not None:
                await battle.bridge.close()
            self.battles_by_id.pop(battle.battle_id, None)
            self._release_active_battle(battle)

    async def handle_action_callback(self, call: types.CallbackQuery, data: str) -> None:
        parts = data.split(":")
        if len(parts) != 6:
            await self._answer(call.id, "Invalid battle action.", show_alert=True)
            return
        battle = self.battles_by_id.get(parts[2])
        if not battle:
            await self._answer(call.id, "That battle no longer exists.", show_alert=True)
            return

        response_text = ""
        alert = False
        should_render = False
        async with battle.lock:
            if battle.finished:
                await self._answer(call.id, "That battle already ended.", show_alert=True)
                return
            player = battle.player_for_user(call.from_user.id)
            if not player:
                await self._answer(call.id, "That button belongs to one of the battlers.", show_alert=True)
                return
            if self.short_slot(player.slot) != parts[3]:
                await self._answer(call.id, "That button belongs to the other side.", show_alert=True)
                return
            try:
                token = int(parts[4])
            except ValueError:
                await self._answer(call.id, "Invalid action token.", show_alert=True)
                return
            if token != player.request_token:
                await self._answer(call.id, "That battle panel is stale. Use the current one.", show_alert=True)
                return
            request = player.current_request
            if not request:
                await self._answer(call.id, "No current request is available yet.", show_alert=True)
                return
            action_code = parts[5]
            passive_action = self.is_passive_action_token(action_code)
            now = asyncio.get_running_loop().time()
            if now < player.next_action_at and not passive_action:
                remaining = max(0.1, player.next_action_at - now)
                await self._answer(call.id, f"Wait {remaining:.1f}s before the next action.")
                return
            if player.locked_choice and not passive_action:
                await self._answer(call.id, f"Already locked in: {player.locked_choice}", show_alert=True)
                return

            try:
                response_text, should_render, alert = await self.apply_player_action(battle, player, request, action_code)
            except (ValueError, ShowdownBridgeError) as exc:
                await self._answer(call.id, str(exc), show_alert=True)
                return
            if not passive_action:
                player.next_action_at = asyncio.get_running_loop().time() + ACTION_COOLDOWN_SECONDS

        if should_render:
            await self.render_public_message(battle)
        await self._answer(call.id, response_text, show_alert=alert)

    def legacy_lock_reason(self, user_id: int) -> str | None:
        if user_id <= 0:
            return None
        try:
            from bot.battle.battle_handlers import legacy_pvp_lock_reason
        except Exception:
            return None
        return legacy_pvp_lock_reason(user_id)

    async def collect_battle_event_batch(
        self,
        battle: BattleSession,
        first_event: dict[str, Any],
    ) -> list[dict[str, Any]]:
        bridge = battle.bridge
        if bridge is None:
            return [first_event]

        events = [first_event]
        deadline = asyncio.get_running_loop().time() + EVENT_BATCH_WINDOW_SECONDS
        while True:
            event = bridge.next_event_nowait()
            if event is not None:
                events.append(event)
                continue

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                events.append(await asyncio.wait_for(bridge.next_event(), timeout=remaining))
            except asyncio.TimeoutError:
                break
        return events

    async def apply_player_action(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
        action_code: str,
    ) -> tuple[str, bool, bool]:
        if self.is_doubles_battle(battle):
            return await self.apply_doubles_player_action(battle, player, request, action_code)
        return await self.apply_singles_player_action(battle, player, request, action_code)

    async def apply_singles_player_action(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
        action_code: str,
    ) -> tuple[str, bool, bool]:
        if battle.bridge is None:
            raise ShowdownBridgeError("No bridge is attached to this battle.")

        if action_code == "vm":
            if request.get("teamPreview") or request.get("forceSwitch"):
                raise ValueError("Move details are only available on move turns.")
            return self.view_moves_text(battle, request, player), False, True

        if action_code == "vt":
            return self.view_team_text(request), False, True

        if action_code == "vc":
            return self.team_choice_popup_text(player, request), False, True

        if action_code == "cx":
            player.pending_target = None
            return "Target selection cleared.", True, False

        if action_code == "ta":
            sent_text = await self.deliver_team_analysis(
                player,
                request,
                source_chat_id=battle.chat_id,
                source_message_id=battle.public_message_id,
                prefer_private=True,
            )
            return sent_text, False, False

        if action_code == "td":
            sent_text = await self.deliver_team_detail(
                player,
                request,
                source_chat_id=battle.chat_id,
                source_message_id=battle.public_message_id,
                prefer_private=True,
            )
            return sent_text, False, False

        if action_code in {"tt", "mg", "mx", "my", "dy", "zm", "ub"}:
            if request.get("teamPreview") or request.get("forceSwitch"):
                raise ValueError("Battle mechanics can only be toggled on a move turn.")
            active = request["active"][0]
            mechanics = {
                "tt": ("terastallize", "canTerastallize", "Tera"),
                "mg": ("mega", "canMegaEvo", "Mega"),
                "mx": ("megax", "canMegaEvoX", "Mega X"),
                "my": ("megay", "canMegaEvoY", "Mega Y"),
                "dy": ("dynamax", "canDynamax", "Dynamax"),
                "zm": ("zmove", "canZMove", "Z-Move"),
                "ub": ("ultra", "canUltraBurst", "Ultra Burst"),
            }
            action_name, active_key, label = mechanics[action_code]
            if not active.get(active_key):
                raise ValueError(f"{label} is not available right now.")
            if (
                action_name in PRIMARY_GIMMICK_ACTIONS
                and player.used_primary_gimmick in PRIMARY_GIMMICK_ACTIONS
                and player.used_primary_gimmick != action_name
            ):
                used_label = PRIMARY_GIMMICK_LABELS.get(player.used_primary_gimmick, player.used_primary_gimmick.title())
                raise ValueError(f"You already used {used_label}. Only one of Mega, Tera, or Dynamax can be used per battle.")
            if (
                action_name in PRIMARY_GIMMICK_ACTIONS
                and player.primed_action in PRIMARY_GIMMICK_ACTIONS
                and player.primed_action != action_name
            ):
                active_label = PRIMARY_GIMMICK_LABELS.get(player.primed_action, player.primed_action.title())
                raise ValueError(f"{active_label} is already active. Deactivate it first.")
            if player.primed_action == action_name:
                player.primed_action = None
                return f"{label} deactivated.", True, False
            player.primed_action = action_name
            return f"{label} activated. Pick a move.", True, False

        if action_code == "f":
            player.locked_choice = "Forfeit"
            player.primed_action = None
            await battle.bridge.forfeit(player.slot)
            return "Forfeit submitted.", True, False

        if request.get("wait"):
            raise ValueError("The simulator is not waiting for a choice from you right now.")

        if action_code.startswith("tg"):
            if not player.pending_target:
                raise ValueError("No target selection is pending.")
            target_loc = decode_target_location(action_code[2:])
            choice = f"{player.pending_target['base_choice']} {target_loc}"
            player.locked_choice = self.describe_choice(request, choice, battle=battle, player=player)
            player.last_error = None
            await battle.bridge.choose(player.slot, choice)
            player.pending_target = None
            player.primed_action = None
            should_render = self.current_actor_slot(battle) is not None
            return f"Locked in: {player.locked_choice}", should_render, False

        chosen_primary_gimmick: str | None = None
        if request.get("teamPreview"):
            if not action_code.startswith("t"):
                raise ValueError("Pick a lead Pokemon from the current panel.")
            index = int(action_code[1:])
            if index < 1 or index > len(request["side"]["pokemon"]):
                raise ValueError("That lead slot is not valid.")
            choice = self.team_preview_choice(index)
            player.last_submitted_move_index = None
        elif request.get("forceSwitch"):
            if not action_code.startswith("s"):
                raise ValueError("You must pick a switch-in right now.")
            index = int(action_code[1:])
            if index not in self.valid_switch_indices(request, forced=True):
                raise ValueError("That switch slot is not valid right now.")
            choice = f"switch {index}"
            player.last_submitted_move_index = None
        else:
            if action_code.startswith("m"):
                index = int(action_code[1:])
                active = request["active"][0]
                moves = active["moves"]
                if index < 1 or index > len(moves):
                    raise ValueError("That move slot is not valid.")
                if player.primed_action in {"dynamax", "zmove"}:
                    suffix = self.special_move_suffix(request, player.primed_action, index)
                else:
                    move = moves[index - 1]
                    if move.get("disabled"):
                        raise ValueError(f"Move {index} is disabled.")
                    suffix = self.special_move_suffix(request, player.primed_action, index)
                if player.primed_action in PRIMARY_GIMMICK_ACTIONS and suffix:
                    chosen_primary_gimmick = player.primed_action
                choice = f"move {index}{suffix}"
                target_type = self.request_target_type(active["moves"][index - 1])
                if player.primed_action == "zmove":
                    zmove_list = active.get("canZMove") or []
                    if index <= len(zmove_list) and zmove_list[index - 1]:
                        target_type = self.request_target_type(zmove_list[index - 1]) or target_type
                elif player.primed_action == "dynamax":
                    max_moves = ((active.get("maxMoves") or {}).get("maxMoves") or [])
                    if index <= len(max_moves):
                        target_type = self.request_target_type(max_moves[index - 1]) or target_type
                target_options = self.multi_target_options(battle, player, target_type)
                if len(target_options) > 1:
                    player.pending_target = {
                        "base_choice": choice,
                        "target_options": [(encode_target_location(loc), label) for loc, label in target_options],
                    }
                    return "Choose a target.", True, False
                if len(target_options) == 1:
                    choice = f"{choice} {target_options[0][0]}"
                player.pending_target = None
                player.last_submitted_move_index = index
            elif action_code.startswith("s"):
                index = int(action_code[1:])
                if index not in self.valid_switch_indices(request):
                    raise ValueError("That switch slot is not valid right now.")
                choice = f"switch {index}"
                player.pending_target = None
                player.last_submitted_move_index = None
            else:
                raise ValueError("That action is not valid for the current request.")

        player.locked_choice = self.describe_choice(request, choice, battle=battle, player=player)
        player.last_error = None
        await battle.bridge.choose(player.slot, choice)
        if chosen_primary_gimmick in PRIMARY_GIMMICK_ACTIONS:
            player.used_primary_gimmick = chosen_primary_gimmick
        player.primed_action = None
        player.pending_target = None
        should_render = self.current_actor_slot(battle) is not None
        return f"Locked in: {player.locked_choice}", should_render, False

    def reset_doubles_draft(self, player: PlayerState) -> None:
        player.doubles_draft.clear()

    def doubles_request_size(self, request: dict[str, Any]) -> int:
        if request.get("teamPreview"):
            side_pokemon = (request.get("side") or {}).get("pokemon") or []
            preview_size = int(request.get("maxChosenTeamSize") or min(2, len(side_pokemon) or 1))
            return max(1, min(preview_size, len(side_pokemon) or preview_size))
        if request.get("forceSwitch"):
            return len(request.get("forceSwitch") or [])
        return len(request.get("active") or [])

    def ensure_doubles_draft(self, player: PlayerState, request: dict[str, Any]) -> None:
        draft = player.doubles_draft
        size = self.doubles_request_size(request)
        phase = "teampreview" if request.get("teamPreview") else ("switch" if request.get("forceSwitch") else "move")
        if draft.token != player.request_token or draft.phase != phase:
            draft.clear()
            draft.token = player.request_token
            draft.phase = phase
        draft.ensure_size(size)
        if request.get("teamPreview"):
            draft.pending_target = None
            for index in range(size):
                choice = draft.choices[index]
                if choice:
                    pokemon_index = int(choice)
                    pokemon = ((request.get("side") or {}).get("pokemon") or [])[pokemon_index - 1]
                    draft.descriptions[index] = f"Lead {doubles_slot_label(index)}: {details_name(pokemon['details'])}"
        elif request.get("forceSwitch"):
            for index, must_switch in enumerate(request.get("forceSwitch") or []):
                if not must_switch:
                    draft.choices[index] = "pass"
                    draft.descriptions[index] = "Pass"
        else:
            active_list = request.get("active") or []
            side_list = (request.get("side") or {}).get("pokemon") or []
            for index, active in enumerate(active_list):
                side_mon = side_list[index] if index < len(side_list) else {}
                if str(side_mon.get("condition", "")).endswith(" fnt") or side_mon.get("commanding"):
                    draft.choices[index] = "pass"
                    draft.descriptions[index] = "Pass"
                if draft.primed_actions[index] and active.get("maxMoves") is None and draft.primed_actions[index] == "dynamax":
                    draft.primed_actions[index] = None
            if draft.pending_target and int(draft.pending_target.get("focus", -1)) >= size:
                draft.pending_target = None
        next_index = self.next_doubles_unset_index(player, request)
        if next_index is not None:
            draft.focus = next_index

    def next_doubles_unset_index(self, player: PlayerState, request: dict[str, Any]) -> int | None:
        draft = player.doubles_draft
        size = self.doubles_request_size(request)
        for index in range(size):
            if request.get("teamPreview"):
                if not draft.choices[index]:
                    return index
                continue
            if request.get("forceSwitch"):
                if (request.get("forceSwitch") or [])[index] and not draft.choices[index]:
                    return index
                continue
            side_mon = ((request.get("side") or {}).get("pokemon") or [{}])[index] if index < len((request.get("side") or {}).get("pokemon") or []) else {}
            if str(side_mon.get("condition", "")).endswith(" fnt") or side_mon.get("commanding"):
                continue
            if not draft.choices[index]:
                return index
        return None

    def chosen_primary_gimmick_in_draft(self, player: PlayerState) -> str | None:
        for action in player.doubles_draft.primed_actions:
            if action in PRIMARY_GIMMICK_ACTIONS:
                return action
        for choice in player.doubles_draft.choices:
            text = str(choice or "")
            for action in PRIMARY_GIMMICK_ACTIONS:
                if f" {action}" in text:
                    return action
        return None

    def doubles_team_preview_choice(self, player: PlayerState, request: dict[str, Any]) -> str:
        self.ensure_doubles_draft(player, request)
        picks = [str(choice) for choice in player.doubles_draft.choices if choice]
        if len(picks) < self.doubles_request_size(request):
            raise ValueError("Choose all lead slots before locking in.")
        return f"team {''.join(picks)}"

    def multi_half_slots(self, slot: str) -> list[str]:
        digits = int("".join(char for char in str(slot or "") if char.isdigit()) or 1)
        return ["p1", "p3"] if digits % 2 == 1 else ["p2", "p4"]

    def multi_foe_slots(self, slot: str) -> list[str]:
        digits = int("".join(char for char in str(slot or "") if char.isdigit()) or 1)
        return ["p2", "p4"] if digits % 2 == 1 else ["p1", "p3"]

    def multi_self_target_loc(self, slot: str) -> int:
        same_half = self.multi_half_slots(slot)
        return -(same_half.index(slot) + 1) if slot in same_half else -1

    def active_state_for_slot(self, battle: BattleSession, slot: str) -> dict[str, Any]:
        return self.primary_active_state(battle, slot) or {}

    def multi_target_slot(self, slot: str, target_loc: int) -> str | None:
        if target_loc == 0:
            return None
        slots = self.multi_foe_slots(slot) if target_loc > 0 else self.multi_half_slots(slot)
        index = abs(int(target_loc)) - 1
        if index < 0 or index >= len(slots):
            return None
        return slots[index]

    def multi_target_loc_for_slot(self, slot: str, target_slot: str) -> int | None:
        same_half = self.multi_half_slots(slot)
        if target_slot in same_half:
            return -(same_half.index(target_slot) + 1)
        foe_half = self.multi_foe_slots(slot)
        if target_slot in foe_half:
            return foe_half.index(target_slot) + 1
        return None

    def multi_target_options(
        self,
        battle: BattleSession,
        player: PlayerState,
        target_type: str,
    ) -> list[tuple[int, str]]:
        if not self.supports_manual_target_selection(battle):
            return []

        options: list[tuple[int, str]] = []
        player_slot = player.slot
        same_half = self.multi_half_slots(player_slot)
        foe_half = self.multi_foe_slots(player_slot)
        self_loc = self.multi_self_target_loc(player_slot)

        def add_option(target_loc: int, *, allow_self: bool = False, fallback_label: str = "Target") -> None:
            target_slot = self.multi_target_slot(player_slot, target_loc)
            if not target_slot:
                return
            if not allow_self and target_slot == player_slot:
                return
            active = self.active_state_for_slot(battle, target_slot)
            if not active or active.get("fainted"):
                return
            if target_slot == player_slot:
                label = "Self"
            else:
                label = str(active.get("name") or "").strip() or fallback_label
            options.append((target_loc, label))

        if self.is_freeforall_battle(battle):
            opponent_slots = [
                target_slot
                for target_slot in sorted(set(same_half + foe_half), key=self.slot_sort_key)
                if target_slot != player_slot
            ]
            if target_type in {"normal", "adjacentFoe", "any", "adjacentAlly"}:
                for target_slot in opponent_slots:
                    target_loc = self.multi_target_loc_for_slot(player_slot, target_slot)
                    if target_loc is not None:
                        add_option(target_loc, fallback_label=f"Target {target_slot.upper()}")
            elif target_type == "adjacentAllyOrSelf":
                add_option(self_loc, allow_self=True, fallback_label="Self")
        elif target_type in {"normal", "adjacentFoe"}:
            for index, target_slot in enumerate(foe_half, start=1):
                add_option(index, fallback_label=f"Foe {target_slot.upper()}")
        elif target_type == "any":
            for index, target_slot in enumerate(foe_half, start=1):
                add_option(index, fallback_label=f"Foe {target_slot.upper()}")
            for index, target_slot in enumerate(same_half, start=1):
                add_option(-index, fallback_label=f"Ally {target_slot.upper()}")
        elif target_type == "adjacentAlly":
            for index, target_slot in enumerate(same_half, start=1):
                if target_slot != player_slot:
                    add_option(-index, fallback_label=f"Ally {target_slot.upper()}")
        elif target_type == "adjacentAllyOrSelf":
            for index, target_slot in enumerate(same_half, start=1):
                add_option(-index, allow_self=target_slot == player_slot, fallback_label=f"Ally {target_slot.upper()}")

        deduped: list[tuple[int, str]] = []
        seen: set[int] = set()
        for target_loc, label in options:
            if target_loc in seen:
                continue
            seen.add(target_loc)
            deduped.append((target_loc, label))
        return deduped

    def target_slot_key(self, side: str, target_loc: int) -> str | None:
        if not side or target_loc == 0:
            return None
        if target_loc > 0:
            foe_side = "p2" if side == "p1" else "p1"
            letter_index = target_loc - 1
            return f"{foe_side}{chr(ord('a') + letter_index)}"
        letter_index = abs(target_loc) - 1
        return f"{side}{chr(ord('a') + letter_index)}"

    def doubles_target_options(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
        focus: int,
        target_type: str,
    ) -> list[tuple[int, str]]:
        side = player.slot
        side_states = {
            slot: battle.public_view.active.get(slot) or {}
            for slot in battle.public_view.active.keys()
        }
        options: list[tuple[int, str]] = []
        ally_count = len(request.get("active") or [])

        def label_for(loc: int) -> str:
            target_slot = self.target_slot_key(side, loc)
            active = side_states.get(target_slot or "") or {}
            name = str(active.get("name") or "")
            if not name:
                if loc > 0:
                    name = f"Foe {doubles_slot_label(loc - 1)}"
                elif abs(loc) - 1 == focus:
                    name = "Self"
                else:
                    name = f"Ally {doubles_slot_label(abs(loc) - 1)}"
            return name

        if target_type in {"normal", "adjacentFoe", "any"}:
            for loc in (1, 2):
                target_slot = self.target_slot_key(side, loc)
                active = side_states.get(target_slot or "") or {}
                if active and not active.get("fainted"):
                    options.append((loc, label_for(loc)))
            if target_type == "any":
                partner_index = 1 - focus if ally_count > 1 else None
                if partner_index is not None:
                    loc = -(partner_index + 1)
                    target_slot = self.target_slot_key(side, loc)
                    active = side_states.get(target_slot or "") or {}
                    if active and not active.get("fainted"):
                        options.append((loc, label_for(loc)))
        elif target_type == "adjacentAllyOrSelf":
            self_loc = -(focus + 1)
            options.append((self_loc, "Self"))
            partner_index = 1 - focus if ally_count > 1 else None
            if partner_index is not None:
                loc = -(partner_index + 1)
                target_slot = self.target_slot_key(side, loc)
                active = side_states.get(target_slot or "") or {}
                if active and not active.get("fainted"):
                    options.append((loc, label_for(loc)))
        return options

    def doubles_auto_target(self, request: dict[str, Any], focus: int, target_type: str) -> int | None:
        if target_type == "adjacentAlly":
            ally_index = 1 - focus
            if ally_index >= 0 and ally_index < len(request.get("active") or []):
                return -(ally_index + 1)
        return None

    def request_target_type(self, move_entry: dict[str, Any]) -> str:
        target = move_entry.get("target")
        if target is None:
            return ""
        return str(target).strip()

    def doubles_remaining_force_switch_slots(
        self,
        request: dict[str, Any],
        player: PlayerState,
        focus: int,
    ) -> int:
        pending = 0
        for index, must_switch in enumerate(request.get("forceSwitch") or []):
            if not must_switch:
                continue
            if index == focus:
                pending += 1
                continue
            choice = str(player.doubles_draft.choices[index] or "")
            if choice.startswith("switch ") or choice == "pass":
                continue
            pending += 1
        return pending

    def doubles_can_force_pass(
        self,
        request: dict[str, Any],
        player: PlayerState,
        focus: int,
    ) -> bool:
        if not request.get("forceSwitch"):
            return False
        remaining_slots = self.doubles_remaining_force_switch_slots(request, player, focus)
        remaining_switches = len(self.doubles_valid_switch_indices(request, player, focus, forced=True))
        return remaining_slots > remaining_switches

    def doubles_describe_choice(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
        focus: int,
        choice: str,
    ) -> str:
        prefix = f"{doubles_slot_label(focus)}: "
        if choice == "pass":
            return prefix + "Pass"
        if choice.startswith("switch "):
            index = int(choice.split()[1])
            pokemon = request["side"]["pokemon"][index - 1]
            return prefix + f"Switch to {details_name(pokemon['details'])}"
        if choice.startswith("move "):
            parts = choice.split()
            index = int(parts[1])
            move_name = request["active"][focus]["moves"][index - 1]["move"]
            target_text = ""
            if len(parts) >= 3 and re.fullmatch(r"-?\d+", parts[2]):
                target_slot = self.target_slot_key(player.slot, int(parts[2]))
                target_state = battle.public_view.active.get(target_slot or "") or {}
                target_name = str(target_state.get("name") or "").strip()
                if target_name:
                    target_text = f" -> {target_name}"
            gimmick = ""
            for part in parts[2:]:
                if re.fullmatch(r"-?\d+", part):
                    continue
                gimmick = {
                    "terastallize": "Tera + ",
                    "mega": "Mega + ",
                    "megax": "Mega X + ",
                    "megay": "Mega Y + ",
                    "dynamax": "Dynamax + ",
                    "zmove": "Z-Move + ",
                    "ultra": "Ultra Burst + ",
                }.get(part, part.title() + " + ")
            return prefix + f"{gimmick}{move_name}{target_text}"
        return prefix + choice

    def doubles_choice_string(self, player: PlayerState, request: dict[str, Any]) -> str:
        draft = player.doubles_draft
        size = self.doubles_request_size(request)
        choices = []
        for index in range(size):
            choices.append(str(draft.choices[index] or "pass"))
        return ", ".join(choices)

    async def submit_doubles_choice(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> tuple[str, bool, bool]:
        if battle.bridge is None:
            raise ShowdownBridgeError("No bridge is attached to this battle.")
        choice = self.doubles_choice_string(player, request)
        player.locked_choice = " / ".join(str(item or "Pass") for item in player.doubles_draft.descriptions if item)
        player.last_error = None
        await battle.bridge.choose(player.slot, choice)
        chosen_primary = self.chosen_primary_gimmick_in_draft(player)
        if chosen_primary in PRIMARY_GIMMICK_ACTIONS:
            player.used_primary_gimmick = chosen_primary
        player.doubles_draft.clear()
        should_render = self.current_actor_slot(battle) is not None
        return f"Locked in: {player.locked_choice}", should_render, False

    async def apply_doubles_player_action(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
        action_code: str,
    ) -> tuple[str, bool, bool]:
        if battle.bridge is None:
            raise ShowdownBridgeError("No bridge is attached to this battle.")
        self.ensure_doubles_draft(player, request)
        draft = player.doubles_draft

        if action_code == "vm":
            return self.view_moves_text(battle, request, player), False, True
        if action_code == "vt":
            return self.view_team_text(request), False, True
        if action_code == "vc":
            return self.team_choice_popup_text(player, request), False, True
        if action_code == "ta":
            sent_text = await self.deliver_team_analysis(
                player,
                request,
                source_chat_id=battle.chat_id,
                source_message_id=battle.public_message_id,
                prefer_private=True,
            )
            return sent_text, False, False
        if action_code == "td":
            sent_text = await self.deliver_team_detail(
                player,
                request,
                source_chat_id=battle.chat_id,
                source_message_id=battle.public_message_id,
                prefer_private=True,
            )
            return sent_text, False, False
        if action_code == "cx":
            draft.pending_target = None
            draft.choices[draft.focus] = None
            draft.descriptions[draft.focus] = None
            if not request.get("teamPreview"):
                draft.primed_actions[draft.focus] = None
            return "Selection cleared.", True, False
        if action_code == "f":
            player.locked_choice = "Forfeit"
            draft.clear()
            await battle.bridge.forfeit(player.slot)
            return "Forfeit submitted.", True, False

        if request.get("wait"):
            raise ValueError("The simulator is not waiting for a choice from you right now.")

        if action_code.startswith("a"):
            index = int(action_code[1:])
            if index < 0 or index >= self.doubles_request_size(request):
                raise ValueError("That active slot is not valid.")
            draft.focus = index
            draft.pending_target = None
            return f"Editing slot {doubles_slot_label(index)}.", True, False

        if request.get("teamPreview"):
            if not action_code.startswith("t"):
                raise ValueError("Pick your lead Pokemon from the current panel.")
            index = int(action_code[1:])
            pokemon_list = (request.get("side") or {}).get("pokemon") or []
            if index < 1 or index > len(pokemon_list):
                raise ValueError("That lead slot is not valid.")
            if any(str(choice or "") == str(index) for choice_index, choice in enumerate(draft.choices) if choice_index != draft.focus):
                raise ValueError("That Pokemon is already assigned to another lead slot.")
            selected_focus = draft.focus
            pokemon = pokemon_list[index - 1]
            draft.choices[selected_focus] = str(index)
            draft.descriptions[selected_focus] = f"Lead {doubles_slot_label(selected_focus)}: {details_name(pokemon['details'])}"
            draft.pending_target = None
            next_index = self.next_doubles_unset_index(player, request)
            if next_index is None:
                choice = self.doubles_team_preview_choice(player, request)
                player.locked_choice = " / ".join(str(item or "pending") for item in draft.descriptions if item)
                player.last_error = None
                await battle.bridge.choose(player.slot, choice)
                draft.clear()
                should_render = self.current_actor_slot(battle) is not None
                return f"Locked in: {player.locked_choice}", should_render, False
            draft.focus = next_index
            return f"{doubles_slot_label(selected_focus)} lead set.", True, False

        focus = draft.focus
        if request.get("forceSwitch"):
            if action_code == "p":
                if not self.doubles_can_force_pass(request, player, focus):
                    raise ValueError("A switch-in is still required for this slot.")
                choice = "pass"
                draft.choices[focus] = choice
                draft.descriptions[focus] = self.doubles_describe_choice(battle, player, request, focus, choice)
                draft.pending_target = None
                next_index = self.next_doubles_unset_index(player, request)
                if next_index is None:
                    return await self.submit_doubles_choice(battle, player, request)
                draft.focus = next_index
                return f"{doubles_slot_label(focus)} set.", True, False
            if action_code.startswith("s"):
                index = int(action_code[1:])
                if index not in self.doubles_valid_switch_indices(request, player, focus, forced=True):
                    raise ValueError("That switch slot is not valid right now.")
                choice = f"switch {index}"
                draft.choices[focus] = choice
                draft.descriptions[focus] = self.doubles_describe_choice(battle, player, request, focus, choice)
                draft.pending_target = None
                next_index = self.next_doubles_unset_index(player, request)
                if next_index is None:
                    return await self.submit_doubles_choice(battle, player, request)
                draft.focus = next_index
                return f"{doubles_slot_label(focus)} set.", True, False
            raise ValueError("You must pick a switch-in right now.")

        if action_code in {"tt", "mg", "mx", "my", "dy", "zm", "ub"}:
            active = (request.get("active") or [])[focus]
            mechanics = {
                "tt": ("terastallize", "canTerastallize", "Tera"),
                "mg": ("mega", "canMegaEvo", "Mega"),
                "mx": ("megax", "canMegaEvoX", "Mega X"),
                "my": ("megay", "canMegaEvoY", "Mega Y"),
                "dy": ("dynamax", "canDynamax", "Dynamax"),
                "zm": ("zmove", "canZMove", "Z-Move"),
                "ub": ("ultra", "canUltraBurst", "Ultra Burst"),
            }
            action_name, active_key, label = mechanics[action_code]
            if not active.get(active_key):
                raise ValueError(f"{label} is not available right now.")
            used_primary = player.used_primary_gimmick if player.used_primary_gimmick in PRIMARY_GIMMICK_ACTIONS else None
            drafted_primary = self.chosen_primary_gimmick_in_draft(player)
            if (
                action_name in PRIMARY_GIMMICK_ACTIONS
                and used_primary in PRIMARY_GIMMICK_ACTIONS
                and used_primary != action_name
            ):
                used_label = PRIMARY_GIMMICK_LABELS.get(used_primary, used_primary.title())
                raise ValueError(f"You already used {used_label}. Only one of Mega, Tera, or Dynamax can be used per battle.")
            if (
                action_name in PRIMARY_GIMMICK_ACTIONS
                and drafted_primary in PRIMARY_GIMMICK_ACTIONS
                and drafted_primary != action_name
            ):
                active_label = PRIMARY_GIMMICK_LABELS.get(drafted_primary, drafted_primary.title())
                raise ValueError(f"{active_label} is already active on this turn.")
            if draft.primed_actions[focus] == action_name:
                draft.primed_actions[focus] = None
                return f"{label} deactivated for slot {doubles_slot_label(focus)}.", True, False
            draft.primed_actions[focus] = action_name
            draft.pending_target = None
            return f"{label} activated for slot {doubles_slot_label(focus)}.", True, False

        if action_code.startswith("s"):
            index = int(action_code[1:])
            if index not in self.doubles_valid_switch_indices(request, player, focus, forced=False):
                raise ValueError("That switch slot is not valid right now.")
            choice = f"switch {index}"
            draft.choices[focus] = choice
            draft.descriptions[focus] = self.doubles_describe_choice(battle, player, request, focus, choice)
            draft.primed_actions[focus] = None
            draft.pending_target = None
            next_index = self.next_doubles_unset_index(player, request)
            if next_index is None:
                return await self.submit_doubles_choice(battle, player, request)
            draft.focus = next_index
            return f"{doubles_slot_label(focus)} set.", True, False

        if action_code.startswith("m"):
            index = int(action_code[1:])
            active = (request.get("active") or [])[focus]
            moves = active.get("moves") or []
            if index < 1 or index > len(moves):
                raise ValueError("That move slot is not valid.")
            move = moves[index - 1]
            if not move.get("disabled") or draft.primed_actions[focus] in {"dynamax", "zmove"}:
                suffix = self.special_move_suffix_for_active(active, draft.primed_actions[focus], index)
            else:
                raise ValueError(f"Move {index} is disabled.")
            target_type = self.request_target_type(move)
            if draft.primed_actions[focus] == "zmove":
                zmove_list = active.get("canZMove") or []
                if index <= len(zmove_list) and zmove_list[index - 1]:
                    target_type = self.request_target_type(zmove_list[index - 1]) or target_type
            elif draft.primed_actions[focus] == "dynamax":
                max_moves = ((active.get("maxMoves") or {}).get("maxMoves") or [])
                if index <= len(max_moves):
                    target_type = self.request_target_type(max_moves[index - 1]) or target_type
            base_choice = f"move {index}{suffix}"
            auto_target = self.doubles_auto_target(request, focus, target_type)
            target_options = self.doubles_target_options(battle, player, request, focus, target_type)
            if auto_target is not None:
                choice = f"{base_choice} {auto_target}"
            elif target_options:
                if len(target_options) == 1:
                    choice = f"{base_choice} {target_options[0][0]}"
                else:
                    draft.pending_target = {
                        "focus": focus,
                        "move_index": index,
                        "base_choice": base_choice,
                        "target_options": [(encode_target_location(loc), label) for loc, label in target_options],
                    }
                    return f"Choose a target for slot {doubles_slot_label(focus)}.", True, False
            else:
                choice = base_choice
            draft.choices[focus] = choice
            draft.descriptions[focus] = self.doubles_describe_choice(battle, player, request, focus, choice)
            draft.pending_target = None
            next_index = self.next_doubles_unset_index(player, request)
            if next_index is None:
                return await self.submit_doubles_choice(battle, player, request)
            draft.focus = next_index
            return f"{doubles_slot_label(focus)} set.", True, False

        if action_code.startswith("tg"):
            if not draft.pending_target:
                raise ValueError("No target selection is pending.")
            target_loc = decode_target_location(action_code[2:])
            focus = int(draft.pending_target.get("focus", draft.focus))
            choice = f"{draft.pending_target['base_choice']} {target_loc}"
            draft.choices[focus] = choice
            draft.descriptions[focus] = self.doubles_describe_choice(battle, player, request, focus, choice)
            draft.pending_target = None
            next_index = self.next_doubles_unset_index(player, request)
            if next_index is None:
                return await self.submit_doubles_choice(battle, player, request)
            draft.focus = next_index
            return f"{doubles_slot_label(focus)} set.", True, False

        raise ValueError("That action is not valid for the current request.")

    def doubles_valid_switch_indices(
        self,
        request: dict[str, Any],
        player: PlayerState,
        focus: int,
        *,
        forced: bool,
    ) -> list[int]:
        if not forced:
            active = (request.get("active") or [])[focus]
            if active.get("trapped"):
                return []
        chosen_switches = {
            int(str(choice).split()[1])
            for index, choice in enumerate(player.doubles_draft.choices)
            if index != focus and str(choice or "").startswith("switch ")
        }
        return [
            index
            for index, pokemon in enumerate(request["side"]["pokemon"], start=1)
            if not pokemon.get("active")
            and not fainted(str(pokemon.get("condition", "")))
            and index not in chosen_switches
        ]

    def record_public_kos(self, battle: BattleSession, lines: list[str]) -> None:
        if len(battle.players) != 2:
            return
        for line in lines:
            command, args = protocol_parts(line)
            if command != "faint" or not args:
                continue
            fainted_slot = ident_side(args[0])
            if fainted_slot == "p1":
                battle.players["p2"].ko_count += 1
            elif fainted_slot == "p2":
                battle.players["p1"].ko_count += 1

    def apply_battle_rewards(self, battle: BattleSession) -> None:
        if battle.metadata.get("rewards_applied"):
            return
        battle.metadata["rewards_applied"] = True
        if len(battle.players) != 2:
            return
        if battle.public_view.tie:
            return

        winner_name = str(battle.public_view.winner or "").strip()
        if not winner_name:
            return
        winner = next(
            (player for player in battle.players.values() if player.name.strip().lower() == winner_name.lower()),
            None,
        )
        if winner is None:
            return
        loser = battle.players["p1"] if winner.slot == "p2" else battle.players["p2"]
        winner_reward = max(0, int(winner.ko_count) * 10)
        loser_reward = max(0, int(loser.ko_count) * 10)
        db.add_clash_coins(winner.user_id, winner_reward)
        db.add_clash_coins(loser.user_id, loser_reward)
        battle.winner_reward = winner_reward
        battle.loser_reward = loser_reward
        self.apply_showdown_ranking(battle, winner, loser)

    def apply_showdown_ranking(self, battle: BattleSession, winner: PlayerState, loser: PlayerState) -> None:
        if battle.metadata.get("ranking_applied"):
            return
        battle.metadata["ranking_applied"] = True

        winner_stats = db.get_user_stats(winner.user_id)
        loser_stats = db.get_user_stats(loser.user_id)
        if not winner_stats or not loser_stats:
            return

        winner_old_elo = int(winner_stats[0] or 1000)
        loser_old_elo = int(loser_stats[0] or 1000)
        winner_delta = calculate_elo_change(winner_old_elo, loser_old_elo, 1.0)
        loser_delta = calculate_elo_change(loser_old_elo, winner_old_elo, 0.0)
        winner_new_elo = winner_old_elo + winner_delta
        loser_new_elo = loser_old_elo + loser_delta

        db.update_user_stats(winner.user_id, winner_new_elo, 1, 0, 0)
        db.update_user_stats(loser.user_id, loser_new_elo, 0, 1, 0)
        battle.metadata["ranking_result"] = {
            "winner_name": winner.name,
            "loser_name": loser.name,
            "winner_old_elo": winner_old_elo,
            "winner_new_elo": winner_new_elo,
            "winner_delta": winner_delta,
            "loser_old_elo": loser_old_elo,
            "loser_new_elo": loser_new_elo,
            "loser_delta": loser_delta,
        }

    def sync_player_move_catalog(self, battle: BattleSession, player: PlayerState, request: dict[str, Any]) -> None:
        if self.is_doubles_battle(battle):
            player.active_pokemon_key = None
            player.move_catalog = []
            player.revealed_moves.clear()
            player.last_submitted_move_index = None
            return

        active_state = self.primary_active_state(battle, player.slot)
        active_key = str(active_state.get("key") or "") or None
        if active_key != player.active_pokemon_key:
            player.active_pokemon_key = active_key
            player.revealed_moves.clear()
            player.last_submitted_move_index = None

        active_list = request.get("active") or []
        if not active_list:
            player.move_catalog = []
            return

        current_active = active_list[0] or {}
        moves = current_active.get("moves") or []
        catalog: list[dict[str, Any]] = []
        for index, move in enumerate(moves, start=1):
            catalog.append(
                {
                    "index": index,
                    "name": str(move.get("move") or f"Move {index}"),
                    "type": str(move.get("displayType") or "?"),
                    "accuracy": str(move.get("displayAccuracy") or "?"),
                    "power": self.move_power_text(str(move.get("id") or ""), str(move.get("move") or "")),
                    "pp": self.move_pp_text(move.get("pp"), move.get("maxpp")),
                }
            )
        player.move_catalog = catalog
        for index, revealed in list(player.revealed_moves.items()):
            match = next((entry for entry in catalog if int(entry["index"]) == int(index)), None)
            if not match:
                continue
            revealed["type"] = match["type"]
            revealed["accuracy"] = match["accuracy"]
            revealed["power"] = match["power"]
            revealed["pp"] = match["pp"]

    def record_public_revealed_moves(self, battle: BattleSession, lines: list[str]) -> None:
        if self.is_doubles_battle(battle):
            return
        for line in lines:
            command, args = protocol_parts(line)
            if command in {"switch", "drag", "replace"} and args:
                side = ident_side(args[0])
                if side in battle.players:
                    player = battle.players[side]
                    player.active_pokemon_key = None
                    player.move_catalog = []
                    player.revealed_moves.clear()
                    player.last_submitted_move_index = None
                continue
            if command != "move" or len(args) < 2:
                continue
            side = ident_side(args[0])
            if side not in battle.players:
                continue
            player = battle.players[side]
            move_name = str(args[1] or "").strip()
            if not move_name:
                continue
            move_index = player.last_submitted_move_index
            match = None
            if move_index is not None:
                match = next((entry for entry in player.move_catalog if int(entry["index"]) == int(move_index)), None)
            if match is None:
                match = next((entry for entry in player.move_catalog if normalized(entry["name"]) == normalized(move_name)), None)
                move_index = int(match["index"]) if match else None
            if move_index is None:
                continue
            player.revealed_moves[int(move_index)] = {
                "index": int(move_index),
                "name": move_name,
                "type": str(match["type"]) if match else self.move_type_text(move_name),
                "accuracy": str(match["accuracy"]) if match else self.move_accuracy_text(move_name),
                "power": str(match["power"]) if match else self.move_power_text("", move_name),
                "pp": str(match["pp"]) if match else "?",
            }
            player.last_submitted_move_index = None

    def move_lookup(self, move_id: str, move_name: str) -> dict[str, Any]:
        normalized_id = normalized(move_id)
        normalized_name = normalized(move_name)
        if normalized_id and normalized_id in MOVE_BY_ID:
            return MOVE_BY_ID[normalized_id]
        for candidate_id, move_data in MOVE_BY_ID.items():
            if normalized(candidate_id) == normalized_id or normalized(move_data.get("name", "")) == normalized_name:
                return move_data
        return {}

    def move_power_text(self, move_id: str, move_name: str) -> str:
        move_data = self.move_lookup(move_id, move_name)
        power = move_data.get("basePower", move_data.get("power", "—"))
        if power in {None, "", 0, "0"}:
            return "—"
        return str(power)

    def move_accuracy_text(self, move_name: str) -> str:
        move_data = self.move_lookup("", move_name)
        accuracy = move_data.get("accuracy", "—")
        if accuracy is True:
            return "—"
        return str(accuracy)

    def move_type_text(self, move_name: str) -> str:
        move_data = self.move_lookup("", move_name)
        return str(move_data.get("type", "?"))

    def move_pp_text(self, current_pp: Any, max_pp: Any) -> str:
        if current_pp is None or max_pp is None:
            return "?"
        return f"{current_pp}/{max_pp}"

    def should_defer_request_render(self, battle: BattleSession) -> bool:
        if self.current_actor_slot(battle):
            return False
        return any(player.locked_choice for player in battle.players.values())

    def slot_sort_key(self, slot: str) -> tuple[int, str]:
        digits = "".join(char for char in str(slot or "") if char.isdigit())
        return (int(digits or 99), str(slot or ""))

    def ordered_battle_slots(self, battle: BattleSession) -> list[str]:
        display_order = battle.metadata.get("display_slot_order")
        if isinstance(display_order, list):
            ordered = [str(slot) for slot in display_order if str(slot) in battle.players]
            if len(ordered) == len(battle.players):
                return ordered
        return sorted(battle.players, key=self.slot_sort_key)

    def current_actor_slot(self, battle: BattleSession) -> str | None:
        actionable = self.actionable_slots(battle)
        return actionable[0] if actionable else None

    def actionable_slots(self, battle: BattleSession) -> list[str]:
        slots = [
            slot
            for slot in self.ordered_battle_slots(battle)
            if battle.players[slot].current_request
            and not battle.players[slot].current_request.get("wait")
            and not battle.players[slot].locked_choice
        ]
        forced = [slot for slot in slots if battle.players[slot].current_request.get("forceSwitch")]
        return forced + [slot for slot in slots if slot not in forced] if forced else slots

    def short_slot(self, slot: str) -> str:
        return slot[1:] if slot.startswith("p") else slot

    def action_data(self, battle: BattleSession, player: PlayerState, action_code: str) -> str:
        return f"sdb:a:{battle.battle_id}:{self.short_slot(player.slot)}:{player.request_token}:{action_code}"

    def team_preview_choice(self, lead_index: int) -> str:
        return f"team {lead_index}"

    def special_move_suffix_for_active(self, active: dict[str, Any], primed_action: str | None, index: int) -> str:
        if not primed_action:
            return ""
        if primed_action == "terastallize":
            if not active.get("canTerastallize"):
                raise ValueError("Tera is not available right now.")
            return " terastallize"
        if primed_action == "mega":
            if not active.get("canMegaEvo"):
                raise ValueError("Mega Evolution is not available right now.")
            return " mega"
        if primed_action == "megax":
            if not active.get("canMegaEvoX"):
                raise ValueError("Mega X is not available right now.")
            return " megax"
        if primed_action == "megay":
            if not active.get("canMegaEvoY"):
                raise ValueError("Mega Y is not available right now.")
            return " megay"
        if primed_action == "dynamax":
            max_moves = ((active.get("maxMoves") or {}).get("maxMoves") or [])
            if index < 1 or index > len(max_moves):
                raise ValueError("That Max Move slot is not valid.")
            if max_moves[index - 1].get("disabled"):
                raise ValueError(f"Max Move {index} is disabled.")
            return " dynamax"
        if primed_action == "zmove":
            z_moves = active.get("canZMove") or []
            if index < 1 or index > len(z_moves):
                raise ValueError("That Z-Move slot is not valid.")
            if not z_moves[index - 1]:
                raise ValueError("That move cannot be used as a Z-Move.")
            return " zmove"
        if primed_action == "ultra":
            if not active.get("canUltraBurst"):
                raise ValueError("Ultra Burst is not available right now.")
            return " ultra"
        return ""

    def special_move_suffix(self, request: dict[str, Any], primed_action: str | None, index: int) -> str:
        return self.special_move_suffix_for_active(request["active"][0], primed_action, index)

    def describe_choice(self, request: dict[str, Any], choice: str, *, battle: BattleSession | None = None, player: PlayerState | None = None) -> str:
        if choice == "Forfeit":
            return "Forfeit"
        if choice.startswith("team "):
            index = int(choice.split()[1])
            pokemon = request["side"]["pokemon"][index - 1]
            return f"Lead: {details_name(pokemon['details'])}"
        if choice.startswith("switch "):
            index = int(choice.split()[1])
            pokemon = request["side"]["pokemon"][index - 1]
            return f"Switch to {details_name(pokemon['details'])}"
        if choice.startswith("move "):
            parts = choice.split()
            index = int(parts[1])
            move_name = request["active"][0]["moves"][index - 1]["move"]
            target_text = ""
            if battle is not None and player is not None and len(parts) >= 3 and re.fullmatch(r"-?\d+", parts[-1]):
                target_loc = int(parts[-1])
                if self.supports_manual_target_selection(battle):
                    target_slot = self.multi_target_slot(player.slot, target_loc)
                    if target_slot:
                        target_state = self.active_state_for_slot(battle, target_slot)
                        target_name = str(target_state.get("name") or "").strip()
                        if target_name:
                            target_text = f" -> {target_name}"
            gimmick = ""
            for part in parts[2:]:
                if re.fullmatch(r"-?\d+", part):
                    continue
                gimmick = {
                    "terastallize": "Tera",
                    "mega": "Mega",
                    "megax": "Mega X",
                    "megay": "Mega Y",
                    "dynamax": "Dynamax",
                    "zmove": "Z-Move",
                    "ultra": "Ultra Burst",
                }.get(part, part.title())
                break
            if gimmick:
                return f"{gimmick} + {move_name}{target_text}"
            return f"{move_name}{target_text}"
        return choice

    def extract_mega_notifications(self, lines: list[str]) -> list[tuple[str, str, str]]:
        notifications: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for line in lines:
            parts = line.split("|")
            if len(parts) < 4:
                continue
            command = parts[1]
            args = parts[2:]
            if command not in {"detailschange", "-formechange"} or len(args) < 2:
                continue
            slot = args[0].split(":", 1)[0].strip()
            base_name = ident_name(args[0])
            new_species = details_name(args[1])
            if "Mega" not in new_species:
                continue
            key = (slot, new_species)
            if key in seen:
                continue
            seen.add(key)
            notifications.append((slot, base_name, new_species))
        return notifications

    async def send_mega_notifications(self, battle: BattleSession, notifications: list[tuple[str, str, str]]) -> None:
        sent_keys = battle.metadata.setdefault("mega_notice_keys", set())
        for slot, base_name, new_species in notifications:
            notice_key = f"{slot}:{new_species}"
            if notice_key in sent_keys:
                continue
            sent_keys.add(notice_key)
            active_state = battle.public_view.active.get(slot) or {}
            shiny = bool(active_state.get("shiny"))
            shiny_suffix = " ✨" if shiny else ""
            caption = f"{base_name}{shiny_suffix} has mega evolved into {new_species}{shiny_suffix}"
            artwork_path = self.visual_renderer.artwork_path(new_species, shiny=shiny)
            try:
                if artwork_path and artwork_path.exists():
                    with open(artwork_path, "rb") as artwork:
                        await self.bot.send_photo(
                            battle.chat_id,
                            photo=artwork,
                            caption=caption,
                            reply_to_message_id=battle.public_message_id,
                        )
                else:
                    await self.bot.send_message(battle.chat_id, caption, reply_to_message_id=battle.public_message_id)
            except Exception:
                continue

    def extract_zmove_notifications(self, lines: list[str]) -> list[tuple[str, str, str]]:
        notifications: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for line in lines:
            parts = line.split("|")
            if len(parts) < 4 or parts[1] != "move":
                continue
            slot = parts[2].split(":", 1)[0].strip()
            attacker = ident_name(parts[2])
            move_name = parts[3]
            normalized_move = move_name.lower().strip()
            if normalized_move not in SIGNATURE_ZMOVES:
                continue
            key = (slot, normalized_move)
            if key in seen:
                continue
            seen.add(key)
            notifications.append((slot, attacker, move_name))
        return notifications

    async def send_zmove_notifications(self, battle: BattleSession, notifications: list[tuple[str, str, str]]) -> None:
        sent_keys = battle.metadata.setdefault("zmove_notice_keys", set())
        for slot, attacker, move_name in notifications:
            normalized_move = move_name.lower().strip()
            notice_key = f"{slot}:{normalized_move}"
            if notice_key in sent_keys:
                continue
            sent_keys.add(notice_key)
            filename = SIGNATURE_ZMOVES.get(normalized_move)
            if not filename:
                continue
            filepath = BOT_DIR / "assets" / "zmoves" / filename
            caption = f"{attacker} unleashed its full Z-Power to use {move_name}!"
            try:
                if filepath.exists():
                    with open(filepath, "rb") as image:
                        await self.bot.send_photo(
                            battle.chat_id,
                            photo=image,
                            caption=caption,
                            reply_to_message_id=battle.public_message_id,
                        )
                else:
                    await self.bot.send_message(battle.chat_id, caption, reply_to_message_id=battle.public_message_id)
            except Exception:
                continue

    async def render_public_message(self, battle: BattleSession) -> None:
        text, reply_markup = self.render_public_text_and_buttons(battle)
        if self.battle_uses_visuals(battle):
            visual_payload = self.visual_renderer.render(battle, highlight_slot=self.current_actor_slot(battle))
            if visual_payload is not None:
                await self._upsert_visual_message(
                    battle,
                    text=text,
                    reply_markup=reply_markup,
                    visual_payload=visual_payload,
                )
                return
        await self._edit_message(battle.chat_id, battle.public_message_id, text, reply_markup=reply_markup, parse_mode="HTML")

    def battle_uses_visuals(self, battle: BattleSession) -> bool:
        return (
            bool(battle.metadata.get("visuals_enabled")) and
            self.visual_renderer.available
        )

    def visual_caption_text(self, text: str) -> str:
        return compact_text(text, limit=900)

    async def _upsert_visual_message(
        self,
        battle: BattleSession,
        *,
        text: str,
        reply_markup: types.InlineKeyboardMarkup | None,
        visual_payload: tuple[Any, str],
    ) -> None:
        image, scene_fingerprint = visual_payload
        caption = self.visual_caption_text(text)
        visual_message_id = int(battle.metadata.get("visual_message_id") or 0)

        if visual_message_id <= 0:
            origin_message_id = int(battle.metadata.get("origin_message_id") or battle.public_message_id)
            challenge_message_id = int(battle.metadata.get("challenge_message_id") or origin_message_id)
            reply_source_message_id = int(battle.metadata.get("reply_source_message_id") or 0)
            reply_target = reply_source_message_id or 0
            try:
                sent = await self.bot.send_photo(
                    battle.chat_id,
                    photo=image,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_target if reply_target > 0 else None,
                )
            except Exception:
                sent = await self.bot.send_photo(
                    battle.chat_id,
                    photo=image,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            battle.metadata["visual_message_id"] = sent.message_id
            battle.public_message_id = sent.message_id
            battle.last_visual_scene_fingerprint = scene_fingerprint
            if challenge_message_id > 0 and challenge_message_id != sent.message_id:
                try:
                    await self.bot.delete_message(battle.chat_id, challenge_message_id)
                except Exception:
                    pass
            return

        if battle.last_visual_scene_fingerprint == scene_fingerprint:
            try:
                await self.bot.edit_message_caption(
                    caption=caption,
                    chat_id=battle.chat_id,
                    message_id=visual_message_id,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception:
                pass
            return

        try:
            media = types.InputMediaPhoto(media=image, caption=caption, parse_mode="HTML")
            await self.bot.edit_message_media(
                media=media,
                chat_id=battle.chat_id,
                message_id=visual_message_id,
                reply_markup=reply_markup,
            )
            battle.last_visual_scene_fingerprint = scene_fingerprint
        except Exception:
            try:
                await self.bot.edit_message_caption(
                    caption=caption,
                    chat_id=battle.chat_id,
                    message_id=visual_message_id,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception:
                pass

    def render_public_text_and_buttons(self, battle: BattleSession) -> tuple[str, types.InlineKeyboardMarkup | None]:
        recent = list(battle.public_view.display_recent())
        recent = self.trim_opening_recent_lines(battle, recent)
        recent = [html.escape(entry) for entry in recent]
        current_slot = self.current_actor_slot(battle)
        is_doubles = self.is_doubles_battle(battle)

        lines: list[str] = []
        if recent:
            recent_turn = battle.public_view.turn
            if not battle.public_view.recent and battle.public_view.last_turn_recent and recent_turn > 1:
                recent_turn -= 1
            lines.append(f"<b>{'Turn ' + str(recent_turn) + ' Recap' if recent_turn > 0 else 'Battle Recap'}</b>")
            lines.extend(f"• {entry}" for entry in recent)
            lines.append("")

        display_slots = self.display_slots_for_battle(battle, current_slot)
        for index, slot in enumerate(display_slots):
            lines.extend(self.render_side_block(battle, slot, highlight=current_slot == slot))
            if index + 1 < len(display_slots):
                lines.append("")

        button_specs: list[list[tuple[str, str]]] | None = None
        if battle.finished:
            lines.append("")
            if battle.public_view.tie:
                lines.append("Battle over: tie.")
            else:
                winner = html.escape(battle.public_view.winner or "Unknown winner")
                lines.append(f"Battle over: winner is {winner}.")
                if len(battle.players) == 2 and battle.winner_reward is not None and battle.loser_reward is not None:
                    loser = battle.players["p1"] if (battle.public_view.winner or "").strip().lower() == battle.players["p2"].name.strip().lower() else battle.players["p2"]
                    lines.append(f"{winner} earned {battle.winner_reward} CC.")
                    lines.append(f"{html.escape(loser.name)} earned {battle.loser_reward} CC.")
                ranking_result = battle.metadata.get("ranking_result") or {}
                if ranking_result:
                    winner_name = html.escape(str(ranking_result.get("winner_name") or "Winner"))
                    loser_name = html.escape(str(ranking_result.get("loser_name") or "Loser"))
                    winner_delta = int(ranking_result.get("winner_delta") or 0)
                    loser_delta = int(ranking_result.get("loser_delta") or 0)
                    lines.append(
                        f"{winner_name}: Elo {ranking_result.get('winner_old_elo')} -> {ranking_result.get('winner_new_elo')} ({winner_delta:+d})."
                    )
                    lines.append(
                        f"{loser_name}: Elo {ranking_result.get('loser_old_elo')} -> {ranking_result.get('loser_new_elo')} ({loser_delta:+d})."
                    )
        elif current_slot:
            current_player = battle.players[current_slot]
            request = current_player.current_request or {}
            lines.append("")
            if current_player.last_error:
                lines.append(
                    f"{html.escape(current_player.name)}, your last choice was rejected: "
                    f"{html.escape(current_player.last_error)}"
                )
            if request.get("teamPreview"):
                if is_doubles:
                    lines.extend(self.render_doubles_team_preview_prompt(current_player, request))
                    button_specs = self.doubles_team_preview_button_specs(battle, current_player, request)
                else:
                    lines.append(f"{mention_html(current_player.user_id, current_player.name)}: choose your lead.")
                    button_specs = self.team_preview_button_specs(battle, current_player, request)
            elif request.get("forceSwitch"):
                if is_doubles:
                    lines.extend(self.render_doubles_prompt(battle, current_player, request))
                    button_specs = self.doubles_button_specs(battle, current_player, request)
                else:
                    lines.append(f"{mention_html(current_player.user_id, current_player.name)}: choose your switch-in.")
                    button_specs = self.forced_switch_button_specs(battle, current_player, request)
            else:
                if is_doubles:
                    lines.extend(self.render_doubles_prompt(battle, current_player, request))
                    button_specs = self.doubles_button_specs(battle, current_player, request)
                else:
                    if current_player.pending_target:
                        lines.append(f"{mention_html(current_player.user_id, current_player.name)}: choose a target.")
                    else:
                        lines.append(f"{mention_html(current_player.user_id, current_player.name)}: choose your move or switch.")
                    button_specs = self.move_request_button_specs(battle, current_player, request)
            reveal_lines = [] if is_doubles else self.render_revealed_moves_section(battle, current_slot)
            if reveal_lines:
                lines.extend(reveal_lines)
        else:
            lines.append("")
            lines.append("Generating teams and waiting for the simulator...")

        text = "\n".join(lines)
        return text.replace("â€¢ ", "- "), self.build_buttons(button_specs)

    def trim_opening_recent_lines(self, battle: BattleSession, recent: list[str]) -> list[str]:
        recent_lines = list(recent)
        if (
            not battle.finished
            and battle.public_view.turn <= 1
            and recent_lines
            and all(
                (" sent out " in entry or " revealed " in entry or " dragged in " in entry)
                for entry in recent_lines
            )
        ):
            return []
        return recent_lines

    def render_side_block(self, battle: BattleSession, slot: str, *, highlight: bool) -> list[str]:
        if not self.is_doubles_battle(battle):
            return self.render_active_block(battle, slot, highlight=highlight)

        player_name = battle.players[slot].name
        if highlight:
            player_name += " (TURN)"
        lines = [html.escape(player_name)]
        active_states = self.side_active_states(battle, slot)
        if not active_states:
            lines.append("waiting for lead")
            return lines
        for index, active in enumerate(active_states):
            info_parts = [
                f"Lv {active.get('level', '?')}",
                f"Type {format_types(active.get('types'))}",
            ]
            if active.get("status"):
                info_parts.append(f"Status {active.get('status')}")
            shiny_suffix = " ✨" if active.get("shiny") else ""
            lines.append(html.escape(f"{doubles_slot_label(index)}. {active.get('name', 'Pokemon')}{shiny_suffix} | {' | '.join(info_parts)}"))
            lines.append(html.escape(f"HP: {hp_bar_ascii(active.get('percent'))} ({active.get('hp_text') or 'unknown'})"))
        return lines

    def render_doubles_prompt(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[str]:
        self.ensure_doubles_draft(player, request)
        draft = player.doubles_draft
        lines = [f"{mention_html(player.user_id, player.name)}: choose actions for both active slots."]
        if request.get("forceSwitch"):
            lines.append("Pick a switch-in for the active slot.")
        elif draft.pending_target:
            lines.append("Choose a target.")
        return lines

    def render_doubles_team_preview_prompt(
        self,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[str]:
        self.ensure_doubles_draft(player, request)
        draft = player.doubles_draft
        lines = [f"{mention_html(player.user_id, player.name)}: choose your opening pair."]
        for index in range(self.doubles_request_size(request)):
            lines.append(f"{doubles_slot_label(index)}: pending")
        lines.append("Pick two leads. The selection locks automatically when both are set.")
        return lines

    def render_active_block(self, battle: BattleSession, slot: str, *, highlight: bool) -> list[str]:
        player_name = battle.players[slot].name
        active = self.primary_active_state(battle, slot)
        if not active:
            suffix = " (TURN)" if highlight else ""
            return [f"{html.escape(player_name)}{suffix}: waiting for lead"]

        info_parts = [
            f"Level: {active.get('level', '?')}",
            f"Type: {format_types(active.get('types'))}",
        ]
        status = active.get("status")
        if status:
            info_parts.append(f"Status: {status}")
        shiny_suffix = " ✨" if active.get("shiny") else ""
        header = f"{player_name}: {active['name']}{shiny_suffix}"
        if highlight:
            header += " (TURN)"
        lines = [
            html.escape(header),
            html.escape(" | ".join(info_parts)),
            html.escape(f"HP: {hp_bar_ascii(active.get('percent'))} ({active.get('hp_text') or 'unknown'})"),
        ]
        return lines

    def display_slots_for_battle(self, battle: BattleSession, current_slot: str | None) -> list[str]:
        ordered = self.ordered_battle_slots(battle)
        if len(ordered) != 2:
            return ordered
        if current_slot == "p1":
            return ["p2", "p1"]
        if current_slot == "p2":
            return ["p1", "p2"]
        return ordered

    def render_revealed_moves_section(self, battle: BattleSession, current_slot: str | None) -> list[str]:
        if not current_slot:
            return []
        current_state = battle.players[current_slot]
        revealed_moves = sorted(current_state.revealed_moves.values(), key=lambda move: int(move.get("index") or 99))
        if not revealed_moves:
            return []
        lines = ["Revealed Moves:"]
        for move in revealed_moves:
            lines.append(
                f"{move['index']}. {move['name']} [{move['type']}] acc:{move['accuracy']} pwr:{move['power']} pp:{move['pp']}"
            )
        return [html.escape(line) for line in lines]

    def build_buttons(self, specs: list[list[tuple[str, str]]] | None) -> types.InlineKeyboardMarkup | None:
        if not specs:
            return None
        markup = types.InlineKeyboardMarkup(row_width=5)
        for row in specs:
            if not row:
                continue
            markup.row(*(types.InlineKeyboardButton(label, callback_data=data) for label, data in row))
        return markup

    def team_preview_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[list[tuple[str, str]]]:
        specs = [(str(index), self.action_data(battle, player, f"t{index}")) for index, _ in enumerate(request["side"]["pokemon"], start=1)]
        rows = chunk_specs(specs, per_row=4)
        rows.append(
            [
                ("TEAM", self.action_data(battle, player, "vt")),
                #("ANALYSIS", self.action_data(battle, player, "ta")),
                #("DETAIL", self.action_data(battle, player, "td")),
            ]
        )
        return rows

    def doubles_team_preview_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[list[tuple[str, str]]]:
        self.ensure_doubles_draft(player, request)
        draft = player.doubles_draft
        size = self.doubles_request_size(request)
        rows: list[list[tuple[str, str]]] = []
        rows.append(
            [
                (
                    f"{doubles_slot_label(index)}{' *' if draft.focus == index else ''}{' OK' if draft.descriptions[index] else ''}",
                    self.action_data(battle, player, f"a{index}"),
                )
                for index in range(size)
            ]
        )
        team_specs = []
        for index, _pokemon in enumerate(request["side"]["pokemon"], start=1):
            team_specs.append((str(index), self.action_data(battle, player, f"t{index}")))
        rows.extend(chunk_specs(team_specs, per_row=4))
        rows.append(
            [
                ("CLEAR", self.action_data(battle, player, "cx")),
                ("TEAM", self.action_data(battle, player, "vt")),
                ("CHOICE", self.action_data(battle, player, "vc")),
            ]
        )
        return rows

    def doubles_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[list[tuple[str, str]]]:
        self.ensure_doubles_draft(player, request)
        draft = player.doubles_draft
        focus = draft.focus
        rows: list[list[tuple[str, str]]] = []
        slot_specs = [
            (
                f"{doubles_slot_label(index)}{' *' if focus == index else ''}{' OK' if draft.descriptions[index] else ''}",
                self.action_data(battle, player, f"a{index}"),
            )
            for index in range(self.doubles_request_size(request))
        ]
        rows.append(slot_specs)

        if draft.pending_target:
            target_specs = [
                (label[:18], self.action_data(battle, player, f"tg{code}"))
                for code, label in (draft.pending_target.get("target_options") or [])
            ]
            rows.extend(chunk_specs(target_specs, per_row=2))
            rows.append(
                [
                    ("BACK", self.action_data(battle, player, "cx")),
                    ("TEAM", self.action_data(battle, player, "vt")),
                    ("CHOICE", self.action_data(battle, player, "vc")),
                ]
            )
            return rows

        if request.get("forceSwitch"):
            switch_specs = [
                (str(index), self.action_data(battle, player, f"s{index}"))
                for index in self.doubles_valid_switch_indices(request, player, focus, forced=True)
            ]
            rows.extend(chunk_specs(switch_specs, per_row=5))
            if self.doubles_can_force_pass(request, player, focus):
                rows.append([("PASS", self.action_data(battle, player, "p"))])
            rows.append(
                [
                    ("TEAM", self.action_data(battle, player, "vt")),
                    ("CHOICE", self.action_data(battle, player, "vc")),
                    ("FORFIT", self.action_data(battle, player, "f")),
                ]
            )
            return rows

        active = (request.get("active") or [])[focus]
        move_specs = [(str(index), self.action_data(battle, player, f"m{index}")) for index, _ in enumerate(active.get("moves") or [], start=1)]
        rows.extend(chunk_specs(move_specs, per_row=4))
        rows.append(
            [
                ("MOVES", self.action_data(battle, player, "vm")),
                ("TEAM", self.action_data(battle, player, "vt")),
                ("CHOICE", self.action_data(battle, player, "vc")),
            ]
        )
        switch_specs = [
            (str(index), self.action_data(battle, player, f"s{index}"))
            for index in self.doubles_valid_switch_indices(request, player, focus, forced=False)
        ]
        if switch_specs:
            rows.extend(chunk_specs(switch_specs, per_row=5))
        mechanics = self.doubles_mechanic_button_specs(battle, player, request, focus)
        if mechanics:
            rows.extend(chunk_specs(mechanics, per_row=2))
        rows.append(
            [
                #("ANALYSIS", self.action_data(battle, player, "ta")),
                #("DETAIL", self.action_data(battle, player, "td")),
            ]
        )
        rows.append([("CLEAR", self.action_data(battle, player, "cx")), ("FORFIT", self.action_data(battle, player, "f"))])
        return rows

    def move_request_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[list[tuple[str, str]]]:
        if player.pending_target:
            target_specs = [
                (label[:18], self.action_data(battle, player, f"tg{code}"))
                for code, label in (player.pending_target.get("target_options") or [])
            ]
            rows = chunk_specs(target_specs, per_row=2)
            rows.append(
                [
                    ("BACK", self.action_data(battle, player, "cx")),
                    ("MOVES", self.action_data(battle, player, "vm")),
                    ("TEAM", self.action_data(battle, player, "vt")),
                ]
            )
            return rows

        active = request["active"][0]
        rows: list[list[tuple[str, str]]] = []
        move_specs = [(str(index), self.action_data(battle, player, f"m{index}")) for index, _ in enumerate(active["moves"], start=1)]
        rows.extend(chunk_specs(move_specs, per_row=4))
        rows.append(
            [
                ("MOVES", self.action_data(battle, player, "vm")),
                ("TEAM", self.action_data(battle, player, "vt")),
                #("ANALYSIS", self.action_data(battle, player, "ta")),
                #("DETAIL", self.action_data(battle, player, "td")),
            ]
        )
        if self.can_offer_switch(request):
            rows.extend(self.switch_button_specs(battle, player, request))
        mechanics = self.mechanic_button_specs(battle, player, request)
        if mechanics:
            rows.extend(chunk_specs(mechanics, per_row=2))
        rows.append([("FORFIT", self.action_data(battle, player, "f"))])
        return rows

    def switch_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[list[tuple[str, str]]]:
        specs = [
            (str(index), self.action_data(battle, player, f"s{index}"))
            for index in self.valid_switch_indices(request, forced=bool(request.get("forceSwitch")))
        ]
        return chunk_specs(specs, per_row=5)

    def forced_switch_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[list[tuple[str, str]]]:
        rows = self.switch_button_specs(battle, player, request)
        rows.append(
            [
                ("TEAM", self.action_data(battle, player, "vt")),
                #("ANALYSIS", self.action_data(battle, player, "ta")),
                #("DETAIL", self.action_data(battle, player, "td")),
            ]
        )
        return rows

    def mechanic_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
    ) -> list[tuple[str, str]]:
        active = request["active"][0]
        specs: list[tuple[str, str]] = []
        locked_primary = player.primed_action if player.primed_action in PRIMARY_GIMMICK_ACTIONS else None
        used_primary = player.used_primary_gimmick if player.used_primary_gimmick in PRIMARY_GIMMICK_ACTIONS else None
        allow_primary = lambda action_name: locked_primary in {None, action_name} and used_primary in {None, action_name}

        if active.get("canMegaEvo") and allow_primary("mega"):
            specs.append(("MEGA" + (" *" if player.primed_action == "mega" else ""), self.action_data(battle, player, "mg")))
        elif active.get("canMegaEvoX") and allow_primary("megax"):
            specs.append(("MEGA X" + (" *" if player.primed_action == "megax" else ""), self.action_data(battle, player, "mx")))
        elif active.get("canMegaEvoY") and allow_primary("megay"):
            specs.append(("MEGA Y" + (" *" if player.primed_action == "megay" else ""), self.action_data(battle, player, "my")))
        elif active.get("canUltraBurst"):
            specs.append(("ULTRA" + (" *" if player.primed_action == "ultra" else ""), self.action_data(battle, player, "ub")))
        if active.get("canZMove"):
            specs.append(("Z" + (" *" if player.primed_action == "zmove" else ""), self.action_data(battle, player, "zm")))
        if active.get("canTerastallize") and allow_primary("terastallize"):
            specs.append(("TERA" + (" *" if player.primed_action == "terastallize" else ""), self.action_data(battle, player, "tt")))
        if active.get("canDynamax") and allow_primary("dynamax"):
            specs.append(("DYNA" + (" *" if player.primed_action == "dynamax" else ""), self.action_data(battle, player, "dy")))
        return specs

    def doubles_mechanic_button_specs(
        self,
        battle: BattleSession,
        player: PlayerState,
        request: dict[str, Any],
        focus: int,
    ) -> list[tuple[str, str]]:
        active = (request.get("active") or [])[focus]
        specs: list[tuple[str, str]] = []
        primed_action = player.doubles_draft.primed_actions[focus] if focus < len(player.doubles_draft.primed_actions) else None
        locked_primary = self.chosen_primary_gimmick_in_draft(player)
        used_primary = player.used_primary_gimmick if player.used_primary_gimmick in PRIMARY_GIMMICK_ACTIONS else None
        allow_primary = lambda action_name: locked_primary in {None, action_name} and used_primary in {None, action_name}

        if active.get("canMegaEvo") and allow_primary("mega"):
            specs.append(("MEGA" + (" *" if primed_action == "mega" else ""), self.action_data(battle, player, "mg")))
        elif active.get("canMegaEvoX") and allow_primary("megax"):
            specs.append(("MEGA X" + (" *" if primed_action == "megax" else ""), self.action_data(battle, player, "mx")))
        elif active.get("canMegaEvoY") and allow_primary("megay"):
            specs.append(("MEGA Y" + (" *" if primed_action == "megay" else ""), self.action_data(battle, player, "my")))
        elif active.get("canUltraBurst"):
            specs.append(("ULTRA" + (" *" if primed_action == "ultra" else ""), self.action_data(battle, player, "ub")))
        if active.get("canZMove"):
            specs.append(("Z" + (" *" if primed_action == "zmove" else ""), self.action_data(battle, player, "zm")))
        if active.get("canTerastallize") and allow_primary("terastallize"):
            specs.append(("TERA" + (" *" if primed_action == "terastallize" else ""), self.action_data(battle, player, "tt")))
        if active.get("canDynamax") and allow_primary("dynamax"):
            specs.append(("DYNA" + (" *" if primed_action == "dynamax" else ""), self.action_data(battle, player, "dy")))
        return specs

    def can_offer_switch(self, request: dict[str, Any]) -> bool:
        return bool(self.valid_switch_indices(request))

    def valid_switch_indices(self, request: dict[str, Any], *, forced: bool = False) -> list[int]:
        if not forced:
            active = request["active"][0]
            if active.get("trapped"):
                return []
        return [
            index
            for index, pokemon in enumerate(request["side"]["pokemon"], start=1)
            if not pokemon.get("active") and not fainted(str(pokemon.get("condition", "")))
        ]

    def view_moves_text(self, battle: BattleSession, request: dict[str, Any], player: PlayerState) -> str:
        active = request.get("active") or []
        if not active:
            return "No move details available."
        focus = 0
        primed_action = player.primed_action
        if self.is_doubles_battle(battle):
            self.ensure_doubles_draft(player, request)
            focus = min(player.doubles_draft.focus, max(0, len(active) - 1))
            primed_action = player.doubles_draft.primed_actions[focus]
        current = active[focus]
        active_state = self.primary_active_state(battle, player.slot)
        if self.is_doubles_battle(battle):
            side_states = self.side_active_states(battle, player.slot)
            if focus < len(side_states):
                active_state = side_states[focus]
        is_dynamaxed = bool(active_state.get("dynamaxed"))
        lines: list[str] = []

        if (primed_action == "dynamax" or is_dynamaxed) and current.get("maxMoves"):
            lines = [
                compact_text(f"{i} {move.get('move', f'Max Move {i}')}{' DIS' if move.get('disabled') else ''}", limit=48)
                for i, move in enumerate((current.get("maxMoves") or {}).get("maxMoves", []), start=1)
            ]
        elif primed_action == "zmove" and current.get("canZMove"):
            for index, option in enumerate(current.get("canZMove") or [], start=1):
                lines.append(compact_text(f"{index} {option.get('move', 'Z-Move')}" if option else f"{index} unavailable", limit=48))
        else:
            for index, move in enumerate(current["moves"], start=1):
                move_name = str(move.get("move", f"Move {index}"))
                move_id = move.get("id") or re.sub(r"[^a-z0-9]+", "", move_name.lower())
                info = MOVE_BY_ID.get(move_id, {})
                move_type = str(move.get("displayType") or info.get("type", "?")).title()[:3]
                power = info.get("basePower", info.get("power", "-"))
                accuracy = move.get("displayAccuracy") or info.get("accuracy", "-")
                pp = f"{move.get('pp', '?')}/{move.get('maxpp', '?')}"
                suffix = " [X]" if move.get("disabled") else ""
                lines.append(f"{index}.{move_name}[{move_type}]{suffix} P:{power} A:{accuracy} {pp}")

        if self.is_doubles_battle(battle):
            return compact_text(f"{doubles_slot_label(focus)}\n" + "\n".join(lines), limit=195)
        return compact_text("\n".join(lines), limit=195)

    def view_team_text(self, request: dict[str, Any]) -> str:
        lines = []
        for index, pokemon in enumerate(request["side"]["pokemon"], start=1):
            prefix = "*" if pokemon.get("active") else ""
            details = str(pokemon.get("details", pokemon.get("ident", f"Pokemon {index}")))
            name = details_name(details)
            shiny_suffix = " ✨" if pokemon.get("shiny") else ""
            info = SPECIES_BY_NORMALIZED_NAME.get(normalized(name), {})
            pokemon_types = "/".join(t[:3].title() for t in info.get("types", ["?"])) if info.get("types") else "?"
            parsed = parse_condition(str(pokemon.get("condition", "")))
            hp = "FNT" if parsed["fainted"] else (f"{parsed['percent']}%" if parsed["percent"] is not None else parsed["hp_text"])
            item = str(pokemon.get("item") or "") or "None"
            if len(item) > 10:
                item = item[:10]
            lines.append(f"{index}{prefix}.{name}{shiny_suffix}[{pokemon_types}] {hp} {item}")
        return compact_text("\n".join(lines), limit=195)

    def battle_stats_text(self, snapshot: dict[str, Any]) -> str:
        active = snapshot.get("active")
        if isinstance(active, list):
            turn = int(snapshot.get("turn") or 0)
            live = self.battle_stats_live_entries(snapshot)

            lines = [f"<b>Your Active Pokemon</b> - Turn {turn}", ""]
            if not live:
                lines.append("No active Pokemon is currently visible for your side.")
                return "\n".join(lines)

            for index, item in enumerate(live):
                if len(live) > 1:
                    slot = html.escape(str(item.get("position") or item.get("slot") or "?").upper())
                    lines.append(f"<b>{slot}</b>")
                lines.append(self._single_battle_stats_text(item))
                if index + 1 < len(live):
                    lines.append("")
            return "\n".join(lines)

        return self._single_battle_stats_text(snapshot)

    def battle_stats_live_entries(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        active = snapshot.get("active")
        if not isinstance(active, list):
            return [snapshot] if snapshot else []
        requester_slot = str(snapshot.get("requesterSlot") or "")
        live = [
            item
            for item in active
            if isinstance(item, dict) and str(item.get("slot") or "") == requester_slot
        ]
        live.sort(key=lambda item: str(item.get("position") or item.get("slot") or ""))
        return live

    def battle_stats_tera_reveal_text(self, snapshot: dict[str, Any]) -> str:
        live = self.battle_stats_live_entries(snapshot)
        if not live:
            return ""
        reveal_lines = []
        for index, item in enumerate(live, start=1):
            name = str(item.get("name") or "Pokemon")
            tera_type = str(item.get("terastallized") or item.get("teraType") or "Unknown").strip() or "Unknown"
            if len(live) > 1:
                reveal_lines.append(f"{index}. {name} - {tera_type}")
            else:
                reveal_lines.append(f"{name} - {tera_type}")
        return "\n".join(reveal_lines)

    def _single_battle_stats_text(self, snapshot: dict[str, Any]) -> str:
        name = str(snapshot.get("name") or "Pokemon")
        level = int(snapshot.get("level") or 0)
        base_types = [str(item) for item in (snapshot.get("baseTypes") or []) if str(item).strip()]
        current_types = [str(item) for item in (snapshot.get("currentTypes") or []) if str(item).strip()]
        item_name = str(snapshot.get("item") or "None").strip() or "None"
        item_id = str(snapshot.get("itemId") or "").strip()
        status = str(snapshot.get("status") or "").strip()
        hp = snapshot.get("hp") or {}
        lines = [f"<b>{html.escape(name)}</b> [Lv. {level}]"]

        base_type_text = format_types(base_types)
        current_type_text = format_types(current_types)
        if base_types and current_types and base_types != current_types:
            type_part = f"[{base_type_text} -> {current_type_text}]"
        else:
            type_part = f"[{current_type_text if current_types else base_type_text}]"
        lines.append(html.escape(type_part))
        lines.append(f"[Held Item: {html.escape(item_name)}]")
        if status:
            lines.append(f"Status: {html.escape(status)}")
        lines.append("")
        lines.append("<b>Live Stats</b>")
        lines.append(f"HP: {int(hp.get('current') or 0)}/{int(hp.get('max') or 0)}")
        if snapshot.get("bestEffort"):
            lines.append("<i>Best-effort snapshot: some live modifiers could not be read safely between turns.</i>")

        item_stat_notes = {
            "choiceband": {"atk": "Choice Band"},
            "choicespecs": {"spa": "Choice Specs"},
            "choicescarf": {"spe": "Choice Scarf"},
            "assaultvest": {"spd": "Assault Vest"},
            "eviolite": {"def": "Eviolite", "spd": "Eviolite"},
            "thickclub": {"atk": "Thick Club"},
            "lightball": {"atk": "Light Ball", "spa": "Light Ball"},
            "deepseatooth": {"spa": "Deep Sea Tooth"},
            "deepseascale": {"spd": "Deep Sea Scale"},
            "metalpowder": {"def": "Metal Powder"},
            "quickpowder": {"spe": "Quick Powder"},
        }
        stat_line_labels = {"atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}
        for stat in ("atk", "def", "spa", "spd", "spe"):
            stat_payload = (snapshot.get("stats") or {}).get(stat) or {}
            current = int(stat_payload.get("current") or 0)
            base = int(stat_payload.get("base") or 0)
            unboosted = int(stat_payload.get("unboosted") or 0)
            stage = int(stat_payload.get("stage") or 0)
            modified = current != base
            value = f"<b>{current}</b>" if modified else str(current)
            notes: list[str] = []
            if stage:
                notes.append(f"{stage:+d}")
            item_note = item_stat_notes.get(item_id, {}).get(stat)
            if item_note and unboosted != base:
                notes.append(item_note)
            elif unboosted != base:
                notes.append("modifier active")
            note_text = f" ({', '.join(notes)})" if notes else ""
            lines.append(f"{stat_line_labels[stat]}: {value}{html.escape(note_text)}")
        return "\n".join(lines)

    def _is_challenge_expired(self, challenge: PendingChallenge) -> bool:
        return challenge.state == "open" and challenge.expires_at > 0 and asyncio.get_running_loop().time() >= challenge.expires_at

    async def _expire_pending_challenge_later(self, challenge_id: str) -> None:
        challenge = self.pending_by_id.get(challenge_id) or self.pending_ffa_by_id.get(challenge_id)
        if challenge is None:
            return
        delay = max(0.0, challenge.expires_at - asyncio.get_running_loop().time())
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        challenge = self.pending_by_id.get(challenge_id) or self.pending_ffa_by_id.get(challenge_id)
        if challenge is None or challenge.state != "open":
            return
        challenge.state = "expired"
        if isinstance(challenge, PendingFfaChallenge):
            self._release_pending_ffa(challenge, cancel_expiry_task=False)
            text = self.ffa_text(challenge)
        else:
            self._release_pending_challenge(challenge, cancel_expiry_task=False)
            text = self.challenge_text(challenge)
        await self._edit_message(
            challenge.chat_id,
            challenge.public_message_id,
            text,
            reply_markup=None,
            parse_mode="HTML",
        )

    async def _answer(self, callback_query_id: str, text: str | None = None, *, show_alert: bool = False) -> None:
        try:
            await self.bot.answer_callback_query(callback_query_id, text, show_alert=show_alert)
        except Exception:
            return

    async def _edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: types.InlineKeyboardMarkup | None,
        parse_mode: str | None = None,
    ) -> None:
        try:
            await self.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except ApiTelegramException as exc:
            if "message is not modified" in str(exc).lower():
                return
            if "there is no text in the message to edit" in str(exc).lower() or "message content and reply markup are exactly the same" in str(exc).lower():
                try:
                    await self.bot.edit_message_caption(
                        caption=self.visual_caption_text(text),
                        chat_id=chat_id,
                        message_id=message_id,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )
                    return
                except Exception:
                    return
        except Exception:
            return


def register_showdown_challenge_handlers(bot: AsyncTeleBot) -> ShowdownChallengeService:
    global ACTIVE_SHOWDOWN_SERVICE
    service = ShowdownChallengeService(bot)
    ACTIVE_SHOWDOWN_SERVICE = service
    callback_limiter = CallbackRateLimiter()

    @bot.message_handler(commands=["challenge"])
    @user_registered(bot)
    @user_not_banned(bot)
    async def challenge_command(message: types.Message):
        await service.on_challenge_command(message)

    @bot.message_handler(commands=["doubles"])
    @user_registered(bot)
    @user_not_banned(bot)
    async def doubles_command(message: types.Message):
        await service.on_doubles_command(message)

    @bot.message_handler(commands=["ffa"])
    @user_registered(bot)
    @user_not_banned(bot)
    async def ffa_command(message: types.Message):
        await service.on_ffa_command(message)

    @bot.message_handler(commands=["battle_stats"])
    @user_registered(bot)
    @user_not_banned(bot)
    async def battle_stats_command(message: types.Message):
        await service.on_battle_stats_command(message)

    @bot.message_handler(commands=["exit"])
    @user_registered(bot)
    @user_not_banned(bot)
    async def exit_command(message: types.Message):
        await service.on_exit_command(message)

    @bot.message_handler(commands=["testsprite", "trstbimage"])
    @user_registered(bot)
    @user_not_banned(bot)
    async def test_battle_image_command(message: types.Message):
        await service.on_test_battle_image_command(message)

    @bot.callback_query_handler(func=lambda call: str(call.data or "").startswith("sdb:"))
    @user_not_banned(bot)
    async def showdown_callbacks(call: types.CallbackQuery):
        if await callback_limiter.is_limited(
            call,
            bot,
            bypass=service.is_read_only_callback_data(str(call.data or "")),
        ):
            return
        await service.handle_callback(call)

    return service


def get_showdown_service() -> ShowdownChallengeService | None:
    return ACTIVE_SHOWDOWN_SERVICE
