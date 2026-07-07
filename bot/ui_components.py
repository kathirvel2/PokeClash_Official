# File: bot/ui_components.py
import os
from telebot import types
from bot.mechanics.db import db
from bot.mechanics.team import Pokemon
from bot.mechanics.moves_loader import SPECIES_BY_ID
from bot.mechanics.team import Pokemon
from bot.battle.battle_utils import get_actual_stats

import html
import json 


def format_pokemon_display_line(pokemon, display_mode: str) -> str:
    """
    Formats a single Pokemon's display string based on the user's display preference.
    Includes ✨ for shiny Pokemon.
    """
    shiny = "✨" if pokemon.is_shiny else ""
    name = html.escape(pokemon.name)
    
    if display_mode == "Nature":
        return f"{name}{shiny} - {pokemon.nature}"
    elif display_mode == "Ability":
        return f"{name}{shiny}[{pokemon.ability}]"
    elif display_mode == "Type":
        type_str = "/".join(pokemon.types)
        return f"{name}{shiny}[{type_str}]"
    elif display_mode == "Tier":
        species_info = SPECIES_BY_ID.get(pokemon.id, {})
        tier = species_info.get("tier", "?")
        return f"{name}{shiny}[{tier}]"
    elif display_mode == "BST":
        species_info = SPECIES_BY_ID.get(pokemon.id, {})
        base_stats = species_info.get("baseStats", {})
        bst = sum(base_stats.values())
        return f"{name}{shiny} (BST:{bst})"
    else:  # Default: Level
        return f"{name}{shiny} (Lv{pokemon.level})"


BOT_USERNAME = os.getenv('BOT_USERNAME', 'PokeClash_bot')
WEB_APP_LINK_NAME = os.getenv('WEB_APP_LINK_NAME', 'Pokeclashdex')
WEB_APP_HOST = os.getenv("WEB_APP_HOST_URL")

def get_stats_message_content(pokemon: Pokemon, chat_type: str, user_id: int) -> dict:
    """
    Generates the main, detailed info caption for the stats message.
    """
    species_info = SPECIES_BY_ID.get(pokemon.id, {})
    shiny_indicator = " ✨" if pokemon.is_shiny else ""

    caption = f"<b>{pokemon.name}</b>{shiny_indicator}\n\n"
    caption += f"<b>Lv. {pokemon.level}</b> | <b>Nature:</b> {pokemon.nature}\n"
    caption += f"<b>Ability:</b> {pokemon.ability}\n"
    caption += f"<b>Item:</b> {pokemon.item or 'None'}\n"
    caption += f"<b>Types:</b> [{', '.join(pokemon.types)}]\n\n"

    caption += "<b><u>Pokédex Data</u></b>\n"
    caption += f"<b>Species:</b> {species_info.get('baseSpecies', pokemon.name)}\n"
    caption += f"<b>Pokédex №:</b> {species_info.get('num', 'N/A')}\n"
    caption += f"<b>Height:</b> {species_info.get('heightm', 'N/A')} m\n"
    caption += f"<b>Weight:</b> {species_info.get('weightkg', 'N/A')} kg\n"
    caption += f"<b>Egg Groups:</b> {', '.join(species_info.get('eggGroups', ['N/A']))}\n"
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    # --- THIS IS THE FIX ---
    # We will only create the web_editor_button if all conditions are met
    web_editor_button = None
    if WEB_APP_HOST and chat_type == 'private':
        # This button is now *only* created in a private chat.
        editor_path = f"pokemon-editor.html?uuid={pokemon.pokemon_uuid}&user_id={user_id}&return_to=collection"
        final_url = f"{WEB_APP_HOST}/{editor_path}"
        web_editor_button = types.InlineKeyboardButton(
            "🌐 Web Editor",
            web_app=types.WebAppInfo(url=final_url)
        )
    # --- END OF FIX ---

    buttons_row1 = [
        types.InlineKeyboardButton("Stats Table", callback_data=f"p_statstable_{pokemon.pokemon_uuid}"),
        types.InlineKeyboardButton("Moves", callback_data=f"p_moves_{pokemon.pokemon_uuid}")
    ]
    buttons_row2 = [
        types.InlineKeyboardButton("Form", callback_data=f"p_formchange_{pokemon.pokemon_uuid}"),
        types.InlineKeyboardButton("Calculated Stats", callback_data=f"p_maincalcstats_{pokemon.pokemon_uuid}")
    ]
    buttons_row3 = [
         types.InlineKeyboardButton("✏️ Edit (In-Chat)", callback_data=f"p_edt_{pokemon.pokemon_uuid}"),
         types.InlineKeyboardButton("🔥 Release", callback_data=f"p_rel_{pokemon.pokemon_uuid}")
    ]
    
    if web_editor_button:
        # If the button was created (i.e., in a private chat), add it.
        # If not, this line is skipped, and it won't appear.
        markup.row(web_editor_button) 

    markup.add(*buttons_row1)
    markup.row(*buttons_row2)
    markup.add(*buttons_row3)

    return {"caption": caption, "reply_markup": markup}

