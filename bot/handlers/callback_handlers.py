from telebot.async_telebot import AsyncTeleBot
from telebot import types
import json
import string
import html
import random
import os

from bot.mechanics.moves_loader import ABILITIES_BY_ID, MOVE_BY_ID, SPECIES_BY_ID
from bot.handlers.command_handlers import _get_start_menu_content
from bot.mechanics.item_data import ITEM_NAME_BY_ID
from bot.mechanics.db import db
from bot.mechanics.team import Pokemon, resolve_full_learnset
from bot.mechanics.moves_loader import LEARNSETS, MOVE_BY_ID, SPECIES_BY_ID
from bot.mechanics.team import create_pokemon
from bot.services.pokeapi import get_pokemon_image_and_stats
from bot.handlers.command_handlers import show_pokemon_stats
from bot.handlers.decorators import owner_only
from bot.battle.battle_utils import get_actual_stats, find_best_sprite_path
from bot.ui_components import get_myteam_message_content, get_stats_message_content, get_stats_table_content, get_team_selection_content, get_calculated_stats_content, get_calculated_stats_content_main, format_pokemon_display_line
from bot.mechanics.status_manager import status_manager
from bot.mechanics.item_data import ITEM_NAME_BY_ID, ITEM_ID_BY_NAME, ITEM_CATEGORIES
from bot.image_generation.trainer_card import create_trainer_card_image
from bot.handlers.decorators import owner_only, user_not_banned
from bot.ui_components import get_settings_content
from bot.mechanics.team import create_pokemon
import uuid
from bot.dex.dex_handlers import handle_dex_callbacks
from .handler_utils import CallbackRateLimiter
from bot.mechanics.item_data import ALL_ITEMS
from bot.mechanics.form_validation import get_collection_form_block_reason
from bot.team_analysis.presenter import build_team_from_showdown_request, format_team_detail_text
import uuid

user_states = {}

ALL_NATURES = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile",
    "Relaxed", "Impish", "Lax", "Timid", "Hasty", "Serious", "Jolly",
    "Naive", "Modest", "Mild", "Quiet", "Bashful", "Rash", "Calm",
    "Gentle", "Sassy", "Careful", "Quirky"
]
ALL_TYPES = [
    "Normal", "Fire", "Water", "Grass", "Electric", "Ice", "Fighting", "Poison",
    "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark",
    "Steel", "Fairy"
]

callback_limiter = CallbackRateLimiter()

CATEGORY_NAMES = list(ITEM_CATEGORIES.keys())

