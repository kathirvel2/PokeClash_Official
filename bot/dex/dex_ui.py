# ./bot/dex/dex_ui.py
from telebot import types
from bot.mechanics.moves_loader import MOVE_BY_ID, SPECIES_BY_ID, ABILITIES_BY_ID, LEARNSETS
import html
import math
from telebot.types import WebAppInfo

ALL_MOVE_FLAGS = sorted(list(set(
    flag for move in MOVE_BY_ID.values() for flag in move.get('flags', {})
)))

def _get_stat_visualization(stat_name: str, base_stat: int) -> str:
    """
    Calculates min/max stats at Lv. 100 and generates a 5-block visualization.
    """
    # --- 1. Calculate Min/Max Stats ---
    if stat_name == 'hp':
        # Shedinja clause
        if base_stat == 1:
            min_stat, max_stat = 1, 1
        else:
            # Min HP (0 IVs, 0 EVs)
            min_stat = 2 * base_stat + 110
            # Max HP (31 IVs, 252 EVs)
            max_stat = 2 * base_stat + 204
    else:
        # Min Other Stat (0 IVs, 0 EVs, Hindering Nature)
        min_stat = math.floor((2 * base_stat + 5) * 0.9)
        # Max Other Stat (31 IVs, 252 EVs, Beneficial Nature)
        max_stat = math.floor((2 * base_stat + 99) * 1.1)

    # --- 2. Generate Block Visualization ---
    if base_stat >= 150:   blocks = 5
    elif base_stat >= 120:  blocks = 4
    elif base_stat >= 90:   blocks = 3
    elif base_stat >= 60:   blocks = 2
    elif base_stat >= 30:   blocks = 1
    else:                   blocks = 0
    
    vis_str = "⬢" * blocks + "⬡" * (5 - blocks)

    return f"({min_stat}-{max_stat}) {vis_str}"

def _suggest_natures(stats: dict) -> str:
    """Suggests competitively viable natures based on base stats."""
    atk = stats.get('atk', 0)
    spa = stats.get('spa', 0)
    spe = stats.get('spe', 0)

    suggestions = []
    if atk > spa + 10:
        suggestions.append("<b>Adamant</b> (+Atk, -SpA)")
        if spe > 60: suggestions.append("<b>Jolly</b> (+Spe, -SpA)")
    elif spa > atk + 10:
        suggestions.append("<b>Modest</b> (+SpA, -Atk)")
        if spe > 60: suggestions.append("<b>Timid</b> (+Spe, -Atk)")
    else:
        if spe > 80:
            suggestions.append("<b>Hasty</b> (+Spe, -Def)")
            suggestions.append("<b>Naive</b> (+Spe, -SpD)")
        else:
            suggestions.append("<b>Brave</b> (+Atk, -Spe)")
            suggestions.append("<b>Quiet</b> (+SpA, -Spe)")
    
    if not suggestions:
        return "<i>Standard natures like Adamant or Modest are a good starting point.</i>"
        
    return ", ".join(suggestions)

