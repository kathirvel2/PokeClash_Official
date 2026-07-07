# ./bot/battle/battle_ui.py
import os
import math
import io
import asyncio
import aiohttp
from PIL import Image, ImageFilter
import random
import os
from telebot import types
from bot.battle.battle_engine import Battle, ActivePokemon, active_battles
from bot.mechanics.moves_loader import MOVE_BY_ID
from bot.services.pokeapi import fetch_pokemon
from bot.battle.battle_utils import can_mega_evolve
from bot.battle.battle_utils import find_best_sprite_path
from bot.battle.dynamax.dynamax_ui import add_dynamax_button
from bot.battle.dynamax.dynamax_utils import can_dynamax
from bot.battle.battle_engine import Battle, ActivePokemon
from bot.battle.dynamax.dynamax_ui import get_dynamax_move_for_pokemon
from bot.battle.battle_logic import get_max_move_power
from bot.battle.ability_effects import is_weather_suppressed
from bot.battle.battle_utils import can_mega_evolve, find_best_sprite_path, can_item_form_change, can_use_z_move
from bot.battle.z_move_data import get_z_move_details,Z_CRYSTAL_TYPE_MAP
from bot.mechanics.item_data import ITEM_ID_BY_NAME

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')

def generate_health_bar(current_hp: int, max_hp: int) -> str:
    if max_hp <= 0: return "▒" * 10
    percentage = (current_hp / max_hp) * 10
    filled_blocks = math.floor(percentage)
    return "█" * filled_blocks + "▒" * (10 - filled_blocks)