# --- Main Registration Function ---
def register_callback_handlers(bot: AsyncTeleBot):
    """
    Registers all callback and state-based text handlers.
    """
    bot.callback_query_handler(func=lambda call: call.data.startswith('buy_slot_'))
    @owner_only(bot) # Ensures only the user who was prompted can click
    @user_not_banned(bot)
    async def handle_buy_slot(call: types.CallbackQuery):
        user_id = call.from_user.id
        SLOT_COST = 500 # Make sure this matches the command_handlers file

        current_coins = db.get_clash_coin_count(user_id)
        
        if current_coins < SLOT_COST:
            await bot.answer_callback_query(call.id, f"You don't have enough coins! You need {SLOT_COST}.", show_alert=True)
            return

        # Deduct coins and add the slot
        db.add_clash_coins(user_id, -SLOT_COST)
        current_max = db.get_max_slots(user_id)
        new_max = current_max + 1
        db.set_max_slots(user_id, new_max)
        
        await bot.edit_message_text(
            f"✅ <b>Purchase Successful!</b>\n\n"
            f"You spent 500 Clash Coins. Your new Pokémon slot limit is <b>{new_max}</b>.\n\n"
            f"You can now use the <code>/add</code> command again.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
            parse_mode="HTML"
        )
        await bot.answer_callback_query(call.id, "Purchase successful!")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('lb_'))
    @user_not_banned(bot)
    async def handle_leaderboard_callback(call: types.CallbackQuery):
        parts = call.data.split('_')
        # Expected formats: lb_page_overall_1 OR lb_mode_ranked_0
        mode = parts[2]
        page = int(parts[3])
        
        # Import the helper we just made
        from bot.handlers.command_handlers import _build_leaderboard_ui 
        content = _build_leaderboard_ui(mode=mode, page=page)
        
        try:
            await bot.edit_message_text(
                content['text'], 
                call.message.chat.id, 
                call.message.id, 
                reply_markup=content['markup'], 
                parse_mode="HTML"
            )
        except Exception as e:
            # Ignore "message is not modified" if they click the same button twice
            pass 
            
        await bot.answer_callback_query(call.id)
    
    # --- FIX: New text handler for state-based input ---
    @bot.message_handler(content_types=['text'], func=lambda message: message.from_user.id in user_states)
    @user_not_banned(bot)
    async def handle_stateful_text_input(message):
        user_id = message.from_user.id
        state = user_states[user_id]
        action = state.get("action")

        if action == "awaiting_level":
            await process_new_level(bot, message, state)
        elif action == "awaiting_item":
            await process_new_item(bot, message, state)
        elif action == "awaiting_stat":
            await process_new_stat_value(bot, message, state)
        
        # Clean up the state after processing
        if user_id in user_states:
            del user_states[user_id]

    @bot.callback_query_handler(func=lambda call: call.data.startswith('teamview_'))
    @owner_only(bot)
    @user_not_banned(bot)
    async def handle_teamview_callback(call: types.CallbackQuery):
        user_id = call.from_user.id
        parts = call.data.split('_')
        if len(parts) < 4 or parts[1] != "detail":
            await bot.answer_callback_query(call.id, "Unknown team view action.", show_alert=True)
            return

        from bot.showdown_battle.service import get_showdown_service

        showdown_service = get_showdown_service()
        showdown_battle = showdown_service.active_battle_for_user(user_id) if showdown_service else None
        detail_text = None

        if showdown_battle:
            player = showdown_battle.player_for_user(user_id)
            request = player.current_request if player else None
            if player and request:
                detail_text = format_team_detail_text(
                    f"{player.name}'s Team",
                    build_team_from_showdown_request(request),
                )

        if detail_text is None:
            from bot.battle.battle_engine import active_battles

            for raw_battles_in_chat in active_battles.values():
                battles_in_chat = raw_battles_in_chat if isinstance(raw_battles_in_chat, list) else [raw_battles_in_chat]
                legacy_battle = next((battle for battle in battles_in_chat if battle.get_player(user_id)), None)
                if not legacy_battle:
                    continue
                legacy_player = legacy_battle.get_player(user_id)
                detail_text = format_team_detail_text(
                    f"{legacy_player.user_name}'s Team",
                    [active_poke.pokemon for active_poke in legacy_player.team],
                )
                break

        if detail_text is None:
            active_team_db = db.get_active_team(user_id)
            if active_team_db and active_team_db[3]:
                collection = db.get_collection(user_id)
                pokemon_map = {pokemon.pokemon_uuid: pokemon for pokemon in collection}
                team = [pokemon_map[uuid] for uuid in active_team_db[3] if uuid in pokemon_map]
                if team:
                    detail_text = format_team_detail_text(active_team_db[2], team)

        if detail_text is None:
            await bot.answer_callback_query(call.id, "No team data is available right now.", show_alert=True)
            return

        if len(parts) >= 5:
            target_mode = parts[3]
        else:
            target_mode = parts[2]
        target_chat_id = user_id if target_mode == "dm" else call.message.chat.id
        reply_target = None if target_mode == "dm" else call.message.message_id

        try:
            await bot.send_message(target_chat_id, detail_text, reply_to_message_id=reply_target)
        except Exception:
            await bot.answer_callback_query(call.id, "I couldn't send the team detail right now.", show_alert=True)
            return

        if target_mode == "dm" and call.message.chat.id != user_id:
            await bot.answer_callback_query(call.id, "Team detail sent to your DM.")
            return
        await bot.answer_callback_query(call.id, "Team detail sent.")
            
    @bot.callback_query_handler(
        func=lambda call: (
            not call.data.startswith('battle_')
            and not call.data.startswith('b_')
            and not call.data.startswith('challenge_page_')
            and not call.data.startswith('sdb:')
            and not call.data.startswith('teamview_')
        )
    )
    @owner_only(bot)
    @user_not_banned(bot)
    async def handle_callback(call):
        if await callback_limiter.is_limited(call, bot):
            return

        if call.data.startswith("start_menu_"):
            action = call.data.split('_')[2]
            
            if action == "main":
                content = _get_start_menu_content(call.from_user.first_name)
            else:
                content = _get_feature_explanation_content(action)
            
            await bot.edit_message_text(
                content["text"],
                call.message.chat.id,
                call.message.id,
                reply_markup=content["reply_markup"],
                parse_mode="HTML"
            )
            await bot.answer_callback_query(call.id)
            return

        from bot.handlers.command_handlers import register_command_handlers, show_pokemon_stats, show_duplicate_selection_menu
        # The 'bot' object is still available from the parent function's scope.
        # The decorator now correctly handles the ownership check.
        user_id = call.from_user.id
        parts = call.data.split('_')
        prefix = parts[0]
        action = parts[1] if len(parts) > 1 else None

        if prefix == "buy" and action == "slot":
            user_id_from_call = call.from_user.id # This is the user who clicked
            SLOT_COST = 500 

            current_coins = db.get_clash_coin_count(user_id_from_call)
            
            if current_coins < SLOT_COST:
                await bot.answer_callback_query(call.id, f"You don't have enough coins! You need {SLOT_COST}.", show_alert=True)
                return

            # Deduct coins and add the slot
            db.add_clash_coins(user_id_from_call, -SLOT_COST)
            current_max = db.get_max_slots(user_id_from_call)
            new_max = current_max + 1
            db.set_max_slots(user_id_from_call, new_max)
            
            await bot.edit_message_text(
                f"✅ <b>Purchase Successful!</b>\n\n"
                f"You spent 500 Clash Coins. Your new Pokémon slot limit is <b>{new_max}</b>.\n\n"
                f"You can now use the <code>/add</code> command again.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None,
                parse_mode="HTML"
            )
            await bot.answer_callback_query(call.id, "Purchase successful!")
            return # Exit the handler

        if prefix == "dex":
            # This call is for the dex. Pass it to the specialized handler.
            await handle_dex_callbacks(bot, call)
            return

        if prefix == "impl":
            # This whole block is now automatically protected by the @owner_only decorator
            action = parts[1]
            category = parts[2] if len(parts) > 2 else None

            if action == "menu":
                text = f"Select the first letter for: <b>{category.capitalize()}</b>"
                markup = types.InlineKeyboardMarkup(row_width=7)
                buttons = [types.InlineKeyboardButton(letter, callback_data=f"impl_filter_{category}_{letter}_0") for letter in string.ascii_uppercase]
                markup.add(*buttons)
                markup.row(types.InlineKeyboardButton("⬅️ Back to Categories", callback_data="impl_main"))
                await bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")

            elif action == "filter":
                letter = parts[3]
                page = int(parts[4])
                
                source_map = {}
                if category == "moves": source_map = {k: v['name'] for k, v in MOVE_BY_ID.items()}
                elif category == "abilities": source_map = {k: v['name'] for k, v in ABILITIES_BY_ID.items()}
                elif category == "items": source_map = ITEM_NAME_BY_ID

                filtered_items = sorted([item_id for item_id in source_map if source_map[item_id].upper().startswith(letter)])
                
                items_per_page = 10
                start, end = page * items_per_page, (page + 1) * items_per_page
                page_items = filtered_items[start:end]

                text = f"<b>{category.capitalize()}</b> starting with '<b>{letter}</b>' (Page {page+1})"
                markup = types.InlineKeyboardMarkup(row_width=2)
                buttons = [
                    types.InlineKeyboardButton(
                        f"{'✅' if status_manager.get_status(category, item_id) else '❌'} {source_map[item_id]}",
                        callback_data=f"impl_select_{category}_{item_id}_{letter}_{page}"
                    ) for item_id in page_items
                ]
                markup.add(*buttons)

                nav_buttons = []
                if page > 0: nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"impl_filter_{category}_{letter}_{page-1}"))
                if end < len(filtered_items): nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"impl_filter_{category}_{letter}_{page+1}"))
                if nav_buttons: markup.row(*nav_buttons)

                markup.row(types.InlineKeyboardButton("⬅️ Back to A-Z", callback_data=f"impl_menu_{category}"))
                await bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")

            elif action == "select":
                item_id, letter, page = parts[3], parts[4], int(parts[5])

                name_map = {"moves": MOVE_BY_ID, "abilities": ABILITIES_BY_ID, "items": ITEM_NAME_BY_ID}
                item_name = name_map[category].get(item_id)
                if isinstance(item_name, dict): item_name = item_name['name']

                text = f"Editing status for: <b>{item_name}</b>"
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✅ Mark Implemented", callback_data=f"impl_set_{category}_{item_id}_1_{letter}_{page}"),
                    types.InlineKeyboardButton("❌ Mark Unimplemented", callback_data=f"impl_set_{category}_{item_id}_0_{letter}_{page}")
                )
                markup.row(types.InlineKeyboardButton("⬅️ Back to List", callback_data=f"impl_filter_{category}_{letter}_{page}"))
                await bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")

            elif action == "set":
                item_id, status, letter, page = parts[3], bool(int(parts[4])), parts[5], int(parts[6])
                
                status_manager.set_status(category, item_id, status)
                
                # To refresh the view, we can simulate a click on the "filter" callback
                call.data = f"impl_filter_{category}_{letter}_{page}"
                await handle_callback(call)
                return # Important: exit to prevent double-answering the callback

            elif action == "main":
                text = "<b>Implementation Checklist</b>\n\nSelect a category to view its status."
                markup = types.InlineKeyboardMarkup(row_width=3)
                markup.add(
                    types.InlineKeyboardButton("Moves", callback_data="impl_menu_moves"),
                    types.InlineKeyboardButton("Abilities", callback_data="impl_menu_abilities"),
                    types.InlineKeyboardButton("Items", callback_data="impl_menu_items")
                )
                await bot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=markup, parse_mode="HTML")
            
            await bot.answer_callback_query(call.id)
            return

        if prefix == "add" and parts[1] == "confirm":
            species_id = parts[2]
            species_data = SPECIES_BY_ID.get(species_id)
            if not species_data:
                await bot.edit_message_text("Sorry, there was an error finding that Pokémon data.", call.message.chat.id, call.message.id)
                await bot.answer_callback_query(call.id)
                return
            block_reason = get_collection_form_block_reason(species_data)
            if block_reason:
                await bot.edit_message_text(
                    f"❌ <b>{species_data['name']}</b> is a {block_reason} and cannot be added permanently.",
                    call.message.chat.id, call.message.id, parse_mode="HTML"
                )
                await bot.answer_callback_query(call.id)
                return

            # --- <<< START: EXACT COPY FROM /add COMMAND >>> ---
            SHINY_RATE = 4096
            is_shiny = (random.randint(1, SHINY_RATE) == 1)

            # Create the Pokémon using the validated species_id
            new_pokemon = create_pokemon(species_id=species_data['id'], is_shiny=is_shiny)

            # Ensure UUID is unique (same loop as in /add)
            while db.pokemon_uuid_exists(new_pokemon.pokemon_uuid):
                print(f"CONFIRM UUID COLLISION: {new_pokemon.pokemon_uuid}. Regenerating.")
                new_pokemon.pokemon_uuid = uuid.uuid4().hex[:8]

            # Add to collection (using user_id from the callback context)
            db.add_pokemon_to_collection(user_id, new_pokemon)

            # Format the success message (same as in /add)
            text = ""
            if is_shiny:
                text = f"✨ Unbelievable! A SHINY <b>{new_pokemon.name}</b> has been added to your collection!"
            else:
                text = f"✅ <b>{new_pokemon.name}</b> has been added to your collection!"

            # Edit the original "Did you mean?" message with the result
            await bot.edit_message_text(text, call.message.chat.id, call.message.id, parse_mode="HTML")

        if prefix == "stats" and parts[1] == "confirm":
            query_name = parts[2]
            original_command = call.message.reply_to_message
            collection = db.get_collection(user_id)
            found_by_name = [p for p in collection if p.name.lower() == query_name.lower()]
            
            await bot.delete_message(call.message.chat.id, call.message.id) # Delete the suggestion message

            if len(found_by_name) == 1:
                await show_pokemon_stats(bot, original_command, found_by_name[0])
            else:
                await show_duplicate_selection_menu(bot, original_command, query_name, found_by_name)
            return

        if prefix == "suggestion" and parts[1] == "cancel":
            await bot.edit_message_text("Okay, cancelled.", call.message.chat.id, call.message.id)
            return
        
        if call.data.startswith("set_display_"):
            setting = call.data.replace("set_display_", "")
            db.set_display_setting(user_id, setting)
            await bot.answer_callback_query(call.id, f"Display set to {setting}!")
            options = ["Level", "Nature", "Ability", "Type", "Tier", "BST"]
            text = "<b>Display Settings</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            for i, opt in enumerate(options, 1):
                text += f" {i}. {opt}\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
            text += f"<i>Selected: {setting}</i>"
            
            markup = types.InlineKeyboardMarkup(row_width=3)
            buttons = [types.InlineKeyboardButton(str(i), callback_data=f"set_display_{opt}") for i, opt in enumerate(options, 1)]
            markup.add(*buttons)
            await bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="HTML")
            return

        if prefix == "collection" and parts[1] == "page":
            page = int(parts[2])
            collection = db.get_collection(user_id)
            display_mode = db.get_display_setting(user_id)
            
            items_per_page = 20
            sorted_collection = sorted(collection, key=lambda p: p.name)
            total_pages = -(-len(sorted_collection) // items_per_page)

            start = page * items_per_page
            end = start + items_per_page
            page_pokemon = sorted_collection[start:end]

            message_lines = ["<b>Your Collection</b>\n━━━━━━━━━━━━━━━━━━━━"]
            for index, p in enumerate(page_pokemon, start=start + 1):
                display_str = format_pokemon_display_line(p, display_mode)
                message_lines.append(f" {index}. {display_str}")
        
            collection_text = "\n".join(message_lines)
            collection_text += f"\n━━━━━━━━━━━━━━━━━━━━\n<i>Display: {display_mode} | Total: {len(collection)} | Page: {page + 1}/{total_pages}</i>"

            markup = types.InlineKeyboardMarkup()
            nav_buttons = []
            if page > 0:
                nav_buttons.append(types.InlineKeyboardButton("Prev", callback_data=f"collection_page_{page-1}"))
            if end < len(sorted_collection):
                nav_buttons.append(types.InlineKeyboardButton("Next", callback_data=f"collection_page_{page+1}"))
            
            if nav_buttons:
                markup.row(*nav_buttons)

            await bot.edit_message_text(
                text=collection_text, 
                chat_id=call.message.chat.id, 
                message_id=call.message.id, 
                reply_markup=markup, 
                parse_mode="HTML"
            )
            return


        # --- Pokémon Actions Router ---
        if prefix == "p":
            pokemon_uuid = parts[2]
            if action == "stats":
                pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
                if pokemon:
                    content = get_stats_message_content(pokemon, call.message.chat.type, call.from_user.id)
                    await bot.edit_message_caption(
                        caption=content["caption"], 
                        chat_id=call.message.chat.id, 
                        message_id=call.message.id, 
                        reply_markup=content["reply_markup"], 
                        parse_mode="HTML"
                    )
            elif action == "edt":
                # Check if the command was used in a private chat
                if call.message.chat.type != 'private':
                    await bot.answer_callback_query(
                        call.id, 
                        "Pokémon editing is only available in a private chat with the bot.", 
                        show_alert=True
                    )
                    return
                # If it's private, proceed as normal
                await show_pokemon_editor(bot, call, user_id, pokemon_uuid)
            elif action == "edtmenu":
                context = parts[3]
                page = int(parts[4]) if len(parts) > 4 else 0
                await handle_pokemon_edit_menu(bot, call, user_id, pokemon_uuid, context, page)
            elif action == "setnature":
                new_nature = parts[3]
                await set_pokemon_nature(bot, call, user_id, pokemon_uuid, new_nature)
            elif action == "setability":
                ability_key = parts[3]
                # Look up the full ability name using the key
                pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
                if pokemon:
                    species_info = SPECIES_BY_ID.get(pokemon.id, {})
                    abilities = species_info.get("abilities", {})
                    new_ability_name = abilities.get(ability_key)
                    if new_ability_name:
                        await set_pokemon_ability(bot, call, user_id, pokemon_uuid, new_ability_name)
            elif action == "setmove":
                move_id = parts[3]
                letter_filter = parts[4]
                page = int(parts[5])
                await set_pokemon_move(bot, call, user_id, pokemon_uuid, move_id, letter_filter, page)
            elif action == "rel": await confirm_release_pokemon(bot, call, user_id, pokemon_uuid)
            elif action == "crel": await release_pokemon(bot, call, user_id, pokemon_uuid)
            # The "info" action is now part of the main stats view and is no longer needed.
            elif action == "moves": await show_current_moves_details(bot, call, user_id, pokemon_uuid)
            elif action == "statstable": await show_stats_table(bot, call, user_id, pokemon_uuid)
            elif action == "eviveditor": await show_ev_iv_editor(bot, call, user_id, pokemon_uuid)
            elif action == "maincalcstats": await show_calculated_stats_main(bot, call, user_id, pokemon_uuid)
            elif action == "calcstats": await show_calculated_stats(bot, call, user_id, pokemon_uuid)
            elif action == "evivedit":
                stat_type = parts[3]
                stat_name = parts[4]
                await prompt_for_stat_value(bot, call, user_id, pokemon_uuid, stat_type, stat_name)
            elif action == "tera": await show_tera_type_selector(bot, call, user_id, pokemon_uuid)
            elif action == "settera":
                new_tera_type = parts[3]
                await set_pokemon_tera_type(bot, call, user_id, pokemon_uuid, new_tera_type)
            elif action == "formchange": await show_form_change_menu(bot, call, user_id, pokemon_uuid)
            elif action == "itembrowse":
                # The third part is now a numeric category_id
                category_id_str = parts[3]
                # --- ADD THIS LINE ---
                page = int(parts[4]) if len(parts) > 4 else 0
                await show_item_browser(bot, call, user_id, pokemon_uuid, category_id_str, page)
            elif action == "setitem":
                item_id = parts[3]
                category_index = parts[4]
                page = int(parts[5])
                
                # Call the new function with all the required arguments
                await set_pokemon_item(bot, call, user_id, pokemon_uuid, item_id, category_index, page)
                
            elif action == "select":
                pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
                if pokemon:
                    # --- THIS IS THE FIX ---
                    # The selection menu we clicked was a reply to the user's original command.
                    # We access that original command via 'reply_to_message'.
                    original_user_command = call.message.reply_to_message
                    
                    # Now, we create the new stats photo as a reply to that original command.
                    await show_pokemon_stats(bot, original_user_command, pokemon)
                    
                    # Finally, delete the old selection menu.
                    await bot.delete_message(call.message.chat.id, call.message.id)
                    
            elif action == "dupe":
                # The query key now includes the original message ID to keep it unique
                query_key_parts = parts[2:-1]
                # Rejoin the parts of the name, in case the name itself had an underscore
                query_name_full = "_".join(query_key_parts)
                page = int(parts[-1])
                
                # Extract the actual pokemon name from the unique key
                pokemon_name = query_name_full.split('_')[0]
                
                collection = db.get_collection(user_id)
                found_by_name = [p for p in collection if p.name.lower() == pokemon_name.lower()]
                
                # --- THIS IS THE FIX ---
                # Rebuild the menu content and edit the message in place.
                
                items_per_page = 6
                start = page * items_per_page
                end = start + items_per_page
                total_pages = -(-len(found_by_name) // items_per_page)
                
                selection_text = f"You have multiple Pokémon named <b>{pokemon_name.capitalize()}</b>. Please choose one:\n"
                selection_text += f"<i>(Page {page + 1}/{total_pages})</i>\n\n"
                
                page_pokemon = found_by_name[start:end]
                for i, p in enumerate(page_pokemon):
                    list_number = start + i + 1
                    selection_text += f"<b>{list_number}.</b> Lvl {p.level} | {p.nature} | {p.ability} | Item: {p.item or 'None'}\n"

                markup = types.InlineKeyboardMarkup(row_width=3)
                buttons = []
                for i, p in enumerate(page_pokemon):
                    button_number = str(start + i + 1)
                    buttons.append(types.InlineKeyboardButton(
                        button_number, 
                        callback_data=f"p_select_{p.pokemon_uuid}"
                    ))
                markup.add(*buttons)
                
                nav_buttons = []
                # Use the same unique key for subsequent page turns
                unique_query_key = query_name_full 
                if page > 0:
                    nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"p_dupe_{unique_query_key}_{page-1}"))
                if end < len(found_by_name):
                    nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"p_dupe_{unique_query_key}_{page+1}"))
                if nav_buttons:
                    markup.row(*nav_buttons)

                await bot.edit_message_text(
                    text=selection_text,
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                    reply_markup=markup,
                    parse_mode="HTML"
                )

        # --- Pokemon Set Move Handler ---
        elif prefix == "psm":
            pokemon_uuid = parts[1]
            move_index = int(parts[2])
            letter_filter = parts[3]
            page = int(parts[4])
   
            pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
            if pokemon:
                # --- THIS IS THE FIX ---
                # Replicate the exact same logic from show_move_selector to get the correct move list
                all_possible_moves = sorted(resolve_full_learnset(pokemon.id).keys())
                
                possible_moves = sorted([
                    move_id for move_id in all_possible_moves
                    if MOVE_BY_ID.get(move_id, {}).get("name", "").upper().startswith(letter_filter)
                ], key=lambda mid: MOVE_BY_ID.get(mid, {}).get("name", ""))
                # --- END OF FIX ---
                
                if move_index < len(possible_moves):
                    move_id = possible_moves[move_index]
                    await set_pokemon_move(bot, call, user_id, pokemon_uuid, move_id, letter_filter, page)
                else:
                    await bot.answer_callback_query(call.id, "Error: Move index out of date.", show_alert=True)
            return # Added return to ensure callback query is not answered twice

        elif prefix == "tc":
            action = parts[1]
            
            if action == "main":
                new_content = get_tc_main_menu_content()
                await bot.edit_message_caption(caption=new_content['text'], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=new_content['markup'], parse_mode="HTML")
            
            elif action == "types":
                new_content = get_tc_type_selection_content()
                await bot.edit_message_caption(caption=new_content['text'], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=new_content['markup'], parse_mode="HTML")
        
            elif action == "templates":
                card_type, page = parts[2], int(parts[3])
                new_content = get_tc_template_selection_content(user_id, card_type, page)
                await bot.edit_message_caption(caption=new_content['text'], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=new_content['markup'], parse_mode="HTML")
        
            elif action == "settemplate":
                card_type, filename, page = parts[2], parts[3], int(parts[4])
                db.set_user_card_pref(user_id, 'card_template', f"{card_type}/{filename}")
                await bot.answer_callback_query(call.id, "Preview updated!")
                await refresh_trainer_card_preview(bot, call, menu_context='templates', card_type=card_type, page=page)
        
            elif action == "spriteaz":
                new_content = get_tc_sprite_az_content()
                await bot.edit_message_caption(caption=new_content['text'], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=new_content['markup'], parse_mode="HTML")
            
            elif action == "spritelist":
                letter, page = parts[2], int(parts[3])
                new_content = get_tc_sprite_list_content(user_id, letter, page)
                await bot.edit_message_caption(caption=new_content['text'], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=new_content['markup'], parse_mode="HTML")
        
            elif action == "setsprite":
                filename, letter, page = parts[2], parts[3], int(parts[4])
                db.set_user_card_pref(user_id, 'trainer_sprite', filename)
                await bot.answer_callback_query(call.id, "Preview updated!")
                await refresh_trainer_card_preview(bot, call, menu_context='sprites', letter=letter, page=page)
        
            # --- NEW FONT COLOR LOGIC ---
            elif action == "font":
                new_content = get_tc_font_menu_content(user_id)
                await bot.edit_message_caption(caption=new_content['text'], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=new_content['markup'], parse_mode="HTML")
        
            elif action == "setfont":
                color = parts[2]
                db.set_user_card_pref(user_id, 'card_font_color', color)
                await bot.answer_callback_query(call.id, "Preview updated!")
                await refresh_trainer_card_preview(bot, call, menu_context='font')
            # --- END OF NEW LOGIC ---
        
            elif action == "done":
                await bot.delete_message(call.message.chat.id, call.message.id)
                await bot.answer_callback_query(call.id, "Card updated! Use /trainercard to see it.")
        
            
        elif prefix == "t":
            action = parts[1]

            if action == "mainmenu":
                content = get_team_selection_content(user_id)
                await bot.edit_message_text(content["text"], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=content["reply_markup"], parse_mode="HTML")
            
            elif action == "select":
                team_id = int(parts[2])
                db.set_active_team(user_id, team_id)
                content = get_team_selection_content(user_id)
                await bot.edit_message_text(content["text"], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=content["reply_markup"], parse_mode="HTML")
            
            elif action == "edit":
                team_id = int(parts[2])
                content = get_myteam_message_content(user_id, team_id)
                await bot.edit_message_text(content["text"], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=content["reply_markup"], parse_mode="HTML")

            elif action == "add":
                team_id, slot_index, page = int(parts[2]), int(parts[3]), int(parts[4])
                await show_add_to_team_menu(bot, call, user_id, team_id, slot_index, page)

            elif action == "addsel":
                team_id, pokemon_uuid, slot_index = int(parts[2]), parts[3], int(parts[4])
                await add_pokemon_to_team(bot, call, user_id, team_id, pokemon_uuid, slot_index)

            elif action == "clr":
                team_id = int(parts[2])
                await confirm_clear_team(bot, call, team_id)

            elif action == "cclr":
                team_id = int(parts[2])
                await clear_team(bot, call, user_id, team_id)
            
            elif action == "remmenu":
                team_id = int(parts[2])
                await show_remove_from_team_menu(bot, call, user_id, team_id)
            
            elif action == "remsel":
                team_id, slot_index = int(parts[2]), int(parts[3])
                await remove_pokemon_from_team(bot, call, user_id, team_id, slot_index)

            elif action == "swapmenu":
                team_id = int(parts[2])
                await show_swap_menu_step1(bot, call, user_id, team_id)
            
            elif action == "swapsel1":
                team_id, slot_index1 = int(parts[2]), int(parts[3])
                await show_swap_menu_step2(bot, call, user_id, team_id, slot_index1)

            elif action == "swapexec":
                team_id, slot_index1, slot_index2 = int(parts[2]), int(parts[3]), int(parts[4])
                await execute_swap(bot, call, user_id, team_id, slot_index1, slot_index2)

            elif action == "export":
                team_id = int(parts[2])
                await export_team(bot, call, user_id, team_id)
            
            else:
                await bot.answer_callback_query(call.id, f"Unknown team action: '{action}'")
            return # Exit after handling the team action

        # --- Back Button Router ---
        elif prefix == "back":
            context_id = parts[2]
            if action == "peditor": await show_pokemon_editor(bot, call, user_id, context_id)
            elif action == "pmovefilter": await show_move_alphabet_filter(bot, call, user_id, context_id)
        
        try:
            await bot.answer_callback_query(call.id)
        except Exception:
            pass

