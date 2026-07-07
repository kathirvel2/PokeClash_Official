# ./bot/battle/battle_engine.py
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Set
from bot.mechanics.team import Pokemon
from bot.battle.battle_utils import get_actual_stats
from bot.mechanics.moves_loader import MOVE_BY_ID
import asyncio
from datetime import datetime
from collections import defaultdict

@dataclass
class ActivePokemon:
    """Represents a Pokémon in battle, tracking its own stats, HP, and PP."""
    pokemon: Pokemon
    actual_stats: Dict[str, int]
    current_hp: int = field(init=False)

    stat_multipliers: Dict[str, float] = field(default_factory=lambda: {
        'atk': 1.0, 'def': 1.0, 'spa': 1.0, 'spd': 1.0, 'spe': 1.0,
        'accuracy': 1.0, 'evasion': 1.0
    })

    ability_is_swapped: bool = False

    last_damage_taken: int = 0
    last_damage_category: Optional[str] = None
    last_move_used_by_opponent: Optional[str] = None
    last_move_used: Optional[str] = None
    
    move_pp: Dict[str, int] = field(default_factory=dict)
    status: Optional[str] = None
    status_counter: int = 0
    volatiles: Dict[str, Any] = field(default_factory=dict)
    charging_move: Optional[Dict] = None

    is_protected: bool = False
    consecutive_protect_successes: int = 0

    boosts: Dict[str, int] = field(default_factory=lambda: {
        'atk': 0, 'def': 0, 'spa': 0, 'spd': 0, 'spe': 0,
        'accuracy': 0, 'evasion': 0
    })

    active_turns: int = 0
    
    def __post_init__(self):
        """Initializes current_hp and move_pp."""
        self.current_hp = self.actual_stats['hp']
        
        for move_id in self.pokemon.moves:
            # If the move is a specific Hidden Power, look up the PP of the base move.
            if move_id.startswith('hiddenpower'):
                base_move_data = MOVE_BY_ID.get('hiddenpower', {})
                self.move_pp[move_id] = base_move_data.get('pp', 0)
            else:
                # --- THIS IS THE FIX ---
                # Safely get the move data using .get() to prevent crashes
                # if a move_id from a random battle set isn't in our main data file.
                move_data = MOVE_BY_ID.get(move_id, {})
                self.move_pp[move_id] = move_data.get('pp', 0)

@dataclass
class BattlePlayer:
    """Represents a player, now holding a team of battle-ready Pokémon."""
    user_id: int
    user_name: str
    
    team: List[ActivePokemon]
    active_pokemon_index: int = 0
    ko_count: int = 0
    
    slot_conditions: Dict[str, Any] = field(default_factory=dict)

    side_conditions: Dict[str, Any] = field(default_factory=dict)

    has_mega_evolved: bool = False
    has_dynamaxed: bool = False
    has_used_z_move: bool = False

    def get_active_pokemon(self) -> ActivePokemon:
        """Returns the currently active Pokémon from the team."""
        return self.team[self.active_pokemon_index]

@dataclass
class Battle:
    """The main class that holds the entire state of a battle."""
    chat_id: int
    player1: BattlePlayer
    player2: BattlePlayer
    mode: str = 'turn-based'

    mega_evolution_allowed: bool = True
    dynamax_allowed: bool = True
    is_ranked: bool = False
    sleep_clause_enabled: bool = True

    generation: Optional[int] = None
    
    battle_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_id: Optional[int] = None
    turn: int = 0
    state: str = 'pending'
    terrain: str = "normal.jpg"
    delayed_effects: List[Dict] = field(default_factory=list)

    log_for_faint: str = ""

    start_time: datetime = field(default_factory=datetime.now)
    timer_task: Optional[asyncio.Task] = None
    
    baton_pass_data: Optional[Dict] = None

    active_terrain: Optional[str] = None
    active_terrain_turns: int = 0

    active_weather: Optional[str] = None
    weather_turns: int = 0

    trick_room_turns: int = 0
    gravity_turns: int = 0
    wonder_room_turns: int = 0

    player1_hazards: Dict[str, Any] = field(default_factory=dict)
    player2_hazards: Dict[str, Any] = field(default_factory=dict)
    
    player1_screens: Dict[str, int] = field(default_factory=dict)
    player2_screens: Dict[str, int] = field(default_factory=dict)

    player1_tailwind_turns: int = 0
    player2_tailwind_turns: int = 0

    active_player_id: Optional[int] = None 
    turn_phase: str = 'awaiting_move'
    turn_order: List[Tuple[BattlePlayer, 'ActivePokemon']] = field(default_factory=list)
    winner: Optional[BattlePlayer] = None

    force_switch_flags: List[str] = field(default_factory=list)

    is_processing_turn: bool = False

    last_successful_move: Optional[str] = None

    primed_action: Optional[str] = None

    p1_action: Optional[tuple] = None
    p2_action: Optional[tuple] = None
    run_votes: Set[int] = field(default_factory=set)

    winner_reward: Optional[int] = None
    loser_reward: Optional[int] = None

    def get_player(self, user_id: int) -> Optional[BattlePlayer]:
        if self.player1.user_id == user_id:
            return self.player1
        if self.player2.user_id == user_id:
            return self.player2
        return None

    def get_active_pokemon_for_player(self, player: BattlePlayer) -> ActivePokemon:
        return player.get_active_pokemon()

    def get_opponent_for_player(self, player: BattlePlayer) -> Tuple[BattlePlayer, ActivePokemon]:
        opponent_player = self.player2 if player.user_id == self.player1.user_id else self.player1
        return opponent_player, opponent_player.get_active_pokemon()

active_battles: Dict[int, List['Battle']] = defaultdict(list)