def format_pokemon_dex_entry(species_data: dict) -> str:
    """Formats a detailed Pokédex entry with an invisible link preview."""
    from bot.dex.dex_handlers import get_pokemon_image_url
    name = species_data.get('name', 'Unknown')

    # --- Get Image URL using the helper function ---
    image_url = get_pokemon_image_url(species_data) # Pass the dictionary
    link_preview = ""
    if image_url:
        link_preview = f'<a href="{image_url}">\u200B</a>'
    # ---

    num = species_data.get('num', '???')
    types = ", ".join(species_data.get('types', []))
    abilities = list(species_data.get('abilities', {}).values())
    hidden_ability = species_data.get('abilities', {}).get('H')

    ability_str = ""
    for i, ability in enumerate(abilities):
        if ability == hidden_ability:
            ability_str += f"<i>{html.escape(ability)} (H)</i>"
        else:
            ability_str += html.escape(ability)
        if i < len(abilities) - 1:
            ability_str += ", "

    stats = species_data.get('baseStats', {})
    bst = species_data.get('bst', 0)
    tier = species_data.get('tier', 'N/A')
    tags = species_data.get('tags', [])

    tier_info = f"<b>Tier:</b> {tier}"
    if tags:
        tier_info += f" ({', '.join(tags)})"

    suggested_natures = _suggest_natures(stats)

    # --- Prepend the link_preview ---
    entry = (
        f"{link_preview}"
        f"<b>{html.escape(name)}</b> - #{num}\n"
        f"<i>{types}</i>\n\n"
        f"{tier_info}\n"
        f"<b>Abilities:</b> {ability_str}\n\n"
        f"<b><u>Base Stats (BST: {bst})</u></b>\n"
        f"<code>HP:  {stats.get('hp', 0):>3} {_get_stat_visualization('hp', stats.get('hp', 0))}\n"
        f"Atk: {stats.get('atk', 0):>3} {_get_stat_visualization('atk', stats.get('atk', 0))}\n"
        f"Def: {stats.get('def', 0):>3} {_get_stat_visualization('def', stats.get('def', 0))}\n"
        f"SpA: {stats.get('spa', 0):>3} {_get_stat_visualization('spa', stats.get('spa', 0))}\n"
        f"SpD: {stats.get('spd', 0):>3} {_get_stat_visualization('spd', stats.get('spd', 0))}\n"
        f"Spe: {stats.get('spe', 0):>3} {_get_stat_visualization('spe', stats.get('spe', 0))}</code>\n\n"
        f"<b>Suggested Natures:</b>\n{suggested_natures}"
    )
    # ---

    return entry

def format_move_dex_entry(move_data: dict) -> str:
    name = move_data.get('name', 'Unknown')
    move_type = move_data.get('type', '???')
    category = move_data.get('category', '???')
    power = move_data.get('basePower', '—')
    accuracy = move_data.get('accuracy')
    pp = move_data.get('pp', '—')
    desc = move_data.get('shortDesc', 'No description available.')
    priority = move_data.get('priority', 0)

    acc_str = f"{accuracy}" if isinstance(accuracy, int) else "—"
    
    priority_str = ""
    if priority > 0:
        priority_str = f" (Priority: +{priority})"
    elif priority < 0:
        priority_str = f" (Priority: {priority})"

    entry = (
        f"<b>{html.escape(name)}</b>{priority_str}\n"
        f"<i>{html.escape(desc)}</i>\n\n"
        f"<b>Type:</b> {move_type}\n"
        f"<b>Category:</b> {category}\n\n"
        f"<b>Power:</b> <code>{power}</code>\n"
        f"<b>Accuracy:</b> <code>{acc_str}</code>\n"
        f"<b>PP:</b> <code>{pp}</code> (max {int(pp * 1.6)})"
    )
    
    return entry

def format_ability_dex_entry(ability_data: dict) -> str:
    name = ability_data.get('name', 'Unknown')
    desc = ability_data.get('desc', 'No description available.')
    rating = ability_data.get('rating', 'N/A')

    entry = (
        f"<b>{html.escape(name)}</b>\n"
        f"<i>{html.escape(desc)}</i>\n\n"
        f"<b>Competitive Rating:</b> {rating} / 5"
    )

    return entry

