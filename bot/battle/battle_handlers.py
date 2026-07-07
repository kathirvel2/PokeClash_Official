import os
import random
import asyncio
import traceback
import html
from PIL import Image
import io
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from telebot.types import LinkPreviewOptions
import math
import re
from bot.mechanics.team import Stats # Add Stats
from bot.mechanics.moves_loader import SPECIES_BY_ID # Add SPECIES_BY_ID
from bot.mechanics.db import db
from bot.mechanics.team import Pokemon
from bot.battle.battle_engine import Battle, BattlePlayer
from bot.battle.battle_ui import generate_battle_caption, generate_battle_keyboard, generate_battle_image
from bot.battle.battle_logic import execute_move, get_move_order
from bot.mechanics.moves_loader import MOVE_BY_ID
from typing import Dict, Tuple, Any
from bot.battle.battle_ui import generate_battle_caption, generate_battle_keyboard, generate_battle_image, generate_switch_keyboard
from bot.battle.battle_engine import Battle, BattlePlayer, ActivePokemon, active_battles 
from bot.battle.battle_utils import get_actual_stats # NEW
from bot.battle.move_effects.status import check_can_move, apply_status
from bot.battle.field_effects import terrain as terrain_logic
from bot.battle.field_effects import hazards as hazard_logic
from bot.battle.modes import turn_based_handler, showdown_handler
from telebot.asyncio_helper import ApiTelegramException
from bot.battle.battle_utils import find_best_sprite_path
from bot.battle.dynamax.dynamax_logic import execute_dynamax
from bot.battle.dynamax.dynamax_ui import prime_dynamax_buttons
from bot.battle.dynamax.dynamax_logic import revert_dynamax
from bot.battle.item_effects import item_logic
from bot.mechanics.ranking import calculate_elo_change
from bot.image_generation.ranking_image import create_ranking_summary_image
from bot.battle.ability_effects import trigger_on_switch_in_abilities
from bot.ui_components import get_settings_content
from bot.handlers.decorators import user_not_banned
import asyncio
from datetime import datetime, timedelta
from bot.randombattle.gen1 import gen1_random_team
from bot.randombattle.gen2 import gen2_random_team
from bot.randombattle.gen3 import gen3_random_team
from bot.randombattle.gen4 import gen4_random_team
from bot.randombattle.gen5 import gen5_random_team
from bot.randombattle.gen6 import gen6_random_team
from bot.randombattle.gen7 import gen7_random_team
from bot.randombattle.gen8 import gen8_random_team
from bot.battle import ability_effects
from bot.battle.ability_effects.form_change_logic import check_for_form_change
from bot.battle.ability_effects import trigger_on_faint
from bot.battle.ability_effects import is_weather_suppressed
from bot.battle.z_move_data import get_z_move_details, Z_CRYSTAL_TYPE_MAP, SIGNATURE_Z_MOVES, TYPE_TO_Z_MOVE
from bot.mechanics.item_data import ITEM_ID_BY_NAME
from bot.handlers.handler_utils import CallbackRateLimiter

pending_challenges: Dict[int, Dict[str, Any]] = {}
battle_callback_limiter = CallbackRateLimiter()


def legacy_active_battle_for_user(user_id: int) -> Battle | None:
    for raw_chat_battles in active_battles.values():
        chat_battles = raw_chat_battles if isinstance(raw_chat_battles, list) else [raw_chat_battles]
        for battle in chat_battles:
            if user_id in [battle.player1.user_id, battle.player2.user_id]:
                return battle
    return None


def legacy_pending_challenge_for_user(user_id: int) -> Dict[str, Any] | None:
    for challenge in pending_challenges.values():
        if user_id in [challenge.get('challenger_id'), challenge.get('opponent_id')]:
            return challenge
    return None


def legacy_pvp_lock_reason(user_id: int) -> str | None:
    if legacy_active_battle_for_user(user_id) is not None:
        return "You are already in another PvP battle."
    if legacy_pending_challenge_for_user(user_id) is not None:
        return "You already have a pending PvP challenge."
    return None

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')

LEGENDARY_TIERS = ["Uber", "AG"]
LEGENDARY_POKEMON_IDS = {
    s['id'] for s in SPECIES_BY_ID.values() if s.get('tier') in LEGENDARY_TIERS
}
# --- THIS IS THE FIX ---
# Define clear sets for each category based on the tags you found.
RESTRICTED_LEGENDARY_IDS = {s['id'] for s in SPECIES_BY_ID.values() if 'Restricted Legendary' in s.get('tags', [])}
SUB_LEGENDARY_IDS = {s['id'] for s in SPECIES_BY_ID.values() if 'Sub-Legendary' in s.get('tags', [])}
MYTHICAL_IDS = {s['id'] for s in SPECIES_BY_ID.values() if 'Mythical' in s.get('tags', [])}
ULTRA_BEAST_IDS = {s['id'] for s in SPECIES_BY_ID.values() if 'Ultra Beast' in s.get('tags', [])}

# Combine sets for easier checking
ALL_SPECIAL_IDS = RESTRICTED_LEGENDARY_IDS | SUB_LEGENDARY_IDS | MYTHICAL_IDS | ULTRA_BEAST_IDS
ALL_LEGENDARY_IDS = RESTRICTED_LEGENDARY_IDS | SUB_LEGENDARY_IDS
# --- END OF FIX ---

async def validate_player_for_battle(user_id: int, user_first_name: str) -> (bool, str):
    """
    Validates if a player is ready for battle.

    Returns:
        A tuple containing a boolean (True if valid) and a reason string.
    """
    # 1. Check if the user has started the bot
    if not db.get_user_by_id(user_id):
        return False, f"❌ {user_first_name} has not started the bot yet. They need to send /start to me in a private message first."

    # 2. Check for an active team
    active_team = db.get_active_team(user_id)
    if not active_team:
        return False, f"❌ {user_first_name} does not have an active team selected. They can set one with /myteam."

    team_uuids = active_team[3] if active_team[3] else []
    
    # 3. Check if the active team has Pokémon
    if not team_uuids:
        return False, f"❌ {user_first_name}'s active team is empty."

    # 4. Check if every Pokémon on the team has at least one move
    collection = db.get_collection(user_id)
    pokemon_map = {p.pokemon_uuid: p for p in collection}
    team_pokemon = [pokemon_map[uuid] for uuid in team_uuids if uuid in pokemon_map]

    for pokemon in team_pokemon:
        if not pokemon.moves:
            return False, f"❌ {user_first_name}'s Pokémon, {pokemon.name}, does not have any moves."

    ban_status = db.get_user_ban_status(user_id)
    if ban_status.get('is_banned', False):
        return False, f"❌ {user_first_name} is currently banned from the bot."
    if ban_status.get('is_battle_banned', False):
        return False, f"❌ {user_first_name} is currently banned from battling."

    return True, "Player is ready for battle."

def _generate_challenge_text(settings: Dict, challenger_name: str, opponent_name: str) -> str:
    """Generates the text, showing the active mode and any non-standard rules."""

    preview_url = "https://ar-hosting.pages.dev/1761312150998.mp4"

    generation = settings.get('random_battle_generation')
    special_mode = settings.get('special_mode') 

    SPECIAL_MODE_DISPLAY_NAMES = {
        "restricted_only": "Restricted Legendary Only",
        "sub_legendary_only": "Sub-Legendary Only",
        "ultra_beast_only": "Ultra Beast Only"
    }

    # Determine the main mode text
    if generation:
        mode_text = f"<b>Mode:</b> Gen {generation} Random Battle"
    elif special_mode:
        display_name = SPECIAL_MODE_DISPLAY_NAMES.get(special_mode, special_mode.replace('_', ' ').title())
        mode_text = f"<b>Mode:</b> {display_name}"
    elif settings.get('legendary_mode'):
        mode_text = "<b>Mode:</b> Legendary Only"
    elif settings.get('non_legendary_mode'):
        mode_text = "<b>Mode:</b> Non-Legendary"
    else:
        mode_text = "<b>Mode:</b> Standard Battle"

    # --- THIS IS THE NEW LOGIC BLOCK ---
    
    rules_to_display = []
    
    # 1. Always show if the match is Ranked.
    if settings.get('is_ranked'):
        rules_to_display.append("<code>Ranked Match:  ✅ Enabled </code>")
        
    # 2. Define the standard defaults for other rules.
    STANDARD_RULES = {
        'mega_enabled': True,
        'gmax_enabled': True,
        'sleep_clause_enabled': True
    }
    
    # 3. Check if any current setting deviates from the standard default.
    for key, standard_value in STANDARD_RULES.items():
        current_value = settings.get(key, standard_value)
        if current_value != standard_value:
            # Only show the rule if it's NOT the default.
            rule_name = key.replace('_', ' ').title().replace('Gmax', 'Dynamax')
            status = "✅ Enabled" if current_value else "❌ Disabled"
            # Use formatting to align the text nicely
            rules_to_display.append(f"<code>{rule_name:<18}: {status}</code>")

    # 4. Construct the final rules text.
    rules_text = mode_text
    if rules_to_display:
        rules_text += "\n<b><u>Options:</u></b>\n" + "\n".join(rules_to_display)
        
    # --- END OF NEW LOGIC BLOCK ---

    text = (
        f"⚔️ <b>A Battle Challenge Has Been Issued!</b> ⚔️\n\n"
        f"<pre>Challenger: {challenger_name}</pre>\n"
        f"<pre>Opponent:  {opponent_name}</pre>\n\n"
        f"{rules_text}\n\n"
        f"<b>{opponent_name}</b>, do you accept the challenge?"
    )

    return {"text": text, "preview_url": preview_url}

def _generate_challenge_keyboard(challenge_id: int, challenger_id: int, opponent_id: int) -> types.InlineKeyboardMarkup:
    """Generates the main keyboard for the challenge screen."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("⚙️ Settings", callback_data=f"b_ch_settings_{challenge_id}_{challenger_id}"),
        types.InlineKeyboardButton("✅ Challenge", callback_data=f"b_ch_accept_{challenge_id}_{opponent_id}")
    )
    markup.row(types.InlineKeyboardButton("❌ Decline", callback_data=f"b_ch_decline_{challenge_id}"))
    return markup

def _generate_settings_keyboard(challenge_id: int, settings: Dict, challenger_id: int) -> types.InlineKeyboardMarkup:
    """Generates the keyboard for the settings configuration screen."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    mega_text = "Mega: ✅ Enabled" if settings['mega_enabled'] else "Mega: ❌ Disabled"
    gmax_text = "Dynamax: ✅ Enabled" if settings['gmax_enabled'] else "Dynamax: ❌ Disabled"
    ranked_text = "Ranked: ✅ Enabled" if settings['is_ranked'] else "Ranked: ❌ Disabled"
    sleep_clause_text = "Sleep Clause: ✅ Enabled" if settings['sleep_clause_enabled'] else "Sleep Clause: ❌ Disabled"

    markup.add(
        types.InlineKeyboardButton(mega_text, callback_data=f"b_ch_toggle_{challenge_id}_mega_{challenger_id}"),
        types.InlineKeyboardButton(gmax_text, callback_data=f"b_ch_toggle_{challenge_id}_gmax_{challenger_id}")
    )
    markup.add(
        types.InlineKeyboardButton(ranked_text, callback_data=f"b_ch_toggle_{challenge_id}_ranked_{challenger_id}"),
        types.InlineKeyboardButton(sleep_clause_text, callback_data=f"b_ch_toggle_{challenge_id}_sleep_{challenger_id}")
    )
    markup.row(types.InlineKeyboardButton("✅ Done", callback_data=f"b_ch_main_{challenge_id}_{challenger_id}"))
    return markup

