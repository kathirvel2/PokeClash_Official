# ./bot/battle/modes/turn_based_handler.py
import asyncio
import random
from telebot.async_telebot import AsyncTeleBot

from bot.battle.battle_engine import Battle, active_battles 
from bot.battle.battle_logic import execute_move
from bot.battle.move_effects.status import check_can_move, apply_status
from bot.mechanics.moves_loader import MOVE_BY_ID
from bot.battle.move_effects.status_moves import handle_status_move, handle_stat_boost_move

from bot.battle.field_effects import terrain as terrain_logic
from bot.battle.field_effects import weather as weather_logic
from bot.battle.dynamax.dynamax_logic import revert_dynamax
from bot.battle.dynamax.dynamax_ui import get_dynamax_move_for_pokemon
from bot.battle.item_effects import item_logic
from bot.mechanics.db import db
from telebot import types
from bot.mechanics.ranking import calculate_elo_change
from bot.image_generation.ranking_image import create_ranking_summary_image
from bot.battle.ability_effects.form_change_logic import check_for_form_change
from bot.battle.z_move_data import get_z_move_details, SIGNATURE_Z_MOVES, TYPE_TO_Z_MOVE
from bot.mechanics.item_data import ITEM_ID_BY_NAME

def remove_battle(battle: Battle):
    """Safely removes a specific battle instance without deleting the whole chat key."""
    if battle.chat_id in active_battles:
        if battle in active_battles[battle.chat_id]:
            active_battles[battle.chat_id].remove(battle)
        
        # Only delete the dictionary key if the list is completely empty
        if not active_battles[battle.chat_id]:
            del active_battles[battle.chat_id]