def format_item_dex_entry(item_data: dict) -> str:
    name = item_data.get('name', 'Unknown Item')
    desc = item_data.get('desc') or item_data.get('shortDesc') or 'No description available.'
    category = item_data.get('category', 'Item')
    gen = item_data.get('gen', 'N/A')
    item_num = item_data.get('num')

    lines = [
        f"<b>{html.escape(name)}</b>",
        f"<i>{html.escape(desc)}</i>",
        "",
        f"<b>Category:</b> {html.escape(str(category))}",
        f"<b>Introduced:</b> Gen {html.escape(str(gen))}",
    ]
    if item_num is not None:
        lines.append(f"<b>Item No.:</b> <code>{item_num}</code>")
    if item_data.get("isBerry"):
        lines.append("<b>Berry:</b> Yes")
    if item_data.get("isNonstandard"):
        lines.append(f"<b>Legality:</b> {html.escape(str(item_data['isNonstandard']))}")

    natural_gift = item_data.get("naturalGift") or {}
    if natural_gift:
        parts = []
        if natural_gift.get("type"):
            parts.append(f"{natural_gift['type']} type")
        if natural_gift.get("basePower"):
            parts.append(f"{natural_gift['basePower']} BP")
        if parts:
            lines.append(f"<b>Natural Gift:</b> {html.escape(', '.join(str(part) for part in parts))}")

    fling = item_data.get("fling") or {}
    if fling:
        parts = []
        if fling.get("basePower"):
            parts.append(f"{fling['basePower']} BP")
        if fling.get("status"):
            parts.append(f"status {fling['status']}")
        if fling.get("volatileStatus"):
            parts.append(f"volatile {fling['volatileStatus']}")
        if parts:
            lines.append(f"<b>Fling:</b> {html.escape(', '.join(str(part) for part in parts))}")

    mega_stone = item_data.get("megaStone") or {}
    if mega_stone:
        users = item_data.get("itemUser") or list(mega_stone.keys())
        targets = ", ".join(mega_stone.values())
        lines.append(f"<b>Mega Evolves:</b> {html.escape(', '.join(users))} -> {html.escape(targets)}")
    elif item_data.get("itemUser"):
        lines.append(f"<b>Used By:</b> {html.escape(', '.join(item_data['itemUser']))}")

    special_fields = []
    if item_data.get("zMove"):
        special_fields.append(f"Z-Move: {item_data['zMove']}")
    if item_data.get("zMoveType"):
        special_fields.append(f"Z-Type: {item_data['zMoveType']}")
    if item_data.get("onPlate"):
        special_fields.append(f"Plate Type: {item_data['onPlate']}")
    if item_data.get("forcedForme"):
        special_fields.append(f"Forced Form: {item_data['forcedForme']}")
    if special_fields:
        lines.append("<b>Special:</b> " + html.escape("; ".join(str(field) for field in special_fields)))

    return "\n".join(lines)

def get_pokemon_dex_keyboard(species_data: dict, chat_type: str, direct_url: str, telegram_url: str) -> types.InlineKeyboardMarkup | None:
    """
    MODIFIED: Accepts the base URLs to use for private vs group chats.
    """
    base_species = species_data.get("baseSpecies", species_data["name"])
    pokemon_num_id = species_data.get("num") 

    other_forms = [
        s for s in SPECIES_BY_ID.values()
        if s.get("baseSpecies") == base_species and s["id"] != species_data["id"]
    ]

    markup = types.InlineKeyboardMarkup()
    
    # Add the regular callback buttons first
    markup.add(types.InlineKeyboardButton("📜 View Moveset", callback_data=f"dex_moves_{species_data['id']}_0"))
    
    if other_forms:
        markup.add(types.InlineKeyboardButton("🔄 Other Forms", callback_data=f"dex_forms_{species_data['id']}"))
        
    # --- THIS IS THE MODIFICATION ---
    if chat_type == 'private':
        # Use the direct onrender.com link for WebAppInfo in private chats
        final_url = f"{direct_url}/details.html?id={pokemon_num_id}"
        markup.add(
            types.InlineKeyboardButton(
                "🌐 Open in Web Dex", 
                web_app=WebAppInfo(url=final_url)
            )
        )
    else:
        # Use the t.me link as a regular URL in group chats
        final_url = f"{telegram_url}?startapp=id-{pokemon_num_id}"
        markup.add(
            types.InlineKeyboardButton(
                "🌐 Open in Web Dex", 
                url=final_url
            )
        )
    # --- END OF MODIFICATION ---
    
    return markup