def generate_battle_caption(battle: Battle, action_log: str = "") -> str:

    p1_active_poke = battle.player1.get_active_pokemon()
    dynamax_turns_p1 = p1_active_poke.volatiles.get('dynamax', {}).get('turns')
    dynamax_indicator_p1 = f"🔥 D-Max ({dynamax_turns_p1}/3)" if dynamax_turns_p1 else ""
    p1_types = "/".join(p1_active_poke.pokemon.types)
    p1_tags = []
    if p1_active_poke.status:
        p1_tags.append(p1_active_poke.status.upper())
    if 'confusion' in p1_active_poke.volatiles:
        p1_tags.append('?CON')
    if 'substitute' in p1_active_poke.volatiles:
        p1_tags.append('SUB')
    if 'perishsong' in p1_active_poke.volatiles:
        p1_tags.append(f"PERISH {p1_active_poke.volatiles['perishsong']}")
    p1_status_tag = f" [{' '.join(p1_tags)}]" if p1_tags else ""

    p1_status = (
        f"<b>{battle.player1.user_name}</b>'s {p1_active_poke.pokemon.name} {dynamax_indicator_p1}\n"
        f"<i>[{p1_types}]</i>\n"
        f"Lv. {p1_active_poke.pokemon.level}  •  HP {p1_active_poke.current_hp}/{p1_active_poke.actual_stats['hp']}\n"
        f"<code>{generate_health_bar(p1_active_poke.current_hp, p1_active_poke.actual_stats['hp'])}</code>{p1_status_tag}"
    )

    # Player 2's Status Block
    p2_active_poke = battle.player2.get_active_pokemon()
    dynamax_turns_p2 = p2_active_poke.volatiles.get('dynamax', {}).get('turns')
    dynamax_indicator_p2 = f"🔥 D-Max ({dynamax_turns_p2}/3)" if dynamax_turns_p2 else ""
    p2_types = "/".join(p2_active_poke.pokemon.types)
    p2_tags = []
    if p2_active_poke.status:
        p2_tags.append(p2_active_poke.status.upper())
    if 'confusion' in p2_active_poke.volatiles:
        p2_tags.append('?CON')
    if 'substitute' in p2_active_poke.volatiles:
        p2_tags.append('SUB')
    if 'perishsong' in p2_active_poke.volatiles:
        p2_tags.append(f"PERISH {p2_active_poke.volatiles['perishsong']}")
    p2_status_tag = f" [{' '.join(p2_tags)}]" if p2_tags else ""

    p2_status = (
        f"<b>{battle.player2.user_name}</b>'s {p2_active_poke.pokemon.name} {dynamax_indicator_p2}\n"
        f"<i>[{p2_types}]</i>\n"
        f"Lv. {p2_active_poke.pokemon.level}  •  HP {p2_active_poke.current_hp}/{p2_active_poke.actual_stats['hp']}\n"
        f"<code>{generate_health_bar(p2_active_poke.current_hp, p2_active_poke.actual_stats['hp'])}</code>{p2_status_tag}"
    )

    move_details_str = ""
    active_player = battle.get_player(battle.active_player_id) if battle.active_player_id else None
    if battle.state == 'active' and battle.turn_phase == 'awaiting_move' and active_player:
        active_pokemon = active_player.get_active_pokemon()

        # --- FIX FOR Z-MOVE PRIMING ---
        if battle.primed_action == 'zmove':
            # Display a simple, clear message and skip the complex move formatting loop
            move_details_str = "<b>Z-MOVE SELECTION ACTIVE</b>: Choose the move above to unleash Z-Power!"
        # --- END FIX ---
            
        else: 
            # Original complex move loop (now only runs if NOT Z-Move primed)
            move_lines = ["<b>Moves:</b>"]
            is_dynamaxed = 'dynamax' in active_pokemon.volatiles

            for base_move_id in active_pokemon.pokemon.moves:
                # Initialize variables at the start of the loop
                actual_move_id = base_move_id
                move_data = MOVE_BY_ID.get(actual_move_id, {}).copy()
                z_move_info = None # This will store details for damaging Z-Moves
                is_zmove_primed = battle.primed_action == 'zmove' # Define the variable here
    
                # Logic to determine the final move to display
                if is_zmove_primed:
                    # Check for compatibility before transforming the move in the UI
                    item_id = ITEM_ID_BY_NAME.get(active_pokemon.pokemon.item, "")
                    required_z_crystal_type = Z_CRYSTAL_TYPE_MAP.get(item_id)
                    
                    # Check if the base move is compatible
                    is_compatible_z_move = (required_z_crystal_type and move_data.get('type') == required_z_crystal_type)
    
                    if is_compatible_z_move:
                        z_move_info = get_z_move_details(base_move_id)
                        if z_move_info: # This is a damaging Z-Move
                            move_data['name'] = z_move_info['name']
                            move_data['basePower'] = z_move_info['power']
                    # If not compatible, move_data remains as the normal move
                
                elif is_dynamaxed:
                    actual_move_id = get_dynamax_move_for_pokemon(base_move_id, active_pokemon)
                    move_data = MOVE_BY_ID.get(actual_move_id, {}).copy()
    
                if not move_data:
                    continue
            
                # --- NEW LOGIC BLOCK STARTS HERE ---
                # Handle dynamic move types/names for UI display
                if actual_move_id == 'judgment' and active_pokemon.pokemon.id.startswith('arceus'):
                    if active_pokemon.pokemon.item and 'plate' in active_pokemon.pokemon.item.lower():
                        move_data['type'] = active_pokemon.pokemon.types[0]
            
                elif actual_move_id == 'multiattack' and active_pokemon.pokemon.id.startswith('silvally'):
                    if active_pokemon.pokemon.item and 'memory' in active_pokemon.pokemon.item.lower():
                        move_data['type'] = active_pokemon.pokemon.types[0]
            
                elif actual_move_id == 'technoblast' and active_pokemon.pokemon.id.startswith('genesect'):
                    if active_pokemon.pokemon.item == 'Douse Drive': move_data['type'] = 'Water'
                    elif active_pokemon.pokemon.item == 'Shock Drive': move_data['type'] = 'Electric'
                    elif active_pokemon.pokemon.item == 'Burn Drive': move_data['type'] = 'Fire'
                    elif active_pokemon.pokemon.item == 'Chill Drive': move_data['type'] = 'Ice'
                
                # Also handle Zacian/Zamazenta's move name change for the display
                elif active_pokemon.pokemon.id == 'zaciancrowned' and actual_move_id == 'ironhead':
                    move_data = MOVE_BY_ID.get('behemothbash', {}).copy()
            
                elif active_pokemon.pokemon.id == 'zamazentacrowned' and actual_move_id == 'ironhead':
                    move_data = MOVE_BY_ID.get('behemothblade', {}).copy()
                        # --- NEW LOGIC BLOCK ENDS HERE ---
    
                base_move_data = MOVE_BY_ID.get(base_move_id)
                if move_data and base_move_data:
                    
                    # --- THIS IS THE FIX ---
                    # Inherit category from the BASE move for transformations
                    if is_dynamaxed or (is_zmove_primed and base_move_data.get('category') != 'Status'):
                        cat = base_move_data.get('category', '?')
                    else:
                        cat = move_data.get('category', '?')
                    
                    # Also fixed the power logic, get_max_move_power handles status moves.
                    if move_data.get('isMax'):
                        pwr = get_max_move_power(base_move_id)
                    else:
                        pwr = move_data.get('basePower', '–')
                    # --- END OF FIX ---
                    
                    acc = move_data.get('accuracy')
                    acc_str = f"{acc}" if isinstance(acc, int) else "–"
                    
                    # Simplified PP display logic
                    if is_zmove_primed and z_move_info: # Only hide PP for damaging Z-Moves
                        pp_display = "–/–"
                    else:
                        curr_pp = active_pokemon.move_pp.get(base_move_id, 0)
                        max_pp = base_move_data.get('pp', 0)
                        pp_display = f"{curr_pp}/{max_pp}"
                    
                    move_lines.append(
                        f"• {move_data['name']} <i>[{move_data['type']}/{cat}]</i>\n"
                        f" <b>Pwr:</b> <code>{pwr}</code> <b>Acc:</b> <code>{acc_str}</code> <b>PP:</b> <code>{pp_display}</code>"
                    )
    
            move_details_str = "\n".join(move_lines)

    status_indicator = ""
    if battle.state == 'finished':
        if hasattr(battle, 'final_message') and battle.final_message:
            status_indicator = battle.final_message
        elif battle.winner:
            status_indicator = f"<b>GAME OVER! {battle.winner.user_name} wins!</b> 🏆"

            if battle.winner_reward is not None and battle.loser_reward is not None:
               loser = battle.player1 if battle.winner.user_id != battle.player1.user_id else battle.player2
               status_indicator += (
                   f"\n\n💰 <b>{battle.winner.user_name}</b> <i>earned {battle.winner_reward} CC!</i>\n"
                   f"💰 <b>{loser.user_name}</b> <i>earned {battle.loser_reward} CC!</i>"
               )
            
        else:
            status_indicator = "<b>The match has ended in a draw!</b>"
            
    elif battle.state == 'active' and active_player:
        if battle.turn_phase == 'awaiting_move':
            # --- THIS IS THE NEW LOGIC ---
            # Get the faster Pokémon from the pre-calculated turn order
            faster_pokemon = battle.turn_order[0][1] 
            outspeed_log = f"<i>{faster_pokemon.pokemon.name} outspeeds and will move first!</i>\n"
            status_indicator = f"{outspeed_log}<i>Waiting for <b>{active_player.user_name}</b> to move...</i>"
            # --- END OF NEW LOGIC ---
            
        elif battle.turn_phase == 'awaiting_switch':
            status_indicator = f"<i>Waiting for <b>{active_player.user_name}</b> to switch Pokémon...</i>"
            
        elif battle.turn_phase == 'awaiting_forced_switch':
           status_indicator = f"<b>{active_player.user_name} must choose a Pokémon to switch in!</b>"

    caption = (
        f"{p1_status}\nvs\n{p2_status}\n\n"
        f"<b><i>{action_log}</i></b>\n\n"
        f"{status_indicator}\n\n"
        f"{move_details_str}"
    )

    return caption.strip()

