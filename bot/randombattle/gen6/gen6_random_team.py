import os
import json
import random
from typing import List, Dict, Any, Set, Tuple, Optional

from bot.mechanics.team import Pokemon, Stats, create_pokemon
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID

# --- Data Loading ---
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'gen6_data.json')
with open(DATA_FILE_PATH, 'r', encoding='utf-8') as f:
    GEN6_RANDOM_DATA: Dict[str, Any] = json.load(f)

# --- Constants from teams.ts ---
RECOVERY_MOVES = [
    'healorder', 'milkdrink', 'moonlight', 'morningsun', 'recover', 'recycle', 'roost', 'slackoff', 'softboiled', 'synthesis',
]
SETUP = [
    'acidarmor', 'agility', 'autotomize', 'bellydrum', 'bulkup', 'calmmind', 'coil', 'curse', 'dragondance', 'flamecharge',
    'focusenergy', 'geomancy', 'growth', 'honeclaws', 'howl', 'irondefense', 'meditate', 'nastyplot', 'poweruppunch',
    'quiverdance', 'raindance', 'rockpolish', 'shellsmash', 'shiftgear', 'swordsdance', 'tailglow', 'workup',
]
NO_STAB = [
    'aquajet', 'bulletpunch', 'clearsmog', 'dragontail', 'eruption', 'explosion', 'fakeout', 'flamecharge',
    'futuresight', 'iceshard', 'icywind', 'incinerate', 'infestation', 'machpunch', 'nuzzle', 'pluck', 'poweruppunch',
    'pursuit', 'quickattack', 'rapidspin', 'reversal', 'selfdestruct', 'shadowsneak', 'skyattack', 'skydrop', 'snarl',
    'suckerpunch', 'uturn', 'watershuriken', 'vacuumwave', 'voltswitch', 'waterspout',
]
HAZARDS = [
    'spikes', 'stealthrock', 'stickyweb', 'toxicspikes',
]
PRIORITY_POKEMON = [
    'aegislash', 'banette', 'breloom', 'cacturne', 'doublade', 'dusknoir', 'honchkrow', 'scizor', 'scizormega', 'shedinja',
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
    "genesectdouse": "Douse Drive", "genesectshock": "Shock Drive",
    "genesectburn": "Burn Drive", "genesectchill": "Chill Drive"
}

class MoveCounter:
    """A helper class to count move types and attributes, mirroring the JS version."""
    def __init__(self, moves: Set[str], species: Dict[str, Any]):
        self.moves = moves
        self.species_types = set(t.lower() for t in species['types'])
        self.damaging_moves: List[Dict[str, Any]] = []  
        self.stab = 0
        self.move_counts: Dict[str, int] = {}
        self.recoil = 0
        self.sheer_force = 0
        self.iron_fist = 0
        self.technician = 0
        self.status = 0
        self.priority = 0

        for move_id in moves:
            move_data = MOVE_BY_ID.get(move_id, {})
            if not move_data: continue

            if move_data.get('category') != 'Status':
                self.damaging_moves.append(move_data) 
            else:
                self.status += 1

            move_type = move_data.get('type', '').lower()
            if move_type in self.species_types:
                self.stab += 1
            
            self.move_counts[move_type] = self.move_counts.get(move_type, 0) + 1
            
            if move_data.get('recoil'): self.recoil += 1
            if move_data.get('flags', {}).get('punch'): self.iron_fist += 1
            if move_data.get('basePower', 0) <= 60: self.technician += 1
            if move_data.get('priority', 0) > 0: self.priority += 1

