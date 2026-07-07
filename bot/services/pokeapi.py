import aiohttp
from typing import Dict, Optional, Any

BASE_URL = "https://pokeapi.co/api/v2"

# --- NEW: Name mapping for inconsistent API names ---
API_NAME_MAP = {
    "necrozma-dusk-mane": "necrozma-dusk",
    "necrozma-dawn-wings": "necrozma-dawn",
    "gourgeist": "gourgeist-average",
    # Add any other inconsistencies you find here
    # "your-file-name": "pokeapi-name"
}

async def fetch_pokemon(pokemon_name: str) -> Optional[Dict[str, Any]]:
    """Fetches the full Pokémon data from PokeAPI, handling name inconsistencies."""
    
    # --- The Fix is Here ---
    # Check if the name needs to be mapped to a different API name
    api_name = API_NAME_MAP.get(pokemon_name.lower(), pokemon_name.lower())
    
    url = f"{BASE_URL}/pokemon/{api_name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

async def get_pokemon_image_and_stats(pokemon_name: str, is_shiny: bool = False) -> dict:
    """
    Fetches Pokémon data, prioritizing the best available artwork and
    gracefully falling back if shiny versions of specific forms don't exist.
    """
    data = await fetch_pokemon(pokemon_name)
    if not data:
        return {}

    sprites = data.get("sprites", {})
    other_sprites = sprites.get("other", {})
    official_artwork = other_sprites.get("official-artwork", {})

    # --- New, More Robust Image Selection Logic ---
    # Create a priority list of images to try.
    # The code will use the first valid URL it finds in the list.
    image_priority = []

    if is_shiny:
        # For shiny Pokémon, prioritize shiny art but add non-shiny as a fallback.
        image_priority = [
            official_artwork.get("front_shiny"),      # 1. Official Shiny
            sprites.get("front_shiny"),               # 2. Default Shiny Sprite
            official_artwork.get("front_default"),    # 3. FALLBACK: Official Regular
            sprites.get("front_default")              # 4. FALLBACK: Default Regular
        ]
    else:
        # For regular Pokémon
        image_priority = [
            official_artwork.get("front_default"),
            sprites.get("front_default")
        ]

    # Find the first valid image URL from the priority list
    image_url = next((url for url in image_priority if url), None)
            
    stats = {s["stat"]["name"]: s["base_stat"] for s in data.get("stats", [])}
    types = [t["type"]["name"] for t in data.get("types", [])]

    return {
        "name": data.get("name"),
        "id": data.get("id"),
        "image_url": image_url,
        "stats": stats,
        "types": types,
    }