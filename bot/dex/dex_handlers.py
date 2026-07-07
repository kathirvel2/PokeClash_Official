# ./bot/dex/dex_handlers.py
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from bot.mechanics.item_data import ITEMS_BY_NORMALIZED_NAME
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID, ABILITIES_BY_ID, LEARNSETS
from bot.handlers.command_handlers import levenshtein_distance
from bot.handlers.decorators import user_not_banned
from .dex_ui import (
    format_pokemon_dex_entry, format_move_dex_entry, format_ability_dex_entry, format_item_dex_entry,
    get_pokemon_dex_keyboard, get_forms_keyboard, format_pokemon_movelist,
    get_move_flags_menu, format_moves_by_flag_list
)
import html
import math
import json
import os
import re
# --- THIS IS NEW ---
from telebot.types import WebAppInfo
# --- END NEW ---

DEX_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DATA_PATH = os.path.join(DEX_DIR, 'pokemon_images.json')

POKEMON_IMAGE_URLS = {}
try:
    with open(IMAGE_DATA_PATH, 'r', encoding='utf-8') as f:
        image_data = json.load(f)
        # Create a dictionary mapping the NORMALIZED lowercase name to image_url
        for item in image_data:
            pokemon_name = item.get("pokemon_name", "")
            if pokemon_name:
                # Normalize: lowercase, remove hyphens and spaces
                normalized_key = pokemon_name.lower().replace("-", "").replace(" ", "")

                # Handle Nidoran symbols during key creation
                normalized_key = normalized_key.replace("♀", "f").replace("♂", "m") # Replace symbols

                # Only add if the key doesn't exist yet to avoid overwriting (takes the first found)
                # Or you could prioritize based on URL structure if needed
                if normalized_key not in POKEMON_IMAGE_URLS:
                    POKEMON_IMAGE_URLS[normalized_key] = item.get("image_url")

    print(f"Successfully loaded {len(POKEMON_IMAGE_URLS)} Pokémon image URLs (normalized keys).")
except FileNotFoundError:
    print(f"WARNING: pokemon_images.json not found at {IMAGE_DATA_PATH}")
except json.JSONDecodeError:
    print(f"ERROR: Could not decode pokemon_images.json")
except Exception as e:
    print(f"An unexpected error occurred loading pokemon_images.json: {e}")

# --- NEW HELPER FUNCTION ---
def _get_url_name(name: str) -> str:
    """Converts a name like 'Belly Drum' or "King's Shield" to 'belly-drum' or 'kings-shield' for URLs."""
    # Converts to lowercase, removes problematic punctuation like apostrophes,
    # and replaces spaces with hyphens.
    return name.lower().replace("'", "").replace(" ", "-")
# --- END NEW HELPER FUNCTION ---

def _normalize_dex_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())

