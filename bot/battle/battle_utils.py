import math
from bot.mechanics.team import Pokemon
from bot.mechanics.moves_loader import NATURES_DATA, SPECIES_BY_ID
import os
from typing import Optional
from bot.mechanics.item_data import ITEM_ID_BY_NAME
from bot.mechanics.moves_loader import MOVE_BY_ID
from bot.battle.z_move_data import Z_CRYSTAL_TYPE_MAP, SIGNATURE_Z_MOVES

ARTWORK_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

def calculate_stat(base: int, iv: int, ev: int, level: int, nature_mod: float) -> int:
    """Calculates a single non-HP stat for a Pokémon."""
    # Formula: floor( ( ( (2 * Base + IV + floor(EV/4)) * Level ) / 100 ) + 5 ) * Nature
    s = math.floor(((2 * base + iv + math.floor(ev / 4)) * level) / 100) + 5
    return math.floor(s * nature_mod)

def calculate_hp(base: int, iv: int, ev: int, level: int) -> int:
    """Calculates the HP stat for a Pokémon."""
    # --- ADD THIS IF-STATEMENT ---
    # Shedinja clause
    if base == 1:
        return 1
    # --- END OF ADDITION ---

    # Formula: floor( ( (2 * Base + IV + floor(EV/4)) * Level ) / 100 ) + Level + 10
    return math.floor(((2 * base + iv + math.floor(ev / 4)) * level) / 100) + level + 10

def get_actual_stats(pokemon: Pokemon) -> dict:
    """
    Calculates and returns the final, in-battle stats of a Pokémon.
    """
    stats = {
        'hp': 0, 'atk': 0, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 0
    }
    
    nature_info = NATURES_DATA.get(pokemon.nature.lower(), {})
    nature_mods = {
        'atk': 1.0, 'def': 1.0, 'spa': 1.0, 'spd': 1.0, 'spe': 1.0
    }

    if nature_info.get("plus"):
        nature_mods[nature_info["plus"]] = 1.1
    if nature_info.get("minus"):
        nature_mods[nature_info["minus"]] = 0.9

    # Calculate HP
    stats['hp'] = calculate_hp(pokemon.base_stats.hp, pokemon.ivs.hp, pokemon.evs.hp, pokemon.level)

    # Calculate other stats
    stats['atk'] = calculate_stat(pokemon.base_stats.atk, pokemon.ivs.atk, pokemon.evs.atk, pokemon.level, nature_mods['atk'])
    stats['def'] = calculate_stat(pokemon.base_stats.def_, pokemon.ivs.def_, pokemon.evs.def_, pokemon.level, nature_mods['def'])
    stats['spa'] = calculate_stat(pokemon.base_stats.spa, pokemon.ivs.spa, pokemon.evs.spa, pokemon.level, nature_mods['spa'])
    stats['spd'] = calculate_stat(pokemon.base_stats.spd, pokemon.ivs.spd, pokemon.evs.spd, pokemon.level, nature_mods['spd'])
    stats['spe'] = calculate_stat(pokemon.base_stats.spe, pokemon.ivs.spe, pokemon.evs.spe, pokemon.level, nature_mods['spe'])

    return stats

def can_use_z_move(player: 'BattlePlayer', battle: 'Battle') -> bool:
    """Checks if the player's active Pokémon can use a Z-Move."""
    if player.has_used_z_move:
        return False

    active_pokemon = player.get_active_pokemon()
    pokemon_item = active_pokemon.pokemon.item

    if not pokemon_item or not pokemon_item.endswith(" Z"):
        return False

    item_id = ITEM_ID_BY_NAME.get(pokemon_item)
    if not item_id:
        return False

    required_z_crystal_type = Z_CRYSTAL_TYPE_MAP.get(item_id)

    for move_id in active_pokemon.pokemon.moves:
        move_data = MOVE_BY_ID.get(move_id, {})
        if not move_data:
            continue
            
        # --- THIS IS THE NEW LOGIC BLOCK TO ADD ---
        # Path A: Signature Z-Move (e.g., Pikanium Z + Volt Tackle)
        signature_info = SIGNATURE_Z_MOVES.get(move_id)
        if signature_info and \
           signature_info['item_id'] == item_id and \
           signature_info['pokemon_id'] == active_pokemon.pokemon.id:
            return True # Found a valid signature Z-Move combination
        # --- END OF NEW LOGIC BLOCK ---

        # Path B: Generic Z-Move (e.g., Fairium Z + Moonblast)
        if required_z_crystal_type and move_data.get('type') == required_z_crystal_type:
            return True # Found a compatible generic Z-Move by type

    return False

def can_mega_evolve(player: 'BattlePlayer', battle: 'Battle') -> bool:
    """
    REFINED: Checks if the player's active Pokémon can perform a special
    battle transformation (Mega, Primal, Crowned). This is the definitive check.
    """
    # 1. Standard checks: Mechanic is allowed and player hasn't transformed yet.
    if not battle.mega_evolution_allowed or player.has_mega_evolved:
        return False

    active_pokemon = player.get_active_pokemon()
    pokemon_item = active_pokemon.pokemon.item
    species_info = SPECIES_BY_ID.get(active_pokemon.pokemon.id, {})
    base_species = species_info.get("baseSpecies", active_pokemon.pokemon.name)

    # 2. Handle no-item transformations (e.g., Rayquaza)
    if active_pokemon.pokemon.id == 'rayquaza' and 'dragonascent' in active_pokemon.pokemon.moves:
        return True

    # After this point, an item is required for any transformation.
    if not pokemon_item:
        return False

    # 3. Handle specific, non-Mega-Stone transformations (Primals, Crowned forms)
    # This whitelist is the most reliable way to handle these exceptions.
    special_transformation_map = {
        "Groudon": "Red Orb",
        "Kyogre": "Blue Orb",
        "Zacian": "Rusted Sword",
        "Zamazenta": "Rusted Shield"
    }
    if base_species in special_transformation_map and pokemon_item == special_transformation_map[base_species]:
        return True

    # 4. Handle all standard Mega Evolutions by checking the species data directly.
    # This is the most robust way and correctly handles "Charizardite X", "Mewtwonite Y", etc.
    for s_data in SPECIES_BY_ID.values():
        # Check if the species in the database is a form of our active Pokémon,
        # requires the exact item our Pokémon is holding,
        # and is explicitly a "Mega" form.
        if (
            s_data.get("baseSpecies") == base_species and
            s_data.get("requiredItem") == pokemon_item and
            "mega" in s_data.get("name", "").lower()
        ):
            return True # It's a valid Mega Stone for a valid Mega form.

    # If none of the above specific conditions are met, it's not a transformation we should show the button for.
    return False

