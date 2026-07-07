# ./bot/battle/item_effects/item_logic.py

import math
import random
from typing import TYPE_CHECKING
from bot.mechanics.item_data import ITEM_ID_BY_NAME
from .item_data import ITEM_EFFECTS

if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, ActivePokemon, BattlePlayer

def get_item_effect(pokemon: "ActivePokemon"):
    """A helper function to safely get the effect data for the Pokémon's held item."""
    if not pokemon.pokemon.item:
        return None
    item_id = ITEM_ID_BY_NAME.get(pokemon.pokemon.item)
    return ITEM_EFFECTS.get(item_id)

# === HOOK 1: ON MOVE CHOICE ===
def apply_on_move_choice(pokemon: "ActivePokemon", move_id: str) -> tuple[bool, str]:
    """
    Applies effects that trigger when a move is selected.
    Handles Choice item locking, Gorilla Tactics, and Assault Vest.
    """
    if 'dynamax' in pokemon.volatiles:
        return True, ""

    # --- THIS IS THE NEW LOGIC ---
    ability_id = pokemon.pokemon.ability.lower().replace(" ", "")
    item_effect = get_item_effect(pokemon)
    
    # Check for Choice lock from either an item or Gorilla Tactics ability
    is_choice_locked = (item_effect and item_effect.get("on_move_choice", {}).get("type") == "lock") or \
                       (ability_id == 'gorillatactics')

    if is_choice_locked:
        if 'choice_locked_move' not in pokemon.volatiles:
            pokemon.volatiles['choice_locked_move'] = move_id
        return True, ""
    # --- END OF NEW LOGIC ---

    # Assault Vest logic remains the same
    if item_effect and item_effect.get("on_move_choice", {}).get("type") == "block_status_moves":
        from bot.mechanics.moves_loader import MOVE_BY_ID
        if MOVE_BY_ID[move_id]['category'] == 'Status':
            return False, f"\n{pokemon.pokemon.name} can't use status moves due to its Assault Vest!"

    return True, ""

# === HOOK 2: ON STAT CALCULATION ===
def apply_on_stat_calculation(pokemon: "ActivePokemon"):
    """
    Applies permanent stat multipliers from items at the start of a battle.
    Handles Choice Scarf, Choice Band, Choice Specs, Eviolite, Assault Vest.
    """
    if 'dynamax' in pokemon.volatiles:
        return
    item_effect = get_item_effect(pokemon)
    if not item_effect or "on_stat_calculation" not in item_effect:
        return

    effect_data = item_effect["on_stat_calculation"]
    
    # Eviolite Check: only apply if the Pokémon is not fully evolved
    if effect_data.get("condition") == "not_fully_evolved":
        from bot.mechanics.moves_loader import SPECIES_BY_ID
        species_data = SPECIES_BY_ID.get(pokemon.pokemon.id, {})
        if not species_data.get("nfe", False): # "nfe" is the "Not Fully Evolved" flag
            return 
    
    stats_to_modify = effect_data["stat"]
    if not isinstance(stats_to_modify, list):
        stats_to_modify = [stats_to_modify]
        
    for stat in stats_to_modify:
        pokemon.stat_multipliers[stat] *= effect_data["multiplier"]

# === HOOK 3: ON DAMAGE DEALT ===
def apply_on_damage_dealt(attacker: "ActivePokemon", move_data: dict, effectiveness: float) -> float:
    """
    Applies damage multipliers from items like Life Orb, Expert Belt, and Type-Enhancers.
    Returns the total multiplier.
    """
    if 'dynamax' in attacker.volatiles:
        return 1.0

    item_effect = get_item_effect(attacker)
    if not item_effect or "on_damage_dealt" not in item_effect:
        return 1.0

    effect_data = item_effect["on_damage_dealt"]
    
    if effect_data.get("type") == "multiplier":
        return effect_data["value"]
        
    elif effect_data.get("type") == "super_effective_multiplier" and effectiveness > 1:
        return effect_data["value"]
        
    elif effect_data.get("type") == "category_multiplier" and move_data['category'] == effect_data['category']:
        return effect_data["value"]

    elif effect_data.get("type") == "type_multiplier" and move_data['type'] == effect_data['move_type']:
        return effect_data["value"]

    elif effect_data.get("type") == "specific_pokemon_boost":
        if attacker.pokemon.id == effect_data["pokemon"] and move_data['type'] in attacker.pokemon.types:
             return effect_data["value"]
        
    return 1.0