def register_dex_handlers(bot: AsyncTeleBot):
    """Registers the /dex command handler."""

    # --- DEFINE BOTH URLS ---
    WEB_APP_URL_DIRECT = "https://pokeclashdex.onrender.com"
    WEB_APP_URL_TELEGRAM = "https://t.me/PokeClash_bot/Pokeclashdex"
    # --- END ---

    @bot.message_handler(commands=['dex'], func=lambda message: message.text.strip().lower() == '/dex moves')
    @user_not_banned(bot)
    async def dex_moves_command(message):
        text, markup = get_move_flags_menu(page=0) # Start at the first page
        await bot.reply_to(message, text, reply_markup=markup, parse_mode="HTML")

    @bot.message_handler(commands=['dex'], func=lambda message: message.text.strip().lower() != '/dex moves')
    @user_not_banned(bot)
    async def dex_command(message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            usage_text = "Please specify a Pokémon, Move, Ability, or Item name.\n\n<b>Usage:</b> <code>/dex &lt;name&gt;</code>"
            markup = types.InlineKeyboardMarkup()
            # --- MODIFICATION ---
            if message.chat.type == 'private':
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open Web Dex",
                    web_app=WebAppInfo(url=f"{WEB_APP_URL_DIRECT}/") # Use direct link for private chat
                ))
            else:
                 markup.add(types.InlineKeyboardButton(
                    "🌐 Open Web Dex",
                    url=WEB_APP_URL_TELEGRAM # Use t.me link for groups
                ))
            # --- END MODIFICATION ---
            await bot.reply_to(message, usage_text, parse_mode="HTML", reply_markup=markup)
            return

        query = parts[1].strip()

        query_lower = _normalize_dex_name(query)

        species_data = next((s for s in SPECIES_BY_ID.values() if _normalize_dex_name(s['name']) == query_lower), None)
        if species_data:
            response_text = format_pokemon_dex_entry(species_data)
            # Pass the chat_type to the keyboard generator
            keyboard = get_pokemon_dex_keyboard(species_data, message.chat.type, WEB_APP_URL_DIRECT, WEB_APP_URL_TELEGRAM)
            await bot.reply_to(message, response_text, parse_mode="HTML", reply_markup=keyboard)
            return

        move_data = next((m for m in MOVE_BY_ID.values() if _normalize_dex_name(m['name']) == query_lower), None)
        if move_data:
            response_text = format_move_dex_entry(move_data)
            markup = types.InlineKeyboardMarkup()
            
            url_name = _get_url_name(move_data['name'])
            
            # --- MODIFICATION ---
            if message.chat.type == 'private':
                final_url = f"{WEB_APP_URL_DIRECT}/move-details.html?name={url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    web_app=WebAppInfo(url=final_url)
                ))
            else:
                final_url = f"{WEB_APP_URL_TELEGRAM}?startapp=move-{url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    url=final_url
                ))
            # --- END MODIFICATION ---
            await bot.reply_to(message, response_text, parse_mode="HTML", reply_markup=markup)
            return
        
        ability_data = next((a for a in ABILITIES_BY_ID.values() if _normalize_dex_name(a['name']) == query_lower), None)
        if ability_data:
            response_text = format_ability_dex_entry(ability_data)
            markup = types.InlineKeyboardMarkup()

            url_name = _get_url_name(ability_data['name'])

            # --- MODIFICATION ---
            if message.chat.type == 'private':
                final_url = f"{WEB_APP_URL_DIRECT}/ability-details.html?name={url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    web_app=WebAppInfo(url=final_url)
                ))
            else:
                final_url = f"{WEB_APP_URL_TELEGRAM}?startapp=ability-{url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    url=final_url
                ))
            # --- END MODIFICATION ---
            await bot.reply_to(message, response_text, parse_mode="HTML", reply_markup=markup)
            return

        item_data = ITEMS_BY_NORMALIZED_NAME.get(query_lower)
        if item_data:
            await bot.reply_to(message, format_item_dex_entry(item_data), parse_mode="HTML")
            return
        
        all_names = {_normalize_dex_name(s['name']): s['name'] for s in SPECIES_BY_ID.values()}
        all_names.update({_normalize_dex_name(m['name']): m['name'] for m in MOVE_BY_ID.values()})
        all_names.update({_normalize_dex_name(a['name']): a['name'] for a in ABILITIES_BY_ID.values()})
        all_names.update({_normalize_dex_name(item['name']): item['name'] for item in ITEMS_BY_NORMALIZED_NAME.values()})
        
        best_match_name = None
        min_dist = 3
        for name_key, display_name in all_names.items():
            dist = levenshtein_distance(query_lower, name_key)
            if dist < min_dist:
                min_dist = dist
                best_match_name = display_name
        
        if best_match_name:
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("✅ Yes", callback_data=f"dex_confirm_{best_match_name}"),
                types.InlineKeyboardButton("❌ No", callback_data="dex_cancel")
            )
            await bot.reply_to(message, f"I couldn't find '{query}'. Did you mean <b>{best_match_name}</b>?", reply_markup=markup, parse_mode="HTML")
        else:
            await bot.reply_to(message, f"Sorry, I couldn't find any Pokémon, Move, Ability, or Item named '{query}'.")