async def show_pokemon_editor(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    
    # --- MODIFIED: Caption is now HTML ---
    caption = f"✏️ <b>Editing {pokemon.name}</b>\n\nSelect an attribute to modify."
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # --- MODIFIED: Button layout and actions ---
    buttons_row1 = [
        types.InlineKeyboardButton("Level", callback_data=f"p_edtmenu_{pokemon_uuid}_level"),
        types.InlineKeyboardButton("Nature", callback_data=f"p_edtmenu_{pokemon_uuid}_nature"),
        types.InlineKeyboardButton("Ability", callback_data=f"p_edtmenu_{pokemon_uuid}_ability"),
        # "Set Item (Name)" is replaced with "EVs / IVs"
        types.InlineKeyboardButton("EVs / IVs", callback_data=f"p_eviveditor_{pokemon_uuid}"),
        types.InlineKeyboardButton("Browse Items", callback_data=f"p_itembrowse_{pokemon_uuid}_main"),
        types.InlineKeyboardButton("Moves", callback_data=f"p_edtmenu_{pokemon_uuid}_moves"),
    ]
    
    # New button in the middle row for Calculated Stats
    buttons_row2 = [
        types.InlineKeyboardButton("📊 Calculated Stats 📊", callback_data=f"p_calcstats_{pokemon_uuid}")
    ]

    buttons_row3 = [
         types.InlineKeyboardButton("⬅️ Back to Stats", callback_data=f"p_stats_{pokemon_uuid}")
    ]

    markup.add(*buttons_row1)
    markup.row(*buttons_row2)
    markup.row(*buttons_row3)
    
    await bot.edit_message_caption(
        caption=caption, 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=markup, 
        parse_mode="HTML" # <-- Use HTML
    )

async def show_calculated_stats(bot, call, user_id, pokemon_uuid):
    """Displays the final, calculated stats of a Pokémon."""
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon:
        await bot.answer_callback_query(call.id, "Pokémon not found.", show_alert=True)
        return

    content = get_calculated_stats_content(pokemon)
    await bot.edit_message_caption(
        caption=content["caption"],
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        reply_markup=content["reply_markup"],
        parse_mode="HTML"
    )
async def show_calculated_stats_main(bot, call, user_id, pokemon_uuid):
    """Displays the final, calculated stats from the main menu."""
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon:
        await bot.answer_callback_query(call.id, "Pokémon not found.", show_alert=True)
        return

    content = get_calculated_stats_content_main(pokemon)
    await bot.edit_message_caption(
        caption=content["caption"],
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        reply_markup=content["reply_markup"],
        parse_mode="HTML"
    )

async def handle_pokemon_edit_menu(bot, call, user_id, pokemon_uuid, context, page):
    try:
        if context == "nature": await show_nature_selector(bot, call, user_id, pokemon_uuid, page)
        elif context == "ability": await show_ability_selector(bot, call, user_id, pokemon_uuid)
        elif context == "moves": await show_move_alphabet_filter(bot, call, user_id, pokemon_uuid)
        elif len(context) == 1 and context.isalpha(): await show_move_selector(bot, call, user_id, pokemon_uuid, context.upper(), page)
        elif context == "level": await prompt_for_level(bot, call, user_id, pokemon_uuid)
        elif context == "item": await prompt_for_item(bot, call, user_id, pokemon_uuid)

    except Exception as e:  # <<< --- ADD THIS BLOCK
        print(f"--- DIAGNOSTIC: An error occurred in handle_pokemon_edit_menu ---")
        print(f"Callback data that caused the error: {call.data}")
        print(f"Error details: {e}")
        import traceback
        traceback.print_exc()
        await bot.answer_callback_query(call.id, "An error occurred. Check the console.", show_alert=True)

# --- Text Input Handlers (State-based) ---

async def prompt_for_level(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    prompt_message = await bot.send_message(call.message.chat.id, f"Enter a new level for **{pokemon.name}** (1-100).", parse_mode="Markdown")
    user_states[user_id] = {
        "action": "awaiting_level",
        "pokemon_uuid": pokemon_uuid,
        "prompt_message_id": prompt_message.id
    }

async def process_new_level(bot, message, state):
    user_id = message.from_user.id
    pokemon_uuid = state['pokemon_uuid']
    try:
        new_level = int(message.text)
        if not 1 <= new_level <= 100: raise ValueError()
    except (ValueError, TypeError):
        await bot.reply_to(message, "Invalid input. Please enter a number between 1 and 100.")
        return
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    pokemon.level = new_level
    db.update_pokemon_in_collection(user_id, pokemon)
    await bot.delete_message(message.chat.id, message.id)
    await bot.delete_message(message.chat.id, state['prompt_message_id'])
    # --- THIS IS THE FIX ---
    # The message now correctly uses HTML for formatting.
    await bot.send_message(
        message.chat.id,
        f"✅ <b>{pokemon.name}</b>'s level has been set to {new_level}!",
        parse_mode="HTML"
    )

async def prompt_for_item(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    prompt_message = await bot.send_message(call.message.chat.id, f"Enter the name of an item for **{pokemon.name}**.", parse_mode="Markdown")
    user_states[user_id] = {
        "action": "awaiting_item",
        "pokemon_uuid": pokemon_uuid,
        "prompt_message_id": prompt_message.id
    }

async def process_new_item(bot, message, state):
    user_id = message.from_user.id
    pokemon_uuid = state['pokemon_uuid']
    item_name_input = message.text.strip()
    
    # --- NEW: Validation Logic ---
    # Find a case-insensitive match for the item in our master list
    found_item = next((item for item in ALL_ITEMS if item.lower() == item_name_input.lower()), None)
    
    if not found_item:
        await bot.reply_to(message, f"❌ '{item_name_input}' is not a valid item. Please try again.")
        # We don't delete the state here, so the user can try again immediately.
        return
    # --- End of Validation ---

    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    
    # Use the correctly capitalized item name
    pokemon.item = found_item
    db.update_pokemon_in_collection(user_id, pokemon)
    
    # Clean up state and messages
    await bot.delete_message(message.chat.id, message.id)
    await bot.delete_message(message.chat.id, state['prompt_message_id'])
    await bot.send_message(message.chat.id, f"✅ **{pokemon.name}** is now holding **{found_item}**!")
    
    # Remove the user from the input state
    if user_id in user_states:
        del user_states[user_id]

async def prompt_for_stat_value(bot, call, user_id, pokemon_uuid, stat_type, stat_name):
    limit = 31 if stat_type == "iv" else 252
    prompt_message = await bot.send_message(call.message.chat.id, f"Enter the new value for <b>{stat_name.upper()} {stat_type.upper()}</b> (0-{limit}).", parse_mode="HTML") # Also updated this to HTML
    user_states[user_id] = {
        "action": "awaiting_stat",
        "pokemon_uuid": pokemon_uuid,
        "stat_type": stat_type,
        "stat_name": stat_name,
        "prompt_message_id": prompt_message.id,
        "editor_message_id": call.message.id
    }
    
async def process_new_stat_value(bot, message, state):
    user_id = message.from_user.id
    pokemon_uuid = state['pokemon_uuid']
    stat_type = state['stat_type']
    stat_name = state['stat_name']
    limit = 31 if stat_type == "iv" else 252
    
    try:
        value = int(message.text)
        if not 0 <= value <= limit: raise ValueError()
    except (ValueError, TypeError):
        await bot.reply_to(message, f"Invalid input. Please enter a number between 0 and {limit}.")
        # Don't delete state, let the user try again
        return

    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return

    stat_obj = pokemon.evs if stat_type == "ev" else pokemon.ivs
    attr_name = 'def_' if stat_name == 'def' else stat_name
    
    # Check total EV limit before setting the value
    if stat_type == "ev":
        current_total = sum(pokemon.evs.__dict__.values())
        old_value = getattr(stat_obj, attr_name)
        if current_total - old_value + value > 510:
            await bot.reply_to(message, f"⚠️ <b>Error:</b> Setting this value would exceed the total EV limit of 510.", parse_mode="HTML")
            return
            
    setattr(stat_obj, attr_name, value)
    db.update_pokemon_in_collection(user_id, pokemon)

    # --- THIS IS THE NEW LOGIC ---
    # 1. Clean up the prompt and the user's reply
    await bot.delete_message(message.chat.id, message.id)
    await bot.delete_message(message.chat.id, state['prompt_message_id'])
    
    # 2. Re-fetch the updated Pokémon to be safe
    updated_pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not updated_pokemon: return

    # 3. Rebuild the EV/IV editor menu caption and keyboard
    caption = f"✏️ <b>Editing {updated_pokemon.name}'s EVs & IVs</b>\n\nSelect a stat to modify."
    markup = types.InlineKeyboardMarkup(row_width=2)
    stats = ["hp", "atk", "def", "spa", "spd", "spe"]
    buttons = []
    for stat in stats:
        attr = 'def_' if stat == 'def' else stat
        buttons.append(types.InlineKeyboardButton(f"{stat.upper()} EV: {getattr(updated_pokemon.evs, attr)}", callback_data=f"p_evivedit_{pokemon_uuid}_ev_{stat}"))
        buttons.append(types.InlineKeyboardButton(f"IV: {getattr(updated_pokemon.ivs, attr)}", callback_data=f"p_evivedit_{pokemon_uuid}_iv_{stat}"))
    
    markup.add(*buttons)
    # The back button should go to the main editor, not the stats page
    markup.row(types.InlineKeyboardButton("⬅️ Back to Editor", callback_data=f"p_edt_{pokemon_uuid}"))

    # 4. Edit the original message to refresh the menu
    editor_message_id = state.get("editor_message_id")
    if editor_message_id:
        try:
            await bot.edit_message_caption(
                caption=caption,
                chat_id=message.chat.id,
                message_id=editor_message_id,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Could not edit EV/IV menu: {e}")

# --- Other Functions ---
async def show_pokemon_info(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    species_info = SPECIES_BY_ID.get(pokemon.id, {})
    info_text = f"**Pokédex Info for {pokemon.name}**\n\n"
    info_text += f"**Species:** {species_info.get('baseSpecies', pokemon.name)}\n"
    info_text += f"**Pokédex №:** {species_info.get('num', 'N/A')}\n"
    info_text += f"**Height:** {species_info.get('heightm', 'N/A')} m\n"
    info_text += f"**Weight:** {species_info.get('weightkg', 'N/A')} kg\n"
    info_text += f"**Egg Groups:** {', '.join(species_info.get('eggGroups', ['N/A']))}\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Back to Stats", callback_data=f"p_stats_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=info_text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def show_current_moves_details(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    if not pokemon.moves:
        await bot.answer_callback_query(call.id, f"{pokemon.name} doesn't know any moves!", show_alert=True)
        return
    
    category_emojis = {
        'Physical': '💥',
        'Special': '🔮',
        'Status': '🧿'
    }

    moves_list_parts = [f"<b>{pokemon.name}'s Moves:</b>"]

    for move_id in pokemon.moves:
        move_info = MOVE_BY_ID.get(move_id, {}).copy()
        if not move_info:
            continue

        # --- Dynamic move type logic (Unchanged) ---
        if move_id == 'judgment' and pokemon.id.startswith('arceus'):
            if pokemon.item and 'plate' in pokemon.item.lower():
                move_info['type'] = pokemon.types[0]
        elif move_id == 'multiattack' and pokemon.id.startswith('silvally'):
            if pokemon.item and 'memory' in pokemon.item.lower():
                move_info['type'] = pokemon.types[0]
        elif move_id == 'technoblast' and pokemon.id.startswith('genesect'):
            if pokemon.item == 'Douse Drive': move_info['type'] = 'Water'
            elif pokemon.item == 'Shock Drive': move_info['type'] = 'Electric'
            elif pokemon.item == 'Burn Drive': move_info['type'] = 'Fire'
            elif pokemon.item == 'Chill Drive': move_info['type'] = 'Ice'
        
        # --- NEW, SIMPLIFIED FORMATTING ---
        name = move_info.get('name', 'Unknown')
        move_type = move_info.get('type', '???')
        category = move_info.get('category', '?')
        cat_emoji = category_emojis.get(category, '')
        
        power = move_info.get('basePower', '—')
        accuracy = move_info.get('accuracy')
        acc_str = f"{accuracy}" if isinstance(accuracy, int) else "—"
        
        # FIX: Get MAX PP from the static move data, not the Pokemon object
        max_pp = move_info.get('pp', 0)
        
        # Create a two-line entry for each move
        move_entry = (
            f"• <b>{html.escape(name)}</b> [{move_type}] {cat_emoji}\n"
            f"  <code>Pwr: {str(power):<3} | Acc: {acc_str:<3} | PP: {max_pp}</code>"
        )
        moves_list_parts.append(move_entry)

    moves_text = "\n\n".join(moves_list_parts)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Back to Stats", callback_data=f"p_stats_{pokemon.pokemon_uuid}"))
    
    await bot.edit_message_caption(
        caption=moves_text, 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=markup, 
        parse_mode="HTML"
    )
    
async def show_ev_iv_editor(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    caption = f"**EV/IV Editor for {pokemon.name}**\n\n"
    caption += "Select a stat to modify its EV or IV."
    markup = types.InlineKeyboardMarkup(row_width=2)
    stats = ["hp", "atk", "def", "spa", "spd", "spe"]
    buttons = []
    for stat in stats:
        attr_name = 'def_' if stat == 'def' else stat
        buttons.append(types.InlineKeyboardButton(f"{stat.upper()} EV: {getattr(pokemon.evs, attr_name)}", callback_data=f"p_evivedit_{pokemon_uuid}_ev_{stat}"))
        buttons.append(types.InlineKeyboardButton(f"IV: {getattr(pokemon.ivs, attr_name)}", callback_data=f"p_evivedit_{pokemon_uuid}_iv_{stat}"))
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Back to Stats", callback_data=f"p_stats_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def show_move_selector(bot, call, user_id, pokemon_uuid, letter_filter, page=0):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return

    # --- FIX FOR FORMS & EGG MOVES ---
    all_possible_moves = sorted(resolve_full_learnset(pokemon.id).keys())
    
    filtered_moves = sorted([
        move_id for move_id in all_possible_moves
        if MOVE_BY_ID.get(move_id, {}).get("name", "").upper().startswith(letter_filter)
    ], key=lambda mid: MOVE_BY_ID.get(mid, {}).get("name", ""))
    # --- END OF FIX SECTION ---

    if not filtered_moves:
        await bot.answer_callback_query(call.id, f"No learnable moves found starting with '{letter_filter}'.")
        return

    known_moves_str = ", ".join(
        m.get('name', 'Unknown').capitalize() for m_id in pokemon.moves if (m := MOVE_BY_ID.get(m_id))
    )
    caption = f"Select a move for **{pokemon.name}** (Letter: {letter_filter}).\nCurrently: {known_moves_str}"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    items_per_page = 10
    start, end = page * items_per_page, (page + 1) * items_per_page
    buttons = []

    for i, move_id in enumerate(filtered_moves[start:end]):
        # This calculates the move's true index in the full filtered list.
        actual_index = start + i 

        move_name = MOVE_BY_ID.get(move_id, {}).get("name", move_id)
        prefix = "✅ " if move_id in pokemon.moves else ""
        
        # --- FIX: The callback now uses the correct index ---
        buttons.append(types.InlineKeyboardButton(f"{prefix}{move_name}", callback_data=f"psm_{pokemon_uuid}_{actual_index}_{letter_filter}_{page}"))
    
    markup.add(*buttons)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"p_edtmenu_{pokemon_uuid}_{letter_filter}_{page-1}"))
    if end < len(filtered_moves):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"p_edtmenu_{pokemon_uuid}_{letter_filter}_{page+1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Back to A-Z", callback_data=f"back_pmovefilter_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def set_pokemon_move(bot, call, user_id, pokemon_uuid, move_id, letter_filter, page=0):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    if move_id in pokemon.moves:
        pokemon.moves.remove(move_id)
    elif len(pokemon.moves) < 4:
        pokemon.moves.append(move_id)
    else:
        await bot.answer_callback_query(call.id, "Moveset is full! Remove a move first.", show_alert=True)
        return
    db.update_pokemon_in_collection(user_id, pokemon)
    await show_move_selector(bot, call, user_id, pokemon_uuid, letter_filter, page)

async def set_pokemon_nature(bot, call, user_id, pokemon_uuid, new_nature):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    pokemon.nature = new_nature
    db.update_pokemon_in_collection(user_id, pokemon)
    await bot.answer_callback_query(call.id, f"{pokemon.name}'s nature is now {new_nature}!")
    await show_pokemon_editor(bot, call, user_id, pokemon_uuid)

async def show_ability_selector(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    species_info = SPECIES_BY_ID.get(pokemon.id)
    if not species_info: return
    caption = f"Select a new ability for **{pokemon.name}**."
    markup = types.InlineKeyboardMarkup(row_width=1)
    ability_keys = species_info.get("abilities", {})
    buttons = []
    for key, ability_name in ability_keys.items():
        prefix = "✅ " if pokemon.ability == ability_name else ""
        buttons.append(types.InlineKeyboardButton(f"{prefix}{ability_name}", callback_data=f"p_setability_{pokemon_uuid}_{key}"))
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Back to Editor", callback_data=f"back_peditor_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def set_pokemon_ability(bot, call, user_id, pokemon_uuid, new_ability):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    pokemon.ability = new_ability
    db.update_pokemon_in_collection(user_id, pokemon)
    await bot.answer_callback_query(call.id, f"{pokemon.name}'s ability is now {new_ability}!")
    await show_pokemon_editor(bot, call, user_id, pokemon_uuid)

async def show_move_alphabet_filter(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    caption = f"Select the first letter of the move for **{pokemon.name}**."
    markup = types.InlineKeyboardMarkup(row_width=7)
    buttons = [types.InlineKeyboardButton(letter, callback_data=f"p_edtmenu_{pokemon_uuid}_{letter}") for letter in string.ascii_uppercase]
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Back to Editor", callback_data=f"back_peditor_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")
    
async def confirm_release_pokemon(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    text = f"Are you sure you want to release **{pokemon.name}**?\nThis action cannot be undone."
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("✅ Yes, Release", callback_data=f"p_crel_{pokemon_uuid}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data=f"p_stats_{pokemon_uuid}")
    ]
    markup.add(*buttons)
    await bot.edit_message_caption(caption=text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def release_pokemon(bot, call, user_id, pokemon_uuid):
    pokemon_to_release = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon_to_release: return
    db.remove_pokemon_from_collection(user_id, pokemon_uuid)
    text = f"**{pokemon_to_release.name}** has been released. Farewell, old friend. 😢"
    await bot.delete_message(call.message.chat.id, call.message.id)
    await bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
    await bot.answer_callback_query(call.id, "Pokémon Released!")

# --- Team Management Functions ---
async def show_add_to_team_menu(bot, call, user_id, team_id, slot_index, page=0):
    """
    Shows a paginated list of the user's collection (25 per page),
    marking Pokémon that are already on the current team.
    """
    team_data = db.get_team_by_id(team_id)
    current_team_uuids = set(team_data[3]) if team_data and team_data[3] else set()

    collection = db.get_collection(user_id)
    if not collection:
        await bot.answer_callback_query(call.id, "Your collection is empty!", show_alert=True)
        return

    display_mode = db.get_display_setting(user_id)
    sorted_collection = sorted(collection, key=lambda p: p.name)
    items_per_page = 25
    start = page * items_per_page
    end = start + items_per_page
    page_pokemon = sorted_collection[start:end]

    text = "<b>Select a Pokémon to add:</b>\n\n"
    for i, p in enumerate(page_pokemon):
        list_number = start + i + 1
        prefix = "* " if p.pokemon_uuid in current_team_uuids else ""
        display_str = format_pokemon_display_line(p, display_mode)
        text += f"<b>{list_number}.</b> {prefix}{display_str}\n"

    markup = types.InlineKeyboardMarkup(row_width=5)
    number_buttons = []
    for i, p in enumerate(page_pokemon):
        button_number = str(start + i + 1)
        callback = f"t_addsel_{team_id}_{p.pokemon_uuid}_{slot_index}"
        number_buttons.append(types.InlineKeyboardButton(button_number, callback_data=callback))
    markup.add(*number_buttons)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("Prev", callback_data=f"t_add_{team_id}_{slot_index}_{page-1}"))
    if end < len(sorted_collection):
        nav_buttons.append(types.InlineKeyboardButton("Next", callback_data=f"t_add_{team_id}_{slot_index}_{page+1}"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    markup.row(types.InlineKeyboardButton("Back to Team", callback_data=f"t_edit_{team_id}"))

    await bot.edit_message_text(
        text, 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=markup, 
        parse_mode="HTML"
    )

async def add_pokemon_to_team(bot, call, user_id, team_id, pokemon_uuid, slot_index):
    """Adds a pokemon to the team by appending it consecutively."""
    teams = db.get_user_teams(user_id)
    target_team = next((t for t in teams if t[0] == int(team_id)), None)
    if not target_team: return

    pokemon_uuids = [u for u in (target_team[3] if target_team[3] else []) if u is not None]
    
    if pokemon_uuid in pokemon_uuids:
        await bot.answer_callback_query(call.id, "That Pokémon is already in your team!", show_alert=True)
        return

    if len(pokemon_uuids) >= 6:
        await bot.answer_callback_query(call.id, "Your team is full!", show_alert=True)
        return

    pokemon_uuids.append(pokemon_uuid)
    db.update_team(int(team_id), pokemon_uuids)
    await bot.answer_callback_query(call.id, "Pokémon added to team!")
    
    content = get_myteam_message_content(user_id, team_id)
    await bot.edit_message_text(
        content["text"], 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=content["reply_markup"], 
        parse_mode="HTML"
    )
    
async def confirm_clear_team(bot, call, team_id):
    text = "Are you sure you want to remove all Pokémon from this team?"
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("✅ Yes, Clear", callback_data=f"t_cclr_{team_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data=f"t_view_{team_id}")
    ]
    markup.add(*buttons)
    await bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup)

async def clear_team(bot, call, user_id, team_id):
    db.update_team(int(team_id), [])
    await bot.answer_callback_query(call.id, "Team cleared!")
    
    # --- THIS IS THE FIX ---
    # We now pass the team_id to the UI function
    content = get_myteam_message_content(user_id, team_id)

    await bot.edit_message_text(
        content["text"], 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=content["reply_markup"], 
        parse_mode="HTML"
    )
async def export_team(bot, call, user_id, team_id):
    """Exports the team in Showdown format wrapped in mono font."""
    team_data = db.get_team_by_id(team_id)
    if not team_data:
        await bot.answer_callback_query(call.id, "Team not found.", show_alert=True)
        return

    _, _, team_name, uuids_json, _ = team_data
    pokemon_uuids = [u for u in (uuids_json if uuids_json else []) if u is not None]

    if not pokemon_uuids:
        await bot.answer_callback_query(call.id, "Team is empty!", show_alert=True)
        return

    collection = db.get_collection(user_id)
    pokemon_map = {p.pokemon_uuid: p for p in collection}

    export_lines = []
    for uuid_val in pokemon_uuids:
        p = pokemon_map.get(uuid_val)
        if not p:
            continue

        # Line 1: Name @ Item
        item_str = f" @ {p.item}" if p.item else ""
        export_lines.append(f"{p.name}{item_str}")

        # Ability
        if p.ability:
            export_lines.append(f"Ability: {p.ability}")

        # Tera Type
        if p.tera_type:
            export_lines.append(f"Tera Type: {p.tera_type}")

        # EVs (only non-zero)
        ev_parts = []
        if p.evs.hp > 0: ev_parts.append(f"{p.evs.hp} HP")
        if p.evs.atk > 0: ev_parts.append(f"{p.evs.atk} Atk")
        if p.evs.def_ > 0: ev_parts.append(f"{p.evs.def_} Def")
        if p.evs.spa > 0: ev_parts.append(f"{p.evs.spa} SpA")
        if p.evs.spd > 0: ev_parts.append(f"{p.evs.spd} SpD")
        if p.evs.spe > 0: ev_parts.append(f"{p.evs.spe} Spe")
        if ev_parts:
            export_lines.append(f"EVs: {' / '.join(ev_parts)}")

        # Nature
        if p.nature:
            export_lines.append(f"{p.nature} Nature")

        # IVs (only non-31)
        iv_parts = []
        if p.ivs.hp < 31: iv_parts.append(f"{p.ivs.hp} HP")
        if p.ivs.atk < 31: iv_parts.append(f"{p.ivs.atk} Atk")
        if p.ivs.def_ < 31: iv_parts.append(f"{p.ivs.def_} Def")
        if p.ivs.spa < 31: iv_parts.append(f"{p.ivs.spa} SpA")
        if p.ivs.spd < 31: iv_parts.append(f"{p.ivs.spd} SpD")
        if p.ivs.spe < 31: iv_parts.append(f"{p.ivs.spe} Spe")
        if iv_parts:
            export_lines.append(f"IVs: {' / '.join(iv_parts)}")

        # Moves
        for move_id in p.moves:
            move_info = MOVE_BY_ID.get(move_id, {})
            move_name = move_info.get('name', move_id)
            export_lines.append(f"- {move_name}")

        export_lines.append("")  # blank line between pokemon

    export_text = "\n".join(export_lines).strip()
    message = f"<b>{html.escape(team_name)} (Showdown Export)</b>\n\n<code>{export_text}</code>"

    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Back to Editor", callback_data=f"t_edit_{team_id}"))

    await bot.edit_message_text(
        message,
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        reply_markup=markup,
        parse_mode="HTML"
    )

async def show_tera_type_selector(bot, call, user_id, pokemon_uuid):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    caption = f"Select a Tera Type for **{pokemon.name}**.\nCurrent: {pokemon.tera_type}"
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = [types.InlineKeyboardButton(t, callback_data=f"p_settera_{pokemon_uuid}_{t}") for t in ALL_TYPES]
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Back to Stats", callback_data=f"p_stats_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def set_pokemon_tera_type(bot, call, user_id, pokemon_uuid, new_tera_type):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    pokemon.tera_type = new_tera_type
    db.update_pokemon_in_collection(user_id, pokemon)
    await bot.answer_callback_query(call.id, f"{pokemon.name}'s Tera Type is now {new_tera_type}!")
    content = get_stats_message_content(pokemon, call.message.chat.type, call.from_user.id)
    await bot.edit_message_caption(caption=content["caption"], chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=content["reply_markup"], parse_mode="Markdown")

# --- 3. Implement the menu and logic ---
async def show_form_change_menu(bot, call, user_id, pokemon_uuid):
    """
    Shows a menu of all available forms, explaining how to get both
    permanent and temporary (battle-only) forms.
    """
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon:
        await bot.answer_callback_query(call.id, "Pokémon not found.", show_alert=True)
        return

    species_info = SPECIES_BY_ID.get(pokemon.id, {})
    base_species_name = species_info.get("baseSpecies", pokemon.name)

    permanent_forms = []
    temporary_forms = []

    # --- Categorize all related forms ---
    for s in SPECIES_BY_ID.values():
        if s.get("baseSpecies") == base_species_name:
            form_name = s['name']
            form_name_lower = form_name.lower()

            # --- THIS IS THE FIX ---
            # Explicitly skip G-Max forms so they don't appear in any list.
            if "gmax" in form_name_lower:
                continue
            # --- END OF FIX ---

            block_reason = get_collection_form_block_reason(s)

            if "mega" in form_name_lower:
                stone = form_name.replace(base_species_name, "").replace("-", "") + "ite"
                temporary_forms.append(f"{form_name} (Requires: {stone})")
            elif "primal" in form_name_lower:
                item = s.get("requiredItem", "a special item")
                temporary_forms.append(f"{form_name} (Requires: {item})")
            elif s.get("requiredItem"):
                item = s.get("requiredItem")
                temporary_forms.append(f"{form_name} (Requires: {item})")
            elif block_reason:
                temporary_forms.append(f"{form_name} ({block_reason.capitalize()})")
            elif form_name != pokemon.name:
                permanent_forms.append(form_name)

    # --- Build the informative message ---
    caption = f"✨ <b>Available Forms for {base_species_name.capitalize()}</b>\n\n"

    if permanent_forms:
        caption += "✅ <b>Permanent Forms</b>\n"
        caption += "Use <code>/add</code> to get these forms permanently:\n"
        caption += "<code>"
        for form_name in permanent_forms:
            caption += f"/add {form_name}\n"
        caption += "</code>\n"

    if temporary_forms:
        caption += "⚔️ <b>Battle-Only Forms</b>\n"
        caption += "These forms are achieved in battle by holding the required item:\n"
        for form_info in temporary_forms:
            caption += f"• {form_info}\n"

    if not permanent_forms and not temporary_forms:
            caption += "This Pokémon has no other known forms."

    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("⬅️ Back to Stats", callback_data=f"p_stats_{pokemon.pokemon_uuid}"))
    
    await bot.edit_message_caption(
        caption=caption, 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=markup, 
        parse_mode="HTML"
    )
    
async def set_pokemon_form(bot, call, user_id, pokemon_uuid, new_species_id):
    """
    Transforms a Pokémon to a new form. This is a destructive operation on the old
    pokémon object, replacing it with a new one that inherits key properties.
    """
    old_pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not old_pokemon: return

    # Create the new Pokémon with the new species ID
    new_pokemon = create_pokemon(species_id=new_species_id)

    # --- CARRY OVER PERSISTENT STATS ---
    new_pokemon.pokemon_uuid = old_pokemon.pokemon_uuid # Keep the same unique ID
    new_pokemon.level = old_pokemon.level
    new_pokemon.nickname = old_pokemon.nickname
    new_pokemon.evs = old_pokemon.evs
    new_pokemon.ivs = old_pokemon.ivs
    new_pokemon.is_shiny = old_pokemon.is_shiny # Shininess is permanent
    
    # NOTE: Moveset is NOT carried over, as the new form has a different learnset.
    # The user will have to set moves for the new form.

    db.update_pokemon_in_collection(user_id, new_pokemon)
    await bot.answer_callback_query(call.id, f"{old_pokemon.name} transformed into {new_pokemon.name}!")
    
    # Go back to the main stats screen to show the new Pokémon
    content = get_stats_message_content(new_pokemon, call.message.chat.type, user_id)
    image_path = find_best_sprite_path(new_pokemon, 'image')

    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as photo:
            media = types.InputMediaPhoto(photo, caption=content["caption"], parse_mode="HTML")
            await bot.edit_message_media(
                media=media,
                chat_id=call.message.chat.id,
                message_id=call.message.id,
                reply_markup=content["reply_markup"],
            )
        return

    await bot.edit_message_caption(
        caption=content["caption"],
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        reply_markup=content["reply_markup"],
        parse_mode="HTML",
    )

async def show_item_browser(bot, call, user_id, pokemon_uuid, category_id_str="main", page=0):
    """
    Shows a browsable, toggleable list of items for a Pokémon.
    """
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return

    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if category_id_str == "main":
        caption = f"Browse items for **{pokemon.name}**.\nSelect a category:"
        buttons = [
            types.InlineKeyboardButton(cat_name, callback_data=f"p_itembrowse_{pokemon_uuid}_{i}_0")
            for i, cat_name in enumerate(CATEGORY_NAMES)
        ]
        markup.add(*buttons)
        markup.row(types.InlineKeyboardButton("⬅️ Back to Editor", callback_data=f"p_edt_{pokemon_uuid}"))
    else:
        category_index = int(category_id_str)
        category_name = CATEGORY_NAMES[category_index]
        items_in_category = sorted(ITEM_CATEGORIES.get(category_name, []))

        # --- Combined Pagination Logic for all categories ---
        items_per_page = 10 # 5 rows of 2 buttons
        start = page * items_per_page
        end = start + items_per_page
        page_items = items_in_category[start:end]
        total_pages = -(-len(items_in_category) // items_per_page)
        
        caption = f"Select an item for **{pokemon.name}**.\n(Page {page + 1}/{total_pages})"
        
        buttons = []
        for item_name in page_items:
            item_id = ITEM_ID_BY_NAME.get(item_name)
            if item_id:
                # --- THIS IS THE NEW LOGIC ---
                # 1. Add a checkmark if this is the currently held item
                prefix = "✅ " if pokemon.item == item_name else ""
                
                # 2. Update the callback data to include category and page for refreshing
                callback = f"p_setitem_{pokemon_uuid}_{item_id}_{category_index}_{page}"
                buttons.append(types.InlineKeyboardButton(f"{prefix}{item_name}", callback_data=callback))
                # --- END OF NEW LOGIC ---

        markup.add(*buttons)

        # --- Navigation Buttons ---
        nav_buttons = []
        if page > 0:
            nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"p_itembrowse_{pokemon_uuid}_{category_index}_{page-1}"))
        if end < len(items_in_category):
            nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"p_itembrowse_{pokemon_uuid}_{category_index}_{page+1}"))
        if nav_buttons:
            markup.row(*nav_buttons)
        
        markup.row(types.InlineKeyboardButton("⬅️ Back to Categories", callback_data=f"p_itembrowse_{pokemon_uuid}_main"))

    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def set_pokemon_item(bot, call, user_id, pokemon_uuid, item_id, category_id_str, page):
    """
    Equips, unequips, or toggles an item for a Pokémon and refreshes the browser.
    Handles both form changes and reversions.
    """
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return

    # --- THIS IS THE NEW, MORE ROBUST LOGIC ---

    # 1. Store the Pokémon's original form ID to detect any change later.
    original_pokemon_id = pokemon.id

    item_name_clicked = ITEM_NAME_BY_ID.get(item_id)

    # 2. Toggle the item: If it's already held, remove it. Otherwise, equip it.
    if pokemon.item == item_name_clicked:
        pokemon.item = None
        await bot.answer_callback_query(call.id, "Item unequipped!")
    else:
        pokemon.item = item_name_clicked
        await bot.answer_callback_query(call.id, f"{item_name_clicked} equipped!")

    # 3. Determine the correct form based on the current item.
    base_species_info = SPECIES_BY_ID.get(original_pokemon_id, {})
    base_species_name = base_species_info.get("baseSpecies", pokemon.name)

    form_change_pokemon = ["Arceus", "Silvally", "Dialga", "Palkia", "Giratina", "Genesect", "Necrozma", "Ogerpon"]

    if base_species_name in form_change_pokemon:
        target_form_id = None
        # Case A: An item is held. Find the corresponding form.
        if pokemon.item:
            for s_id, s_data in SPECIES_BY_ID.items():
                if s_data.get("baseSpecies") == base_species_name:
                    required_item_single = s_data.get("requiredItem")
                    required_items_list = s_data.get("requiredItems")
                    is_match = False
                    if isinstance(required_items_list, list) and pokemon.item in required_items_list:
                        is_match = True
                    elif isinstance(required_item_single, str) and pokemon.item == required_item_single:
                        is_match = True
                    if is_match:
                        target_form_id = s_id
                        break
        # Case B: No item is held. The target form MUST be the base form.
        else:
            target_form_id = base_species_name.lower().replace(" ", "")

        # 4. Apply the form change if a valid target was found and it's different from the current form.
        if target_form_id and pokemon.id != target_form_id:
            new_form_data = SPECIES_BY_ID.get(target_form_id)
            if new_form_data:
                pokemon.id = new_form_data['id']
                pokemon.name = new_form_data['name']
                pokemon.types = new_form_data['types']
                # Provide feedback to the user about the change
                form_name = new_form_data.get('forme') or 'base'
                await bot.answer_callback_query(call.id, f"{base_species_name} reverted to its {form_name} form!")

    # 5. Determine if a form change occurred by comparing the ID before and after all logic.
    form_changed = (original_pokemon_id != pokemon.id)

    db.update_pokemon_in_collection(user_id, pokemon)

    # 6. Refresh the main stats view if a change happened, otherwise refresh the item browser.
    if form_changed:
        await _refresh_stats_view_after_edit(bot, call, pokemon)
    else:
        await show_item_browser(bot, call, user_id, pokemon_uuid, category_id_str, page)

async def show_nature_selector(bot, call, user_id, pokemon_uuid, page=0):
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon: return
    caption = f"Select a new nature for **{pokemon.name}**."
    markup = types.InlineKeyboardMarkup(row_width=3)
    items_per_page = 9
    start, end = page * items_per_page, (page + 1) * items_per_page
    page_natures = ALL_NATURES[start:end]
    buttons = [types.InlineKeyboardButton(n, callback_data=f"p_setnature_{pokemon_uuid}_{n}") for n in page_natures]
    markup.add(*buttons)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"p_edtmenu_{pokemon_uuid}_nature_{page-1}"))
    if end < len(ALL_NATURES):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"p_edtmenu_{pokemon_uuid}_nature_{page+1}"))
    
    markup.row(*nav_buttons)
    markup.row(types.InlineKeyboardButton("⬅️ Back to Editor", callback_data=f"back_peditor_{pokemon_uuid}"))
    await bot.edit_message_caption(caption=caption, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="Markdown")

