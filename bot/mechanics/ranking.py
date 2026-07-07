# File: ./bot/mechanics/ranking.py
import math

# Define the Elo thresholds for each rank
RANK_TIERS = {
    "Beginner": 0,
    "Great": 1200,
    "Expert": 1400,
    "Veteran": 1600,
    "Ultra": 1800,
    "Master": 2000
}

def get_rank_details(elo_score: int) -> dict:
    """
    Determines a player's rank name and asset files based on their Elo score.
    """
    if elo_score is None: elo_score = 1000

    player_rank_name = "Beginner"
    for rank_name, threshold in RANK_TIERS.items():
        if elo_score >= threshold:
            player_rank_name = rank_name
        else:
            break

    sprite_file = f"UNITE_{player_rank_name}_Rank_Sprite.png"
    symbol_file = f"UNITE_{player_rank_name}_Rank_Symbol.png"

    # For non-Master ranks, determine which of the 5 class symbols to use
    if player_rank_name != "Master":
        next_rank_elo = RANK_TIERS.get(list(RANK_TIERS.keys())[list(RANK_TIERS.keys()).index(player_rank_name) + 1], float('inf'))
        rank_elo_range = next_rank_elo - RANK_TIERS[player_rank_name]
        class_size = rank_elo_range / 5
        
        elo_in_rank = elo_score - RANK_TIERS[player_rank_name]
        class_num = min(5, math.floor(elo_in_rank / class_size) + 1)
        symbol_file = f"UNITE_{player_rank_name}_Rank_Symbol_{class_num}.png"

    return {
        "name": player_rank_name,
        "sprite": sprite_file,
        "symbol": symbol_file
    }

def calculate_elo_change(player_rating: int, opponent_rating: int, score: float) -> int:
    """
    Calculates the new Elo rating for a player.
    """
    K_FACTOR = 32
    expected_score = 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))
    rating_change = K_FACTOR * (score - expected_score)
    return round(rating_change)