async def process_turn_based_action(
    bot: AsyncTeleBot, battle: Battle, call, user_id: int, pre_action_log: str = "", action_type: str | None = None
):
    """
    This function contains all the logic for processing a single action
    in a turn-based battle.
    """
    from bot.battle.battle_handlers import (
        handle_faint,
        start_turn,
        update_battle_ui,
        handle_end_of_turn_effects,
        handle_delayed_effects,
        handle_slot_conditions,
        start_turn_timer
    )

    battle.is_processing_turn = True
    player = battle.get_player(user_id)
    attacker = player.get_active_pokemon()
    opponent_player, defender = battle.get_opponent_for_player(player)
    
    action_log = pre_action_log
    move_results = {}
    should_update_image = False
    is_charging_turn = False
    move_data = None # Will hold the move data for the turn
    
    # --- BIDE ACTION BLOCK ---
    bide_state = attacker.volatiles.get('bide')
    if bide_state:
        bide_state['turns'] -= 1
        
        if bide_state['turns'] > 0:
            action_log = f"{attacker.pokemon.name} is storing energy!"
        else:
            damage_to_deal = bide_state['damage_taken'] * 2
            del attacker.volatiles['bide']
            if 'lockedmove' in attacker.volatiles: del attacker.volatiles['lockedmove']

            if damage_to_deal == 0:
                action_log = f"{attacker.pokemon.name} unleashed energy, but it failed!"
            else:
                defender.current_hp = max(0, defender.current_hp - damage_to_deal)
                action_log = f"{attacker.pokemon.name} unleashed energy, dealing {damage_to_deal} damage!"
        
        if defender.current_hp <= 0:
            action_log += f"\n{defender.pokemon.name} fainted!"
            if await handle_faint(bot, battle, opponent_player):
                action_log += f"\n\n🏆 {battle.winner.user_name} is the winner!"
                await update_battle_ui(bot, battle, action_log)
                remove_battle(battle)
                battle.is_processing_turn = False
                return

        is_turn_over = player.user_id == battle.turn_order[1][0].user_id
        if is_turn_over:
            # --- THIS IS THE CORRECTED END-OF-TURN SEQUENCE FOR BIDE ---
            await update_battle_ui(bot, battle, action_log)
            await asyncio.sleep(2.5)
            
            # Call all end-of-turn effects
            end_of_turn_log = await handle_end_of_turn_effects(battle)
            slot_condition_log = await handle_slot_conditions(battle)
            
            final_log = action_log
            if end_of_turn_log: final_log += "\n" + end_of_turn_log
            if slot_condition_log: final_log += "\n" + slot_condition_log

            # Final faint checks after all effects
            p1_fainted = battle.player1.get_active_pokemon().current_hp <= 0
            p2_fainted = battle.player2.get_active_pokemon().current_hp <= 0
            if p1_fainted or p2_fainted:
                 # Let handle_faint manage the switch prompt or end the game
                 fainting_player = battle.player1 if p1_fainted else battle.player2
                 final_log += f"\n{fainting_player.get_active_pokemon().pokemon.name} fainted!"
                 if await handle_faint(bot, battle, fainting_player):
                      final_log += f"\n\n🏆 {battle.winner.user_name} is the winner!"
                 await update_battle_ui(bot, battle, final_log)
                 remove_battle(battle)
                 battle.is_processing_turn = False
                 return
            
            await start_turn(bot, battle)
            await update_battle_ui(bot, battle, f"{final_log}\n\n--- Turn {battle.turn} ---")
            # --- END OF CORRECTED SEQUENCE ---
        else:
            battle.active_player_id = battle.turn_order[1][0].user_id
            await update_battle_ui(bot, battle, action_log)

        battle.is_processing_turn = False
        return
    # --- END OF BIDE ACTION BLOCK ---

    move_id = None
    is_locked_turn = False
    locked_move_state = attacker.volatiles.get('lockedmove')

    if locked_move_state:
        is_locked_turn = True
        move_id = locked_move_state['move_id']
        action_log += f"{attacker.pokemon.name} is thrashing about!\n"
        defender = opponent_player.get_active_pokemon()
    
    attacker.is_protected = False

    if attacker.charging_move:
        # This is TURN 2 of a charging move.
        move_data = attacker.charging_move
        attacker.charging_move = None
        # action_log += f"{attacker.pokemon.name} used {move_data['name']}!"
        move_results = execute_move(attacker, defender, move_data["id"], battle, base_move_id=move_data.get('base_move_id'))
    else:
        # This is TURN 1 of any move.
        parts = call.data.split("_")
        move_id_for_check = attacker.pokemon.moves[int(parts[2])]
        can_move, reason = check_can_move(attacker, move_id_for_check)
        if not can_move:
            # --- REPLACE THE OLD `if not can_move:` BLOCK WITH THIS ---
    
            # 1. Perform immediate cleanup for the Pokémon that cannot move.
            if is_locked_turn:
                del attacker.volatiles['lockedmove']
            attacker.consecutive_protect_successes = 0
            
            # 2. Determine if this was the last action of the turn.
            is_turn_over = player.user_id == battle.turn_order[1][0].user_id
    
            # 3. Handle the turn flow.
            if is_turn_over:
                # --- Start of Complete End-of-Turn Logic ---
                end_of_turn_log = await handle_end_of_turn_effects(battle)
                slot_condition_log = await handle_slot_conditions(battle)
                delayed_effects_log, _ = await handle_delayed_effects(bot, battle)
                
                final_log = reason
                if end_of_turn_log: final_log += "\n" + end_of_turn_log
                if slot_condition_log: final_log += "\n" + slot_condition_log
                if delayed_effects_log: final_log += "\n" + delayed_effects_log
    
                # Final faint checks after all effects
                fainted_players = []
                if battle.player1.get_active_pokemon().current_hp <= 0: fainted_players.append(battle.player1)
                if battle.player2.get_active_pokemon().current_hp <= 0: fainted_players.append(battle.player2)
    
                for p in fainted_players:
                    if battle.state == "active":
                        final_log += f"\n{p.get_active_pokemon().pokemon.name} fainted!"
                        if await handle_faint(bot, battle, p):
                            # Game is over, show final message and stop
                            final_log += f"\n\n🏆 {battle.winner.user_name} is the winner!"
                            await update_battle_ui(bot, battle, final_log, update_image=True)
                            remove_battle(battle)
                            battle.is_processing_turn = False
                            return 
                        else:
                            # A switch is required, stop and wait for input
                            await update_battle_ui(bot, battle, final_log, update_image=True)
                            battle.is_processing_turn = False
                            return
    
                # If no one fainted, start the next turn normally
                if battle.state == "active":
                    await start_turn(bot, battle)
                    await update_battle_ui(bot, battle, f"{final_log}\n\n--- Turn {battle.turn} ---", update_image=True)
                # --- End of Complete End-of-Turn Logic ---
    
            else:
                # The first player couldn't move, so just pass control to the second player.
                battle.active_player_id = battle.turn_order[1][0].user_id
                await update_battle_ui(bot, battle, reason)
                
            # 4. Release the turn lock and exit.
            battle.is_processing_turn = False
            return

        base_move_id = None # The original move before transformation

        # 1. Determine the BASE move for this turn
        if locked_move_state:
            is_locked_turn = True
            base_move_id = locked_move_state['move_id']
            action_log += f"{attacker.pokemon.name} is thrashing about!\n"
        elif call:
            parts = call.data.split("_")
            base_move_id = attacker.pokemon.moves[int(parts[2])]

        if not base_move_id:
            # Failsafe in case something went wrong
            battle.is_processing_turn = False
            return

        if base_move_id == 'sleeptalk' and attacker.status == 'slp':
            restricted_moves = ['sleeptalk', 'rest', 'bide', 'focuspunch'] 
            usable_moves = [m for m in attacker.pokemon.moves if m not in restricted_moves]
            
            if not usable_moves:
                action_log += "\nBut it failed!"
                # If the move fails, the turn must end here.
                await start_turn(bot, battle)
                await update_battle_ui(bot, battle, f"{action_log}\n\n--- Turn {battle.turn} ---")
                battle.is_processing_turn = False
                return
                
            chosen_move_id = random.choice(usable_moves)
            chosen_move_data = MOVE_BY_ID[chosen_move_id]
            action_log += f"\n{attacker.pokemon.name} used Sleep Talk!\n{attacker.pokemon.name} used {chosen_move_data['name']}!"
            
            # CRITICAL: Overwrite the base_move_id for the rest of the function to use the new move
            base_move_id = chosen_move_id

        is_z_move_execution = (action_type == 'zmove')

        # --- Determine the ACTUAL move to be used (Z-Move, Max Move, or Base) ---
        if is_z_move_execution:
            signature_info = SIGNATURE_Z_MOVES.get(base_move_id)
            item_id = ITEM_ID_BY_NAME.get(attacker.pokemon.item, "")
            base_move_data = MOVE_BY_ID[base_move_id]

            if signature_info and item_id == signature_info['item_id'] and base_move_data['category'] != 'Status':
                # This is a signature Z-move. We create a temporary dict for it.
                move_id = signature_info['z_move_id']
                move_data = {
                    'id': move_id,
                    'name': signature_info['z_move_name'],
                    'category': base_move_data['category'],
                    'type': base_move_data['type'],
                    'accuracy': True,
                    'breaksProtect': True
                }
            elif base_move_data['category'] != 'Status':
                # Generic damaging Z-move
                z_move_info_from_type = TYPE_TO_Z_MOVE.get(base_move_data['type'])
                if z_move_info_from_type:
                    move_id = z_move_info_from_type['id']
                    move_data = MOVE_BY_ID.get(move_id, {}).copy()
                else: # Failsafe
                    move_id = base_move_id
                    move_data = base_move_data.copy()
            else:
                # Status Z-move
                move_id = base_move_id
                move_data = base_move_data.copy()
                move_data['name'] = f"Z-{move_data['name']}"

        elif 'dynamax' in attacker.volatiles:
            move_id = get_dynamax_move_for_pokemon(base_move_id, attacker)
            move_data = MOVE_BY_ID.get(move_id, {}).copy()
        else:
            move_id = base_move_id
            move_data = MOVE_BY_ID.get(move_id, {}).copy()

        # This handles special form-based move name changes after the main logic
        if attacker.pokemon.id == 'zaciancrowned' and move_id == 'ironhead':
            move_data = MOVE_BY_ID.get('behemothbash', {}).copy()
        elif attacker.pokemon.id == 'zamazentacrowned' and move_id == 'ironhead':
            move_data = MOVE_BY_ID.get('behemothblade', {}).copy()


        move_data = MOVE_BY_ID[move_id]
        
        if 'taunt' in attacker.volatiles and move_data['category'] == 'Status':
            await update_battle_ui(bot, battle, f"{attacker.pokemon.name} can't use {move_data['name']} after being taunted!")
            battle.is_processing_turn = False
            return

        if 'encore' in attacker.volatiles and move_id != attacker.volatiles['encore']['move_id']:
            await update_battle_ui(bot, battle, f"{attacker.pokemon.name} can't use that move! It's under an encore!")
            battle.is_processing_turn = False
            return

        if 'disable' in attacker.volatiles and move_id == attacker.volatiles['disable']['move_id']:
            await update_battle_ui(bot, battle, f"{attacker.pokemon.name}'s {move_data['name']} is disabled!")
            battle.is_processing_turn = False
            return

        if 'torment' in attacker.volatiles and move_id == attacker.last_move_used:
            await update_battle_ui(bot, battle, f"{attacker.pokemon.name} can't use the same move twice in a row!")
            battle.is_processing_turn = False
            return

        if move_data.get('volatileStatus') != 'protect':
            attacker.consecutive_protect_successes = 0

        if move_data.get('terrain') and battle.active_terrain != move_data.get('terrain'):
            should_update_image = True

        if move_data.get('weather') and battle.active_weather != move_data.get('weather'):
            should_update_image = True
            
        if move_id == 'trickroom' or move_id == 'wonderroom':
            should_update_image = True

        if attacker.move_pp[base_move_id] <= 0:
            await bot.answer_callback_query(call.id, "No PP left for this move!", show_alert=True)
            battle.is_processing_turn = False
            return

        # Decrement PP of the BASE move
        if not is_locked_turn:
            attacker.move_pp[base_move_id] -= 1
        
        # Create the log using the ACTUAL move's name
        # if not is_locked_turn:
        #    action_log += f"{attacker.pokemon.name} used {move_data['name']}!"

        form_change_log = await check_for_form_change(bot, battle, attacker, event='on_before_move', move_category=move_data['category'])
        if form_change_log:
            action_log += form_change_log
            should_update_image = True
        
        # Check if this is the START of a charging move
        if move_data.get("flags", {}).get("charge") and not \
                (move_data.get('id') == 'solarbeam' and battle.active_weather == 'sunnyday') and not is_z_move_execution:
            is_charging_turn = True
            attacker.charging_move = move_data.copy()
            attacker.charging_move['base_move_id'] = base_move_id
            attacker.charging_move = move_data
            # --- START OF MODIFICATION ---
            
            # Special case for Meteor Beam: Apply +1 SpA on Turn 1
            if move_id == 'meteorbeam':
                boost_log = handle_stat_boost_move(attacker, {'boosts': {'spa': 1}})
                action_log = f"{attacker.pokemon.name} is absorbing power!"
                if boost_log:
                    action_log += "\n" + boost_log
            else:
                # Original charge move logic
                charge_messages = {
                    "fly": f"{attacker.pokemon.name} flew up high!",
                    "dig": f"{attacker.pokemon.name} dug a hole!",
                    "solarbeam": f"{attacker.pokemon.name} is absorbing sunlight!",
                    "skullbash": f"{attacker.pokemon.name} lowered its head!",
                    "skyattack": f"{attacker.pokemon.name} is glowing!",
                }
                action_log = charge_messages.get(move_data["id"], f"{attacker.pokemon.name} is charging up!")
            
            # --- END OF MODIFICATION ---

        else:
            # This is a normal 1-turn damaging move
            move_results = execute_move(attacker, defender, move_id, battle, base_move_id=base_move_id)

            if move_results.get("did_hit"):
                battle.last_successful_move = move_id

            if move_results.get("final_move_name"):
                # Don't create a log for locked moves, as that's handled earlier
                if not is_locked_turn:
                    action_log += f"\n{attacker.pokemon.name} used {move_results['final_move_name']}!"
            if move_results.get('update_image'):
                should_update_image = True
            if move_results.get("is_baton_pass"):
                # Copy boosts and specific volatiles to the battle state to be passed
                battle.baton_pass_data = {
                    "boosts": attacker.boosts.copy(),
                    "volatiles": {
                        k: v for k, v in attacker.volatiles.items() 
                        if k in ['substitute', 'focusenergy', 'leechseed', 'confusion']
                    }
                }
            attacker.last_move_used = move_id
            if not is_locked_turn:
                action_log = f"{attacker.pokemon.name} used {move_data['name']}!"

    # =================================================================
    # SHARED BLOCK TO APPLY MOVE RESULTS
    # =================================================================
    if move_results: # This block now safely handles ALL results from a damaging move
        if not move_results["did_hit"]:
            if move_results["log"]:
                action_log += move_results["log"]
            else:
                action_log += "\nBut it missed!"
            if move_data.get("hasCrashDamage"):
                crash_damage = attacker.actual_stats["hp"] // 2
                attacker.current_hp = max(0, attacker.current_hp - crash_damage)
                action_log += f"\n{attacker.pokemon.name} kept going and crashed! It lost {crash_damage} HP!"
        else:
            if 'lockedmove' in attacker.volatiles:
                attacker.volatiles['lockedmove']['turns'] -= 1
                
            damage = move_results["damage_dealt"]
            if damage > 0:
                defender.current_hp = max(0, defender.current_hp - damage)
                defender.last_damage_taken = damage
                defender.last_damage_category = move_data.get('category')
                defender.volatiles['last_hit_by_contact'] = move_data.get("flags", {}).get("contact", False)
            
            if move_results["log"]:
                action_log += move_results["log"]

            # This condition is now safe because we only enter this block for damaging moves
            if damage > 0:
                action_log += f"\nIt dealt {damage} damage!"
            elif move_data['category'] != 'Status': # Only show this for damaging moves
                action_log += "\nIt dealt no damage!"
            
            if move_results["hits"] > 1:
                action_log += f" (Hit {move_results['hits']} times!)"
                        
            eff = move_results["effectiveness"]
            if eff > 1: action_log += " It's super effective!"
            elif 0 < eff < 1: action_log += " It's not very effective..."
            elif eff == 0 and move_data['category'] != 'Status': action_log += " It had no effect!"

            if move_results["recoil_damage"] > 0:
                recoil = move_results["recoil_damage"]
                attacker.current_hp = max(0, attacker.current_hp - recoil)
                action_log += f"\n{attacker.pokemon.name} was hurt by recoil! It lost {recoil} HP!"

        berry_log_def = item_logic.apply_on_below_hp_threshold(defender, battle)
        if berry_log_def:
            action_log += berry_log_def
        
        # Check attacker's berry (in case they took recoil damage)
        if move_results["recoil_damage"] > 0:
            berry_log_atk = item_logic.apply_on_below_hp_threshold(attacker, battle)
            if berry_log_atk:
                action_log += berry_log_atk

        # --- BIDE DAMAGE TRACKING BLOCK ---
        if defender.volatiles.get('bide') and move_results.get("damage_dealt", 0) > 0:
            defender.volatiles['bide']['damage_taken'] += move_results["damage_dealt"]

        form_change_log_defender = await check_for_form_change(bot, battle, defender, event='on_after_move')
        if form_change_log_defender:
            action_log += f"\n{form_change_log_defender}"
            should_update_image = True # Force an image update to show the new form

        form_change_log_attacker = await check_for_form_change(bot, battle, attacker, event='on_after_move')
        if form_change_log_attacker:
            action_log += f"\n{form_change_log_attacker}"
            should_update_image = True

        if defender.current_hp <= 0 and defender.volatiles.get('destinybond'):
            # If so, the attacker also faints.
            if attacker.current_hp > 0:
                attacker.current_hp = 0
                action_log += f"\n{defender.pokemon.name} took {attacker.pokemon.name} down with it!"

        # --- FAINT AND SWITCH CHECKS (NOW SAFELY INSIDE) ---
        if defender.current_hp <= 0:
            if battle.log_for_faint:
                action_log += battle.log_for_faint
                battle.log_for_faint = ""
            action_log += f"\n{defender.pokemon.name} fainted!"
            if await handle_faint(bot, battle, opponent_player):
                # --- BATTLE IS OVER: CONSTRUCT AND SEND THE FINAL MESSAGE ---
                winner = battle.winner
                loser = opponent_player
                
                # ALWAYS fetch the latest scores from the DB for display
                final_winner_stats = db.get_user_stats(winner.user_id)
                final_loser_stats = db.get_user_stats(loser.user_id)
    
                if battle.is_ranked and final_winner_stats and final_loser_stats:
                    # For ranked, we need the "before" and "after" to show the change
                    new_winner_elo = final_winner_stats[0]
                    
                    # Reverse calculate old elo for display
                    winner_rating_change = calculate_elo_change(new_winner_elo, final_loser_stats[0], 1.0)
                    winner_old_elo = new_winner_elo - winner_rating_change
                    loser_old_elo = final_loser_stats[0] - calculate_elo_change(final_loser_stats[0], winner_old_elo, 0.0)
                    new_loser_elo = final_loser_stats[0]
    
                    final_caption = (
                        f"<code>{action_log.strip()}</code>\n\n"
                        f"🏆 <b>{winner.user_name} is the winner! (Ranked)</b>\n\n"
                        f"<code>{winner.user_name}: {winner_old_elo} -> {new_winner_elo} 🔺{winner_rating_change}</code>\n"
                        f"<code>{loser.user_name}: {loser_old_elo} -> {new_loser_elo} 🔻{abs(new_loser_elo - loser_old_elo)}</code>"
                    )
                    summary_image = await create_ranking_summary_image(winner.user_name, winner_old_elo, new_winner_elo)
                    if summary_image:
                        await bot.edit_message_media(
                            media=types.InputMediaPhoto(summary_image, caption=final_caption, parse_mode="HTML"),
                            chat_id=battle.chat_id, message_id=battle.message_id, reply_markup=None
                        )
                else: # Unranked match
                    winner_elo = final_winner_stats[0] if final_winner_stats else 'N/A'
                    loser_elo = final_loser_stats[0] if final_loser_stats else 'N/A'
                    final_caption = (
                        f"<code>{action_log.strip()}</code>\n\n"
                        f"🏆 <b>{winner.user_name} is the winner!</b> (Unranked)\n\n"
                        f"<b>Current Elo:</b>\n"
                        f"<code>{winner.user_name}: {winner_elo}</code>\n"
                        f"<code>{loser.user_name}: {loser_elo}</code>"
                    )
                    await update_battle_ui(bot, battle, final_caption, update_image=True)

                remove_battle(battle)
                battle.is_processing_turn = False
                return # --- STOP ALL FURTHER PROCESSING ---

        elif move_results.get("force_switch"):
            # If the move forces the user to switch (like Baton Pass or Parting Shot)
            await update_battle_ui(bot, battle, action_log, update_image=should_update_image)
            await asyncio.sleep(1) # Pause to let the user read the log
            
            battle.turn_phase = "awaiting_forced_switch"
            battle.active_player_id = player.user_id # The current player needs to switch
            await update_battle_ui(bot, battle, f"{attacker.pokemon.name} is coming back!")
            battle.is_processing_turn = False
            return

        if attacker.current_hp <= 0:
            if battle.log_for_faint:
                action_log += battle.log_for_faint
                battle.log_for_faint = ""
            action_log += f"\n{attacker.pokemon.name} fainted!"
            if await handle_faint(bot, battle, player):
                # --- BATTLE IS OVER: CONSTRUCT AND SEND THE FINAL MESSAGE ---
                winner = battle.winner
                loser = player
    
                # ALWAYS fetch the latest scores from the DB for display
                final_winner_stats = db.get_user_stats(winner.user_id)
                final_loser_stats = db.get_user_stats(loser.user_id)
    
                if battle.is_ranked and final_winner_stats and final_loser_stats:
                    new_winner_elo = final_winner_stats[0]
                    
                    winner_rating_change = calculate_elo_change(new_winner_elo, final_loser_stats[0], 1.0)
                    winner_old_elo = new_winner_elo - winner_rating_change
                    loser_old_elo = final_loser_stats[0] - calculate_elo_change(final_loser_stats[0], winner_old_elo, 0.0)
                    new_loser_elo = final_loser_stats[0]
    
                    final_caption = (
                        f"<code>{action_log.strip()}</code>\n\n"
                        f"🏆 <b>{winner.user_name} is the winner! (Ranked)</b>\n\n"
                        f"<code>{winner.user_name}: {winner_old_elo} -> {new_winner_elo} 🔺{winner_rating_change}</code>\n"
                        f"<code>{loser.user_name}: {loser_old_elo} -> {new_loser_elo} 🔻{abs(new_loser_elo - loser_old_elo)}</code>"
                    )
                    summary_image = await create_ranking_summary_image(winner.user_name, winner_old_elo, new_winner_elo)
                    if summary_image:
                        await bot.edit_message_media(
                            media=types.InputMediaPhoto(summary_image, caption=final_caption, parse_mode="HTML"),
                            chat_id=battle.chat_id, message_id=battle.message_id, reply_markup=None
                        )
                else: # Unranked match
                    winner_elo = final_winner_stats[0] if final_winner_stats else 'N/A'
                    loser_elo = final_loser_stats[0] if final_loser_stats else 'N/A'
                    final_caption = (
                        f"<code>{action_log.strip()}</code>\n\n"
                        f"🏆 <b>{winner.user_name} is the winner!</b> (Unranked)\n\n"
                        f"<b>Current Elo:</b>\n"
                        f"<code>{winner.user_name}: {winner_elo}</code>\n"
                        f"<code>{loser.user_name}: {loser_elo}</code>"
                    )
                    await update_battle_ui(bot, battle, final_caption, update_image=True)

                remove_battle(battle)
                battle.is_processing_turn = False
                return # --- STOP ALL FURTHER PROCESSING ---

        if move_results.get("force_opponent_switch"):
            can_switch = any(p.current_hp > 0 for p in opponent_player.team)
            if can_switch:
                await update_battle_ui(bot, battle, action_log)
                await asyncio.sleep(2.5)
                battle.turn_phase = 'awaiting_switch'
                battle.active_player_id = opponent_player.user_id
                await update_battle_ui(bot, battle, f"{defender.pokemon.name} was dragged out!")
                battle.is_processing_turn = False
                return
            else:
                action_log += "\nBut it failed!"

        if move_results.get("force_switch"):
            can_switch = any(p.current_hp > 0 and i != player.active_pokemon_index for i, p in enumerate(player.team))
            if can_switch:
                if move_results.get("is_baton_pass"):
                    battle.baton_pass_data = {
                        "boosts": attacker.boosts.copy(),
                        "volatiles": { k: v for k, v in attacker.volatiles.items() if k in ['substitute', 'focusenergy', 'leechseed', 'confusion'] }
                    }
                await update_battle_ui(bot, battle, action_log)
                await asyncio.sleep(2.5)
                battle.turn_phase = "awaiting_forced_switch"
                battle.active_player_id = player.user_id
                await update_battle_ui(bot, battle, "You must switch to a different Pokémon!")
                battle.is_processing_turn = False
                return
            else:
                action_log += "\nBut there was no one to switch to!"

    if 'dynamax' in attacker.volatiles:
        attacker.volatiles['dynamax']['turns'] -= 1
        if attacker.volatiles['dynamax']['turns'] <= 0:
            revert_dynamax(attacker)
            action_log += f"\n{attacker.pokemon.name} returned to its normal size!"
            should_update_image = True # Force image update on reversion

    # === FINAL, ROBUST FAINT & TURN-END LOGIC ===

    # 1. First, check for faints caused by the direct move action
    attacker_fainted = attacker.current_hp <= 0
    defender_fainted = defender.current_hp <= 0
    final_log = action_log

    # 2. Handle the outcome of these faints SEQUENTIALLY
    # The defender always faints "first" as a result of the move.
    if defender_fainted:
        final_log += f"\n{defender.pokemon.name} fainted!"
        # Check if this faint ends the game. If it does, handle_faint returns True.
        if await handle_faint(bot, battle, opponent_player):
            final_log += f"\n\n🏆 {battle.winner.user_name} is the winner!"
            await update_battle_ui(bot, battle, final_log)

            print(f"[DEBUG] Battle Finished in Chat {battle.chat_id}")
            print(f"[DEBUG] Current battles BEFORE deletion: {len(active_battles.get(battle.chat_id, []))}")
            for b in active_battles.get(battle.chat_id, []):
                 print(f" - Battle ID: {b.battle_id} (Players: {b.player1.user_name} vs {b.player2.user_name})")

            if battle.chat_id in active_battles:
                remove_battle(battle)

            print(f"[DEBUG] Current battles AFTER deletion: {len(active_battles.get(battle.chat_id, []))}")

            battle.is_processing_turn = False
            return # GAME OVER

    # Now, check if the attacker fainted from recoil or a move like Self-Destruct.
    # This happens "after" the defender faints.
    if attacker_fainted:
        final_log += f"\n{attacker.pokemon.name} fainted!"
        # Check if this faint ends the game.
        if await handle_faint(bot, battle, player):
            final_log += f"\n\n🏆 {battle.winner.user_name} is the winner!"
            await update_battle_ui(bot, battle, final_log)
            if battle.chat_id in active_battles:
                remove_battle(battle)
            battle.is_processing_turn = False
            return # GAME OVER

    # 3. If either Pokémon fainted but the game is NOT over, a switch is required.
    # The battle state will have been set to 'awaiting_switch' by handle_faint.
    if defender_fainted or attacker_fainted:
        await update_battle_ui(bot, battle, final_log, update_image=should_update_image)
        battle.is_processing_turn = False
        return # CRITICAL: Stop here and wait for the switch input.

    if battle.force_switch_flags:
        # Check if the defender (who was just hit) is the one that needs to switch
        if defender.pokemon.pokemon_uuid in battle.force_switch_flags:
            await update_battle_ui(bot, battle, action_log, update_image=should_update_image)
            await asyncio.sleep(2.5) # Pause to let user read the log

            battle.turn_phase = 'awaiting_forced_switch'
            battle.active_player_id = opponent_player.user_id # The defender's player
            await update_battle_ui(bot, battle, f"{defender.pokemon.name} must switch out!")
            
            battle.force_switch_flags.clear() # Clear the flag
            battle.is_processing_turn = False
            return # IMPORTANT: Stop the turn here and wait for the switch

    # 4. If no one fainted, proceed with the normal turn flow.
    is_turn_over = player.user_id == battle.turn_order[1][0].user_id

    if is_turn_over:
        # This was the second move, so the main action phase of the turn is over.
        # --- YOUR ORIGINAL END-OF-TURN LOGIC IS PRESERVED HERE ---
        delayed_effects_log, faint_from_delayed = await handle_delayed_effects(bot, battle)
        if delayed_effects_log:
            action_log += "\n" + delayed_effects_log

        if faint_from_delayed and battle.state == 'finished':
            # This logic is for when the battle ends due to a delayed move like Future Sight.
            winner = battle.winner
            loser = battle.player1 if winner.user_id == battle.player2.user_id else battle.player2
            final_winner_stats = db.get_user_stats(winner.user_id)
            final_loser_stats = db.get_user_stats(loser.user_id)
            if battle.is_ranked and final_winner_stats and final_loser_stats:
                new_winner_elo = final_winner_stats[0]
                winner_rating_change = calculate_elo_change(new_winner_elo, final_loser_stats[0], 1.0)
                winner_old_elo = new_winner_elo - winner_rating_change
                loser_old_elo = final_loser_stats[0] - calculate_elo_change(final_loser_stats[0], winner_old_elo, 0.0)
                new_loser_elo = final_loser_stats[0]
                final_caption = (
                    f"<b><i>{action_log.strip()}</i></b>\n\n"
                    f"🏆 <b>{winner.user_name} is the winner! (Ranked)</b>\n\n"
                    f"<code>{winner.user_name}: {winner_old_elo} -> {new_winner_elo} 🔺{winner_rating_change}</code>\n"
                    f"<code>{loser.user_name}: {loser_old_elo} -> {new_loser_elo} 🔻{abs(new_loser_elo - loser_old_elo)}</code>"
                )
                summary_image = await create_ranking_summary_image(winner.user_name, winner_old_elo, new_winner_elo)
                if summary_image:
                    await bot.edit_message_media(
                        media=types.InputMediaPhoto(summary_image, caption=final_caption, parse_mode="HTML"),
                        chat_id=battle.chat_id, message_id=battle.message_id, reply_markup=None
                    )
            else: # Unranked match
                winner_elo = final_winner_stats[0] if final_winner_stats else 'N/A'
                loser_elo = final_loser_stats[0] if final_loser_stats else 'N/A'
                final_caption = (
                    f"<b><i>{action_log.strip()}</i></b>\n\n"
                    f"🏆 <b>{winner.user_name} is the winner!</b> (Unranked)\n\n"
                    f"<b>Current Elo:</b>\n"
                    f"<code>{winner.user_name}: {winner_elo}</code>\n"
                    f"<code>{loser.user_name}: {loser_elo}</code>"
                )
                await update_battle_ui(bot, battle, final_caption, update_image=True)

            battle.is_processing_turn = False
            return
        elif faint_from_delayed:
            await update_battle_ui(bot, battle, action_log)
            battle.is_processing_turn = False
            return

        if battle.trick_room_turns > 0:
            battle.trick_room_turns -= 1
            if battle.trick_room_turns == 0:
                action_log += "\nThe twisted dimensions returned to normal."
        if battle.gravity_turns > 0:
            battle.gravity_turns -= 1
            if battle.gravity_turns == 0:
                action_log += "\nGravity returned to normal."
        if battle.wonder_room_turns > 0:
            battle.wonder_room_turns -= 1
            if battle.wonder_room_turns == 0:
                action_log += "\nThe bizarre area returned to normal."

        screen_fade_log_parts = []
        for screens, player_name in [(battle.player1_screens, battle.player1.user_name), (battle.player2_screens, battle.player2.user_name)]:
            for screen_type in list(screens.keys()):
                screens[screen_type] -= 1
                if screens[screen_type] <= 0:
                    del screens[screen_type]
                    screen_name = "Reflect" if screen_type == 'reflect' else "Light Screen"
                    screen_fade_log_parts.append(f"{player_name}'s {screen_name} wore off!")
        if screen_fade_log_parts:
            action_log += "\n" + "\n".join(screen_fade_log_parts)

        tailwind_fade_log_parts = []
        if battle.player1_tailwind_turns > 0:
            battle.player1_tailwind_turns -= 1
            if battle.player1_tailwind_turns == 0:
                tailwind_fade_log_parts.append(f"The tailwind behind {battle.player1.user_name}'s team died down.")
        if battle.player2_tailwind_turns > 0:
            battle.player2_tailwind_turns -= 1
            if battle.player2_tailwind_turns == 0:
                tailwind_fade_log_parts.append(f"The tailwind behind {battle.player2.user_name}'s team died down.")
        if tailwind_fade_log_parts:
            action_log += "\n" + "\n".join(tailwind_fade_log_parts)

        terrain_fade_log = terrain_logic.handle_terrain_end_of_turn(battle)
        if terrain_fade_log:
            action_log += "\n" + terrain_fade_log
            if not battle.active_terrain:
                should_update_image = True

        weather_log = weather_logic.handle_weather_end_of_turn(battle)
        if weather_log:
            action_log += "\n" + weather_log

        end_of_turn_log = await handle_end_of_turn_effects(battle)
        if end_of_turn_log:
            action_log += "\n" + end_of_turn_log

        for p in [attacker, defender]:
            # We only check if the pokemon is still active
            if p.current_hp > 0:
                form_change_log = await check_for_form_change(bot, battle, p, event='on_end_of_turn')
                if form_change_log:
                    action_log += f"\n{form_change_log}"
                    should_update_image = True

        slot_condition_log = await handle_slot_conditions(battle)
        if slot_condition_log:
            action_log += "\n" + slot_condition_log

        p1_fainted_after_effects = battle.player1.get_active_pokemon().current_hp <= 0
        p2_fainted_after_effects = battle.player2.get_active_pokemon().current_hp <= 0
        fainted_players = []
        if p1_fainted_after_effects: fainted_players.append(battle.player1)
        if p2_fainted_after_effects: fainted_players.append(battle.player2)

        for p in fainted_players:
            if battle.state == "active":
                action_log += f"\n{p.get_active_pokemon().pokemon.name} fainted!"
                if await handle_faint(bot, battle, p):
                    # --- BATTLE IS OVER: CONSTRUCT AND SEND THE FINAL MESSAGE ---
                    winner = battle.winner
                    loser = p # The player who fainted
                    
                    final_winner_stats = db.get_user_stats(winner.user_id)
                    final_loser_stats = db.get_user_stats(loser.user_id)

                    if battle.is_ranked and final_winner_stats and final_loser_stats:
                        new_winner_elo = final_winner_stats[0]
                        
                        winner_rating_change = calculate_elo_change(new_winner_elo, final_loser_stats[0], 1.0)
                        winner_old_elo = new_winner_elo - winner_rating_change
                        loser_old_elo = final_loser_stats[0] - calculate_elo_change(final_loser_stats[0], winner_old_elo, 0.0)
                        new_loser_elo = final_loser_stats[0]

                        final_caption = (
                            f"<b><i>{action_log.strip()}</i></b>\n\n"
                            f"🏆 <b>{winner.user_name} is the winner! (Ranked)</b>\n\n"
                            f"<code>{winner.user_name}: {winner_old_elo} -> {new_winner_elo} 🔺{winner_rating_change}</code>\n"
                            f"<code>{loser.user_name}: {loser_old_elo} -> {new_loser_elo} 🔻{abs(new_loser_elo - loser_old_elo)}</code>"
                        )
                        summary_image = await create_ranking_summary_image(winner.user_name, winner_old_elo, new_winner_elo)
                        if summary_image:
                            await bot.edit_message_media(
                                media=types.InputMediaPhoto(summary_image, caption=final_caption, parse_mode="HTML"),
                                chat_id=battle.chat_id, message_id=battle.message_id, reply_markup=None
                            )
                    else: # Unranked match
                        winner_elo = final_winner_stats[0] if final_winner_stats else 'N/A'
                        loser_elo = final_loser_stats[0] if final_loser_stats else 'N/A'
                        final_caption = (
                            f"<b><i>{action_log.strip()}</i></b>\n\n"
                            f"🏆 <b>{winner.user_name} is the winner!</b> (Unranked)\n\n"
                            f"<b>Current Elo:</b>\n"
                            f"<code>{winner.user_name}: {winner_elo}</code>\n"
                            f"<code>{loser.user_name}: {loser_elo}</code>"
                        )
                        await update_battle_ui(bot, battle, final_caption, update_image=True)

                    remove_battle(battle)
                    battle.is_processing_turn = False
                    return # --- STOP ALL FURTHER PROCESSING ---
                else: # A faint occurred but the battle is not over (player has other Pokemon)
                    await update_battle_ui(bot, battle, action_log)
                    battle.is_processing_turn = False
                    return

        # If we get here, the turn is truly over. Start the next one.
        await start_turn(bot, battle)
        final_log = f"{action_log}\n\n--- Turn {battle.turn} ---"
        await update_battle_ui(bot, battle, final_log, update_image=True)
    else:
        # This was the first move of the turn. Pass to the next player.
        battle.active_player_id = battle.turn_order[1][0].user_id
        battle.timer_task = asyncio.create_task(
            start_turn_timer(bot, battle, battle.active_player_id, battle.turn)
        )
        battle.primed_action = None
        await update_battle_ui(bot, battle, action_log, update_image=should_update_image)
    
    battle.is_processing_turn = False