async def handle_dex_callbacks(bot: AsyncTeleBot, call: types.CallbackQuery):
    """Handles all callback queries with the 'dex_' prefix."""
    
    # --- DEFINE BOTH URLS ---
    WEB_APP_URL_DIRECT = "https://pokeclashdex.onrender.com"
    WEB_APP_URL_TELEGRAM = "https://t.me/PokeClash_bot/Pokeclashdex"
    # --- END ---

    parts = call.data.split('_')
    action = parts[1]

    if action == "flags":
        sub_action = parts[2]
        
        if sub_action == "main":
            # This now handles pagination for the main flags menu
            page = int(parts[3]) if len(parts) > 3 else 0
            text, markup = get_move_flags_menu(page=page)
            try:
                await bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")
            except Exception as e:
                if "message is not modified" not in str(e):
                    print(f"Error editing dex flags menu: {e}")
        
        elif sub_action == "list":
            # This part for showing the list of moves remains the same
            flag = parts[3]
            page = int(parts[4])
            content, markup = format_moves_by_flag_list(flag, page)
            try:
                await bot.edit_message_text(content, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")
            except Exception as e:
                if "message is not modified" not in str(e):
                    print(f"Error editing dex flags list: {e}")

        await bot.answer_callback_query(call.id)
        return

    if action == "moves":
        species_id = parts[2]
        page = int(parts[3])
        species_data = SPECIES_BY_ID.get(species_id)
        if species_data:
            content, markup = format_pokemon_movelist(species_data, page)
            if content:
                try:
                    await bot.edit_message_text(content, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")
                except Exception as e:
                    if "message is not modified" not in str(e):
                        print(f"Error editing movelist: {e}")
        await bot.answer_callback_query(call.id)
        return

    if action == "cancel":
        await bot.edit_message_text("Okay, cancelled.", call.message.chat.id, call.message.id, reply_markup=None)
        await bot.answer_callback_query(call.id)
        return

    if action == "confirm":
        name_to_search = "_".join(parts[2:])
        name_lower = _normalize_dex_name(name_to_search)

        species_data = next((s for s in SPECIES_BY_ID.values() if _normalize_dex_name(s['name']) == name_lower), None)
        if species_data:
            response_text = format_pokemon_dex_entry(species_data)
            # Pass the chat_type from the callback message
            keyboard = get_pokemon_dex_keyboard(species_data, call.message.chat.type, WEB_APP_URL_DIRECT, WEB_APP_URL_TELEGRAM)
            await bot.edit_message_text(response_text, call.message.chat.id, call.message.id, parse_mode="HTML", reply_markup=keyboard)
            await bot.answer_callback_query(call.id)
            return

        move_data = next((m for m in MOVE_BY_ID.values() if _normalize_dex_name(m['name']) == name_lower), None)
        if move_data:
            response_text = format_move_dex_entry(move_data)
            markup = types.InlineKeyboardMarkup()
            
            # --- MODIFICATION ---
            url_name = _get_url_name(move_data['name'])
            if call.message.chat.type == 'private':
                final_url = f"{WEB_APP_URL_DIRECT}/move-details.html?name={url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    web_app=WebAppInfo(url=final_url)
                ))
            else:
                final_url = f"{WEB_APP_URL_TELEGRAM}?startapp=move-{url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    url=final_url
                ))
            # --- END MODIFICATION ---

            await bot.edit_message_text(response_text, call.message.chat.id, call.message.id, parse_mode="HTML", reply_markup=markup)
            await bot.answer_callback_query(call.id)
            return
        
        ability_data = next((a for a in ABILITIES_BY_ID.values() if _normalize_dex_name(a['name']) == name_lower), None)
        if ability_data:
            response_text = format_ability_dex_entry(ability_data)
            markup = types.InlineKeyboardMarkup()
            
            # --- MODIFICATION ---
            url_name = _get_url_name(ability_data['name'])
            if call.message.chat.type == 'private':
                final_url = f"{WEB_APP_URL_DIRECT}/ability-details.html?name={url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    web_app=WebAppInfo(url=final_url)
                ))
            else:
                final_url = f"{WEB_APP_URL_TELEGRAM}?startapp=ability-{url_name}"
                markup.add(types.InlineKeyboardButton(
                    "🌐 Open in Web Dex",
                    url=final_url
                ))
            # --- END MODIFICATION ---

            await bot.edit_message_text(response_text, call.message.chat.id, call.message.id, parse_mode="HTML", reply_markup=markup)
            await bot.answer_callback_query(call.id)
            return

        item_data = ITEMS_BY_NORMALIZED_NAME.get(name_lower)
        if item_data:
            await bot.edit_message_text(format_item_dex_entry(item_data), call.message.chat.id, call.message.id, parse_mode="HTML", reply_markup=None)
            await bot.answer_callback_query(call.id)
            return
        
        await bot.edit_message_text("Sorry, an error occurred with that name.", call.message.chat.id, call.message.id, reply_markup=None)
        await bot.answer_callback_query(call.id, "Error!", show_alert=True)
        return

    species_id = parts[2]
    species_data = SPECIES_BY_ID.get(species_id)
    if not species_data:
        await bot.answer_callback_query(call.id, "Error: Pokémon data not found.", show_alert=True)
        return

    if action == "forms":
        forms_keyboard = get_forms_keyboard(species_data)
        await bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=forms_keyboard)
        await bot.answer_callback_query(call.id)

    elif action == "view":
        new_text = format_pokemon_dex_entry(species_data)
        # Pass the chat_type from the callback message
        new_keyboard = get_pokemon_dex_keyboard(species_data, call.message.chat.type, WEB_APP_URL_DIRECT, WEB_APP_URL_TELEGRAM)
        
        try:
            await bot.edit_message_text(
                new_text,
                call.message.chat.id,
                call.message.id,
                parse_mode="HTML",
                reply_markup=new_keyboard
            )
            await bot.answer_callback_query(call.id)
        except Exception as e:
            if "message is not modified" in str(e):
                await bot.answer_callback_query(call.id)
            else:
                print(f"Error editing dex message: {e}")