def find_best_sprite_path(pokemon: Pokemon, sprite_folder: str) -> Optional[str]:
    """
    MODIFIED: Finds the best available sprite file for a Pokémon, prioritizing
    hyphenated form names and handling special Mega X/Y names.
    """
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
    SPRITE_BASE_PATH = os.path.join(ASSETS_DIR, 'sprite')
    sprite_folders_to_try = [sprite_folder]

    if sprite_folder == 'image' and getattr(pokemon, 'is_shiny', False):
        sprite_folders_to_try = ['image-shiny', 'image']

    def first_existing(*names: str) -> Optional[str]:
        for folder_name in sprite_folders_to_try:
            for name in names:
                for extension in (ARTWORK_EXTENSIONS if folder_name.startswith("image") else (".png",)):
                    path = os.path.join(SPRITE_BASE_PATH, folder_name, f"{name}{extension}")
                    if os.path.exists(path):
                        return path
        return None

    if pokemon.id == 'necrozmaduskmane':
        # Try both 'necrozma-dusk-mane.png' and 'necrozma-dusk.png'
        resolved = first_existing('necrozma-duskmane', 'necrozma-dusk')
        if resolved:
            return resolved
    
    if pokemon.id == 'necrozmadawnwings':
        # Try both 'necrozma-dawn-wings.png' and 'necrozma-dawn.png'
        resolved = first_existing('necrozma-dawnwings', 'necrozma-dawn')
        if resolved:
            return resolved

    if pokemon.id == 'urshifurapidstrikegmax':
        resolved = first_existing('urshifu-rapidstrikegmax')
        if resolved:
            return resolved
    
    if pokemon.id == 'urshifurapidstrike':
        resolved = first_existing('urshifu-rapidstrike')
        if resolved:
            return resolved

    if pokemon.id == 'darmanitangalarzen':
        # Priority 1: Check for the exact filename you mentioned.
        resolved = first_existing("darmanitan-galarzen")
        if resolved:
            return resolved
        # Fallback: If it's not found, try the standard Galar form sprite.
        resolved = first_existing("darmanitan-galar")
        if resolved:
            return resolved
        return None
    
    ids_to_try = []
    
    # Priority 1: The formatted full name (e.g., 'Charizard-Mega-X' -> 'charizard-mega-x')
    formatted_name = pokemon.name.lower().replace(" ", "-").replace("’", "").replace(".", "")
    ids_to_try.append(formatted_name)

    # --- THIS IS THE FIX ---
    # Priority 2: Special Mega format (e.g., 'charizard-megax')
    if "-mega-" in formatted_name:
        abbreviated_mega_name = formatted_name.replace("-mega-", "-mega")
        ids_to_try.append(abbreviated_mega_name)
    # --- END OF FIX ---

    # Priority 3: The exact internal ID (e.g., 'charizardmegax')
    ids_to_try.append(pokemon.id)
    
    # Priority 4: The base species name (e.g., 'Charizard-Mega-X' -> 'charizard')
    species_info = SPECIES_BY_ID.get(pokemon.id, {})
    base_species_name = species_info.get("baseSpecies", pokemon.name)
    base_name = base_species_name.lower().replace(" ", "-").replace("’", "").replace(".", "")
    ids_to_try.append(base_name)
    
    # Remove duplicates to avoid checking the same file twice
    ids_to_try = list(dict.fromkeys(ids_to_try))

    # Loop through candidates and return the first path that exists
    for folder_name in sprite_folders_to_try:
        for image_id in ids_to_try:
            for extension in (ARTWORK_EXTENSIONS if folder_name.startswith("image") else (".png",)):
                path = os.path.join(SPRITE_BASE_PATH, folder_name, f"{image_id}{extension}")
                if os.path.exists(path):
                    return path
            
    return None

def can_item_form_change(pokemon: "ActivePokemon") -> bool:
    """Checks if the active Pokémon can change form with its held item."""
    if not pokemon.pokemon.item:
        return False

    species_info = SPECIES_BY_ID.get(pokemon.pokemon.id, {})
    base_species = species_info.get("baseSpecies", pokemon.pokemon.name)

    if base_species not in ["Arceus", "Silvally"]:
        return False

    # Check if any form of this species requires the held item
    for s_data in SPECIES_BY_ID.values():
        # --- FIX: Check the "requiredItems" LIST instead of "requiredItem" ---
        required_items = s_data.get("requiredItems")
        if s_data.get("baseSpecies") == base_species and isinstance(required_items, list) and pokemon.pokemon.item in required_items:
            # Return True only if the pokemon is NOT already in the target form
            return pokemon.pokemon.id != s_data['id']
            
    return False
