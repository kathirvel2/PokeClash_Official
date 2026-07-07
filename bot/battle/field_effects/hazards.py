# File: bot/battle/field_effects/hazards.py
from typing import TYPE_CHECKING, Dict, Any
# This is a temporary import, you might want to move TYPE_CHART to a central constants file later


if TYPE_CHECKING:
    from bot.battle.battle_engine import Battle, BattlePlayer
    from bot.mechanics.team import Pokemon

def set_hazard(battle: "Battle", player: "BattlePlayer", condition: str) -> str:
    """Sets a hazard OR a screen on one side of the field."""
    from bot.battle.battle_logic import TYPE_CHART
    
    # --- HAZARD LOGIC (Affects Opponent's Side) ---
    if condition in ['stealthrock', 'spikes','toxicspikes','stickyweb']:
        opponent_hazards = battle.player2_hazards if player.user_id == battle.player1.user_id else battle.player1_hazards
        
        if condition == 'stealthrock':
            if opponent_hazards.get('stealthrock'):
                return "But it failed!"
            opponent_hazards['stealthrock'] = True
            return "Pointed stones float in the air around the opposing team!"

        elif condition == 'spikes':
            layers = opponent_hazards.get('spikes', 0)
            if layers >= 3:
                return "But it failed!"
            opponent_hazards['spikes'] = layers + 1
            return "Spikes were scattered on the opposing team's side of the field!"

        elif condition == 'toxicspikes':
            layers = opponent_hazards.get('toxicspikes', 0)
            if layers >= 2:
                return "But it failed!"
            opponent_hazards['toxicspikes'] = layers + 1
            return "Poisonous spikes were scattered all around the opposing team's feet!"

        elif condition == 'stickyweb':
            if opponent_hazards.get('stickyweb'):
                return "But it failed!"
            opponent_hazards['stickyweb'] = True
            return "A sticky web has been laid out on the opposing team's side!"

    # --- SCREEN LOGIC (Affects User's Side) ---
    elif condition in ['reflect', 'lightscreen']:
        user_screens = battle.player1_screens if player.user_id == battle.player1.user_id else battle.player2_screens
        
        if user_screens.get(condition):
            return "But it failed!"
            
        turns = 5 # Default duration
        if player.get_active_pokemon().pokemon.item == 'Light Clay':
            turns = 8 # Extended duration
            
        user_screens[condition] = turns

        screen_name = "Reflect" if condition == 'reflect' else "Light Screen"
        return f"{screen_name} was put up for {player.user_name}'s team!"
    
    # --- NEW: AURORA VEIL LOGIC ---
    elif condition == 'auroraveil':
        # Check if the weather is Hail/Snow
        if battle.active_weather != 'hail':
            return "But it failed!"
            
        # Check if screens are already active
        user_screens = battle.player1_screens if player.user_id == battle.player1.user_id else battle.player2_screens
        if user_screens.get('reflect') or user_screens.get('lightscreen'):
            return "But it failed!"
            
        # Set both screens for 5 turns
        user_screens['reflect'] = 5
        user_screens['lightscreen'] = 5
        return f"Aurora Veil raised the defenses of {player.user_name}'s team!"
    # --- END OF NEW LOGIC ---
    
    return "Side condition logic not implemented."
    
def apply_hazard_effects(battle: "Battle", player: "BattlePlayer", new_pokemon: "Pokemon") -> Dict[str, Any]:
    """Applies damage and effects from hazards upon switching in. Returns a results dict."""
    from bot.battle.battle_logic import TYPE_CHART
    from bot.battle.move_effects.status_moves import handle_stat_boost_move

    hazards = battle.player1_hazards if player.user_id == battle.player1.user_id else battle.player2_hazards
    total_damage = 0
    log_entries = []
    
    # This dictionary is slightly modified to support status effects from hazards
    results = {
        "damage": 0,
        "log": "",
        "status_effect": None
    }

    # Get the correct max HP from the ActivePokemon object, not the base Pokemon object
    active_poke_obj = next((p for p in player.team if p.pokemon.pokemon_uuid == new_pokemon.pokemon_uuid), None)
    if not active_poke_obj:
        return results # Return the base dictionary if the pokémon isn't found
    max_hp = active_poke_obj.actual_stats['hp']

    is_grounded = 'Flying' not in new_pokemon.types
    if battle.gravity_turns > 0:
        is_grounded = True

    # --- Unaltered Stealth Rock Logic ---
    if hazards.get('stealthrock'):
        rock_effectiveness = 1.0
        for p_type in new_pokemon.types:
            rock_effectiveness *= TYPE_CHART.get('rock', {}).get(p_type.lower(), 1.0)
        
        damage = max(1, int(max_hp * (rock_effectiveness / 8)))
        total_damage += damage
        log_entries.append(f"Pointed stones dug into {new_pokemon.name}!")
        
    # --- Unaltered Spikes Logic ---
    if is_grounded and hazards.get('spikes'):
        layers = hazards.get('spikes', 0)
        damage_fraction = {1: 1/8, 2: 1/6, 3: 1/4}.get(layers, 0)

        damage = max(1, int(max_hp * damage_fraction))
        total_damage += damage
        log_entries.append(f"{new_pokemon.name} was hurt by the spikes!")

    # --- New Logic for Toxic Spikes ---
    if is_grounded and hazards.get('toxicspikes'):
        # Poison-type Pokémon absorb the spikes
        if 'Poison' in new_pokemon.types:
            hazards.pop('toxicspikes', None)
            log_entries.append(f"{new_pokemon.name} absorbed the Toxic Spikes!")
        # --- THIS IS THE FIX ---
        # Steel-type Pokémon are immune but do not absorb them
        elif 'Steel' in new_pokemon.types:
            pass # Do nothing, they are immune
        # --- END OF FIX ---
        # Apply poison if not already statused and not immune
        elif not active_poke_obj.status:
            layers = hazards.get('toxicspikes', 0)
            if layers == 1:
                results["status_effect"] = 'psn'
                log_entries.append(f"{new_pokemon.name} was poisoned!")
            elif layers == 2:
                results["status_effect"] = 'tox'
                log_entries.append(f"{new_pokemon.name} was badly poisoned!")

    # --- New Logic for Sticky Web ---
    if is_grounded and hazards.get('stickyweb'):
        # The handle_stat_boost_move function applies the boost and returns the log string
        temp_move_data = {'boosts': {'spe': -1}}
        log_entries.append(handle_stat_boost_move(active_poke_obj, temp_move_data))
        
    results["damage"] = total_damage
    results["log"] = "\n".join(log_entries)
    
    return results