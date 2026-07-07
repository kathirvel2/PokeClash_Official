# ./bot/battle/ability_effects/__init__.py

from typing import TYPE_CHECKING
from .ability_logic import (
    intimidate,
    adaptability,
    handle_ate_abilities,
    air_lock,
    set_drizzle_weather,
    set_drought_weather,
    check_levitate,
    check_volt_absorb,
    check_water_absorb,
    check_flash_fire,
    check_motor_drive,
    check_storm_drain,
    handle_natural_cure,
    handle_regenerator,
    check_static,
    check_poison_point,
    check_flame_body,
    set_sandstorm_weather,
    set_hail_weather,
    check_soundproof,
    check_magma_armor,
    check_water_veil,
    check_sleep_immunity,
    prevent_stat_lower_general,
    prevent_stat_lower_specific,
    check_sap_sipper,
    check_lightning_rod,
    check_bulletproof,
    check_disguise,
    restore_ice_face,
    check_ice_face,
    check_immunity,
    check_limber,
    check_own_tempo,
    check_oblivious,
    check_gooey_or_tangling_hair,
    check_iron_barbs_or_rough_skin,
    check_effect_spore,
    check_aroma_veil,
    anticipation,
    handle_passive_power_boost,
    handle_permanent_stat_multiply,
    handle_on_ko_boosts,
    handle_on_taking_damage_boosts,
    handle_stat_lowered_boosts,
    check_earth_eater,
    check_well_baked_body,
    check_wind_rider,
    handle_aftermath,
    check_cute_charm,
    check_cursed_body,
    handle_ability_change_on_contact,
    check_sturdy,
    set_electric_terrain,
    set_grassy_terrain,
    set_misty_terrain,
    set_psychic_terrain,
    check_dry_skin,
    check_inner_focus,
    check_leaf_guard,
    check_comatose,
    check_purifying_salt_status,
    check_pastel_veil,
    check_sweet_veil,
    handle_pinch_abilities,
    handle_pure_type_boost,
    handle_field_effect_boosts,
    handle_damage_reduction_abilities,
    handle_opportunist,
    download,
    dauntless_shield,
    intrepid_sword,
    screen_cleaner,
    trace,
    frisk,
    guard_dog,
    hadron_engine,
    check_magic_bounce,
    check_good_as_gold,
    handle_retaliatory_stat_boosts,
    handle_hp_threshold_abilities,
    check_wonder_guard,
    imposter
)
if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, ActivePokemon

