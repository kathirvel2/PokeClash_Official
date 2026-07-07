# ./bot/battle/ability_effects/form_change_logic.py
import math
import os
from typing import TYPE_CHECKING
from telebot.async_telebot import AsyncTeleBot
from bot.mechanics.moves_loader import SPECIES_BY_ID
from bot.mechanics.team import Stats, Pokemon
from bot.battle.battle_utils import get_actual_stats, find_best_sprite_path
from bot.battle.battle_engine import ActivePokemon
from bot.mechanics.team import Stats, Pokemon, create_pokemon

if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, ActivePokemon, BattlePlayer

async def send_show_off_image(bot: AsyncTeleBot, battle: "Battle", pokemon: "ActivePokemon", caption: str):
    """Finds the artwork for a Pokémon and sends it as a notification."""
    artwork_path = find_best_sprite_path(pokemon.pokemon, 'image')
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

async def _transform_pokemon(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", target_form_id: str, log_message: str) -> str:
    """Core logic to transform a Pokémon, update stats, and send a notification."""

    if pokemon.pokemon.id == target_form_id:
        return ""
    
    new_form_data = SPECIES_BY_ID.get(target_form_id)
    if not new_form_data:
        return ""

    # --- THIS IS THE FIX ---
    # 1. Create a full, temporary Pokemon object using the factory.
    temp_pokemon_for_image = create_pokemon(
        species_id=new_form_data['id'],
        is_shiny=bool(getattr(pokemon.pokemon, 'is_shiny', False)),
    )
    # 2. Calculate its actual stats so it has a valid 'hp' key.
    temp_actual_stats = get_actual_stats(temp_pokemon_for_image)
    # 3. Create the temporary ActivePokemon with real stats, preventing the crash.
    await send_show_off_image(bot, battle, ActivePokemon(pokemon=temp_pokemon_for_image, actual_stats=temp_actual_stats), log_message)
    # --- END OF FIX ---

    # --- THIS IS THE HP PRESERVATION LOGIC (ALREADY CORRECT) ---
    # It ensures the Pokémon does NOT get a free heal.
    old_max_hp = pokemon.actual_stats['hp']
    hp_ratio = pokemon.current_hp / old_max_hp
    # --- END OF HP LOGIC PREVIEW ---

    # Transform the actual Pokémon object in the battle
    pokemon.pokemon.id = new_form_data['id']
    pokemon.pokemon.name = new_form_data['name']
    pokemon.pokemon.types = new_form_data['types']
    
    new_base_stats_data = new_form_data["baseStats"].copy()
    if 'def' in new_base_stats_data:
        new_base_stats_data['def_'] = new_base_stats_data.pop('def')
    pokemon.pokemon.base_stats = Stats(**new_base_stats_data)
    
    # Recalculate stats for the *real* Pokémon
    pokemon.actual_stats = get_actual_stats(pokemon.pokemon)
    
    # Apply the saved HP ratio to the new, higher max HP
    pokemon.current_hp = math.ceil(pokemon.actual_stats['hp'] * hp_ratio)
    
    pokemon.volatiles['transformed'] = True # Prevent re-transforming

    return log_message

async def handle_battle_bond(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str) -> str:
    """Handles Greninja's Battle Bond transformation."""
    if event != 'on_ko':
        return ""

    if 'transformed' in pokemon.volatiles:
        return "" # Already transformed

    # Transform Greninja to Ash-Greninja
    return await _transform_pokemon(bot, battle, pokemon, 'greninjaash', f"<b>{pokemon.pokemon.name} became Ash-Greninja!</b>")

async def handle_zen_mode(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str) -> str:
    """Handles Darmanitan's Zen Mode transformation for both Unovan and Galarian forms."""
    if event != 'on_end_of_turn':
        return ""

    current_id = pokemon.pokemon.id
    hp_percent = (pokemon.current_hp / pokemon.actual_stats['hp']) * 100
    target_form_id = None
    log_message = ""

    is_galarian = 'galar' in current_id
    
    # Define the forms for clarity
    standard_form = 'darmanitangalar' if is_galarian else 'darmanitan'
    zen_form = 'darmanitangalarzen' if is_galarian else 'darmanitanzen'

    # If below 50% HP and in Standard form, change to Zen.
    if hp_percent <= 50 and current_id == standard_form:
        target_form_id = zen_form
        log_message = f"<b>{pokemon.pokemon.name} entered Zen Mode!</b>"
        
    # If above 50% HP and in Zen form, change back to Standard.
    elif hp_percent > 50 and current_id == zen_form:
        target_form_id = standard_form
        log_message = f"<b>{pokemon.pokemon.name} calmed down and reverted to its Standard Form!</b>"

    if target_form_id:
        return await _transform_pokemon(bot, battle, pokemon, target_form_id, log_message)
        
    return ""

async def handle_shields_down(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str) -> str:
    """Handles Minior's Shields Down transformation whenever its HP changes."""
    if event not in ['on_residual', 'on_after_move']:
        return ""

    hp_percent = (pokemon.current_hp / pokemon.actual_stats['hp']) * 100
    target_form_id = None

    if hp_percent <= 50 and pokemon.pokemon.id.startswith('miniormeteor'):
        color = pokemon.pokemon.id.replace('miniormeteor', '')
        target_form_id = f'minior{color}'
        log_message = f"<b>{pokemon.pokemon.name}'s shell broke!</b>"
        
    elif hp_percent > 50 and not pokemon.pokemon.id.startswith('miniormeteor'):
        color = pokemon.pokemon.id.replace('minior', '')
        target_form_id = f'miniormeteor{color}'
        log_message = f"<b>{pokemon.pokemon.name} reformed its shell!</b>"

    if target_form_id:
        return await _transform_pokemon(bot, battle, pokemon, target_form_id, log_message)
        
    return ""

async def handle_zero_to_hero(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str) -> str:
    """Handles Palafin's Zero to Hero transformation on its first move."""
    # This ability only triggers before a move is used.
    if event != 'on_before_move':
        return ""

    # Check if the pokemon is in its base form and has not transformed yet.
    if pokemon.pokemon.id == 'palafin' and 'transformed' not in pokemon.volatiles:
        log_message = f"<b>{pokemon.pokemon.name} transformed into its Hero Form!</b>"
        # The _transform_pokemon helper handles the change and prevents re-transformation.
        return await _transform_pokemon(bot, battle, pokemon, 'palafinhero', log_message)
    
    return ""


async def handle_stance_change(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str, move_category: str) -> str:
    """Handles Aegislash's Stance Change as a one-time transformation."""
    # Only triggers before a move is used, and only if the move is a damaging one.
    if event != 'on_before_move' or move_category == 'Status':
        return ""

    # Check if the pokemon is in its base Shield Forme and has not transformed yet.
    if pokemon.pokemon.id == 'aegislash' and 'transformed' not in pokemon.volatiles:
        log_message = f"<b>{pokemon.pokemon.name} changed to Blade Forme!</b>"
        # The _transform_pokemon helper handles the change and sets the 'transformed' volatile to prevent it from happening again.
        return await _transform_pokemon(bot, battle, pokemon, 'aegislashblade', log_message)
    
    return ""

async def handle_power_construct(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str) -> str:
    """Handles Zygarde's Power Construct transformation when HP is low."""
    # This check can happen after taking damage or at the end of the turn.
    if event not in ['on_after_move', 'on_end_of_turn']:
        return ""

    # Check if the Pokémon is a Zygarde, its HP is below 50%, and it hasn't transformed yet.
    is_zygarde = 'zygarde' in pokemon.pokemon.id # Catches 10% and 50% forms
    hp_percent = (pokemon.current_hp / pokemon.actual_stats['hp']) * 100

    if is_zygarde and hp_percent <= 50 and 'transformed' not in pokemon.volatiles:
        log_message = f"<b>You sense the presence of many! {pokemon.pokemon.name} transformed into its Complete Forme!</b>"
        return await _transform_pokemon(bot, battle, pokemon, 'zygardecomplete', log_message)

    return ""

# --- THE MAIN ROUTER FUNCTION ---
FORM_CHANGE_ABILITIES = {
    'battlebond': handle_battle_bond,
    'zenmode': handle_zen_mode,
    'shieldsdown': handle_shields_down,
    'zerotohero': handle_zero_to_hero,
    'stancechange': handle_stance_change,
    'powerconstruct': handle_power_construct,
}

async def check_for_form_change(bot: "AsyncTeleBot", battle: "Battle", pokemon: "ActivePokemon", event: str, move_category: str = None) -> str:
    """Checks if a Pokémon's ability triggers a form change based on a battle event."""
    ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
    
    if ability_id in FORM_CHANGE_ABILITIES:
        handler = FORM_CHANGE_ABILITIES[ability_id]
        # Special case for Stance Change which needs to know the move category
        if ability_id == 'stancechange':
            return await handler(bot, battle, pokemon, event, move_category)
        else:
            # All other handlers use the standard call signature
            return await handler(bot, battle, pokemon, event)
            
    return ""