# === HOOK 4: AFTER ATTACK ===
def apply_after_attack_effects(attacker: "ActivePokemon", battle: "Battle") -> str:
    """Applies effects that trigger after an attack resolves, like Life Orb recoil."""
    if 'dynamax' in attacker.volatiles:
        return ""
    item_effect = get_item_effect(attacker)
    if not item_effect or "on_after_attack" not in item_effect:
        return ""

    effect_data = item_effect["on_after_attack"]
    
    if effect_data.get("type") == "recoil_hp_fraction":
        recoil_damage = max(1, int(attacker.actual_stats['hp'] * effect_data["value"]))
        attacker.current_hp = max(0, attacker.current_hp - recoil_damage)
        return f"\n{attacker.pokemon.name} was hurt by its {attacker.pokemon.item}!"
        
    return ""

# === HOOK 5: BEFORE DAMAGE IS TAKEN ===
def apply_on_before_damage(defender: "ActivePokemon", damage: int) -> tuple[int, str]:
    """Applies effects that trigger before damage is taken, like Focus Sash."""
    if 'dynamax' in defender.volatiles:
        return damage, ""
    item_effect = get_item_effect(defender)
    if not item_effect or "on_before_damage" not in item_effect:
        return damage, ""

    effect_data = item_effect["on_before_damage"]
    
    if effect_data.get("type") == "survive_ohko":
        # Check if Focus Sash should activate (full HP and damage is lethal)
        if defender.current_hp == defender.actual_stats['hp'] and damage >= defender.current_hp:
            defender.pokemon.item = None # Consume the item
            return defender.current_hp - 1, f"\n{defender.pokemon.name} held on using its Focus Sash!"
            
    return damage, ""

# === HOOK 6: END OF TURN ===
def apply_end_of_turn_item_effects(pokemon: "ActivePokemon") -> str:
    """Applies item effects that trigger at the end of the turn."""
    if 'dynamax' in pokemon.volatiles:
        return ""
    item_effect = get_item_effect(pokemon)
    if not item_effect or "on_end_of_turn" not in item_effect:
        return ""
        
    effect_data = item_effect["on_end_of_turn"]
    log = ""
    
    # Healing (Leftovers)
    if effect_data.get("type") == "heal_hp_fraction":
        if pokemon.current_hp > 0 and pokemon.current_hp < pokemon.actual_stats['hp']:
            heal_amount = max(1, int(pokemon.actual_stats['hp'] * effect_data["value"]))
            pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
            log += f"\n{pokemon.pokemon.name} restored a little HP using its {pokemon.pokemon.item}!"
    
    # Healing/Damage (Black Sludge)
    elif effect_data.get("type") == "heal_or_damage_hp_fraction":
        fraction = effect_data["value"]
        if "Poison" in pokemon.pokemon.types:
            if pokemon.current_hp > 0 and pokemon.current_hp < pokemon.actual_stats['hp']:
                heal_amount = max(1, int(pokemon.actual_stats['hp'] * fraction))
                pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
                log += f"\n{pokemon.pokemon.name} restored a little HP using its {pokemon.pokemon.item}!"
        else:
            if pokemon.current_hp > 0:
                damage_amount = max(1, int(pokemon.actual_stats['hp'] * fraction))
                pokemon.current_hp = max(0, pokemon.current_hp - damage_amount)
                log += f"\n{pokemon.pokemon.name} was hurt by its {pokemon.pokemon.item}!"
            
    # Status Orbs (Toxic Orb, Flame Orb)
    elif effect_data.get("type") == "apply_status":
        if effect_data.get("condition") == "no_status" and not pokemon.status:
            pokemon.status = effect_data["status"]
            if pokemon.status == 'tox':
                pokemon.status_counter = 1
            status_name = "badly poisoned" if pokemon.status == 'tox' else "burned"
            log += f"\n{pokemon.pokemon.name} was {status_name} by its {pokemon.pokemon.item}!"
            
    return log

