# File: bot/image_generation/trainer_card.py

import os
import io
from PIL import Image, ImageDraw, ImageFont
from bot.mechanics.ranking import get_rank_details

# --- PATH CONSTANTS ---
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BOT_DIR, 'assets') 
FONT_PATH = os.path.join(ASSETS_DIR, 'font.ttf')
CARD_ASSETS_DIR = os.path.join(ASSETS_DIR, 'trainercard')
RANKING_ASSETS_DIR = os.path.join(ASSETS_DIR, 'ranking_system')

# --- NEW: MULTIPLE LAYOUT CONFIGURATIONS ---

# Layout for the standard cards (like card1.png, card2.png, etc.)
LAYOUT_CONFIG_NORMAL = {
    "trainer_sprite": {"pos": (30, 130), "size": (400, 400)},
    "trainer_name":   {"pos": (700, 130), "font_size": 50, "color": "black"},
    "elo_score":      {"pos": (700, 200), "font_size": 45, "color": "black"},
    "win_loss":       {"pos": (700, 240), "font_size": 45, "color": "black"},
    "rank_symbol":    {"pos": (750, 330), "size": (128, 128)},
}

# Layout for your custom cards (Lcard1.png, etc.)
# I've put in different values as an example; you can adjust these as you like.
LAYOUT_CONFIG_CUSTOM = {
    "trainer_sprite": {"pos": (50, 130), "size": (400, 400)},
    "trainer_name":   {"pos": (550, 130), "font_size": 50, "color": "white"},
    "elo_score":      {"pos": (550, 200), "font_size": 45, "color": "white"},
    "win_loss":       {"pos": (550, 250), "font_size": 45, "color": "white"},
    "rank_symbol":    {"pos": (600, 360), "size": (128, 128)},
}

# A dictionary to select the correct layout
LAYOUTS = {
    "normalcard": LAYOUT_CONFIG_NORMAL,
    "customcard": LAYOUT_CONFIG_CUSTOM
}

async def create_trainer_card_image(user_name: str, elo: int, wins: int, losses: int, card_template_path: str, trainer_sprite_name: str, font_color: str) -> io.BytesIO:
    """
    Generates a dynamic trainer card by layering text and sprites onto a base template.
    It now uses a specified font_color for the text.
    """
    
    card_type = "normalcard"
    if 'customcard' in card_template_path:
        card_type = "customcard"
        
    cfg = LAYOUTS.get(card_type, LAYOUT_CONFIG_NORMAL)
    
    # 1. Load Base Card Template
    full_template_path = os.path.join(CARD_ASSETS_DIR, card_template_path)
    try:
        canvas = Image.open(full_template_path).convert("RGBA")
    except FileNotFoundError:
        print(f"!!! ERROR: Card template not found at '{full_template_path}'")
        return None

    draw = ImageDraw.Draw(canvas)
    
    # 2. Load Fonts
    try:
        font_name = ImageFont.truetype(FONT_PATH, cfg['trainer_name']['font_size'])
        font_elo = ImageFont.truetype(FONT_PATH, cfg['elo_score']['font_size'])
        font_wl = ImageFont.truetype(FONT_PATH, cfg['win_loss']['font_size'])
    except IOError:
        print(f"!!! WARNING: Font file not found at '{FONT_PATH}'. Using default font.")
        font_name = font_elo = font_wl = ImageFont.load_default()
        
    # 3. Paste Trainer Sprite
    trainer_sprite_path = os.path.join(CARD_ASSETS_DIR, 'sprites-trainers', trainer_sprite_name)
    try:
        with Image.open(trainer_sprite_path) as sprite:
            sprite = sprite.resize(cfg['trainer_sprite']['size'], Image.Resampling.LANCZOS).convert("RGBA")
            canvas.paste(sprite, cfg['trainer_sprite']['pos'], sprite)
    except FileNotFoundError:
        print(f"!!! WARNING: Trainer sprite not found at '{trainer_sprite_path}'")

    # 4. Paste Rank Symbol
    rank_details = get_rank_details(elo)
    rank_symbol_path = os.path.join(RANKING_ASSETS_DIR, rank_details['name'], rank_details['symbol'])
    try:
        with Image.open(rank_symbol_path) as symbol:
            symbol = symbol.resize(cfg['rank_symbol']['size'], Image.Resampling.LANCZOS).convert("RGBA")
            canvas.paste(symbol, cfg['rank_symbol']['pos'], symbol)
    except FileNotFoundError:
        print(f"!!! WARNING: Rank symbol not found at '{rank_symbol_path}'")
    # ...

    # 5. Draw Text (--- THIS IS THE MODIFIED PART ---)
    # Use the passed font_color instead of the one from the config
    draw.text(cfg['trainer_name']['pos'], user_name, font=font_name, fill=font_color)
    draw.text(cfg['elo_score']['pos'], f"Elo: {elo}", font=font_elo, fill=font_color)
    draw.text(cfg['win_loss']['pos'], f"W/L: {wins} / {losses}", font=font_wl, fill=font_color)

    # 6. Save to buffer and return
    final_image_buffer = io.BytesIO()
    canvas.save(final_image_buffer, format='PNG')
    final_image_buffer.seek(0)
    
    return final_image_buffer