def get_stats_table_content(pokemon: Pokemon) -> dict:
    """
    NEW: Generates the caption and keyboard for the detailed stats table view.
    """
    caption = f"<b>{pokemon.name}'s Stats</b>\n\n"

    # --- NEW: Calculate the totals first ---
    total_ivs = pokemon.ivs.hp + pokemon.ivs.atk + pokemon.ivs.def_ + pokemon.ivs.spa + pokemon.ivs.spd + pokemon.ivs.spe
    total_evs = pokemon.evs.hp + pokemon.evs.atk + pokemon.evs.def_ + pokemon.evs.spa + pokemon.evs.spd + pokemon.evs.spe

    stats_table = "<code>"
    stats_table += "Stat      | IV | EV\n"
    stats_table += "---------------------\n"
    stats_table += f"HP        | {pokemon.ivs.hp:2d} | {pokemon.evs.hp:3d}\n"
    stats_table += f"Attack    | {pokemon.ivs.atk:2d} | {pokemon.evs.atk:3d}\n"
    stats_table += f"Defense   | {pokemon.ivs.def_:2d} | {pokemon.evs.def_:3d}\n"
    stats_table += f"Sp. Atk   | {pokemon.ivs.spa:2d} | {pokemon.evs.spa:3d}\n"
    stats_table += f"Sp. Def   | {pokemon.ivs.spd:2d} | {pokemon.evs.spd:3d}\n"
    stats_table += f"Speed     | {pokemon.ivs.spe:2d} | {pokemon.evs.spe:3d}\n"
    stats_table += "---------------------\n"
    
    # --- THIS IS THE NEW LINE ---
    # It adds the totals, formatted to align with the columns above.
    stats_table += f"Total     | {total_ivs:3d}| {total_evs:3d}\n"

    stats_table += "</code>"
    caption += stats_table

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Back to Info", callback_data=f"p_stats_{pokemon.pokemon_uuid}"))

    return {"caption": caption, "reply_markup": markup}