async def show_stats_table(bot, call, user_id, pokemon_uuid):
    """Displays the detailed IV/EV stats table for a Pokémon."""
    pokemon = db.get_pokemon_from_collection(user_id, pokemon_uuid)
    if not pokemon:
        await bot.answer_callback_query(call.id, "Pokémon not found.", show_alert=True)
        return

    # We need to import this new function at the top of the file:
    # from bot.ui_components import get_stats_table_content
    content = get_stats_table_content(pokemon)
    await bot.edit_message_caption(
        caption=content["caption"],
        chat_id=call.message.chat.id,
        message_id=call.message.id,
        reply_markup=content["reply_markup"],
        parse_mode="HTML"
    )

async def show_remove_from_team_menu(bot, call, user_id, team_id):
    """Shows a menu to select which Pokémon to remove from a team."""
    team_data = db.get_team_by_id(team_id)
    if not team_data: return

    pokemon_uuids = [u for u in (team_data[3] if team_data[3] else []) if u is not None]
    if not pokemon_uuids:
        await bot.answer_callback_query(call.id, "This team is already empty!", show_alert=True)
        return

    collection = db.get_collection(user_id)
    pokemon_map = {p.pokemon_uuid: p for p in collection}
    display_mode = db.get_display_setting(user_id)
    
    text = "➖ Select a Pokémon to remove:"
    markup = types.InlineKeyboardMarkup(row_width=1)
    buttons = []
    for i, uuid in enumerate(pokemon_uuids):
        pokemon = pokemon_map.get(uuid)
        if pokemon:
            display_str = format_pokemon_display_line(pokemon, display_mode)
            buttons.append(types.InlineKeyboardButton(f"{i+1}.{display_str}", callback_data=f"t_remsel_{team_id}_{i}"))
        else:
            buttons.append(types.InlineKeyboardButton(f"{i+1}.Unknown", callback_data=f"t_remsel_{team_id}_{i}"))
    
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("Back to Editor", callback_data=f"t_edit_{team_id}"))
    await bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="HTML")