def generate_switch_keyboard(battle: Battle, player: 'BattlePlayer') -> types.InlineKeyboardMarkup:
    """
    MODIFIED: Generates a compact, numbered keyboard for switching Pokémon
    and includes a "View Team" button.
    """
    markup = types.InlineKeyboardMarkup(row_width=3) # Use 3 columns for the 1-6 buttons
    buttons = []

    # Create a mapping of team index to a button if the pokemon is switchable
    for i, active_poke in enumerate(player.team):
        is_fainted = active_poke.current_hp <= 0
        is_active = (i == player.active_pokemon_index)

        # Only create a button if the Pokemon is alive and not already in battle
        if not is_fainted and not is_active:
            # The button text is just the party slot number (1-6)
            button_text = str(i + 1)
            callback_data = f"b_switchsel_{i}"
            buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))

    # Add the numbered buttons to the keyboard. The row_width=3 will handle the layout.
    if buttons:
        markup.add(*buttons)
    else:
        # This case is rare, but good to have a failsafe
        markup.row(types.InlineKeyboardButton("No Pokémon available!", callback_data="b_noop"))

    # --- NEW "VIEW TEAM" BUTTON ---
    # Add the "View Team" button in its own row.
    # We pass the player's ID in the callback to know which team to show.
    markup.row(types.InlineKeyboardButton("View Team", callback_data=f"b_view_team_{player.user_id}"))

    # Add the "Back" button if it's a voluntary switch (not a forced faint switch)
    if battle.turn_phase == 'awaiting_voluntary_switch':
        markup.row(types.InlineKeyboardButton("⬅️ Back", callback_data="b_back_moves"))

    return markup