ABILITY_EFFECTS = {
    'intimidate': {'on_switch_in': intimidate},
    'drizzle': {'on_switch_in': set_drizzle_weather},
    'drought': {'on_switch_in': set_drought_weather},
    'electricsurge': {'on_switch_in': set_electric_terrain},
    'grassysurge': {'on_switch_in': set_grassy_terrain},
    'mistysurge': {'on_switch_in': set_misty_terrain},
    'psychicsurge': {'on_switch_in': set_psychic_terrain},
    'sandstream': {'on_switch_in': set_sandstorm_weather},
    'snowwarning': {'on_switch_in': set_hail_weather},
    'adaptability': {},
    'aerilate': {},
    'pixilate': {},
    'galvanize': {},
    'refrigerate': {},
    'normalize': {},
    'liquidvoice': {},
    'airlock': {'on_switch_in': air_lock},
    'cloudnine': {'on_switch_in': air_lock},
    'levitate': {'on_try_hit': check_levitate},
    'voltabsorb': {'on_try_hit': check_volt_absorb},
    'waterabsorb': { 'on_try_hit': check_water_absorb },
    'dryskin': { 'on_try_hit': check_dry_skin },
    'flashfire': { 'on_try_hit': check_flash_fire },
    'motordrive': { 'on_try_hit': check_motor_drive },
    'stormdrain': { 'on_try_hit': check_storm_drain },
    'naturalcure': { 'on_switch_out': handle_natural_cure },
    'regenerator': { 'on_switch_out': handle_regenerator },
    'static': { 'on_taking_contact_damage': check_static },
    'poisonpoint': { 'on_taking_contact_damage': check_poison_point },
    'flamebody': { 'on_taking_contact_damage': check_flame_body },
    'aftermath': {'on_faint': handle_aftermath},
    'cutecharm': {'on_taking_contact_damage': check_cute_charm},
    'cursedbody': {'on_taking_contact_damage': check_cursed_body},
    'mummy': {'on_taking_contact_damage': handle_ability_change_on_contact},
    'wanderingspirit': {'on_taking_contact_damage': handle_ability_change_on_contact},
    'sturdy': {'on_before_damage': check_sturdy},
    'soundproof': {'on_try_hit': check_soundproof},
    'magmaarmor': {'on_status_infliction': check_magma_armor},
    'waterveil': {'on_status_infliction': check_water_veil},
    'insomnia': {'on_status_infliction': check_sleep_immunity},
    'vitalspirit': {'on_status_infliction': check_sleep_immunity},
    'clearbody': {'on_stat_lower': prevent_stat_lower_general},
    'whitesmoke': {'on_stat_lower': prevent_stat_lower_general},
    'hypercutter': {'on_stat_lower': lambda target, boosts: prevent_stat_lower_specific(target, boosts, 'atk')},
    'bigpecks': {'on_stat_lower': lambda target, boosts: prevent_stat_lower_specific(target, boosts, 'def')},
    'swiftswim': {},
    'chlorophyll': {},
    'sandrush': {},
    'slushrush': {},
    'sapsipper': {'on_try_hit': check_sap_sipper},
    'eartheater': {'on_try_hit': check_earth_eater},
    'wellbakedbody': {'on_try_hit': check_well_baked_body},
    'windrider': { 'on_try_hit': check_wind_rider},
    'lightningrod': {'on_try_hit': check_lightning_rod},
    'bulletproof': {'on_try_hit': check_bulletproof},
    'battlebond': {},
    'disguise': {'on_try_hit': check_disguise},
    'iceface': {'on_try_hit': check_ice_face, 'on_end_of_turn': restore_ice_face},
    'immunity': {'on_status_infliction': check_immunity},
    'limber': {'on_status_infliction': check_limber},
    'owntempo': {'on_volatile_status_infliction': check_own_tempo},
    'oblivious': {'on_volatile_status_infliction': check_oblivious},
    'gooey': {'on_taking_contact_damage': check_gooey_or_tangling_hair},
    'tanglinghair': {'on_taking_contact_damage': check_gooey_or_tangling_hair},
    'ironbarbs': {'on_taking_contact_damage': check_iron_barbs_or_rough_skin},
    'roughskin': {'on_taking_contact_damage': check_iron_barbs_or_rough_skin},
    'effectspore': {'on_taking_contact_damage': check_effect_spore},
    'aromaveil': {'on_volatile_status_infliction': check_aroma_veil},
    'anticipation': {'on_switch_in': anticipation},
    'strongjaw':   {'on_modify_move_power': handle_passive_power_boost},
    'toughclaws':  {'on_modify_move_power': handle_passive_power_boost},
    'ironfist':    {'on_modify_move_power': handle_passive_power_boost},
    'sharpness':   {'on_modify_move_power': handle_passive_power_boost},
    'hugepower':   {'on_stat_calculation': handle_permanent_stat_multiply},
    'purepower':   {'on_stat_calculation': handle_permanent_stat_multiply},
    'furcoat': {'on_stat_calculation': handle_permanent_stat_multiply},
    'gorillatactics': {'on_stat_calculation': handle_permanent_stat_multiply},
    'beastboost': {'on_ko': handle_on_ko_boosts},
    'chillingneigh': {'on_ko': handle_on_ko_boosts},
    'grimneigh': {'on_ko': handle_on_ko_boosts},
    'moxie': {'on_ko': handle_on_ko_boosts},
    'stamina': {'on_taking_damage': handle_on_taking_damage_boosts},
    'weakarmor': {'on_taking_damage': handle_on_taking_damage_boosts},
    'competitive': {'on_stat_lowered': handle_stat_lowered_boosts},
    'defiant': {'on_stat_lowered': handle_stat_lowered_boosts},
    'innerfocus': {'on_volatile_status_infliction': check_inner_focus},
    'leafguard': {'on_status_infliction': check_leaf_guard},
    'comatose': {'on_status_infliction': check_comatose},
    'purifyingsalt': {'on_status_infliction': check_purifying_salt_status},
    'pastelveil': {'on_status_infliction': check_pastel_veil},
    'sweetveil': {'on_status_infliction': check_sweet_veil},
    'blaze': { 'on_modify_move_power': handle_pinch_abilities },
    'torrent': { 'on_modify_move_power': handle_pinch_abilities },
    'overgrow': { 'on_modify_move_power': handle_pinch_abilities },
    'transistor': { 'on_modify_move_power': handle_pure_type_boost },
    'dragonsmaw': { 'on_modify_move_power': handle_pure_type_boost },
    'steelworker': { 'on_modify_move_power': handle_pure_type_boost },
    'rockypayload': { 'on_modify_move_power': handle_pure_type_boost },
    'marvelscale': {},
    'quickfeet': {},
    'sandforce': {'on_modify_move_power': handle_field_effect_boosts},
    'fluffy': {'on_damage_taken': handle_damage_reduction_abilities},
    'punkrock': {'on_damage_taken': handle_damage_reduction_abilities},
    'icescales': {'on_damage_taken': handle_damage_reduction_abilities},
    'heatproof': {'on_damage_taken': handle_damage_reduction_abilities},
    'whitesmoke': {'on_stat_lower': prevent_stat_lower_general},
    'fullmetalbody': {'on_stat_lower': prevent_stat_lower_general},
    'keeneye': {'on_stat_lower': lambda target, boosts: prevent_stat_lower_specific(target, boosts, 'accuracy')},
    'opportunist': {'on_opponent_stat_boost': handle_opportunist},
    'sheerforce': {},
    'serenegrace': {},
    'skilllink': {},
    'sniper': {},
    'megalauncher': {},
    'download': {'on_switch_in': download},
    'dauntlessshield': {'on_switch_in': dauntless_shield},
    'intrepidsword': {'on_switch_in': intrepid_sword},
    'screencleaner': {'on_switch_in': screen_cleaner},
    'trace': {'on_switch_in': trace},
    'frisk': {'on_switch_in': frisk},
    'guarddog': {'on_switch_in': guard_dog},
    'hadronengine': {'on_switch_in': hadron_engine},
    'magicbounce': {'on_try_hit': check_magic_bounce},
    'goodasgold': {'on_try_hit': check_good_as_gold},
    'justified': {'on_after_move_damage': handle_retaliatory_stat_boosts},
    'rattled': {'on_after_move_damage': handle_retaliatory_stat_boosts},
    'steamengine': {'on_after_move_damage': handle_retaliatory_stat_boosts},
    'angerpoint': {'on_after_move_damage': handle_retaliatory_stat_boosts},
    'thermalexchange': {'on_after_move_damage': handle_retaliatory_stat_boosts},
    'emergencyexit': {
        'on_hp_threshold': handle_hp_threshold_abilities,
    },
    'wimpout': {
        'on_hp_threshold': handle_hp_threshold_abilities,
    },
    'berserk': {
        'on_hp_threshold': handle_hp_threshold_abilities,
    },
    'angershell': {
        'on_hp_threshold': handle_hp_threshold_abilities,
    },
    'guts':{},
    'flareboost':{},
    'toxicboost':{},
    'speedboost': {}, # Logic is in end_of_turn
    'simple': {}, # Logic is in handle_stat_boost_move
    'contrary': {}, # Logic is in handle_stat_boost_move
    'unaware': {}, # Logic is in damage calculation
    'wonderguard': {'on_try_hit': check_wonder_guard},
    'superluck': {}, # Logic is in check_for_crit
    'tangledfeet': {}, # Logic is in check_accuracy
    'victorystar': {}, # Logic is in check_accuracy
    'compoundeyes': {}, # Logic is in check_accuracy
    'hustle': {},       # Logic is in get_modified_stat & check_accuracy
    'neuroforce': {},   # Logic is in execute_move (damage calc)
    'noguard': {},      # Logic is in check_accuracy
    'reckless': {},     # Logic is in execute_move (damage calc)
    'scrappy': {},      # Logic is in get_type_effectiveness
    'imposter': {'on_switch_in': imposter},
}

