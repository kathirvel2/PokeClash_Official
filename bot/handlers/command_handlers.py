import os
import json
import asyncio
import uuid
from telebot.async_telebot import AsyncTeleBot
from telebot import types
import random
from bot.mechanics.db import db
from bot.bridge.showdown_team_packer import import_team as import_showdown_team
from bot.services.pokeapi import get_pokemon_image_and_stats
import html
from PIL import Image
import io
from telebot.types import LinkPreviewOptions, InlineKeyboardMarkup, InlineKeyboardButton

def levenshtein_distance(s1, s2):
    """Calculates the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

from bot.mechanics.team import Pokemon, create_pokemon, normalize_species_id
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID
from bot.ui_components import get_stats_message_content, get_myteam_message_content, get_team_selection_content
from bot.image_generation.team_image import create_team_image
from bot.team_analysis.analyzer import analyze_team_coverage, format_analysis_caption
from bot.team_analysis.presenter import build_team_from_showdown_request
from bot.battle.battle_ui import generate_battle_stats_text # We will create this next
from bot.battle.battle_engine import active_battles
from bot.image_generation.ranking_image import create_ranking_summary_image
from bot.image_generation.trainer_card import create_trainer_card_image
from bot.ui_components import get_settings_content
from bot.handlers.decorators import admin_only, user_registered, user_not_banned # Import new decorator
from bot.mechanics.form_validation import get_collection_form_block_reason
from bot.showdown_config import BOT_DIR, OWNED_BATTLE_FORMAT, SHOWDOWN_DIR

LEGENDARY_TIERS = ["Uber", "AG"]
LEGENDARY_POKEMON_IDS = {
    s['id'] for s in SPECIES_BY_ID.values() if s.get('tier') in LEGENDARY_TIERS or 'Mythical' in s.get('tags', []) or 'Sub-Legendary' in s.get('tags', []) or 'Restricted Legendary' in s.get('tags', [])
}
SHINY_PASS_PRICE = 2000
LEGENDARY_PASS_PRICE = 6000

BOT_USERNAME = os.getenv('BOT_USERNAME', 'PokeClash_bot') 
WEB_APP_LINK_NAME = os.getenv('WEB_APP_LINK_NAME', 'Pokeclashdex')
pending_team_imports = {}

# Command Handlers
def register_command_handlers(bot: AsyncTeleBot):
    """
    Registers all the command handlers for the bot.
    """
    COMMUNITY_CHAT_ID = os.getenv('COMMUNITY_CHAT_ID')
    COMMUNITY_CHAT_LINK = os.getenv('COMMUNITY_CHAT_LINK')
    SLOT_COST = 500

    def _parse_bool_flag(value: str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False
        return None

    def _format_ban_label(value: bool) -> str:
        return "ON" if value else "OFF"

    def _resolve_pass_target(pokemon_query_raw: str):
        pokemon_query = pokemon_query_raw.lower().replace("-", "").replace(" ", "")
        return next((
            s for s in SPECIES_BY_ID.values()
            if s['name'].lower().replace("-", "").replace(" ", "") == pokemon_query
        ), None)

    def _build_admin_user_summary(user_details: dict) -> str:
        return (
            f"<b>{html.escape(user_details['first_name'] or 'Unknown')}</b> "
            f"(<code>{user_details['user_id']}</code>)\n"
            f"💰 Coins: <b>{user_details['clash_coins']}</b>\n"
            f"✨ Shiny Passes: <b>{user_details['shiny_pass_count']}</b>\n"
            f"🌟 Legendary Passes: <b>{user_details['legendary_pass_count']}</b>\n"
            f"📦 Max Slots: <b>{user_details['max_pokemon_slots']}</b>\n"
            f"🚫 Full Ban: <b>{_format_ban_label(user_details['is_banned'])}</b>\n"
            f"⚔️ Battle Ban: <b>{_format_ban_label(user_details['is_battle_banned'])}</b>"
        )

    def _format_redeem_rewards(clash_coins: int, shiny_passes: int, legendary_passes: int) -> str:
        reward_lines = []
        if clash_coins:
            reward_lines.append(f"💰 Clash Coins: <b>{clash_coins}</b>")
        if shiny_passes:
            reward_lines.append(f"✨ Shiny Passes: <b>{shiny_passes}</b>")
        if legendary_passes:
            reward_lines.append(f"🌟 Legendary Passes: <b>{legendary_passes}</b>")
        return "\n".join(reward_lines)

    async def _grant_shiny_pokemon_with_pass(message: types.Message, species_data: dict, pass_type: str):
        user_id = message.from_user.id
        pokemon_id = species_data['id']

        block_reason = get_collection_form_block_reason(species_data)
        if block_reason:
            await bot.reply_to(
                message,
                f"❌ <b>{species_data['name']}</b> is a {block_reason} and cannot be targeted by a pass.",
                parse_mode="HTML"
            )
            return

        new_pokemon = create_pokemon(species_id=pokemon_id, is_shiny=True)

        while db.pokemon_uuid_exists(new_pokemon.pokemon_uuid):
            new_pokemon.pokemon_uuid = uuid.uuid4().hex[:8]

        db.add_pokemon_to_collection(user_id, new_pokemon)

        if pass_type == "legendary":
            db.add_legendary_passes(user_id, -1)
            pass_label = "Legendary Pass"
        else:
            db.add_shiny_passes(user_id, -1)
            pass_label = "Shiny Pass"

        await bot.reply_to(
            message,
            f"✨ Your {pass_label} was used successfully. A SHINY <b>{new_pokemon.name}</b> has been added to your collection.",
            parse_mode="HTML"
        )

    async def check_and_handle_slot_limit(message: types.Message) -> bool:
        """
        Checks if a user is at their slot limit.
        Returns True if they are blocked, False if they can proceed.
        """
        user_id = message.from_user.id
        current_count = len(db.get_collection(user_id))
        max_slots = db.get_max_slots(user_id)
        
        # Check if the user is in the community chat
        is_in_chat = False
        if COMMUNITY_CHAT_ID:
            try:
                member = await bot.get_chat_member(COMMUNITY_CHAT_ID, user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    is_in_chat = True
            except Exception:
                is_in_chat = False # Bot is not in the chat or user is not found

        # --- Your "Re-check on Leave" logic ---
        # Update their max slots based on chat status *before* checking the limit
        if is_in_chat and max_slots < 30:
            max_slots = 30
            db.set_max_slots(user_id, 30)
        elif not is_in_chat and max_slots > 12:
            # If they left the chat, their max slots revert to 12
            # but they keep their purchased slots (if any > 30)
            if max_slots < 30: # Only revert if they are in the bonus "chat" tier
                max_slots = 12
                db.set_max_slots(user_id, 12)
        
        # --- Now, check the limit ---
        if current_count < max_slots:
            return False # User has space, they can proceed.

        # --- User is at their limit, send the appropriate message ---
        
        # Tier 1 Block: Not in chat and at 12-slot limit
        if not is_in_chat:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Join Community Chat", url=COMMUNITY_CHAT_LINK))
            text = (
                f"🚫 <b>Collection Full!</b>\n\n"
                f"You have reached your limit of <b>{max_slots} Pokémon</b> slots.\n\n"
                f"Join our community chat to unlock up to <b>30 slots</b> for free!"
            )
            await bot.reply_to(message, text, reply_markup=markup, parse_mode="HTML")
            return True # Block the command

        # Tier 2 Block: In chat and at 30-slot limit (or higher purchased limit)
        if is_in_chat:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(f"Buy 1 Slot (500 Coins)", callback_data=f"buy_slot_{message.from_user.id}"))
            text = (
                f"🚫 <b>Collection Full!</b>\n\n"
                f"You have reached your limit of <b>{max_slots} Pokémon</b> slots.\n\n"
                f"Would you like to buy one more slot for <b>500 Clash Coins</b>?"
            )
            await bot.reply_to(message, text, reply_markup=markup, parse_mode="HTML")
            return True # Block the command
            
        return True # Default block just in case

    async def resolve_collection_slot_limit(user_id: int) -> tuple[int, bool]:
        max_slots = db.get_max_slots(user_id)
        is_in_chat = False

        if COMMUNITY_CHAT_ID:
            try:
                member = await bot.get_chat_member(COMMUNITY_CHAT_ID, user_id)
                if member.status in ['member', 'administrator', 'creator']:
                    is_in_chat = True
            except Exception:
                is_in_chat = False

        if is_in_chat and max_slots < 30:
            max_slots = 30
            db.set_max_slots(user_id, 30)
        elif not is_in_chat and 12 < max_slots < 30:
            max_slots = 12
            db.set_max_slots(user_id, 12)

        return max_slots, is_in_chat

    def _ensure_user_teams(user_id: int) -> None:
        user_teams = db.get_user_teams(user_id)
        if user_teams:
            return
        for index in range(6):
            db.create_team(user_id, f"Team {index + 1}")

    def _to_id(value: str) -> str:
        return "".join(char for char in str(value or "").lower() if char.isalnum())

    def _species_data_from_name(name: str) -> dict | None:
        species_id = normalize_species_id(name)
        if species_id in SPECIES_BY_ID:
            return SPECIES_BY_ID[species_id]
        return next(
            (
                species_data for species_data in SPECIES_BY_ID.values()
                if normalize_species_id(species_data.get("name")) == species_id
            ),
            None,
        )

    def _max_hp_for_import(species_data: dict, level: int, iv_hp: int, ev_hp: int) -> int:
        base_hp = int(species_data.get("baseStats", {}).get("hp", 1))
        return int(((2 * base_hp + iv_hp + ev_hp // 4) * level) / 100) + level + 10

    def _build_imported_collection_pokemon(imported_set: dict) -> Pokemon:
        species_name = str(imported_set.get("species") or "").strip()
        species_data = _species_data_from_name(species_name)
        if not species_data:
            raise ValueError(f"Species data for {species_name or 'that Pokemon'} is missing from the bot.")

        level = max(1, min(100, int(imported_set.get("level") or 100)))
        pokemon = create_pokemon(species_id=species_data["id"], level=level, is_shiny=False)

        nickname = str(imported_set.get("name") or "").strip()
        pokemon.name = nickname or species_data["name"]
        pokemon.item = str(imported_set.get("item") or "").strip() or None
        pokemon.ability = str(imported_set.get("ability") or "").strip() or pokemon.ability
        pokemon.nature = str(imported_set.get("nature") or "").strip() or pokemon.nature
        pokemon.level = level
        pokemon.tera_type = str(imported_set.get("teraType") or pokemon.tera_type or "Normal").strip()
        pokemon.moves = [_to_id(move_name) for move_name in list(imported_set.get("moves") or [])[:4]]

        evs = imported_set.get("evs") or {}
        ivs = imported_set.get("ivs") or {}
        pokemon.evs.hp = int(evs.get("hp", 0))
        pokemon.evs.atk = int(evs.get("atk", 0))
        pokemon.evs.def_ = int(evs.get("def", 0))
        pokemon.evs.spa = int(evs.get("spa", 0))
        pokemon.evs.spd = int(evs.get("spd", 0))
        pokemon.evs.spe = int(evs.get("spe", 0))
        pokemon.ivs.hp = int(ivs.get("hp", 31))
        pokemon.ivs.atk = int(ivs.get("atk", 31))
        pokemon.ivs.def_ = int(ivs.get("def", 31))
        pokemon.ivs.spa = int(ivs.get("spa", 31))
        pokemon.ivs.spd = int(ivs.get("spd", 31))
        pokemon.ivs.spe = int(ivs.get("spe", 31))
        pokemon.max_hp = _max_hp_for_import(species_data, pokemon.level, pokemon.ivs.hp, pokemon.evs.hp)
        pokemon.current_hp = pokemon.max_hp
        return pokemon

    async def _process_showdown_team_import(message: types.Message, export_text: str) -> bool:
        user_id = message.from_user.id
        cleaned_export = str(export_text or "").strip()
        if not cleaned_export:
            await bot.reply_to(message, "Send a Showdown export after `/import`, or use `/cancelimport`.", parse_mode="Markdown")
            return False

        try:
            import_result = await import_showdown_team(
                bot_dir=BOT_DIR,
                showdown_dir=SHOWDOWN_DIR,
                format_id=OWNED_BATTLE_FORMAT,
                text=cleaned_export,
            )
        except Exception as exc:
            await bot.reply_to(message, f"Import failed: {html.escape(str(exc))}", parse_mode="HTML")
            return False

        imported_sets = list(import_result.get("team") or [])
        problems = [str(problem).strip() for problem in list(import_result.get("problems") or []) if str(problem).strip()]
        if problems:
            await bot.reply_to(
                message,
                f"Imported team is invalid:\n{html.escape('; '.join(problems[:12]))}",
                parse_mode="HTML",
            )
            return False

        if not imported_sets:
            await bot.reply_to(message, "I couldn't find any Pokemon in that export.")
            return False

        if len(imported_sets) > 6:
            await bot.reply_to(message, "Only up to 6 Pokemon can be imported into your active team.")
            return False

        shiny_species = [
            str(imported_set.get("species") or imported_set.get("name") or "Pokemon")
            for imported_set in imported_sets
            if imported_set.get("shiny")
        ]
        if shiny_species:
            await bot.reply_to(
                message,
                f"Shiny imports are not allowed. Remove the shiny flag from: {', '.join(shiny_species)}.",
            )
            return False

        _ensure_user_teams(user_id)
        active_team_db = db.get_active_team(user_id)
        if not active_team_db:
            await bot.reply_to(message, "No active team was found. Open `/myteams` once and try again.", parse_mode="Markdown")
            return False

        active_team_id = active_team_db[0]
        active_team_name = active_team_db[2]
        active_team_uuids = list(active_team_db[3] or [])
        empty_slots = max(0, 6 - len(active_team_uuids))
        if len(imported_sets) > empty_slots:
            await bot.reply_to(
                message,
                f"Your active team <b>{html.escape(active_team_name)}</b> only has {empty_slots} empty slot(s). Empty more slots and try again.",
                parse_mode="HTML",
            )
            return False

        current_collection = db.get_collection(user_id)
        max_slots, is_in_chat = await resolve_collection_slot_limit(user_id)
        needed_collection_slots = len(current_collection) + len(imported_sets) - max_slots
        if needed_collection_slots > 0:
            markup = InlineKeyboardMarkup()
            if is_in_chat:
                markup.add(InlineKeyboardButton("Buy 1 Slot (500 Coins)", callback_data=f"buy_slot_{user_id}"))
                text = (
                    f"🚫 <b>Collection Full!</b>\n\n"
                    f"You need <b>{needed_collection_slots}</b> more slot(s) to import this team.\n"
                    f"Current limit: <b>{max_slots}</b>."
                )
            else:
                if COMMUNITY_CHAT_LINK:
                    markup.add(InlineKeyboardButton("Join Community Chat", url=COMMUNITY_CHAT_LINK))
                text = (
                    f"🚫 <b>Collection Full!</b>\n\n"
                    f"You need <b>{needed_collection_slots}</b> more slot(s) to import this team.\n"
                    f"Join the community chat to unlock up to <b>30 slots</b>."
                )
            await bot.reply_to(message, text, reply_markup=markup if markup.keyboard else None, parse_mode="HTML")
            return False

        new_pokemon: list[Pokemon] = []
        for imported_set in imported_sets:
            species_name = str(imported_set.get("species") or "").strip()
            species_data = _species_data_from_name(species_name)
            if not species_data:
                await bot.reply_to(message, f"I couldn't map {html.escape(species_name or 'that Pokemon')} into the bot data.", parse_mode="HTML")
                return False
            block_reason = get_collection_form_block_reason(species_data)
            if block_reason:
                await bot.reply_to(
                    message,
                    f"{html.escape(species_data['name'])} is a {html.escape(block_reason)} and cannot be imported into your collection.",
                    parse_mode="HTML",
                )
                return False
            try:
                pokemon = _build_imported_collection_pokemon(imported_set)
            except ValueError as exc:
                await bot.reply_to(message, html.escape(str(exc)), parse_mode="HTML")
                return False
            while db.pokemon_uuid_exists(pokemon.pokemon_uuid):
                pokemon.pokemon_uuid = uuid.uuid4().hex[:8]
            new_pokemon.append(pokemon)

        updated_collection = list(current_collection)
        updated_collection.extend(new_pokemon)
        db.save_collection(user_id, updated_collection)
        db.update_team(active_team_id, active_team_uuids + [pokemon.pokemon_uuid for pokemon in new_pokemon])
        pending_team_imports.pop(user_id, None)

        imported_names = ", ".join(html.escape(pokemon.name) for pokemon in new_pokemon)
        await bot.reply_to(
            message,
            (
                f"Imported <b>{len(new_pokemon)}</b> Pokemon into <b>{html.escape(active_team_name)}</b>.\n"
                f"Added: {imported_names}"
            ),
            parse_mode="HTML",
        )
        return True

    @bot.message_handler(commands=['start', 'help'])
    async def start_command(message):
        user = message.from_user
        db.add_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
        
        content = _get_start_menu_content(user.first_name)
        
        await bot.reply_to(message, content["text"], parse_mode="HTML", reply_markup=content["reply_markup"])

    @bot.message_handler(commands=['shinypass'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def shinypass_command(message):

        if await check_and_handle_slot_limit(message):
            return

        user = message.from_user

        # 1. Check if the user has a shiny pass
        shiny_passes = db.get_shiny_pass_count(user.id)
        if shiny_passes <= 0:
            await bot.reply_to(message, "You don't have any Shiny Passes left!")
            return

        # 2. Basic argument check (same as /add)
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            reply_text = "Please specify a Pokémon to use your pass on!\n\n<b>Usage:</b> <code>/shinypass &lt;pokemon_name&gt;</code>"
            await bot.reply_to(message, reply_text, parse_mode="HTML")
            return
        
        pokemon_query_raw = parts[1].strip()
        species_data = _resolve_pass_target(pokemon_query_raw)
    
        if not species_data:
            await bot.reply_to(message, f"Sorry, I couldn't find a Pokémon named '{pokemon_query_raw}'.")
            return

        if species_data['id'] in LEGENDARY_POKEMON_IDS:
            await bot.reply_to(message, "Shiny Passes can only be used on non-legendary Pokémon.")
            return

        await _grant_shiny_pokemon_with_pass(message, species_data, pass_type="shiny")

    @bot.message_handler(commands=['import'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def import_team_command(message):
        inline_export = ""
        if message.text and "\n" in message.text:
            inline_export = message.text.split("\n", 1)[1].strip()
        if inline_export:
            await _process_showdown_team_import(message, inline_export)
            return

        pending_team_imports[message.from_user.id] = {"chat_id": message.chat.id}
        await bot.reply_to(
            message,
            "Send your Showdown export text for up to 6 Pokemon. Use `/cancelimport` to stop.",
            parse_mode="Markdown",
        )

    @bot.message_handler(commands=['cancelimport'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def cancel_import_command(message):
        if pending_team_imports.pop(message.from_user.id, None) is None:
            await bot.reply_to(message, "No active team import is waiting for you.")
            return
        await bot.reply_to(message, "Cancelled the pending team import.")

    @bot.message_handler(
        content_types=['text'],
        func=lambda message: message.from_user.id in pending_team_imports and not str(message.text or "").startswith("/"),
    )
    @user_registered(bot)
    @user_not_banned(bot)
    async def import_team_text_handler(message):
        await _process_showdown_team_import(message, message.text or "")

    @bot.message_handler(commands=['legendarypass'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def legendarypass_command(message):

        if await check_and_handle_slot_limit(message):
            return

        user = message.from_user
        legendary_passes = db.get_legendary_pass_count(user.id)
        if legendary_passes <= 0:
            await bot.reply_to(message, "You don't have any Legendary Passes left!")
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            reply_text = "Please specify a legendary Pokémon to use your pass on!\n\n<b>Usage:</b> <code>/legendarypass &lt;pokemon_name&gt;</code>"
            await bot.reply_to(message, reply_text, parse_mode="HTML")
            return

        pokemon_query_raw = parts[1].strip()
        species_data = _resolve_pass_target(pokemon_query_raw)

        if not species_data:
            await bot.reply_to(message, f"Sorry, I couldn't find a Pokémon named '{pokemon_query_raw}'.")
            return

        if species_data['id'] not in LEGENDARY_POKEMON_IDS:
            await bot.reply_to(message, "Legendary Passes can only be used on legendary, mythical, or sub-legendary Pokémon.")
            return

        await _grant_shiny_pokemon_with_pass(message, species_data, pass_type="legendary")

    @bot.message_handler(commands=['buy'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def buy_command(message):
        parts = message.text.split()
        if len(parts) != 3:
            await bot.reply_to(
                message,
                (
                    "<b>Usage:</b>\n"
                    "<code>/buy pass &lt;count&gt;</code>\n"
                    "<code>/buy legendarypass &lt;count&gt;</code>\n\n"
                    f"✨ Shiny Pass: <b>{SHINY_PASS_PRICE}</b> Clash Coins each\n"
                    f"🌟 Legendary Pass: <b>{LEGENDARY_PASS_PRICE}</b> Clash Coins each"
                ),
                parse_mode="HTML"
            )
            return

        item_name = parts[1].lower().replace("-", "").replace("_", "")
        try:
            count = int(parts[2])
        except ValueError:
            await bot.reply_to(message, "The pass count must be a whole number.")
            return

        if count <= 0 or count > 50:
            await bot.reply_to(message, "Choose a pass count between 1 and 50.")
            return

        if item_name in {"pass", "shinypass", "shinypass"}:
            item_label = "Shiny Pass"
            unit_price = SHINY_PASS_PRICE
            apply_purchase = lambda user_id, amount: db.add_shiny_passes(user_id, amount)
            get_balance = db.get_shiny_pass_count
        elif item_name in {"legendarypass", "legendpass", "legendary"}:
            item_label = "Legendary Pass"
            unit_price = LEGENDARY_PASS_PRICE
            apply_purchase = lambda user_id, amount: db.add_legendary_passes(user_id, amount)
            get_balance = db.get_legendary_pass_count
        else:
            await bot.reply_to(message, "Unknown item. Use <code>/buy pass 1</code> or <code>/buy legendarypass 1</code>.", parse_mode="HTML")
            return

        total_cost = unit_price * count
        current_coins = db.get_clash_coin_count(message.from_user.id)
        if current_coins < total_cost:
            await bot.reply_to(
                message,
                f"You need <b>{total_cost}</b> Clash Coins for that purchase, but you only have <b>{current_coins}</b>.",
                parse_mode="HTML"
            )
            return

        db.add_clash_coins(message.from_user.id, -total_cost)
        apply_purchase(message.from_user.id, count)
        new_balance = get_balance(message.from_user.id)
        new_coin_balance = db.get_clash_coin_count(message.from_user.id)

        await bot.reply_to(
            message,
            (
                f"✅ Purchased <b>{count}</b> {item_label}{'' if count == 1 else 'es'} for <b>{total_cost}</b> Clash Coins.\n\n"
                f"🎟️ New {item_label} balance: <b>{new_balance}</b>\n"
                f"💰 Clash Coins left: <b>{new_coin_balance}</b>"
            ),
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['add'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def add_pokemon_command(message):

        if await check_and_handle_slot_limit(message):
            return

        user = message.from_user
        db.add_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            # --- THIS IS THE CHANGED LINE ---
            reply_text = "Please specify a Pokémon to add!\n\n<b>Usage:</b> <code>/add &lt;pokemon_name&gt;</code>"
            await bot.reply_to(message, reply_text, parse_mode="HTML")
            return
        
        pokemon_query_raw = parts[1].strip()
        query_lower = pokemon_query_raw.lower()
        if query_lower == 'minior':
            await bot.reply_to(
                message,
                "❌ <b>Minior's Core form</b> is battle-only. To add Minior, please specify its shelled form:\n\n"
                "<code>/add Minior-Meteor</code>",
                parse_mode="HTML"
            )
            return
        if query_lower == 'darmanitan-zen' or query_lower == 'darmanitan zen':
            await bot.reply_to(
                message,
                "❌ <b>Darmanitan-Zen</b> is a battle-only form. Please add the regular form:\n\n"
                "<code>/add Darmanitan</code>",
                parse_mode="HTML"
            )
            return
        if query_lower == 'eternatus-eternamax' or query_lower == 'eternatuseternamax':
            await bot.reply_to(
                message,
                "❌ <b>Eternatus-Eternamax</b> is a battle-only form and cannot be added to your collection.",
                parse_mode="HTML"
            )
            return
        pokemon_query = pokemon_query_raw.lower().replace("-", "").replace(" ", "")
        
        species_data = next((
            s for s in SPECIES_BY_ID.values() 
            if s['name'].lower().replace("-", "").replace(" ", "") == pokemon_query
        ), None)
    
        if not species_data:
            # --- NEW: "Did You Mean?" Logic ---
            best_match = None
            min_dist = 3  # Set a threshold for suggestions

            for s in SPECIES_BY_ID.values():
                dist = levenshtein_distance(pokemon_query, s['name'].lower().replace("-", "").replace(" ", ""))
                if dist < min_dist:
                    min_dist = dist
                    best_match = s

            if best_match:
                markup = types.InlineKeyboardMarkup()
                markup.row(
                    types.InlineKeyboardButton("✅ Yes", callback_data=f"add_confirm_{best_match['id']}"),
                    types.InlineKeyboardButton("❌ No", callback_data="suggestion_cancel")
                )
                await bot.reply_to(message, f"Did you mean <b>{best_match['name']}</b>?", reply_markup=markup, parse_mode="HTML")
            else:
                await bot.reply_to(message, f"Sorry, I couldn't find a Pokémon named '{pokemon_query_raw}'.")
            return
        
        block_reason = get_collection_form_block_reason(species_data)
        if block_reason:
            await bot.reply_to(
                message,
                f"❌ <b>{species_data['name']}</b> is a {block_reason} and cannot be added directly to your collection.",
                parse_mode="HTML"
            )
            return

        SHINY_RATE = 4096
        is_shiny = (random.randint(1, SHINY_RATE) == 1)
    
        new_pokemon = create_pokemon(species_id=species_data['id'], is_shiny=is_shiny)

        while db.pokemon_uuid_exists(new_pokemon.pokemon_uuid):
            print(f"UUID COLLISION DETECTED: {new_pokemon.pokemon_uuid}. Generating a new one.")
            new_pokemon.pokemon_uuid = uuid.uuid4().hex[:8]

        db.add_pokemon_to_collection(user.id, new_pokemon)
        
        if is_shiny:
            await bot.reply_to(message, f"✨ Unbelievable! A SHINY <b>{new_pokemon.name}</b> has been added to your collection!", parse_mode="HTML")
        else:
            await bot.reply_to(message, f"✅ <b>{new_pokemon.name}</b> has been added to your collection!", parse_mode="HTML")

    #@bot.message_handler(commands=['main'])
    #@user_registered(bot)
    #async def main_profile_command(message):
    #    user_id = message.from_user.id
    #    user_name = message.from_user.first_name
    #    
    #    # --- THIS IS THE URL TO YOUR NEW PAGE ---
    #    # We will create 'profile.html' in your 'website' folder
    #    WEB_APP_HOST = os.getenv("WEB_APP_HOST_URL") 
    #    if not WEB_APP_HOST:
    #         await bot.reply_to(message, "The web app URL is not configured.")
    #         return
#
    #    # Use the direct URL. The web app will get the user ID
    #    # from the Telegram SDK, just like the editors do.
    #    web_app_url = f"{WEB_APP_HOST}/profile.html"
#
    #    markup = types.InlineKeyboardMarkup()
    #    markup.add(types.InlineKeyboardButton(
    #        "My Trainer Profile",
    #        web_app=WebAppInfo(url=web_app_url)
    #    ))
#
    #    await bot.reply_to(
    #        message,
    #        f"Hello, {user_name}! Click the button below to open your profile.",
    #        reply_markup=markup
    #    )

            
    @bot.message_handler(commands=['view'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def stats_command(message):
        user_id = message.from_user.id
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            reply_text = "Please specify which Pokémon you want to view!\n\n<b>Usage:</b> <code>/view &lt;pokemon name&gt;</code>"
            await bot.reply_to(message, reply_text, parse_mode="HTML")
            return
        
        query = parts[1].strip()
        
        pokemon = db.get_pokemon_from_collection(user_id, query)
        if pokemon:
            await show_pokemon_stats(bot, message, pokemon)
            return

        collection = db.get_collection(user_id)
        found_by_name = [p for p in collection if p.name.lower() == query.lower()]

        if not found_by_name:
            # --- NEW: "Did You Mean?" Logic for stats ---
            best_match = None
            min_dist = 3 

            # Create a unique list of names in the user's collection
            collection_names = list(set(p.name.lower() for p in collection))

            for name in collection_names:
                dist = levenshtein_distance(query.lower(), name)
                if dist < min_dist:
                    min_dist = dist
                    best_match = name
            
            if best_match:
                markup = types.InlineKeyboardMarkup()
                # We use the name in the callback, as there might be duplicates
                markup.row(
                    types.InlineKeyboardButton("✅ Yes", callback_data=f"stats_confirm_{best_match}"),
                    types.InlineKeyboardButton("❌ No", callback_data="suggestion_cancel")
                )
                await bot.reply_to(message, f"Did you mean <b>{best_match.capitalize()}</b>?", reply_markup=markup, parse_mode="HTML")
            else:
                await bot.reply_to(message, f"You don't have a Pokémon matching '{query}'.")
            return

        elif len(found_by_name) == 1:
            await show_pokemon_stats(bot, message, found_by_name[0])
        else:
            await show_duplicate_selection_menu(bot, message, query, found_by_name)

    @bot.message_handler(commands=['display'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def display_command(message):
        user_id = message.from_user.id
        current = db.get_display_setting(user_id)
        options = ["Level", "Nature", "Ability", "Type", "Tier", "BST"]
        text = "<b>Display Settings</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, opt in enumerate(options, 1):
            text += f" {i}. {opt}\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += f"<i>Selected: {current}</i>"
        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [types.InlineKeyboardButton(str(i), callback_data=f"set_display_{opt}") for i, opt in enumerate(options, 1)]
        markup.add(*buttons)
        await bot.reply_to(message, text, reply_markup=markup, parse_mode="HTML")

    @bot.message_handler(commands=['mycollection'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def mycollection_command(message):
        """Handles the initial /mycollection command, showing only the first page."""
        user_id = message.from_user.id
        collection = db.get_collection(user_id)
    
        if not collection:
            await bot.reply_to(message, "Your collection is empty! Add Pokémon with `/add <name>`.")
            return
        
        from bot.ui_components import format_pokemon_display_line
        display_mode = db.get_display_setting(user_id)

        page = 0
        items_per_page = 20
        sorted_collection = sorted(collection, key=lambda p: p.name)
        total_pages = -(-len(sorted_collection) // items_per_page)
        page_pokemon = sorted_collection[0:items_per_page]

        message_lines = ["<b>Your Collection</b>\n━━━━━━━━━━━━━━━━━━━━"]
        for index, p in enumerate(page_pokemon, start=1):
            display_str = format_pokemon_display_line(p, display_mode)
            message_lines.append(f" {index}. {display_str}")
    
        collection_text = "\n".join(message_lines)
        collection_text += f"\n━━━━━━━━━━━━━━━━━━━━\n<i>Display: {display_mode} | Total: {len(collection)} | Page: {page + 1}/{total_pages}</i>"

        markup = types.InlineKeyboardMarkup()
        nav_buttons = []
        if total_pages > 1:
            nav_buttons.append(types.InlineKeyboardButton("Next", callback_data=f"collection_page_{page + 1}"))
        if nav_buttons:
            markup.row(*nav_buttons)

        await bot.reply_to(message, collection_text, reply_markup=markup, parse_mode="HTML")

    @bot.message_handler(commands=['myteams'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def myteam_command(message):
        content = get_team_selection_content(message.from_user.id)
        markup = content["reply_markup"] 
    
        if markup: 
            # WEB_APP_HOST is the direct URL to the static HTML files (e.g., https://pokeclashdex.onrender.com)
            WEB_APP_HOST = os.getenv("WEB_APP_HOST_URL") 
            
            # 1. Define the DEEP LINK URL: Use the standard format to pass 'team-editor' as the destination
            WEB_APP_DEEP_LINK = f"https://t.me/{BOT_USERNAME}/{WEB_APP_LINK_NAME}?startapp=team-editor"
            
            if WEB_APP_HOST:
                button_text = "✏️ Edit Teams in Web App"
    
                if message.chat.type == 'private':
                    # Private Chat: Direct access to the team-editor.html via WebAppInfo
                    web_app_url = f"{WEB_APP_HOST}/team-editor.html"
                    web_app_button = types.InlineKeyboardButton(
                        button_text,
                        web_app=types.WebAppInfo(url=web_app_url)
                    )
                else:
                    # Group Chat: Standard URL button using the t.me deep link
                    web_app_button = types.InlineKeyboardButton(
                        button_text,
                        url=WEB_APP_DEEP_LINK # <-- This link forces the app to open and provides the destination parameter
                    )
    
                markup.row(web_app_button)
    
        await bot.reply_to(
            message, 
            content["text"], 
            reply_markup=markup,
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['viewteam'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def viewteam_command(message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        detail_target = "chat" if message.chat.type == "private" else "dm"
        showdown_detail_markup = InlineKeyboardMarkup()
        showdown_detail_markup.row(
            InlineKeyboardButton("TEAM DETAIL", callback_data=f"teamview_detail_{detail_target}_{user_id}")
        )

        team_to_view = None
        team_name = "Active Team" # Default name

        from bot.showdown_battle.service import get_showdown_service

        showdown_service = get_showdown_service()
        showdown_battle = showdown_service.active_battle_for_user(user_id) if showdown_service else None
        if showdown_battle:
            showdown_player = showdown_battle.player_for_user(user_id)
            request = showdown_player.current_request if showdown_player else None
            if showdown_player and request:
                team_to_view = build_team_from_showdown_request(request)
                team_name = f"{showdown_player.name}'s Battling Team"

        if team_to_view is None:
            raw_battles_in_chat = active_battles.get(chat_id, [])
            battles_in_chat = raw_battles_in_chat if isinstance(raw_battles_in_chat, list) else [raw_battles_in_chat]
            battle = next((b for b in battles_in_chat if b.get_player(user_id)), None)

            if battle:
                player = battle.get_player(user_id)
                team_to_view = [active_poke.pokemon for active_poke in player.team]
                team_name = f"{player.user_name}'s Battling Team"

        # If no battle was found (or user isn't a player), fall back to DB
        if team_to_view is None:
            active_team_db = db.get_active_team(user_id)
            if not active_team_db:
                await bot.reply_to(message, "You don't have an active team yet. Use `/myteams` to set one up.")
                return

            team_name = active_team_db[2]
            team_uuids = active_team_db[3] if active_team_db[3] else []
            
            collection = db.get_collection(user_id)
            pokemon_map = {p.pokemon_uuid: p for p in collection}
            team_to_view = [pokemon_map[uuid] for uuid in team_uuids if uuid in pokemon_map]

        # --- The rest of the logic is the same, but uses 'team_to_view' ---
        if not team_to_view:
            await bot.reply_to(message, f"Your team, <b>{html.escape(team_name)}</b>, is empty.", parse_mode="HTML")
            return
            
        loading_message = await bot.reply_to(message, "Analyzing your team and generating image...")

        analysis_data = analyze_team_coverage(team_to_view)
        caption = format_analysis_caption(team_name, team_to_view, analysis_data)

        image_bytes = await create_team_image(team_to_view)

        if image_bytes:
            # Use edit_message_media to replace the loading message
            await bot.edit_message_media(
                media=types.InputMediaPhoto(image_bytes, caption=caption, parse_mode="HTML"),
                chat_id=loading_message.chat.id,
                message_id=loading_message.message_id,
                reply_markup=showdown_detail_markup,
            )
        else:
            await bot.edit_message_text("Sorry, there was an error creating your team image.", chat_id=loading_message.chat.id, message_id=loading_message.message_id)
            
    @bot.message_handler(commands=['battle_stats'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def battle_stats_command(message):
        chat_id = message.chat.id
        user_id = message.from_user.id

        from bot.showdown_battle.service import get_showdown_service

        showdown_service = get_showdown_service()
        if showdown_service and showdown_service.active_battle_for_user(user_id):
            await showdown_service.on_battle_stats_command(message)
            return

        # Find the battle in this chat
        battles_in_chat = active_battles.get(chat_id, [])
        battle = next((b for b in battles_in_chat if b.get_player(user_id)), None)
        if not battle or battle.state != 'active':
            await bot.reply_to(message, "There is no active battle in this chat.")
            return

        # Find which player the user is
        player = battle.get_player(user_id)
        if not player:
            await bot.reply_to(message, "You are not a participant in this battle.")
            return
            
        # Get the player's active Pokémon
        active_pokemon = player.get_active_pokemon()
        
        # Generate and send the stats text
        stats_text = generate_battle_stats_text(active_pokemon)
        await bot.reply_to(message, stats_text, parse_mode="HTML")

#    @bot.message_handler(commands=['settings'])
#    @user_registered(bot)
#    async def settings_command(message):
#        user_id = message.from_user.id
#        # Start at page 0
#        content = get_settings_content(context='global', user_id=user_id, page=0)
#        await bot.reply_to(message, content['text'], reply_markup=content['markup'], parse_mode="HTML")

    @bot.message_handler(commands=['implemented'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def implemented_command(message):
        """Displays the implementation status tracking menu."""
        text = "<b>Implementation Checklist</b>\n\nSelect a category to view its status."
        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [
            types.InlineKeyboardButton("Moves", callback_data="impl_menu_moves"),
            types.InlineKeyboardButton("Abilities", callback_data="impl_menu_abilities"),
            types.InlineKeyboardButton("Items", callback_data="impl_menu_items")
        ]
        markup.add(*buttons)
        await bot.reply_to(message, text, reply_markup=markup, parse_mode="HTML")

    @bot.message_handler(commands=['leaderboard', 'rank'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def leaderboard_command(message):
        # Default to overall wins on page 0 when they type the command
        content = _build_leaderboard_ui(mode='overall', page=0)
        await bot.reply_to(message, content['text'], reply_markup=content['markup'], parse_mode="HTML")

    @bot.message_handler(commands=['testrankimage'])
    async def test_rank_image_command(message):
        """
        A debug command to generate a sample ranking image without a battle.
        """
        loading_msg = await bot.reply_to(message, "Generating a sample ranking summary image...")

        # --- You can change this sample data to test different ranks/names ---
        winner_name = "Cynthia"
        winner_old_elo = 1985
        winner_new_elo = 2001 # Test a rank-up to Master

        try:
            # --- THIS IS THE MODIFIED PART ---
            # Call the image generation function with only winner data
            summary_image = await create_ranking_summary_image(
                winner_name, winner_old_elo, winner_new_elo
            )
            # --- END OF MODIFICATION ---

            # Send the generated image
            if summary_image:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=summary_image,
                    caption="This is a test of the ranking summary image."
                )
            else:
                await bot.send_message(message.chat.id, "Failed to generate the image.")

        except Exception as e:
            await bot.send_message(message.chat.id, f"An error occurred: {e}")
        
        finally:
            # Clean up the "Generating..." message
            await bot.delete_message(message.chat.id, loading_msg.id)

    @bot.message_handler(commands=['trainercard'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def trainercard_command(message):
        user_id = message.from_user.id
        user_name = message.from_user.first_name

        loading_msg = await bot.reply_to(message, "⏳ Generating your trainer card...")

        stats = db.get_user_stats(user_id)
        prefs = db.get_user_card_prefs(user_id)
        
        if not stats or not prefs:
            await bot.edit_message_text("Could not retrieve your data.", chat_id=loading_msg.chat.id, message_id=loading_msg.message_id)
            return

        elo, wins, losses, _ = stats
        card_template, trainer_sprite, font_color = prefs

        card_image = await create_trainer_card_image(
            user_name, elo, wins, losses, card_template, trainer_sprite, font_color
        )

        if card_image:
            markup = types.InlineKeyboardMarkup()

            # --- START OF NEW/MODIFIED LOGIC ---
            
            # 1. Get the URLs (these are already defined at the top of your file [cite: 15, 16])
            WEB_APP_HOST = os.getenv("WEB_APP_HOST_URL") 
            
            if WEB_APP_HOST:
                # 2. Define the two different links
                
                # The link for the WebAppInfo object (direct)
                # This opens profile.html, which finds the user ID from the SDK
                direct_profile_url = f"{WEB_APP_HOST}/profile.html"
                
                # The link for the URL button (Telegram deep-link)
                # This opens the profile page for the *specific user*
                telegram_profile_url = f"https://t.me/{BOT_USERNAME}/{WEB_APP_LINK_NAME}?startapp=profile-{user_id}"

                # 3. Check chat type and add the correct button
                if message.chat.type == 'private':
                    markup.add(types.InlineKeyboardButton(
                        "👤 My Profile",
                        web_app=types.WebAppInfo(url=direct_profile_url)
                    ))
                else:
                    # In a group, show a link to their public profile
                    markup.add(types.InlineKeyboardButton(
                        "👤 View Profile",
                        url=telegram_profile_url
                    ))

            # 4. This is your existing "Edit Card" logic [cite: 87-88]
            if message.chat.type == 'private':
                markup.add(types.InlineKeyboardButton("✏️ Edit Card", callback_data=f"tc_main_{user_id}"))
            
            # --- END OF MODIFIED LOGIC ---
            
            media = types.InputMediaPhoto(
                card_image, 
                caption=f"<b>{user_name}'s Trainer Card</b>", 
                parse_mode="HTML"
            )

            await bot.edit_message_media(
                media=media,
                chat_id=loading_msg.chat.id,
                message_id=loading_msg.message_id,
                reply_markup=markup
            )
        else:
            await bot.edit_message_text("Error: Could not generate your trainer card.", chat_id=loading_msg.chat.id, message_id=loading_msg.message_id)

    @bot.message_handler(commands=['card'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def card_command(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip().lower() != "new":
            await bot.reply_to(message, "Usage: <code>/card</code>", parse_mode="HTML")
            return

        web_app_host = (os.getenv("WEB_APP_HOST_URL") or "").strip().strip('"').rstrip("/")
        if not web_app_host:
            await bot.reply_to(message, "The web app URL is not configured, so trainer card previews are unavailable.")
            return

        user_id = message.from_user.id
        user_name = html.escape(message.from_user.first_name or "Trainer")
        card_image_url = f"{web_app_host}/api/user/{user_id}/trainer-card.png"
        link_preview = f'<a href="{html.escape(card_image_url)}">&#8203;</a>'
        link_options = LinkPreviewOptions(
            is_disabled=False,
            url=card_image_url,
            prefer_large_media=True,
            show_above_text=True,
        )
        await bot.reply_to(
            message,
            f"{link_preview}<b>{user_name}'s Trainer Card</b>",
            parse_mode="HTML",
            link_preview_options=link_options,
        )

    @bot.message_handler(commands=['bag'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def bag_command(message):
        """Displays the user's items and shop prices using a link preview."""
        user_id = message.from_user.id
        user_name = message.from_user.first_name
    
        # Fetch the real item counts from the database
        shiny_passes = db.get_shiny_pass_count(user_id)
        legendary_passes = db.get_legendary_pass_count(user_id)
        clash_coins = db.get_clash_coin_count(user_id)
    
        # URL for the bag image preview
        bag_image_url = "https://files.catbox.moe/kfx389.jpg"
        link_preview = f'<a href="{bag_image_url}">&#8203;</a>'
    
        caption = (
            f"{link_preview}"
            f"<b>🎒 {user_name}'s Bag</b>\n\n"
            f"✨ <b>Shiny Pass:</b> {shiny_passes}\n"
            f"🌟 <b>Legendary Pass:</b> {legendary_passes}\n"
            f"💰 <b>Clash Coins:</b> {clash_coins}\n\n"
            f"<b>Shop</b>\n"
            f"<code>/buy pass 1</code> - {SHINY_PASS_PRICE} coins\n"
            f"<code>/buy legendarypass 1</code> - {LEGENDARY_PASS_PRICE} coins"
        )
    
        # Set up link preview options
        link_options = LinkPreviewOptions(
            is_disabled=False,
            url=bag_image_url,
            prefer_large_media=True,
            show_above_text=True
        )
        
        await bot.reply_to(
            message,
            caption,
            parse_mode="HTML",
            link_preview_options=link_options
        )

    @bot.message_handler(commands=['admin'])
    @admin_only(bot)
    async def admin_help_command(message):
        await bot.reply_to(
            message,
            (
                "<b>Admin Commands</b>\n\n"
                "<code>/admin</code> - show this help\n"
                "<code>/adminstats</code>\n"
                "<code>/adminfind &lt;name_or_id&gt;</code>\n"
                "<code>/adminuser &lt;user_id&gt;</code>\n"
                "<code>/adminset &lt;user_id&gt; coins=500 passes=1 legendarypasses=1 slots=30 ban=off battleban=on</code>\n"
                "<code>/adminreset &lt;user_id&gt; confirm</code>\n"
                "<code>/redeemcreate cc-500 sp-1 lp-1 u-5</code>\n"
                "<code>/broadcast</code> or <code>/bradcast</code> as a reply to the source message\n"
                "<code>/redeem &lt;code&gt;</code> for users"
            ),
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['adminstats'])
    @admin_only(bot)
    async def admin_stats_command(message):
        stats = db.get_admin_stats()
        stats['active_battles'] = sum(len(battles) for battles in active_battles.values())

        await bot.reply_to(
            message,
            (
                "<b>Bot Statistics</b>\n\n"
                f"👥 Users: <b>{stats['total_users']}</b>\n"
                f"🆕 New 24h: <b>{stats['new_users_24h']}</b>\n"
                f"⚔️ Active Battles: <b>{stats['active_battles']}</b>\n"
                f"📦 Total Pokémon: <b>{stats['total_pokemon']}</b>\n"
                f"🧩 Total Teams: <b>{stats['total_teams']}</b>\n"
                f"🏟️ Total Battles: <b>{stats['total_battles']}</b>\n"
                f"💰 Total Coins: <b>{stats['total_coins']}</b>\n"
                f"✨ Total Shiny Passes: <b>{stats['total_passes']}</b>\n"
                f"🌟 Total Legendary Passes: <b>{stats['total_legendary_passes']}</b>"
            ),
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['adminfind'])
    @admin_only(bot)
    async def admin_find_command(message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await bot.reply_to(message, "Usage: <code>/adminfind &lt;name_or_id&gt;</code>", parse_mode="HTML")
            return

        users = db.search_users(parts[1].strip(), limit=10)
        if not users:
            await bot.reply_to(message, "No users found.")
            return

        lines = ["<b>Search Results</b>"]
        for user in users:
            flags = []
            if user["is_banned"]:
                flags.append("FULL BAN")
            if user["is_battle_banned"]:
                flags.append("BATTLE BAN")
            suffix = f" [{' | '.join(flags)}]" if flags else ""
            lines.append(
                f"• {html.escape(user['first_name'] or 'Unknown')} "
                f"(<code>{user['user_id']}</code>){suffix}"
            )

        await bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

    @bot.message_handler(commands=['adminuser'])
    @admin_only(bot)
    async def admin_user_command(message):
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await bot.reply_to(message, "Usage: <code>/adminuser &lt;user_id&gt;</code>", parse_mode="HTML")
            return

        user_details = db.get_user_admin_details(int(parts[1]))
        if not user_details:
            await bot.reply_to(message, "User not found.")
            return

        await bot.reply_to(message, _build_admin_user_summary(user_details), parse_mode="HTML")

    @bot.message_handler(commands=['adminset'])
    @admin_only(bot)
    async def admin_set_command(message):
        parts = message.text.split()
        if len(parts) < 3 or not parts[1].isdigit():
            await bot.reply_to(
                message,
                "Usage: <code>/adminset &lt;user_id&gt; coins=500 passes=1 legendarypasses=1 slots=30 ban=off battleban=on</code>",
                parse_mode="HTML"
            )
            return

        user_id = int(parts[1])
        if not db.get_user_by_id(user_id):
            await bot.reply_to(message, "User not found.")
            return

        updates = {}
        errors = []

        for token in parts[2:]:
            if "=" not in token:
                errors.append(token)
                continue

            key, raw_value = token.split("=", 1)
            key = key.strip().lower()
            raw_value = raw_value.strip()

            if key in {"coins", "passes", "legendarypasses", "slots"}:
                try:
                    parsed_value = int(raw_value)
                except ValueError:
                    errors.append(token)
                    continue

                if key == "coins":
                    updates["add_coins"] = parsed_value
                elif key == "passes":
                    updates["add_passes"] = parsed_value
                elif key == "legendarypasses":
                    updates["add_legendary_passes"] = parsed_value
                elif key == "slots":
                    if parsed_value < 1:
                        errors.append(token)
                        continue
                    updates["set_slots"] = parsed_value
                continue

            if key in {"ban", "battleban"}:
                parsed_bool = _parse_bool_flag(raw_value)
                if parsed_bool is None:
                    errors.append(token)
                    continue
                if key == "ban":
                    updates["is_banned"] = parsed_bool
                else:
                    updates["is_battle_banned"] = parsed_bool
                continue

            errors.append(token)

        if errors:
            await bot.reply_to(
                message,
                f"Invalid adminset arguments: <code>{html.escape(', '.join(errors))}</code>",
                parse_mode="HTML"
            )
            return

        if not updates:
            await bot.reply_to(message, "No valid updates supplied.")
            return

        db.update_user_admin(user_id, updates)
        user_details = db.get_user_admin_details(user_id)
        await bot.reply_to(
            message,
            f"✅ Updated user successfully.\n\n{_build_admin_user_summary(user_details)}",
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['adminreset'])
    @admin_only(bot)
    async def admin_reset_command(message):
        parts = message.text.split()
        if len(parts) != 3 or not parts[1].isdigit() or parts[2].lower() != "confirm":
            await bot.reply_to(message, "Usage: <code>/adminreset &lt;user_id&gt; confirm</code>", parse_mode="HTML")
            return

        user_id = int(parts[1])
        if not db.get_user_by_id(user_id):
            await bot.reply_to(message, "User not found.")
            return

        db.admin_reset_user(user_id)
        await bot.reply_to(message, f"✅ Reset user <code>{user_id}</code> to default progress.", parse_mode="HTML")

    @bot.message_handler(commands=['redeemcreate'])
    @admin_only(bot)
    async def redeem_create_command(message):
        raw_args = message.text.split(maxsplit=1)
        if len(raw_args) < 2:
            await bot.reply_to(
                message,
                "Usage: <code>/redeemcreate cc-500 sp-1 lp-1 u-5</code>",
                parse_mode="HTML"
            )
            return

        tokens = raw_args[1].replace(",", " ").split()
        clash_coins = 0
        shiny_passes = 0
        legendary_passes = 0
        uses = 1
        invalid = []

        for token in tokens:
            if "-" not in token:
                invalid.append(token)
                continue
            key, value = token.split("-", 1)
            key = key.strip().lower()
            try:
                amount = int(value.strip())
            except ValueError:
                invalid.append(token)
                continue

            if amount < 0:
                invalid.append(token)
                continue

            if key in {"cc", "coins"}:
                clash_coins = amount
            elif key in {"sp", "pass", "passes"}:
                shiny_passes = amount
            elif key in {"lp", "legendarypass", "legendarypasses"}:
                legendary_passes = amount
            elif key in {"u", "uses"}:
                uses = amount
            else:
                invalid.append(token)

        if invalid:
            await bot.reply_to(
                message,
                f"Invalid redeemcreate tokens: <code>{html.escape(', '.join(invalid))}</code>",
                parse_mode="HTML"
            )
            return

        if uses < 1:
            await bot.reply_to(message, "Uses must be at least 1.")
            return

        try:
            redeem_data = db.create_redeem_code(
                reward_clash_coins=clash_coins,
                reward_shiny_passes=shiny_passes,
                reward_legendary_passes=legendary_passes,
                max_uses=uses,
                created_by=message.from_user.id,
            )
        except ValueError as exc:
            await bot.reply_to(message, str(exc))
            return

        await bot.reply_to(
            message,
            (
                f"✅ Redeem code created: <code>{redeem_data['code']}</code>\n"
                f"Uses: <b>{redeem_data['max_uses']}</b>\n\n"
                f"{_format_redeem_rewards(clash_coins, shiny_passes, legendary_passes)}"
            ),
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['redeem'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def redeem_command(message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await bot.reply_to(message, "Usage: <code>/redeem &lt;code&gt;</code>", parse_mode="HTML")
            return

        result = db.claim_redeem_code(message.from_user.id, parts[1])
        if not result["ok"]:
            error_messages = {
                "invalid_code": "That redeem code does not exist.",
                "no_uses_left": "That redeem code has no uses left.",
                "already_claimed": "You already claimed that redeem code.",
            }
            await bot.reply_to(message, error_messages.get(result["error"], "Could not claim that code."))
            return

        await bot.reply_to(
            message,
            (
                f"✅ Redeemed <code>{result['code']}</code>\n\n"
                f"{_format_redeem_rewards(result['reward_clash_coins'], result['reward_shiny_passes'], result['reward_legendary_passes'])}\n\n"
                f"Remaining uses: <b>{result['remaining_uses']}</b>"
            ),
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['broadcast', 'bradcast'])
    @admin_only(bot)
    async def broadcast_command(message):
        if not message.reply_to_message:
            await bot.reply_to(
                message,
                "Reply to the message you want to send, then use <code>/broadcast</code> or <code>/bradcast</code>.",
                parse_mode="HTML"
            )
            return

        user_ids = db.get_all_user_ids()
        sent_count = 0
        fail_count = 0

        status_message = await bot.reply_to(message, "Broadcast started...")

        for user_id in user_ids:
            try:
                await bot.copy_message(
                    user_id,
                    message.chat.id,
                    message.reply_to_message.message_id
                )
                sent_count += 1
            except Exception:
                fail_count += 1
            await asyncio.sleep(0.1)

        await bot.edit_message_text(
            f"Broadcast complete.\nSent: <b>{sent_count}</b>\nFailed: <b>{fail_count}</b>",
            chat_id=status_message.chat.id,
            message_id=status_message.message_id,
            parse_mode="HTML"
        )

    @bot.message_handler(commands=['setfavorite'])
    @user_registered(bot)
    @user_not_banned(bot)
    async def set_favorite_command(message):
        user_id = message.from_user.id
        parts = message.text.split(maxsplit=1)
    
        if len(parts) < 2:
            await bot.reply_to(message, "Please specify a Pokémon from your collection.\n<b>Usage:</b> <code>/setfavorite <name or uuid></code>", parse_mode="HTML")
            return
    
        query = parts[1].strip()
    
        # Check if this pokemon is in their collection [cite: 1089]
        pokemon = db.get_pokemon_from_collection(user_id, query)
    
        if not pokemon:
            # Try searching by name if UUID fails
            collection = db.get_collection(user_id)
            found_by_name = [p for p in collection if p.name.lower() == query.lower()]
            if len(found_by_name) == 1:
                pokemon = found_by_name[0]
            elif len(found_by_name) > 1:
                await bot.reply_to(message, f"You have multiple Pokémon named '{query}'. Please use the Pokémon's unique ID (from /view) to set it as favorite.")
                return
    
        if not pokemon:
            await bot.reply_to(message, f"I couldn't find a Pokémon named '{query}' in your collection.")
            return
    
        # Call your new database function
        db.set_user_favorite_pokemon(user_id, pokemon.pokemon_uuid)
        await bot.reply_to(message, f"<b>{pokemon.name}</b> is now your favorite Pokémon and will be featured on your profile!", parse_mode="HTML")
    
async def show_pokemon_stats(bot, message, pokemon):
    """
    MODIFIED: Smartly searches for shiny sprites first if the Pokémon is shiny,
    with a fallback to regular sprites if the shiny version is not found.
    """
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
    
    # This logic to generate potential filenames remains the same
    ids_to_try = []
    formatted_name = pokemon.name.lower().replace(" ", "-").replace("’", "").replace(".", "")
    ids_to_try.append(formatted_name)

    simplified_name = formatted_name.replace("-dusk-mane", "-duskmane").replace("-dawn-wings", "-dawnwings")
    ids_to_try.append(simplified_name)

    if "-mega-" in formatted_name:
        abbreviated_mega_name = formatted_name.replace("-mega-", "-mega")
        ids_to_try.append(abbreviated_mega_name)
    ids_to_try.append(pokemon.id)
    base_name = formatted_name.split('-')[0]
    ids_to_try.append(base_name)
    ids_to_try = list(dict.fromkeys(ids_to_try))

    image_path_to_use = None

    # --- THIS IS THE NEW LOGIC BLOCK ---

    # 1. If the Pokémon is shiny, search the shiny folders first.
    if pokemon.is_shiny:
        for image_id in ids_to_try:
            filename = f"{image_id}.png"
            # Prioritize high-quality shiny artwork
            shiny_artwork_path = os.path.join(ASSETS_DIR, 'sprite', 'image-shiny', filename)
            if os.path.exists(shiny_artwork_path):
                image_path_to_use = shiny_artwork_path
                break 
            # Fallback to shiny pixel sprite
            shiny_sprite_path = os.path.join(ASSETS_DIR, 'sprite', 'sprites-gen5-shiny', filename)
            if os.path.exists(shiny_sprite_path):
                image_path_to_use = shiny_sprite_path
                break

    # 2. If no shiny image was found (or if the Pokémon isn't shiny), search the regular folders.
    if not image_path_to_use:
        for image_id in ids_to_try:
            filename = f"{image_id}.png"
            # Prioritize regular artwork
            artwork_path = os.path.join(ASSETS_DIR, 'sprite', 'image', filename)
            if os.path.exists(artwork_path):
                image_path_to_use = artwork_path
                break
            # Fallback to regular pixel sprite
            sprite_path = os.path.join(ASSETS_DIR, 'sprite', 'sprites-gen5', filename)
            if os.path.exists(sprite_path):
                image_path_to_use = sprite_path
                break
    # --- END OF NEW LOGIC BLOCK ---

    content = get_stats_message_content(pokemon, message.chat.type, message.from_user.id)

    if image_path_to_use:
        try:
            with open(image_path_to_use, 'rb') as photo:
                await bot.send_photo(
                    message.chat.id,
                    photo=photo,
                    caption=content["caption"],
                    reply_markup=content["reply_markup"],
                    parse_mode="HTML",
                    reply_to_message_id=message.message_id
                )
        except Exception as e:
            print(f"ERROR: Could not send photo from path {image_path_to_use}. Reason: {e}")
            await bot.reply_to(message, content["caption"], reply_markup=content["reply_markup"], parse_mode="HTML")
    else:
        # This part runs if no image (shiny or regular) could be found at all
        print(f"CRITICAL: All images missing for Pokémon '{pokemon.name}'. Tried IDs: {ids_to_try}")
        await bot.reply_to(
            message,
            f"Could not find any local images for {pokemon.name}.\n\n{content['caption']}",
            reply_markup=content["reply_markup"],
            parse_mode="HTML"
        )


async def show_duplicate_selection_menu(bot, message, query_name, pokemon_list, page=0):
    """
    Displays a paginated menu for selecting from duplicate Pokémon.
    """
    items_per_page = 6
    start = page * items_per_page
    end = start + items_per_page

    total_pages = -(-len(pokemon_list) // items_per_page)

    selection_text = f"You have multiple Pokémon named <b>{query_name.capitalize()}</b>. Please choose one:\n"
    selection_text += f"<i>(Page {page + 1}/{total_pages})</i>\n\n"

    page_pokemon = pokemon_list[start:end]
    for i, p in enumerate(page_pokemon):
        list_number = start + i + 1
        # --- <<< THIS IS THE MODIFIED LINE >>> ---
        item_name = p.item or 'None' # Get item name or 'None'
        # Added p.nature after p.level
        selection_text += f"<i>{list_number}. Lv {p.level}, {p.nature}, {p.ability}, {item_name}</i>\n"
        # --- <<< END OF MODIFICATION >>> ---

    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for i, p in enumerate(page_pokemon):
        button_number = str(start + i + 1)
        buttons.append(types.InlineKeyboardButton(
            button_number,
            callback_data=f"p_select_{p.pokemon_uuid}"
        ))
    markup.add(*buttons)

    nav_buttons = []
    # Use a unique query_name in the callback to avoid conflicts
    unique_query_key = f"{query_name}_{message.message_id}"
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"p_dupe_{unique_query_key}_{page-1}"))
    if end < len(pokemon_list):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"p_dupe_{unique_query_key}_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    await bot.reply_to(message, selection_text, reply_markup=markup, parse_mode="HTML")

def _get_start_menu_content(user_first_name: str):
    """Generates the text and keyboard for the main start menu."""
    image_url = "https://ar-hosting.pages.dev/1761312150998.mp4"
    link_preview = f'<a href="{image_url}">&#8203;</a>'
    
    text = (
        f"{link_preview}"
        f"<b>Welcome, Trainer {user_first_name}!</b> ⚔️\n\n"
        "This bot is built for battling, inspired by Pokémon Showdown. <b>Forget the grind—jump straight into the action!</b>\n\n"
        "With over <b>90% of move effects</b> and <b>60% of abilities</b> implemented, you can build competitively viable teams right away.\n\n"
        "<b>Quick PvP:</b> reply with <code>/challenge</code> or <code>/doubles</code> to another user, use <code>/ffa</code> in a group for a free-for-all lobby, use <code>/battle_stats</code> for live active-mon stats, and <code>/exit</code> to close your current PvP session.\n\n"
        "Select a feature below to learn more!"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("📸 Collection", callback_data="start_menu_collection"),
        types.InlineKeyboardButton("🏆 Team Building", callback_data="start_menu_teams"),
        types.InlineKeyboardButton("⚔️ Battling", callback_data="start_menu_battle"),
        types.InlineKeyboardButton("🎨 Customization", callback_data="start_menu_custom")
    ]
    markup.add(*buttons)

    return {"text": text, "reply_markup": markup}

def _build_leaderboard_ui(mode='overall', page=0):
    limit = 10
    offset = page * limit
    # Fetch limit + 1 to easily check if there is a "Next" page
    leaderboard_data = db.get_leaderboard(mode=mode, limit=limit + 1, offset=offset) 
    
    has_next = len(leaderboard_data) > limit
    page_data = leaderboard_data[:limit]
    
    if not page_data and page == 0:
        return {"text": "The leaderboard is currently empty! Play at least one match to get ranked.", "markup": None}
        
    if mode == 'ranked':
        title = "🏆 <b>Top Players (by Elo)</b> 🏆"
    else:
        title = "🌍 <b>Top Players (Overall Wins)</b> 🌍"
        
    reply_text = f"{title}\n\n"
    for i, (name, elo, wins, losses, draws) in enumerate(page_data, start=offset + 1):
        reply_text += f"<b>{i}.</b> {html.escape(name)} - <code>{wins}W-{losses}L-{draws}D</code> <i>(Elo: {elo})</i>\n"
        
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"lb_page_{mode}_{page-1}"))
    if has_next:
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"lb_page_{mode}_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)
        
    # Toggle mode button
    if mode == 'overall':
        markup.row(types.InlineKeyboardButton("🏆 View Ranked Leaderboard", callback_data="lb_mode_ranked_0"))
    else:
        markup.row(types.InlineKeyboardButton("🌍 View Overall Leaderboard", callback_data="lb_mode_overall_0"))
        
    return {"text": reply_text, "markup": markup}