async def remove_pokemon_from_team(bot, call, user_id, team_id, slot_index):
    """Removes a Pokémon from the specified slot and updates the team."""
    team_data = db.get_team_by_id(team_id)
    if not team_data: return
    
    pokemon_uuids = team_data[3] if team_data[3] else []
    
    if 0 <= slot_index < len(pokemon_uuids):
        removed_pokemon_uuid = pokemon_uuids.pop(slot_index)
        db.update_team(team_id, pokemon_uuids)
        await bot.answer_callback_query(call.id, "Pokémon removed.")

    # Refresh the main editor menu
    content = get_myteam_message_content(user_id, team_id)
    await bot.edit_message_text(
        content["text"], 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=content["reply_markup"], 
        parse_mode="HTML"
    )

async def show_swap_menu_step1(bot, call, user_id, team_id):
    """Shows the first step of the swap process."""
    team_data = db.get_team_by_id(team_id)
    if not team_data: return
    
    pokemon_uuids = [u for u in (team_data[3] if team_data[3] else []) if u is not None]
    if len(pokemon_uuids) < 2:
        await bot.answer_callback_query(call.id, "You need at least two Pokémon to swap.", show_alert=True)
        return

    collection = db.get_collection(user_id)
    pokemon_map = {p.pokemon_uuid: p for p in collection}
    display_mode = db.get_display_setting(user_id)
    
    text = "🔁 <b>Step 1:</b> Select the first Pokémon to swap."
    markup = types.InlineKeyboardMarkup(row_width=1)
    buttons = []
    for i, uuid in enumerate(pokemon_uuids):
        pokemon = pokemon_map.get(uuid)
        display_str = format_pokemon_display_line(pokemon, display_mode) if pokemon else "Unknown"
        buttons.append(types.InlineKeyboardButton(f"{i+1}.{display_str}", callback_data=f"t_swapsel1_{team_id}_{i}"))
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("Cancel", callback_data=f"t_edit_{team_id}"))
    await bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="HTML")

