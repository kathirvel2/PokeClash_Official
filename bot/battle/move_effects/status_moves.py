# In file: bot/battle/move_effects/status_moves.py

import random
import math
from typing import TYPE_CHECKING
from bot.battle.battle_engine import ActivePokemon
from bot.battle.field_effects import hazards as hazard_logic
from bot.battle.field_effects import weather as weather_logic
from bot.battle.field_effects import terrain as terrain_logic
from bot.mechanics.moves_loader import MOVE_BY_ID
from bot.mechanics.item_data import ITEM_ID_BY_NAME
from .status import apply_status
if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle

from bot.battle import ability_effects
from bot.battle.ability_effects import is_weather_suppressed

def handle_ability_move(attacker: ActivePokemon, defender: ActivePokemon, move_id: str) -> str:
    if move_id == 'skillswap':
        # Simple swap, more complex abilities might need more checks
        attacker_ability = attacker.pokemon.ability
        defender_ability = defender.pokemon.ability
        attacker.pokemon.ability = defender_ability
        defender.pokemon.ability = attacker_ability
        attacker.ability_is_swapped = True
        defender.ability_is_swapped = True
        return f"\n{attacker.pokemon.name} swapped its Ability with {defender.pokemon.name}!"
    elif move_id == 'entrainment':
        defender.pokemon.ability = attacker.pokemon.ability
        defender.ability_is_swapped = True
        return f"\n{defender.pokemon.name}'s Ability became {attacker.pokemon.ability}!"
    elif move_id == 'gastroacid':
        defender.volatiles['gastroacid'] = True
        return f"\n{defender.pokemon.name}'s Ability was suppressed!"
    return ""

def handle_stat_boost_move(target: ActivePokemon, move_data: dict) -> str:
    from bot.battle.battle_engine import active_battles
    
    boosts = move_data.get('boosts') or move_data.get('self', {}).get('boosts')
    if not boosts:
        return ""

    if any(value < 0 for value in boosts.values()):
        if target.pokemon.item == 'Clear Amulet':
            return f"\n{target.pokemon.name}'s Clear Amulet prevents its stats from being lowered!"

    ability_id = target.pokemon.ability.lower().replace(" ", "")
    ability_effect = ability_effects.ABILITY_EFFECTS.get(ability_id)
    if ability_effect and 'on_stat_lower' in ability_effect:
        is_protected, reason = ability_effect['on_stat_lower'](target, boosts)
        if is_protected:
            return reason

    log_parts = []
    stat_names = {
        'atk': 'Attack', 'def': 'Defense', 'spa': 'Sp. Atk',
        'spd': 'Sp. Def', 'spe': 'Speed','accuracy': 'accuracy',
        'evasion': 'evasiveness'
    }

    for stat, value in boosts.items():
        ability_id_contrary = target.pokemon.ability.lower().replace(" ", "")
        if ability_id_contrary == 'contrary':
            value *= -1

        ability_id_simple = target.pokemon.ability.lower().replace(" ", "")
        if ability_id_simple == 'simple':
            value *= 2
            
        if target.boosts[stat] == 6 and value > 0:
            log_parts.append(f"\n{target.pokemon.name}'s {stat_names[stat]} won't go any higher!")
            continue
        if target.boosts[stat] == -6 and value < 0:
            log_parts.append(f"\n{target.pokemon.name}'s {stat_names[stat]} won't go any lower!")
            continue

        target.boosts[stat] = max(-6, min(6, target.boosts[stat] + value))
        
        if value == 1: log_parts.append(f"{target.pokemon.name}'s {stat_names[stat]} rose!")
        elif value == 2: log_parts.append(f"{target.pokemon.name}'s {stat_names[stat]} sharply rose!")
        elif value >= 3: log_parts.append(f"{target.pokemon.name}'s {stat_names[stat]} drastically rose!")
        elif value == -1: log_parts.append(f"{target.pokemon.name}'s {stat_names[stat]} fell!")
        elif value == -2: log_parts.append(f"{target.pokemon.name}'s {stat_names[stat]} harshly fell!")
        elif value <= -3: log_parts.append(f"{target.pokemon.name}'s {stat_names[stat]} severely fell!")

        # --- THIS IS THE CORRECTED BATTLE LOOKUP ---
        battle = None
        for chat_battles in active_battles.values():
            for b in chat_battles:
                if target in b.player1.team or target in b.player2.team:
                    battle = b
                    break
            if battle:
                break
        # --- END OF CORRECTION ---

        if value < 0:
            if battle:
                log_parts.append(ability_effects.trigger_on_stat_lowered(target, battle))

    # --- THIS IS ALSO A CORRECTED BATTLE LOOKUP ---
    battle = None
    for chat_battles in active_battles.values():
        for b in chat_battles:
            if target in b.player1.team or target in b.player2.team:
                battle = b
                break
        if battle:
            break
    # --- END OF CORRECTION ---
            
    if battle and any(v > 0 for v in boosts.values()):
        target_player = battle.player1 if target in battle.player1.team else battle.player2
        opponent_player, opponent_pokemon = battle.get_opponent_for_player(target_player)

        if opponent_pokemon:
            log_parts.append(ability_effects.trigger_on_opponent_stat_boost(opponent_pokemon, target, boosts, battle))
            
    return "\n".join(filter(None, log_parts))

