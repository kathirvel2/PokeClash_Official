from typing import List, Dict
from collections import Counter
from bot.mechanics.team import Pokemon

# A full type chart: attacking_type -> defending_type -> multiplier
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
ALL_TYPES = list(TYPE_CHART.keys())

def analyze_team_coverage(team_pokemon: List[Pokemon]) -> Dict[str, List[str]]:
    """Analyzes the team's type weaknesses and resistances."""
    weakness_counter = Counter()
    resistance_counter = Counter()

    for pokemon in team_pokemon:
        pokemon_types = [t.lower() for t in pokemon.types]
        
        # Calculate vulnerabilities for this single Pokémon
        for attacking_type in ALL_TYPES:
            multiplier = 1.0
            for defending_type in pokemon_types:
                multiplier *= TYPE_CHART.get(attacking_type, {}).get(defending_type, 1.0)
            
            if multiplier >= 2:
                weakness_counter[attacking_type.capitalize()] += 1
            elif 0 < multiplier < 1:
                resistance_counter[attacking_type.capitalize()] += 1

    # Find the most common weaknesses (types the team is frequently weak to)
    # The 'most_common' method returns a list of (element, count) tuples
    top_weaknesses = [f"{w} (x{c})" for w, c in weakness_counter.most_common(3)]
    
    # Find types the team resists most often
    top_resistances = [f"{r} (x{c})" for r, c in resistance_counter.most_common(3)]

    return {
        "weaknesses": top_weaknesses,
        "resistances": top_resistances,
    }

def format_analysis_caption(team_name: str, team_pokemon: List[Pokemon], analysis: Dict) -> str:
    """Formats the team analysis data into a clean HTML caption."""
    
    team_types = set()
    for p in team_pokemon:
        team_types.update(p.types)
    
    caption = f"<b>Team Analysis: {team_name}</b>\n\n"
    
    # --- MODIFICATION START ---
    # Add a new section for the team roster with items
    caption += "<b><u>Team Roster</u></b>\n"
    for p in team_pokemon:
        # Use html.escape to be safe with special characters in names or items
        item_name = p.item or 'None'
        caption += f"• <b>{p.name}</b> @ <i>{item_name}</i>\n"
        caption += f"  Tera: <i>{p.tera_type or 'Unknown'}</i>\n"
    caption += "\n"
    # --- MODIFICATION END ---
    
    caption += "<b><u>Type Coverage</u></b>\n"
    caption += f"• <b>Types Present:</b> {', '.join(sorted(list(team_types)))}\n\n"
    
    caption += "<b><u>Defensive Overview</u></b>\n"
    if analysis["weaknesses"]:
        caption += f"• <b>Common Weaknesses:</b> {', '.join(analysis['weaknesses'])}\n"
    else:
        caption += "• No significant weaknesses found.\n"
        
    if analysis["resistances"]:
        caption += f"• <b>Common Resistances:</b> {', '.join(analysis['resistances'])}\n"
    else:
        caption += "• No significant resistances found.\n"

    return caption