async def show_swap_menu_step2(bot, call, user_id, team_id, slot_index1):
    """Shows the second step of the swap process."""
    team_data = db.get_team_by_id(team_id)
    if not team_data: return

    pokemon_uuids = [u for u in (team_data[3] if team_data[3] else []) if u is not None]
    collection = db.get_collection(user_id)
    pokemon_map = {p.pokemon_uuid: p for p in collection}
    display_mode = db.get_display_setting(user_id)
    
    first_pokemon = pokemon_map.get(pokemon_uuids[slot_index1])
    first_name = format_pokemon_display_line(first_pokemon, display_mode) if first_pokemon else "Unknown"

    text = f"🔁 <b>Step 2:</b> Select a Pokémon to swap with <b>{first_name}</b>."
    markup = types.InlineKeyboardMarkup(row_width=1)
    buttons = []
    for i, uuid in enumerate(pokemon_uuids):
        pokemon = pokemon_map.get(uuid)
        display_str = format_pokemon_display_line(pokemon, display_mode) if pokemon else "Unknown"
        if i == slot_index1:
            buttons.append(types.InlineKeyboardButton(f"> {i+1}.{display_str} <", callback_data="noop"))
        else:
            buttons.append(types.InlineKeyboardButton(f"{i+1}.{display_str}", callback_data=f"t_swapexec_{team_id}_{slot_index1}_{i}"))

    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("Cancel", callback_data=f"t_edit_{team_id}"))
    await bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.id, reply_markup=markup, parse_mode="HTML")