def is_weather_suppressed(battle: "Battle") -> bool:
    """Checks if any active Pokémon has an ability that suppresses weather."""
    for player in [battle.player1, battle.player2]:
        pokemon = player.get_active_pokemon()
        ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
        if ability_id in ['airlock', 'cloudnine']:
            return True
    return False

def trigger_on_switch_in_abilities(attacker: "ActivePokemon", battle: "Battle") -> str:
    """
    Checks the Pokémon's ability and triggers the 'on_switch_in' effect if it exists.
    Returns a log of what happened.
    """
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_switch_in' in effect:
        return effect['on_switch_in'](attacker, battle)
        
    return ""

def get_stab_multiplier(attacker: "ActivePokemon") -> float:
    """
    Determines the STAB multiplier, accounting for abilities like Adaptability.
    """
    return adaptability(attacker)

def trigger_on_modify_move(attacker: "ActivePokemon", move_data: dict) -> tuple[dict, float]:
    """
    Applies ability effects that can change a move's type or power before execution.
    Returns the (potentially modified) move_data and a power multiplier.
    """
    
    move_data, power_multiplier = handle_ate_abilities(attacker, move_data)
    
    return move_data, power_multiplier

def trigger_on_try_hit(attacker: "ActivePokemon", defender: "ActivePokemon", move_data: dict, battle: "Battle") -> tuple[bool, str]:
    """
    Checks the DEFENDER's ability for any 'on_try_hit' effects that might stop a move.
    Returns (should_stop, log_message).
    """
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    
    if 'gastroacid' in defender.volatiles:
        return False, ""
        
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_try_hit' in effect:
        return effect['on_try_hit'](attacker, defender, move_data, battle)
        
    return False, ""