# --- UPDATED MOVELIST LOGIC ---

async def show_pokemon_movelist(bot: AsyncTeleBot, message_or_call, pokemon_name: str, page: int = 0):
    """
    Displays a paginated list of moves for a given Pokémon.
    Can be initiated by a message or updated via a callback query.
    """
    is_callback = isinstance(message_or_call, types.CallbackQuery)
    chat_id = message_or_call.chat.id if is_callback else message_or_call.chat.id
    message_id = message_or_call.message.id if is_callback else message_or_call.message_id

    query_lower = pokemon_name.lower().replace("-", "").replace(" ", "")
    species_data = next((s for s in SPECIES_BY_ID.values() if s['name'].lower().replace("-", "").replace(" ", "") == query_lower), None)

    if not species_data:
        await bot.reply_to(message_or_call, f"Sorry, I couldn't find a Pokémon named '{pokemon_name}'.")
        return

    content, markup = _generate_movelist_content_and_keyboard(species_data, page)
    
    if not content:
        await bot.reply_to(message_or_call, f"{species_data['name']} has no moves in its learnset.")
        return
    
    if is_callback:
        await bot.edit_message_text(content, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    else:
        await bot.reply_to(message_or_call, content, reply_markup=markup, parse_mode="HTML")

def _parse_learn_method(methods: list) -> str:
    """Parses the learnset array to find the most relevant learn method."""
    # Sort by generation descending to prioritize newer games
    sorted_methods = sorted(methods, key=lambda m: int(m[0]), reverse=True)
    
    # Priority: Level -> TM/HM -> Egg -> Tutor
    for method_char in ['L', 'M', 'E', 'T']:
        for method in sorted_methods:
            if method.endswith('R'): continue # Skip Restricted methods
            if method[1] == method_char:
                if method_char == 'L':
                    return f"Lvl {method[2:]}"
                elif method_char == 'M':
                    return "TM/HM"
                elif method_char == 'E':
                    return "Egg"
                elif method_char == 'T':
                    return "Tutor"
    return "Event" # Fallback for special moves

def _generate_movelist_content_and_keyboard(species_data: dict, page: int = 0):
    """Helper function to generate the numbered list and keyboard for the movelist."""
    species_id = species_data['id']
    learnset_data = LEARNSETS.get(species_id, {}).get("learnset", {})
    
    if not learnset_data:
        return None, None

    # Create a list of tuples: (move_name, learn_method_string)
    move_details = []
    for move_id, methods in learnset_data.items():
        if move_id in MOVE_BY_ID:
            move_name = MOVE_BY_ID[move_id]['name']
            learn_method = _parse_learn_method(methods)
            move_details.append((move_name, learn_method))

    # Sort alphabetically by move name
    move_details.sort(key=lambda x: x[0])
    
    items_per_page = 20
    total_pages = math.ceil(len(move_details) / items_per_page)
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    page_moves = move_details[start_index:end_index]

    if not page_moves:
        return None, None

    # --- THIS IS THE MODIFIED PART ---
    # Format into a single, numbered list instead of columns
    formatted_list_parts = []
    for i, (name, method) in enumerate(page_moves, start=start_index + 1):
        formatted_list_parts.append(f"<code>{i}. {name} ({method})</code>")
    
    formatted_list = "\n".join(formatted_list_parts)
    # --- END OF MODIFICATION ---

    content = (
        f"<b>Available Moves for {species_data['name']}</b>\n"
        f"Page {page + 1}/{total_pages}\n\n"
        f"{formatted_list}"
    )

    markup = types.InlineKeyboardMarkup()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"dex_mv_{species_id}_{page - 1}"))
    if end_index < len(move_details):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"dex_mv_{species_id}_{page + 1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)

    return content, markup