async def execute_swap(bot, call, user_id, team_id, slot_index1, slot_index2):
    """Performs the swap and updates the team."""
    team_data = db.get_team_by_id(team_id)
    if not team_data: return
    
    pokemon_uuids = team_data[3] if team_data[3] else []

    if 0 <= slot_index1 < len(pokemon_uuids) and 0 <= slot_index2 < len(pokemon_uuids):
        # Perform the swap
        pokemon_uuids[slot_index1], pokemon_uuids[slot_index2] = pokemon_uuids[slot_index2], pokemon_uuids[slot_index1]
        db.update_team(team_id, pokemon_uuids)
        await bot.answer_callback_query(call.id, "Pokémon positions swapped!")

    # Refresh the main editor menu
    content = get_myteam_message_content(user_id, team_id)
    await bot.edit_message_text(
        content["text"], 
        chat_id=call.message.chat.id, 
        message_id=call.message.id, 
        reply_markup=content["reply_markup"], 
        parse_mode="HTML"
    )

CARD_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'trainercard')
AVAILABLE_COLORS = {"White": "white", "Black": "black", "Gold": "gold", "Red": "#FF4136", "Blue": "#0074D9"}

async def refresh_trainer_card_preview(bot, call, menu_context: str, **kwargs):
    user_id = call.from_user.id
    user_name = call.from_user.first_name
    
    if menu_context == 'templates':
        new_content = get_tc_template_selection_content(user_id, kwargs['card_type'], kwargs['page'])
    elif menu_context == 'sprites':
        new_content = get_tc_sprite_list_content(user_id, kwargs['letter'], kwargs['page'])
    elif menu_context == 'font':
        new_content = get_tc_font_menu_content(user_id)
    else:
        new_content = get_tc_main_menu_content()

    stats = db.get_user_stats(user_id)
    prefs = db.get_user_card_prefs(user_id)
    elo, wins, losses, _ = stats
    card_template, trainer_sprite, font_color = prefs

    card_image = await create_trainer_card_image(user_name, elo, wins, losses, card_template, trainer_sprite, font_color)

    if card_image:
        media = types.InputMediaPhoto(card_image, caption=new_content['text'], parse_mode="HTML")
        await bot.edit_message_media(
            media=media,
            chat_id=call.message.chat.id,
            message_id=call.message.id,
            reply_markup=new_content['markup']
        )