async def execute_item_form_change(bot: AsyncTeleBot, battle: Battle, player: 'BattlePlayer'):
    """Performs an item-based form change (Arceus/Silvally) and sends notifications."""
    active_pokemon = player.get_active_pokemon()
    
    base_species_info = SPECIES_BY_ID.get(active_pokemon.pokemon.id, {})
    base_species = base_species_info.get("baseSpecies", active_pokemon.pokemon.name)
    
    target_form_id = None
    for s_id, s_data in SPECIES_BY_ID.items():
        required_items = s_data.get("requiredItems")
        if s_data.get("baseSpecies") == base_species and isinstance(required_items, list) and active_pokemon.pokemon.item in required_items:
            target_form_id = s_id
            break
            
    if not target_form_id:
        return "" # Should not happen if can_item_form_change passed

    new_form_data = SPECIES_BY_ID[target_form_id]
    
    caption = f"The <b>{active_pokemon.pokemon.item}</b> is reacting with {active_pokemon.pokemon.name}!"

    # --- NEW: Send the "Show-off" Image ---
    # Create a temporary Pokemon object just to find the artwork path
    temp_form_pokemon = Pokemon(id=new_form_data['id'], name=new_form_data['name'], level=100, types=[], base_stats=None, ivs=None, evs=None, nature="", ability="", weight=0, item=None, moves=[], current_hp=1, max_hp=1, status=None, boosts={}, volatiles={}, is_shiny=active_pokemon.pokemon.is_shiny)
    artwork_path = find_best_sprite_path(temp_form_pokemon, 'image')

    if artwork_path and os.path.exists(artwork_path):
        with open(artwork_path, 'rb') as photo:
            await bot.send_photo(
                chat_id=battle.chat_id,
                photo=photo,
                caption=caption,
                parse_mode="HTML",
                reply_to_message_id=battle.message_id
            )
    else:
        # Fallback to a text message if image is not found
        await bot.send_message(battle.chat_id, caption, parse_mode="HTML")
    # --- END OF NEW LOGIC ---
    
    # Transform the actual Pokémon object
    active_pokemon.pokemon.id = new_form_data['id']
    active_pokemon.pokemon.name = new_form_data['name']
    active_pokemon.pokemon.types = new_form_data['types']
    
    new_base_stats_data = new_form_data["baseStats"].copy()
    if 'def' in new_base_stats_data:
        new_base_stats_data['def_'] = new_base_stats_data.pop('def')
    active_pokemon.pokemon.base_stats = Stats(**new_base_stats_data)
    
    old_max_hp = active_pokemon.actual_stats['hp']
    active_pokemon.actual_stats = get_actual_stats(active_pokemon.pokemon)
    hp_ratio = active_pokemon.current_hp / old_max_hp
    active_pokemon.current_hp = math.ceil(active_pokemon.actual_stats['hp'] * hp_ratio)

    await update_battle_ui(bot, battle, update_image=True)
    await asyncio.sleep(2) # Pause to let the user see the change

    return f"{active_pokemon.pokemon.name} became the {new_form_data['types'][0]} type!"
    
# --- NEW HELPER FUNCTIONS FOR SEQUENTIAL FLOW ---
GMAX_SYMBOL_PATH = os.path.join(ASSETS_DIR, 'gmax_symbol.png') # Adjust filename if needed

async def execute_dynamax_transformation(bot: AsyncTeleBot, battle: Battle, player: 'BattlePlayer'):
    """Performs the Dynamax transformation and sends a show-off image with a G-Max symbol."""
    # 1. Perform the core logic using the original, working function. This is UNTOUCHED.
    log_msg, gmax_species_id = execute_dynamax(player, battle)
    active_pokemon = player.get_active_pokemon() # This is now the transformed Pokémon

    # 2. Find the high-quality artwork. This is UNTOUCHED.
    art_pokemon_id = gmax_species_id or active_pokemon.pokemon.id
    temp_art_pokemon = Pokemon(id=art_pokemon_id, name=active_pokemon.pokemon.name, level=100, types=[], base_stats=None, ivs=None, evs=None, nature="", ability="", weight=0, item=None, moves=[], current_hp=1, max_hp=1, status=None, boosts={}, volatiles={}, is_shiny=active_pokemon.pokemon.is_shiny)
    artwork_path = find_best_sprite_path(temp_art_pokemon, 'image')

    # 3. Send the show-off image. This is the ONLY modified section.
    if artwork_path and os.path.exists(artwork_path):
        try:
            # --- START OF MINIMAL IMAGE EDIT ---
            with Image.open(artwork_path).convert("RGBA") as main_art:
                # Path to your transparent symbol
                symbol_path = os.path.join(ASSETS_DIR, 'gmax_symbol.png')
                
                if os.path.exists(symbol_path):
                    with Image.open(symbol_path).convert("RGBA") as symbol_img:
                        # Resize symbol to be 15% of the main image's width (slightly larger)
                        symbol_width = int(main_art.width * 0.25)
                        symbol_height = int(symbol_width * (symbol_img.height / symbol_img.width)) # Keep aspect ratio
                        symbol_img = symbol_img.resize((symbol_width, symbol_height), Image.Resampling.LANCZOS)
                        
                        # Position in the top-left corner with a small margin
                        margin = int(main_art.width * 0.02)
                        position = (margin, margin)
                        
                        # Paste the symbol using its own transparency
                        main_art.paste(symbol_img, position, symbol_img)

                # Save the final image to an in-memory file
                final_image_buffer = io.BytesIO()
                main_art.save(final_image_buffer, format='PNG')
                final_image_buffer.seek(0)

                # Send the composed image
                await bot.send_photo(
                    chat_id=battle.chat_id,
                    photo=final_image_buffer,
                    caption=f"<b>{log_msg}</b>",
                    parse_mode="HTML",
                    reply_to_message_id=battle.message_id
                )
            # --- END OF MINIMAL IMAGE EDIT ---
        except Exception as e:
            print(f"ERROR processing image with symbol: {e}")
            # Fallback to sending the original image if something goes wrong
            with open(artwork_path, 'rb') as photo:
                await bot.send_photo(
                    chat_id=battle.chat_id,
                    photo=photo,
                    caption=f"<b>{log_msg}</b>",
                    parse_mode="HTML"
                )
    
    # 4. Update the main battle UI. This is UNTOUCHED.
    await update_battle_ui(bot, battle, update_image=True)

    # 5. Deletion logic remains commented out. This is UNTOUCHED.
    return log_msg

def _clean_duplicate_faint_logs(log: str) -> str:
    """
    Removes duplicate '<Pokemon> fainted!' lines for the SAME Pokemon
    within a single log string update. Keeps the first instance for each Pokemon.
    """
    lines = log.strip().split('\n')
    cleaned_lines = []
    # This set will store the names of Pokémon whose faint message
    # has already been included in this specific log batch.
    fainted_pokemon_logged_this_batch = set()

    for line in lines:
        stripped_line = line.strip()
        # Use regex to find lines ending exactly with " fainted!"
        match = re.match(r"^(.*) fainted!$", stripped_line)

        if match:
            pokemon_name = match.group(1).strip() # Get the Pokémon name

            # Check if we've already added a faint message FOR THIS SPECIFIC POKEMON in this batch
            if pokemon_name not in fainted_pokemon_logged_this_batch:
                cleaned_lines.append(line) # Keep the first occurrence for this Pokémon
                fainted_pokemon_logged_this_batch.add(pokemon_name) # Mark this Pokémon as logged
            # Else: This is a duplicate faint message for this specific pokemon in this batch, so skip it.
        else:
            # If it's not a faint message, keep it.
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)

async def update_battle_ui(bot: AsyncTeleBot, battle: Battle, action_log: str = "", update_image: bool = False, start_timer: bool = True):
    """
    A centralized function to update the battle message.
    It now selects the background folder and image based on the active terrain.
    """
    keyboard = None
    if battle.state == 'active':
        if battle.turn_phase == 'awaiting_move':
            keyboard = generate_battle_keyboard(battle)
        # --- THIS IS THE FIX ---
        # This now correctly checks for ANY state that requires a switch menu.
        elif battle.turn_phase in ['awaiting_switch', 'awaiting_voluntary_switch', 'awaiting_forced_switch']:
            player_to_switch = battle.get_player(battle.active_player_id)
            keyboard = generate_switch_keyboard(battle, player_to_switch)

    cleaned_action_log = _clean_duplicate_faint_logs(action_log)

    caption = generate_battle_caption(battle, cleaned_action_log)

    # 1. Define mappings for all effect types
    room_to_image_map = {
        'trickroom': 'trickroom.png',
        'wonderroom': 'wonderroom.png'
    }
    weather_to_image_map = {
        'raindance': 'rain.png',
        'sunnyday': 'sunnyday.png',
        'hail': 'snowstrom.png',
        'sandstorm': 'sandstorm.png'
    }
    terrain_to_image_map = {
        'electricterrain': 'electric.jpg',
        'grassyterrain': 'grassy.jpg',
        'mistyterrain': 'misty.jpg',
        'psychicterrain': 'psychic.jpg'
    }

    # 2. Set default background (random terrain)
    background_image_file = battle.terrain
    image_folder = 'terrains'

    # 3. Check for effects with priority: Room > Weather > Terrain
    if battle.trick_room_turns > 0:
        background_image_file = room_to_image_map['trickroom']
        image_folder = 'room_effects'
    elif battle.wonder_room_turns > 0: # CORRECTED: This check was missing
        background_image_file = room_to_image_map['wonderroom']
        image_folder = 'room_effects'
    elif battle.active_weather in weather_to_image_map:
        background_image_file = weather_to_image_map[battle.active_weather]
        image_folder = 'weather_effects' # CORRECTED: Always use this folder for weather
    elif battle.active_terrain in terrain_to_image_map:
        background_image_file = terrain_to_image_map[battle.active_terrain]
        image_folder = 'effect_terrains'
    
    if start_timer:
        # First, cancel any old timer that might be running.
        if battle.timer_task:
            battle.timer_task.cancel()
        
        # Next, check if the battle is in a state where we are waiting for a player.
        if battle.state == 'active' and battle.turn_phase in ['awaiting_move', 'awaiting_switch', 'awaiting_voluntary_switch', 'awaiting_forced_switch']:
            
            # If we are waiting, start a new timer for the currently active player.
            battle.timer_task = asyncio.create_task(
                start_turn_timer(bot, battle, battle.active_player_id, battle.turn)
            )

    try:
        if update_image:
            new_image_bytes = await generate_battle_image(
                battle.player1.get_active_pokemon(),
                battle.player2.get_active_pokemon(),
                terrain=background_image_file,
                folder=image_folder
            )
            if new_image_bytes:
                await bot.edit_message_media(
                    media=types.InputMediaPhoto(new_image_bytes, caption=caption, parse_mode="HTML"),
                    chat_id=battle.chat_id,
                    message_id=battle.message_id,
                    reply_markup=keyboard
                )
        else:
            await bot.edit_message_caption(
                caption=caption,
                chat_id=battle.chat_id,
                message_id=battle.message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except ApiTelegramException as e:
        if "message is not modified" in e.description:
            pass
        else:
            raise e

async def start_turn_timer(bot: AsyncTeleBot, battle: Battle, player_id: int, turn_number: int):
    try:
        # Wait 45 seconds for the warning
        await asyncio.sleep(45) 

        if battle.state == 'active' and battle.active_player_id == player_id and battle.turn == turn_number:
            player = battle.get_player(player_id)
            warning_log = f"⏳ {player.user_name} has 15 seconds left to move!"
            await update_battle_ui(bot, battle, action_log=warning_log, start_timer=False)

        # Wait the final 15 seconds
        await asyncio.sleep(15) 

        if battle.state == 'active' and battle.active_player_id == player_id and battle.turn == turn_number:
            player = battle.get_player(player_id)
            opponent = battle.get_opponent_for_player(player)[0]
            
            battle.winner = opponent
            battle.state = 'finished'
            
            log = f"⏰ <b>Time's up!</b> {player.user_name} did not make a move in time and has forfeited the match."
            
            if battle.chat_id in active_battles:
               _remove_battle(battle)
            
            await update_battle_ui(bot, battle, log)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"An error occurred in the turn timer: {e}")

async def start_turn(bot: AsyncTeleBot, battle: Battle):
    """
    Starts a new turn.
    CHANGED: This function now ONLY sets up the state and does NOT update the UI.
    """
    battle.primed_action = None
    if battle.timer_task:
        battle.timer_task.cancel()
    battle.turn += 1
    battle.turn_phase = 'awaiting_move'
    battle.turn_order = get_move_order(battle)

    for p in [battle.player1.get_active_pokemon(), battle.player2.get_active_pokemon()]:
        p.last_damage_taken = 0
        p.last_damage_category = None
        p.volatiles.pop('faint_processed', None)
    
    faster_player, _ = battle.turn_order[0]
    battle.active_player_id = faster_player.user_id
    battle.timer_task = asyncio.create_task(
        start_turn_timer(bot, battle, battle.active_player_id, battle.turn)
    )

async def handle_slot_conditions(battle: Battle) -> str:
    log = []
    for player in [battle.player1, battle.player2]:
        if 'wish' in player.slot_conditions:
            wish_data = player.slot_conditions['wish']
            wish_data['turns_left'] -= 1
            if wish_data['turns_left'] <= 0:
                active_poke = player.get_active_pokemon()
                if active_poke.current_hp > 0:
                    active_poke.current_hp = min(active_poke.actual_stats['hp'], active_poke.current_hp + wish_data['hp_to_restore'])
                    log.append(f"{player.user_name}'s wish came true!")
                del player.slot_conditions['wish']
    return "\n".join(log)

