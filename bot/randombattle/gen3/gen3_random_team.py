# File: bot/randombattle/gen3/gen3_random_team.py

import os
import json
import random
from typing import List, Dict, Any, Set

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID, NATURES_DATA

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen3_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN3_RANDOM_DATA: Dict[str, Any] = json.load(f)

ALL_NATURES = list(NATURES_DATA.keys())

def _calculate_gen3_ivs(moves: Set[str]) -> Stats:
    """Calculates IVs for Gen 3, which are all 31 except for Hidden Power."""
    ivs = {'hp': 31, 'atk': 31, 'def_': 31, 'spa': 31, 'spd': 31, 'spe': 31}
    hp_move = next((m for m in moves if m.startswith('hiddenpower')), None)
    if not hp_move:
        return Stats(**ivs)
    
    # This is a simplified mapping for Gen 3 Hidden Power IVs.
    hp_type_ivs = {
        'fighting': {'def_': 30, 'spa': 30, 'spd': 30, 'spe': 30},
        'flying': {'def_': 30, 'spa': 30, 'spd': 30, 'spe': 30, 'hp': 30},
        'poison': {'def_': 30, 'spa': 30, 'spd': 30, 'atk': 30},
        'ground': {'spa': 30, 'spd': 30},
        'rock': {'spa': 30, 'spd': 30, 'def_': 30},
        'bug': {'spa': 30, 'spd': 30, 'atk': 30},
        'ghost': {'spa': 30, 'spd': 30, 'def_': 30, 'atk': 30},
        'steel': {'spd': 30},
        'fire': {'spd': 30, 'atk': 30},
        'water': {'spd': 30, 'def_': 30},
        'grass': {'spd': 30, 'def_': 30, 'atk': 30},
        'electric': {'atk': 30},
        'psychic': {'def_': 30},
        'ice': {'def_': 30, 'atk': 30},
        'dragon': {'def_': 30, 'spa': 30},
        'dark': {}, # All 31s
    }
    
    hp_type = hp_move[11:]
    if hp_type in hp_type_ivs:
        ivs.update(hp_type_ivs[hp_type])
        
    return Stats(**ivs)

def _generate_pokemon_from_set(species_id: str, chosen_set: Dict[str, Any]) -> Pokemon:
    """Creates a single Pokémon from a specific, pre-selected set."""
    species_data = GEN3_RANDOM_DATA[species_id]
    move_pool = list(set(chosen_set["movepool"]))

    # 1. Select moveset, prioritizing preferred types for Hidden Power
    preferred_hp_type = chosen_set.get("preferredTypes", [None])[0]
    
    # Separate Hidden Powers from other moves
    hp_moves = [m for m in move_pool if m.startswith('hiddenpower')]
    other_moves = [m for m in move_pool if not m.startswith('hiddenpower')]
    
    temp_moveset = set()
    
    # Try to add the preferred HP type if one exists and is available
    if preferred_hp_type:
        preferred_hp_move = f"hiddenpower{preferred_hp_type.lower()}"
        if preferred_hp_move in hp_moves:
            temp_moveset.add(preferred_hp_move)
            hp_moves.remove(preferred_hp_move)

    # Fill remaining slots
    remaining_pool = other_moves + hp_moves
    while len(temp_moveset) < 4 and remaining_pool:
        temp_moveset.add(remaining_pool.pop(random.randrange(len(remaining_pool))))

    # 2. Calculate IVs using the specific Hidden Power type BEFORE replacing the ID.
    ivs = _calculate_gen3_ivs(temp_moveset)

    # 3. Create the final moveset, replacing specific HP IDs with the generic one.
    final_moveset = {'hiddenpower' if move.startswith('hiddenpower') else move for move in temp_moveset}

    # --- Finalize Pokémon Object ---
    new_pokemon = create_pokemon(species_id=species_id)
    new_pokemon.level = species_data.get('level', 100)
    new_pokemon.moves = list(final_moveset)
    
    # Gen 3 Random Battle Standard: Max EVs
    new_pokemon.evs = Stats(hp=252, atk=252, def_=252, spa=252, spd=252, spe=252)
    new_pokemon.ivs = ivs
    
    # Gen 3 Mechanics: Abilities and Natures
    new_pokemon.ability = random.choice(chosen_set.get("abilities", ["No Ability"]))
    new_pokemon.nature = random.choice(ALL_NATURES).capitalize()
    
    # Gen 3 Random Battles typically do not use items
    new_pokemon.item = None 
    
    return new_pokemon

def generate() -> List[Pokemon]:
    """The main entry point to generate a complete and diverse Gen 3 random battle team."""
    team: List[Pokemon] = []
    
    all_possible_sets = []
    for species_id, data in GEN3_RANDOM_DATA.items():
        for individual_set in data.get("sets", []):
            all_possible_sets.append((species_id, individual_set))

    random.shuffle(all_possible_sets)

    team_species_ids = set()
    role_counts = {}
    MAX_PER_ROLE = 2 # Encourages variety by limiting duplicate roles

    for species_id, chosen_set in all_possible_sets:
        if len(team) >= 6:
            break
        if species_id in team_species_ids:
            continue

        role = chosen_set.get("role", "Unknown")
        if role_counts.get(role, 0) >= MAX_PER_ROLE:
            continue
            
        new_pokemon = _generate_pokemon_from_set(species_id, chosen_set)
        
        if new_pokemon.moves and len(new_pokemon.moves) >= 4:
            team.append(new_pokemon)
            team_species_ids.add(species_id)
            role_counts[role] = role_counts.get(role, 0) + 1

    # Failsafe: If the diversity logic resulted in an incomplete team, fill it.
    while len(team) < 6 and all_possible_sets:
        species_id, chosen_set = all_possible_sets.pop(0)
        if species_id not in team_species_ids:
             new_pokemon = _generate_pokemon_from_set(species_id, chosen_set)
             if new_pokemon.moves and len(new_pokemon.moves) >= 4:
                team.append(new_pokemon)
                team_species_ids.add(species_id)

    return team