def generate_battle_keyboard(battle: Battle) -> types.InlineKeyboardMarkup:
    """Generates the inline keyboard, showing moves and Mega Evolve option."""
    markup = types.InlineKeyboardMarkup(row_width=2)

    if battle.state != 'active' or battle.turn_phase != 'awaiting_move':
        return None

    active_player = battle.get_player(battle.active_player_id)
    if not active_player:
        return None

    active_pokemon = active_player.get_active_pokemon()

    # Case: Pokémon is recharging
    if 'mustrecharge' in active_pokemon.volatiles:
        markup.add(types.InlineKeyboardButton("『 Recharging 』", callback_data="b_recharge"))
        return markup

    # Case: Pokémon is charging a move (e.g., Fly, Dig)
    if active_pokemon.charging_move:
        move_name = active_pokemon.charging_move['name']
        markup.add(types.InlineKeyboardButton(f"『 {move_name} 』", callback_data="b_m_0"))
        return markup

    # Case: Pokémon is locked into a multi-turn move (e.g., Outrage)
    locked_move_state = active_pokemon.volatiles.get('lockedmove')
    if locked_move_state:
        move_id = locked_move_state['move_id']
        move_data = MOVE_BY_ID.get(move_id)
        if move_data:
            try:
                move_index = active_pokemon.pokemon.moves.index(move_id)
                callback_data = f"b_m_{move_index}"
                markup.add(types.InlineKeyboardButton(f"『 {move_data['name']} 』", callback_data=callback_data))
                return markup
            except ValueError:
                pass

    elif 'choice_locked_move' in active_pokemon.volatiles:
        locked_move_id = active_pokemon.volatiles['choice_locked_move']
        move_data = MOVE_BY_ID.get(locked_move_id)
        
        # Find the index of the locked move to create the correct callback
        try:
            move_index = active_pokemon.pokemon.moves.index(locked_move_id)
            callback_data = f"b_m_{move_index}"
            
            # Display a single, centered button for the locked move
            markup.add(types.InlineKeyboardButton(f"『 Locked: {move_data['name']} 』", callback_data=callback_data))
            
            # The player can still switch out to reset the lock
            utility_buttons = [
                types.InlineKeyboardButton("Switch", callback_data="b_s"),
                types.InlineKeyboardButton("Run", callback_data="b_run"),
                types.InlineKeyboardButton("Forfeit", callback_data="b_forfeit")
            ]
            markup.row(*utility_buttons)
            return markup # Return this special keyboard and stop
        except ValueError:
            pass # Failsafe if move isn't found

    if 'dynamax' in active_pokemon.volatiles:
        move_buttons = []
        for i, move_id in enumerate(active_pokemon.pokemon.moves):
            max_move_id = get_dynamax_move_for_pokemon(move_id, active_pokemon)
            max_move_data = MOVE_BY_ID.get(max_move_id)
            if max_move_data:
                button_text = f"🔥 {max_move_data['name']}"
                # The callback is a standard move, the turn handler knows to use the Max Move
                callback_data = f"b_m_{i}"
                move_buttons.append(types.InlineKeyboardButton(button_text, callback_data=callback_data))

        while len(move_buttons) < 4:
            move_buttons.append(types.InlineKeyboardButton(" ", callback_data="b_noop"))

        markup.add(*move_buttons)
        # A Dynamaxed Pokémon cannot switch, so we only show Run/Forfeit
        utility_buttons = [
            types.InlineKeyboardButton("Run", callback_data="b_run"),
            types.InlineKeyboardButton("Forfeit", callback_data="b_forfeit")
        ]
        markup.row(*utility_buttons)
        return markup

    # --- Main Logic for a Normal Turn (unchanged) ---
    move_buttons = []
    for i, move_id in enumerate(active_pokemon.pokemon.moves):
        # Use .copy() to be safe
        move_data = MOVE_BY_ID.get(move_id, {}).copy()
        if not move_data:
            continue
        
        # --- ADD THIS TRANSFORMATION LOGIC ---
        if move_data['id'] == 'judgment' and active_pokemon.pokemon.id.startswith('arceus'):
            if active_pokemon.pokemon.item and 'plate' in active_pokemon.pokemon.item.lower():
                move_data['type'] = active_pokemon.pokemon.types[0]
    
        elif move_data['id'] == 'technoblast' and active_pokemon.pokemon.id.startswith('genesect'):
            if active_pokemon.pokemon.item == 'Douse Drive': move_data['type'] = 'Water'
            elif active_pokemon.pokemon.item == 'Shock Drive': move_data['type'] = 'Electric'
            elif active_pokemon.pokemon.item == 'Burn Drive': move_data['type'] = 'Fire'
            elif active_pokemon.pokemon.item == 'Chill Drive': move_data['type'] = 'Ice'
    
        elif active_pokemon.pokemon.id == 'zaciancrowned' and move_id == 'ironhead':
            move_data = MOVE_BY_ID.get('behemothbash', {}).copy()
        
        elif active_pokemon.pokemon.id == 'zamazentacrowned' and move_id == 'ironhead':
            move_data = MOVE_BY_ID.get('behemothblade', {}).copy()
        # --- END OF NEW LOGIC ---
    
        callback_data = f"b_m_{i}"
        move_buttons.append(types.InlineKeyboardButton(move_data['name'], callback_data=callback_data))
    while len(move_buttons) < 4:
        move_buttons.append(types.InlineKeyboardButton(" ", callback_data="b_noop"))
    markup.add(*move_buttons)
    
    super_move_buttons = []
    if can_mega_evolve(active_player, battle):
        super_move_buttons.append(
            types.InlineKeyboardButton("Mega Evolve ✨", callback_data="b_mega_prime")
        )
        
    if can_item_form_change(active_pokemon):
        super_move_buttons.append(
            types.InlineKeyboardButton("Form Change ⚜️", callback_data="b_formchange_prime")
        )

    if can_dynamax(active_player, battle):
        super_move_buttons.append(
            types.InlineKeyboardButton("Dynamax 🔥", callback_data="b_dynamax_prime")
        )

    if can_use_z_move(active_player, battle):
        super_move_buttons.append(
            types.InlineKeyboardButton("Z-Move ⚡️", callback_data="b_zmove_prime")
        )

    if super_move_buttons:
        markup.row(*super_move_buttons)

    utility_buttons = [
        types.InlineKeyboardButton("Switch", callback_data="b_s"),
        types.InlineKeyboardButton("Run", callback_data="b_run"),
        types.InlineKeyboardButton("Forfeit", callback_data="b_forfeit")
    ]
    markup.row(*utility_buttons)

    return markup
    