async def handle_side_conditions(battle: Battle) -> str:
    """Applies end-of-turn effects from G-Max side conditions like Wildfire."""
    log = []
    
    for player in [battle.player1, battle.player2]:
        opponent_player, _ = battle.get_opponent_for_player(player)
        active_poke = opponent_player.get_active_pokemon()

        # Check if the opponent is immune to the effect's type
        effects_to_process = []
        if 'gmax_wildfire' in player.side_conditions and 'Fire' not in active_poke.pokemon.types:
            effects_to_process.append(('gmax_wildfire', 'wildfire'))
        if 'gmax_cannonade' in player.side_conditions and 'Water' not in active_poke.pokemon.types:
            effects_to_process.append(('gmax_cannonade', 'raging waters'))
        if 'gmax_vinelash' in player.side_conditions and 'Grass' not in active_poke.pokemon.types:
            effects_to_process.append(('gmax_vinelash', 'thick vines'))
        if 'gmax_volcalith' in player.side_conditions and 'Rock' not in active_poke.pokemon.types:
            effects_to_process.append(('gmax_volcalith', 'sharp rocks'))

        for effect_key, effect_name in effects_to_process:
            if active_poke.current_hp > 0:
                damage = active_poke.actual_stats['hp'] // 6
                active_poke.current_hp = max(0, active_poke.current_hp - damage)
                log.append(f"{active_poke.pokemon.name} is hurt by the {effect_name}!")

            player.side_conditions[effect_key]['turns'] -= 1
            if player.side_conditions[effect_key]['turns'] <= 0:
                del player.side_conditions[effect_key]

    return "\n".join(log)

async def handle_faint(bot: AsyncTeleBot, battle: Battle, fainted_player: BattlePlayer) -> bool:
    """
    Handles the fainting of a Pokémon. If the battle ends, it updates the database
    and returns True. Otherwise, it sets up for a switch and returns False.
    """
    fainted_pokemon = fainted_player.get_active_pokemon()
    opponent_player, opponent_pokemon = battle.get_opponent_for_player(fainted_player)

    if 'faint_processed' in fainted_pokemon.volatiles:
        # We still need to run the rest of the logic to check if a switch is needed or if the game ends.
        pass
    else:
        # This is the first time we're processing this faint this turn.
        # 1. Set the flag to prevent double-counting.
        fainted_pokemon.volatiles['faint_processed'] = True
        
        # 2. Increment the knockout count.
        opponent_player, _ = battle.get_opponent_for_player(fainted_player)
        opponent_player.ko_count += 1

    faint_ability_log = trigger_on_faint(opponent_pokemon, fainted_pokemon, battle)
    if faint_ability_log:
        battle.log_for_faint += faint_ability_log
        # Check if the attacker fainted from Aftermath
        if opponent_pokemon.current_hp <= 0:
            battle.log_for_faint += f"\n{opponent_pokemon.pokemon.name} fainted!"

    if opponent_pokemon.current_hp > 0: # Check if the attacker is still active
        # NEW HOOK CALL
        ko_ability_log = ability_effects.trigger_on_ko(opponent_pokemon, battle)
        if ko_ability_log:
            # We'll need a way to display this log. For now, let's add it to the battle log.
            # You might need to adjust how logs are passed and displayed.
            battle.log_for_faint += ko_ability_log

    if opponent_pokemon.current_hp > 0: # Ensure the attacker hasn't also fainted from recoil, etc.
        form_change_log = await check_for_form_change(bot, battle, opponent_pokemon, event='on_ko')
        if form_change_log:
            # If a form change happened, we update the UI to show it before continuing
            await update_battle_ui(bot, battle, f"\n{fainted_pokemon.pokemon.name} fainted!", update_image=True)
            await asyncio.sleep(2.5)

    # --- Handle Destiny Bond ---
    #if fainted_pokemon.volatiles.get('destinybond'):
    #    opponent_pokemon.current_hp = 0
    #    # Let the subsequent faint check handle the game over logic
    #    await update_battle_ui(bot, battle, f"{fainted_pokemon.pokemon.name} took {opponent_pokemon.pokemon.name} down with it!")
    #    await asyncio.sleep(2)

    # --- Handle Grudge ---
    if fainted_pokemon.volatiles.get('grudge') and opponent_pokemon.last_move_used:
        move_id = opponent_pokemon.last_move_used
        if move_id in opponent_pokemon.move_pp:
            opponent_pokemon.move_pp[move_id] = 0
            move_name = MOVE_BY_ID[move_id]['name']
            await update_battle_ui(bot, battle, f"The grudge on {fainted_pokemon.pokemon.name} drained the PP of {move_name}!")
            await asyncio.sleep(2)

    # Check if this faint ends the game
    if all(p.current_hp <= 0 for p in fainted_player.team):
        battle.state = 'finished'
        battle.winner = opponent_player

        COINS_PER_KO = 10 
        winner = battle.winner
        loser = fainted_player

        winner_reward = winner.ko_count * COINS_PER_KO
        loser_reward = loser.ko_count * COINS_PER_KO

        db.add_clash_coins(winner.user_id, winner_reward)
        db.add_clash_coins(loser.user_id, loser_reward)

        # Store the calculated rewards on the battle object for the UI to use later
        battle.winner_reward = winner_reward
        battle.loser_reward = loser_reward

        # If ranked, handle the Elo update in the background
        if battle.is_ranked:
            winner, loser = battle.winner, fainted_player
            winner_stats = db.get_user_stats(winner.user_id)
            loser_stats = db.get_user_stats(loser.user_id)
            if winner_stats and loser_stats:
                w_old, l_old = winner_stats[0], loser_stats[0]
                w_new = w_old + calculate_elo_change(w_old, l_old, 1.0)
                l_new = l_old + calculate_elo_change(l_old, w_old, 0.0)
                db.update_user_stats(winner.user_id, w_new, win=1, loss=0, draw=0)
                db.update_user_stats(loser.user_id, l_new, win=0, loss=1, draw=0)
        
        return True # --- GAME IS OVER ---

    # If game is not over, set up for a switch
    else:
        battle.turn_phase = 'awaiting_switch'
        battle.active_player_id = fainted_player.user_id
        battle.timer_task = asyncio.create_task(
            start_turn_timer(bot, battle, battle.active_player_id, battle.turn)
        )
        return False # --- BATTLE CONTINUES ---