def get_team_selection_content(user_id: int) -> dict:
    """
    Generates the main team selection menu, showing the active
    team's roster and arranging buttons in a 2x3 grid.
    """
    user_teams = db.get_user_teams(user_id)
    active_team = db.get_active_team(user_id)
    
    if len(user_teams) < 6:
        num_to_create = 6 - len(user_teams)
        start_num = len(user_teams) + 1
        for i in range(num_to_create):
            team_num = start_num + i
            new_team_name = f"Team {team_num}"
            db.create_team(user_id, new_team_name)
        user_teams = db.get_user_teams(user_id)
        if not active_team:
            active_team = db.get_active_team(user_id)
            
    active_team_id = active_team[0] if active_team else None
    active_team_name = active_team[2] if active_team else "N/A"
    active_team_uuids = active_team[3] if active_team and active_team[3] else []

    display_mode = db.get_display_setting(user_id)

    text = f"<b>Active Team:</b> {html.escape(active_team_name)}\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    if active_team_uuids:
        collection = db.get_collection(user_id)
        pokemon_map = {p.pokemon_uuid: p for p in collection}
        
        roster_lines = []
        for i, uuid in enumerate(active_team_uuids, start=1):
            pokemon = pokemon_map.get(uuid)
            if pokemon:
                display_str = format_pokemon_display_line(pokemon, display_mode)
                roster_lines.append(f" {i}. {display_str}")
            else:
                roster_lines.append(f" {i}. Unknown Pokémon")
        text += "\n".join(roster_lines) + "\n"
    else:
        text += " (Team empty)\n"
        
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "<i>Select a team below or edit the active one.</i>"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    team_buttons = []
    for team in user_teams[:6]:
        team_id, _, team_name, _, _ = team
        button_text = f"> {team_name} <" if team_id == active_team_id else team_name
        team_buttons.append(
            types.InlineKeyboardButton(button_text, callback_data=f"t_select_{team_id}")
        )
    markup.add(*team_buttons)

    if active_team_id:
        markup.row(
            types.InlineKeyboardButton("Edit Active Team", callback_data=f"t_edit_{active_team_id}")
        )

    return {"text": text, "reply_markup": markup}
    
def get_myteam_message_content(user_id: int, team_id: int) -> dict:
    """
    Generates a compact team editor view for a specific team.
    """
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM teams WHERE team_id = %s', (team_id,))
    target_team = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not target_team:
        return {"text": "Error: Team not found.", "reply_markup": None}

    _, _, team_name, uuids_json, _ = target_team
    # Filter out None — this gives automatic shift-up on removal
    team_pokemon_uuids = [u for u in (uuids_json if uuids_json else []) if u is not None]

    display_mode = db.get_display_setting(user_id)
    collection = db.get_collection(user_id)
    team_pokemon_map = {p.pokemon_uuid: p for p in collection}

    team_text = f"<b>Editing Team:</b> {html.escape(team_name)}\n"
    team_text += "━━━━━━━━━━━━━━━━━━━━\n"
    if not team_pokemon_uuids:
        team_text += " (Team empty)\n"
    else:
        for i, slot_uuid in enumerate(team_pokemon_uuids, start=1):
            pokemon = team_pokemon_map.get(slot_uuid)
            if pokemon:
                display_str = format_pokemon_display_line(pokemon, display_mode)
                team_text += f" {i}. {display_str}\n"
            else:
                team_text += f" {i}. Unknown\n"
    team_text += "━━━━━━━━━━━━━━━━━━━━"

    markup = types.InlineKeyboardMarkup(row_width=2)
    next_slot = len(team_pokemon_uuids)

    # Row 1: Add Poke | Remove
    if next_slot < 6:
        add_btn = types.InlineKeyboardButton("Add Poke", callback_data=f"t_add_{team_id}_{next_slot}_0")
    else:
        add_btn = types.InlineKeyboardButton("Full", callback_data="noop")
    remove_btn = types.InlineKeyboardButton("Remove", callback_data=f"t_remmenu_{team_id}")

    # Row 2: Clear | Swap
    clear_btn = types.InlineKeyboardButton("Clear", callback_data=f"t_clr_{team_id}")
    swap_btn = types.InlineKeyboardButton("Swap", callback_data=f"t_swapmenu_{team_id}")

    # Row 3: Back | Export
    back_btn = types.InlineKeyboardButton("Back", callback_data="t_mainmenu")
    export_btn = types.InlineKeyboardButton("Export", callback_data=f"t_export_{team_id}")

    markup.row(add_btn, remove_btn)
    markup.row(clear_btn, swap_btn)
    markup.row(back_btn, export_btn)
    
    return {"text": team_text, "reply_markup": markup}