def get_tc_main_menu_content():
    text = "<b>Trainer Card Editor</b>\n\nChoose what you want to customize. Press 'Done' when you're finished."
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("🖼️ Card Template", callback_data="tc_types"),
        types.InlineKeyboardButton("🧍 Trainer Sprite", callback_data="tc_spriteaz")
    )
    markup.add(types.InlineKeyboardButton("🎨 Font Color", callback_data="tc_font")) # New button
    markup.add(types.InlineKeyboardButton("✅ Done", callback_data="tc_done"))
    return {"text": text, "markup": markup}

# --- NEW FUNCTION for the font menu ---
def get_tc_font_menu_content(user_id):
    _, _, current_color = db.get_user_card_prefs(user_id)
    text = "Select a font color:"
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for name, value in AVAILABLE_COLORS.items():
        button_text = f"✅ {name}" if value == current_color else name
        buttons.append(types.InlineKeyboardButton(button_text, callback_data=f"tc_setfont_{value}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="tc_main"))
    return {"text": text, "markup": markup}
    
def get_tc_type_selection_content():
    text = "Select a card category:"
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Normal Cards", callback_data="tc_templates_normalcard_0"),
        types.InlineKeyboardButton("Custom Cards", callback_data="tc_templates_customcard_0")
    )
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="tc_main"))
    return {"text": text, "markup": markup}

def get_tc_template_selection_content(user_id, card_type, page):
    current_template, _, _ = db.get_user_card_prefs(user_id)
    items_per_page = 4
    folder_path = os.path.join(CARD_ASSETS_DIR, card_type)
    prefix = 'Lcard' if card_type == 'customcard' else 'card'
    all_files = sorted([f for f in os.listdir(folder_path) if f.startswith(prefix) and f.endswith('.png')])
    
    start, end = page * items_per_page, (page + 1) * items_per_page
    page_files = all_files[start:end]
    
    text = f"Select a template from <b>{card_type}</b> (Page {page + 1})"
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for f in page_files:
        button_text = f.replace('.png','')
        # Add a checkmark for the currently selected template
        if f"{card_type}/{f}" == current_template:
            button_text = f"✅ {button_text}"
        buttons.append(types.InlineKeyboardButton(button_text, callback_data=f"tc_settemplate_{card_type}_{f}_{page}"))
    markup.add(*buttons)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"tc_templates_{card_type}_{page-1}"))
    if end < len(all_files):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"tc_templates_{card_type}_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    markup.add(types.InlineKeyboardButton("⬅️ Back to Categories", callback_data="tc_types"))
    return {"text": text, "markup": markup}

def get_tc_sprite_az_content():
    text = "Select the first letter of the trainer sprite's name:"
    markup = types.InlineKeyboardMarkup(row_width=7)
    buttons = [types.InlineKeyboardButton(letter, callback_data=f"tc_spritelist_{letter}_0") for letter in string.ascii_uppercase]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="tc_main"))
    return {"text": text, "markup": markup}

def get_tc_sprite_list_content(user_id, letter, page):
    _, current_sprite, _ = db.get_user_card_prefs(user_id)
    items_per_page = 10
    folder_path = os.path.join(CARD_ASSETS_DIR, 'sprites-trainers')
    all_files = sorted([f for f in os.listdir(folder_path) if f.lower().startswith(letter.lower()) and f.endswith('.png')])

    start, end = page * items_per_page, (page + 1) * items_per_page
    page_files = all_files[start:end]

    text = f"Select a sprite (Letter: <b>{letter}</b>, Page {page + 1})"
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for f in page_files:
        button_text = f.replace('.png','').title()
        if f == current_sprite:
            button_text = f"✅ {button_text}"
        buttons.append(types.InlineKeyboardButton(button_text, callback_data=f"tc_setsprite_{f}_{letter}_{page}"))
    markup.add(*buttons)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"tc_spritelist_{letter}_{page-1}"))
    if end < len(all_files):
        nav_buttons.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"tc_spritelist_{letter}_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)

    markup.add(types.InlineKeyboardButton("⬅️ Back to A-Z", callback_data="tc_spriteaz"))
    return {"text": text, "markup": markup}

async def _refresh_stats_view_after_edit(bot: AsyncTeleBot, call: types.CallbackQuery, pokemon: Pokemon):
    """
    Finds the new image for a Pokémon and updates the entire stats message (media + caption).
    """
    # --- This is the "smart search" logic to find the best image ---
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
    ids_to_try = []
    ids_to_try.append(pokemon.id)
    formatted_name = pokemon.name.lower().replace(" ", "-").replace("’", "").replace(".", "")
    ids_to_try.append(formatted_name)
    base_name = formatted_name.split('-')[0]
    ids_to_try.append(base_name)
    ids_to_try = list(dict.fromkeys(ids_to_try))
    image_path_to_use = None

    for image_id in ids_to_try:
        filename = f"{image_id}.png"
        artwork_path = os.path.join(ASSETS_DIR, 'sprite', 'image', filename)
        if os.path.exists(artwork_path):
            image_path_to_use = artwork_path
            break
        sprite_path = os.path.join(ASSETS_DIR, 'sprite', 'sprites-gen5', filename)
        if os.path.exists(sprite_path):
            image_path_to_use = sprite_path
            break
            
    # --- Generate the new caption and keyboard ---
    content = get_stats_message_content(pokemon, call.message.chat.type, call.from_user.id)

    # --- Update the message with the new photo and caption ---
    if image_path_to_use:
        with open(image_path_to_use, 'rb') as photo:
            media = types.InputMediaPhoto(photo.read(), caption=content["caption"], parse_mode="HTML")
            await bot.edit_message_media(
                media=media,
                chat_id=call.message.chat.id,
                message_id=call.message.id,
                reply_markup=content["reply_markup"]
            )
    else: # Fallback if for some reason an image isn't found
        await bot.edit_message_caption(
            caption=f"Image for {pokemon.name} not found.\n\n{content['caption']}",
            chat_id=call.message.chat.id,
            message_id=call.message.id,
            reply_markup=content["reply_markup"],
            parse_mode="HTML"
        )

def _get_feature_explanation_content(feature: str) -> dict:
    """Generates the detailed text and image for a specific feature."""
    
    # Image URLs for each section
    image_map = {
        "collection": "https://ar-hosting.pages.dev/1761313866114.jpg",
        "teams": "https://ar-hosting.pages.dev/1761313606047.jpg",
        "battle": "https://ar-hosting.pages.dev/1761313328619.jpg",
        "custom": "https://ar-hosting.pages.dev/1761313236677.jpg"
    }
    
    # Text content for each section
    text_map = {
        "collection": (
            "<b>📸 Pokémon Collection</b>\n\n"
            "Your journey begins here! Build a collection of your favorite Pokémon.\n\n"
            "• <code>/add &lt;pokemon&gt;</code>: Catch a new Pokémon. Try <code>/add Pikachu</code>!\n"
            "• <code>/mycollection</code>: View your entire collection in a paginated list.\n"
            "• <code>/view &lt;name&gt;</code>: Get a detailed view of one of your Pokémon, where you can customize its level, nature, moves, and more."
        ),
        "teams": (
            "<b>🏆 Team Building & Analysis</b>\n\n"
            "Assemble your ultimate team of six to prepare for battle.\n\n"
            "• <code>/myteams</code>: Access the team management menu. Here you can create up to six teams, set one as active, and edit your roster.\n"
            "• <code>/viewteam</code>: Generates a beautiful image of your active team, complete with a strategic analysis of its defensive strengths and weaknesses."
        ),
        "battle": (
            "<b>⚔️ Live Battles</b>\n\n"
            "Challenge other trainers in your group to a real-time battle!\n\n"
            "• <code>/challenge</code>: Reply to a user's message to issue a singles Showdown PvP challenge.\n"
            "• <code>/doubles</code>: Reply to a user's message to issue a doubles Showdown PvP challenge.\n"
            "• <code>/ffa</code>: Open a free-for-all lobby in a group chat.\n"
            "• <code>/battle_stats</code>: View the live stat snapshot of your current active Pokémon during a battle.\n"
            "• <code>/exit</code>: Cancel your pending PvP challenge or close your active PvP battle.\n"
            "• <b>Full-Fledged Mechanics</b>: The Showdown battle flow supports team preview, move locking, switches, forfeit, battle visuals, Mega Evolution, Dynamax, Tera, Z-Moves, and more.\n"
            "• <b>Custom Rules</b>: Use the 'Settings' button in the challenge menu to enable owned-team or random battles and tune visuals."
        ),
        "custom": (
            "<b>🎨 Profile Customization</b>\n\n"
            "Show off your achievements with a personalized Trainer Card.\n\n"
            "• <code>/trainercard</code>: Generates your unique card, displaying your battle record and Elo rating.\n"
            "• <b>Edit Your Card</b>: Use the 'Edit Card' button (in a private chat with me) to change your card's template, your trainer sprite, and even the font color!"
        )
    }

    image_url = image_map.get(feature, "https://images.alphacoders.com/133/1332281.png")
    link_preview = f'<a href="{image_url}">&#8203;</a>'
    text = f"{link_preview}{text_map.get(feature, 'Feature not found.')}"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="start_menu_main"))

    return {"text": text, "reply_markup": markup}
