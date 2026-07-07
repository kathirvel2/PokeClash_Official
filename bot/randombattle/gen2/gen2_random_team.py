import os
import json
import random
from typing import List, Dict, Any, Set, Tuple

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen2_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN2_RANDOM_DATA: Dict[str, Any] = json.load(f)

# (Helper functions for IVs, item, and level remain the same as they are correct)
def _get_item(species_id: str, moves: Set[str], role: str) -> str:
    if species_id == 'ditto': return 'Metal Powder'
    if species_id == 'marowak': return 'Thick Club'
    if species_id == 'pikachu': return 'Light Ball'
    if 'thief' in moves: return ''
    if 'rest' in moves and 'sleeptalk' not in moves and "Bulky" not in role: return 'Mint Berry'
    if 'bellydrum' in moves and 'rest' not in moves and random.random() < 0.5: return 'Miracle Berry'
    return 'Leftovers'

def _calculate_hp_ivs(moves: Set[str]) -> Stats:
    ivs = {'hp': 30, 'atk': 30, 'def_': 30, 'spa': 30, 'spd': 30, 'spe': 30}
    hp_move = next((m for m in moves if m.startswith('hiddenpower')), None)
    if not hp_move:
        return Stats(**ivs)
    hp_type = hp_move[11:]
    hp_iv_map = {
        'dragon': {'def_': 28}, 'ice': {'def_': 26}, 'psychic': {'def_': 24}, 'electric': {'atk': 28},
        'grass': {'atk': 28, 'def_': 28}, 'water': {'atk': 28, 'def_': 26}, 'fire': {'atk': 28, 'def_': 24},
        'steel': {'atk': 26}, 'ghost': {'atk': 26, 'def_': 28}, 'bug': {'atk': 26, 'def_': 26},
        'rock': {'atk': 26, 'def_': 24}, 'ground': {'atk': 24}, 'poison': {'atk': 24, 'def_': 28},
        'flying': {'atk': 24, 'def_': 26}, 'fighting': {'atk': 24, 'def_': 24},
    }
    if hp_type in hp_iv_map: ivs.update(hp_iv_map[hp_type])
    hp_dv = 0
    if ivs['atk'] % 4 >= 2: hp_dv += 8
    if ivs['def_'] % 4 >= 2: hp_dv += 4
    if ivs['spe'] % 4 >= 2: hp_dv += 2
    if ivs['spa'] % 4 >= 2: hp_dv += 1
    ivs['hp'] = hp_dv * 2
    return Stats(**ivs)

def _generate_pokemon_from_set(species_id: str, chosen_set: Dict[str, Any]) -> Pokemon:
    """
    Creates a single Pokémon from a specific, pre-selected set, correcting Hidden Power IDs.
    """
    species_data = GEN2_RANDOM_DATA[species_id]
    role = chosen_set["role"]
    move_pool = list(set(chosen_set["movepool"]))

    # 1. Select 4 moves from the pool, which might include 'hiddenpowerwater', etc.
    if len(move_pool) <= 4:
        temp_moveset = set(move_pool)
    else:
        temp_moveset = set(random.sample(move_pool, 4))

    # 2. Calculate IVs using the specific Hidden Power type (e.g., 'hiddenpowerwater')
    # This must be done BEFORE we replace the move ID.
    ivs = _calculate_hp_ivs(temp_moveset)

    # 3. Create the final moveset, replacing specific Hidden Powers with the generic one.
    final_moveset = set()
    for move in temp_moveset:
        if move.startswith('hiddenpower'):
            final_moveset.add('hiddenpower')
        else:
            final_moveset.add(move)

    # --- Finalize Pokémon Object ---
    new_pokemon = create_pokemon(species_id=species_id)
    new_pokemon.level = species_data.get('level', 100)
    new_pokemon.moves = list(final_moveset) # Use the corrected moveset
    new_pokemon.evs = Stats(hp=255, atk=255, def_=255, spa=255, spd=255, spe=255)
    new_pokemon.ivs = ivs # Use the correctly calculated IVs
    new_pokemon.nature = "Serious"
    new_pokemon.ability = "No Ability"
    new_pokemon.item = _get_item(species_id, final_moveset, role)
    
    return new_pokemon

def generate() -> List[Pokemon]:
    """
    The main entry point to generate a complete and diverse Gen 2 random battle team.
    """
    team: List[Pokemon] = []
    
    # --- 1. Create a flat list of all Pokémon species available ---
    all_pokemon_ids = list(GEN2_RANDOM_DATA.keys())
    random.shuffle(all_pokemon_ids)
    
    # --- 2. Build the team, ensuring no duplicate species ---
    team_species_ids = set()

    for species_id in all_pokemon_ids:
        if len(team) >= 6:
            break

        # Rule: Don't add the same Pokémon species twice
        if species_id in team_species_ids:
            continue

        # Pick a random moveset for the chosen Pokémon
        species_data = GEN2_RANDOM_DATA[species_id]
        if not species_data.get("sets"):
            continue # Skip if this entry has no defined sets
            
        chosen_set = random.choice(species_data["sets"])
            
        # Generate the Pokémon from that set
        new_pokemon = _generate_pokemon_from_set(species_id, chosen_set)
        
        # Final check to ensure the generated Pokémon has moves
        if new_pokemon.moves:
            team.append(new_pokemon)
            team_species_ids.add(species_id)

    # This failsafe is unlikely to be needed with the new logic but is good practice
    while len(team) < 6 and all_pokemon_ids:
        species_id = all_pokemon_ids.pop(0)
        if species_id not in team_species_ids:
             chosen_set = random.choice(GEN2_RANDOM_DATA[species_id]["sets"])
             new_pokemon = _generate_pokemon_from_set(species_id, chosen_set)
             if new_pokemon.moves:
                team.append(new_pokemon)
                team_species_ids.add(species_id)

    return team