def _generate_pokemon_set(species_id: str, team_details: Dict) -> Optional[Pokemon]:
    """Creates a single, complete Pokémon set for Gen 6."""
    species_data = GEN6_RANDOM_DATA.get(species_id)
    if not species_data or not species_data.get('sets'):
        return None

    chosen_set = random.choice(species_data['sets'])
    role = chosen_set['role']
    
    # Select moveset
    move_pool = chosen_set['movepool']
    random.shuffle(move_pool)
    temp_moveset = set(random.sample(move_pool, min(4, len(move_pool))))

    # Handle Hidden Power IVs
    ivs = {'hp': 31, 'atk': 31, 'def_': 31, 'spa': 31, 'spd': 31, 'spe': 31}
    final_moveset = {'hiddenpower' if m.startswith('hiddenpower') else m for m in temp_moveset}

    # Look up the actual Pokedex data, NOT the random battle data
    dex_data = SPECIES_BY_ID.get(species_id, {})
    base_species_name = dex_data.get('baseSpecies')
    required_item = dex_data.get('requiredItem')

    # --- MEGA / G-MAX / PRIMAL INTERCEPT ---
    # Check if this species is an alternate form of something else
    if base_species_name and base_species_name.lower().replace("-", "").replace(" ", "") != species_id:
        
        # --- NEW: Mega Limiter Logic ---
        if team_details.get('has_mega'):
            return None # We already have a Mega on the team, force a re-roll!
            
        team_details['has_mega'] = True
        
        base_species_id = base_species_name.lower().replace("-", "").replace(" ", "")
        
        # Create the BASE form instead
        pokemon = create_pokemon(species_id=base_species_id, level=species_data.get('level', 80))
        
        # Give it the required Mega Stone or Primal Orb!
        if required_item:
            pokemon.item = required_item
    else:
        # Create the normal Pokémon
        pokemon = create_pokemon(species_id=species_id, level=species_data.get('level', 80))
        
        # --- ITEM ASSIGNMENT LOGIC ---
        if species_id.startswith('arceus') and species_id != 'arceus':
            poke_type = SPECIES_BY_ID[species_id]['types'][0]
            pokemon.item = ARCEUS_PLATES.get(poke_type, 'Leftovers')
        elif species_id.startswith('genesect') and species_id != 'genesect':
            pokemon.item = GENESECT_DRIVES.get(species_id, 'Choice Scarf')
        elif species_id.startswith('silvally') and species_id != 'silvally':
            pokemon.item = f"{SPECIES_BY_ID[species_id]['types'][0]} Memory"
        elif species_id == 'pikachu': pokemon.item = 'Light Ball'
        elif species_id == 'shedinja': pokemon.item = 'Focus Sash'
        elif pokemon.ability == 'Poison Heal': pokemon.item = 'Toxic Orb'
        elif 'Setup' in role: pokemon.item = 'Life Orb'
        elif 'Attacker' in role: 
            # --- NEW: Choice Item Limiter logic ---
            used_choices = team_details.setdefault('used_choices', set())
            choices = ['Life Orb', 'Choice Scarf', 'Choice Band', 'Choice Specs']
            # Only allow a Choice item if it hasn't been used yet
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
    pokemon.ivs = Stats(**ivs)
    
    # Minimize attack for special attackers
    counter = MoveCounter(final_moveset, SPECIES_BY_ID[pokemon.id])
    is_physical = any(m.get('category') == 'Physical' for m in counter.damaging_moves)
    if not is_physical:
        pokemon.ivs.atk = 0
        pokemon.evs.atk = 0
        
    return pokemon

def generate() -> List[Pokemon]:
    """The main entry point to generate a complete Gen 6 random battle team."""
    team: List[Pokemon] = []
    
    pokemon_pool = list(GEN6_RANDOM_DATA.keys())
    random.shuffle(pokemon_pool)
    
    team_species_ids: Set[str] = set()
    # NEW: Initialize the team trackers
    team_details: Dict[str, Any] = {'used_choices': set(), 'has_mega': False}
    
    while len(team) < 6 and pokemon_pool:
        species_id = pokemon_pool.pop(0)
        
        # Check base species to avoid generating both Venusaur AND Mega-Venusaur
        dex_data = SPECIES_BY_ID.get(species_id, {})
        base_species = dex_data.get('baseSpecies', dex_data.get('name', species_id))
        
        if base_species in team_species_ids:
            continue
            
        new_pokemon_obj = _generate_pokemon_set(species_id, team_details)
        
        # NEW: If the generator returned None (because we hit a duplicate Mega limit), skip it!
        if not new_pokemon_obj:
            continue
        
        team.append(new_pokemon_obj)
        team_species_ids.add(base_species)
        
        # Update team details for subsequent generation
        for move in new_pokemon_obj.moves:
            if move in HAZARDS:
                team_details[move] = True

    return team