async def handle_end_of_turn_effects(battle: Battle) -> str:
    """
    Applies end-of-turn effects like poison/burn/leech seed damage.
    Returns a log of events that occurred.
    """
    log_entries = []

    for player in [battle.player1, battle.player2]:
        pokemon = player.get_active_pokemon()
        pokemon.active_turns += 1

    for player in [battle.player1, battle.player2]:
        pokemon = player.get_active_pokemon()
        if 'perishsong' in pokemon.volatiles:
            pokemon.volatiles['perishsong'] -= 1
            log_entries.append(f"{pokemon.pokemon.name}'s perish count fell to {pokemon.volatiles['perishsong']}!")
            if pokemon.volatiles['perishsong'] == 0:
                pokemon.current_hp = 0 # Pokémon faints

    for player in [battle.player1, battle.player2]:
        pokemon = player.get_active_pokemon()
        if pokemon.current_hp > 0:

            if 'disable' in pokemon.volatiles:
                pokemon.volatiles['disable']['turns'] -= 1
                if pokemon.volatiles['disable']['turns'] <= 0:
                    del pokemon.volatiles['disable']
                    log_entries.append(f"{pokemon.pokemon.name} is no longer disabled!")
            
            if 'encore' in pokemon.volatiles:
                pokemon.volatiles['encore']['turns'] -= 1
                if pokemon.volatiles['encore']['turns'] <= 0:
                    del pokemon.volatiles['encore']
                    log_entries.append(f"{pokemon.pokemon.name}'s encore ended!")

            if 'taunt' in pokemon.volatiles:
                pokemon.volatiles['taunt'] -= 1
                if pokemon.volatiles['taunt'] <= 0:
                    del pokemon.volatiles['taunt']
                    log_entries.append(f"{pokemon.pokemon.name}'s taunt wore off!")

            if 'trap' in pokemon.volatiles:
                # If duration is > 900, it's a permanent trap like Mean Look that
                # only ends when the user switches. We don't count it down.
                if pokemon.volatiles['trap']['duration'] < 900:
                    pokemon.volatiles['trap']['duration'] -= 1
                
                if pokemon.volatiles['trap']['duration'] <= 0:
                    del pokemon.volatiles['trap']
                    log_entries.append(f"{pokemon.pokemon.name} was freed from the trap!")
                else:
                    # Check if it's a damaging trap
                    source_move = pokemon.volatiles['trap']['source_move']
                    damaging_traps = ['firespin', 'whirlpool', 'sandtomb', 'clamp', 'magmastorm', 'infestation']
                    if source_move in damaging_traps:
                        damage = max(1, pokemon.actual_stats['hp'] // 8) # 1/8th max HP
                        pokemon.current_hp = max(0, pokemon.current_hp - damage)
                        log_entries.append(f"{pokemon.pokemon.name} is hurt by {MOVE_BY_ID[source_move]['name']}! It lost {damage} HP!")

            if 'yawn' in pokemon.volatiles:
                pokemon.volatiles['yawn'] -= 1
                if pokemon.volatiles['yawn'] == 0:
                    del pokemon.volatiles['yawn']
                    # Use apply_status to try and put them to sleep.
                    # This correctly handles existing statuses, Lum Berry, etc.
                    sleep_log = apply_status('slp', pokemon, {'status': 'slp'}, battle)
                    if sleep_log:
                        log_entries.append(sleep_log)
                    else:
                        log_entries.append(f"\n{pokemon.pokemon.name} didn't fall asleep!")

            if 'curse' in pokemon.volatiles:
                damage = max(1, pokemon.actual_stats['hp'] // 4)
                pokemon.current_hp = max(0, pokemon.current_hp - damage)
                log_entries.append(f"{pokemon.pokemon.name} is afflicted by the curse! It lost {damage} HP!")

            item_log = item_logic.apply_end_of_turn_item_effects(pokemon)
            if item_log:
                # We use .strip() to avoid adding extra blank lines
                log_entries.append(item_log.strip())

            # --- Handle Leech Seed first ---
            if pokemon.volatiles.get('leechseed'):
                opponent = battle.get_opponent_for_player(player)[0]
                opponent_pokemon = opponent.get_active_pokemon()

                # Sap 1/8 of max HP
                sap_amount = max(1, pokemon.actual_stats['hp'] // 8)
                pokemon.current_hp = max(0, pokemon.current_hp - sap_amount)
                log_entries.append(f"{pokemon.pokemon.name}'s health was sapped by Leech Seed!")

                # Heal the opponent, but only if they are not at full health
                if opponent_pokemon.current_hp > 0:
                    opponent_pokemon.current_hp = min(
                        opponent_pokemon.actual_stats['hp'],
                        opponent_pokemon.current_hp + sap_amount
                    )
            # --- End of Leech Seed logic ---
            ability_id = pokemon.pokemon.ability.lower().replace(" ", "")

            if not is_weather_suppressed(battle):
                # Rain Dish
                if ability_id == 'raindish' and battle.active_weather == 'raindance':
                    if pokemon.current_hp < pokemon.actual_stats['hp']:
                        heal_amount = max(1, pokemon.actual_stats['hp'] // 16)
                        pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
                        log_entries.append(f"{pokemon.pokemon.name}'s Rain Dish restored its HP!")
                
                # Ice Body
                elif ability_id == 'icebody' and battle.active_weather == 'hail':
                    if pokemon.current_hp < pokemon.actual_stats['hp']:
                        heal_amount = max(1, pokemon.actual_stats['hp'] // 16)
                        pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
                        log_entries.append(f"{pokemon.pokemon.name}'s Ice Body restored its HP!")
                
                # Dry Skin
                elif ability_id == 'dryskin':
                    if battle.active_weather == 'raindance' and pokemon.current_hp < pokemon.actual_stats['hp']:
                        heal_amount = max(1, pokemon.actual_stats['hp'] // 8)
                        pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
                        log_entries.append(f"{pokemon.pokemon.name}'s Dry Skin restored its HP in the rain!")
                    elif battle.active_weather == 'sunnyday':
                        damage_amount = max(1, pokemon.actual_stats['hp'] // 8)
                        pokemon.current_hp = max(0, pokemon.current_hp - damage_amount)
                        log_entries.append(f"{pokemon.pokemon.name} was hurt by the harsh sunlight!")

                # Solar Power
                elif ability_id == 'solarpower' and battle.active_weather == 'sunnyday':
                    damage_amount = max(1, pokemon.actual_stats['hp'] // 8)
                    pokemon.current_hp = max(0, pokemon.current_hp - damage_amount)
                    log_entries.append(f"{pokemon.pokemon.name} was hurt by its Solar Power!")
                    
            if ability_id == 'speedboost':
                # Use handle_stat_boost_move to apply the boost and get the log
                boost_data = {'boosts': {'spe': 1}}
                # Make sure handle_stat_boost_move is imported
                from bot.battle.move_effects.status_moves import handle_stat_boost_move
                boost_log = handle_stat_boost_move(pokemon, boost_data)
                if boost_log: # Only add log if the boost wasn't prevented (e.g., at +6)
                    log_entries.append(boost_log.strip())

            # 1. Poison Heal Logic (Highest priority to prevent poison damage)
            if ability_id == 'poisonheal' and pokemon.status in ['psn', 'tox']:
                if pokemon.current_hp < pokemon.actual_stats['hp']:
                    heal_amount = max(1, pokemon.actual_stats['hp'] // 8)
                    pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
                    log_entries.append(f"{pokemon.pokemon.name}'s Poison Heal restored its HP!")
                continue # CRITICAL: Skip the poison/burn damage logic below
            
            # 2. Hydration Logic (Cures status before damage)
            elif ability_id == 'hydration' and battle.active_weather == 'raindance' and pokemon.status is not None:
                pokemon.status = None
                pokemon.status_counter = 0
                log_entries.append(f"{pokemon.pokemon.name}'s Hydration cured its status condition in the rain!")

            # 3. Shed Skin Logic (Cures status before damage)
            elif ability_id == 'shedskin' and pokemon.status is not None and random.randint(1, 100) <= 33:
                pokemon.status = None
                pokemon.status_counter = 0
                log_entries.append(f"{pokemon.pokemon.name} shed its skin and cured its status!")

            if pokemon.status == 'brn':
                # Burn damage is 1/16 of max HP
                damage = max(1, pokemon.actual_stats['hp'] // 16)
                pokemon.current_hp = max(0, pokemon.current_hp - damage)
                # --- MODIFIED LINE ---
                log_entries.append(f"{pokemon.pokemon.name} was hurt by its burn! It lost {damage} HP!")

            elif pokemon.status == 'psn':
                # Poison damage is 1/8 of max HP
                damage = max(1, pokemon.actual_stats['hp'] // 8)
                pokemon.current_hp = max(0, pokemon.current_hp - damage)
                # --- MODIFIED LINE ---
                log_entries.append(f"{pokemon.pokemon.name} was hurt by poison! It lost {damage} HP!")

            elif pokemon.status == 'tox':
                pokemon.status_counter += 1
                # Toxic damage is (1/16) * N, where N is the turn counter
                damage = max(1, int((pokemon.actual_stats['hp'] / 16) * pokemon.status_counter))
                pokemon.current_hp = max(0, pokemon.current_hp - damage)
                # --- MODIFIED LINE ---
                log_entries.append(f"{pokemon.pokemon.name} was hurt by poison! It lost {damage} HP!")

    for player in [battle.player1, battle.player2]:
        pokemon = player.get_active_pokemon()
        if pokemon.current_hp > 0:
            ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
            effect = ability_effects.ABILITY_EFFECTS.get(ability_id)
            if effect and 'on_end_of_turn' in effect:
                # The restore_ice_face function will handle the logic and return a log message
                restore_log = effect['on_end_of_turn'](pokemon, battle)
                if restore_log:
                    log_entries.append(restore_log)

    side_condition_log = await handle_side_conditions(battle)
    if side_condition_log:
        log_entries.append(side_condition_log)

    return "\n".join(log_entries)

async def execute_mega_evolution(bot: AsyncTeleBot, battle: Battle, player: 'BattlePlayer'):
    """Performs the Mega Evolution transformation and sends notifications."""
    active_pokemon = player.get_active_pokemon()
    
    base_species = SPECIES_BY_ID.get(active_pokemon.pokemon.id, {}).get("baseSpecies", active_pokemon.pokemon.name)
    mega_species_id = None

    if active_pokemon.pokemon.id == 'rayquaza' and 'dragonascent' in active_pokemon.pokemon.moves:
        mega_species_id = 'rayquazamega'
    
    if not mega_species_id:
        pokemon_item = active_pokemon.pokemon.item
        for s in SPECIES_BY_ID.values():
            if s.get("baseSpecies") == base_species and s.get("requiredItem") and s.get("requiredItem") == pokemon_item:
                mega_species_id = s["id"]
                break
    
    if not mega_species_id:
        return

    mega_species_data = SPECIES_BY_ID[mega_species_id]
    
    # --- THIS IS THE NEW LOGIC ---
    # A dictionary to hold custom captions for special transformations.
    custom_captions = {
        "Zacian": f"The Rusted Sword resonates! {player.user_name}'s Zacian changed to its <b>Crowned Sword</b> form!",
        "Zamazenta": f"The Rusted Shield resonates! {player.user_name}'s Zamazenta changed to its <b>Crowned Shield</b> form!",
        "Mewtwo": f"A wave of psychic energy erupts! {player.user_name}'s Mewtwo has Mega Evolved into <b>{mega_species_data['name']}</b>!",
        "Rayquaza": f"The heavens tremble! {player.user_name}'s Rayquaza has Mega Evolved into <b>{mega_species_data['name']}</b>!",
        # You can add more here for other Pokémon like Primals
        "Groudon": f"The land itself groans as scorching magma erupts! {player.user_name}'s Groudon has undergone Primal Reversion into <b>{mega_species_data['name']}</b>!",
        "Kyogre": f"A torrential downpour begins as the seas churn! {player.user_name}'s Kyogre has undergone Primal Reversion into <b>{mega_species_data['name']}</b>!",
    }

    # Select a custom caption if the Pokémon's base species is in our dictionary,
    # otherwise, use the default generic caption.
    caption = custom_captions.get(
        base_species, 
        f"<b>{player.user_name}</b>'s {active_pokemon.pokemon.name} has Mega Evolved into <b>{mega_species_data['name']}</b>!"
    )
    # --- END OF NEW LOGIC ---

    # --- 1. Send the "Show-off" Image ---
    artwork_path = None
    temp_mega_pokemon = Pokemon(id=mega_species_id, name=mega_species_data['name'], level=100, types=[], base_stats=None, ivs=None, evs=None, nature="", ability="", weight=0, item=None, moves=[], current_hp=1, max_hp=1, status=None, boosts={}, volatiles={}, is_shiny=active_pokemon.pokemon.is_shiny)
    
    artwork_path = find_best_sprite_path(temp_mega_pokemon, 'image')

    if artwork_path and os.path.exists(artwork_path):
        with open(artwork_path, 'rb') as photo:
            await bot.send_photo(
                chat_id=battle.chat_id,
                photo=photo,
                caption=caption, # Use the new caption variable
                parse_mode="HTML",
                reply_to_message_id=battle.message_id
            )

    # --- 2. Transform the Pokémon ---
    active_pokemon.pokemon.id = mega_species_id
    active_pokemon.pokemon.name = mega_species_data['name']
    active_pokemon.pokemon.types = mega_species_data['types']
    active_pokemon.pokemon.ability = mega_species_data['abilities']['0']
    
    new_base_stats_data = mega_species_data["baseStats"].copy()
    if 'def' in new_base_stats_data:
        new_base_stats_data['def_'] = new_base_stats_data.pop('def')
    active_pokemon.pokemon.base_stats = Stats(**new_base_stats_data)
    
    old_max_hp = active_pokemon.actual_stats['hp']
    active_pokemon.actual_stats = get_actual_stats(active_pokemon.pokemon)
    hp_ratio = active_pokemon.current_hp / old_max_hp
    active_pokemon.current_hp = math.ceil(active_pokemon.actual_stats['hp'] * hp_ratio)

    # --- 3. Set Battle Flags ---
    player.has_mega_evolved = True
    player.has_dynamaxed = True 
    
    current_caption = generate_battle_caption(battle, f"{player.user_name}'s {base_species} has Mega Evolved into {mega_species_data['name']}!")

    new_image_bytes = await generate_battle_image(
        battle.player1.get_active_pokemon(),
        battle.player2.get_active_pokemon(),
        terrain=battle.terrain,
        folder='terrains'
    )
    if new_image_bytes:
        await bot.edit_message_media(
            # This updates the image and caption in one go, fixing the flicker
            media=types.InputMediaPhoto(new_image_bytes, caption=current_caption, parse_mode="HTML"),
            chat_id=battle.chat_id,
            message_id=battle.message_id
        )

    # --- THIS IS THE FIX ---
    # Return an empty string. This tells the next function that the log
    # has already been handled, preventing a duplicate message and avoiding errors.
    return ""

# --- MAIN REGISTRATION FUNCTION ---

def register_battle_handlers(bot: AsyncTeleBot):
    """
    Registers all handlers for the new interactive challenge system.
    """
    
    @bot.message_handler(commands=['clash'])
    @user_not_banned(bot)
    async def challenge_command(message):
        if not message.reply_to_message:
            await bot.reply_to(message, "To start a battle, you must reply to a user's message with the `/clash` command.")
            return

        challenger = message.from_user
        opponent = message.reply_to_message.from_user

        if opponent.is_bot or challenger.id == opponent.id:
            await bot.reply_to(message, "You can't challenge bots or yourself.")
            return

        from bot.showdown_battle.service import get_showdown_service

        showdown_service = get_showdown_service()
        if showdown_service:
            challenger_lock = showdown_service.showdown_lock_reason(challenger.id)
            if challenger_lock:
                await bot.reply_to(message, challenger_lock)
                return
            opponent_lock = showdown_service.showdown_lock_reason(opponent.id)
            if opponent_lock:
                await bot.reply_to(message, f"{opponent.first_name} is already in another PvP battle.")
                return

        legacy_challenger_lock = legacy_pvp_lock_reason(challenger.id)
        if legacy_challenger_lock:
            await bot.reply_to(message, legacy_challenger_lock)
            return
        legacy_opponent_lock = legacy_pvp_lock_reason(opponent.id)
        if legacy_opponent_lock:
            await bot.reply_to(message, f"{opponent.first_name} is already in another PvP battle.")
            return

        if len(active_battles.get(message.chat.id, [])) >= 2:
            await bot.reply_to(message, "There are already 2 battles in progress in this chat. Please wait for one to finish.")
            return

        challenge_id = message.message_id
        
        settings = {
            'chat_id': message.chat.id,
            'challenger_id': challenger.id,
            'challenger_name': challenger.first_name,
            'opponent_id': opponent.id,
            'opponent_name': opponent.first_name,
            'mode': db.get_battle_mode(challenger.id),
            'mega_enabled': db.get_mega_setting(challenger.id),
            'gmax_enabled': db.get_gmax_setting(challenger.id),
            'is_ranked': db.get_ranking_setting(challenger.id),
            'sleep_clause_enabled': db.get_sleep_clause_setting(challenger.id),
            'legendary_mode': db.get_legendary_setting(challenger.id),
            'non_legendary_mode': db.get_non_legendary_setting(challenger.id),
            'random_battle_generation': db.get_random_battle_setting(challenger.id),
            'special_mode': None,
        }
        pending_challenges[challenge_id] = settings

        content = _generate_challenge_text(settings, challenger.first_name, opponent.first_name)
        text = content["text"]
        preview_url = content["preview_url"]
        
        # 2. Generate the keyboard as before
        markup = _generate_challenge_keyboard(challenge_id, challenger.id, opponent.id)

        # 3. Create the LinkPreviewOptions object
        link_options = LinkPreviewOptions(
            is_disabled=False, 
            url=preview_url, 
            prefer_large_media=True, 
            show_above_text=True
        )

        # 4. Pass the options to the send_message call
        sent_message = await bot.send_message(
            message.chat.id, 
            text, 
            reply_markup=markup, 
            parse_mode="HTML",
            link_preview_options=link_options
        )
        settings['challenge_message_id'] = sent_message.message_id

    @bot.callback_query_handler(func=lambda call: call.data.startswith('b_ch_'))
    @user_not_banned(bot)
    async def handle_challenge_callbacks(call):
        """A single, unified handler for all challenge-related button clicks, including menus."""
        try:
            user_id = call.from_user.id
            parts = call.data.split('_')
            action = parts[2]
            challenge_id = None

            # --- ROBUST CALLBACK PARSING ---
            # This block identifies the action and correctly extracts the challenge_id and owner_id.
            if action == "reset":
                challenge_id = int(parts[3])
            elif action == "set":
                if parts[3] == "gen":
                    action = "set_gen"
                    challenge_id = int(parts[4])
                elif parts[3] == "special":
                    action = "set_special"
                    challenge_id = int(parts[4])
            elif action == "toggle":
                challenge_id = int(parts[3])
            elif action == "menu":
                challenge_id = int(parts[3])
            elif action in ["settings", "main", "accept", "decline"]:
                challenge_id = int(parts[3])

            if challenge_id is None:
                # This is a failsafe for any unexpected callback format.
                await bot.answer_callback_query(call.id, "Error: Unknown challenge action.", show_alert=True)
                return

            challenge_data = pending_challenges.get(challenge_id)

            if not challenge_data:
                await bot.answer_callback_query(call.id, "This challenge has expired or is invalid.", show_alert=True)
                try:
                    await bot.edit_message_text("This challenge has expired.", call.message.chat.id, call.message.id, reply_markup=None)
                except Exception:
                    pass
                return

            # --- ACTION HANDLERS ---
            if action == "set_gen":
                generation = int(parts[5])
                owner_id = int(parts[6])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can change settings.", show_alert=True)

                if generation == 0:
                    challenge_data['random_battle_generation'] = None
                    db.set_random_battle_setting(owner_id, 0)
                    await bot.answer_callback_query(call.id, "Random Battle mode disabled.")
                else:
                    challenge_data['random_battle_generation'] = generation
                    challenge_data.update({'legendary_mode': False, 'non_legendary_mode': False, 'special_mode': None})
                    db.set_random_battle_setting(owner_id, generation)
                    await bot.answer_callback_query(call.id, f"Random Battle set to Gen {generation}.")

                content = get_settings_content(context='challenge', menu_context='main_modes', challenge_id=challenge_id, settings=challenge_data, challenger_id=user_id)
                await bot.edit_message_text(content['text'], call.message.chat.id, call.message.id, reply_markup=content['markup'], parse_mode="HTML")
                return

            elif action == "decline":
                challenger_id = challenge_data['challenger_id']
                opponent_id = challenge_data['opponent_id']
                if user_id not in [challenger_id, opponent_id]:
                    return await bot.answer_callback_query(call.id, "This challenge is not for you.", show_alert=True)

                pending_challenges.pop(challenge_id, None)
                actor_name = challenge_data['challenger_name'] if user_id == challenger_id else challenge_data['opponent_name']
                status_text = "cancelled" if user_id == challenger_id else "declined"
                await bot.edit_message_text(
                    f"❌ This challenge was {status_text} by <b>{html.escape(actor_name)}</b>.",
                    call.message.chat.id,
                    call.message.id,
                    reply_markup=None,
                    parse_mode="HTML",
                )
                await bot.answer_callback_query(call.id, f"Challenge {status_text}.")
                return

            elif action == "reset":
                owner_id = int(parts[4])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can reset settings.", show_alert=True)

                challenge_data = pending_challenges.get(challenge_id)
                if not challenge_data:
                    # Safety check for expired challenges
                    await bot.answer_callback_query(call.id, "This challenge has expired.", show_alert=True)
                    return

                # 1. Reset the settings for the current challenge
                challenge_data['random_battle_generation'] = None
                challenge_data['legendary_mode'] = False
                challenge_data['non_legendary_mode'] = False
                challenge_data['special_mode'] = None
                challenge_data['is_ranked'] = False
                # Keep battle mechanics enabled by default
                challenge_data['mega_enabled'] = True
                challenge_data['gmax_enabled'] = True
                challenge_data['sleep_clause_enabled'] = True

                # 2. Update the user's saved defaults in the database
                db.set_random_battle_setting(owner_id, 0)
                db.set_legendary_setting(owner_id, False)
                db.set_non_legendary_setting(owner_id, False)
                db.set_ranking_setting(owner_id, False)
                db.set_mega_setting(owner_id, True)
                db.set_gmax_setting(owner_id, True)
                db.set_sleep_clause_setting(owner_id, True)

                # 3. Provide feedback and refresh the UI
                await bot.answer_callback_query(call.id, "All battle settings have been reset to Standard.")
                
                # Refresh the current menu to show the changes
                content = get_settings_content(
                    context='challenge', 
                    menu_context='main_modes', 
                    challenge_id=challenge_id, 
                    settings=challenge_data, 
                    challenger_id=owner_id
                )
                await bot.edit_message_text(
                    content['text'], 
                    call.message.chat.id, 
                    call.message.id, 
                    reply_markup=content['markup'], 
                    parse_mode="HTML"
                )
                return

            elif action == "toggle":
                setting_to_toggle = parts[4]
                owner_id = int(parts[5])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can change settings.", show_alert=True)

                current_menu = 'rules'
                if setting_to_toggle in ['legendary', 'nonlegendary']:
                    current_menu = 'main_modes'
                    is_legendary = setting_to_toggle == 'legendary'
                    new_value = not challenge_data.get(f"{setting_to_toggle}_mode", False)

                    challenge_data.update({'random_battle_generation': None, 'legendary_mode': False, 'non_legendary_mode': False, 'special_mode': None})
                    
                    if is_legendary:
                        challenge_data['legendary_mode'] = new_value
                    else:
                        challenge_data['non_legendary_mode'] = new_value
                    
                    db.set_random_battle_setting(owner_id, 0) # **THE FIX FOR DatatypeMismatch**
                    db.set_legendary_setting(owner_id, challenge_data['legendary_mode'])
                    db.set_non_legendary_setting(owner_id, challenge_data['non_legendary_mode'])
                else:
                    setting_map = {"mega": "mega_enabled", "gmax": "gmax_enabled", "ranked": "is_ranked", "sleep": "sleep_clause_enabled"}
                    key = setting_map.get(setting_to_toggle)
                    if key:
                        new_value = not challenge_data.get(key, False)
                        challenge_data[key] = new_value
                        if key == 'mega_enabled': db.set_mega_setting(owner_id, new_value)
                        elif key == 'gmax_enabled': db.set_gmax_setting(owner_id, new_value)
                        elif key == 'is_ranked': db.set_ranking_setting(owner_id, new_value)
                        elif key == 'sleep_clause_enabled': db.set_sleep_clause_setting(owner_id, new_value)
                
                content = get_settings_content(context='challenge', menu_context=current_menu, challenge_id=challenge_id, settings=challenge_data, challenger_id=user_id)
                await bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=content['markup'])
                await bot.answer_callback_query(call.id, "Setting updated and saved!")


            elif action == "set_special":
                mode = "_".join(parts[5:-1])
                owner_id = int(parts[-1])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can change settings.", show_alert=True)
                
                challenge_data['special_mode'] = None if challenge_data.get('special_mode') == mode else mode
                challenge_data.update({'random_battle_generation': None, 'legendary_mode': False, 'non_legendary_mode': False})
                db.set_random_battle_setting(owner_id, 0)
                db.set_legendary_setting(owner_id, False)
                db.set_non_legendary_setting(owner_id, False)
                
                content = get_settings_content(context='challenge', menu_context='fun_modes', challenge_id=challenge_id, settings=challenge_data, challenger_id=user_id)
                await bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=content['markup'])
                await bot.answer_callback_query(call.id, "Fun mode updated!")

            elif action == "menu":
                menu_context = "_".join(parts[4:-1])
                owner_id = int(parts[-1])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can change settings.", show_alert=True)

                content = get_settings_content(context='challenge', menu_context=menu_context, challenge_id=challenge_id, settings=challenge_data, challenger_id=user_id)
                await bot.edit_message_text(content['text'], call.message.chat.id, call.message.id, reply_markup=content['markup'], parse_mode="HTML")

            elif action == "settings":
                owner_id = int(parts[4])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can change settings.", show_alert=True)
                
                content = get_settings_content(context='challenge', menu_context='main', challenge_id=challenge_id, settings=challenge_data, challenger_id=user_id)
                await bot.edit_message_text(content['text'], call.message.chat.id, call.message.id, reply_markup=content['markup'], parse_mode="HTML")

            elif action == "main": # This is the "Done" button handler
                owner_id = int(parts[4])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "Only the challenger can do this.", show_alert=True)
                
                # --- THIS IS THE FIX ---
                # 1. Get the content dictionary, which includes the text and the preview URL.
                content = _generate_challenge_text(challenge_data, challenge_data['challenger_name'], challenge_data['opponent_name'])
                text = content["text"]
                preview_url = content["preview_url"]

                # 2. Generate the keyboard as before.
                markup = _generate_challenge_keyboard(challenge_id, challenge_data['challenger_id'], challenge_data['opponent_id'])
                
                # 3. Re-create the LinkPreviewOptions object.
                link_options = LinkPreviewOptions(
                    is_disabled=False, 
                    url=preview_url, 
                    prefer_large_media=True, 
                    show_above_text=True
                )

                # 4. Pass the link_preview_options to the edit_message_text call.
                await bot.edit_message_text(
                    text, 
                    call.message.chat.id, 
                    call.message.id, 
                    reply_markup=markup, 
                    parse_mode="HTML",
                    link_preview_options=link_options
                )
    
            elif action == "accept":
                owner_id = int(parts[4])
                if user_id != owner_id:
                    return await bot.answer_callback_query(call.id, "This challenge is not for you.", show_alert=True)
                
                settings = pending_challenges.get(challenge_id)
                if not settings:
                    await bot.answer_callback_query(call.id, "This challenge has expired.", show_alert=True)
                    return
                    
                challenger_id = settings['challenger_id']
                opponent_id = settings['opponent_id']
                
                for chat_battles in active_battles.values():
                    for battle in chat_battles:
                        if challenger_id in [battle.player1.user_id, battle.player2.user_id]:
                            await bot.answer_callback_query(call.id, f"{settings['challenger_name']} has already entered another battle.", show_alert=True)
                            await bot.edit_message_text("This challenge has expired because the challenger started a different battle.", call.message.chat.id, call.message.id, reply_markup=None)
                            pending_challenges.pop(challenge_id, None)
                            return
                        if opponent_id in [battle.player1.user_id, battle.player2.user_id]:
                            await bot.answer_callback_query(call.id, "You are already in another battle.", show_alert=True)
                            await bot.edit_message_text("This challenge has expired because the opponent started a different battle.", call.message.chat.id, call.message.id, reply_markup=None)
                            pending_challenges.pop(challenge_id, None)
                            return
                
                async def fail_challenge(reason: str):
                    await bot.edit_message_text(f"❌ <b>Battle Cannot Start!</b>\n\n<b>Reason:</b> {reason}", call.message.chat.id, call.message.id, parse_mode="HTML", reply_markup=None)
                    pending_challenges.pop(challenge_id, None)
                if not settings.get('random_battle_mode'):
                    # --- Basic Validation (Unchanged) ---
                    is_challenger_valid, reason = await validate_player_for_battle(settings['challenger_id'], settings['challenger_name'])
                    if not is_challenger_valid: return await fail_challenge(reason)
                    is_opponent_valid, reason = await validate_player_for_battle(settings['opponent_id'], settings['opponent_name'])
                    if not is_opponent_valid: return await fail_challenge(reason)
    
                    # --- NEW, COMPREHENSIVE VALIDATION LOGIC ---
                    for player_id, player_name in [(settings['challenger_id'], settings['challenger_name']), (settings['opponent_id'], settings['opponent_name'])]:
                        team_data = db.get_active_team(player_id)
                        team_uuids = team_data[3] if team_data else []
                        collection = db.get_collection(player_id)
                        pokemon_map = {p.pokemon_uuid: p for p in collection}
                        team_pokemon = [pokemon_map[uuid] for uuid in team_uuids if uuid in pokemon_map]
    
                        for p in team_pokemon:
                            # Rule 1: Non-Legendary Mode (Standard Mode)
                            if settings.get('non_legendary_mode'):
                                if p.id in ALL_SPECIAL_IDS:
                                    return await fail_challenge(f"{player_name}'s team contains a special Pokémon ({p.name}), which is not allowed in Non-Legendary Mode.")
                            
                            # Rule 2: Legendary Mode (Legends Only)
                            elif settings.get('legendary_mode'):
                                if p.id not in ALL_LEGENDARY_IDS:
                                    return await fail_challenge(f"{player_name}'s team contains a non-legendary Pokémon ({p.name}), which is not allowed in Legendary Mode.")
                                if p.id in MYTHICAL_IDS:
                                    return await fail_challenge(f"{player_name}'s team contains a Mythical Pokémon ({p.name}), which is not allowed in Legendary Mode.")
                            
                            # Rule 3: Fun Modes (Temporary)
                            elif settings.get('special_mode') == 'sub_legendary_only':
                                if p.id not in SUB_LEGENDARY_IDS:
                                    return await fail_challenge(f"{player_name}'s team contains a Pokémon ({p.name}) that is not a Sub-Legendary.")
                            elif settings.get('special_mode') == 'ultra_beast_only':
                                if p.id not in ULTRA_BEAST_IDS:
                                    return await fail_challenge(f"{player_name}'s team contains a Pokémon ({p.name}) that is not an Ultra Beast.")
                            elif settings.get('special_mode') == 'restricted_only':
                                if p.id not in RESTRICTED_LEGENDARY_IDS:
                                    return await fail_challenge(f"{player_name}'s team contains a Pokémon ({p.name}) that is not a Restricted Legendary.")
                    # --- END OF NEW LOGIC ---

                if settings.get('is_ranked', False):
                    ranked_group_ids_str = os.getenv('RANKED_GROUP_IDS', '')
                    allowed_chat_ids = [int(id_str.strip()) for id_str in ranked_group_ids_str.split(',') if id_str.strip()]
                    if call.message.chat.id not in allowed_chat_ids:
                        return await fail_challenge("Ranked matches are not allowed in this chat.")
                    if not db.get_ranking_setting(settings['challenger_id']):
                        return await fail_challenge(f"{settings['challenger_name']} does not have Ranked Battles enabled in their global /settings.")
                from bot.showdown_battle.service import get_showdown_service
                showdown_service = get_showdown_service()
                if showdown_service:
                    challenger_lock = showdown_service.showdown_lock_reason(settings['challenger_id'])
                    if challenger_lock:
                        return await fail_challenge(challenger_lock)
                    opponent_lock = showdown_service.showdown_lock_reason(settings['opponent_id'])
                    if opponent_lock:
                        return await fail_challenge(f"{settings['opponent_name']} is already in another PvP battle.")
                if len(active_battles.get(call.message.chat.id, [])) >= 2:
                    await bot.answer_callback_query(call.id, "There are already 2 battles in progress in this chat!", show_alert=True)
                    await bot.edit_message_text(
                        "This challenge has expired because the chat's battle limit has been reached.",
                        chat_id=call.message.chat.id,
                        message_id=call.message.id,
                        reply_markup=None
                    )
                    pending_challenges.pop(challenge_id, None) # Remove from pending
                    return
                challenges_to_remove = []
                for other_challenge_id, other_data in pending_challenges.items():
                    # Find any other challenge where the accepting user is the opponent OR the challenger
                    if user_id in [other_data['opponent_id'], other_data['challenger_id']] and other_challenge_id != challenge_id:
                        challenges_to_remove.append(other_challenge_id)
                
                for cid in challenges_to_remove:
                    expired_challenge_data = pending_challenges.pop(cid, None)
                    if expired_challenge_data:
                        try:
                            # Edit the old message to show it's no longer valid
                            await bot.edit_message_text(
                                "This challenge has expired as another battle was accepted.",
                                chat_id=expired_challenge_data['chat_id'],
                                message_id=cid,
                                reply_markup=None
                            )
                        except Exception as e:
                            print(f"Could not edit expired challenge message {cid}: {e}")

                final_settings = pending_challenges.pop(challenge_id, None)
                if final_settings:
                    await start_battle_from_challenge(bot, call, final_settings, challenge_id)
                else:
                    await bot.answer_callback_query(call.id, "This challenge has already been accepted or has expired.", show_alert=True)
        except Exception:
            traceback.print_exc()
            await bot.answer_callback_query(call.id, "An error occurred with this challenge.", show_alert=True)

    async def start_battle_from_challenge(bot, call, settings, original_message_id):
        """The logic to initialize and start the battle, separated for clarity."""
        await bot.answer_callback_query(call.id, "Preparing the arena...")
        await bot.edit_message_text("✅ <b>Challenge Accepted!</b>\n\nLoading battle...", call.message.chat.id, call.message.id, parse_mode="HTML")

        # --- (Data fetching logic is unchanged) ---
        challenger_id = settings['challenger_id']; opponent_id = settings['opponent_id']
        challenger_user = await bot.get_chat(challenger_id); opponent_user = await bot.get_chat(opponent_id)
        generation = settings.get('random_battle_generation')
    
        if generation:
            # --- NEW RANDOM BATTLE LOGIC ---
            await bot.edit_message_text(f"✅ Challenge Accepted!\n\nGenerating Gen {generation} teams...", call.message.chat.id, call.message.id, parse_mode="HTML")
            
            p1_team, p2_team = [], []
            if generation == 1:
                p1_team = gen1_random_team.generate()
                p2_team = gen1_random_team.generate()
            elif generation == 2:
                p1_team = gen2_random_team.generate()
                p2_team = gen2_random_team.generate()
            elif generation == 3:
                p1_team = gen3_random_team.generate()
                p2_team = gen3_random_team.generate()
            elif generation == 4:
                p1_team = gen4_random_team.generate()
                p2_team = gen4_random_team.generate()
            elif generation == 5:
                p1_team = gen5_random_team.generate()
                p2_team = gen5_random_team.generate()
            elif generation == 6:
                p1_team = gen6_random_team.generate()
                p2_team = gen6_random_team.generate()
            elif generation == 7:
                p1_team = gen7_random_team.generate()
                p2_team = gen7_random_team.generate()
            elif generation == 8:
                p1_team = gen8_random_team.generate()
                p2_team = gen8_random_team.generate()
            # You can add more generations here with 'elif generation == 9:'
            
            if not p1_team or not p2_team:
                 await bot.edit_message_text(f"❌ Error: Failed to generate teams for Gen {generation} Random Battle.", call.message.chat.id, call.message.id, parse_mode="HTML")
                 pending_challenges.pop(original_message_id, None)
                 return
        else:
            # ---  STANDARD BATTLE LOGIC
            # STANDARD BATTLE: Load the players' saved teams from the database.
            p1_team_data = db.get_active_team(challenger_id)
            p2_team_data = db.get_active_team(opponent_id)
            p1_collection = db.get_collection(challenger_id)
            p2_collection = db.get_collection(opponent_id)
            p1_uuids = p1_team_data[3] if p1_team_data else []
            p2_uuids = p2_team_data[3] if p2_team_data else []
            p1_map = {p.pokemon_uuid: p for p in p1_collection}
            p2_map = {p.pokemon_uuid: p for p in p2_collection}
            p1_team = [p1_map[uuid] for uuid in p1_uuids if uuid in p1_map]
            p2_team = [p2_map[uuid] for uuid in p2_uuids if uuid in p2_map]
        p1_active_team = [ActivePokemon(pokemon=p, actual_stats=get_actual_stats(p)) for p in p1_team]; p2_active_team = [ActivePokemon(pokemon=p, actual_stats=get_actual_stats(p)) for p in p2_team]
        player1 = BattlePlayer(user_id=challenger_id, user_name=challenger_user.first_name, team=p1_active_team)
        player2 = BattlePlayer(user_id=opponent_id, user_name=opponent_user.first_name, team=p2_active_team)

        battle = Battle(
            chat_id=call.message.chat.id, player1=player1, player2=player2,
            mode=settings['mode'], mega_evolution_allowed=settings['mega_enabled'],
            dynamax_allowed=settings['gmax_enabled'], is_ranked=settings['is_ranked'],
            sleep_clause_enabled=settings['sleep_clause_enabled'],
            generation=settings.get('random_battle_generation')
        )
        
        # --- RESTORED TERRAIN LOGIC ---
        ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
        terrains_path = os.path.join(ASSETS_DIR, 'terrains')
        available_terrains = [f for f in os.listdir(terrains_path) if f.endswith('.jpg')]
        if available_terrains:
            battle.terrain = random.choice(available_terrains)
        
        item_logic.apply_on_stat_calculation(player1.get_active_pokemon())
        item_logic.apply_on_stat_calculation(player2.get_active_pokemon())

        ability_effects.trigger_on_stat_calculation(player1.get_active_pokemon(), battle)
        ability_effects.trigger_on_stat_calculation(player2.get_active_pokemon(), battle)

        log1 = item_logic.apply_on_switch_in(player1.get_active_pokemon(), battle)
        log2 = item_logic.apply_on_switch_in(player2.get_active_pokemon(), battle)
        initial_log = (log1 + "\n" + log2).strip()

        # Trigger switch-in abilities at the start of the battle
        # We call get_move_order() directly to determine who is faster.
        turn_order = get_move_order(battle)
        faster_player, _ = turn_order[0]
        slower_player, _ = turn_order[1]
        
        initial_log += trigger_on_switch_in_abilities(faster_player.get_active_pokemon(), battle)
        initial_log += trigger_on_switch_in_abilities(slower_player.get_active_pokemon(), battle)
        # --- END OF CORRECTION ---

        image_bytes = await generate_battle_image(battle.player1.get_active_pokemon(), battle.player2.get_active_pokemon(), terrain=battle.terrain, folder='terrains')
        
        await bot.delete_message(call.message.chat.id, call.message.id)

        # --- RESTORED REPLY LOGIC ---
        try:
            sent_message = await bot.send_photo(
                chat_id=battle.chat_id, photo=image_bytes,
                caption="Get ready for battle!", parse_mode="HTML",
                reply_to_message_id=original_message_id
            )
        except Exception:
            sent_message = await bot.send_photo(
                chat_id=battle.chat_id, photo=image_bytes,
                caption="Get ready for battle!", parse_mode="HTML"
            )
        
        battle.message_id = sent_message.message_id
        battle.state = 'active'
        active_battles[call.message.chat.id].append(battle)

        await start_turn(bot, battle)
        full_log = f"{initial_log}\n\n--- Turn {battle.turn} ---" if initial_log else f"--- Turn {battle.turn} ---"
        await update_battle_ui(bot, battle, full_log)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('battle_accept_'))
    @user_not_banned(bot)
    async def handle_accept_challenge(call):
        """
        Handles the 'Accept Challenge' button click.
        This now sets up the battle and immediately starts the first turn.
        """
        try:
            user_who_clicked = call.from_user
            parts = call.data.split('_')
            
            challenger_id = int(parts[2])
            opponent_id = int(parts[3])

            mega_allowed = bool(int(parts[4])) if len(parts) > 4 else True
            dynamax_allowed = bool(int(parts[5])) if len(parts) > 5 else True
            original_message_id = int(parts[6]) if len(parts) > 6 else None

            if user_who_clicked.id != opponent_id:
                await bot.answer_callback_query(call.id, "This challenge is not for you.", show_alert=True)
                return

            await bot.answer_callback_query(call.id, "Preparing the arena...")
            await bot.edit_message_text(
                "✅ <b>Challenge Accepted!</b>\n\nLoading battle...",
                chat_id=call.message.chat.id,
                message_id=call.message.id,
                parse_mode="HTML"
            )
            
            challenger_user = await bot.get_chat(challenger_id)
            opponent_user = await bot.get_chat(opponent_id)
            
            challenger_team_data = db.get_active_team(challenger_id)
            opponent_team_data = db.get_active_team(opponent_id)

            challenger_team_uuids = challenger_team_data[3] if challenger_team_data else []
            opponent_team_uuids = opponent_team_data[3] if opponent_team_data else []
            
            challenger_collection = db.get_collection(challenger_id)
            opponent_collection = db.get_collection(opponent_id)
            
            challenger_map = {p.pokemon_uuid: p for p in challenger_collection}
            opponent_map = {p.pokemon_uuid: p for p in opponent_collection}
            
            challenger_team = [challenger_map[uuid] for uuid in challenger_team_uuids if uuid in challenger_map]
            opponent_team = [opponent_map[uuid] for uuid in opponent_team_uuids if uuid in opponent_map]
            
            challenger_active_team = [ActivePokemon(pokemon=p, actual_stats=get_actual_stats(p)) for p in challenger_team]
            opponent_active_team = [ActivePokemon(pokemon=p, actual_stats=get_actual_stats(p)) for p in opponent_team]

            is_ranked = bool(int(parts[7])) if len(parts) > 7 else False
            sleep_clause_enabled = bool(int(parts[8])) if len(parts) > 8 else True

            player1 = BattlePlayer(user_id=challenger_id, user_name=challenger_user.first_name, team=challenger_active_team)
            player2 = BattlePlayer(user_id=opponent_id, user_name=opponent_user.first_name, team=opponent_active_team)

            challenger_mode = db.get_battle_mode(challenger_id)
            
            # --- THIS IS THE FIX ---
            # 1. CREATE the battle object FIRST.
            battle = Battle(
                chat_id=call.message.chat.id,
                player1=player1,
                player2=player2,
                mode=challenger_mode,
                mega_evolution_allowed=mega_allowed,
                dynamax_allowed=dynamax_allowed,
                is_ranked=is_ranked,
                sleep_clause_enabled=sleep_clause_enabled
            )

            # 2. NOW, apply item logic using the created battle object.
            item_logic.apply_on_stat_calculation(player1.get_active_pokemon())
            item_logic.apply_on_stat_calculation(player2.get_active_pokemon())
            log1 = item_logic.apply_on_switch_in(player1.get_active_pokemon(), battle)
            log2 = item_logic.apply_on_switch_in(player2.get_active_pokemon(), battle)
            initial_log = (log1 + "\n" + log2).strip()
            # --- END OF FIX ---
            
            terrains_path = os.path.join(ASSETS_DIR, 'terrains')
            available_terrains = [f for f in os.listdir(terrains_path) if f.endswith('.jpg')]
            if available_terrains:
                battle.terrain = random.choice(available_terrains)
            
            image_bytes = await generate_battle_image(
                battle.player1.get_active_pokemon(),
                battle.player2.get_active_pokemon(),
                terrain=battle.terrain,
                folder='terrains'
            )
            
            await bot.delete_message(call.message.chat.id, call.message.id)

            # Now, try to send the battle message as a reply
            try:
                sent_message = await bot.send_photo(
                    chat_id=battle.chat_id,
                    photo=image_bytes,
                    caption="Get ready for battle!",
                    parse_mode="HTML",
                    reply_to_message_id=original_message_id
                )
            except Exception:
                # If replying fails for ANY reason, just send it as a normal message
                print("Failed to send battle message as a reply. Sending normally.")
                sent_message = await bot.send_photo(
                    chat_id=battle.chat.id,
                    photo=image_bytes,
                    caption="Get ready for battle!",
                    parse_mode="HTML"
                )
            
            battle.message_id = sent_message.message_id
            battle.state = 'active'
            active_battles[call.message.chat.id] = battle

            # Set up and draw the first turn UI
            await start_turn(bot, battle)
            full_log = f"{initial_log}\n\n--- Turn {battle.turn} ---" if initial_log else f"--- Turn {battle.turn} ---"
            await update_battle_ui(bot, battle, full_log)

        except Exception:
            traceback.print_exc()
            await bot.send_message(call.message.chat.id, "❌ An unexpected error occurred while starting the battle.")

    @bot.callback_query_handler(func=lambda call: call.data == 'b_zmove_prime')
    @user_not_banned(bot)
    async def handle_zmove_prime(call):
        """Primes the UI for Z-Move selection with a single-column layout showing Z-Move names."""
        battles_in_chat = active_battles.get(call.message.chat.id, [])
        battle = next((b for b in battles_in_chat if b.message_id == call.message.message_id), None)

        if not battle or battle.state != 'active':
            await bot.answer_callback_query(call.id, "This battle has ended.", show_alert=True)
            return

        user_id = call.from_user.id
        if user_id != battle.active_player_id:
            await bot.answer_callback_query(call.id, "It's not your turn!", show_alert=False)
            return

        # 1. Set the primed action state
        battle.primed_action = 'zmove'

        # 2. Get necessary data
        active_player = battle.get_player(user_id)
        active_pokemon = active_player.get_active_pokemon()
        
        # Get the type required by the held Z-Crystal
        item_id = ITEM_ID_BY_NAME.get(active_pokemon.pokemon.item, "")
        required_z_crystal_type = Z_CRYSTAL_TYPE_MAP.get(item_id)
        
        # 3. Build the new keyboard in a single column
        markup = types.InlineKeyboardMarkup(row_width=1) # Single column layout
        move_buttons = []

        for i, move_id in enumerate(active_pokemon.pokemon.moves):
            move_data = MOVE_BY_ID.get(move_id)
            if not move_data: continue
        
            is_compatible = False
            
            # 1. Check for Signature Z-Move compatibility (Pokemon + Item + Base Move)
            signature_info = SIGNATURE_Z_MOVES.get(move_id)
            if signature_info and ITEM_ID_BY_NAME.get(active_pokemon.pokemon.item) == signature_info['item_id']:
                is_compatible = True
                z_move_name = signature_info['z_move_name']
            
            # 2. Check for Generic Z-Move compatibility (Item Type + Base Move Type)
            elif required_z_crystal_type and move_data['type'] == required_z_crystal_type:
                is_compatible = True
                z_details = get_z_move_details(move_id)
                if z_details:
                    z_move_name = z_details['name']
                else:
                    # For Status Z-Moves (like Z-Hone Claws)
                    z_move_name = f"Z-{move_data['name']}"
                    
            button_text = ""
            callback_data = "b_noop" # Default to no operation
        
            if is_compatible:
                callback_data = f"b_m_{i}_zmove"
                # Use the determined Z-Move name
                button_text = f"⚡️ {z_move_name} ⚡️"
            else:
                # Show this as the normal move to indicate it's not a valid Z-Move option
                button_text = f"❌ {move_data['name']}" 
                callback_data = "b_noop" # Make it unclickable
        
            move_buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))

        markup.add(*move_buttons)
        markup.row(types.InlineKeyboardButton("⬅️ Cancel Z-Move", callback_data="b_back_moves"))

        # 4. Update the message with both the new caption and the new keyboard
        new_caption = generate_battle_caption(battle) # This will show Z-Move names in the text
        await bot.edit_message_caption(
            caption=new_caption,
            chat_id=call.message.chat.id,
            message_id=call.message.id,
            reply_markup=markup,
            parse_mode="HTML"
        )
        await bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == 'b_mega_prime')
    @user_not_banned(bot)
    async def handle_mega_prime(call):
        """Primes the move buttons for Mega Evolution."""
        battles_in_chat = active_battles.get(call.message.chat.id, [])
        battle = next((b for b in battles_in_chat if b.message_id == call.message.message_id), None)

        if not battle or battle.state != 'active':
            await bot.answer_callback_query(call.id, "This battle has ended.", show_alert=True)
            return

        user_id = call.from_user.id
        if user_id != battle.active_player_id:
            await bot.answer_callback_query(call.id, "It's not your turn!", show_alert=False)
            return

        active_player = battle.get_player(user_id)
        active_pokemon = active_player.get_active_pokemon()

        # Create a new keyboard with modified move buttons
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        move_buttons = []
        for i, move_id in enumerate(active_pokemon.pokemon.moves):
            move_data = MOVE_BY_ID.get(move_id)
            if move_data:
                # Change the text and callback data for the primed move
                button_text = f"✨ {move_data['name']} ✨"
                callback_data = f"b_m_{i}_mega" 
                move_buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))

        while len(move_buttons) < 4:
            move_buttons.append(types.InlineKeyboardButton(" ", callback_data="b_noop"))

        markup.add(*move_buttons)
        # Add a "Cancel" button to go back
        markup.row(types.InlineKeyboardButton("⬅️ Cancel Mega", callback_data="b_back_moves"))

        await bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.id,
            reply_markup=markup
        )
        await bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == 'b_formchange_prime')
    @user_not_banned(bot)
    async def handle_formchange_prime(call):
        """Primes the move buttons for an item-based form change."""
        battles_in_chat = active_battles.get(call.message.chat.id, [])
        battle = next((b for b in battles_in_chat if b.message_id == call.message.message_id), None)

        if not battle or battle.state != 'active': return await bot.answer_callback_query(call.id)

        user_id = call.from_user.id
        if user_id != battle.active_player_id:
            return await bot.answer_callback_query(call.id, "It's not your turn!", show_alert=False)

        active_player = battle.get_player(user_id)
        active_pokemon = active_player.get_active_pokemon()

        markup = types.InlineKeyboardMarkup(row_width=2)
        move_buttons = []
        for i, move_id in enumerate(active_pokemon.pokemon.moves):
            move_data = MOVE_BY_ID.get(move_id)
            if move_data:
                button_text = f"⚜️ {move_data['name']} ⚜️"
                callback_data = f"b_m_{i}_formchange"
                move_buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))
        
        while len(move_buttons) < 4:
            move_buttons.append(types.InlineKeyboardButton(" ", callback_data="b_noop"))

        markup.add(*move_buttons)
        markup.row(types.InlineKeyboardButton("⬅️ Cancel", callback_data="b_back_moves"))
        await bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup)
        await bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('b_'))
    @user_not_banned(bot)
    async def handle_battle_action(call):
        try:
            if await battle_callback_limiter.is_limited(
                call,
                bot,
                bypass=call.data.startswith("b_view_team_"),
            ):
                return

            battles_in_chat = active_battles.get(call.message.chat.id, [])
            battle = next((b for b in battles_in_chat if b.message_id == call.message.message_id), None)

            if not battle or battle.state != 'active':
                await bot.answer_callback_query(call.id, "This battle has ended.", show_alert=True)
                return
    
            # --- ADDED: The Turn Lock Check ---
            if battle.is_processing_turn:
                await bot.answer_callback_query(call.id, "Please wait, the turn is processing...", show_alert=False)
                return

            user_id = call.from_user.id
            parts = call.data.split('_')
            action = parts[1]

            # --- THIS IS THE CORRECTED PLACEMENT ---
            # Handle "View Team" FIRST, before checking for active turn.
            if action == "view" and parts[2] == "team":
                player_id_to_show = int(parts[3])

                if user_id != player_id_to_show:
                    await bot.answer_callback_query(call.id, "You can only view your own team.", show_alert=True)
                    return

                player = battle.get_player(player_id_to_show)
                if not player:
                    await bot.answer_callback_query(call.id, "Error: Player not found.", show_alert=True)
                    return

                team_lines = ["Your Team:"]
                for i, p in enumerate(player.team, 1):
                    faint_indicator = " 💀" if p.current_hp <= 0 else ""
                    team_lines.append(f"{i}. {p.pokemon.name}{faint_indicator}")

                team_status_text = "\n".join(team_lines)

                await bot.answer_callback_query(call.id, text=team_status_text, show_alert=True)
                return

            user_id = call.from_user.id
            if user_id != battle.active_player_id:
                await bot.answer_callback_query(call.id, "It's not your turn!", show_alert=False)
                return

            if battle.timer_task and call.from_user.id == battle.active_player_id:
                battle.timer_task.cancel()
    
            await bot.answer_callback_query(call.id)
            parts = call.data.split('_')
            action = parts[1]

            if call.data == 'b_dynamax_prime':
                player = battle.get_player(user_id)
                active_pokemon = player.get_active_pokemon()
                markup = prime_dynamax_buttons(active_pokemon)
                await bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                    reply_markup=markup
                )
                await bot.answer_callback_query(call.id)
                return

            if len(parts) > 3 and (parts[3] in ['mega', 'dynamax', 'formchange', 'zmove']):
                battle.is_processing_turn = True
                player = battle.get_player(user_id)
                pre_action_log = ""
    
                if parts[3] == 'mega':
                    pre_action_log = await execute_mega_evolution(bot, battle, player)
                elif parts[3] == 'dynamax':
                    pre_action_log = await execute_dynamax_transformation(bot, battle, player)
                # --- ADD THIS ELIF ---
                elif parts[3] == 'formchange':
                    pre_action_log = await execute_item_form_change(bot, battle, player)
                elif parts[3] == 'zmove':
                    # --- START: THIS IS THE CORRECTED Z-MOVE BLOCK ---
                    battle.is_processing_turn = True
                    player = battle.get_player(user_id)
                    attacker = player.get_active_pokemon()
                    base_move_id = attacker.pokemon.moves[int(parts[2])]
                    
                    z_move_id = None
                    z_move_name = None
                    log_message = ""
        
                    # Determine the Z-Move being used
                    signature_info = SIGNATURE_Z_MOVES.get(base_move_id)
                    item_id = ITEM_ID_BY_NAME.get(attacker.pokemon.item, "")
                    
                    if signature_info and item_id == signature_info['item_id']:
                        z_move_id = signature_info['z_move_id']
                        z_move_name = signature_info['z_move_name']
                    else:
                        z_details = get_z_move_details(base_move_id)
                        if z_details:
                            z_move_name = z_details['name']
                            base_move_data = MOVE_BY_ID[base_move_id]
                            z_move_id = TYPE_TO_Z_MOVE.get(base_move_data['type'], {}).get('id')
        
                    # Try to send the show-off image
                    show_off_sent = False
                    if z_move_id and z_move_name:
                        z_image_path = os.path.join(ASSETS_DIR, 'zmoves', f"{z_move_id}.png")
                        if os.path.exists(z_image_path):
                            
                            # --- THIS IS THE FIX ---
                            # Replaced <br><br> with \n\n
                            caption = (
                                f"<b>{player.user_name}</b> unleashes the full power of the Z-Ring!\n\n"
                                f"<b>{z_move_name}!</b>"
                            )
                            # --- END OF FIX ---
        
                            with open(z_image_path, 'rb') as photo:
                                await bot.send_photo(
                                    chat_id=battle.chat_id,
                                    photo=photo,
                                    caption=caption,
                                    parse_mode="HTML",
                                    reply_to_message_id=battle.message_id
                                )
                            show_off_sent = True
                            log_message = "" 
                    
                    # Fallback to a text message if no image was found
                    if not show_off_sent:
                        log_message = f"<b>{player.user_name}</b> is unleashing their full force with a Z-Move!"
                        await update_battle_ui(bot, battle, log_message, update_image=False)
                        await asyncio.sleep(1)
                    else:
                        await asyncio.sleep(2.5)
        
                    player.has_used_z_move = True
                    await turn_based_handler.process_turn_based_action(bot, battle, call, user_id, pre_action_log=log_message, action_type='zmove')
                    return
    
                await turn_based_handler.process_turn_based_action(bot, battle, call, user_id, pre_action_log=pre_action_log, action_type=parts[3])
                return
    
            # --- (Switching logic remains the same) ---
            if action == 'switchsel':
                # --- ADDED: Engage the lock ---
                battle.is_processing_turn = True
                switch_index = int(parts[2])
                player = battle.get_player(user_id)

                outgoing_pokemon = player.get_active_pokemon()
                if 'destinybond' in outgoing_pokemon.volatiles:
                    del outgoing_pokemon.volatiles['destinybond']

                if 'dynamax' in outgoing_pokemon.volatiles:
                    revert_dynamax(outgoing_pokemon)
                    log = f"{outgoing_pokemon.pokemon.name} returned to its normal size!\n"
                else:
                    log = ""

                if 'transformed' in outgoing_pokemon.volatiles:
                    from bot.battle.ability_effects.ability_logic import revert_transformation
                    revert_transformation(outgoing_pokemon)
            
                # --- Your original, correct variable definitions ---
                opponent_player, opponent_pokemon = battle.get_opponent_for_player(player)
                is_turn_ending_switch = battle.turn_phase in ['awaiting_voluntary_switch', 'awaiting_forced_switch']
            
                # --- MODIFIED: Logic for resetting/passing stats on switch ---
                outgoing_pokemon = player.get_active_pokemon()

                switch_out_log = ability_effects.trigger_on_switch_out(outgoing_pokemon, battle)
            
                # --- NEW: Check for Baton Pass data ---
                if battle.baton_pass_data:
                    incoming_pokemon = player.team[switch_index]
                    # Pass stat boosts
                    incoming_pokemon.boosts = battle.baton_pass_data['boosts']
                    # Pass specific, non-cleared volatiles
                    for v_status in ['substitute', 'focusenergy', 'leechseed', 'confusion']:
                         if v_status in battle.baton_pass_data['volatiles']:
                             incoming_pokemon.volatiles[v_status] = battle.baton_pass_data['volatiles'][v_status]
                    battle.baton_pass_data = None # Clear the data after passing it
                else:
                    # On a normal switch, clear boosts and volatiles
                    outgoing_pokemon.volatiles.clear()
                    outgoing_pokemon.boosts = {
                        'atk': 0, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 0,
                        'accuracy': 0, 'evasion': 0
                    }
                
                # --- Perform the switch ---
                player.active_pokemon_index = switch_index
                newly_active_pokemon = player.get_active_pokemon() # Get the full object for the new Pokémon
                newly_active_pokemon.active_turns = 0
                log = f"{player.user_name} sent out {newly_active_pokemon.pokemon.name}!"

                if player.slot_conditions.get('healing_wish'):
                    # Fully heal the incoming Pokémon's HP
                    newly_active_pokemon.current_hp = newly_active_pokemon.actual_stats['hp']
                    # Clear any major status conditions
                    newly_active_pokemon.status = None
                    newly_active_pokemon.status_counter = 0
                    
                    log += f"\n\nThe healing wish came true!"
                    
                    # IMPORTANT: Remove the flag so it doesn't trigger again
                    del player.slot_conditions['healing_wish']

                # --- NEW: HAZARD LOGIC INSERTED HERE ---
                hazard_results = hazard_logic.apply_hazard_effects(battle, player, newly_active_pokemon.pokemon)
                if hazard_results["damage"] > 0:
                    newly_active_pokemon.current_hp -= hazard_results["damage"]
                    log += f"\n{hazard_results['log']}"

                if hazard_results["status_effect"]:
                    newly_active_pokemon.status = hazard_results["status_effect"]
                    if hazard_results["status_effect"] == 'tox':
                        newly_active_pokemon.status_counter = 1
                    # If there was no damage, we still need to add the log message
                    if not hazard_results["damage"]:
                         log += f"\n{hazard_results['log']}"
                
                # NEW: Check if the Pokémon fainted immediately from hazards
                if newly_active_pokemon.current_hp <= 0:
                    log += f"\n{newly_active_pokemon.pokemon.name} fainted!"
                    # Check if this ends the battle or forces another switch
                    if await handle_faint(bot, battle, player):
                        log += f"\n\n🏆 {battle.winner.user_name} is the winner!"
                    # Update the UI to show the faint and stop further turn processing
                    await update_battle_ui(bot, battle, log, update_image=True)
                    # --- ADDED: Release the lock ---
                    battle.is_processing_turn = False
                    return
                # --- END OF NEW HAZARD LOGIC ---

                log += trigger_on_switch_in_abilities(newly_active_pokemon, battle)

                # --- Your original, correct logic for handling the rest of the turn ---
                if opponent_pokemon.current_hp <= 0 and battle.state == 'active':
                    log += f"\n{opponent_pokemon.pokemon.name} fainted!"
                    if not await handle_faint(bot, battle, opponent_player):
                        await update_battle_ui(bot, battle, log, update_image=True)
                        # --- ADDED: Release the lock ---
                        battle.is_processing_turn = False
                        return # STOP and wait for the second player.
                
                if is_turn_ending_switch:
                    battle.active_player_id = opponent_player.user_id
                    battle.turn_phase = 'awaiting_move'
                    await update_battle_ui(bot, battle, log, update_image=True)
                else:
                    await start_turn(bot, battle)
                    full_log = f"\n{log}\n\n--- Turn {battle.turn} ---"
                    await update_battle_ui(bot, battle, full_log, update_image=True)

                # --- ADDED: Release the lock before returning ---
                battle.is_processing_turn = False
                return
    
            if action == 's' and battle.turn_phase == 'awaiting_move':
                player = battle.get_player(user_id)
                active_pokemon = player.get_active_pokemon()
                if 'trap' in active_pokemon.volatiles:
                    # Acknowledge the button press so the UI doesn't hang
                    await bot.answer_callback_query(call.id)
                    # Create the message and update the battle caption
                    log = f"{active_pokemon.pokemon.name} can't switch out, it's trapped!"
                    await update_battle_ui(bot, battle, log)
                    return
                # This part is fine as it's a specific UI state change
                battle.turn_phase = 'awaiting_voluntary_switch'
                caption = generate_battle_caption(battle, f"{player.user_name}, choose a Pokémon to switch to.")
                keyboard = generate_switch_keyboard(battle, player)
                await bot.edit_message_caption(caption, battle.chat_id, battle.message_id, reply_markup=keyboard, parse_mode="HTML")
                return

            elif action == 'run':
                player = battle.get_player(user_id)
                battle.run_votes.add(user_id)
    
                if len(battle.run_votes) == 2:
                    battle.state = 'finished'
                    battle.winner = None # No winner for a draw
                    log = "Both players have agreed to a draw!"
                    await update_battle_ui(bot, battle, log)
                    _remove_battle(battle)
                else:
                    opponent = battle.get_opponent_for_player(player)[0]
                    log = f"{player.user_name} has voted to run. Waiting for {opponent.user_name}."
                    # Update the UI but the turn continues
                    await update_battle_ui(bot, battle, log)
                return

            elif action == 'recharge':
                # This is the new, dedicated handler for the recharge action
                battle.is_processing_turn = True
                player = battle.get_player(user_id)
                attacker = player.get_active_pokemon()
                
                # Clear the recharge status
                del attacker.volatiles['mustrecharge']
                
                # Determine if the turn is over
                is_turn_over = player.user_id == battle.turn_order[1][0].user_id
                recharge_log = f"{attacker.pokemon.name} must recharge!"
                
                if is_turn_over:
                    # The second player recharged, so end the turn
                    await update_battle_ui(bot, battle, recharge_log)
                    await asyncio.sleep(2.5) # Pause to show the message
                    
                    end_of_turn_log = await handle_end_of_turn_effects(battle)
                    final_log = recharge_log + ("\n" + end_of_turn_log if end_of_turn_log else "")
                    # (Add faint checks and other end-of-turn logic here if needed, or just start new turn)
                    
                    await start_turn(bot, battle)
                    await update_battle_ui(bot, battle, f"{final_log}\n\n--- Turn {battle.turn} ---")
                else:
                    # The first player recharged, pass the turn to the second player
                    battle.active_player_id = battle.turn_order[1][0].user_id
                    await update_battle_ui(bot, battle, recharge_log)
        
                battle.is_processing_turn = False
                return
            
            # --- NEW: Handle the "Forfeit" action ---
            elif action == 'forfeit':
                player = battle.get_player(user_id)
                opponent = battle.get_opponent_for_player(player)[0]
    
                battle.winner = opponent
                battle.state = 'finished'
                log = f"{player.user_name} has forfeited the match!"
                await update_battle_ui(bot, battle, log)
                _remove_battle(battle)
                return

            elif action == 'back' and parts[2] == 'moves':
                player = battle.get_player(user_id)
                battle.turn_phase = 'awaiting_move'
                battle.primed_action = None
                await update_battle_ui(bot, battle, f"{player.user_name}, choose an action.")
                return
    
            # --- REFINED: Logic for executing a MOVE ---
            if action == 'm' and battle.turn_phase == 'awaiting_move':
                # This block is now a simple dispatcher.
                if battle.mode == 'showdown':
                    await showdown_handler.process_showdown_action(bot, battle, call, user_id)
                else: # Default to 'turn-based'
                    await turn_based_handler.process_turn_based_action(bot, battle, call, user_id)
        except Exception:
            traceback.print_exc()
            if 'battle' in locals() and battle and battle.chat_id in active_battles:
                await bot.edit_message_caption("An error occurred. Battle terminated.", battle.chat_id, battle.message_id)
                _remove_battle(battle)