def handle_strength_sap(attacker: ActivePokemon, defender: ActivePokemon, battle: "Battle") -> str:
    """Heals user by the target's Attack stat and lowers the target's Attack by 1."""
    from bot.battle.battle_logic import get_modified_stat
    
    # Get the defender's current, in-battle Attack stat
    defender_attack_stat = get_modified_stat(defender, 'atk')
    
    # Heal the attacker, capped at their max HP
    heal_amount = defender_attack_stat
    attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + heal_amount)
    
    log = f"\n{attacker.pokemon.name} sapped {defender.pokemon.name}'s strength and restored its HP!"
    
    # Lower the defender's Attack by 1 stage
    stat_changes = {'boosts': {'atk': -1}}
    log += "\n" + handle_stat_boost_move(defender, stat_changes)
    
    return log

def handle_status_move(attacker: ActivePokemon, defender: ActivePokemon, move_data: dict, battle: "Battle") -> str:
    """
    Handles all logic for moves with category "Status".
    """
    from bot.mechanics.moves_loader import MOVE_BY_ID
    from bot.battle import ability_effects
    from bot.battle.battle_engine import active_battles
    log = ""
    move_id = move_data.get('id')

    if move_id == 'strengthsap':
        return handle_strength_sap(attacker, defender, battle)

    if move_id == 'bellydrum':
        # Check fail conditions
        hp_cost = attacker.actual_stats['hp'] // 2
        if attacker.current_hp <= hp_cost:
            return "\nBut it failed! (Not enough HP)"
        if attacker.boosts['atk'] >= 6:
            return "\nBut it failed! (Attack already maximized)"

        # Apply effects
        attacker.current_hp -= hp_cost
        boost_change = 6 - attacker.boosts['atk'] # Calculate the actual change
        attacker.boosts['atk'] = 6

        # --- THIS IS THE CORRECT FIX ---
        # 1. Determine which player object belongs to the attacker.
        attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2

        # 2. Get the opponent using the attacker's BattlePlayer object.
        opponent_player, opponent_pokemon = battle.get_opponent_for_player(attacker_player)

        # 3. Trigger Opportunist check if the opponent exists.
        if opponent_pokemon:
            log += ability_effects.trigger_on_opponent_stat_boost(opponent_pokemon, attacker, {'atk': boost_change}, battle)
        # --- END OF CORRECT FIX ---

        return f"\n{attacker.pokemon.name} cut its HP and maximized its Attack!" + log

    elif move_id == 'filletaway':
        # Calculate the HP cost (50% of max HP)
        hp_cost = attacker.actual_stats['hp'] // 2

        # Fail if the user doesn't have enough HP or if stats are already maxed
        if attacker.current_hp <= hp_cost:
            return "\nBut it failed! (Not enough HP)"
        if attacker.boosts['atk'] >= 6 and attacker.boosts['spa'] >= 6 and attacker.boosts['spe'] >= 6:
            return "\nBut it failed! (Stats are already maximized)"

        # Apply the effects
        attacker.current_hp -= hp_cost
        boost_data = {'boosts': {'atk': 2, 'spa': 2, 'spe': 2}}
        
        log = f"\n{attacker.pokemon.name} cut its own HP to sharpen its focus!"
        log += "\n" + handle_stat_boost_move(attacker, boost_data)
        
        return log

    elif move_id == 'noretreat':
        # Fails if the user is already trapped by No Retreat
        if 'noretreat' in attacker.volatiles:
            return "\nBut it failed!"
            
        attacker.volatiles['noretreat'] = True
        attacker.volatiles['trap'] = {
            'duration': 999, 
            'source_move': 'noretreat'
        }
        
        log += f"\n{attacker.pokemon.name} can no longer escape!"
        boost_data = {'boosts': {'atk': 1, 'def': 1, 'spa': 1, 'spd': 1, 'spe': 1}}
        log += "\n" + handle_stat_boost_move(attacker, boost_data)
        
        return log

    volatile_status = move_data.get('volatileStatus')

    if volatile_status:
        # We need a new trigger function for this hook
        is_immune, reason = ability_effects.trigger_on_volatile_status_infliction(volatile_status, defender, attacker)
        if is_immune:
            return reason

    if volatile_status in ['confusion', 'infatuation']:
        ability_id = defender.pokemon.ability.lower().replace(" ", "")
        ability_effect = ability_effects.ABILITY_EFFECTS.get(ability_id)
        if ability_effect and 'on_volatile_status_infliction' in ability_effect:
            # The handler for Oblivious needs the attacker, so we pass it
            is_immune, reason = ability_effect['on_volatile_status_infliction'](volatile_status, defender, attacker)
            if is_immune:
                return reason

    if move_id == 'rest':
        # Fail if HP is full and user has no status to cure
        if attacker.current_hp >= attacker.actual_stats['hp'] and attacker.status is None:
            return "\nBut it failed!"
        
        attacker.current_hp = attacker.actual_stats['hp']
        attacker.status = 'slp'
        attacker.status_counter = 2  # Rest sleep always lasts for 2 turns of not moving
        if 'confusion' in attacker.volatiles:
            del attacker.volatiles['confusion']
        
        return f"\n{attacker.pokemon.name} went to sleep and became healthy!"
        
    elif move_id == 'sleeptalk':
        # The main logic is now correctly handled in the turn handler.
        # This part of the code is only reached if the user is AWAKE, so the move must fail.
        return "\nBut it failed!"
    
    elif move_id == 'perishsong':
        log_parts = []
        # Apply the perish count to all active Pokemon that don't already have it
        for p in [attacker, defender]:
            if 'perishsong' not in p.volatiles:
                p.volatiles['perishsong'] = 4 # Counter starts at 4 (faints when it hits 0)
                log_parts.append(p.pokemon.name)

        if not log_parts:
            return "\nBut it failed!"
        
        return "\nAll Pokémon hearing the song will faint in 3 turns!"

    # --- END OF NEW BLOCK ---

    elif move_id in ['healingwish', 'lunardance']:
        # Get the player object for the user of the move.
        player = battle.get_player(attacker.pokemon.pokemon_uuid)
        if not player: # Failsafe
            player = battle.player1 if attacker in battle.player1.team else battle.player2
            
        # --- NEW CHECK ---
        # The move should fail if the user is the last conscious Pokémon on the team,
        # as there would be no one to switch in and receive the healing wish.
        can_heal_someone = any(p.current_hp > 0 for p in player.team if p.pokemon.pokemon_uuid != attacker.pokemon.pokemon_uuid)
        if not can_heal_someone:
            return "\nBut it failed!"
        # --- END OF NEW CHECK ---

        # The user must faint to trigger the effect.
        attacker.current_hp = 0
        
        # Set the flag on that player's side of the field.
        player.slot_conditions['healing_wish'] = True
        
        return f"\n{attacker.pokemon.name} used {move_data['name']}!"

    elif move_data.get('heal'):
        # Fail if HP is already full
        if attacker.current_hp >= attacker.actual_stats['hp']:
            return "\nBut it failed!"
        
        heal_fraction = move_data['heal'][0] / move_data['heal'][1]

        # Weather-dependent healing for specific moves
        if move_id in ['morningsun', 'synthesis', 'moonlight']:
            if battle.active_weather in ['sunnyday', 'desolateland']:
                heal_fraction = 2 / 3
            elif battle.active_weather in ['raindance', 'primordialsea', 'sandstorm', 'hail']:
                heal_fraction = 1 / 4
        
        heal_amount = math.floor(attacker.actual_stats['hp'] * heal_fraction)
        attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + heal_amount)

        # Special case for Roost: grounds the user for the turn
        if move_id == 'roost':
            attacker.volatiles['roost'] = True
            log += f"\n{attacker.pokemon.name} landed and restored its HP!"
        else:
            log += f"\n{attacker.pokemon.name} restored its HP!"
        
        return log

    elif move_id == 'shoreup':
        # Fail if HP is already full
        if attacker.current_hp >= attacker.actual_stats['hp']:
            return "\nBut it failed!"
    
        heal_fraction = 1/2 # Default heal amount
    
        # Check if sandstorm is active and not suppressed by an ability
        if battle.active_weather == 'sandstorm' and not is_weather_suppressed(battle):
            heal_fraction = 2/3 # Boosted heal amount in sandstorm
    
        heal_amount = math.floor(attacker.actual_stats['hp'] * heal_fraction)
        attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + heal_amount)
    
        log += f"\n{attacker.pokemon.name} restored its HP!"
        return log

    elif move_id == 'purify':
        # Fail if the target has no status condition
        if defender.status is None:
            return "\nBut it failed!"
        
        # Cure the defender's status
        defender.status = None
        defender.status_counter = 0
        log += f"\n{defender.pokemon.name}'s status was cured!"
        
        # Heal the user by 50% of their max HP
        heal_amount = attacker.actual_stats['hp'] // 2
        attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + heal_amount)
        log += f"\n{attacker.pokemon.name} restored its own HP!"
        
        return log

    elif move_id == 'floralhealing':
        # Fail if the target is already at full HP
        if defender.current_hp >= defender.actual_stats['hp']:
            return "\nBut it failed!"

        heal_fraction = 1/2 # Default is 50%
        
        # If Grassy Terrain is active, the heal is boosted to 2/3
        if battle.active_terrain == 'grassyterrain':
            heal_fraction = 2/3
        
        heal_amount = math.floor(defender.actual_stats['hp'] * heal_fraction)
        defender.current_hp = min(defender.actual_stats['hp'], defender.current_hp + heal_amount)
        
        log += f"\n{defender.pokemon.name}'s HP was restored!"
        return log

    elif move_id == 'junglehealing':
        # In a 1v1 context, this affects only the user.
        # The move fails if the user is at full HP and has no status condition.
        if attacker.current_hp >= attacker.actual_stats['hp'] and attacker.status is None:
            return "\nBut it failed!"

        log = ""
        
        # Heal HP if not full
        if attacker.current_hp < attacker.actual_stats['hp']:
            heal_amount = attacker.actual_stats['hp'] // 4
            attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + heal_amount)
            log += f"\n{attacker.pokemon.name}'s HP was restored."
        
        # Cure status if afflicted
        if attacker.status is not None:
            attacker.status = None
            attacker.status_counter = 0
            log += f"\n{attacker.pokemon.name}'s status was cured."
            
        return log

    elif move_id in ['trick', 'switcheroo']:
        # Define a list of unswappable items
        unswappable_items = ['redorb', 'blueorb', 'griseousorb'] # Can be expanded

        attacker_item_id = ITEM_ID_BY_NAME.get(attacker.pokemon.item, "").lower()
        defender_item_id = ITEM_ID_BY_NAME.get(defender.pokemon.item, "").lower()

        # Fail conditions
        if (not attacker.pokemon.item and not defender.pokemon.item) or \
           (attacker_item_id in unswappable_items) or \
           (defender_item_id in unswappable_items):
            return "\nBut it failed!"
        
        # Swap items
        attacker.pokemon.item, defender.pokemon.item = defender.pokemon.item, attacker.pokemon.item

        log = f"\n{attacker.pokemon.name} swapped items with {defender.pokemon.name}!"
        if attacker.pokemon.item:
            log += f"\n{attacker.pokemon.name} obtained a {attacker.pokemon.item}."
        else:
             log += f"\n{attacker.pokemon.name} no longer has an item."
        if defender.pokemon.item:
            log += f"\n{defender.pokemon.name} obtained a {defender.pokemon.item}."
        else:
             log += f"\n{defender.pokemon.name} no longer has an item."

        return log

    elif move_data.get('sideCondition'):
        # This will now handle Stealth Rock, Spikes, Reflect, Light Screen, etc.
        player = battle.player1 if attacker in battle.player1.team else battle.player2
        return hazard_logic.set_hazard(battle, player, move_data['sideCondition'])

    volatile_status = move_data.get('volatileStatus')

    if volatile_status == 'infatuation':
        # Check for immunities first
        if 'infatuation' in defender.volatiles:
            return "\nBut it failed!"
            
        attacker_gender = SPECIES_BY_ID.get(attacker.pokemon.id, {}).get('gender')
        defender_gender = SPECIES_BY_ID.get(defender.pokemon.id, {}).get('gender')
        
        # Fails if either Pokémon is genderless, or if they are the same gender
        if not attacker_gender or not defender_gender or attacker_gender == defender_gender:
            return "\nBut it failed!"

        # Your Oblivious check will be handled by the on_volatile_status_infliction hook you already built.
        # So we just need to apply the status here.
        defender.volatiles['infatuation'] = True
        return f"\n{defender.pokemon.name} fell in love with {attacker.pokemon.name}!"

    elif volatile_status == 'encore':
        last_move = defender.last_move_used
        if not last_move or 'encore' in defender.volatiles:
            return "\nBut it failed!"
        defender.volatiles['encore'] = {'turns': 3, 'move_id': last_move}
        return f"\n{defender.pokemon.name} received an encore!"

    elif volatile_status == 'disable':
        last_move = defender.last_move_used
        if not last_move or 'disable' in defender.volatiles:
            return "\nBut it failed!"
        defender.volatiles['disable'] = {'turns': 4, 'move_id': last_move}
        move_name = MOVE_BY_ID.get(last_move, {}).get('name', 'the last move')
        return f"\n{defender.pokemon.name}'s {move_name} was disabled!"

    elif volatile_status == 'torment':
        if 'torment' in defender.volatiles:
            return "\nBut it failed!"
        defender.volatiles['torment'] = True
        return f"\n{defender.pokemon.name} was subjected to torment!"

    elif move_id == 'haze':
        # Reset boosts for the attacker
        attacker.boosts = {
            'atk': 0, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 0,
            'accuracy': 0, 'evasion': 0
        }
        # Reset boosts for the defender
        defender.boosts = {
            'atk': 0, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 0,
            'accuracy': 0, 'evasion': 0
        }
        log += "\nAll stat changes were reset!"

    elif move_id == 'yawn':
        # Check for immunities
        if 'yawn' in defender.volatiles or defender.status is not None:
            return "\nBut it failed!"
        
        # Check terrain immunity
        if terrain_logic.is_protected_by_terrain(defender.pokemon, battle):
             return f"\n{defender.pokemon.name} is protected by the Misty Terrain!"
        
        # Check ability immunity (e.g., Comatose, Insomnia)
        ability_id = defender.pokemon.ability.lower().replace(" ", "")
        if ability_id in ['insomnia', 'vitalspirit', 'comatose', 'sweetveil']:
            return f"\nIt doesn't affect {defender.pokemon.name}..."

        # Apply the volatile
        defender.volatiles['yawn'] = 2 # 2 = "will fall asleep at end of next turn"
        log += f"\n{defender.pokemon.name} grew drowsy!"

    if move_id == 'tailwind':
        player = battle.player1 if attacker in battle.player1.team else battle.player2
        
        # Check if tailwind is already active for the player
        if player.user_id == battle.player1.user_id and battle.player1_tailwind_turns > 0:
            return "\nBut it failed!"
        if player.user_id == battle.player2.user_id and battle.player2_tailwind_turns > 0:
            return "\nBut it failed!"

        # Set tailwind for 4 turns
        if player.user_id == battle.player1.user_id:
            battle.player1_tailwind_turns = 4
        else:
            battle.player2_tailwind_turns = 4
            
        return f"\nThe wind picked up behind {player.user_name}'s team!"

    elif move_id == 'powerswap':
        # Swap Attack boosts
        attacker.boosts['atk'], defender.boosts['atk'] = defender.boosts['atk'], attacker.boosts['atk']
        # Swap Special Attack boosts
        attacker.boosts['spa'], defender.boosts['spa'] = defender.boosts['spa'], attacker.boosts['spa']
        
        log += f"\n{attacker.pokemon.name} swapped its Attack and Sp. Atk changes with the target!"
        return log

    elif move_id == 'guardswap':
        # Swap Defense boosts
        attacker.boosts['def'], defender.boosts['def'] = defender.boosts['def'], attacker.boosts['def']
        # Swap Special Defense boosts
        attacker.boosts['spd'], defender.boosts['spd'] = defender.boosts['spd'], attacker.boosts['spd']

        log += f"\n{attacker.pokemon.name} swapped its Defense and Sp. Def changes with the target!"
        return log

    elif move_id == 'psychup':
        attacker.boosts = defender.boosts.copy()
        log += f"\n{attacker.pokemon.name} copied {defender.pokemon.name}'s stat changes!"
        return log

    elif move_id == 'topsyturvy':
        # Check if there are any stat changes to invert
        if all(value == 0 for value in defender.boosts.values()):
            return "\nBut it failed!"

        for stat, value in defender.boosts.items():
            defender.boosts[stat] = -value
        
        log += f"\n{defender.pokemon.name}'s stat changes were inverted!"
        return log

    elif move_id == 'powertrick':
        # Swap the actual Attack and Defense stats
        attacker.actual_stats['atk'], attacker.actual_stats['def'] = attacker.actual_stats['def'], attacker.actual_stats['atk']
        
        # Toggle the volatile status to track the effect, so it can be swapped back
        if 'powertrick' in attacker.volatiles:
            del attacker.volatiles['powertrick']
            log += f"\n{attacker.pokemon.name} swapped its Attack and Defense stats back!"
        else:
            attacker.volatiles['powertrick'] = True
            log += f"\n{attacker.pokemon.name} swapped its Attack and Defense stats!"
        return log

    elif move_id == 'acupressure':
        # For 1v1, Acupressure targets the user.
        target = attacker

        # Find all stats that are not already maxed out at +6
        possible_stats = [stat for stat, value in target.boosts.items() if value < 6]
        
        if not possible_stats:
            return "\nBut it failed!"

        # Choose a random stat and boost it by 2
        stat_to_boost = random.choice(possible_stats)
        target.boosts[stat_to_boost] = min(6, target.boosts[stat_to_boost] + 2)

        stat_names = {
            'atk': 'Attack', 'def': 'Defense', 'spa': 'Sp. Atk', 
            'spd': 'Sp. Def', 'spe': 'Speed', 'accuracy': 'accuracy', 'evasion': 'evasiveness'
        }
        log += f"\n{target.pokemon.name}'s {stat_names.get(stat_to_boost, stat_to_boost)} sharply rose!"
        return log

    # --- NEW: Handle Substitute ---
    if move_id == 'substitute':
        # Fail if the user already has a substitute
        if 'substitute' in attacker.volatiles:
            return "\nBut it failed!"
            
        # Calculate the HP cost (25% of max HP)
        cost = attacker.actual_stats['hp'] // 4
        
        # Fail if the user doesn't have enough HP
        if attacker.current_hp <= cost:
            return "\nBut it failed!"
            
        # Deduct HP and create the substitute
        attacker.current_hp -= cost
        attacker.volatiles['substitute'] = {'hp': cost}
        
        return f"\n{attacker.pokemon.name} created a substitute!"
    # --- END OF NEW LOGIC ---
    
    # --- NEW --- Handle ability moves
    if move_id in ['skillswap', 'entrainment', 'gastroacid']:
        return handle_ability_move(attacker, defender, move_id)

    # --- NEW --- Handle Wish
    if move_id == 'wish':
        player = battle.get_player(attacker.pokemon.pokemon_uuid)
        if not player: 
            player = battle.player1 if attacker in battle.player1.team else battle.player2

        player.slot_conditions['wish'] = {
            'turns_left': 2,
            'hp_to_restore': attacker.actual_stats['hp'] // 2
        }
        return f"\n{attacker.pokemon.name} made a wish!"

    # --- NEW --- Handle Destiny Bond, Grudge, Bide
    if move_id == 'destinybond':
        attacker.volatiles['destinybond'] = True
        return f"\n{attacker.pokemon.name} is hoping to take its foe down with it!"
    if move_id == 'grudge':
        attacker.volatiles['grudge'] = True
        return f"\n{attacker.pokemon.name} is holding a grudge!"
    if move_id == 'bide':
        attacker.volatiles['bide'] = {'turns': random.randint(2,3), 'damage_taken': 0}
        # --- NEW --- Lock the move so the user can't do anything else
        attacker.volatiles['lockedmove'] = {'move_id': 'bide', 'turns': 99} 
        return f"\n{attacker.pokemon.name} is storing energy!"

    if move_id == 'trickroom':
        if battle.trick_room_turns > 0:
            battle.trick_room_turns = 0
            return "\nThe twisted dimensions returned to normal."
        else:
            battle.trick_room_turns = 5
            return f"\n{attacker.pokemon.name} twisted the dimensions!"

    elif move_id == 'painsplit':
        # Pain Split fails if it hits a substitute
        if 'substitute' in defender.volatiles:
            return "\nBut it failed!"
            
        # Calculate the average HP
        total_hp = attacker.current_hp + defender.current_hp
        avg_hp = total_hp // 2

        # Set each Pokémon's HP to the average, but not more than their max HP
        attacker.current_hp = min(avg_hp, attacker.actual_stats['hp'])
        defender.current_hp = min(avg_hp, defender.actual_stats['hp'])
        
        return "\nThe two Pokémon shared their pain!"

    elif move_id == 'spite':
        last_move_id = defender.last_move_used
        
        # Fail if the opponent hasn't moved yet or the move has no PP
        if not last_move_id or defender.move_pp.get(last_move_id, 0) == 0:
            return "\nBut it failed!"
        
        reduction = 4
        defender.move_pp[last_move_id] = max(0, defender.move_pp[last_move_id] - reduction)
        last_move_name = MOVE_BY_ID[last_move_id]['name']
        
        return f"\nIt reduced the PP of {last_move_name} by {reduction}!"

    elif move_id == 'gravity':
        if battle.gravity_turns > 0:
            return "\nBut it failed!"
        
        battle.gravity_turns = 5
        return "\nGravity intensified!"

    elif move_id == 'wonderroom':
        if battle.wonder_room_turns > 0:
            battle.wonder_room_turns = 0
            return "\nThe bizarre area returned to normal."
        else:
            battle.wonder_room_turns = 5
            return "\nIt created a bizarre area!"

    elif move_id == 'curse':
        if 'Ghost' in attacker.pokemon.types:
            # Ghost-type effect: Curse the opponent
            if 'curse' in defender.volatiles:
                return "\nBut it failed!"
            
            hp_cost = attacker.actual_stats['hp'] // 2
            if attacker.current_hp <= hp_cost:
                return "\nBut it failed!"
            
            attacker.current_hp -= hp_cost
            defender.volatiles['curse'] = True
            return f"\n{attacker.pokemon.name} cut its own HP and laid a curse on {defender.pokemon.name}!"
        else:
            # Non-Ghost-type effect: Stat changes
            # Lower Speed by 1, Raise Attack by 1, Raise Defense by 1
            stat_changes = {'boosts': {'spe': -1, 'atk': 1, 'def': 1}}
            log += handle_stat_boost_move(attacker, stat_changes)
            return log

    elif move_id == 'conversion':
        if not attacker.pokemon.moves:
            return "\nBut it failed!"
            
        # Get the type of the first move in the moveset
        first_move_id = attacker.pokemon.moves[0]
        first_move_type = MOVE_BY_ID[first_move_id]['type']
        
        # Fail if the user is already that single type
        if attacker.pokemon.types == [first_move_type]:
            return "\nBut it failed!"
            
        attacker.pokemon.types = [first_move_type]
        return f"\n{attacker.pokemon.name} transformed into the {first_move_type} type!"

    if move_data.get('id') in ['block', 'meanlook', 'spiderweb']:
        if 'trap' in defender.volatiles:
            return "\nBut it failed!"
        
        # Traps like these last until the user switches out.
        defender.volatiles['trap'] = {
            'duration': 999, 
            'source_move': move_id
        }
        return f"\n{defender.pokemon.name} can no longer escape!"

    if move_data.get('id') == 'defog':
        # Clear hazards from both sides
        battle.player1_hazards.clear()
        battle.player2_hazards.clear()
        
        # Clear screens from both sides
        battle.player1_screens.clear()
        battle.player2_screens.clear()
        
        # Clear terrain
        battle.active_terrain = None
        battle.active_terrain_turns = 0
        
        log += "\nThe fog cleared the field of hazards and screens!"
        
        # Lower opponent's evasion
        temp_move_data = {'boosts': {'evasion': -1}}
        log += "\n" + handle_stat_boost_move(defender, temp_move_data)
        return log

    if move_data.get('id') in ['aromatherapy', 'healbell']:
        player = battle.get_player(attacker.pokemon.pokemon_uuid)
        if not player: # Failsafe, should not happen
             player = battle.player1 if attacker in battle.player1.team else battle.player2

        for p in player.team:
            p.status = None
            p.status_counter = 0
        return f"\nA wave of soothing aroma wafted through {player.user_name}'s team!"
    # --- END OF NEW LOGIC ---

    if move_data.get('volatileStatus') in ['protect', 'maxguard', 'banefulbunker']:
        success_chance = 100 / (2 ** attacker.consecutive_protect_successes)
        
        if random.randint(1, 100) > success_chance:
            attacker.consecutive_protect_successes = 0
            log += "\nBut it failed!"
        else:
            attacker.is_protected = True
            # Add the specific volatile for Baneful Bunker
            if move_data.get('id') == 'banefulbunker':
                attacker.volatiles['banefulbunker'] = True
            attacker.consecutive_protect_successes += 1
            log += f"\n{attacker.pokemon.name} protected itself!"
        return log
        
    elif move_data.get('weather'):
        weather_type = move_data['weather']
        log += weather_logic.set_weather(battle, weather_type, attacker)
        return log

    elif move_data.get('terrain'):
        terrain_type = move_data['terrain']
        # Fail if the specified terrain is already active
        if battle.active_terrain == terrain_type:
            return "\nBut it failed!"
        
        # Call the helper function to set the terrain for 5 turns
        log += terrain_logic.set_terrain(battle, terrain_type, 5)
        return log

    if move_data.get('status'):
        log += apply_status(move_data['status'], defender, move_data, battle)

    elif move_data.get('volatileStatus') == 'confusion':
        # ... (confusion logic is unchanged) ...
        if 'confusion' not in defender.volatiles:
            defender.volatiles['confusion'] = random.randint(1, 4)
            log += f"\n{defender.pokemon.name} became confused!"
        else:
            log += "\nBut it failed!"

    elif move_data.get('volatileStatus') == 'leechseed':
        # ... (leech seed logic is unchanged) ...
        if 'Grass' in defender.pokemon.types or 'leechseed' in defender.volatiles:
            return "\nBut it failed!"
        else:
            defender.volatiles['leechseed'] = True
            return f"\n{defender.pokemon.name} was seeded!"

    elif move_data.get('volatileStatus') == 'taunt':
        if 'taunt' in defender.volatiles:
            return "\nBut it failed!"
        else:
            defender.volatiles['taunt'] = 3 # Set the taunt duration to 3 turns
            return f"\n{defender.pokemon.name} fell for the taunt!"

    if move_data.get('target') in ['self', 'allySide', 'allAdjacent']:
        log += handle_stat_boost_move(attacker, move_data)
    else:
        log += handle_stat_boost_move(defender, move_data)

    return log

def handle_flinch_move(defender: ActivePokemon, move_data: dict) -> str:
    """
    Handles the secondary effect of flinching. Checks for immunity and applies the volatile.
    NOTE: The chance check is now expected to be done *before* calling this function.
    """
    from bot.battle import ability_effects

    # Check for immunities like Inner Focus
    is_immune, reason = ability_effects.trigger_on_volatile_status_infliction('flinch', defender, None)
    
    if is_immune:
        # If the Pokémon is immune, return the reason why.
        return reason
    else:
        # If not immune, apply the flinch status.
        defender.volatiles['flinch'] = True
        # Do not return a log message here; the flinch message appears when the Pokemon tries to move.
        return ""