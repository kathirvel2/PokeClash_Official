# ./bot/battle/dynamax/dynamax_utils.py
from typing import TYPE_CHECKING
from bot.mechanics.moves_loader import SPECIES_BY_ID

if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, BattlePlayer

def can_dynamax(player: "BattlePlayer", battle: "Battle") -> bool:
    """Checks if a player's active Pokémon can Dynamax."""
    
    if battle.generation is not None and battle.generation != 0 and battle.generation < 8:
        return False

    if not battle.dynamax_allowed:
        return False
    # 1. Has the player already used Dynamax in this battle?
    if player.has_dynamaxed:
        return False

    # 2. Is it past the allowed turn limit? (Optional rule, but common)
    # if battle.turn > 3:
    #     return False

    # 3. Does the species data explicitly forbid Dynamax?
    active_pokemon = player.get_active_pokemon()
    species_data = SPECIES_BY_ID.get(active_pokemon.pokemon.id, {})
    if species_data.get("cannotDynamax", False):
        return False

    return True

def get_gmax_form(base_species_id: str) -> str | None:
    """Finds the G-Max form ID for a given base species ID."""
    gmax_id = f"{base_species_id}gmax" 
    if gmax_id in SPECIES_BY_ID:
        return gmax_id
    return None