import os
import json
import random
from typing import List, Dict, Any, Set, Optional

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen8_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN8_RANDOM_DATA: Dict[str, Any] = json.load(f)

# --- Constants from teams.ts ---
PHYSICAL_SETUP = [
    'bellydrum', 'bulkup', 'coil', 'curse', 'dragondance', 'honeclaws', 'poweruppunch', 'swordsdance',
]
SPECIAL_SETUP = [
    'calmmind', 'chargebeam', 'geomancy', 'nastyplot', 'quiverdance', 'tailglow',
]
MIXED_SETUP = [
    'clangoroussoul', 'growth', 'shellsmash', 'workup',
]
SPEED_SETUP = [
    'agility', 'autotomize', 'flamecharge', 'rockpolish',
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

def get_pokemon_pool(type_name: str, pokemon_to_exclude: list, pokemon_list: list) -> list:
    """Gets a pool of Pokémon species, filtering by type if necessary."""
    exclude_ids = {p.id for p in pokemon_to_exclude}
    pool = []
    
    for species_id in pokemon_list:
        species = SPECIES_BY_ID.get(species_id)
        if not species: continue
        
        if species_id in exclude_ids: continue
        if type_name and type_name not in species['types']: continue
        
        pool.append(species_id)
        
    return pool


def _calculate_hp_ivs_gen8(moves: Set[str], is_physical: bool) -> Dict[str, int]:
    """Calculates IVs for Gen 8, specifically for Unown's Hidden Power."""
    ivs = {'hp': 31, 'atk': 31, 'def_': 31, 'spa': 31, 'spd': 31, 'spe': 31}
    hp_move = next((m for m in moves if m.startswith('hiddenpower')), None)

    if not is_physical:
        ivs['atk'] = 0

    if not hp_move:
        return ivs
    
    hp_type = hp_move[11:]

    # Gen 8 uses the same IVs as Gen 7 for 0 Attack sets
    zero_attack_hp_ivs = {
        'grass': {'hp': 30, 'spa': 30}, 'fire': {'spa': 30, 'spe': 30},
        'ice': {'def_': 30}, 'ground': {'spa': 30, 'spd': 30},
        'fighting': {'def_': 30, 'spa': 30, 'spd': 30, 'spe': 30},
        'electric': {'def_': 30, 'spe': 30}, 'psychic': {'spe': 30},
        'flying': {'spa': 30, 'spd': 30, 'spe': 30},
        'rock': {'def_': 30, 'spd': 30, 'spe': 30},
    }
    
    if not is_physical and hp_type in zero_attack_hp_ivs:
        ivs.update(zero_attack_hp_ivs[hp_type])
        
    return ivs


def random_set(species_id: str, team_details: Dict) -> Optional[Pokemon]:
    """Generates a single, competitively viable Pokémon set."""
    species_data = GEN8_RANDOM_DATA.get(species_id)
    if not species_data:
        return None
    
    moveset: Set[str] = set()
    if species_id == 'genesectdouse':
        moveset.add('technoblast')

    move_pool = list(species_data.get('moves', []))
    random.shuffle(move_pool)
    
    # Fill the moveset up to 4
    i = 0
    while len(moveset) < 4 and i < len(move_pool):
        moveset.add(move_pool[i])
        i += 1

    final_moveset = {'hiddenpower' if m.startswith('hiddenpower') else m for m in moveset}
    is_physical = any(MOVE_BY_ID.get(m, {}).get('category') == 'Physical' for m in final_moveset)
    
    iv_dict = _calculate_hp_ivs_gen8(moveset, is_physical)

    dex_data = SPECIES_BY_ID.get(species_id, {})
    base_species_name = dex_data.get('baseSpecies')
    required_item = dex_data.get('requiredItem')
    
    # --- MEGA / G-MAX / CROWNED / PRIMAL INTERCEPT ---
    # Strip ALL special characters to accurately match the database ID
    if base_species_name:
        base_species_id = base_species_name.lower().replace("-", "").replace(" ", "").replace(":", "").replace(".", "").replace("'", "").replace("’", "")
    else:
        base_species_id = species_id

    if base_species_name and base_species_id != species_id:
        
        # --- NEW: Mega/Z-Move Limiter Logic (if applicable to the generation) ---
        if team_details.get('has_mega'):
            return None # Force a re-roll!
        team_details['has_mega'] = True
        # ------------------------------------------------------------------------

        # Create the BASE form instead
        pokemon = create_pokemon(species_id=base_species_id, level=species_data.get('level', 80))
        
        if required_item:
            pokemon.item = required_item
    else:
        pokemon = create_pokemon(species_id=species_id, level=species_data.get('level', 80))

    # --- ITEM ASSIGNMENT LOGIC ---
    # Only assign an item if it wasn't already given a required item (like Rusted Sword)
    if not pokemon.item:
        if species_id.startswith('silvally') and species_id != 'silvally':
            pokemon.item = f"{SPECIES_BY_ID[species_id]['types'][0]} Memory"
        elif species_id.startswith('arceus') and species_id != 'arceus':
            poke_type = SPECIES_BY_ID[species_id]['types'][0]
            pokemon.item = ARCEUS_PLATES.get(poke_type, 'Leftovers')
        elif species_id.startswith('genesect') and species_id != 'genesect':
            pokemon.item = GENESECT_DRIVES.get(species_id, 'Choice Scarf')
        elif pokemon.ability == 'Guts': 
            pokemon.item = 'Flame Orb'
        elif 'dragondance' in moveset or 'swordsdance' in moveset or 'calmmind' in moveset or 'nastyplot' in moveset: 
            pokemon.item = 'Life Orb'
        elif 'stealthrock' in moveset: 
            pokemon.item = 'Focus Sash'
        elif is_physical:
            used_choices = team_details.setdefault('used_choices', set())
            available = [c for c in ['Choice Band', 'Choice Scarf', 'Life Orb'] if c not in used_choices or c == 'Life Orb']
            pokemon.item = random.choice(available)
            if 'Choice' in pokemon.item: used_choices.add(pokemon.item)
        else:
            used_choices = team_details.setdefault('used_choices', set())
            available = [c for c in ['Choice Specs', 'Choice Scarf', 'Life Orb'] if c not in used_choices or c == 'Life Orb']
            pokemon.item = random.choice(available)
            if 'Choice' in pokemon.item: used_choices.add(pokemon.item)

    pokemon.moves = list(final_moveset)
    
    # Randomly assign a valid ability from the base Pokedex, avoiding defaults
    abilities = list(SPECIES_BY_ID[pokemon.id]['abilities'].values())
    pokemon.ability = random.choice(abilities)
    
    pokemon.evs = Stats(hp=85, atk=85, def_=85, spa=85, spd=85, spe=85)
    pokemon.ivs = Stats(**iv_dict)
    
    if not is_physical: 
        pokemon.evs.atk = 0

    return pokemon
    
def generate() -> List[Pokemon]:
    """The main entry point to generate a complete and diverse Gen 8 random battle team."""
    team: List[Pokemon] = []
    
    all_pokemon_ids = [pid for pid, data in GEN8_RANDOM_DATA.items() if data.get('moves')]
    random.shuffle(all_pokemon_ids)
    
    team_species_ids: Set[str] = set()
    team_details: Dict[str, Any] = {'used_choices': set()}
    
    while len(team) < 6 and all_pokemon_ids:
        species_id = all_pokemon_ids.pop(0)
        
        species = SPECIES_BY_ID.get(species_id)
        if not species: continue
        
        base_species = species.get('baseSpecies', species['name'])
        if base_species in team_species_ids:
            continue

        # Basic team composition checks (weakness limiter)
        weaknesses = {}
        for p in team:
            for type_name in SPECIES_BY_ID[p.id]['types']:
                for attack_type, effectiveness in TYPE_CHART.items():
                    if effectiveness.get(type_name.lower(), 1) > 1:
                        weaknesses[attack_type] = weaknesses.get(attack_type, 0) + 1
        
        current_weaknesses = {}
        for type_name in species['types']:
            for attack_type, effectiveness in TYPE_CHART.items():
                if effectiveness.get(type_name.lower(), 1) > 1:
                    current_weaknesses[attack_type] = current_weaknesses.get(attack_type, 0) + 1

        too_many_weaknesses = False
        for t, count in current_weaknesses.items():
            if weaknesses.get(t, 0) + count >= 3:
                too_many_weaknesses = True
                break
        
        if too_many_weaknesses and random.random() < 0.75: # High chance to skip
            continue

        new_pokemon_obj = random_set(species_id, team_details)
        if not new_pokemon_obj: 
            continue
        
        team.append(new_pokemon_obj)
        team_species_ids.add(base_species)
        
        for move in new_pokemon_obj.moves:
            if move in HAZARDS:
                team_details[move] = team_details.get(move, 0) + 1

    return team

TYPE_CHART = {
    'normal': {'rock': 0.5, 'ghost': 0, 'steel': 0.5},
    'fire': {'fire': 0.5, 'water': 0.5, 'grass': 2, 'ice': 2, 'bug': 2, 'rock': 0.5, 'dragon': 0.5, 'steel': 2},
    'water': {'fire': 2, 'water': 0.5, 'grass': 0.5, 'ground': 2, 'rock': 2, 'dragon': 0.5},
    'electric': {'water': 2, 'electric': 0.5, 'grass': 0.5, 'ground': 0, 'flying': 2, 'dragon': 0.5},
    'grass': {'fire': 0.5, 'water': 2, 'grass': 0.5, 'poison': 0.5, 'ground': 2, 'flying': 0.5, 'bug': 0.5, 'rock': 2, 'dragon': 0.5, 'steel': 0.5},
    'ice': {'fire': 0.5, 'water': 0.5, 'grass': 2, 'ice': 0.5, 'ground': 2, 'flying': 2, 'dragon': 2, 'steel': 0.5},
    'fighting': {'normal': 2, 'ice': 2, 'poison': 0.5, 'flying': 0.5, 'psychic': 0.5, 'bug': 0.5, 'rock': 2, 'ghost': 0, 'dark': 2, 'steel': 2, 'fairy': 0.5},
    'poison': {'grass': 2, 'poison': 0.5, 'ground': 0.5, 'rock': 0.5, 'ghost': 0.5, 'steel': 0, 'fairy': 2},
    'ground': {'fire': 2, 'electric': 2, 'grass': 0.5, 'poison': 2, 'flying': 0, 'bug': 0.5, 'rock': 2, 'steel': 2},
    'flying': {'electric': 0.5, 'grass': 2, 'fighting': 2, 'bug': 2, 'rock': 0.5, 'steel': 0.5},
    'psychic': {'fighting': 2, 'poison': 2, 'psychic': 0.5, 'dark': 0, 'steel': 0.5},
    'bug': {'fire': 0.5, 'grass': 2, 'fighting': 0.5, 'poison': 0.5, 'flying': 0.5, 'psychic': 2, 'ghost': 0.5, 'dark': 2, 'steel': 0.5, 'fairy': 0.5},
    'rock': {'fire': 2, 'ice': 2, 'fighting': 0.5, 'ground': 0.5, 'flying': 2, 'bug': 2, 'steel': 0.5},
    'ghost': {'normal': 0, 'psychic': 2, 'ghost': 2, 'dark': 0.5},
    'dragon': {'dragon': 2, 'steel': 0.5, 'fairy': 0},
    'dark': {'fighting': 0.5, 'psychic': 2, 'ghost': 2, 'dark': 0.5, 'fairy': 0.5},
    'steel': {'fire': 0.5, 'water': 0.5, 'electric': 0.5, 'ice': 2, 'rock': 2, 'steel': 0.5, 'fairy': 2},
    'fairy': {'fighting': 2, 'poison': 0.5, 'dragon': 2, 'dark': 2, 'steel': 0.5},
}