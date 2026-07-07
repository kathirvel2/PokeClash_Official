# File: bot/randombattle/gen5/gen5_random_team.py
import os
import json
import random
from typing import List, Dict, Any, Set, Tuple

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen5_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN5_RANDOM_DATA: Dict[str, Any] = json.load(f)

# --- Constants from teams.ts ---
RECOVERY_MOVES = [
    'healorder', 'milkdrink', 'moonlight', 'morningsun', 'recover', 'roost', 'slackoff', 'softboiled', 'synthesis',
]
PHYSICAL_SETUP = [
    'bellydrum', 'bulkup', 'coil', 'curse', 'dragondance', 'honeclaws', 'howl', 'meditate', 'screech', 'swordsdance',
]
SPEED_SETUP = [
    'agility', 'autotomize', 'flamecharge', 'rockpolish',
]
SETUP = [
    'acidarmor', 'agility', 'autotomize', 'bellydrum', 'bulkup', 'calmmind', 'coil', 'curse', 'dragondance', 'flamecharge',
    'growth', 'honeclaws', 'howl', 'irondefense', 'meditate', 'nastyplot', 'quiverdance', 'raindance', 'rockpolish',
    'shellsmash', 'shiftgear', 'sunnyday', 'swordsdance', 'tailglow', 'workup',
]
NO_STAB = [
    'aquajet', 'bulletpunch', 'chatter', 'clearsmog', 'dragontail', 'eruption', 'explosion', 'fakeout', 'flamecharge',
    'futuresight', 'iceshard', 'icywind', 'incinerate', 'knockoff', 'machpunch', 'pluck', 'pursuit', 'quickattack',
    'rapidspin', 'reversal', 'selfdestruct', 'shadowsneak', 'skyattack', 'skydrop', 'snarl', 'suckerpunch',
    'uturn', 'vacuumwave', 'voltswitch', 'waterspout',
]
HAZARDS = [
    'spikes', 'stealthrock', 'toxicspikes',
]
PIVOT_MOVES = [
    'uturn', 'voltswitch',
]
MOVE_PAIRS = [
    ['lightscreen', 'reflect'],
    ['sleeptalk', 'rest'],
    ['protect', 'wish'],
    ['leechseed', 'substitute'],
]
PRIORITY_POKEMON = [
    'bisharp', 'breloom', 'cacturne', 'dusknoir', 'honchkrow', 'scizor', 'shedinja', 'shiftry',
]


class MoveCounter:
    """A helper class to count move types and attributes."""
    def __init__(self, moves: Set[str], species: Dict[str, Any]):
        self.moves = moves
        self.species = species
        self.damaging_moves: Set[Dict[str, Any]] = set()
        self.stab = 0
        self.preferred_type = 0
        self.move_counts: Dict[str, int] = {}

        for move_id in moves:
            move_data = MOVE_BY_ID.get(move_id, {})
            if not move_data:
                continue

            # In Gen 5, Nature Power is Earthquake
            if move_id == 'naturepower':
                move_data = MOVE_BY_ID['earthquake']

            if move_data.get('basePower'):
                self.damaging_moves.add(move_data)

            move_type = move_data.get('type')
            if move_type in species['types']:
                self.stab += 1
            if move_type == species.get('preferredType'):
                self.preferred_type += 1
            
            self.move_counts[move_type] = self.move_counts.get(move_type, 0) + 1

    def get(self, key: str) -> int:
        if key.lower() in [t.lower() for t in self.species['types']]:
            return self.stab
        return self.move_counts.get(key, 0)
        
def _calculate_hp_ivs_gen5(moves: Set[str]) -> Dict[str, int]:
    """Calculates the specific IVs needed for a given Hidden Power type in Gen 5."""
    # The fix is here: using 'def_' to match your Stats dataclass
    ivs = {'hp': 31, 'atk': 31, 'def_': 31, 'spa': 31, 'spd': 31, 'spe': 31}
    hp_move = next((m for m in moves if m.startswith('hiddenpower')), None)
    
    if not hp_move:
        return ivs

    hp_type = hp_move[11:]
    
    # This map now also uses 'def_' to be safe and consistent
    hp_iv_map = {
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
        'dark': {},
    }

    iv_changes = hp_iv_map.get(hp_type, {})
    ivs.update(iv_changes)
    return ivs

