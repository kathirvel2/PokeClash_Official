# File: ./bot/battle/battle_logic.py
import random
from bot.battle.battle_engine import Battle, ActivePokemon, BattlePlayer
from bot.mechanics.moves_loader import MOVE_BY_ID
from bot.battle.move_effects.status_moves import handle_status_move, handle_stat_boost_move, handle_flinch_move
import math
from typing import TYPE_CHECKING
from bot.battle.field_effects import terrain as terrain_logic
from bot.battle.item_effects import item_logic
from bot.mechanics.item_data import ITEM_ID_BY_NAME
from bot.battle.ability_effects import get_stab_multiplier, trigger_on_modify_move
from bot.battle.ability_effects import is_weather_suppressed
from bot.battle import ability_effects
from bot.battle.battle_engine import active_battles
from bot.battle.ability_effects.form_change_logic import check_for_form_change
if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle

from .z_move_data import get_z_move_details, SIGNATURE_Z_MOVES
NO_COPY_MOVES = {
    move_id for move_id, move_data in MOVE_BY_ID.items()
    if move_data.get("noCopy", False) or move_data.get("isZ") or move_data.get("isMax")
}
NO_COPY_MOVES.add('struggle') # Struggle is a special case not flagged in the data

# --- (This section is unchanged) ---
TYPE_CHART = {
    'normal': {'rock': 0.5, 'ghost': 0, 'steel': 0.5},
    'fire': {'fire': 0.5, 'water': 0.5, 'grass': 2, 'ice': 2, 'bug': 2, 'rock': 0.5, 'dragon': 0.5, 'steel': 2},
    'water': {'fire': 2, 'water': 0.5, 'grass': 0.5, 'ground': 2, 'rock': 2, 'dragon': 0.5},
    'electric': {'water': 2, 'electric': 0.5, 'grass': 0.5, 'ground': 0, 'flying': 2, 'dragon': 0.5},
    'grass': {'fire': 0.5, 'water': 2, 'grass': 0.5, 'poison': 0.5, 'ground': 2, 'flying': 0.5, 'bug': 0.5, 'rock': 2, 'dragon': 0.5, 'steel': 0.5},
    'ice': {'fire': 0.5, 'water': 0.5, 'grass': 2, 'ice': 0.5, 'ground': 2, 'flying': 2, 'dragon': 2, 'steel': 0.5},
    'fighting': {'normal': 2, 'ice': 2, 'poison': 0.5, 'flying': 0.5, 'psychic': 0.5, 'bug': 0.5, 'rock': 2, 'ghost': 0, 'dark': 2, 'steel': 2, 'fairy': 0.5},
    'poison': {'grass': 2, 'poison': 0.5, 'ground': 0.5, 'rock': 0.5, 'ghost': 0.5, 'steel': 0, 'fairy': 2},
    'ground': {'fire': 2, 'electric': 2, 'grass': 0.5, 'poison': 2, 'flying': 0, 'bug': 0.5, 'rock': 2, 'steel': 2},
    'flying': {'electric': 0.5, 'grass': 2, 'fighting': 2, 'bug': 2, 'rock': 0.5, 'steel': 0.5},
    'psychic': {'fighting': 2, 'poison': 2, 'psychic': 0.5, 'dark': 0, 'steel': 0.5},
    'bug': {'fire': 0.5, 'grass': 2, 'fighting': 0.5, 'poison': 0.5, 'flying': 0.5, 'psychic': 2, 'ghost': 0.5, 'dark': 2, 'steel': 0.5, 'fairy': 0.5},
    'rock': {'fire': 2, 'ice': 2, 'fighting': 0.5, 'ground': 0.5, 'flying': 2, 'bug': 2, 'steel': 0.5},
    'ghost': {'normal': 0, 'psychic': 2, 'ghost': 2, 'dark': 0.5},
    'dragon': {'dragon': 2, 'steel': 0.5, 'fairy': 0},
    'dark': {'fighting': 0.5, 'psychic': 2, 'ghost': 2, 'dark': 0.5, 'fairy': 0.5},
    'steel': {'fire': 0.5, 'water': 0.5, 'electric': 0.5, 'ice': 2, 'rock': 2, 'steel': 0.5, 'fairy': 2},
    'fairy': {'fighting': 2, 'poison': 0.5, 'dragon': 2, 'dark': 2, 'steel': 0.5},
}

def get_max_move_power(base_move_id: str) -> int:
    """Calculates the power of a Max Move based on its original move."""
    base_move_data = MOVE_BY_ID.get(base_move_id)
    if not base_move_data or base_move_data['category'] == 'Status':
        return 10 # Should not happen for damaging moves, but a safe default

    # Moves with fixed Max Move power (e.g., multi-hit, weight-based)
    fixed_power_moves = {
        'crushgrip', 'wringout', 'magnitude', 'heavyslam', 'heatcrash', 'lowkick', 
        'grassknot', 'flail', 'reversal', 'gyroball', 'electroball', 'eruption', 
        'waterspout', 'bonemerang', 'doubleironbash', 'doublekick', 'dualchop', 
        'geargrind', 'twineedle', 'triplekick', 'tripledive', 'scaleshot'
    }
    if base_move_id in fixed_power_moves:
        if base_move_id in ['lowkick', 'grassknot', 'heavyslam', 'heatcrash']: return 130
        return 140

    power = base_move_data.get('basePower', 0)
    if power <= 40: return 90
    if power <= 50: return 100
    if power <= 60: return 110
    if power <= 70: return 120
    if power <= 100: return 130
    if power <= 140: return 140
    return 150

def _handle_max_move_effects(move_id: str, attacker: ActivePokemon, defender: ActivePokemon, battle: "Battle") -> str:
    """Handles the unique secondary effects of Max Moves."""
    from .move_effects.status_moves import handle_stat_boost_move
    from .field_effects import weather as weather_logic, terrain as terrain_logic
    
    log = ""
    should_update_image = False

    # Stat-boosting for allies
    if move_id in ['maxknuckle', 'maxooze', 'maxquake', 'maxairstream', 'maxsteelspike']:
        target = attacker # In 1v1, this targets the user
        if move_id == 'maxknuckle':
            boost_data = {'boosts': {'atk': 1}}
        elif move_id == 'maxooze':
            boost_data = {'boosts': {'spa': 1}}
        elif move_id == 'maxquake':
            boost_data = {'boosts': {'spd': 1}}
        elif move_id == 'maxairstream':
            boost_data = {'boosts': {'spe': 1}}
        elif move_id == 'maxsteelspike':
            boost_data = {'boosts': {'def': 1}}
        log += "\n" + handle_stat_boost_move(target, boost_data)

    # Stat-lowering for opponents
    elif move_id in ['maxphantasm', 'maxdarkness', 'maxwyrmwind', 'maxflutterby', 'maxstrike']:
        target = defender
        if move_id == 'maxphantasm':
            boost_data = {'boosts': {'def': -1}}
        elif move_id == 'maxdarkness':
            boost_data = {'boosts': {'spd': -1}}
        elif move_id == 'maxwyrmwind':
            boost_data = {'boosts': {'atk': -1}}
        elif move_id == 'maxflutterby':
            boost_data = {'boosts': {'spa': -1}}
        elif move_id == 'maxstrike':
            boost_data = {'boosts': {'spe': -1}}
        log += "\n" + handle_stat_boost_move(target, boost_data)

    # Weather-setting moves
    elif move_id in ['maxflare', 'maxgeyser', 'maxrockfall', 'maxhailstorm']:
        if move_id == 'maxflare':
            log += weather_logic.set_weather(battle, 'sunnyday', attacker)
        elif move_id == 'maxgeyser':
            log += weather_logic.set_weather(battle, 'raindance', attacker)
        elif move_id == 'maxrockfall':
            log += weather_logic.set_weather(battle, 'sandstorm', attacker)
        elif move_id == 'maxhailstorm':
            log += weather_logic.set_weather(battle, 'hail', attacker)

    # Terrain-setting moves
    elif move_id in ['maxovergrowth', 'maxlightning', 'maxmindstorm', 'maxstarfall']:
        if move_id == 'maxovergrowth':
            log += terrain_logic.set_terrain(battle, 'grassyterrain', 5)
            should_update_image = True
        elif move_id == 'maxlightning':
            log += terrain_logic.set_terrain(battle, 'electricterrain', 5)
            should_update_image = True
        elif move_id == 'maxmindstorm':
            log += terrain_logic.set_terrain(battle, 'psychicterrain', 5)
            should_update_image = True
        elif move_id == 'maxstarfall':
            log += terrain_logic.set_terrain(battle, 'mistyterrain', 5)
            should_update_image = True
    
    return log, should_update_image

