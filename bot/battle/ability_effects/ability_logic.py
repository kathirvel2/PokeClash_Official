# ./bot/battle/ability_effects/ability_logic.py

import random
from typing import TYPE_CHECKING
from bot.battle.field_effects import weather as weather_logic
if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, ActivePokemon
from bot.mechanics.moves_loader import SPECIES_BY_ID
from bot.battle.battle_utils import get_actual_stats
from bot.mechanics.moves_loader import MOVE_BY_ID

def intimidate(attacker: "ActivePokemon", battle: "Battle") -> str:
    """
    The logic for the Intimidate ability.
    Lowers the opponent's Attack stat by one stage.
    """
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    opponent_player, opponent_pokemon = battle.get_opponent_for_player(attacker_player)

    opponent_ability_id = opponent_pokemon.pokemon.ability.lower().replace(" ", "")
    if opponent_ability_id in ['clearbody', 'whitesmoke', 'hypercutter', 'fullmetalbody', 'guarddog']:
        if opponent_ability_id == 'guarddog':
             log = f"\n{opponent_pokemon.pokemon.name}'s Guard Dog prevents intimidation!"
             log += "\n" + handle_stat_boost_move(opponent_pokemon, {'boosts': {'atk': 1}})
             return log
        return f"\n{opponent_pokemon.pokemon.name}'s {opponent_pokemon.pokemon.ability} prevents its stats from being lowered!"

    if 'substitute' in opponent_pokemon.volatiles:
        return f"\nBut {opponent_pokemon.pokemon.name} is protected by its substitute!"

    stat_change_data = {'boosts': {'atk': -1}}
    
    log = f"\n{attacker.pokemon.name}'s Intimidate cuts {opponent_pokemon.pokemon.name}'s Attack!"
    log += "\n" + handle_stat_boost_move(opponent_pokemon, stat_change_data)
    
    return log

def adaptability(attacker: "ActivePokemon") -> float:
    """
    Checks if the STAB multiplier should be 2.0 for Adaptability.
    Returns the appropriate STAB multiplier.
    """
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if ability_id == 'adaptability':
        return 2.0
    
    # Return the default STAB if the ability is not Adaptability
    return 1.5

def handle_ate_abilities(attacker: "ActivePokemon", move_data: dict) -> tuple[dict, float]:
    """
    Handles abilities like Aerilate, Pixilate, etc.
    Changes the move's type and returns a power multiplier.
    MODIFIED: Now includes Galvanize, Pixilate, Refrigerate, and Liquid Voice.
    """
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    power_multiplier = 1.0
    
    # Map for -ate abilities that change Normal-type moves
    ate_map = {
        'aerilate': 'Flying',
        'pixilate': 'Fairy',
        'refrigerate': 'Ice',
        'galvanize': 'Electric',
        'normalize': 'Normal' # Normalize makes all moves Normal-type
    }

    # Handle -ate abilities
    if ability_id in ate_map:
        # Normalize affects ALL move types
        if ability_id == 'normalize':
            move_data['type'] = 'Normal'
            power_multiplier = 1.2
        # Other -ate abilities only affect Normal-type moves
        elif move_data.get('type') == 'Normal':
            move_data['type'] = ate_map[ability_id]
            power_multiplier = 1.2

    # Handle Liquid Voice separately as it affects sound moves
    elif ability_id == 'liquidvoice':
        if move_data.get('flags', {}).get('sound'):
            move_data['type'] = 'Water'
            # Note: Liquid Voice does not provide a power boost

    return move_data, power_multiplier

def air_lock(attacker: "ActivePokemon", battle: "Battle") -> str:
    """
    Announces the presence of Air Lock or Cloud Nine.
    """
    return f"\nThe effects of weather were negated by {attacker.pokemon.name}'s {attacker.pokemon.ability}!"

