import random
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from bot.mechanics.moves_loader import SPECIES_BY_ID, LEARNSETS


def normalize_species_id(value: str | None) -> str:
    return str(value or "").lower().replace("-", "").replace(" ", "")


def related_species_ids(species_id: str) -> list[str]:
    pending = [normalize_species_id(species_id)]
    visited: set[str] = set()
    ordered: list[str] = []

    while pending:
        current_id = pending.pop(0)
        if not current_id or current_id in visited:
            continue
        visited.add(current_id)
        ordered.append(current_id)

        species_info = SPECIES_BY_ID.get(current_id, {})
        for key in ("changesFrom", "baseSpecies", "prevo"):
            related_id = normalize_species_id(species_info.get(key))
            if related_id and related_id not in visited:
                pending.append(related_id)

    return ordered


def resolve_full_learnset(species_id: str) -> dict[str, list[str]]:
    learnset: dict[str, list[str]] = {}
    for current_id in related_species_ids(species_id):
        learnset_entry = LEARNSETS.get(current_id, {})
        for move_id, methods in (learnset_entry.get("learnset") or {}).items():
            bucket = learnset.setdefault(move_id, [])
            for method in list(methods or []):
                if method not in bucket:
                    bucket.append(method)
        for event in list(learnset_entry.get("eventData") or []):
            event_moves = list(event.get("moves") or [])
            event_label = f"{int(event.get('generation') or 0)}S" if event.get("generation") else "Event"
            for move_id in event_moves:
                bucket = learnset.setdefault(move_id, [])
                if event_label not in bucket:
                    bucket.append(event_label)
    return learnset


def resolve_learnset(species_id: str) -> dict:
    """Return the most appropriate learnset for a species or its base form."""
    return resolve_full_learnset(species_id)

@dataclass
class Stats:
    hp: int
    atk: int
    def_: int
    spa: int
    spd: int
    spe: int

@dataclass
class Pokemon:
    id: str
    name: str
    level: int
    types: List[str]
    base_stats: Stats
    ivs: Stats
    evs: Stats
    nature: str
    ability: str
    weight: float
    item: Optional[str]
    moves: List[str]
    current_hp: int
    max_hp: int
    status: Optional[str]
    boosts: Dict[str, int]
    volatiles: Dict[str, Any]
    tera_type: Optional[str] = None
    is_shiny: bool = field(default=False)
    pokemon_uuid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def create_pokemon(species_id: str, level: int = 100, is_shiny: bool = False) -> Pokemon:
    """
    Creates a new Pokémon instance, now with one default move from its learnset.
    """
    species_info = SPECIES_BY_ID[species_id]
    
    ivs = Stats(hp=31, atk=31, def_=31, spa=31, spd=31, spe=31)
    evs = Stats(hp=0, atk=0, def_=0, spa=0, spd=0, spe=0)
    
    nature = "Serious"
    ability = species_info["abilities"]["0"]
    
    stats_data = species_info["baseStats"].copy()
    if 'def' in stats_data:
        stats_data['def_'] = stats_data.pop('def')
    base_stats = Stats(**stats_data)

    max_hp = int(((2 * base_stats.hp + ivs.hp + evs.hp // 4) * level) / 100) + level + 10
    
    moves = []
    learnset_data = resolve_learnset(species_id)
    if learnset_data:
        possible_moves = list(learnset_data.keys())
        if possible_moves:
            moves.append(possible_moves[0])

    pokemon = Pokemon(
        id=species_id,
        name=species_info["name"],
        level=level,
        is_shiny=is_shiny,
        types=species_info["types"],
        base_stats=base_stats,
        ivs=ivs,
        evs=evs,
        nature=nature,
        ability=ability,
        weight=species_info.get("weightkg", 0.1),
        item=None,
        moves=moves,
        current_hp=max_hp,
        max_hp=max_hp,
        status=None,
        boosts={},
        volatiles={},
        tera_type=species_info["types"][0]
    )
    return pokemon