async def process_battle_turn(bot: AsyncTeleBot, battle: Battle):
    """Processes one full turn of the battle."""
    
    move_order = get_move_order(battle)
    
    # Get the active Pokémon for each player correctly at the start of the turn
    p1_active_poke = battle.player1.get_active_pokemon()
    p2_active_poke = battle.player2.get_active_pokemon()
    
    if battle.turn == 1:
        p1_speed = p1_active_poke.actual_stats['spe']
        p2_speed = p2_active_poke.actual_stats['spe']
        full_log = f"Speed Check: {battle.player1.user_name} ({p1_speed}) vs {battle.player2.user_name} ({p2_speed})\n\n"
    else:
        full_log = ""
    
    full_log += f"--- Turn {battle.turn} ---\n"

    for i, (player, attacker, move_id) in enumerate(move_order):
        # Determine the defender correctly based on the current attacker
        defender_player = battle.player2 if player.user_id == battle.player1.user_id else battle.player1
        defender = defender_player.get_active_pokemon()
                
        damage, effectiveness, did_hit = calculate_damage(attacker, defender, move_id)
        
        if not did_hit:
            log_entry = f"{attacker.pokemon.name}'s {MOVE_BY_ID[move_id]['name']} missed!"
        else:
            defender.current_hp = max(0, defender.current_hp - damage)
            log_entry = f"{attacker.pokemon.name} used {MOVE_BY_ID[move_id]['name']}!"
            if effectiveness > 1: log_entry += " It's super effective!"
            elif 0 < effectiveness < 1: log_entry += " It's not very effective..."
            elif effectiveness == 0: log_entry += " It had no effect!"
        
        full_log += log_entry + "\n"

        caption = generate_battle_caption(battle, full_log)
        await bot.edit_message_caption(caption, battle.chat_id, battle.message_id, parse_mode="HTML")
        
        if defender.current_hp <= 0:
            full_log += f"<b>{defender.pokemon.name} fainted!</b>\n"
            await handle_faint(bot, battle, defender_player) 
            return

        if i == 0 and len(move_order) > 1:
            await asyncio.sleep(2.5)
    
    await start_turn(bot, battle)
    full_log += f"\n--- Turn {battle.turn} ---"
    await update_battle_ui(bot, battle, full_log)

