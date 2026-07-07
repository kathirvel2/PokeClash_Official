import os
import asyncio
import aiohttp
import io
from PIL import Image, ImageDraw, ImageFont
from typing import List, Optional
from bot.mechanics.team import Pokemon
from bot.services.pokeapi import fetch_pokemon
from bot.battle.battle_utils import find_best_sprite_path


# --- NEW: Configuration for the boxed layout ---
CANVAS_SIZE = 480  # Increased size for better spacing
SPRITE_SIZE = 128  # The size of the box for the sprite
NAME_BOX_HEIGHT = 28
PADDING = 15

# Colors
BROWN_BG = (181, 136, 99)
BOX_BG = (242, 235, 225)
BOX_OUTLINE = (217, 201, 179)
FONT_COLOR = (70, 60, 50)

# Font Path (reusing from your other modules)
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
FONT_PATH = os.path.join(ASSETS_DIR, 'font.ttf')

async def fetch_sprite(session: aiohttp.ClientSession, pokemon: Pokemon) -> Optional[bytes]:
    """Asynchronously fetches the sprite image data for a single Pokemon."""
    try:
        sprite_key = "front_shiny" if pokemon.is_shiny else "front_default"
        api_data = await fetch_pokemon(pokemon.name)
        sprite_url = api_data.get("sprites", {}).get(sprite_key)

        if not sprite_url:
            # Fallback to a placeholder if no sprite is found
            print(f"Warning: Sprite URL not found for {pokemon.name}. Using placeholder.")
            return None

        async with session.get(sprite_url) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception as e:
        print(f"Error fetching sprite for {pokemon.name}: {e}")
    return None

async def create_team_image(team_pokemon: List[Pokemon]) -> Optional[io.BytesIO]:
    """
    MODIFIED: Creates a 3x2 grid image with a brown background, boxes for each
    Pokémon, and a nameplate above each sprite.
    """
    if not team_pokemon:
        return None

    # Create the brown background canvas
    canvas = Image.new('RGBA', (CANVAS_SIZE, CANVAS_SIZE), BROWN_BG)
    draw = ImageDraw.Draw(canvas)
    
    # Load the font
    try:
        font = ImageFont.truetype(FONT_PATH, 16)
    except IOError:
        font = ImageFont.load_default()

    # --- Grid layout calculation ---
    num_cols = 3
    
    # Total width/height of one Pokémon "unit" (name box + sprite box)
    unit_width = SPRITE_SIZE
    unit_height = NAME_BOX_HEIGHT + SPRITE_SIZE
    
    # Calculate the total size of the grid to center it
    grid_width = (unit_width * num_cols) + (PADDING * (num_cols - 1))
    grid_height = (unit_height * 2) + PADDING # For 2 rows
    
    # Top-left starting position to center the grid
    x_offset = (CANVAS_SIZE - grid_width) // 2
    y_offset = (CANVAS_SIZE - grid_height) // 2

    for i, pokemon in enumerate(team_pokemon):
        row = i // num_cols
        col = i % num_cols
        
        # Calculate top-left corner of the entire unit for this Pokémon
        unit_x = x_offset + col * (unit_width + PADDING)
        unit_y = y_offset + row * (unit_height + PADDING)

        # 1. Draw the name box
        name_box_coords = [unit_x, unit_y, unit_x + unit_width, unit_y + NAME_BOX_HEIGHT]
        draw.rectangle(name_box_coords, fill=BOX_BG, outline=BOX_OUTLINE, width=2)
        
        # 2. Draw the Pokémon's name inside the name box
        draw.text(
            (unit_x + unit_width / 2, unit_y + NAME_BOX_HEIGHT / 2),
            pokemon.name,
            font=font,
            fill=FONT_COLOR,
            anchor="mm"  # Middle-middle anchor for perfect centering
        )
        
        # 3. Draw the sprite box
        sprite_box_y = unit_y + NAME_BOX_HEIGHT
        sprite_box_coords = [unit_x, sprite_box_y, unit_x + unit_width, sprite_box_y + SPRITE_SIZE]
        draw.rectangle(sprite_box_coords, fill=BOX_BG, outline=BOX_OUTLINE, width=2)

        # 4. Find and paste the sprite
        sprite_folder = 'sprites-gen5-shiny' if pokemon.is_shiny else 'sprites-gen5'
        sprite_path = find_best_sprite_path(pokemon, sprite_folder)
        
        if sprite_path and os.path.exists(sprite_path):
            with Image.open(sprite_path) as sprite_image:
                # Resize sprite to fit snugly inside the box with a small margin
                sprite_image = sprite_image.convert("RGBA").resize((SPRITE_SIZE - 10, SPRITE_SIZE - 10), Image.Resampling.NEAREST)
                
                # Calculate position to center the sprite inside its box
                sprite_x = unit_x + (SPRITE_SIZE - sprite_image.width) // 2
                sprite_y = sprite_box_y + (SPRITE_SIZE - sprite_image.height) // 2
                
                canvas.paste(sprite_image, (sprite_x, sprite_y), sprite_image)
        else:
            print(f"WARNING: Missing team sprite for '{pokemon.name}' in folder '{sprite_folder}'")

    # Save the final image to a buffer
    final_image_buffer = io.BytesIO()
    canvas.save(final_image_buffer, format='PNG')
    final_image_buffer.seek(0)

    return final_image_buffer