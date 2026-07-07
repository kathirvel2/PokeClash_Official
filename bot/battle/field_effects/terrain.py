# File: bot/battle/field_effects/terrain.py
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, BattlePlayer

def set_terrain(battle: "Battle", terrain_type: str, turns: int) -> str:
    """Sets the battle terrain for a specific number of turns."""
    battle.active_terrain = terrain_type
    battle.active_terrain_turns = turns
    
    terrain_name = terrain_type.replace('terrain', '').title()
    return f"The field became {terrain_name} Terrain!"

def handle_terrain_end_of_turn(battle: "Battle") -> Optional[str]:
    """Manages terrain duration and effects at the end of a turn. Returns a log message."""
    log_entries = []
    if battle.active_terrain:
        # Grassy Terrain Healing
        if battle.active_terrain == 'grassyterrain':
            for player in [battle.player1, battle.player2]:
                pokemon = player.get_active_pokemon()
                is_grounded = 'Flying' not in pokemon.pokemon.types
                # --- ADD THIS CHECK ---
                if is_grounded and pokemon.current_hp > 0 and pokemon.current_hp < pokemon.actual_stats['hp']:
                    heal_amount = pokemon.actual_stats['hp'] // 16
                    pokemon.current_hp = min(pokemon.actual_stats['hp'], pokemon.current_hp + heal_amount)
                    log_entries.append(f"{pokemon.pokemon.name} healed a little from the Grassy Terrain!")
        
        # Countdown Timer
        battle.active_terrain_turns -= 1
        if battle.active_terrain_turns <= 0:
            terrain_name = battle.active_terrain.replace('terrain', '').title()
            log_entries.append(f"The {terrain_name} Terrain faded.")
            battle.active_terrain = None
            
    return "\n".join(log_entries) if log_entries else None

def is_protected_by_terrain(pokemon: "Pokemon", battle: "Battle") -> bool:
    """Checks if a Pokémon is protected from status by active terrain."""
    # Check if the pokemon is immune to grounded hazards/effects
    is_grounded = 'Flying' not in pokemon.types # (and doesn't have Levitate ability)
    
    if battle.active_terrain == 'mistyterrain' and is_grounded:
        return True
        
    return False