async def generate_battle_image(p1_arg, p2_arg, terrain: str, folder: str = 'terrains') -> io.BytesIO:
    """
    MODIFIED: Generates a battle image with conditional scaling for G-Max sprites.
    """
    HORIZONTAL_GAP = 10

    terrain_path = os.path.join(ASSETS_DIR, folder, terrain)
    try:
        canvas = Image.open(terrain_path).convert("RGBA")
    except FileNotFoundError:
        canvas = Image.new('RGBA', (800, 480), (255, 255, 255, 255))

    def process_sprite(pokemon_arg, is_back_sprite: bool):
        """
        Processes a sprite, returning the image object and a flag indicating
        if it's a regular sprite that has been enlarged for Dynamax.
        """
        is_active_pokemon = hasattr(pokemon_arg, 'pokemon')

        if is_active_pokemon:
            active_pokemon_obj = pokemon_arg
            base_pokemon = active_pokemon_obj.pokemon
            is_dynamaxed = 'dynamax' in active_pokemon_obj.volatiles
        else:
            base_pokemon = pokemon_arg
            is_dynamaxed = False

        sprite_folder = 'sprites-gen5-back-shiny' if base_pokemon.is_shiny else 'sprites-gen5-back'
        if not is_back_sprite:
            sprite_folder = 'sprites-gen5-shiny' if base_pokemon.is_shiny else 'sprites-gen5'

        sprite_path = find_best_sprite_path(base_pokemon, sprite_folder)
        if not sprite_path or not os.path.exists(sprite_path):
            print(f"WARNING: Missing battle sprite for {base_pokemon.name} in folder {sprite_folder}")
            return None, False

        with Image.open(sprite_path) as sprite:
            sprite = sprite.convert("RGBA")
            
            # --- START OF NEW SCALING LOGIC ---
            is_gmax_sprite = "-gmax" in sprite_path
            
            # Default scale for a normal or special G-Max sprite
            scale_factor = 3.5 
            
            # Only apply the larger scale if it's a regular Pokémon Dynamaxing
            if is_dynamaxed and not is_gmax_sprite:
                scale_factor = 5.0
            # --- END OF NEW SCALING LOGIC ---

            new_size = (int(sprite.width * scale_factor), int(sprite.height * scale_factor))
            sprite = sprite.resize(new_size, Image.Resampling.NEAREST)
            
            bbox = sprite.getbbox()
            if bbox:
                sprite = sprite.crop(bbox)
            
            # Return the sprite and a flag indicating if it was a standard-sized
            # sprite that was artificially enlarged.
            is_enlarged = is_dynamaxed and not is_gmax_sprite
            return sprite, is_enlarged

    sprite1, is_p1_enlarged = process_sprite(p1_arg, is_back_sprite=True)
    sprite2, is_p2_enlarged = process_sprite(p2_arg, is_back_sprite=False)

    if sprite1:
        # --- FIX: Use the 'is_enlarged' flag to determine y-position ---
        y_pos1 = 200 if is_p1_enlarged else 250
        canvas.paste(sprite1, (HORIZONTAL_GAP, y_pos1), sprite1)

    if sprite2:
        x_position = canvas.size[0] - sprite2.width - HORIZONTAL_GAP
        # --- FIX: Use the 'is_enlarged' flag to determine y-position ---
        y_pos2 = 80 if is_p2_enlarged else 130
        canvas.paste(sprite2, (x_position, y_pos2), sprite2)

    final_image_buffer = io.BytesIO()
    canvas.save(final_image_buffer, format='PNG')
    final_image_buffer.seek(0)
    return final_image_buffer
    