def get_forms_keyboard(species_data: dict) -> types.InlineKeyboardMarkup:
    base_species = species_data.get("baseSpecies", species_data["name"])
    
    all_forms = sorted(
        [s for s in SPECIES_BY_ID.values() if s.get("baseSpecies") == base_species],
        key=lambda x: x['name']
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    for form in all_forms:
        prefix = "✅ " if form['id'] == species_data['id'] else ""
        buttons.append(
            types.InlineKeyboardButton(f"{prefix}{form['name']}", callback_data=f"dex_view_{form['id']}")
        )
    
    markup.add(*buttons)
    return markup

def _parse_all_learn_methods(methods: list) -> str:
    """
    Parses the learnset array into a comma-separated string of all unique learn methods.
    """
    # Use a set to store unique, human-readable methods
    unique_methods = set()
    
    # Keep track of levels to show only the earliest one
    earliest_level = None

    for method in methods:
        if method.endswith('R'): continue # Skip Restricted methods
        
        method_type = method[1]
        
        if method_type == 'L':
            level = int(method[2:])
            if earliest_level is None or level < earliest_level:
                earliest_level = level
        elif method_type == 'M':
            unique_methods.add("TM/HM")
        elif method_type == 'T':
            unique_methods.add("Tutor")
        elif method_type == 'E':
            unique_methods.add("Egg")
        elif method_type == 'S':
            unique_methods.add("Event")
        elif method_type == 'V':
            unique_methods.add("VC")
        elif method_type == 'D':
            unique_methods.add("Dream World")

    # After checking all methods, add the earliest level-up move if it exists
    if earliest_level is not None:
        unique_methods.add(f"Lvl {earliest_level}")

    if not unique_methods:
        return "Special" # Fallback for unknown methods

    # Sort the methods for consistent ordering
    return ", ".join(sorted(list(unique_methods)))
    
def format_pokemon_movelist(species_data: dict, page: int = 0) -> tuple[str, types.InlineKeyboardMarkup | None]:
    """
    Generates a paginated, prioritized list of moves a Pokémon can learn.
    Priority: Level-up -> Egg -> TM/Tutor.
    """
    species_id = species_data['id']
    learnset_data = LEARNSETS.get(species_id, {}).get("learnset", {})
    
    if not learnset_data:
        return f"<b>{species_data['name']}</b> has no moves in its learnset.", None

    # --- NEW SORTING LOGIC ---
    level_moves = []
    egg_moves = []
    other_moves = []

    for move_id, methods in learnset_data.items():
        move_info = MOVE_BY_ID.get(move_id)
        if not move_info:
            continue

        # Determine the highest priority learn method for this move
        earliest_level = None
        is_egg = False
        is_other = False
        learn_methods_str = _parse_all_learn_methods(methods)

        for method in methods:
            if method.endswith('R'): continue # Skip restricted methods
            
            method_type = method[1]
            if method_type == 'L':
                level = int(method[2:])
                if earliest_level is None or level < earliest_level:
                    earliest_level = level
            elif method_type == 'E':
                is_egg = True
            elif method_type in ['M', 'T', 'V', 'S', 'D']:
                is_other = True
        
        move_tuple = (move_info['name'], move_info['type'], learn_methods_str)

        if earliest_level is not None:
            # Store with the level for sorting
            level_moves.append((earliest_level, move_tuple))
        elif is_egg:
            egg_moves.append(move_tuple)
        elif is_other:
            other_moves.append(move_tuple)

    # Sort each category individually
    level_moves.sort(key=lambda x: x[0]) # Sort by level
    egg_moves.sort(key=lambda x: x[0])   # Sort alphabetically by move name
    other_moves.sort(key=lambda x: x[0])  # Sort alphabetically by move name

    # Combine into a final list, preserving the desired order
    all_moves_sorted = []
    all_moves_sorted.extend([item[1] for item in level_moves]) # Extract the tuple
    all_moves_sorted.extend(egg_moves)
    all_moves_sorted.extend(other_moves)
    # --- END OF NEW SORTING LOGIC ---

    # Pagination
    items_per_page = 10 
    total_pages = math.ceil(len(all_moves_sorted) / items_per_page)
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    page_moves = all_moves_sorted[start_index:end_index]

    if not page_moves:
        return f"<b>{species_data['name']}</b> has no moves on this page.", None

    # Format the list with the two-line style
    formatted_list_parts = []
    for name, move_type, methods in page_moves:
        formatted_list_parts.append(
            f"<b>{html.escape(name)}</b> ({methods})\n"
            f"  <i>Type: {move_type}</i>"
        )
    
    formatted_list = "\n\n".join(formatted_list_parts)

    content = (
        f"<b>Moves for {species_data['name']}</b>\n"
        f"<i>Page {page + 1}/{total_pages}</i>\n\n"
        f"{formatted_list}"
    )

    # Keyboard generation remains the same
    markup = types.InlineKeyboardMarkup()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"dex_moves_{species_id}_{page - 1}"))
    if end_index < len(all_moves_sorted):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"dex_moves_{species_id}_{page + 1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    
    markup.row(types.InlineKeyboardButton("⬅️ Back to Entry", callback_data=f"dex_view_{species_id}"))

    return content, markup

