import json
import os
from typing import Dict, Any, List

# Ensure this path is correct based on your project structure
# This assumes the 'data' files are in the parent directory of the 'bot' package
DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(DATA_DIR, 'data_moves.json'), 'r', encoding='utf-8') as f:
    MOVES: List[Dict[str, Any]] = json.load(f)
with open(os.path.join(DATA_DIR, 'data_species.json'), 'r', encoding='utf-8') as f:
    SPECIES: List[Dict[str, Any]] = json.load(f)
with open(os.path.join(DATA_DIR, 'data_abilities.json'), 'r', encoding='utf-8') as f:
    ABILITIES: List[Dict[str, Any]] = json.load(f)
with open(os.path.join(DATA_DIR, 'data_learnsets.json'), 'r', encoding='utf-8') as f:
    LEARNSETS: Dict[str, Any] = json.load(f)
with open(os.path.join(DATA_DIR, 'data_natures.json'), 'r', encoding='utf-8') as f:
    NATURES_DATA: Dict[str, Any] = json.load(f)

# This dictionary is key for the new UI, mapping a move's ID to its full data
MOVE_BY_ID = {m["id"]: m for m in MOVES}
SPECIES_BY_ID = {s["id"]: s for s in SPECIES}
ABILITIES_BY_ID = {a["id"]: a for a in ABILITIES}

# We can keep this for other uses if needed
NAME_TO_ID: Dict[str, str] = {m.get('name', '').lower(): m['id'] for m in MOVES}

# (The rest of the functions in this file can remain the same)
def is_move_legal_for_species(species_id: str, move_id: str) -> bool:
    ls = LEARNSETS.get(species_id)
    if not ls: return False
    learnset = ls.get("learnset", {})
    return move_id in learnset

def get_species_moves(species_id: str) -> List[str]:
    ls = LEARNSETS.get(species_id)
    if not ls: return []
    return list(ls.get("learnset", {}).keys())