def _handle_gmax_move_effects(move_id: str, attacker: ActivePokemon, defender: ActivePokemon, battle: "Battle") -> tuple[str, bool]:
    """Handles the unique secondary effects of G-Max Moves. Returns (log, should_update_image)."""
    from .move_effects.status import apply_status
    from .move_effects.status_moves import handle_stat_boost_move
    from .field_effects import hazards as hazard_logic
    import random

    log = ""
    should_update_image = False

    attacker_player = battle.get_player(attacker.pokemon.pokemon_uuid)
    if not attacker_player: attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2

    # --- G-Max Moves with Unique Effects ---
    
    if move_id == 'gmaxbefuddle':
        status = random.choice(['slp', 'psn', 'par'])
        log += apply_status(status, defender, {'secondary': {'chance': 100}}, battle)

    elif move_id == 'gmaxstunshock':
        status = random.choice(['psn', 'par'])
        log += apply_status(status, defender, {'secondary': {'chance': 100}}, battle)

    elif move_id in ['gmaxcannonade', 'gmaxvinelash', 'gmaxwildfire', 'gmaxvolcalith']:
        effect_name = move_id.replace('gmax', '')
        effect_key = f"gmax_{effect_name}"
        # Prevent stacking the same effect
        if effect_key not in attacker_player.side_conditions:
            attacker_player.side_conditions[effect_key] = {'turns': 4}
            log += f"\nA G-Max {effect_name.title()} effect began on the opponent's side!"

    elif move_id in ['gmaxcentiferno', 'gmaxsandblast', 'gmaxterror']:
        if 'trap' not in defender.volatiles:
            duration = 999 if move_id == 'gmaxterror' else random.randint(4, 5)
            defender.volatiles['trap'] = {'duration': duration, 'source_move': move_id}
            log += f"\n{defender.pokemon.name} was trapped in the vortex!"

    elif move_id == 'gmaxchistrike':
        # NOTE: Crit ratio boosts are not fully implemented yet, this adds the log
        log += f"\n{attacker.pokemon.name}'s team is fired up!"

    elif move_id == 'gmaxcuddle':
        if 'infatuation' not in defender.volatiles:
            defender.volatiles['infatuation'] = True
            log += f"\n{defender.pokemon.name} fell in love with {attacker.pokemon.name}!"

    elif move_id == 'gmaxdepletion':
        last_move = defender.last_move_used
        if last_move and defender.move_pp.get(last_move, 0) > 0:
            defender.move_pp[last_move] = max(0, defender.move_pp[last_move] - 2)
            log += f"\n{defender.pokemon.name}'s PP for {MOVE_BY_ID[last_move]['name']} was reduced!"

    elif move_id == 'gmaxfinale':
        heal_amount = attacker.actual_stats['hp'] // 6
        attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + heal_amount)
        log += f"\n{attacker.pokemon.name} restored some HP!"

    elif move_id == 'gmaxfoamburst':
        log += "\n" + handle_stat_boost_move(defender, {'boosts': {'spe': -2}})

    elif move_id == 'gmaxgravitas':
        if battle.gravity_turns <= 0:
            battle.gravity_turns = 5
            log += "\nGravity intensified!"

    elif move_id == 'gmaxmalodor' or move_id == 'gmaxvoltcrash':
        status = 'psn' if move_id == 'gmaxmalodor' else 'par'
        log += apply_status(status, defender, {'secondary': {'chance': 100}}, battle)

    elif move_id == 'gmaxmeltdown':
        if 'torment' not in defender.volatiles:
            defender.volatiles['torment'] = True
            log += f"\n{defender.pokemon.name} was subjected to torment!"
            
    elif move_id == 'gmaxreplenish':
        if random.random() < 0.5:
            # NOTE: Berry consumption isn't tracked yet, this adds the log
            log += f"\n{attacker.pokemon.name}'s team had its berries restored!"
            
    elif move_id == 'gmaxresonance':
        # Assumes Aurora Veil logic exists in your set_hazard function
        log += hazard_logic.set_hazard(battle, attacker_player, 'auroraveil')

    elif move_id in ['gmaxsmite', 'gmaxgoldrush']:
        if 'confusion' not in defender.volatiles:
            defender.volatiles['confusion'] = random.randint(1, 4)
            log += f"\n{defender.pokemon.name} became confused!"
            
    elif move_id == 'gmaxsnooze':
        if 'yawn' not in defender.volatiles and random.random() < 0.5:
            defender.volatiles['yawn'] = 2 # Will fall asleep at the end of next turn
            log += f"\n{defender.pokemon.name} grew drowsy!"

    elif move_id == 'gmaxstonesurge':
        log += hazard_logic.set_hazard(battle, attacker_player, 'stealthrock')

    elif move_id == 'gmaxsteelsurge':
        # NOTE: This requires a new hazard type 'gmaxsteelsurge' to be added
        log += hazard_logic.set_hazard(battle, attacker_player, 'gmaxsteelsurge')

    elif move_id == 'gmaxsweetness':
        for p in attacker_player.team:
            p.status = None
            p.status_counter = 0
        log += f"\nA wave of sweetness cured {attacker_player.user_name}'s team!"

    elif move_id == 'gmaxtartness':
        log += "\n" + handle_stat_boost_move(defender, {'boosts': {'evasion': -1}})

    elif move_id == 'gmaxwindrage':
        battle.player1_hazards.clear(); battle.player2_hazards.clear()
        battle.player1_screens.clear(); battle.player2_screens.clear()
        if battle.active_terrain:
            should_update_image = True
        battle.active_terrain = None
        battle.active_terrain_turns = 0
        log += "\nThe raging winds blew away all field effects!"
        
    return log, should_update_image

def get_modified_stat(pokemon: "ActivePokemon", stat_name: str,
                      ignore_positive_boosts: bool = False,
                      ignore_negative_boosts: bool = False) -> int:
    """
    Calculates a stat by applying boosts AND item multipliers.
    """
    base_stat = pokemon.actual_stats[stat_name]
    boost_level = pokemon.boosts[stat_name]

    if ignore_positive_boosts and boost_level > 0:
        boost_level = 0
    if ignore_negative_boosts and boost_level < 0:
        boost_level = 0
    
    item_multiplier = 1.0

    item_multiplier = pokemon.stat_multipliers.get(stat_name, 1.0)
    
    modified_stat = base_stat * item_multiplier

    # --- THIS IS THE CORRECTED LOGIC BLOCK ---
    ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
    
    # Find the battle this pokemon belongs to by iterating through all battles
    battle = None
    for chat_battles in active_battles.values(): # Loop through the lists of battles
        for b in chat_battles: # Loop through each battle in the list
            if pokemon in b.player1.team or pokemon in b.player2.team:
                battle = b
                break
        if battle:
            break
    # --- END OF CORRECTION ---

    if ability_id == 'hustle' and stat_name == 'atk':
        modified_stat *= 1.5

    # Marvel Scale & Quick Feet
    if pokemon.status is not None:
        if ability_id == 'marvelscale' and stat_name == 'def':
            modified_stat *= 1.5
        elif ability_id == 'quickfeet' and stat_name == 'spe':
            modified_stat *= 1.5
    
    if battle and battle.active_terrain == 'electricterrain' and ability_id == 'surgesurfer' and stat_name == 'spe':
        is_grounded = 'Flying' not in pokemon.pokemon.types and 'airballoon' not in pokemon.volatiles
        if is_grounded:
            modified_stat *= 2

    # Solar Power
    if stat_name == 'spa' and ability_id == 'solarpower' and battle and not is_weather_suppressed(battle) and battle.active_weather == 'sunnyday':
        modified_stat *= 1.5

    # Weather Speed abilities
    if stat_name == 'spe' and battle and not is_weather_suppressed(battle):
        weather_ability_map = {
            'swiftswim': 'raindance', 'chlorophyll': 'sunnyday',
            'sandrush': 'sandstorm', 'slushrush': 'hail'
        }
        if ability_id in weather_ability_map and battle.active_weather == weather_ability_map[ability_id]:
            modified_stat *= 2
    
    # Apply stat stage boosts
    if boost_level >= 0:
        boost_multiplier = (2 + boost_level) / 2
    else:
        boost_multiplier = 2 / (2 - boost_level)
        
    final_stat = int(modified_stat * boost_multiplier)

    ability_id_for_toxic = pokemon.pokemon.ability.lower().replace(" ", "")
    if ability_id_for_toxic == 'toxicboost' and stat_name == 'atk' and pokemon.status in ['psn', 'tox']:
        final_stat = int(final_stat * 1.5)
    
    ability_id_for_guts = pokemon.pokemon.ability.lower().replace(" ", "")
    if ability_id_for_guts == 'guts' and stat_name == 'atk' and pokemon.status is not None:
        final_stat = int(final_stat * 1.5)

    ability_id_for_flare = pokemon.pokemon.ability.lower().replace(" ", "")
    if ability_id_for_flare == 'flareboost' and stat_name == 'spa' and pokemon.status == 'brn':
        final_stat = int(final_stat * 1.5)

    # Apply burn attack drop
    if stat_name == 'atk' and pokemon.status == 'brn' and ability_id_for_guts != 'guts': # Add the Guts check here
        final_stat //= 2
        
    return final_stat

