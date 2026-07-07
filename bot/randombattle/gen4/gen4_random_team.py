# File: bot/randombattle/gen4/gen4_random_team.py

import os
import json
import random
from typing import List, Dict, Any, Set, Tuple

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID, NATURES_DATA, SPECIES_BY_ID

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen4_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN4_RANDOM_DATA: Dict[str, Any] = json.load(f)

ALL_NATURES = list(NATURES_DATA.keys())

# Helper constants from the teams.ts logic
SETUP = ['swordsdance', 'dragondance', 'calmmind', 'bulkup', 'curse', 'nastyplot', 'agility', 'rockpolish', 'tailglow', 'bellydrum']
NO_STAB = ['fakeout', 'knockoff', 'rapidspin', 'suckerpunch', 'uturn', 'explosion', 'selfdestruct', 'pursuit']

def _generate_pokemon_set(species_id: str, species_data: Dict[str, Any]) -> Pokemon:
    """Creates a single, complete Pokémon set for Gen 4."""
    
    # --- 1. Create Base Pokémon & Choose Set ---
    temp_pokemon = create_pokemon(species_id=species_id)
    pokemon_types = temp_pokemon.types
    base_stats = temp_pokemon.base_stats
    
    chosen_set = random.choice(species_data["sets"])
    move_pool = list(set(chosen_set["movepool"]))
    random.shuffle(move_pool)
    
    moveset: Set[str] = set()
    
    # --- 2. Intelligent Move Selection ---
    
    # Categorize moves
    stab_moves = []
    setup_moves = []
    other_moves = []

    for move_id in move_pool:
        move_data = MOVE_BY_ID.get(move_id)
        if not move_data: continue
        
        if move_id in SETUP:
            setup_moves.append(move_id)
        elif move_data.get('type') in pokemon_types and move_id not in NO_STAB:
            stab_moves.append(move_id)
        else:
            other_moves.append(move_id)
    
    # Add one STAB move
    if stab_moves:
        moveset.add(stab_moves.pop(0))
        
    # Add one Setup move if available and there's room
    if setup_moves and len(moveset) < 4:
        moveset.add(setup_moves.pop(0))
        
    # Fill remaining slots with a mix of other moves, avoiding redundancy
    fill_pool = stab_moves + other_moves
    random.shuffle(fill_pool)
    while len(moveset) < 4 and fill_pool:
        move_to_add = fill_pool.pop(0)
        moveset.add(move_to_add)

    # --- 3. Determine Role and Assign Nature/EVs ---
    is_physical = chosen_set.get("role") in ["Setup Sweeper", "Wallbreaker", "Fast Attacker"]
    is_special = chosen_set.get("role") in ["Special Attacker", "Bulky Attacker"]

    # Simple logic: if more physical moves, lean physical, and vice-versa
    phys_moves = sum(1 for m in moveset if MOVE_BY_ID.get(m, {}).get('category') == 'Physical')
    spec_moves = sum(1 for m in moveset if MOVE_BY_ID.get(m, {}).get('category') == 'Special')

    if phys_moves > spec_moves:
        nature = "Adamant"
    elif spec_moves > phys_moves:
        nature = "Modest"
    else:
        nature = "Hasty" # Mixed attacker

    # EVs for Gen 4 Random Battles are typically simple max attacker spreads
    evs = Stats(hp=4, atk=252, def_=0, spa=252, spd=0, spe=252)
    ivs = Stats(hp=31, atk=31, def_=31, spa=31, spd=31, spe=31)

    # --- 4. Assign Item ---
    item = "Life Orb" # A common and safe default for attackers
    if 'Setup Sweeper' in chosen_set.get("role") and random.random() < 0.3:
        item = "Focus Sash"
    if base_stats.spe > 95 and not setup_moves:
        if is_physical: item = "Choice Band"
        else: item = "Choice Specs"
    elif base_stats.spe > 80 and not setup_moves:
        item = "Choice Scarf"

    # --- 5. Finalize and Create Pokémon Object ---
    new_pokemon = create_pokemon(species_id=species_id)
    new_pokemon.level = species_data.get('level', 100)
    new_pokemon.moves = list(moveset)
    new_pokemon.evs = evs
    new_pokemon.ivs = ivs
    new_pokemon.nature = nature
    new_pokemon.ability = random.choice(chosen_set.get("abilities", ["No Ability"]))
    new_pokemon.item = item
    
    return new_pokemon

def generate() -> List[Pokemon]:
    """The main entry point to generate a complete and diverse Gen 4 random battle team."""
    team: List[Pokemon] = []
    all_pokemon_ids = list(GEN4_RANDOM_DATA.keys())
    random.shuffle(all_pokemon_ids)
    
    team_species_ids = set()

    for species_id in all_pokemon_ids:
        if len(team) >= 6:
            break
        if species_id in team_species_ids:
            continue

        species_data = GEN4_RANDOM_DATA[species_id]
        if not species_data.get("sets"):
            continue
            
        new_pokemon = _generate_pokemon_set(species_id, species_data)
        
        if new_pokemon.moves and len(new_pokemon.moves) >= 4:
            team.append(new_pokemon)
            team_species_ids.add(species_id)

    # Failsafe in case the main loop fails to generate a full team
    while len(team) < 6 and all_pokemon_ids:
        species_id = all_pokemon_ids.pop(0)
        if species_id not in team_species_ids:
            species_data = GEN4_RANDOM_DATA[species_id]
            if species_data.get("sets"):
                new_pokemon = _generate_pokemon_set(species_id, species_data)
                if new_pokemon.moves and len(new_pokemon.moves) >= 4:
                    team.append(new_pokemon)
                    team_species_ids.add(species_id)
    return team