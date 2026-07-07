import os
import json
import random
from typing import List, Dict, Any, Set, Optional

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen7_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN7_RANDOM_DATA: Dict[str, Any] = json.load(f)

# --- Constants from teams.ts ---
RECOVERY_MOVES = [
    'healorder', 'milkdrink', 'moonlight', 'morningsun', 'recover', 'recycle', 'roost', 'shoreup', 'slackoff', 'softboiled', 'strengthsap', 'synthesis',
]
SETUP = [
    'acidarmor', 'agility', 'autotomize', 'bellydrum', 'bulkup', 'calmmind', 'celebrate', 'coil', 'conversion', 'curse', 'dragondance',
    'electricterrain', 'flamecharge', 'focusenergy', 'geomancy', 'growth', 'happyhour', 'holdhands', 'honeclaws', 'howl', 'irondefense', 'meditate',
    'nastyplot', 'poweruppunch', 'quiverdance', 'raindance', 'rockpolish', 'shellsmash', 'shiftgear', 'swordsdance', 'tailglow', 'workup',
]
NO_STAB = [
    'accelerock', 'aquajet', 'bulletpunch', 'clearsmog', 'dragontail', 'eruption', 'explosion',
    'fakeout', 'firstimpression', 'flamecharge', 'futuresight', 'iceshard', 'icywind', 'incinerate', 'infestation', 'machpunch',
    'nuzzle', 'pluck', 'poweruppunch', 'pursuit', 'quickattack', 'rapidspin', 'reversal', 'selfdestruct', 'shadowsneak',
    'skyattack', 'skydrop', 'snarl', 'suckerpunch', 'uturn', 'watershuriken', 'vacuumwave', 'voltswitch', 'waterspout',
]
HAZARDS = [
    'spikes', 'stealthrock', 'stickyweb', 'toxicspikes',
]

ARCEUS_PLATES = {
    "Fire": "Flame Plate", "Water": "Splash Plate", "Electric": "Zap Plate",
    "Grass": "Meadow Plate", "Ice": "Icicle Plate", "Fighting": "Fist Plate",
    "Poison": "Toxic Plate", "Ground": "Earth Plate", "Flying": "Sky Plate",
    "Psychic": "Mind Plate", "Bug": "Insect Plate", "Rock": "Stone Plate",
    "Ghost": "Spooky Plate", "Dragon": "Draco Plate", "Dark": "Dread Plate",
    "Steel": "Iron Plate", "Fairy": "Pixie Plate"
}

GENESECT_DRIVES = {
    "genesectdouse": "Douse Drive",
    "genesectshock": "Shock Drive",
    "genesectburn": "Burn Drive",
    "genesectchill": "Chill Drive"
}

# Helper function for Gen 7 HP IVs
def _calculate_hp_ivs_gen7(moves: Set[str], is_physical: bool) -> Dict[str, int]:
    """Calculates IVs for Gen 7, accounting for Hidden Power and Atk reduction."""
    ivs = {'hp': 31, 'atk': 31, 'def_': 31, 'spa': 31, 'spd': 31, 'spe': 31}
    hp_move = next((m for m in moves if m.startswith('hiddenpower')), None)

    # Minimize Atk for non-physical sets
    if not is_physical:
        ivs['atk'] = 0

    if not hp_move:
        return ivs
    
    hp_type = hp_move[11:]

    # This map is from the teams.ts file for 0 Atk IV sets
    zero_attack_hp_ivs = {
        'grass': {'hp': 30, 'spa': 30},
        'fire': {'spa': 30, 'spe': 30},
        'ice': {'def_': 30},
        'ground': {'spa': 30, 'spd': 30},
        'fighting': {'def_': 30, 'spa': 30, 'spd': 30, 'spe': 30},
        'electric': {'def_': 30, 'spe': 30},
        'psychic': {'spe': 30},
        'flying': {'spa': 30, 'spd': 30, 'spe': 30},
        'rock': {'def_': 30, 'spd': 30, 'spe': 30},
    }
    
    # Standard HP IVs (can be expanded if needed)
    standard_hp_ivs = {
        'dark': {}, 'dragon': {'atk': 30}, 'ice': {'atk': 30}, 'psychic': {'atk': 30},
        'electric': {'spa': 30}, 'grass': {'spa': 30}, 'water': {'spa': 30}, 'fire': {'spa': 30},
        'steel': {'spd': 30}, 'ghost': {'spd': 30}, 'bug': {'spd': 30}, 'rock': {'spd': 30},
        'ground': {'spa': 30, 'spd': 30}, 'poison': {'spa': 30, 'spd': 30},
        'flying': {'spa': 30, 'spd': 30, 'spe': 30}, 'fighting': {'spd': 30, 'spe': 30}
    }

    if not is_physical and hp_type in zero_attack_hp_ivs:
        ivs.update(zero_attack_hp_ivs[hp_type])
    elif hp_type in standard_hp_ivs:
        ivs.update(standard_hp_ivs[hp_type])
        
    return ivs