# === HOOK 7: ON SWITCH-IN ===
def apply_on_switch_in(pokemon: "ActivePokemon", battle: "Battle") -> str:
    """Applies effects that trigger immediately upon switching in."""
    item_effect = get_item_effect(pokemon)
    if not item_effect:
        return ""
        
    log = ""
    # Heavy-Duty Boots (Prevents hazards)
    if item_effect.get("on_switch_in", {}).get("type") == "block_hazards":
        pokemon.volatiles['heavydutyboots'] = True # A flag to be checked by hazard logic
        
    # Air Balloon
    if item_effect.get("on_switch_in", {}).get("type") == "add_volatile":
        pokemon.volatiles['airballoon'] = True
        log += f"\n{pokemon.pokemon.name} floats in the air with its Air Balloon!"
        
    # Terrain Seeds
    if "on_terrain_contact" in item_effect:
        effect_data = item_effect["on_terrain_contact"]
        is_grounded = 'Flying' not in pokemon.pokemon.types and 'airballoon' not in pokemon.volatiles
        if battle.active_terrain == effect_data["terrain"] and is_grounded:
            from bot.battle.move_effects.status_moves import handle_stat_boost_move # Local import
            log += f"\n{pokemon.pokemon.name} consumed its {pokemon.pokemon.item}!"
            log += "\n" + handle_stat_boost_move(pokemon, effect_data)
            pokemon.pokemon.item = None # Consume the item
            
    return log

# === HOOK 8: ON TAKING DAMAGE ===
def apply_on_taking_damage(defender: "ActivePokemon", battle: "Battle") -> str:
    """Applies effects that trigger when a Pokémon takes any damage."""
    item_effect = get_item_effect(defender)
    if not item_effect or "on_taking_damage" not in item_effect:
        return ""
        
    effect_data = item_effect["on_taking_damage"]
    log = ""
    
    # Air Balloon pop
    if effect_data.get("type") == "remove_volatile" and "airballoon" in defender.volatiles:
        del defender.volatiles['airballoon']
        log += f"\n{defender.pokemon.name}'s Air Balloon popped!"

    # --- THIS IS THE FIX ---
    # We just use the 'battle' object that was passed into this function.
    # No need to search for 'active_battles'.
    elif effect_data.get("type") == "force_switch_on_damage":
        # Check if the player has a Pokemon to switch to
        player = battle.get_player(defender.pokemon.pokemon_uuid)
        if not player: player = battle.player1 if defender in battle.player1.team else battle.player2

        can_switch = any(p.current_hp > 0 and i != player.active_pokemon_index for i, p in enumerate(player.team))
        
        if can_switch:
            log += f"\n{defender.pokemon.name} held up its Eject Tool and will switch out!"
            defender.pokemon.item = None # Consume the item
            # Add the user to the force_switch_flags list
            battle.force_switch_flags.append(defender.pokemon.pokemon_uuid)
        else:
            log += f"\n{defender.pokemon.name}'s Eject Tool had no effect!"
    # --- END OF FIX ---
        
    return log