def get_type_effectiveness(move_type: str, defender_types: list[str], battle: "Battle", attacker: "ActivePokemon" = None) -> float: # Added attacker argument
    multiplier = 1.0
    for def_type in defender_types:
        move_type_lower = move_type.lower()
        def_type_lower = def_type.lower()

        if attacker: # Check if attacker object was passed
            attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
            if attacker_ability_id == 'scrappy' and def_type_lower == 'ghost' and move_type_lower in ['normal', 'fighting']:
                 continue # Skip the chart lookup, effectively treating it as 1.0x for this type interaction
        
        # Existing Gravity check
        if move_type_lower == 'ground' and def_type_lower == 'flying' and battle.gravity_turns > 0:
            # Gravity grounds Flying types, making them hittable by Ground
            continue # Skip immunity check

        # Standard type chart lookup
        chart_entry = TYPE_CHART.get(move_type_lower, {})
        multiplier *= chart_entry.get(def_type_lower, 1.0)

    return multiplier

def check_accuracy(attacker: ActivePokemon, defender: ActivePokemon, move_data: dict, battle: "Battle") -> bool:

    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    defender_ability_id = defender.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'noguard' or defender_ability_id == 'noguard':
        return True # Moves always hit if either Pokemon has No Guard

    move_id = move_data.get('id')
    # --- Checks for specific move interactions (Thunder/Hurricane in Rain, Blizzard in Hail, Fly/Dig interactions) ---
    if defender.charging_move:
        defender_charging_move_id = defender.charging_move.get('id')
        if defender_charging_move_id in ['fly', 'bounce'] and move_id in ['thunder', 'hurricane', 'gust', 'twister', 'skyuppercut']:
            return True
        if defender_charging_move_id == 'dig' and move_id in ['earthquake', 'magnitude']:
            return True
        if defender_charging_move_id == 'dive' and move_id in ['surf', 'whirlpool']:
            return True

    if not is_weather_suppressed(battle):
        if battle.active_weather == 'raindance' and move_id in ['thunder', 'hurricane']:
            return True # These moves bypass accuracy check in rain
        if battle.active_weather == 'hail' and move_id == 'blizzard':
            return True # Blizzard bypasses accuracy check in hail

    # --- Base Accuracy ---
    accuracy = move_data.get('accuracy')
    if accuracy is True or accuracy is None: # Moves that never miss (or None accuracy like V-Create)
        return True
    if accuracy == 0: # Should not happen, but safeguard
        return False

    # --- Modifiers ---
    final_accuracy = float(accuracy) # Start with base accuracy

    # Gravity
    if battle.gravity_turns > 0:
        # Gravity multiplies accuracy by 5/3 (approx 1.67)
        final_accuracy *= (5 / 3)

    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "") # Define once
    if attacker_ability_id == 'compoundeyes':
        final_accuracy *= 1.3 # Apply 30% accuracy boost
    
    if attacker_ability_id == 'hustle' and move_data.get('category') == 'Physical':
        final_accuracy *= 0.8 # Apply 20% accuracy drop for Physical moves

    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'victorystar':
        final_accuracy *= 1.1 # Apply 10% accuracy boost from attacker

    defender_ability_id = defender.pokemon.ability.lower().replace(" ", "")
    if defender_ability_id == 'tangledfeet' and 'confusion' in defender.volatiles:
        # Evasion boost typically halves accuracy
        final_accuracy *= 0.5 # Halve the final calculated accuracy

    # --- Accuracy/Evasion Stat Stages ---
    # Simplified: A more complete check would use the boost calculation formula
    # For now, let's add a basic check:
    acc_stage = attacker.boosts.get('accuracy', 0)
    eva_stage = defender.boosts.get('evasion', 0)
    stage_difference = max(-6, min(6, acc_stage - eva_stage)) # Clamp difference between -6 and +6

    if stage_difference > 0:
        accuracy_multiplier = (3 + stage_difference) / 3
    else:
        accuracy_multiplier = 3 / (3 - stage_difference)
    final_accuracy *= accuracy_multiplier
    # --- End Stat Stage Check ---


    # --- Other Accuracy Modifiers (e.g., Compound Eyes, Hustle, Wide Lens) could go here ---
    # Example for Compound Eyes (if implemented):
    # if attacker_ability_id == 'compoundeyes':
    #    final_accuracy *= 1.3

    # Ensure accuracy stays within practical bounds (optional, but good practice)
    final_accuracy = max(1, min(100, int(final_accuracy))) # Clamp between 1 and 100

    # --- Final Random Roll ---
    return random.randint(1, 100) <= final_accuracy

def check_for_crit(attacker: ActivePokemon, defender: ActivePokemon, move_data: dict) -> bool:

    defender_ability_id = defender.pokemon.ability.lower().replace(" ", "")
    if defender_ability_id in ['battlearmor', 'shellarmor']:
        return False

    if move_data.get('willCrit'):
        return True

    crit_ratio = move_data.get('critRatio', 1)

    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'superluck':
        crit_ratio += 1

    crit_chances = {1: 24, 2: 8, 3: 2}

    if crit_ratio >= 3: # Adjusted from >=4 assuming stage 3 is max practical before always crit
        return True
    
    chance = crit_chances.get(crit_ratio, 24)

    return random.randint(1, chance) == 1