def get_calculated_stats_content(pokemon: Pokemon) -> dict:
    """
    NEW: Generates the caption and keyboard for the calculated stats view.
    """
    # Get the final stats used in battle
    final_stats = get_actual_stats(pokemon)

    caption = f"📊 <b>Calculated Stats for {pokemon.name}</b>\n"
    caption += f"<em>(Level {pokemon.level} - {pokemon.nature} Nature)</em>\n\n"
    
    caption += f" • <b>HP:</b> <code>{final_stats['hp']}</code>\n"
    caption += f" • <b>Attack:</b> <code>{final_stats['atk']}</code>\n"
    caption += f" • <b>Defense:</b> <code>{final_stats['def']}</code>\n"
    caption += f" • <b>Sp. Atk:</b> <code>{final_stats['spa']}</code>\n"
    caption += f" • <b>Sp. Def:</b> <code>{final_stats['spd']}</code>\n"
    caption += f" • <b>Speed:</b> <code>{final_stats['spe']}</code>\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Back to Editor", callback_data=f"p_edt_{pokemon.pokemon_uuid}"))

    return {"caption": caption, "reply_markup": markup}

def get_calculated_stats_content_main(pokemon: Pokemon) -> dict:
    """
    NEW: Generates the calculated stats view with a "Back" button
    that returns to the main stats info screen.
    """
    final_stats = get_actual_stats(pokemon)

    caption = f"📊 <b>Calculated Stats for {pokemon.name}</b>\n"
    caption += f"<em>(Level {pokemon.level} - {pokemon.nature} Nature)</em>\n\n"
    
    caption += f" • <b>HP:</b> <code>{final_stats['hp']}</code>\n"
    caption += f" • <b>Attack:</b> <code>{final_stats['atk']}</code>\n"
    caption += f" • <b>Defense:</b> <code>{final_stats['def']}</code>\n"
    caption += f" • <b>Sp. Atk:</b> <code>{final_stats['spa']}</code>\n"
    caption += f" • <b>Sp. Def:</b> <code>{final_stats['spd']}</code>\n"
    caption += f" • <b>Speed:</b> <code>{final_stats['spe']}</code>\n"

    markup = types.InlineKeyboardMarkup()
    # This button goes back to the main stats/info view
    markup.add(types.InlineKeyboardButton("⬅️ Back to Info", callback_data=f"p_stats_{pokemon.pokemon_uuid}"))

    return {"caption": caption, "reply_markup": markup}