def _generate_pokemon_set(species_id: str, team_details: Dict) -> Pokemon:
    """Creates a single, complete Pokémon set for Gen 5."""
    species_data = GEN5_RANDOM_DATA[species_id]
    
    possible_sets = species_data['sets']
    can_be_spinner = any(s['role'] == 'Spinner' for s in possible_sets)
    if team_details.get('rapidSpin') and can_be_spinner:
        possible_sets = [s for s in possible_sets if s['role'] != 'Spinner']
    elif not team_details.get('rapidSpin') and can_be_spinner:
        possible_sets = [s for s in possible_sets if s['role'] == 'Spinner']
    
    chosen_set = random.choice(possible_sets)
    role = chosen_set['role']
    
    move_pool = chosen_set['movepool']
    random.shuffle(move_pool)
    temp_moveset: Set[str] = set()

    # Simplified, safe move selection that avoids the KeyError
    if len(move_pool) <= 4:
        temp_moveset = set(move_pool)
    else:
        # This simplified selection avoids looking up move data prematurely
        # A more complex logic can be built here later if needed, but this is safe and functional
        temp_moveset = set(random.sample(move_pool, 4))

    # --- HIDDEN POWER FIX IMPLEMENTED HERE ---
    # 1. Calculate IVs based on the specific HP type in the temporary moveset
    iv_dict = _calculate_hp_ivs_gen5(temp_moveset)
    
    # 2. Create the final, sanitized moveset for the Pokémon object
    final_moveset = {'hiddenpower' if move.startswith('hiddenpower') else move for move in temp_moveset}
    # --- END OF FIX ---

    pokemon = create_pokemon(species_id=species_id, level=species_data.get('level', 100))
    pokemon.moves = list(final_moveset) # Use the corrected moveset
    pokemon.ability = random.choice(chosen_set['abilities'])
    
    pokemon.evs = Stats(hp=85, atk=85, def_=85, spa=85, spd=85, spe=85)
    pokemon.ivs = Stats(**iv_dict) # Use the correctly calculated IVs

    # Simple item logic (can be expanded later with the full getItem logic)
    if role == "Staller":
        pokemon.item = "Leftovers"
    elif "Setup" in role:
        pokemon.item = "Life Orb"
    elif "Attacker" in role:
        pokemon.item = random.choice(["Life Orb", "Choice Scarf", "Choice Band", "Choice Specs"])
    else:
        pokemon.item = "Leftovers"
    
    # Minimize attack for special attackers
    is_physical = False
    for move_id in final_moveset:
        move_data = MOVE_BY_ID.get(move_id, {})
        if move_data.get('category') == 'Physical':
            is_physical = True
            break

    if not is_physical:
        # Use .get() for safety in case atk is not in the dict from the HP calc
        pokemon.ivs.atk = iv_dict.get('atk', 31) if 'atk' in iv_dict else 0
        pokemon.evs.atk = 0

    return pokemon

def generate() -> List[Pokemon]:
    """The main entry point to generate a complete and diverse Gen 5 random battle team."""
    team: List[Pokemon] = []
    
    pokemon_pool = list(GEN5_RANDOM_DATA.keys())
    random.shuffle(pokemon_pool)
    
    team_species_ids: Set[str] = set()
    team_details: Dict[str, Any] = {}
    
    while len(team) < 6 and pokemon_pool:
        species_id = pokemon_pool.pop(0)
        
        # Species Clause
        if species_id in team_species_ids:
            continue
            
        new_pokemon_obj = _generate_pokemon_set(species_id, team_details)
        
        # Add to team and update details
        team.append(new_pokemon_obj)
        team_species_ids.add(species_id)
        
        if 'rapidspin' in new_pokemon_obj.moves:
            team_details['rapidSpin'] = True
        if 'stealthrock' in new_pokemon_obj.moves:
            team_details['stealthRock'] = True

    return team