def generate_battle_stats_text(pokemon: 'ActivePokemon') -> str:
    """Formats a detailed text for the /battle_stats command."""
    from bot.battle.battle_logic import get_modified_stat

    header = f"<b>Current Stats for {pokemon.pokemon.name}</b>\n"
    
    ability_swapped_tag = " (Swapped)" if pokemon.ability_is_swapped else ""
    header += f" • <b>Ability:</b> {pokemon.pokemon.ability}{ability_swapped_tag}\n"
    header += f" • <b>Held Item:</b> {pokemon.pokemon.item or 'None'}\n\n"

    base_stats_header = "<b><u>Base Stats (Lvl 100 Neutral)</u></b>\n"
    base_stat_lines = [
        f" • HP: <code>{pokemon.actual_stats['hp']}</code>",
        f" • Attack: <code>{pokemon.actual_stats['atk']}</code>",
        f" • Defense: <code>{pokemon.actual_stats['def']}</code>",
        f" • Sp. Atk: <code>{pokemon.actual_stats['spa']}</code>",
        f" • Sp. Def: <code>{pokemon.actual_stats['spd']}</code>",
        f" • Speed: <code>{pokemon.actual_stats['spe']}</code>"
    ]

    in_battle_header = "\n\n<b><u>In-Battle Stats & Modifiers</u></b>\n"
    in_battle_lines = []
    
    stat_map = {
        'atk': 'Attack', 'def': 'Defense', 'spa': 'Sp. Atk',    
        'spd': 'Sp. Def', 'spe': 'Speed'
    }

    for key, name in stat_map.items():
        final_value = get_modified_stat(pokemon, key)
        
        display_line = f" • <b>{name}:</b> <code>{final_value}</code>"
        
        details = []
        
        # --- THIS IS THE CORRECTED LOGIC BLOCK ---
        ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
        
        # Correctly find the battle this pokemon belongs to
        battle = None
        for chat_battles in active_battles.values():
            for b in chat_battles:
                if pokemon in b.player1.team or pokemon in b.player2.team:
                    battle = b
                    break
            if battle:
                break

        # Add item details first
        if pokemon.stat_multipliers.get(key, 1.0) != 1.0:
            details.append(f"x{pokemon.stat_multipliers.get(key, 1.0)} item")

        # Now, check for specific ability effects on the correct stat
        if pokemon.status:
            if ability_id == 'marvelscale' and key == 'def':
                details.append("x1.5 Marvel Scale")
            elif ability_id == 'quickfeet' and key == 'spe':
                details.append("x1.5 Quick Feet")
        
        if battle and battle.active_terrain == 'electricterrain' and ability_id == 'surgesurfer' and key == 'spe':
            details.append("x2 Surge Surfer")
        # --- END OF CORRECTION ---

        if pokemon.boosts.get(key, 0) != 0:
            boost_sign = '+' if pokemon.boosts.get(key, 0) > 0 else ''
            details.append(f"[{boost_sign}{pokemon.boosts.get(key, 0)}]")
        
        if key == 'atk' and pokemon.status == 'brn':
            details.append("Burned")

        if details:
            display_line += f" <i>({', '.join(details)})</i>"
            
        in_battle_lines.append(display_line)

    return header + base_stats_header + "\n".join(base_stat_lines) + in_battle_header + "\n".join(in_battle_lines)