async def handle_delayed_effects(bot: AsyncTeleBot, battle: Battle) -> Tuple[str, bool]:
    """
    Checks for and executes delayed moves like Future Sight at the end of a turn.
    Returns a log of what happened and a boolean indicating if a faint occurred.
    """
    from .battle_logic import get_modified_stat, get_type_effectiveness # Local import
    
    log_parts = []
    faint_occurred = False
    
    for effect in battle.delayed_effects[:]:
        if battle.turn == effect['turn_to_hit']:
            log_parts.append(f"\nThe {MOVE_BY_ID[effect['move_id']]['name']} attack hit!")
            
            origin_player = battle.get_player(effect['origin_player_id'])
            target_player = battle.get_player(effect['target_player_id'])

            if not origin_player or not target_player:
                battle.delayed_effects.remove(effect)
                continue

            attacker = origin_player.get_active_pokemon()
            defender = target_player.get_active_pokemon()
            move_data = MOVE_BY_ID[effect['move_id']]
            
            # Perform the damage calculation
            power = move_data.get('basePower', 0)
            level = attacker.pokemon.level

            # --- THIS IS THE FIX ---
            # Call get_modified_stat with the Pokémon object, not just numbers.
            attack = get_modified_stat(attacker, 'spa')
            defense = get_modified_stat(defender, 'spd')
            
            # The simple damage formula is used directly. We no longer check if effectiveness is 0.
            # This allows the move to hit immune Pokémon like Dark-types.
            damage = int(((((2 * level / 5) + 2) * power * attack / defense) / 50) + 2)
            random_modifier = random.uniform(0.85, 1.0)
            # We still apply effectiveness for super/not very effective, but the move will no longer be stopped by immunity.
            effectiveness = get_type_effectiveness(move_data['type'], defender.pokemon.types, battle, attacker=attacker)
            damage = int(damage * effectiveness * random_modifier) 
            damage = max(1, damage)
            
            defender.current_hp = max(0, defender.current_hp - damage)
            log_parts.append(f"It dealt {damage} damage!")
            # --- END OF FIX ---
            
            if defender.current_hp <= 0:
                faint_occurred = True
                log_parts.append(f"{defender.pokemon.name} fainted!")
                if await handle_faint(bot, battle, target_player):
                    log_parts.append(f"\n\n🏆 {battle.winner.user_name} is the winner!")
            
            battle.delayed_effects.remove(effect)
            
    return "\n".join(log_parts), faint_occurred

def _remove_battle(battle: Battle):
    if battle.chat_id in active_battles:
        if battle in active_battles[battle.chat_id]:
            active_battles[battle.chat_id].remove(battle)
        if not active_battles[battle.chat_id]:
            del active_battles[battle.chat_id]