def trigger_on_switch_out(pokemon: "ActivePokemon", battle: "Battle") -> str:
    """
    Checks the switching Pokémon's ability for any 'on_switch_out' effects.
    Returns a log of what happened.
    """
    ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
    
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_switch_out' in effect:
        return effect['on_switch_out'](pokemon, battle)
        
    return ""

def trigger_on_taking_contact_damage(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """
    Checks the DEFENDER's ability for any effects that trigger when hit by a contact move.
    Returns a log of what happened.
    """
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    
    if 'gastroacid' in defender.volatiles:
        return ""
        
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_taking_contact_damage' in effect:
        return effect['on_taking_contact_damage'](attacker, defender, battle)
        
    return ""

def trigger_on_volatile_status_infliction(volatile_status: str, target: "ActivePokemon", attacker: "ActivePokemon") -> tuple[bool, str]:
    """Checks for abilities that prevent volatile statuses like confusion, taunt, etc."""
    ability_id = target.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_volatile_status_infliction' in effect:
        return effect['on_volatile_status_infliction'](volatile_status, target, attacker)
        
    return False, ""

def trigger_on_modify_move_power(attacker: "ActivePokemon", move_data: dict, battle: "Battle") -> float:
    """Applies ability effects that modify a move's power."""
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)
    
    multiplier = 1.0
    if effect and 'on_modify_move_power' in effect:
        handler = effect['on_modify_move_power']
        import inspect
        sig = inspect.signature(handler)
        if 'battle' in sig.parameters:
            multiplier = handler(attacker, move_data, battle)
        else:
            multiplier = handler(attacker, move_data)
            
    return multiplier

def trigger_on_stat_calculation(pokemon: "ActivePokemon", battle: "Battle"):
    """Applies ability effects that modify stats at the start of battle."""
    ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_stat_calculation' in effect:
        handler = effect['on_stat_calculation']
        import inspect
        sig = inspect.signature(handler)
        if 'battle' in sig.parameters:
            handler(pokemon, battle)
        else:
            handler(pokemon)

def trigger_on_ko(attacker: "ActivePokemon", battle: "Battle") -> str:
    """
    Checks the Pokémon's ability and triggers the 'on_ko' effect if it exists.
    Returns a log of what happened.
    """
    ability_id = attacker.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)

    if effect and 'on_ko' in effect:
        return effect['on_ko'](attacker, battle)

    return ""

