from __future__ import annotations

import re
from typing import Any

from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID
from bot.mechanics.team import Pokemon, Stats, create_pokemon


def _normalized(value: str) -> str:
    return "".join(char for char in str(value or "").lower() if char.isalnum())


SPECIES_BY_NORMALIZED_NAME = {
    _normalized(species_data.get("name", "")): species_data
    for species_data in SPECIES_BY_ID.values()
}


def _details_name(details: str) -> str:
    return str(details or "").split(",", 1)[0].strip()


def _parse_level(details: str) -> int:
    match = re.search(r"\bL(\d+)\b", str(details or ""))
    if not match:
        return 100
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return 100


def _placeholder_pokemon(name: str, level: int, shiny: bool) -> Pokemon:
    base_stats = Stats(hp=100, atk=100, def_=100, spa=100, spd=100, spe=100)
    return Pokemon(
        id=_normalized(name) or "unknown",
        name=name or "Pokemon",
        level=level,
        types=["Normal"],
        base_stats=base_stats,
        ivs=Stats(hp=31, atk=31, def_=31, spa=31, spd=31, spe=31),
        evs=Stats(hp=0, atk=0, def_=0, spa=0, spd=0, spe=0),
        nature="Serious",
        ability="",
        weight=0.1,
        item=None,
        moves=[],
        current_hp=100,
        max_hp=100,
        status=None,
        boosts={},
        volatiles={},
        tera_type="Normal",
        is_shiny=shiny,
    )


def _build_pokemon(
    species_id: str | None,
    *,
    display_name: str,
    level: int,
    item: str | None,
    tera_type: str | None,
    move_ids: list[str],
    shiny: bool,
) -> Pokemon:
    if species_id and species_id in SPECIES_BY_ID:
        pokemon = create_pokemon(species_id=species_id, level=level, is_shiny=shiny)
    else:
        pokemon = _placeholder_pokemon(display_name, level, shiny)
    pokemon.name = display_name or pokemon.name
    pokemon.item = item or None
    pokemon.moves = list(move_ids)
    if species_id and species_id in SPECIES_BY_ID:
        species_data = SPECIES_BY_ID[species_id]
        pokemon.id = species_data["id"]
        pokemon.types = list(species_data.get("types") or pokemon.types)
        pokemon.tera_type = str(tera_type or "").strip() or (species_data.get("types") or [pokemon.tera_type or "Normal"])[0]
    elif tera_type:
        pokemon.tera_type = str(tera_type).strip()
    return pokemon


def _move_ids_from_side_pokemon(side_pokemon: dict[str, Any], active_payload: dict[str, Any] | None) -> list[str]:
    move_ids: list[str] = []
    for move in side_pokemon.get("moves") or []:
        move_id = str(move or "").strip()
        if move_id:
            move_ids.append(move_id)
    if move_ids or not active_payload:
        return move_ids
    for move in active_payload.get("moves") or []:
        move_id = str(move.get("id") or "").strip()
        if move_id:
            move_ids.append(move_id)
    return move_ids


def build_team_from_showdown_request(request: dict[str, Any]) -> list[Pokemon]:
    side = request.get("side") or {}
    side_pokemon = list(side.get("pokemon") or [])
    active_payloads = list(request.get("active") or [])
    active_index = 0
    team: list[Pokemon] = []

    for pokemon_data in side_pokemon:
        details = str(pokemon_data.get("details") or pokemon_data.get("ident") or "Pokemon")
        display_name = _details_name(details) or "Pokemon"
        level = _parse_level(details)
        shiny = bool(pokemon_data.get("shiny"))
        species_data = SPECIES_BY_NORMALIZED_NAME.get(_normalized(display_name), {})
        species_id = str(species_data.get("id") or "").strip() or None
        active_payload = None
        if pokemon_data.get("active") and active_index < len(active_payloads):
            active_payload = active_payloads[active_index]
            active_index += 1
        move_ids = _move_ids_from_side_pokemon(pokemon_data, active_payload)
        item_name = str(pokemon_data.get("item") or "").strip() or None
        tera_type = (
            str(pokemon_data.get("teraType") or "").strip()
            or str((active_payload or {}).get("teraType") or "").strip()
            or str(pokemon_data.get("terastallized") or "").strip()
            or str((active_payload or {}).get("terastallized") or "").strip()
            or None
        )
        team.append(
            _build_pokemon(
                species_id,
                display_name=display_name,
                level=level,
                item=item_name,
                tera_type=tera_type,
                move_ids=move_ids,
                shiny=shiny,
            )
        )
    return team


def format_team_detail_text(team_name: str, team_pokemon: list[Pokemon]) -> str:
    lines = [f"Team Detail: {team_name}"]
    for pokemon in team_pokemon:
        type_text = "/".join(pokemon.types) if pokemon.types else "Unknown"
        header = f"{pokemon.name} [{type_text}]"
        if pokemon.item:
            header += f" @ {pokemon.item}"
        lines.append("")
        lines.append(header)
        lines.append(f"Tera Type: {pokemon.tera_type or 'Unknown'}")
        lines.append("Moves")
        move_names = [
            str(MOVE_BY_ID.get(move_id, {}).get("name") or move_id.replace("-", " ").title())
            for move_id in pokemon.moves[:4]
        ]
        while len(move_names) < 4:
            move_names.append("—")
        for index, move_name in enumerate(move_names, start=1):
            lines.append(f"{index}. {move_name}")
    return "\n".join(lines).strip()
