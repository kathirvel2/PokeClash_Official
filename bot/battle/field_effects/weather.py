# ./bot/battle/field_effects/weather.py
from typing import TYPE_CHECKING, Optional
if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, ActivePokemon

def set_weather(battle: "Battle", weather_type: str, attacker: "ActivePokemon") -> str:
    """Sets the battle weather, extending the duration if the user holds the correct item."""
    weather_type_lower = weather_type.lower()

    if battle.active_weather == weather_type_lower:
        return "\nBut it failed!"

    # --- THIS IS THE NEW LOGIC ---
    turns = 5  # Default duration
    item_map = {
        'raindance': 'Damp Rock',
        'sunnyday': 'Heat Rock',
        'sandstorm': 'Smooth Rock',
        'hail': 'Icy Rock'
    }
    
    # Check if the attacker is holding the correct item for this weather
    if attacker.pokemon.item == item_map.get(weather_type_lower):
        turns = 8
    # --- END OF NEW LOGIC ---

    battle.active_weather = weather_type_lower
    battle.weather_turns = turns

    weather_messages = {
        'raindance': "Rain began to fall!",
        'sunnyday': "The sunlight turned harsh!",
        'sandstorm': "A sandstorm kicked up!",
        'hail': "It started to hail!"
    }
    return f"\n{weather_messages.get(weather_type_lower, 'The weather changed!')}"

def handle_weather_end_of_turn(battle: "Battle") -> Optional[str]:
    """Manages weather duration and effects at the end of a turn. Returns a log message."""
    from bot.battle.ability_effects import is_weather_suppressed
    if not battle.active_weather:
        return None

    if is_weather_suppressed(battle):
        return None

    log_entries = []
    
    # Handle passive damage from Sandstorm or Hail
    if battle.active_weather in ['sandstorm', 'hail']:
        damage_type = 'sand' if battle.active_weather == 'sandstorm' else 'hail'
        immune_types = ['Rock', 'Steel', 'Ground'] if battle.active_weather == 'sandstorm' else ['Ice']
        
        for player in [battle.player1, battle.player2]:
            pokemon = player.get_active_pokemon()
            is_immune = not set(pokemon.pokemon.types).isdisjoint(immune_types)
            # --- ADD THIS CHECK ---
            if pokemon.current_hp > 0 and not is_immune:
                damage = max(1, pokemon.actual_stats['hp'] // 16)
                pokemon.current_hp = max(0, pokemon.current_hp - damage)
                log_entries.append(f"{pokemon.pokemon.name} is buffeted by the {damage_type}!")
            # --- END OF FIX ---
    # Countdown Timer
    battle.weather_turns -= 1
    if battle.weather_turns <= 0:
        weather_name = battle.active_weather.replace('day', '').replace('dance', '').title()
        log_entries.append(f"The {weather_name} stopped.")
        battle.active_weather = None
            
    return "\n".join(log_entries) if log_entries else None