def get_move_flags_menu(page: int = 0) -> tuple[str, types.InlineKeyboardMarkup]:
    """
    Generates a paginated, 3x3 grid menu with buttons for each move flag category.
    """
    items_per_page = 9  # 3x3 grid
    total_pages = math.ceil(len(ALL_MOVE_FLAGS) / items_per_page)
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    page_flags = ALL_MOVE_FLAGS[start_index:end_index]

    text = (
        f"<b>Pokédex: Move Categories</b>\n"
        f"<i>Page {page + 1}/{total_pages}</i>\n\n"
        f"Select a category (flag) to view all moves with that property."
    )
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = [
        types.InlineKeyboardButton(flag.title(), callback_data=f"dex_flags_list_{flag}_0")
        for flag in page_flags
    ]
    markup.add(*buttons)
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"dex_flags_main_{page - 1}"))
    if end_index < len(ALL_MOVE_FLAGS):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"dex_flags_main_{page + 1}"))
        
    if nav_buttons:
        markup.row(*nav_buttons)

    return text, markup

def format_moves_by_flag_list(flag: str, page: int = 0) -> tuple[str, types.InlineKeyboardMarkup]:
    """
    Generates a paginated list of all moves that have a specific flag.
    """
    # Filter all moves to find ones that have the specified flag
    filtered_moves = sorted(
        [move['name'] for move in MOVE_BY_ID.values() if move.get('flags', {}).get(flag)],
        key=str.lower
    )

    if not filtered_moves:
        content = f"No moves found with the '<b>{flag}</b>' flag."
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("⬅️ Back to Categories", callback_data="dex_flags_main"))
        return content, markup

    # Pagination
    items_per_page = 20
    total_pages = math.ceil(len(filtered_moves) / items_per_page)
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    page_moves = filtered_moves[start_index:end_index]

    # Format the list content
    formatted_list = "\n".join([f"• {html.escape(name)}" for name in page_moves])
    
    content = (
        f"<b>Moves with flag: <code>{flag}</code></b>\n"
        f"<i>Page {page + 1}/{total_pages}</i>\n\n"
        f"{formatted_list}"
    )

    # Keyboard for navigation
    markup = types.InlineKeyboardMarkup()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"dex_flags_list_{flag}_{page - 1}"))
    if end_index < len(filtered_moves):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"dex_flags_list_{flag}_{page + 1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    
    markup.row(types.InlineKeyboardButton("⬅️ Back to Categories", callback_data="dex_flags_main"))

    return content, markup