# === HOOK 9: ON BELOW HP THRESHOLD ===
def apply_on_below_hp_threshold(pokemon: "ActivePokemon", battle: "Battle") -> str:
    """
    Applies effects for berries that trigger when HP drops below a threshold.
    Handles Sitrus, stat-boosting, and confusion berries.
    """
    if 'dynamax' in pokemon.volatiles:
        return ""
    item_effect = get_item_effect(pokemon)
    if not item_effect or "on_below_hp_threshold" not in item_effect:
        return ""
        
    # CRITICAL RULE: Never trigger if the Pokémon has fainted.
    if pokemon.current_hp <= 0:
        return ""

    effect_data = item_effect["on_below_hp_threshold"]
    hp_threshold = pokemon.actual_stats['hp'] * effect_data["threshold"]

    # Only trigger if HP is at or below the threshold
    if pokemon.current_hp > hp_threshold:
        return ""
        
    log = f"\n{pokemon.pokemon.name}'s {pokemon.pokemon.item} activated!"
    pokemon.pokemon.item = None # Consume the berry
    
    # HP Healing Berries (Sitrus, Figy, etc.)
    if effect_data.get("type") == "heal_hp_fraction":
        heal_amount = math.floor(pokemon.actual_stats['hp'] * effect_data["value"])
        pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
        log += f"\n{pokemon.pokemon.name} restored its health!"
        
        # Check for confusion effect from certain berries
        if "confuse_nature" in effect_data:
            if pokemon.pokemon.nature in effect_data["confuse_nature"]:
                if 'confusion' not in pokemon.volatiles:
                    pokemon.volatiles['confusion'] = random.randint(1, 4)
                    log += f"\n{pokemon.pokemon.name} became confused!"
    
    # Stat Boosting Berries (Liechi, Salac, etc.)
    elif effect_data.get("type") == "consume_and_boost":
        from bot.battle.move_effects.status_moves import handle_stat_boost_move
        log += "\n" + handle_stat_boost_move(pokemon, effect_data)
        
    return log

# === HOOK 10: ON STATUS INFLICTED ===
def apply_on_status_inflicted(pokemon: "ActivePokemon", battle: "Battle") -> tuple[bool, str]:
    """
    Applies effects for items that trigger when a status is about to be inflicted.
    Handles Lum Berry. Returns (was_cured, log_message).
    """
    if 'dynamax' in pokemon.volatiles:
        return False, ""
    item_effect = get_item_effect(pokemon)
    if not item_effect or "on_status_inflicted" not in item_effect:
        return False, ""
        
    effect_data = item_effect["on_status_inflicted"]
    
    if effect_data.get("type") == "cure_status":
        log = f"\n{pokemon.pokemon.name}'s {pokemon.pokemon.item} cured its status condition!"
        pokemon.pokemon.item = None # Consume the berry
        return True, log
        
    return False, ""

def apply_on_taking_contact_damage(attacker: "ActivePokemon", defender: "ActivePokemon") -> str:
    """Applies effects that trigger when a Pokémon is hit by a contact move, like Rocky Helmet."""
    if 'dynamax' in defender.volatiles:
        return ""
    item_effect = get_item_effect(defender)
    if not item_effect or "on_taking_contact_damage" not in item_effect:
        return ""

    effect_data = item_effect["on_taking_contact_damage"]
    log = ""

    # Handle Rocky Helmet recoil damage
    if effect_data.get("type") == "recoil_hp_fraction":
        # Only trigger if the attacker is not holding Protective Pads
        attacker_item_effect = get_item_effect(attacker)
        if attacker_item_effect and attacker_item_effect.get("on_contact", {}).get("type") == "block_contact_effects":
             return "" # Attacker is protected, so do nothing

        # Deal 1/6th of the attacker's MAX HP as damage
        recoil_damage = max(1, int(attacker.actual_stats['hp'] * effect_data["value"]))
        attacker.current_hp = max(0, attacker.current_hp - recoil_damage)
        log += f"\n{attacker.pokemon.name} was hurt by {defender.pokemon.name}'s {defender.pokemon.item}!"
    
    return log