def execute_move(attacker: ActivePokemon, defender: ActivePokemon, move_id: str, battle: "Battle", base_move_id: str = None) -> dict:
    """
    Executes a move and returns a dictionary with the results.
    """
    from bot.battle.move_effects.status import apply_status
    from bot.battle.item_effects import item_logic

    if 'destinybond' in attacker.volatiles:
        del attacker.volatiles['destinybond']

    results = {
        "damage_dealt": 0,
        "effectiveness": 1.0,
        "did_hit": True,
        "log": "",
        "recoil_damage": 0,
        "hits": 0,
        "force_switch": False,
        "force_opponent_switch": False,
        "is_baton_pass": False,
    }

    if 'focuspunch' in attacker.volatiles:
        # We only get here if check_can_move passed (meaning no damage was taken)
        del attacker.volatiles['focuspunch']
        # The 'move_id' passed into this function will be the one from the opponent's action,
        # so we force it to be 'focuspunch' to deal the correct damage.
        move_id = 'focuspunch'
        move_data = MOVE_BY_ID.get(move_id, {}).copy()
        results['log'] += f"\n{attacker.pokemon.name} unleashed its focus!"
        # Now, the rest of the function will execute as a normal 150 BP physical move.

    # This is TURN 1: Starting the focus
    elif move_id == 'focuspunch':
        attacker.volatiles['focuspunch'] = True
        results['did_hit'] = True # The setup was successful
        results['log'] = f"\n{attacker.pokemon.name} is tightening its focus!"
        # Return immediately, skipping all damage calculation for this turn.
        return results

    if move_id == 'dreameater':
        if defender.status != 'slp':
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results

    if move_id in ['fakeout', 'firstimpression', 'matblock']:
        if attacker.active_turns > 0:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results

    if move_id == 'copycat':
        last_move = battle.last_successful_move
        if not last_move or last_move in NO_COPY_MOVES:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results
        
        # Recursively call execute_move with the copied move
        results['log'] = f"\n{attacker.pokemon.name} used Copycat!\n"
        copied_results = execute_move(attacker, defender, last_move, battle, base_move_id=last_move)
        results['log'] += copied_results.get('log', '')
        # The rest of the results dictionary will be populated by the copied move's execution
        return copied_results

    if move_id == 'mefirst':
        # --- THIS IS THE CORRECTED FIX ---
        attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
        opponent_player, _ = battle.get_opponent_for_player(attacker_player)

        # Get the opponent's action from the main battle object
        target_action = battle.p1_action if opponent_player is battle.player1 else battle.p2_action
        # --- END OF FIX ---

        if not target_action or target_action[0] != 'move' or attacker.has_moved_this_turn or defender.has_moved_this_turn:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results
        
        # The rest of the logic is correct
        target_move_id = opponent_player.team[opponent_player.active_pokemon_index].pokemon.moves[target_action[1]]
        target_move_data = MOVE_BY_ID.get(target_move_id, {})

        if target_move_data.get('category') == 'Status' or target_move_data.get('priority', 0) > 0:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results

        results['log'] = f"\n{attacker.pokemon.name} used Me First!\n"
        copied_results = execute_move(attacker, defender, target_move_id, battle, base_move_id=target_move_id)
        
        if copied_results.get("damage_dealt", 0) > 0:
            copied_results["damage_dealt"] = int(copied_results["damage_dealt"] * 1.5)
        
        results['log'] += copied_results.get('log', '')
        results['final_move_name'] = copied_results.get('final_move_name')
        return copied_results
        
    player = battle.get_player(attacker.pokemon.pokemon_uuid)
    if not player: # Failsafe
        player = battle.player1 if attacker in battle.player1.team else battle.player2
        
    is_z_move_execution = player.has_used_z_move and not attacker.volatiles.get('z_move_used_this_turn')
    
    original_move_data = MOVE_BY_ID.get(base_move_id or move_id, {}).copy()
    move_data = MOVE_BY_ID.get(move_id, {}).copy()

    if is_z_move_execution:
        attacker.volatiles['z_move_used_this_turn'] = True # Flag that the Z-Move has been spent this turn

        signature_move_info = SIGNATURE_Z_MOVES.get(original_move_data['id'])
        item_id = ITEM_ID_BY_NAME.get(attacker.pokemon.item, "")
        base_move_data = MOVE_BY_ID[base_move_id]

        # --- THIS IS THE FIX for Clangorous Soulblaze and other signature moves ---
        if signature_move_info and item_id == signature_move_info['item_id']:
            if 'secondary' in signature_move_info:
                move_data.setdefault('secondary', {}).update(signature_move_info['secondary'])
            if 'self' in signature_move_info:
                move_data.setdefault('self', {}).update(signature_move_info['self'])
        # --- END FIX ---

        # Status Z-Move Logic
        elif original_move_data.get('category') == 'Status' and 'zMove' in original_move_data:
            z_effect = original_move_data['zMove']
        
            # REPLACEMENT effects (like Z-Rest's heal)
            if 'boost' in z_effect or z_effect.get('effect') in ['heal', 'clearnegativeboosts', 'clearnegativeboost']:
                if 'boost' in z_effect:
                    results['log'] += handle_stat_boost_move(attacker, {'boosts': z_effect['boost']})
                elif z_effect['effect'] == 'heal':
                    attacker.current_hp = attacker.actual_stats['hp']
                    results['log'] += f"\n{attacker.pokemon.name}'s HP was fully restored by Z-Power!"
                elif z_effect['effect'] in ['clearnegativeboosts', 'clearnegativeboost']:
                    if any(v < 0 for v in attacker.boosts.values()):
                        for stat, value in attacker.boosts.items():
                            if value < 0:
                                attacker.boosts[stat] = 0
                        results['log'] += f"\n{attacker.pokemon.name}'s lowered stats were reset by Z-Power!"
                
                # --- THIS IS THE FIX for Z-Rest ---
                # Return immediately to prevent the original move's effect.
                return results
                # --- END FIX ---

            # ADDITIVE effects (like Z-Splash's boost)
            elif 'effect' in z_effect:
                # These effects happen IN ADDITION to the original move.
                if z_effect['effect'] == 'redirect':
                    attacker.volatiles['redirect'] = True
                    results['log'] += f"\n{attacker.pokemon.name} became the center of attention!"
                elif z_effect['effect'] == 'crit2':
                    attacker.volatiles['focusenergy'] = True
                    results['log'] += f"\n{attacker.pokemon.name} is getting pumped and will land more critical hits!"
        
        # Damaging Z-Move power/name override (logic is correct, no changes needed here)
        elif original_move_data.get('category') in ['Physical', 'Special']:
            z_move_info = get_z_move_details(original_move_data['id'])
            if z_move_info:
                move_data['basePower'] = z_move_info['power']
                move_data['name'] = z_move_info['name']
                move_data['accuracy'] = True
                move_data['breaksProtect'] = True

    move_data = MOVE_BY_ID[move_id].copy() # Use .copy() to avoid modifying the global dictionary

    move_data, power_multiplier = trigger_on_modify_move(attacker, move_data)

    # --- NEW LOGIC BLOCK STARTS HERE ---

    # 1. Handle Item-Based Type Changes
    if move_id == 'judgment' and attacker.pokemon.id.startswith('arceus'):
        if attacker.pokemon.item and 'plate' in attacker.pokemon.item.lower():
            move_data['type'] = attacker.pokemon.types[0]

    elif move_id == 'multiattack' and attacker.pokemon.id.startswith('silvally'):
        if attacker.pokemon.item and 'memory' in attacker.pokemon.item.lower():
            move_data['type'] = attacker.pokemon.types[0]

    elif move_id == 'technoblast' and attacker.pokemon.id.startswith('genesect'):
        if attacker.pokemon.item == 'Douse Drive': move_data['type'] = 'Water'
        elif attacker.pokemon.item == 'Shock Drive': move_data['type'] = 'Electric'
        elif attacker.pokemon.item == 'Burn Drive': move_data['type'] = 'Fire'
        elif attacker.pokemon.item == 'Chill Drive': move_data['type'] = 'Ice'

    # 2. Handle Form-Based Move Transformations
    if attacker.pokemon.id == 'zaciancrowned' and move_id == 'ironhead':
        move_id = 'behemothbash'
        move_data = MOVE_BY_ID[move_id].copy()
    
    elif attacker.pokemon.id == 'zamazentacrowned' and move_id == 'ironhead':
        move_id = 'behemothblade'
        move_data = MOVE_BY_ID[move_id].copy()

    suppress_secondary = False

    was_stopped, stop_log = ability_effects.trigger_on_try_hit(attacker, defender, move_data, battle)
    if was_stopped:
        results["did_hit"] = False
        results["log"] = stop_log
        results["effectiveness"] = 0
        return results

    if move_id in ['gmaxoneblow', 'gmaxrapidflow']:
        results['breaksProtect'] = True
    
    # G-Max Drum Solo, Fireball, and Hydrosnipe ignore abilities
    if move_id in ['gmaxdrumsolo', 'gmaxfireball', 'gmaxhydrosnipe']:
        results['ignoreAbility'] = True

    breaks_protect = move_data.get('breaksProtect', False)

    if defender.is_protected and not breaks_protect:
        results["did_hit"] = False
        results["log"] = f"\n{defender.pokemon.name} protected itself!"
        if 'banefulbunker' in defender.volatiles and move_data.get("flags", {}).get("contact"):
            if 'Poison' not in attacker.pokemon.types and 'Steel' not in attacker.pokemon.types:
                from .move_effects.status import apply_status
                psn_move_data = {'status': 'psn'}
                status_log = apply_status('psn', attacker, psn_move_data, battle)
                if "was poisoned" in status_log:
                    # Append to the existing results['log']
                    results["log"] += f"\n{attacker.pokemon.name} was poisoned!"
        
        if move_id == 'feint':
            defender.is_protected = False
            results["log"] += f"\nBut the protection was lifted!"
        
        return results

    if breaks_protect and defender.is_protected:
        defender.is_protected = False

    hits_substitute = 'substitute' in defender.volatiles and move_data['category'] != 'Status'
    if hits_substitute:
        if 'sound' in move_data.get('flags', {}) or move_data.get('breaksProtect'):
            hits_substitute = False

    can_move, reason = item_logic.apply_on_move_choice(attacker, move_id)
    if not can_move:
        results["did_hit"] = False
        results["log"] = reason
        return results

    if move_id == 'guardianofalola':
        # This move fails if the opponent is already at 1 HP.
        if defender.current_hp <= 1:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results
        
        # Guardian of Alola's special effect: Deals damage equal to 75% of the target's current HP.
        damage = math.floor(defender.current_hp * 0.75)
        results["damage_dealt"] = max(1, damage) # Ensures at least 1 damage is dealt.
        results["effectiveness"] = 1.0 # Bypasses normal type effectiveness checks.
        results["hits"] = 1
        return results

    if move_id in ['superfang', 'naturesmadness', 'guardianofalola']:
        if defender.current_hp <= 1:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results
        damage = math.floor(defender.current_hp / 2)
        if move_id == 'guardianofalola':
            damage = math.floor(defender.current_hp * 0.75)
        results["damage_dealt"] = damage
        results["effectiveness"] = 1.0
        results["hits"] = 1
        return results

    if move_id in ['futuresight', 'doomdesire']:
        attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
        defender_player = battle.player1 if defender in battle.player1.team else battle.player2
        effect = {
            'turn_to_hit': battle.turn + 2,
            'origin_player_id': attacker_player.user_id,
            'target_player_id': defender_player.user_id,
            'move_id': move_id
        }
        battle.delayed_effects.append(effect)
        results['log'] = f"\n{attacker.pokemon.name} foresaw an attack!"
        return results

    if move_id == 'endeavor':
        if defender.current_hp > attacker.current_hp:
            results["damage_dealt"] = defender.current_hp - attacker.current_hp
        else:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
        return results

    if move_data.get('ohko'):

        defender_ability_id = defender.pokemon.ability.lower().replace(" ", "")
        if defender_ability_id == 'sturdy':
            results["did_hit"] = False
            results["log"] = f"\n{defender.pokemon.name}'s Sturdy prevents OHKO moves!"
            return results

        if attacker.pokemon.level < defender.pokemon.level:
            results["did_hit"] = False
            results["log"] = "\nBut it failed!"
            return results

        effectiveness = get_type_effectiveness(move_data['type'], defender.pokemon.types, battle, attacker=attacker)
        if effectiveness == 0:
            results["did_hit"] = False
            results["effectiveness"] = 0
            return results

        if random.randint(1, 100) <= 30:
            results["did_hit"] = True
            results["damage_dealt"] = defender.current_hp
            results["log"] = "\nIt's a one-hit KO!"
        else:
            results["did_hit"] = False
        return results

    if not check_accuracy(attacker, defender, move_data, battle):
        results["did_hit"] = False
        return results

    if move_id in ['counter', 'mirrorcoat']:
        if attacker.last_damage_taken > 0 and attacker.last_damage_category:
            if move_id == 'counter' and attacker.last_damage_category == 'Physical':
                results['damage_dealt'] = attacker.last_damage_taken * 2
            elif move_id == 'mirrorcoat' and attacker.last_damage_category == 'Special':
                results['damage_dealt'] = attacker.last_damage_taken * 2
            else:
                results['log'] = "\nBut it failed!"
        else:
            results['log'] = "\nBut it failed!"
        return results

    if move_id == 'memento':
        stat_drop_log = handle_stat_boost_move(defender, move_data)
        results['log'] = stat_drop_log
        attacker.current_hp = 0
        results['log'] += f"\n{attacker.pokemon.name} fainted!"
        results['force_switch'] = True
        return results

    if move_data['category'] == 'Status':


        # First, check for self-switching moves like Baton Pass, as they are a special case.
        if move_data.get('selfSwitch'):
            attacker_player = battle.get_player(attacker.pokemon.pokemon_uuid)
            if not attacker_player: # Failsafe
                attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
            
            can_switch = any(p.current_hp > 0 and i != attacker_player.active_pokemon_index for i, p in enumerate(attacker_player.team))
            
            if can_switch:
                results['force_switch'] = True
                if move_id == 'batonpass':
                    results['is_baton_pass'] = True
                # For moves like Parting Shot that also have another effect
                if move_data.get('boosts'):
                     results['log'] += handle_stat_boost_move(defender, move_data)
            else:
                results['log'] += "\nBut it failed!"

        # If it's not a self-switching move, handle other status moves as normal.
        else:
            # Handle force-switching moves like Roar and Whirlwind specifically
            if move_data.get('forceSwitch'):
                if 'dynamax' in defender.volatiles:
                    results["did_hit"] = False
                    results["log"] = "\nBut it failed!"
                else:
                    results["force_opponent_switch"] = True
            # For all other status moves, use the generic handler
            else:
                results['log'] += handle_status_move(attacker, defender, move_data, battle)
        
        return results

    if move_data.get('damage'):
        fixed_damage = move_data.get('damage')
        if fixed_damage == 'level':
            results["damage_dealt"] = attacker.pokemon.level
        elif isinstance(fixed_damage, int):
            results["damage_dealt"] = fixed_damage
        results["effectiveness"] = 1.0
        results["hits"] = 1
        return results
    
    if move_id in ['brickbreak', 'psychicfangs']:
        defender_screens = battle.player1_screens if defender in battle.player1.team else battle.player2_screens
        if defender_screens:
            defender_screens.clear()
            results['log'] += f"\n{attacker.pokemon.name} shattered the opposing team's barriers!"

    num_hits = 1
    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if 'multihit' in move_data:
        if attacker_ability_id == 'skilllink':
            # Skill Link guarantees the maximum number of hits
            if isinstance(move_data['multihit'], list):
                num_hits = move_data['multihit'][1]
            else:
                num_hits = move_data['multihit']
        elif attacker.pokemon.item == 'Loaded Dice':
            if move_id in ['triplekick', 'tripledive']:
                num_hits = 3
            else: # Standard 2-5 hit moves
                num_hits = random.randint(4, 5)
        else:
            # Standard multi-hit logic
            if isinstance(move_data['multihit'], list):
                num_hits = random.randint(move_data['multihit'][0], move_data['multihit'][1])
            else:
                num_hits = move_data['multihit']

    total_damage = 0
    hits_landed = 0
    for i in range(num_hits):
        if defender.current_hp <= 0:
            break

        hits_landed += 1
        power = 0
        is_gmax_move = isinstance(move_data.get("isMax"), str)
        z_move_details = get_z_move_details(base_move_id) if is_z_move_execution and move_data['category'] != 'Status' else None

        if z_move_details:
            # PRIORITY 1: Z-Moves
            power = z_move_details.get('power', 0)
        elif is_gmax_move and move_data.get('basePower', 0) > 10:
            # PRIORITY 2: Fixed-power G-Max moves
            power = move_data.get('basePower', 0)
        elif move_data.get('isMax') and base_move_id:
            # PRIORITY 3: Calculated-power Max and G-Max moves
            power = get_max_move_power(base_move_id)
        else:
            # PRIORITY 4: Regular moves
            power = move_data.get('basePower', 0)

        if move_id == 'lastrespects':
            # Find the player object for the attacker
            attacker_player = battle.get_player(attacker.pokemon.pokemon_uuid)
            if not attacker_player: # Failsafe in case the UUID isn't found
                attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
            
            # Count fainted Pokémon on the attacker's team
            fainted_count = sum(1 for p in attacker_player.team if p.current_hp <= 0)
            
            # Set power: 50 base + 50 for each fainted ally
            power = 50 + (fainted_count * 50)

        if attacker_ability_id == 'reckless' and (move_data.get('recoil') or move_data.get('hasCrashDamage')):
            power = int(power * 1.2)

        if attacker_ability_id == 'sheerforce' and move_data.get('secondary'):
            power = int(power * 1.3)
            suppress_secondary = True # This flag will prevent the secondary effect later

        # Mega Launcher: Boost aura and pulse moves
        if attacker_ability_id == 'megalauncher' and move_data.get('flags', {}).get('pulse'):
            power = int(power * 1.5)

        if attacker.pokemon.ability.lower().replace(" ", "") == 'technician' and move_data.get('basePower', 0) <= 60:
            power = int(power * 1.5)

        power = int(power * power_multiplier)

        if 'flashfire' in attacker.volatiles and move_data['type'] == 'Fire':
            power = int(power * 1.5)
            # The boost is consumed upon use.
            del attacker.volatiles['flashfire']

        if move_id == 'return':
            # In a simulated environment, friendship is always max, so Return's power is 102.
            power = 102

        if move_id == 'knockoff' and _is_item_removable(defender):
            power = int(power * 1.5)
    
        if move_id == 'fling' and attacker.pokemon.item:
            # Simplified: Fling has a fixed power for now.
            # A full implementation requires a large dictionary mapping items to power.
            power = 30
            # Temporarily store the item to be flung and remove it from the user
            attacker.volatiles['fling_item_used'] = attacker.pokemon.item
            attacker.pokemon.item = None

        if move_id == 'acrobatics':
            if not attacker.pokemon.item:
                power *= 2
        if move_id == 'facade':
            if attacker.status in ['brn', 'par', 'psn', 'tox']:
                power *= 2
        if move_id == 'brine':
            if defender.current_hp <= defender.actual_stats['hp'] / 2:
                power *= 2
        if move_id in ['storedpower', 'powertrip']:
            total_boosts = sum(boost for boost in attacker.boosts.values() if boost > 0)
            power = 20 + (total_boosts * 20)
        if move_id == 'weatherball':
            if battle.active_weather:
                power *= 2
                if battle.active_weather in ['sunnyday', 'desolateland']:
                    move_data['type'] = 'Fire'
                elif battle.active_weather in ['raindance', 'primordialsea']:
                    move_data['type'] = 'Water'
                elif battle.active_weather == 'sandstorm':
                    move_data['type'] = 'Rock'
                elif battle.active_weather in ['hail', 'snowscape']:
                    move_data['type'] = 'Ice'
        if move_id in ['eruption', 'waterspout']:
            power = (150 * attacker.current_hp) / attacker.actual_stats['hp']
            power = max(1, int(power))
        elif move_id in ['hex', 'venoshock']:
          # Check the defender's status
          if defender.status is not None:
              # Venoshock doubles power only on poison
              if move_id == 'venoshock' and defender.status in ['psn', 'tox']:
                  power *= 2
              # Hex doubles power on ANY non-volatile status
              elif move_id == 'hex':
                  power *= 2
        elif move_id in ['gyroball', 'electroball']:
            # --- CORRECTED LINES ---
            attacker_speed = get_modified_stat(attacker, 'spe')
            defender_speed = get_modified_stat(defender, 'spe')
            # --- END OF CORRECTION ---
            if move_id == 'gyroball':
                if attacker_speed > 0: # Check attacker_speed is not zero to avoid division error
                    power = 25 * (defender_speed / attacker_speed) + 1
                else:
                    power = 1 # Or some other default/minimum power
                power = min(150, int(power))
            elif move_id == 'electroball':
                if defender_speed > 0: # Check defender_speed is not zero
                    ratio = attacker_speed / defender_speed
                    if ratio >= 4: power = 150
                    elif ratio >= 3: power = 120
                    elif ratio >= 2: power = 80
                    elif ratio >= 1: power = 60
                    else: power = 40
                else:
                    power = 40 # Or some other default if defender speed is 0
        elif move_id in ['heavyslam', 'heatcrash', 'lowkick', 'grassknot']:
            attacker_weight = attacker.pokemon.weight
            defender_weight = defender.pokemon.weight
            if defender_weight > 0:
                if move_id in ['heavyslam', 'heatcrash']:
                    ratio = attacker_weight / defender_weight
                    if ratio >= 5: power = 120
                    elif ratio >= 4: power = 100
                    elif ratio >= 3: power = 80
                    elif ratio >= 2: power = 60
                    else: power = 40
                elif move_id in ['lowkick', 'grassknot']:
                    if defender_weight < 10: power = 20
                    elif defender_weight < 25: power = 40
                    elif defender_weight < 50: power = 60
                    elif defender_weight < 100: power = 80
                    elif defender_weight < 200: power = 100
                    else: power = 120
        elif move_id in ['flail', 'reversal']:
            hp_ratio = (attacker.current_hp * 48) / attacker.actual_stats['hp']
            if hp_ratio <= 1: power = 200
            elif hp_ratio <= 4: power = 150
            elif hp_ratio <= 9: power = 100
            elif hp_ratio <= 16: power = 80
            elif hp_ratio <= 32: power = 40
            else: power = 20
        
        is_attacker_grounded = 'Flying' not in attacker.pokemon.types
        if battle.active_terrain == 'electricterrain' and move_data['type'] == 'Electric' and is_attacker_grounded:
            power = int(power * 1.3)
        elif battle.active_terrain == 'grassyterrain' and move_data['type'] == 'Grass' and is_attacker_grounded:
            power = int(power * 1.3)
        elif battle.active_terrain == 'psychicterrain' and move_data['type'] == 'Psychic' and is_attacker_grounded:
            power = int(power * 1.3)

        move_to_check_for_flags = MOVE_BY_ID.get(base_move_id) or move_data
        power_boost_multiplier = ability_effects.trigger_on_modify_move_power(attacker, move_to_check_for_flags, battle)
        power = int(power * power_boost_multiplier)

        level = attacker.pokemon.level

        attack = 0
        defense = 0
        effective_move_category = move_data['category'] # Default category

        if move_data.get('isMax') and original_move_data:
            effective_move_category = original_move_data['category']
        
        attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
        defender_ability_id = defender.pokemon.ability.lower().replace(" ", "")
        ignore_attacker_drops = (defender_ability_id == 'unaware')
        ignore_defender_boosts = (attacker_ability_id == 'unaware')

        # 1. Handle moves that use the user's higher offensive stat
        if move_id in ['photongeyser', 'shellsidearm']:
            attacker_atk = get_modified_stat(attacker, 'atk')
            attacker_spa = get_modified_stat(attacker, 'spa')

            if attacker_atk > attacker_spa:
                effective_move_category = 'Physical'
                attack = attacker_atk
                defense = get_modified_stat(defender, 'def', ignore_positive_boosts=ignore_defender_boosts)
            else:
                effective_move_category = 'Special'
                attack = attacker_spa
                defense = get_modified_stat(defender, 'spd', ignore_positive_boosts=ignore_defender_boosts)

        # 2. Handle moves that use an unconventional attacking stat (like Body Press)
        elif move_id == 'bodypress':
            effective_move_category = 'Physical'
            attack = get_modified_stat(attacker, 'def', ignore_negative_boosts=ignore_attacker_drops)
            defense = get_modified_stat(defender, 'def', ignore_positive_boosts=ignore_defender_boosts)

        elif move_id == 'foulplay':
            effective_move_category = 'Physical'
            # Use the DEFENDER'S Attack stat for the calculation
            attack = get_modified_stat(defender, 'atk', ignore_negative_boosts=ignore_attacker_drops) 
            defense = get_modified_stat(defender, 'def', ignore_positive_boosts=ignore_defender_boosts)

        # 3. Handle moves that target the opposite defensive stat (like Psyshock)
        elif move_id in ['psyshock', 'psystrike', 'secretsword']:
            effective_move_category = 'Special'
            attack = get_modified_stat(attacker, 'spa', ignore_negative_boosts=ignore_attacker_drops)
            defense = get_modified_stat(defender, 'def', ignore_positive_boosts=ignore_defender_boosts)

        # 4. DEFAULT CASE: If none of the above, use the standard logic
        else:
            if effective_move_category == 'Special':
                attack = get_modified_stat(attacker, 'spa', ignore_negative_boosts=ignore_attacker_drops)
                defense = get_modified_stat(defender, 'spd', ignore_positive_boosts=ignore_defender_boosts)
                if battle.wonder_room_turns > 0:
                    defense = get_modified_stat(defender, 'def', ignore_positive_boosts=ignore_defender_boosts)
            else: # Physical
                attack = get_modified_stat(attacker, 'atk', ignore_negative_boosts=ignore_attacker_drops)
                defense = get_modified_stat(defender, 'def', ignore_positive_boosts=ignore_defender_boosts)
                if battle.wonder_room_turns > 0:
                    defense = get_modified_stat(defender, 'spd', ignore_positive_boosts=ignore_defender_boosts)

                if attacker.status == 'brn' and attacker_ability_id not in ['guts', 'toxicboost']:
                    attack //= 2

        effectiveness = get_type_effectiveness(move_data['type'], defender.pokemon.types, battle, attacker=attacker)
        results["effectiveness"] = effectiveness
        damage = 0
        if effectiveness > 0:
            damage = int(((((2 * level / 5) + 2) * power * attack / defense) / 50) + 2)

            if attacker_ability_id == 'neuroforce' and effectiveness > 1:
                damage = int(damage * 1.25)
            
            # ITEM DAMAGE MULTIPLIER 
            item_multiplier = item_logic.apply_on_damage_dealt(attacker, move_data, effectiveness)
            damage = int(damage * item_multiplier)
            # END

            if move_data['type'] in attacker.pokemon.types:
                # Get the STAB multiplier from our new ability handler
                stab_multiplier = get_stab_multiplier(attacker)
                damage = int(damage * stab_multiplier)
            
            if not is_weather_suppressed(battle):
                if battle.active_weather == 'sunnyday':
                    if move_data['type'] == 'Fire': damage = int(damage * 1.5)
                    if move_data['type'] == 'Water': damage = int(damage * 0.5)
                elif battle.active_weather == 'raindance':
                    if move_data['type'] == 'Water': damage = int(damage * 1.5)
                    if move_data['type'] == 'Fire': damage = int(damage * 0.5)
            
            is_crit = check_for_crit(attacker, defender, move_data)
            if is_crit:
                # Sniper increases crit damage from 1.5x to 2.25x
                crit_multiplier = 2.25 if attacker_ability_id == 'sniper' else 1.5
                damage = int(damage * crit_multiplier)
                if not results['log']: results['log'] += "\nA critical hit!"

            random_modifier = random.uniform(0.85, 1.0)
            damage = int(damage * effectiveness * random_modifier)
            
            defender_screens = battle.player1_screens if defender in battle.player1.team else battle.player2_screens
            if defender_screens.get('reflect') and move_data['category'] == 'Physical':
                damage = int(damage * 0.5)
            if defender_screens.get('lightscreen') and move_data['category'] == 'Special':
                damage = int(damage * 0.5)

            damage_reduction_multiplier = ability_effects.trigger_on_damage_taken(defender, move_data, effectiveness)
            damage = int(damage * damage_reduction_multiplier)

            defender_ability_id = defender.pokemon.ability.lower().replace(" ", "")

            # Handle Filter, Solid Rock, and Prism Armor
            if defender_ability_id in ['filter', 'solidrock', 'prismarmor'] and effectiveness > 1:
                damage = int(damage * 0.75) # Reduce super-effective damage by 25%
    
            # Handle Thick Fat
            elif defender_ability_id == 'thickfat' and move_data['type'] in ['Fire', 'Ice']:
                damage = int(damage * 0.5) # Halve damage from Fire and Ice moves
    
            # Handle Multiscale and Shadow Shield
            elif defender_ability_id in ['multiscale', 'shadowshield'] and defender.current_hp == defender.actual_stats['hp']:
                damage = int(damage * 0.5) # Halve damage if at full HP

            is_defender_grounded = 'Flying' not in defender.pokemon.types
            if battle.active_terrain == 'mistyterrain' and move_data['type'] == 'Dragon' and is_defender_grounded:
                damage = int(damage * 0.5)
            
            damage = max(1, damage)

            damage, sash_log = item_logic.apply_on_before_damage(defender, damage)
            if sash_log:
                results["log"] += sash_log

            damage, sturdy_log = ability_effects.trigger_on_before_damage(defender, damage)
            if sturdy_log:
                results["log"] += sturdy_log
        else:
            damage = 0

        if hits_substitute:
            sub_hp = defender.volatiles['substitute']['hp']
            if damage >= sub_hp:
                del defender.volatiles['substitute']
                total_damage += sub_hp
                if hits_landed == 1: results['log'] += f"\nThe substitute took the damage for {defender.pokemon.name}!"
                results['log'] += f"\n{defender.pokemon.name}'s substitute was broken!"
                break
            else:
                defender.volatiles['substitute']['hp'] -= damage
                total_damage += damage
                if hits_landed == 1: results['log'] += f"\nThe substitute took the damage for {defender.pokemon.name}!"
        else:
            total_damage += damage

        if not hits_substitute and damage > 0:
            was_crit = is_crit if 'is_crit' in locals() else False
            # Call our new, specific trigger function
            results["log"] += ability_effects.trigger_on_after_move_damage(attacker, defender, battle, move_data, was_crit)

    if not hits_substitute and damage > 0:
        results["log"] += ability_effects.trigger_on_hp_threshold(defender, battle)

    results["damage_dealt"] = total_damage

    if results["did_hit"] and total_damage > 0 and not hits_substitute:
        results["log"] += ability_effects.trigger_on_taking_damage(attacker, defender, battle)
        results["log"] += item_logic.apply_on_taking_damage(defender, battle)

    if results["did_hit"] and total_damage > 0:
        # Handle Knock Off's item removal
        if move_id == 'knockoff' and _is_item_removable(defender):
            removed_item = defender.pokemon.item
            defender.pokemon.item = None
            results['log'] += f"\n{attacker.pokemon.name} knocked off {defender.pokemon.name}'s {removed_item}!"

        # Handle Thief/Covet item stealing
        elif move_id in ['thief', 'covet'] and not attacker.pokemon.item and _is_item_removable(defender):
            stolen_item = defender.pokemon.item
            attacker.pokemon.item = stolen_item
            defender.pokemon.item = None
            results['log'] += f"\n{attacker.pokemon.name} stole {defender.pokemon.name}'s {stolen_item}!"

        # Handle Incinerate's Berry/Gem removal
        elif move_id == 'incinerate':
            from bot.mechanics.item_data import ITEM_CATEGORIES
            # Simplified to only check for Berries for now
            if defender.pokemon.item in ITEM_CATEGORIES.get("Berries", []):
                burnt_item = defender.pokemon.item
                defender.pokemon.item = None
                results['log'] += f"\n{defender.pokemon.name}'s {burnt_item} was incinerated!"
        results["log"] += item_logic.apply_after_attack_effects(attacker, battle)

    if results["did_hit"] and move_id == 'rapidspin':
        if 'Ghost' not in defender.pokemon.types:
            user_hazards = battle.player1_hazards if attacker in battle.player1.team else battle.player2_hazards
            if user_hazards:
                user_hazards.clear()
                results['log'] += f"\n{attacker.pokemon.name} blew away the hazards!"
            
            if 'leechseed' in attacker.volatiles:
                del attacker.volatiles['leechseed']
                results['log'] += f"\n{attacker.pokemon.name} shook off the Leech Seed!"
    
            temp_move_data = {'boosts': {'spe': 1}}
            results['log'] += "\n" + handle_stat_boost_move(attacker, temp_move_data)
            
            
    results["hits"] = hits_landed

    if defender.volatiles.get('bide') and results["damage_dealt"] > 0:
        defender.volatiles['bide']['damage_taken'] += results["damage_dealt"]

    if move_data.get('drain'):
        drain_fraction = move_data['drain'][0] / move_data['drain'][1]
        drain_amount = int(total_damage * drain_fraction)
        attacker.current_hp = min(attacker.actual_stats['hp'], attacker.current_hp + drain_amount)
        results['log'] += f"\n{defender.pokemon.name} had its health drained!"

    if 'recoil' in move_data and total_damage > 0:
        if is_z_move_execution:
            results['log'] += f"\n{attacker.pokemon.name} was protected from recoil by Z-Power!"
            recoil_fraction = 0
        else:
            recoil_fraction = move_data['recoil'][0] / move_data['recoil'][1]

        if recoil_fraction > 0:
            results['recoil_damage'] = max(1, math.ceil(total_damage * recoil_fraction))

    if results["did_hit"] and move_data.get("flags", {}).get("contact"):
        # Call the item function with the two arguments it expects. NO CHANGE NEEDED IN item_logic.py.
        results["log"] += item_logic.apply_on_taking_contact_damage(attacker, defender)

        # Call the ability function with the three arguments IT expects.
        results["log"] += ability_effects.trigger_on_taking_contact_damage(attacker, defender, battle)

    secondary = move_data.get('secondary')
    # This is the new flag check for Sheer Force
    if secondary and not suppress_secondary and not hits_substitute:

        if secondary.get('terrain'):
            terrain_log = terrain_logic.set_terrain(battle, secondary['terrain'], 5)
            # Only add the log if the terrain was successfully set
            if "failed" not in terrain_log:
                results['log'] += "\n" + terrain_log
                results['update_image'] = True

        if not terrain_logic.is_protected_by_terrain(defender.pokemon, battle):
            
            # This is the new logic for Serene Grace
            chance = secondary.get('chance', 0)
            if attacker_ability_id == 'serenegrace':
                chance *= 2
            
            if secondary.get('status'):
                # The check now uses the modified `chance` variable
                if random.randint(1, 100) <= chance:
                    results["log"] += apply_status(secondary['status'], defender, move_data, battle)
            
            elif secondary.get('volatileStatus') == 'flinch':
                # Serene Grace also affects flinch chance
                if random.randint(1, 100) <= chance:
                    # Capture the log from handle_flinch_move (it will be non-empty only if immune)
                    flinch_log = handle_flinch_move(defender, move_data)
                    if flinch_log:
                        results["log"] += flinch_log

            elif secondary.get('volatileStatus') == 'confusion':
                if random.randint(1, 100) <= chance:
                    if 'confusion' not in defender.volatiles:
                        defender.volatiles['confusion'] = random.randint(1, 4)
                        results["log"] += f"\n{defender.pokemon.name} became confused!"
            
            elif secondary.get('boosts'):
                if random.randint(1, 100) <= chance:
                    results["log"] += "\n" + handle_stat_boost_move(defender, secondary)

            if secondary.get('self') and secondary.get('self').get('boosts'):
                # Use the same 'chance' variable from a few lines above
                if random.randint(1, 100) <= chance:
                    # Apply the boost to the ATTACKER, not the defender
                    results["log"] += "\n" + handle_stat_boost_move(attacker, secondary.get('self'))
    
    if results["did_hit"] and move_data.get('volatileStatus') == 'partiallytrapped':
        if 'trap' not in defender.volatiles:
            defender.volatiles['trap'] = {
                'duration': random.randint(4, 5),
                'source_move': move_id
            }
            results['log'] += f"\n{defender.pokemon.name} was trapped by {move_data['name']}!"

    if results["did_hit"] and move_data.get('forceSwitch'):
        # Check if the target is Dynamaxed
        if 'dynamax' in defender.volatiles:
            results['log'] += "\nBut it failed against the Dynamax Pokémon!"
        else:
            results['force_opponent_switch'] = True

    if results["did_hit"] and is_z_move_execution:
        # Check for both "selfBoost" (from your JSON) and "self" for safety
        z_move_self_effect = move_data.get('selfBoost') or move_data.get('self')
        if z_move_self_effect and z_move_self_effect.get('boosts'):
            results["log"] += "\n" + handle_stat_boost_move(attacker, z_move_self_effect)
        
    self_effect = move_data.get('self')
    if not is_z_move_execution and self_effect and results["did_hit"]:
        if self_effect.get('volatileStatus') == 'lockedmove':
            if 'lockedmove' not in attacker.volatiles:
                attacker.volatiles['lockedmove'] = {
                    'move_id': move_id,
                    'turns': random.randint(2, 3)
                }
        elif self_effect.get('volatileStatus') == 'mustrecharge':
            attacker.volatiles['mustrecharge'] = True
            
        if self_effect.get('boosts'):
            temp_move_data = {'boosts': self_effect.get('boosts')}
            results['log'] += "\n" + handle_stat_boost_move(attacker, temp_move_data)
    
    if results["did_hit"] and move_data.get('selfSwitch'):
        # --- START of Fix ---
        attacker_player = battle.get_player(attacker.pokemon.pokemon_uuid)
        if not attacker_player: # Failsafe
            attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2

        # Check if there is at least one OTHER conscious Pokémon on the team
        can_switch = any(p.current_hp > 0 and i != attacker_player.active_pokemon_index
                         for i, p in enumerate(attacker_player.team))

        if can_switch:
            # Only set force_switch if a valid switch exists
            results['force_switch'] = True
            if move_id == 'batonpass':
                results['is_baton_pass'] = True
                # Baton Pass specific data transfer is handled later in the turn handler
            # Apply secondary effects ONLY if switching (like Parting Shot drops)
            elif move_data.get('boosts'): # Check if the move itself has boosts (like Parting Shot)
                 # Apply stat drops to the DEFENDER
                 results['log'] += handle_stat_boost_move(defender, move_data)
        else:
            # If no one to switch to, the switch part fails
            results['log'] += "\nBut there was no one to switch to!"
            # Baton Pass fails entirely if there's no target
            if move_id == 'batonpass':
                 results['log'] = "\nBut it failed!" # Override previous log as the whole move fails
            # Parting Shot still applies its stat drops even if the switch fails
            elif move_id == 'partingshot' and move_data.get('boosts'):
                 # Ensure stat drops apply to defender even if switch fails
                 results['log'] += handle_stat_boost_move(defender, move_data)

    if results["did_hit"] and move_data.get("isMax"):
        max_log, needs_image_update = _handle_max_move_effects(move_id, attacker, defender, battle)
        results['log'] += max_log
        if needs_image_update:
            results['update_image'] = True
    
    if results["did_hit"] and isinstance(move_data.get("isMax"), str):
        gmax_log, needs_image_update_gmax = _handle_gmax_move_effects(move_id, attacker, defender, battle)
        results['log'] += gmax_log
        if needs_image_update_gmax:
            results['update_image'] = True

    if move_data.get('selfdestruct'):
        if move_data.get('selfdestruct') == 'always':
            attacker.current_hp = 0
        elif move_data.get('selfdestruct') == 'ifHit' and results["did_hit"]:
            attacker.current_hp = 0

    if results["did_hit"] and move_data.get('selfSwitch'):
        
        attacker_player = battle.get_player(attacker.pokemon.pokemon_uuid)
        if not attacker_player:
             attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
        
        can_switch = any(p.current_hp > 0 and i != attacker_player.active_pokemon_index for i, p in enumerate(attacker_player.team))

        if can_switch:
            results['force_switch'] = True
            if move_id == 'batonpass':
                results['is_baton_pass'] = True
    # --- END OF BLOCK ---

    results['final_move_name'] = move_data['name']

    return results
    