def _generate_pokemon_set(species_id: str, team_details: Dict) -> Optional[Pokemon]:
    """Creates a single, complete Pokémon set for Gen 7 based on roles."""
    species_data = GEN7_RANDOM_DATA.get(species_id)
    if not species_data or not species_data.get('sets'):
        return None
    
    possible_sets = species_data['sets']
    
    # --- NEW: Z-Move Limiter ---
    if team_details.get('has_zmove'):
        possible_sets = [s for s in possible_sets if s.get('role') != 'Z-Move user']
        if not possible_sets:
            return None # Force a reroll if this Pokémon only has Z-Move sets available
            
    chosen_set = random.choice(possible_sets)
    role = chosen_set['role']
    
    move_pool = chosen_set['movepool']
    random.shuffle(move_pool)
    temp_moveset: Set[str] = set()

    # --- SAFE MOVE SELECTION ---
    if len(move_pool) <= 4:
        temp_moveset = set(move_pool)
    else:
        # Prioritize STAB moves
        stab_moves = [m for m in move_pool if MOVE_BY_ID.get(m, {}).get('type') in SPECIES_BY_ID[species_id]['types']]
        if stab_moves and not any(m in temp_moveset for m in stab_moves):
            temp_moveset.add(random.choice(stab_moves))
        # Fill the rest
        remaining_pool = [m for m in move_pool if m not in temp_moveset]
        while len(temp_moveset) < 4 and remaining_pool:
            temp_moveset.add(remaining_pool.pop(0))

    final_moveset = {'hiddenpower' if move.startswith('hiddenpower') else move for move in temp_moveset}
    is_physical = any(MOVE_BY_ID.get(m, {}).get('category') == 'Physical' for m in final_moveset)

    # Hidden Power IVs
    iv_dict = _calculate_hp_ivs_gen7(temp_moveset, is_physical)

    dex_data = SPECIES_BY_ID.get(species_id, {})
    base_species_name = dex_data.get('baseSpecies')
    required_item = dex_data.get('requiredItem')

    # --- MEGA / PRIMAL INTERCEPT ---
    if base_species_name and base_species_name.lower().replace("-", "").replace(" ", "") != species_id:
        if team_details.get('has_mega'):
            return None # We already have a Mega, force a re-roll!
            
        team_details['has_mega'] = True
        base_species_id = base_species_name.lower().replace("-", "").replace(" ", "")
        
        # Create the BASE form instead
        pokemon = create_pokemon(species_id=base_species_id, level=species_data.get('level', 80))
        
        # Give it the required Mega Stone or Primal Orb
        if required_item:
            pokemon.item = required_item
    else:
        # Create the normal Pokémon
        pokemon = create_pokemon(species_id=species_id, level=species_data.get('level', 80))
        
        # --- ITEM ASSIGNMENT LOGIC ---
        if role == 'Z-Move user':
            preferred_type = chosen_set.get('preferredTypes', ['Normal'])[0]
            pokemon.item = f"{preferred_type}ium Z"
            team_details['has_zmove'] = True
        elif species_id.startswith('silvally') and species_id != 'silvally':
            pokemon.item = f"{SPECIES_BY_ID[species_id]['types'][0]} Memory"
        elif species_id.startswith('arceus') and species_id != 'arceus':
            poke_type = SPECIES_BY_ID[species_id]['types'][0]
            pokemon.item = ARCEUS_PLATES.get(poke_type, 'Leftovers')
        elif species_id.startswith('genesect') and species_id != 'genesect':
            pokemon.item = GENESECT_DRIVES.get(species_id, 'Choice Scarf')
        elif species_id == 'pikachu': pokemon.item = 'Light Ball'
        elif pokemon.ability == 'Poison Heal': pokemon.item = 'Toxic Orb'
        elif 'Setup' in role: pokemon.item = 'Life Orb'
        elif 'Attacker' in role:
            # --- NEW: Choice Item Limiter logic ---
            used_choices = team_details.setdefault('used_choices', set())
            choices = ['Life Orb', 'Choice Scarf', 'Choice Band', 'Choice Specs']
            available = [c for c in choices if c not in used_choices or c == 'Life Orb']
            pokemon.item = random.choice(available)
            if 'Choice' in pokemon.item:
                used_choices.add(pokemon.item)
        else: 
            pokemon.item = 'Leftovers'
    # --- END INTERCEPT ---

    pokemon.moves = list(final_moveset)
    pokemon.ability = random.choice(chosen_set.get('abilities', ["No Ability"]))
    
    pokemon.evs = Stats(hp=85, atk=85, def_=85, spa=85, spd=85, spe=85)
    pokemon.ivs = Stats(**iv_dict)
    
    if not is_physical:
        pokemon.evs.atk = 0

    return pokemon

def generate() -> List[Pokemon]:
    """The main entry point to generate a complete and diverse Gen 7 random battle team."""
    team: List[Pokemon] = []
    
    pokemon_pool = list(GEN7_RANDOM_DATA.keys())
    random.shuffle(pokemon_pool)
    
    team_species_ids: Set[str] = set()
    # Track Choice items, Megas, and Z-Moves
    team_details: Dict[str, Any] = {'used_choices': set(), 'has_mega': False, 'has_zmove': False}
    
    while len(team) < 6 and pokemon_pool:
        species_id = pokemon_pool.pop(0)
        
        # Check base species to avoid generating both Venusaur AND Mega-Venusaur
        dex_data = SPECIES_BY_ID.get(species_id, {})
        base_species = dex_data.get('baseSpecies', dex_data.get('name', species_id))
        
        if base_species in team_species_ids:
            continue
            
        new_pokemon_obj = _generate_pokemon_set(species_id, team_details)
        
        # If the generator returned None (e.g., duplicate Mega or Z-Move), skip it!
        if not new_pokemon_obj:
            continue
            
        team.append(new_pokemon_obj)
        team_species_ids.add(base_species)
        
        # Update team details for subsequent generation
        for move in new_pokemon_obj.moves:
            if move in HAZARDS:
                team_details[move] = True

    return team