# File: ./bot/image_generation/ranking_image.py
import os
import io
from PIL import Image, ImageDraw, ImageFont
from bot.mechanics.ranking import get_rank_details

# --- PATH CONSTANTS ---
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
RANKING_ASSETS_DIR = os.path.join(ASSETS_DIR, 'ranking_system')
FONT_PATH = os.path.join(ASSETS_DIR, 'font.ttf')
BACKGROUND_PATH = os.path.join(ASSETS_DIR, 'ranking_bg.png')

# --- YOUR NEW HORIZONTAL LAYOUT CONTROL PANEL ---
# Modify the 'pos' (x, y), 'size', and 'font_size' values here to tweak the layout.
LAYOUT_CONFIG = {
    "canvas_size": (512, 512),
    "background_color": "black", # Fallback color
    "border_color": "white",
    "border_width": 4,
    "winner": {
        "title":       {"text": "WINNER", "pos": (256, 40), "font_size": 50, "color": "gold", "anchor": "mt"},
        "rank_sprite": {"pos": (106, 100), "size": (300, 300)},
        "name":        {"pos": (256, 100), "font_size": 36, "color": "white", "anchor": "mt"},
        "rank_symbol": {"pos": (420, 20), "size": (64, 64)},
        "elo":         {"pos": (256, 450), "font_size": 36, "color_change": "lime", "color_main": "white", "anchor": "mt"}
    }
}

def _load_fonts(config):
    """Loads multiple font sizes from the specified font file."""
    fonts = {}
    try:
        fonts['title'] = ImageFont.truetype(FONT_PATH, config['winner']['title']['font_size'])
        fonts['name'] = ImageFont.truetype(FONT_PATH, config['winner']['name']['font_size'])
        fonts['elo'] = ImageFont.truetype(FONT_PATH, config['winner']['elo']['font_size'])
    except IOError:
        print(f"ERROR: Font file not found at {FONT_PATH}. Using default font.")
        fonts['title'] = fonts['name'] = fonts['elo'] = ImageFont.load_default()
    return fonts

def _paste_image(canvas, image_path, pos, size):
    """Helper function to open, resize, and paste an image onto the canvas."""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
            canvas.paste(img, pos, img)
    except FileNotFoundError:
        print(f"ERROR: Could not find ranking asset at {image_path}")
        return False
    return True

def _draw_player_info(draw, config, player_name, old_elo, new_elo, fonts):
    """Draws all text elements for a single player."""
    rank_change = new_elo - old_elo

    # Draw title and name
    draw.text(config['title']['pos'], config['title']['text'], fill=config['title']['color'], font=fonts['title'], anchor=config['title']['anchor'])
    draw.text(config['name']['pos'], player_name, fill=config['name']['color'], font=fonts['name'], anchor=config['name']['anchor'])

    # --- THIS IS THE NEW ELO DRAWING LOGIC ---
    elo_font = fonts['elo']
    
    # Part 1: "OLD -> NEW " (with a space)
    elo_part1 = f"{old_elo} -> {new_elo} "
    # Part 2: "(+CHANGE)"
    elo_part2 = f"(+{abs(rank_change)})"
    
    # Calculate widths of both parts
    width1 = draw.textlength(elo_part1, font=elo_font)
    width2 = draw.textlength(elo_part2, font=elo_font)
    total_width = width1 + width2

    # Calculate starting position to keep the whole text block centered
    center_x = config['elo']['pos'][0]
    y_pos = config['elo']['pos'][1]
    start_x = center_x - (total_width / 2)

    # Draw Part 1 in white
    draw.text((start_x, y_pos), elo_part1, fill=config['elo']['color_main'], font=elo_font, anchor="lt")
    # Draw Part 2 in green, positioned right after Part 1
    draw.text((start_x + width1, y_pos), elo_part2, fill=config['elo']['color_change'], font=elo_font, anchor="lt")
    # --- END OF NEW LOGIC ---

async def create_ranking_summary_image(
    winner_name: str, winner_old_elo: int, winner_new_elo: int
) -> io.BytesIO:
    """
    Generates a configurable 512x512 image summarizing the results of a ranked battle.
    """
    cfg = LAYOUT_CONFIG

    # Try to load the background image, with a fallback
    try:
        canvas = Image.open(BACKGROUND_PATH).convert("RGB").resize(cfg['canvas_size'], Image.Resampling.LANCZOS)
    except FileNotFoundError:
        print(f"Background image not found at {BACKGROUND_PATH}. Using fallback color.")
        canvas = Image.new('RGB', cfg['canvas_size'], cfg['background_color'])

    draw = ImageDraw.Draw(canvas)
    fonts = _load_fonts(cfg)

    # Draw border
    draw.rectangle([0, 0, cfg['canvas_size'][0] - 1, cfg['canvas_size'][1] - 1],
                   outline=cfg['border_color'], width=cfg['border_width'])

    # Get rank details
    winner_rank_details = get_rank_details(winner_new_elo)

    # Draw all text elements
    _draw_player_info(draw, cfg['winner'], winner_name, winner_old_elo, winner_new_elo, fonts)

    # Paste all image assets
    winner_sprite_path = os.path.join(RANKING_ASSETS_DIR, winner_rank_details['name'], winner_rank_details['sprite'])
    _paste_image(canvas, winner_sprite_path, cfg['winner']['rank_sprite']['pos'], cfg['winner']['rank_sprite']['size'])

    winner_symbol_path = os.path.join(RANKING_ASSETS_DIR, winner_rank_details['name'], winner_rank_details['symbol'])
    _paste_image(canvas, winner_symbol_path, cfg['winner']['rank_symbol']['pos'], cfg['winner']['rank_symbol']['size'])

    # Save to buffer and return
    final_image_buffer = io.BytesIO()
    canvas.save(final_image_buffer, format='PNG')
    final_image_buffer.seek(0)

    return final_image_buffer