def get_move_order(battle: Battle) -> list[tuple[BattlePlayer, ActivePokemon, str]]:
    # This function needs to be updated to use the new get_modified_stat
    p1 = battle.player1
    p2 = battle.player2
    poke1 = p1.get_active_pokemon()
    poke2 = p2.get_active_pokemon()

    # --- MODIFIED LINES ---
    speed1 = get_modified_stat(poke1, 'spe')
    speed2 = get_modified_stat(poke2, 'spe')
    # --- END OF MODIFICATION ---

    if battle.player1_tailwind_turns > 0: speed1 *= 2
    if battle.player2_tailwind_turns > 0: speed2 *= 2

    if poke1.status == 'par': speed1 *= 0.5
    if poke2.status == 'par': speed2 *= 0.5

    # This part of the logic needs to be tied to the move choice, which happens later.
    # We will adjust this in the turn handler. For now, this determines speed tie.
    
    player1_data = (p1, poke1)
    player2_data = (p2, poke2)
    
    if battle.trick_room_turns > 0:
        if speed1 == speed2: return random.sample([player1_data, player2_data], 2)
        return [player1_data, player2_data] if speed1 < speed2 else [player2_data, player1_data]
    else:
        if speed1 == speed2: return random.sample([player1_data, player2_data], 2)
        return [player1_data, player2_data] if speed1 > speed2 else [player2_data, player1_data]

def _is_item_removable(pokemon: "ActivePokemon"):
    if not pokemon.pokemon.item:
        return False
    # This list can be expanded with Mega Stones, Z-Crystals, etc.
    unremovable_items = ['redorb', 'blueorb', 'griseousorb'] 
    item_id = ITEM_ID_BY_NAME.get(pokemon.pokemon.item, "").lower()
    if item_id in unremovable_items:
        return False
    # A full implementation would also check for the Sticky Hold ability here
    return True