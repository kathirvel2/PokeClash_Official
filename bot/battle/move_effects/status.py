# ./bot/battle/move_effects/status.py
import random
from typing import Optional, Tuple, TYPE_CHECKING 
from bot.battle.item_effects import item_logic
from bot.battle.battle_engine import ActivePokemon
from bot.battle.field_effects import terrain as terrain_logic 
from bot.battle import ability_effects
import inspect

if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle

def apply_status(status_to_apply: str, target: ActivePokemon, move_data: dict, battle: "Battle") -> str:
    """
    Applies a status condition, checking for immunities, items, and now correctly
    differentiating between primary (status moves) and secondary effects.
    """
    if target.pokemon.ability.lower().replace(" ", "") == 'shieldsdown':
        if target.pokemon.id.startswith('miniormeteor'):
             return f"\nIt doesn't affect {target.pokemon.name}..."
    ability_id = target.pokemon.ability.lower().replace(" ", "")
    ability_effect = ability_effects.ABILITY_EFFECTS.get(ability_id)
    
    if ability_effect and 'on_status_infliction' in ability_effect:
        handler = ability_effect['on_status_infliction']
        sig = inspect.signature(handler)
    
        # Check if the ability function needs the 'battle' object
        if 'battle' in sig.parameters:
            # If it does (like Leaf Guard), pass it
            is_immune, reason = handler(status_to_apply, target, battle)
        else:
            # If it doesn't (like Limber), call it normally
            is_immune, reason = handler(status_to_apply, target)
    
        if is_immune:
            return reason
    # --- Checks for immunities and existing status (Unchanged) ---
    if terrain_logic.is_protected_by_terrain(target.pokemon, battle):
        return f"\n{target.pokemon.name} is protected by the Misty Terrain!"
    if target.status is not None:
        return "" # Fails if already statused
    if status_to_apply in ['psn', 'tox'] and ('Poison' in target.pokemon.types or 'Steel' in target.pokemon.types):
        return f"\nIt doesn't affect {target.pokemon.name}..."
    if status_to_apply == 'frz' and 'Ice' in target.pokemon.types:
        return f"\nIt doesn't affect {target.pokemon.name}..."
    if status_to_apply == 'slp' and battle.sleep_clause_enabled:
        # Determine which player the target belongs to
        target_player = battle.player1 if target in battle.player1.team else battle.player2
        
        # Check if any Pokémon on that player's team is already asleep
        if any(p.status == 'slp' for p in target_player.team):
            return "\nBut it failed due to the Sleep Clause!"

    # --- Lum Berry Check (Unchanged) ---
    was_cured, cure_log = item_logic.apply_on_status_inflicted(target, battle)
    if was_cured:
        return cure_log

    # --- THIS IS THE NEW, CORRECTED LOGIC ---
    should_apply = False
    secondary = move_data.get('secondary')

    # Case 1: This is a secondary effect from a damaging move.
    if secondary and secondary.get('status') == status_to_apply:
        if random.randint(1, 100) <= secondary.get('chance', 0):
            should_apply = True
    # Case 2: This is a primary status move (like Toxic or Will-O-Wisp).
    elif not secondary and move_data.get('status') == status_to_apply:
        should_apply = True
    # --- END OF NEW LOGIC ---

    if should_apply:
        target.status = status_to_apply
        
        # Set status counters correctly
        if status_to_apply == 'slp':
            target.status_counter = random.randint(1, 3)
        elif status_to_apply == 'tox':
            target.status_counter = 1
        else:
            target.status_counter = 0

        status_map = {
            'brn': 'burned', 'par': 'paralyzed', 'psn': 'poisoned',
            'tox': 'badly poisoned', 'slp': 'put to sleep', 'frz': 'frozen'
        }
        status_name = status_map.get(status_to_apply, 'affected by a status')
        return f"\n{target.pokemon.name} was {status_name}!"

    return ""
    
def _calculate_confusion_damage(attacker: ActivePokemon) -> int:
    """Calculates self-inflicted confusion damage."""
    level = attacker.pokemon.level
    attack = attacker.actual_stats['atk']
    defense = attacker.actual_stats['def']
    power = 40
    damage = int(((((2 * level / 5) + 2) * power * attack / defense) / 50) + 2)
    random_modifier = random.uniform(0.85, 1.0)
    return max(1, int(damage * random_modifier))


def check_can_move(attacker: ActivePokemon, move_id: str) -> Tuple[bool, Optional[str]]:
    """
    Checks for conditions that might prevent a Pokémon from moving.
    Returns a tuple: (can_move: bool, reason: Optional[str])
    """
    # Check for Flinch first as it has top priority.
    if 'focuspunch' in attacker.volatiles and attacker.last_damage_taken > 0:
        del attacker.volatiles['focuspunch'] # Focus is broken
        return (False, f"{attacker.pokemon.name} lost its focus and couldn't move!")

    if 'flinch' in attacker.volatiles:
        del attacker.volatiles['flinch'] # Flinch only lasts one turn
        return (False, f"{attacker.pokemon.name} flinched and couldn't move!")

    if 'infatuation' in attacker.volatiles:
        if random.random() < 0.5: # 50% chance to be immobilized by love
            return (False, f"{attacker.pokemon.name} is infatuated and couldn't move!")

    if 'mustrecharge' in attacker.volatiles:
        del attacker.volatiles['mustrecharge'] # Remove status for next turn
        return (False, f"{attacker.pokemon.name} must recharge!")

    locked_move_state = attacker.volatiles.get('lockedmove')
    if locked_move_state and locked_move_state['turns'] <= 0:
        del attacker.volatiles['lockedmove']
        # Apply confusion
        if 'confusion' not in attacker.volatiles:
            attacker.volatiles['confusion'] = random.randint(1, 4)
            return (True, f"{attacker.pokemon.name} became confused due to fatigue!")
        # If already confused, just let the move proceed
        return (True, None)

    if 'confusion' in attacker.volatiles:
        attacker.volatiles['confusion'] -= 1
        if attacker.volatiles['confusion'] <= 0:
            del attacker.volatiles['confusion']
            return (True, f"{attacker.pokemon.name} snapped out of its confusion!")

        if random.randint(1, 100) <= 33:
            damage = _calculate_confusion_damage(attacker)
            attacker.current_hp = max(0, attacker.current_hp - damage)
            return (False, f"{attacker.pokemon.name} hurt itself in its confusion! It lost {damage} HP!")
    
    if attacker.status == 'par':
        if random.randint(1, 100) <= 25:
            return (False, f"{attacker.pokemon.name} is paralyzed! It can't move!")

    elif attacker.status == 'slp':
        # THIS IS THE MODIFIED BLOCK FOR SLEEP
        if move_id == 'sleeptalk':
            return (True, None) # Allow the move to proceed if it's Sleep Talk

        if attacker.status_counter <= 0:
            attacker.status = None
            attacker.status_counter = 0
            return (True, f"{attacker.pokemon.name} woke up!")
    
        attacker.status_counter -= 1
        return (False, f"{attacker.pokemon.name} is fast asleep...")

    elif attacker.status == 'frz':
        if random.randint(1, 100) <= 20:
            attacker.status = None  
            return (True, f"{attacker.pokemon.name} thawed out!")
        else:
            return (False, f"{attacker.pokemon.name} is frozen solid!")

    return (True, None) # If no condition prevents moving