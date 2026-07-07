# ./bot/battle/dynamax/dynamax_logic.py
import math
from typing import TYPE_CHECKING
from bot.mechanics.moves_loader import SPECIES_BY_ID
from .dynamax_utils import get_gmax_form

if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, BattlePlayer, ActivePokemon

def execute_dynamax(player: "BattlePlayer", battle: "Battle") -> tuple[str, str | None]:
    """
    Transforms the active Pokémon, doubles its HP, and sets battle flags.
    Returns a log message and the new G-Max species ID if applicable.
    """
    active_pokemon = player.get_active_pokemon()
    original_name = active_pokemon.pokemon.name

    # 1. Double HP
    hp_ratio = active_pokemon.current_hp / active_pokemon.actual_stats['hp']
    active_pokemon.actual_stats['hp'] *= 2
    active_pokemon.current_hp = math.ceil(active_pokemon.actual_stats['hp'] * hp_ratio)

    # 2. Set Dynamax state on the Pokémon
    active_pokemon.volatiles['dynamax'] = {'turns': 3}

    # 3. Set battle-wide flag for the player
    player.has_dynamaxed = True
    player.has_mega_evolved = True

    # 4. Check for and apply G-Max form change
    gmax_species_id = get_gmax_form(active_pokemon.pokemon.id)
    if 'choice_locked_move' in active_pokemon.volatiles:
        del active_pokemon.volatiles['choice_locked_move']
        log_suffix = f"\nIts {active_pokemon.pokemon.item} was suppressed by the Dynamax energy!"
    else:
        log_suffix = ""
        
    if gmax_species_id:
        gmax_species_data = SPECIES_BY_ID[gmax_species_id]
        active_pokemon.pokemon.id = gmax_species_id
        active_pokemon.pokemon.name = gmax_species_data['name']
        log_msg = f"{player.user_name}'s {original_name} has Gigantamaxed!"
        return log_msg, gmax_species_id
    else:
        log_msg = f"{player.user_name}'s {original_name} has Dynamaxed!"
        return log_msg, None

def revert_dynamax(pokemon: "ActivePokemon"):
    """Reverts a Pokémon from its Dynamax state."""
    if 'dynamax' not in pokemon.volatiles:
        return

    # Revert HP
    hp_ratio = pokemon.current_hp / pokemon.actual_stats['hp']
    pokemon.actual_stats['hp'] //= 2

    # --- THIS IS THE FIX ---
    # If the Pokémon had 0 HP before reverting, its HP should remain 0.
    if hp_ratio <= 0:
        pokemon.current_hp = 0
    else:
        # Otherwise, calculate the new HP and ensure it's at least 1.
        pokemon.current_hp = max(1, int(hp_ratio * pokemon.actual_stats['hp']))
    # --- END OF FIX ---

    # Revert form if it was a G-Max (or to reset a base form to itself)
    species_data = SPECIES_BY_ID.get(pokemon.pokemon.id, {})
    
    base_species_name = species_data.get("baseSpecies")
    
    if base_species_name:
        base_species_id = base_species_name.lower().replace(" ", "").replace("-", "")
        base_species_data = SPECIES_BY_ID.get(base_species_id)
        if base_species_data:
            pokemon.pokemon.id = base_species_id
            pokemon.pokemon.name = base_species_data['name']

    del pokemon.volatiles['dynamax']