def get_settings_content(context: str, menu_context: str = 'main', **kwargs) -> dict:
    """
    Generates the UI for the hierarchical settings menu.
    - menu_context: 'main', 'main_modes', 'fun_modes', or 'rules'
    """
    challenge_id = kwargs['challenge_id']
    challenger_id = kwargs['challenger_id']
    settings = kwargs['settings']
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = "⚙️ <b>Battle Settings</b>\n\n"

    # --- Main Menu ---
    if menu_context == 'main':
        text += "Select a category to configure."
        markup.add(types.InlineKeyboardButton("Main Modes (Saved)", callback_data=f"b_ch_menu_{challenge_id}_main_modes_{challenger_id}"))
        markup.add(types.InlineKeyboardButton("Fun Modes (Temporary)", callback_data=f"b_ch_menu_{challenge_id}_fun_modes_{challenger_id}"))
        markup.add(types.InlineKeyboardButton("Other Rules (Saved)", callback_data=f"b_ch_menu_{challenge_id}_rules_{challenger_id}"))
        markup.row(types.InlineKeyboardButton("✅ Done", callback_data=f"b_ch_main_{challenge_id}_{challenger_id}"))

    # --- "Main Modes" Sub-Menu ---
    elif menu_context == 'main_modes':
        text += "Select a main legality mode. This choice is saved as your default."
        
        # This button now leads to the generation selection menu
        current_gen = settings.get('random_battle_generation')
        random_mode_text = f"✅ Random Battle (Gen {current_gen})" if current_gen else "Random Battle Mode"
        markup.add(types.InlineKeyboardButton(random_mode_text, callback_data=f"b_ch_menu_{challenge_id}_random_select_{challenger_id}"))
        
        # Other modes remain toggles
        is_non_legendary = settings.get('non_legendary_mode', False)
        non_leg_text = f"{'✅ ' if is_non_legendary else ''}Non-Legendary Mode"
        markup.add(types.InlineKeyboardButton(non_leg_text, callback_data=f"b_ch_toggle_{challenge_id}_nonlegendary_{challenger_id}"))

        is_legendary = settings.get('legendary_mode', False)
        leg_text = f"{'✅ ' if is_legendary else ''}Legendary Only Mode"
        markup.add(types.InlineKeyboardButton(leg_text, callback_data=f"b_ch_toggle_{challenge_id}_legendary_{challenger_id}"))

        markup.add(types.InlineKeyboardButton("🔄 Reset to Standard", callback_data=f"b_ch_reset_{challenge_id}_{challenger_id}"))
        markup.row(types.InlineKeyboardButton("⬅️ Back", callback_data=f"b_ch_menu_{challenge_id}_main_{challenger_id}"))

    # --- NEW SUB-MENU FOR RANDOM BATTLE GEN SELECTION ---
    elif menu_context == 'random_select':
        text += "Select a generation for Random Battle. This will disable other modes."
        current_gen = settings.get('random_battle_generation')
        
        # MODIFY THIS LINE
        supported_gens = [1, 2, 3, 4, 5, 6, 7, 8] # Expand this list as you add more generators
        
        gen_buttons = [
            types.InlineKeyboardButton(
                f"✅ Gen {gen}" if current_gen == gen else f"Gen {gen}",
                callback_data=f"b_ch_set_gen_{challenge_id}_{gen}_{challenger_id}"
            ) for gen in supported_gens
        ]
        for i in range(0, len(gen_buttons), 2):
          row = gen_buttons[i:i+2]
          markup.row(*row)
        
        markup.row(types.InlineKeyboardButton("❌ Disable Random Mode", callback_data=f"b_ch_set_gen_{challenge_id}_0_{challenger_id}"))
        markup.row(types.InlineKeyboardButton("⬅️ Back", callback_data=f"b_ch_menu_{challenge_id}_main_modes_{challenger_id}"))

    # --- "Fun Modes" Sub-Menu ---
    elif menu_context == 'fun_modes':
        text += "Select a temporary mode for this battle only."
        
        special_mode = settings.get('special_mode')
        fun_modes = [
            ("Restricted Legendary Only", "restricted_only"),
            ("Sub-Legendary Only", "sub_legendary_only"),
            ("Ultra Beast Only", "ultra_beast_only")
        ]
        for display_text, mode_id in fun_modes:
            current_text = f"{'✅ ' if special_mode == mode_id else ''}{display_text}"
            markup.add(types.InlineKeyboardButton(current_text, callback_data=f"b_ch_set_special_{challenge_id}_{mode_id}_{challenger_id}"))
        
        markup.row(types.InlineKeyboardButton("⬅️ Back", callback_data=f"b_ch_menu_{challenge_id}_main_{challenger_id}"))

    # --- "Other Rules" Sub-Menu ---
    elif menu_context == 'rules':
        text += "Enable or disable other battle rules. These choices are saved as your default."
        
        other_rules = [
            ('mega_enabled', 'Mega', 'mega'),
            ('gmax_enabled', 'Dynamax', 'gmax'),
            ('is_ranked', 'Ranked', 'ranked'),
            ('sleep_clause_enabled', 'Sleep Clause', 'sleep')
        ]
        for key, label, cbk in other_rules:
            is_enabled = settings.get(key, True)
            button_text = f"{label}: {'✅ Enabled' if is_enabled else '❌ Disabled'}"
            callback_data = f"b_ch_toggle_{challenge_id}_{cbk}_{challenger_id}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))
            
        markup.row(types.InlineKeyboardButton("⬅️ Back", callback_data=f"b_ch_menu_{challenge_id}_main_{challenger_id}"))

    return {"text": text, "markup": markup}