def set_drizzle_weather(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Drizzle ability."""
    return weather_logic.set_weather(battle, 'raindance', attacker)

def set_drought_weather(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Drought ability."""
    return weather_logic.set_weather(battle, 'sunnyday', attacker)

def set_sandstorm_weather(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Sand Stream ability."""
    return weather_logic.set_weather(battle, 'sandstorm', attacker)

def set_hail_weather(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Snow Warning ability."""
    return weather_logic.set_weather(battle, 'hail', attacker)

def check_levitate(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity from Levitate. Returns (should_stop, log_message)."""
    if move_data['type'] != 'Ground':
        return False, ""
    
    if battle.gravity_turns > 0:
        return False, ""
        
    return True, f"\nIt doesn't affect {defender.pokemon.name}..."

def check_volt_absorb(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and healing from Volt Absorb. Returns (should_stop, log_message)."""
    if move_data['type'] != 'Electric':
        return False, ""

    heal_amount = defender.actual_stats['hp'] // 4
    
    if defender.current_hp < defender.actual_stats['hp']:
        defender.current_hp = min(defender.actual_stats['hp'], defender.current_hp + heal_amount)
        log_message = f"\n{defender.pokemon.name} restored HP using its {defender.pokemon.ability}!"
    else:
        log_message = f"\nIt doesn't affect {defender.pokemon.name}..."

    return True, log_message

def check_water_absorb(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and healing from Water Absorb."""
    if move_data['type'] != 'Water':
        return False, ""

    heal_amount = defender.actual_stats['hp'] // 4
    if defender.current_hp < defender.actual_stats['hp']:
        defender.current_hp = min(defender.actual_stats['hp'], defender.current_hp + heal_amount)
        log_message = f"\n{defender.pokemon.name} restored HP using its {defender.pokemon.ability}!"
    else:
        log_message = f"\nIt doesn't affect {defender.pokemon.name}..."

    return True, log_message

def check_flash_fire(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and power boost from Flash Fire."""
    if move_data['type'] != 'Fire':
        return False, ""

    defender.volatiles['flashfire'] = True
    
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} made it immune!"
    return True, log_message

def check_motor_drive(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and Speed boost from Motor Drive."""
    if move_data['type'] != 'Electric':
        return False, ""
    
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    boost_data = {'boosts': {'spe': 1}}
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its Speed!"
    log_message += "\n" + handle_stat_boost_move(defender, boost_data)
    
    return True, log_message

def check_storm_drain(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and Special Attack boost from Storm Drain."""
    if move_data['type'] != 'Water':
        return False, ""

    from bot.battle.move_effects.status_moves import handle_stat_boost_move
        
    boost_data = {'boosts': {'spa': 1}}
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its Sp. Atk!"
    log_message += "\n" + handle_stat_boost_move(defender, boost_data)

    return True, log_message

def handle_natural_cure(pokemon: "ActivePokemon", battle: "Battle") -> str:
    """Cures the user's major status condition upon switching out."""
    if pokemon.status is not None:
        pokemon.status = None
        pokemon.status_counter = 0
        return f"{pokemon.pokemon.name}'s {pokemon.pokemon.ability} cured its status!"
    return ""

def handle_regenerator(pokemon: "ActivePokemon", battle: "Battle") -> str:
    """Heals the user by 1/3 of its max HP upon switching out."""
    if pokemon.current_hp > 0 and pokemon.current_hp < pokemon.actual_stats['hp']:
        heal_amount = pokemon.actual_stats['hp'] // 3
        pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
        return f"{pokemon.pokemon.name} regenerated health with its {pokemon.pokemon.ability}!"
    return ""

def check_static(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for a 30% chance to paralyze on contact."""
    from bot.battle.move_effects.status import apply_status
    if random.randint(1, 100) <= 30:
        dummy_move_data = {'secondary': {'status': 'par', 'chance': 100}}
        return apply_status('par', attacker, dummy_move_data, battle)
    return ""

def check_poison_point(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for a 30% chance to poison on contact."""
    from bot.battle.move_effects.status import apply_status
    if random.randint(1, 100) <= 30:
        dummy_move_data = {'secondary': {'status': 'psn', 'chance': 100}}
        return apply_status('psn', attacker, dummy_move_data, battle)
    return ""

def check_flame_body(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for a 30% chance to burn on contact."""
    from bot.battle.move_effects.status import apply_status
    if random.randint(1, 100) <= 30:
        dummy_move_data = {'secondary': {'status': 'brn', 'chance': 100}}
        return apply_status('brn', attacker, dummy_move_data, battle)
    return ""

def check_soundproof(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity from Soundproof. Returns (should_stop, log_message)."""
    if move_data.get('flags', {}).get('sound'):
        return True, f"\n{defender.pokemon.name}'s Soundproof blocks the move!"
    return False, ""

def check_magma_armor(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Magma Armor prevents freezing."""
    if status_to_apply == 'frz':
        return True, f"\n{target.pokemon.name}'s Magma Armor prevents freezing!"
    return False, ""

def check_water_veil(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Water Veil prevents burns."""
    if status_to_apply == 'brn':
        return True, f"\n{target.pokemon.name}'s Water Veil prevents burns!"
    return False, ""

def check_sleep_immunity(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Insomnia or Vital Spirit prevents sleep."""
    if status_to_apply == 'slp':
        return True, f"\n{target.pokemon.name}'s {target.pokemon.ability} prevents sleep!"
    return False, ""

def prevent_stat_lower_general(target: "ActivePokemon", boosts: dict) -> tuple[bool, str]:
    """Prevents any stat from being lowered (Clear Body, White Smoke)."""
    if any(value < 0 for value in boosts.values()):
        return True, f"\n{target.pokemon.name}'s {target.pokemon.ability} prevents its stats from being lowered!"
    return False, ""

def prevent_stat_lower_specific(target: "ActivePokemon", boosts: dict, stat_to_protect: str) -> tuple[bool, str]:
    """Prevents a specific stat from being lowered (Hyper Cutter, Big Pecks)."""
    if boosts.get(stat_to_protect, 0) < 0:
        stat_name = {"atk": "Attack", "def": "Defense"}.get(stat_to_protect, "stats")
        return True, f"\n{target.pokemon.name}'s {target.pokemon.ability} prevents its {stat_name} from being lowered!"
    return False, ""

def check_sap_sipper(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and Attack boost from Sap Sipper."""
    if move_data['type'] != 'Grass':
        return False, ""

    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    boost_data = {'boosts': {'atk': 1}}
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its Attack!"
    log_message += "\n" + handle_stat_boost_move(defender, boost_data)
    
    return True, log_message

def check_lightning_rod(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and Special Attack boost from Lightning Rod."""
    if move_data['type'] != 'Electric':
        return False, ""

    from bot.battle.move_effects.status_moves import handle_stat_boost_move
        
    boost_data = {'boosts': {'spa': 1}}
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its Sp. Atk!"
    log_message += "\n" + handle_stat_boost_move(defender, boost_data)

    return True, log_message

def check_bulletproof(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity from Bulletproof against ball and bomb moves."""
    if move_data.get('flags', {}).get('bullet'):
        return True, f"\n{defender.pokemon.name}'s Bulletproof blocks the move!"
    return False, ""

def check_disguise(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for and breaks Mimikyu's Disguise, blocking all damage from the hit."""
    if defender.pokemon.id != 'mimikyu':
        return False, ""

    if move_data['category'] == 'Status':
        return False, ""

    log_message = f"\n{defender.pokemon.name}'s Disguise was busted!"
    
    busted_form_id = 'mimikyubusted'
    busted_form_data = SPECIES_BY_ID.get(busted_form_id)
    if busted_form_data:
        defender.pokemon.id = busted_form_id
        defender.pokemon.name = busted_form_data['name']
        defender.actual_stats = get_actual_stats(defender.pokemon)

    return True, log_message

def check_ice_face(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for and breaks Eiscue's Ice Face."""
    if defender.pokemon.id != 'eiscue' or move_data['category'] != 'Physical':
        return False, ""

    log_message = f"\n{defender.pokemon.name}'s Ice Face was broken!"
    
    noice_form_id = 'eiscuenoice'
    noice_form_data = SPECIES_BY_ID.get(noice_form_id)
    if noice_form_data:
        defender.pokemon.id = noice_form_id
        defender.pokemon.name = noice_form_data['name']
        defender.actual_stats = get_actual_stats(defender.pokemon)

    return True, log_message

def restore_ice_face(pokemon: "ActivePokemon", battle: "Battle") -> str:
    """Restores Eiscue's Ice Face if it is hailing."""
    if pokemon.pokemon.id == 'eiscuenoice' and battle.active_weather == 'hail':
        ice_form_id = 'eiscue'
        ice_form_data = SPECIES_BY_ID.get(ice_form_id)
        if ice_form_data:
            pokemon.pokemon.id = ice_form_id
            pokemon.pokemon.name = ice_form_data['name']
            pokemon.actual_stats = get_actual_stats(pokemon.pokemon)
            return f"\n{pokemon.pokemon.name} restored its Ice Face in the hail!"
    return ""

def check_immunity(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Immunity prevents poisoning."""
    if status_to_apply in ['psn', 'tox']:
        return True, f"\n{target.pokemon.name}'s Immunity prevents poisoning!"
    return False, ""

def check_limber(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Limber prevents paralysis."""
    if status_to_apply == 'par':
        return True, f"\n{target.pokemon.name}'s Limber prevents paralysis!"
    return False, ""

def check_own_tempo(volatile_status: str, target: "ActivePokemon", attacker: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Own Tempo prevents confusion."""
    if volatile_status == 'confusion':
        return True, f"\n{target.pokemon.name}'s Own Tempo prevents confusion!"
    return False, ""

def check_oblivious(volatile_status: str, target: "ActivePokemon", attacker: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Oblivious prevents infatuation."""
    if volatile_status == 'infatuation':
        return True, f"\n{target.pokemon.name}'s Oblivious prevents it from being infatuated with {attacker.pokemon.name}!"
    return False, ""

def check_gooey_or_tangling_hair(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for Gooey/Tangling Hair to lower speed on contact."""
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'longreach':
        return ""
        
    boost_data = {'boosts': {'spe': -1}}
    return handle_stat_boost_move(attacker, boost_data)

def check_iron_barbs_or_rough_skin(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for Iron Barbs/Rough Skin to deal damage on contact."""
    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'longreach':
        return ""

    damage = max(1, attacker.actual_stats['hp'] // 8)
    attacker.current_hp = max(0, attacker.current_hp - damage)
    return f"\n{attacker.pokemon.name} was hurt by {defender.pokemon.name}'s {defender.pokemon.ability}!"

def check_effect_spore(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for Effect Spore to apply a random status on contact."""
    from bot.battle.move_effects.status import apply_status
    
    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'longreach':
        return ""

    if random.randint(1, 100) <= 30:
        status_to_apply = random.choice(['psn', 'par', 'slp'])
        dummy_move_data = {'secondary': {'status': status_to_apply, 'chance': 100}}
        return apply_status(status_to_apply, attacker, dummy_move_data, battle)
    return ""

def check_aroma_veil(volatile_status: str, target: "ActivePokemon", attacker: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Aroma Veil prevents infatuation, taunt, encore, etc."""
    blocked_volatiles = ['infatuation', 'taunt', 'encore', 'disable']
    
    if volatile_status in blocked_volatiles:
        return True, f"\n{target.pokemon.name}'s Aroma Veil protects it from {volatile_status}!"
    return False, ""

def anticipation(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Anticipation ability."""
    from bot.battle.battle_logic import TYPE_CHART
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    
    _, opponent = battle.get_opponent_for_player(attacker_player)
    
    ohko_moves = ['fissure', 'guillotine', 'horndrill', 'sheercold']

    for move_id in opponent.pokemon.moves:
        move_data = MOVE_BY_ID.get(move_id, {})
        if not move_data:
            continue
            
        if move_id in ohko_moves:
            return f"\n{attacker.pokemon.name}'s Anticipation made it shudder!"
            
        move_type = move_data.get('type')
        if move_type and move_data.get('category') != 'Status':
            effectiveness = 1.0
            for defender_type in attacker.pokemon.types:
                effectiveness *= TYPE_CHART.get(move_type.lower(), {}).get(defender_type.lower(), 1.0)
            
            if effectiveness >= 2:
                return f"\n{attacker.pokemon.name}'s Anticipation made it shudder!"
                
    return ""

def handle_passive_power_boost(attacker: "ActivePokemon", move_data: dict) -> float:
    """
    Handles abilities that boost the power of certain move types (Strong Jaw, Iron Fist, etc.).
    Returns a power multiplier.
    """
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    move_flags = move_data.get('flags', {})
    
    boost_map = {
        'strongjaw': ('bite', 1.5),
        'toughclaws': ('contact', 1.3),
        'ironfist': ('punch', 1.2),
        'sharpness': ('slicing', 1.5)
    }
    
    if ability_id in boost_map:
        flag_to_check, multiplier = boost_map[ability_id]
        if move_flags.get(flag_to_check):
            return multiplier
            
    return 1.0

def handle_permanent_stat_multiply(pokemon: "ActivePokemon"):
    """
    Handles abilities that multiply a stat for the duration of a battle,
    like Huge Power, Fur Coat, and Gorilla Tactics.
    """
    ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
    
    if ability_id in ['hugepower', 'purepower']:
        pokemon.stat_multipliers['atk'] *= 2
        
    elif ability_id == 'furcoat':
        pokemon.stat_multipliers['def'] *= 2
        
    elif ability_id == 'gorillatactics':
        pokemon.stat_multipliers['atk'] *= 1.5

def handle_on_ko_boosts(attacker: "ActivePokemon", battle: "Battle") -> str:
    """
    Handles abilities like Moxie and Beast Boost that trigger on a KO.
    """
    from bot.battle.move_effects.status_moves import handle_stat_boost_move

    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    boost_data = None
    log_message = ""

    if ability_id == 'moxie':
        boost_data = {'boosts': {'atk': 1}}
    elif ability_id == 'chillingneigh':
        boost_data = {'boosts': {'atk': 1}}
    elif ability_id == 'grimneigh':
        boost_data = {'boosts': {'spa': 1}}
    elif ability_id == 'beastboost':
        stats = attacker.actual_stats
        highest_stat_name = ""
        highest_stat_value = 0
        
        stat_order = ['atk', 'def', 'spa', 'spd', 'spe']
        for stat_name in stat_order:
            if stats[stat_name] > highest_stat_value:
                highest_stat_value = stats[stat_name]
                highest_stat_name = stat_name
        
        if highest_stat_name:
            boost_data = {'boosts': {highest_stat_name: 1}}
            log_message = f"\n{attacker.pokemon.name}'s Beast Boost raised its {highest_stat_name.upper()}!"


    if boost_data:
        if not log_message:
            log_message = f"\n{attacker.pokemon.name}'s {attacker.pokemon.ability} activated!"
            
        return log_message + "\n" + handle_stat_boost_move(attacker, boost_data)

    return ""

def handle_on_taking_damage_boosts(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """
    Handles abilities that trigger stat changes after taking damage,
    like Stamina and Weak Armor.
    """
    from bot.battle.move_effects.status_moves import handle_stat_boost_move

    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    boost_data = None
    log_message = ""

    if ability_id == 'stamina':
        boost_data = {'boosts': {'def': 1}}
    elif ability_id == 'weakarmor':
        boost_data = {'boosts': {'def': -1, 'spe': 2}}

    if boost_data:
        log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} activated!"
        log_message += "\n" + handle_stat_boost_move(defender, boost_data)
    
    return log_message

def handle_stat_lowered_boosts(target: "ActivePokemon", battle: "Battle") -> str:
    """
    Handles abilities that boost stats when another stat is lowered by an opponent,
    like Competitive and Defiant.
    """
    from bot.battle.move_effects.status_moves import handle_stat_boost_move

    ability_id = target.pokemon.ability.lower().replace(" ", "")
    boost_data = None
    log_message = ""

    if ability_id == 'competitive':
        boost_data = {'boosts': {'spa': 2}}
    elif ability_id == 'defiant':
        boost_data = {'boosts': {'atk': 2}}

    if boost_data:
        log_message = f"\n{target.pokemon.name}'s {target.pokemon.ability} activated!"
        log_message += "\n" + handle_stat_boost_move(target, boost_data)
    
    return log_message

def check_earth_eater(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and healing from Earth Eater."""
    if move_data['type'] != 'Ground':
        return False, ""

    heal_amount = defender.actual_stats['hp'] // 4
    if defender.current_hp < defender.actual_stats['hp']:
        defender.current_hp = min(defender.actual_stats['hp'], defender.current_hp + heal_amount)
        log_message = f"\n{defender.pokemon.name} restored HP using its {defender.pokemon.ability}!"
    else:
        log_message = f"\nIt doesn't affect {defender.pokemon.name}..."

    return True, log_message

def check_well_baked_body(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and Defense boost from Well-Baked Body."""
    if move_data['type'] != 'Fire':
        return False, ""

    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    boost_data = {'boosts': {'def': 2}}
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its Defense!"
    log_message += "\n" + handle_stat_boost_move(defender, boost_data)
    
    return True, log_message

def check_wind_rider(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and Attack boost from Wind Rider."""
    if not move_data.get('flags', {}).get('wind'):
        return False, ""

    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    boost_data = {'boosts': {'atk': 1}}
    log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its Attack!"
    log_message += "\n" + handle_stat_boost_move(defender, boost_data)
    
    return True, log_message

def handle_aftermath(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Deals damage to the attacker if the defender faints from a contact move."""
    if not defender.volatiles.get('last_hit_by_contact'):
        return ""

    attacker_ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    if attacker_ability_id == 'damp':
        return f"\n{attacker.pokemon.name}'s Damp prevents the explosion!"
        
    damage = max(1, attacker.actual_stats['hp'] // 4)
    attacker.current_hp = max(0, attacker.current_hp - damage)
    return f"\n{attacker.pokemon.name} was caught in the aftermath! It lost {damage} HP!"

def check_cute_charm(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for a 30% chance to infatuate on contact if genders are opposite."""
    from bot.mechanics.moves_loader import SPECIES_BY_ID
    
    if random.randint(1, 100) > 30:
        return ""

    attacker_gender = SPECIES_BY_ID.get(attacker.pokemon.id, {}).get('gender')
    defender_gender = SPECIES_BY_ID.get(defender.pokemon.id, {}).get('gender')

    if not attacker_gender or not defender_gender or attacker_gender == defender_gender:
        return ""

    if 'infatuation' not in attacker.volatiles:
        attacker.volatiles['infatuation'] = True
        return f"\n{attacker.pokemon.name} fell in love with {defender.pokemon.name}!"
    return ""

def check_cursed_body(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks for a 30% chance to disable the attacker's last move on contact."""
    if random.randint(1, 100) > 30:
        return ""

    last_move = attacker.last_move_used
    if not last_move or 'disable' in attacker.volatiles:
        return ""

    attacker.volatiles['disable'] = {'turns': 4, 'move_id': last_move}
    move_name = MOVE_BY_ID.get(last_move, {}).get('name', 'the last move')
    return f"\n{defender.pokemon.name}'s Cursed Body disabled {attacker.pokemon.name}'s {move_name}!"

def handle_ability_change_on_contact(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Handles Mummy and Wandering Spirit, which change the attacker's ability on contact."""
    new_ability_name = defender.pokemon.ability
    
    if attacker.pokemon.ability == new_ability_name or attacker.pokemon.ability in ["Multitype", "RKS System"]:
        return ""

    if new_ability_name == "Mummy":
        attacker.pokemon.ability = "Mummy"
        attacker.ability_is_swapped = True
        return f"\n{attacker.pokemon.name}'s Ability became Mummy!"
    elif new_ability_name == "Wandering Spirit":
        attacker.pokemon.ability, defender.pokemon.ability = defender.pokemon.ability, attacker.pokemon.ability
        attacker.ability_is_swapped, defender.ability_is_swapped = True, True
        return f"\n{defender.pokemon.name} swapped its Wandering Spirit with {attacker.pokemon.name}'s ability!"
    
    return ""

def check_sturdy(defender: "ActivePokemon", damage: int) -> tuple[int, str]:
    """Checks if Sturdy should activate to survive a hit."""
    if defender.current_hp == defender.actual_stats['hp'] and damage >= defender.current_hp:
        return defender.current_hp - 1, f"\n{defender.pokemon.name} held on using its Sturdy!"
    return damage, ""

def set_electric_terrain(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Electric Surge ability."""
    from bot.battle.field_effects import terrain as terrain_logic
    if battle.active_terrain is None:
        return terrain_logic.set_terrain(battle, 'electricterrain', 5)
    return ""

def set_grassy_terrain(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Grassy Surge ability."""
    from bot.battle.field_effects import terrain as terrain_logic
    if battle.active_terrain is None:
        return terrain_logic.set_terrain(battle, 'grassyterrain', 5)
    return ""

def set_misty_terrain(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Misty Surge ability."""
    from bot.battle.field_effects import terrain as terrain_logic
    if battle.active_terrain is None:
        return terrain_logic.set_terrain(battle, 'mistyterrain', 5)
    return ""

def set_psychic_terrain(attacker: "ActivePokemon", battle: "Battle") -> str:
    """The logic for the Psychic Surge ability."""
    from bot.battle.field_effects import terrain as terrain_logic
    if battle.active_terrain is None:
        return terrain_logic.set_terrain(battle, 'psychicterrain', 5)
    return ""

def check_dry_skin(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity and healing from Dry Skin."""
    if move_data['type'] != 'Water':
        return False, ""

    heal_amount = defender.actual_stats['hp'] // 4
    if defender.current_hp < defender.actual_stats['hp']:
        defender.current_hp = min(defender.actual_stats['hp'], defender.current_hp + heal_amount)
        log_message = f"\n{defender.pokemon.name} restored HP using its {defender.pokemon.ability}!"
    else:
        log_message = f"\nIt doesn't affect {defender.pokemon.name}..."

    return True, log_message

def check_inner_focus(volatile_status: str, target: "ActivePokemon", attacker: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Inner Focus prevents flinching."""
    if volatile_status == 'flinch':
        return True, f"\n{target.pokemon.name}'s Inner Focus prevents flinching!"
    return False, ""

def check_leaf_guard(status_to_apply: str, target: "ActivePokemon", battle: "Battle") -> tuple[bool, str]:
    """Checks if Leaf Guard prevents status conditions in harsh sunlight."""
    from bot.battle.ability_effects import is_weather_suppressed
    if battle.active_weather == 'sunnyday' and not is_weather_suppressed(battle):
        return True, f"\n{target.pokemon.name}'s Leaf Guard prevents status conditions in the sun!"
    return False, ""

def check_comatose(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Comatose prevents all status conditions."""
    return True, f"\n{target.pokemon.name}'s Comatose prevents status conditions!"

def check_purifying_salt_status(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Purifying Salt prevents status conditions."""
    return True, f"\n{target.pokemon.name}'s Purifying Salt prevents status conditions!"

def check_pastel_veil(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Pastel Veil prevents poisoning."""
    if status_to_apply in ['psn', 'tox']:
        return True, f"\n{target.pokemon.name}'s Pastel Veil prevents poisoning!"
    return False, ""

def check_sweet_veil(status_to_apply: str, target: "ActivePokemon") -> tuple[bool, str]:
    """Checks if Sweet Veil prevents sleep."""
    if status_to_apply == 'slp':
        return True, f"\n{target.pokemon.name}'s Sweet Veil prevents sleep!"
    return False, ""

def handle_pinch_abilities(attacker: "ActivePokemon", move_data: dict) -> float:
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    hp_percent = (attacker.current_hp / attacker.actual_stats['hp']) * 100

    pinch_map = {
        'blaze': 'Fire',
        'torrent': 'Water',
        'overgrow': 'Grass'
    }

    if ability_id in pinch_map and hp_percent <= (100 / 3):
        if move_data.get('type') == pinch_map[ability_id]:
            return 1.5

    return 1.0

def handle_pure_type_boost(attacker: "ActivePokemon", move_data: dict) -> float:
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")

    boost_map = {
        'transistor': ('Electric', 1.3),
        'dragonsmaw': ('Dragon', 1.5),
        'steelworker': ('Steel', 1.5),
        'rockypayload': ('Rock', 1.5)
    }

    if ability_id in boost_map:
        boost_type, multiplier = boost_map[ability_id]
        if move_data.get('type') == boost_type:
            return multiplier

    return 1.0
    
def handle_field_effect_boosts(attacker: "ActivePokemon", move_data: dict, battle: "Battle") -> float:
    """
    NEW: Handles abilities that boost move power in certain weather,
    like Sand Force.
    """
    from bot.battle.ability_effects import is_weather_suppressed
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")

    if is_weather_suppressed(battle):
        return 1.0

    if ability_id == 'sandforce' and battle.active_weather == 'sandstorm':
        if move_data.get('type') in ['Rock', 'Ground', 'Steel']:
            return 1.3

    return 1.0

def handle_damage_reduction_abilities(defender: "ActivePokemon", move_data: dict, effectiveness: float) -> float:
    """
    NEW: Handles abilities that reduce incoming damage based on move properties.
    This function ONLY contains logic for NEWLY implemented abilities.
    """
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    multiplier = 1.0

    if ability_id == 'icescales' and move_data.get('category') == 'Special':
        multiplier *= 0.5

    if ability_id == 'heatproof' and move_data.get('type') == 'Fire':
        multiplier *= 0.5

    if ability_id == 'punkrock' and move_data.get('flags', {}).get('sound'):
        multiplier *= 0.5
        
    if ability_id == 'fluffy':
        if move_data.get('flags', {}).get('contact'):
            multiplier *= 0.5
        if move_data.get('type') == 'Fire':
            multiplier *= 2.0

    return multiplier

def handle_opportunist(user: "ActivePokemon", opponent: "ActivePokemon", boosts: dict, battle: "Battle") -> str:
    """Copies the opponent's stat boosts."""
    from bot.battle.move_effects.status_moves import handle_stat_boost_move

    positive_boosts = {stat: value for stat, value in boosts.items() if value > 0}

    if not positive_boosts:
        return ""

    log = f"\n{user.pokemon.name}'s Opportunist copied the stat change!"
    log += "\n" + handle_stat_boost_move(user, {'boosts': positive_boosts})

    return log

def download(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Download ability."""
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    _, opponent = battle.get_opponent_for_player(attacker_player)
    
    def_stat = opponent.actual_stats['def']
    spd_stat = opponent.actual_stats['spd']
    
    if def_stat < spd_stat:
        boost_data = {'boosts': {'atk': 1}}
    else:
        boost_data = {'boosts': {'spa': 1}}
        
    log = f"\n{attacker.pokemon.name}'s Download activated!"
    log += "\n" + handle_stat_boost_move(attacker, boost_data)
    return log

def dauntless_shield(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Dauntless Shield ability."""
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    boost_data = {'boosts': {'def': 1}}
    log = f"\n{attacker.pokemon.name}'s Dauntless Shield boosted its Defense!"
    log += "\n" + handle_stat_boost_move(attacker, boost_data)
    return log

def intrepid_sword(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Intrepid Sword ability."""
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    boost_data = {'boosts': {'atk': 1}}
    log = f"\n{attacker.pokemon.name}'s Intrepid Sword boosted its Attack!"
    log += "\n" + handle_stat_boost_move(attacker, boost_data)
    return log

def screen_cleaner(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Screen Cleaner ability."""
    if battle.player1_screens or battle.player2_screens:
        battle.player1_screens.clear()
        battle.player2_screens.clear()
        return f"\n{attacker.pokemon.name}'s Screen Cleaner removed all screens from the field!"
    return ""

def trace(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Trace ability."""
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    _, opponent = battle.get_opponent_for_player(attacker_player)
    
    untraceable = ['multitype', 'rkssystem', 'trace', 'receiver', 'illusion', 'comatose', 'disguise', 'powerconstruct', 'schooling', 'shieldsdown', 'zerotohero']
    
    opponent_ability_id = opponent.pokemon.ability.lower().replace(" ", "")
    if opponent_ability_id in untraceable:
        return ""
        
    attacker.pokemon.ability = opponent.pokemon.ability
    attacker.ability_is_swapped = True
    return f"\n{attacker.pokemon.name} traced {opponent.pokemon.name}'s {opponent.pokemon.ability}!"

def frisk(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Frisk ability."""
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    _, opponent = battle.get_opponent_for_player(attacker_player)
    
    if opponent.pokemon.item:
        return f"\n{attacker.pokemon.name} frisked the opponent and found one {opponent.pokemon.item}!"
    return ""

def guard_dog(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Announces Guard Dog's immunity to Intimidate."""
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    _, opponent = battle.get_opponent_for_player(attacker_player)

    opponent_ability_id = opponent.pokemon.ability.lower().replace(" ", "")
    if opponent_ability_id != 'intimidate':
        return f"\n{attacker.pokemon.name} stands ready to protect against intimidation!"
    return ""

def hadron_engine(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Handles the Hadron Engine ability."""
    from bot.battle.field_effects import terrain as terrain_logic
    log = ""
    if battle.active_terrain != 'electricterrain':
        log += terrain_logic.set_terrain(battle, 'electricterrain', 5)
    
    attacker.volatiles['hadronengine'] = True
    return log

def check_magic_bounce(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Bounces back most status moves."""
    from bot.battle.move_effects.status_moves import handle_status_move

    if move_data.get('isBounced'):
        return False, ""

    if move_data.get('flags', {}).get('reflectable'):
        log = f"\n{defender.pokemon.name}'s Magic Bounce reflected the move!"
        
        # Mark as bounced to prevent infinite loops
        move_data['isBounced'] = True
        
        # Swap roles and re-apply the status move logic directly
        new_attacker = defender
        new_defender = attacker
        
        # Use handle_status_move to apply the bounced effect
        log += handle_status_move(new_attacker, new_defender, move_data, battle)

        # Stop the original move
        return True, log
        
    return False, ""

def check_good_as_gold(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Blocks status moves that are reflectable."""
    from bot.battle.move_effects.status_moves import handle_status_move

    if move_data.get('flags', {}).get('reflectable'):
        return True, f"\n{defender.pokemon.name}'s Good as Gold blocks the move!"
        
    return False, ""

def handle_retaliatory_stat_boosts(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle", move_data: dict, was_crit: bool) -> str:
    """
    Handles abilities that grant a stat boost after being hit by a specific move type or a critical hit.
    Covers Justified, Rattled, Steam Engine, Anger Point, and Thermal Exchange.
    """
    from bot.battle.move_effects.status_moves import handle_stat_boost_move
    from bot.battle.move_effects.status_moves import handle_status_move

    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    move_type = move_data.get('type')
    boost_data = None
    log_message = ""

    # Anger Point: Maxes Attack when hit by a critical hit
    if ability_id == 'angerpoint' and was_crit:
        if defender.boosts['atk'] < 6:
            boost_amount = 6 - defender.boosts['atk']
            boost_data = {'boosts': {'atk': boost_amount}}
            log_message = f"\n{defender.pokemon.name}'s Anger Point maxed its Attack!"

    # Justified: +1 Attack when hit by a Dark-type move
    elif ability_id == 'justified' and move_type == 'Dark':
        boost_data = {'boosts': {'atk': 1}}

    # Rattled: +1 Speed when hit by a Bug, Ghost, or Dark-type move
    elif ability_id == 'rattled' and move_type in ['Bug', 'Ghost', 'Dark']:
        boost_data = {'boosts': {'spe': 1}}
        
    # Thermal Exchange: +1 Attack when hit by a Fire-type move
    elif ability_id == 'thermalexchange' and move_type == 'Fire':
        boost_data = {'boosts': {'atk': 1}}

    # Steam Engine: Maximizes Speed when hit by a Fire or Water-type move
    elif ability_id == 'steamengine' and move_type in ['Fire', 'Water']:
        if defender.boosts['spe'] < 6:
            boost_amount = 6 - defender.boosts['spe']
            boost_data = {'boosts': {'spe': boost_amount}}
            log_message = f"\n{defender.pokemon.name}'s Steam Engine maxed its Speed!"

    if boost_data:
        if not log_message:
             log_message = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} raised its stats!"
        return log_message + "\n" + handle_stat_boost_move(defender, boost_data)

    return ""
    
def handle_hp_threshold_abilities(defender: "ActivePokemon", battle: "Battle") -> str:
    """
    Handles abilities that trigger when HP drops below 50%, like Emergency Exit, Wimp Out, Berserk, and Anger Shell.
    """
    from bot.battle.move_effects.status_moves import handle_stat_boost_move

    if 'hp_threshold_activated' in defender.volatiles:
        return ""

    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    log = ""
    
    hp_percent = (defender.current_hp / defender.actual_stats['hp']) * 100
    if hp_percent <= 50:
        
        defender.volatiles['hp_threshold_activated'] = True
        log = f"\n{defender.pokemon.name}'s {defender.pokemon.ability} activated!"

        if ability_id == 'berserk':
            boost_data = {'boosts': {'spa': 1}}
            log += "\n" + handle_stat_boost_move(defender, boost_data)
        
        elif ability_id == 'angershell':
            boost_data = {'boosts': {'def': -1, 'spd': -1, 'atk': 1, 'spa': 1, 'spe': 1}}
            log += "\n" + handle_stat_boost_move(defender, boost_data)
        
        elif ability_id in ['emergencyexit', 'wimpout']:
            # --- THIS IS THE USER-REQUESTED CHECK ---
            player = battle.get_player(defender.pokemon.pokemon_uuid)
            if not player: player = battle.player1 if defender in battle.player1.team else battle.player2

            can_switch = any(p.current_hp > 0 for i, p in enumerate(player.team) if i != player.active_pokemon_index)
            if can_switch:
                battle.force_switch_flags.append(defender.pokemon.pokemon_uuid)
                log += f"\n{defender.pokemon.name} is trying to escape!"
            else:
                log += "\nBut it had nowhere to run!"
            # --- END OF CHECK ---

    return log

def check_wonder_guard(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """Checks for immunity from Wonder Guard."""
    
    # 1. Import the TYPE_CHART from battle_logic
    from bot.battle.battle_logic import TYPE_CHART
    
    # 2. Allow Status moves to pass through
    if move_data.get('category') == 'Status':
        return False, ""
        
    # 3. Calculate effectiveness
    move_type = move_data.get('type')
    if not move_type:
        return False, "" # Failsafe for typeless moves

    multiplier = 1.0
    for def_type in defender.pokemon.types:
        multiplier *= TYPE_CHART.get(move_type.lower(), {}).get(def_type.lower(), 1.0)

    # 4. If the move is not super effective (<= 1), block it.
    if multiplier <= 1:
        return True, f"\n{defender.pokemon.name}'s Wonder Guard blocks the move!"
        
    # 5. If it's > 1, let it hit.
    return False, ""

def imposter(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Copies the opponent's stats, types, moves, and ability."""
    attacker_player = battle.player1 if attacker in battle.player1.team else battle.player2
    _, defender = battle.get_opponent_for_player(attacker_player)

    if 'illusion' in defender.volatiles or 'substitute' in defender.volatiles:
        return ""

    # --- SAVE ORIGINAL STATE BEFORE OVERWRITING ---
    if 'original_state' not in attacker.volatiles:
        attacker.volatiles['original_state'] = {
            'id': attacker.pokemon.id,
            'name': attacker.pokemon.name,
            'types': attacker.pokemon.types.copy(),
            'ability': attacker.pokemon.ability,
            'moves': attacker.pokemon.moves.copy(),
            'actual_stats': attacker.actual_stats.copy(),
            'move_pp': attacker.move_pp.copy()
        }

    # Copy Types and Ability
    attacker.pokemon.types = defender.pokemon.types.copy()
    attacker.pokemon.ability = defender.pokemon.ability
    
    # Copy Stats (Except HP)
    for stat in ['atk', 'def', 'spa', 'spd', 'spe']:
        attacker.actual_stats[stat] = defender.actual_stats[stat]
        attacker.boosts[stat] = defender.boosts[stat]
        
    # Copy Moves and set PP to 5
    attacker.pokemon.moves = defender.pokemon.moves.copy()
    attacker.move_pp = {move: 5 for move in attacker.pokemon.moves}
    
    # Update UI variables
    attacker.pokemon.id = defender.pokemon.id
    attacker.pokemon.name = defender.pokemon.name
    attacker.volatiles['transformed'] = True

    return f"\n{attacker.pokemon.name} transformed into {defender.pokemon.name}!"

def revert_transformation(pokemon: "ActivePokemon"):
    """Reverts a Pokemon back to its original state (e.g., Ditto)."""
    if 'transformed' in pokemon.volatiles and 'original_state' in pokemon.volatiles:
        orig = pokemon.volatiles['original_state']
        
        pokemon.pokemon.id = orig['id']
        pokemon.pokemon.name = orig['name']
        pokemon.pokemon.types = orig['types']
        pokemon.pokemon.ability = orig['ability']
        pokemon.pokemon.moves = orig['moves']
        pokemon.actual_stats = orig['actual_stats']
        pokemon.move_pp = orig['move_pp']
        
        # Reset stat boosts
        pokemon.boosts = {'atk': 0, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 0, 'accuracy': 0, 'evasion': 0}
        
        del pokemon.volatiles['transformed']
        del pokemon.volatiles['original_state']