def trigger_on_taking_damage(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """
    Checks the DEFENDER's ability for any effects that trigger after taking damage.
    Returns a log of what happened.
    """
    if attacker.pokemon.pokemon_uuid == defender.pokemon.pokemon_uuid:
        return ""

    ability_id = defender.pokemon.ability.lower().replace(" ", "")

    if 'gastroacid' in defender.volatiles:
        return ""

    effect = ABILITY_EFFECTS.get(ability_id)

    if effect and 'on_taking_damage' in effect:
        return effect['on_taking_damage'](attacker, defender, battle)

    return ""

def trigger_on_stat_lowered(target: "ActivePokemon", battle: "Battle") -> str:
    """
    Checks if the target's ability triggers a boost when its stats are lowered by an opponent.
    Returns a log of what happened.
    """
    ability_id = target.pokemon.ability.lower().replace(" ", "")

    if 'gastroacid' in target.volatiles:
        return ""

    effect = ABILITY_EFFECTS.get(ability_id)

    if effect and 'on_stat_lowered' in effect:
        return effect['on_stat_lowered'](target, battle)

    return ""

def trigger_on_faint(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle") -> str:
    """Checks the fainted Pokémon's (defender) ability for any 'on_faint' effects."""
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_faint' in effect:
        return effect['on_faint'](attacker, defender, battle)
        
    return ""

def trigger_on_before_damage(defender: "ActivePokemon", damage: int) -> tuple[int, str]:
    """Checks the defender's ability for any effects that trigger before damage is dealt."""
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_before_damage' in effect:
        return effect['on_before_damage'](defender, damage)
        
    return damage, ""

def trigger_on_damage_taken(defender: "ActivePokemon", move_data: dict, effectiveness: float) -> float:
    """
    NEW: Checks for abilities that reduce incoming damage and returns a multiplier.
    """
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    
    if 'gastroacid' in defender.volatiles:
        return 1.0
        
    effect = ABILITY_EFFECTS.get(ability_id)
    
    if effect and 'on_damage_taken' in effect:
        handler = effect['on_damage_taken']
        return handler(defender, move_data, effectiveness)
            
    return 1.0

def trigger_on_opponent_stat_boost(user: "ActivePokemon", opponent: "ActivePokemon", boosts: dict, battle: "Battle") -> str:
    """
    Checks the USER's ability for any 'on_opponent_stat_boost' effects.
    This is for abilities like Opportunist that copy the opponent's boosts.
    Returns a log of what happened.
    """
    ability_id = user.pokemon.ability.lower().replace(" ", "")
    effect = ABILITY_EFFECTS.get(ability_id)

    if effect and 'on_opponent_stat_boost' in effect:
        return effect['on_opponent_stat_boost'](user, opponent, boosts, battle)

    return ""

def trigger_on_after_move_damage(attacker: "ActivePokemon", defender: "ActivePokemon", battle: "Battle", move_data: dict, was_crit: bool) -> str:
    """
    NEW HOOK: Checks for abilities that trigger after taking damage from a move.
    This is different from the generic 'on_taking_damage' because it provides move context.
    """
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    if 'gastroacid' in defender.volatiles:
        return ""
    effect = ABILITY_EFFECTS.get(ability_id)
    if effect and 'on_after_move_damage' in effect:
        # This will correctly call handle_retaliatory_stat_boosts with all 5 arguments
        return effect['on_after_move_damage'](attacker, defender, battle, move_data, was_crit)
    return ""

def trigger_on_hp_threshold(defender: "ActivePokemon", battle: "Battle") -> str:
    """
    NEW HOOK: Checks for abilities that trigger when HP drops below a certain threshold.
    """
    ability_id = defender.pokemon.ability.lower().replace(" ", "")
    if 'gastroacid' in defender.volatiles:
        return ""
    
    effect = ABILITY_EFFECTS.get(ability_id)
    if effect and 'on_hp_threshold' in effect:
        # This will correctly call handle_hp_threshold_abilities
        return effect['on_hp_threshold'](defender, battle)
        
    return ""