DEX_IMAGE_NAME_EXCEPTIONS = {
    "necrozmaduskmane": "necrozma-dusk",
    "necrozmadawnwings": "necrozma-dawn",
    "urshifurapidstrike": "urshifu-rapid-strike",
    # Add any other inconsistencies you find here
}

def get_pokemon_image_url(species_data: dict) -> str | None:
    """
    MODIFIED: Gets the image URL using a more robust, multi-step lookup process
    that mirrors the downloader and sprite-finding logic.
    """
    pokemon_name = species_data.get("name")
    pokemon_id = species_data.get("id")
    if not pokemon_name or not pokemon_id:
        return None

    # --- NEW, MORE ACCURATE LOOKUP LOGIC ---
    
    # 1. Create a list of potential keys to try, in order of priority.
    keys_to_try = []

    # Priority 1: Check for a known, hardcoded exception.
    if pokemon_id in DEX_IMAGE_NAME_EXCEPTIONS:
        exception_name = DEX_IMAGE_NAME_EXCEPTIONS[pokemon_id]
        keys_to_try.append(exception_name.lower().replace("-", "").replace(" ", ""))

    # Priority 2: Use the full, formatted name.
    # e.g., "Necrozma-Dusk-Mane" -> "necrozmaduskmane"
    formatted_name_key = pokemon_name.lower().replace("-", "").replace(" ", "")
    keys_to_try.append(formatted_name_key)

    # Priority 3: Use the base species name as a fallback.
    base_species_name = species_data.get("baseSpecies")
    if base_species_name:
        base_species_key = base_species_name.lower().replace("-", "").replace(" ", "")
        keys_to_try.append(base_species_key)

    # Remove duplicates
    keys_to_try = list(dict.fromkeys(keys_to_try))

    # 2. Loop through the potential keys and return the first valid URL found.
    for key in keys_to_try:
        # Also handle Nidoran symbols during the final lookup
        normalized_key = key.replace("♀", "f").replace("♂", "m")
        url = POKEMON_IMAGE_URLS.get(normalized_key)
        if url:
            return url # Success!

    # 3. If no URL was found after trying all keys, return None.
    return None
