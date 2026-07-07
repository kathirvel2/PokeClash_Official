# ./bot/battle/dynamax/dynamax_ui.py
from telebot import types
from typing import TYPE_CHECKING
from bot.mechanics.moves_loader import MOVE_BY_ID
from .dynamax_utils import get_gmax_form
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID
from .dynamax_utils import get_gmax_form
if TYPE_CHECKING:
    from bot.battle.battle_engine import ActivePokemon

# Mapping from type to its standard Max Move
TYPE_TO_MAX_MOVE = {
    "Normal": "maxstrike", "Fire": "maxflare", "Water": "maxgeyser",
    "Grass": "maxovergrowth", "Electric": "maxlightning", "Ice": "maxhailstorm",
    "Fighting": "maxknuckle", "Poison": "maxooze", "Ground": "maxquake",
    "Flying": "maxairstream", "Psychic": "maxmindstorm", "Bug": "maxflutterby",
    "Rock": "maxrockfall", "Ghost": "maxphantasm", "Dragon": "maxwyrmwind",
    "Dark": "maxdarkness", "Steel": "maxsteelspike", "Fairy": "maxstarfall"
}

def get_dynamax_move_for_pokemon(base_move_id: str, pokemon: "ActivePokemon") -> str:
    """Finds the correct Max or G-Max move ID for a given base move."""
    base_move_data = MOVE_BY_ID[base_move_id]

    if base_move_data['category'] == 'Status':
        return 'maxguard'

    # Get the Pokémon's fundamental species name (e.g., "Pikachu").
    species_data = SPECIES_BY_ID.get(pokemon.pokemon.id, {})
    base_species_name = species_data.get("baseSpecies", pokemon.pokemon.name)
    
    # --- THIS IS THE CORRECTED LOGIC ---
    # A Pokémon is G-Max capable if its current ID contains "-gmax" OR
    # if a G-Max form exists for its base ID.
    is_gmax_capable = "gmax" in pokemon.pokemon.id or get_gmax_form(pokemon.pokemon.id) is not None

    if is_gmax_capable:
        for move_id, move_data in MOVE_BY_ID.items():
            # Compare the move's "isMax" field ("Pikachu") to the base_species_name ("Pikachu")
            if move_data.get("isMax") == base_species_name and move_data.get("type") == base_move_data['type']:
                return move_id  # Success! We found the G-Max move.

    # Fallback to the standard Max Move if no G-Max move was found
    return TYPE_TO_MAX_MOVE.get(base_move_data['type'], 'maxstrike')
    
def add_dynamax_button(markup: types.InlineKeyboardMarkup, can_dynamax: bool):
    """Adds the Dynamax button to the keyboard markup if eligible."""
    if can_dynamax:
        dynamax_button = types.InlineKeyboardButton("Dynamax 🔥", callback_data="b_dynamax_prime")
        markup.row(dynamax_button)

def prime_dynamax_buttons(active_pokemon: "ActivePokemon") -> types.InlineKeyboardMarkup:
    """Creates a new keyboard with primed Max/G-Max move buttons."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    move_buttons = []
    for i, move_id in enumerate(active_pokemon.pokemon.moves):
        max_move_id = get_dynamax_move_for_pokemon(move_id, active_pokemon)
        max_move_data = MOVE_BY_ID.get(max_move_id)
        if max_move_data:
            button_text = f"🔥 {max_move_data['name']}"
            callback_data = f"b_m_{i}_dynamax"
            move_buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))

    while len(move_buttons) < 4:
        move_buttons.append(types.InlineKeyboardButton(" ", callback_data="b_noop"))

    markup.add(*move_buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Cancel Dynamax", callback_data="b_back_moves"))
    return markup