# ./bot/mechanics/db.py
import json
import uuid
import os
import secrets
import string
import psycopg2
from typing import Dict, List, Optional, Any
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta # <-- THIS IS THE NEW LINE

from bot.mechanics.team import Pokemon, Stats
from bot.mechanics.moves_loader import SPECIES_BY_ID

class EnhancedJSONEncoder(json.JSONEncoder):
    """A custom JSON encoder that can handle dataclasses."""
    def default(self, o):
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)

class PokemonDatabase:
    """Handles all database operations for the Pokémon RPG Bot using PostgreSQL."""
    def __init__(self):
        # --- MODIFIED: Load all necessary DB variables from environment ---
        self.db_host = os.getenv("DB_HOST")
        self.db_name = os.getenv("DB_NAME")
        self.db_user = os.getenv("DB_USER")
        self.db_pass = os.getenv("DB_PASS")
        self.db_port = os.getenv("DB_PORT", "5432") # Default to 5432 if not set
        self.db_sslmode = os.getenv("DB_SSLMODE")   # Will be None if not set
        self.db_sslcert = os.getenv("DB_SSLCERT")   # Will be None if not set
        self.init_database()

    def _get_connection(self):
        """Establishes and returns a flexible PostgreSQL database connection."""
        # --- MODIFIED: Build connection parameters dynamically ---
        conn_params = {
            'host': self.db_host,
            'dbname': self.db_name,
            'user': self.db_user,
            'password': self.db_pass,
            'port': self.db_port
        }
        if self.db_sslmode:
            conn_params['sslmode'] = self.db_sslmode
        if self.db_sslcert:
            conn_params['sslrootcert'] = self.db_sslcert

        conn = psycopg2.connect(**conn_params)
        return conn

    # ... (The rest of the file is unchanged) ...
    def _add_column_if_not_exists(self, cursor, table_name, column_name, column_definition):
        cursor.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """, (table_name, column_name))
        exists = cursor.fetchone()
        if not exists:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
            print(f"Added column '{column_name}' to table '{table_name}'.")
    
    def init_database(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                user_id BIGINT PRIMARY KEY, pokemon_data JSONB,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teams (
                team_id SERIAL PRIMARY KEY, user_id BIGINT, team_name TEXT,
                pokemon_uuids JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS implementation_status (
                category TEXT NOT NULL,
                item_id TEXT NOT NULL,
                is_implemented BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (category, item_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                reward_clash_coins INTEGER DEFAULT 0,
                reward_shiny_passes INTEGER DEFAULT 0,
                reward_legendary_passes INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT 1,
                remaining_uses INTEGER DEFAULT 1,
                created_by BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS redeem_code_claims (
                code TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                claimed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (code, user_id),
                FOREIGN KEY (code) REFERENCES redeem_codes (code) ON DELETE CASCADE
            )
        ''')
        self._add_column_if_not_exists(cursor, 'users', 'active_team_id', 'INTEGER')
        self._add_column_if_not_exists(cursor, 'users', 'battle_mode', "TEXT DEFAULT 'turn-based'")
        self._add_column_if_not_exists(cursor, 'users', 'mega_enabled', "BOOLEAN DEFAULT TRUE")
        self._add_column_if_not_exists(cursor, 'users', 'gmax_enabled', "BOOLEAN DEFAULT TRUE")

        self._add_column_if_not_exists(cursor, 'users', 'elo_score', 'INTEGER DEFAULT 1000')
        self._add_column_if_not_exists(cursor, 'users', 'wins', 'INTEGER DEFAULT 0')
        self._add_column_if_not_exists(cursor, 'users', 'losses', 'INTEGER DEFAULT 0')
        self._add_column_if_not_exists(cursor, 'users', 'draws', 'INTEGER DEFAULT 0')

        self._add_column_if_not_exists(cursor, 'users', 'ranking_enabled', 'BOOLEAN DEFAULT FALSE')
        self._add_column_if_not_exists(cursor, 'users', 'card_template', "TEXT DEFAULT 'normalcard/card1.png'")
        self._add_column_if_not_exists(cursor, 'users', 'trainer_sprite', "TEXT DEFAULT 'ethan.png'")
        self._add_column_if_not_exists(cursor, 'users', 'card_font_color', "TEXT DEFAULT 'white'")

        self._add_column_if_not_exists(cursor, 'users', 'legendary_mode', "BOOLEAN DEFAULT FALSE")
        self._add_column_if_not_exists(cursor, 'users', 'non_legendary_mode', "BOOLEAN DEFAULT FALSE")
        self._add_column_if_not_exists(cursor, 'users', 'sleep_clause_enabled', "BOOLEAN DEFAULT TRUE")

        self._add_column_if_not_exists(cursor, 'users', 'random_battle_generation', "INTEGER DEFAULT 0")
        self._add_column_if_not_exists(cursor, 'users', 'battle_visuals', "BOOLEAN DEFAULT FALSE")
        self._add_column_if_not_exists(cursor, 'users', 'showdown_singles_mode', 'TEXT')
        self._add_column_if_not_exists(cursor, 'users', 'showdown_singles_format', 'TEXT')
        self._add_column_if_not_exists(cursor, 'users', 'showdown_doubles_mode', 'TEXT')
        self._add_column_if_not_exists(cursor, 'users', 'showdown_doubles_format', 'TEXT')
        self._add_column_if_not_exists(cursor, 'users', 'showdown_ffa_mode', 'TEXT')
        self._add_column_if_not_exists(cursor, 'users', 'showdown_ffa_format', 'TEXT')

        self._add_column_if_not_exists(cursor, 'users', 'shiny_pass_count', 'INTEGER DEFAULT 1')
        self._add_column_if_not_exists(cursor, 'users', 'legendary_pass_count', 'INTEGER DEFAULT 0')

        self._add_column_if_not_exists(cursor, 'users', 'clash_coins', 'INTEGER DEFAULT 1000')

        self._add_column_if_not_exists(cursor, 'users', 'favorite_pokemon_uuid', 'TEXT NULL')
        self._add_column_if_not_exists(cursor, 'users', 'max_pokemon_slots', 'INTEGER DEFAULT 12')

        # --- NEW ADMIN & BAN COLUMNS ---
        self._add_column_if_not_exists(cursor, 'users', 'is_banned', 'BOOLEAN DEFAULT FALSE')
        self._add_column_if_not_exists(cursor, 'users', 'is_battle_banned', 'BOOLEAN DEFAULT FALSE')
        # --- END NEW COLUMNS ---

        # --- DISPLAY SETTING ---
        self._add_column_if_not_exists(cursor, 'users', 'display_setting', "TEXT DEFAULT 'Level'")

        conn.commit()
        cursor.close()
        conn.close()

    def get_user_by_id(self, user_id: int) -> Optional[Any]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        return user_data

    def add_user(self, user_id: int, username: str, first_name: str, last_name: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        sql = '''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name
        '''
        cursor.execute(sql, (user_id, username, first_name, last_name))
        conn.commit()
        cursor.close()
        conn.close()

    def get_collection(self, user_id: int) -> List[Pokemon]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT pokemon_data FROM collections WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        if not result or not result[0]:
            return []
            
        collection_data = result[0] 
        collection: List[Pokemon] = []
        for p_data in collection_data:
            # --- FIX STARTS HERE ---
            # If a Pokémon from the database doesn't have a weight (because it's old data),
            # look it up from its species ID and add it.
            if 'weight' not in p_data:
                species_info = SPECIES_BY_ID.get(p_data['id'], {})
                p_data['weight'] = species_info.get('weightkg', 0.1)
            # --- FIX ENDS HERE ---

            base_stats = Stats(**p_data.pop("base_stats"))
            ivs = Stats(**p_data.pop("ivs"))
            evs = Stats(**p_data.pop("evs"))
            collection.append(Pokemon(base_stats=base_stats, ivs=ivs, evs=evs, **p_data))
        return collection

    def save_collection(self, user_id: int, collection: List[Pokemon]):
        conn = self._get_connection()
        cursor = conn.cursor()
        collection_data = json.dumps([p for p in collection], cls=EnhancedJSONEncoder)
        sql = '''
            INSERT INTO collections (user_id, pokemon_data) VALUES (%s, %s)
            ON CONFLICT(user_id) DO UPDATE SET pokemon_data = EXCLUDED.pokemon_data
        '''
        cursor.execute(sql, (user_id, collection_data))
        conn.commit()
        cursor.close()
        conn.close()
    
    def add_pokemon_to_collection(self, user_id: int, pokemon: Pokemon):
        collection = self.get_collection(user_id)
        collection.append(pokemon)
        self.save_collection(user_id, collection)

    def get_pokemon_from_collection(self, user_id: int, pokemon_uuid: str) -> Optional[Pokemon]:
        collection = self.get_collection(user_id)
        return next((p for p in collection if p.pokemon_uuid == pokemon_uuid), None)

    def update_pokemon_in_collection(self, user_id: int, updated_pokemon: Pokemon):
        collection = self.get_collection(user_id)
        for i, p in enumerate(collection):
            if p.pokemon_uuid == updated_pokemon.pokemon_uuid:
                collection[i] = updated_pokemon
                self.save_collection(user_id, collection)
                return True
        return False

    def remove_pokemon_from_collection(self, user_id: int, pokemon_uuid: str):
        collection = self.get_collection(user_id)
        collection = [p for p in collection if p.pokemon_uuid != pokemon_uuid]
        self.save_collection(user_id, collection)
        user_teams = self.get_user_teams(user_id)
        for team in user_teams:
            team_id = team[0]
            team_pokemon_uuids = team[3]
            if team_pokemon_uuids and pokemon_uuid in team_pokemon_uuids:
                team_pokemon_uuids.remove(pokemon_uuid)
                self.update_team(team_id, team_pokemon_uuids)

    def create_team(self, user_id: int, team_name: str) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()
        sql = '''
            INSERT INTO teams (user_id, team_name, pokemon_uuids)
            VALUES (%s, %s, %s) RETURNING team_id
        '''
        cursor.execute(sql, (user_id, team_name, json.dumps([])))
        new_team_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return new_team_id

    def get_user_teams(self, user_id: int) -> List[Any]:
        conn = self._get_connection()
        cursor = conn.cursor()
        sql = 'SELECT * FROM teams WHERE user_id = %s ORDER BY team_id'
        cursor.execute(sql, (user_id,))
        teams = cursor.fetchall()
        cursor.close()
        conn.close()
        return teams

    def update_team(self, team_id: int, pokemon_uuids: List[str], new_name: Optional[str] = None):
        conn = self._get_connection()
        cursor = conn.cursor()
        if new_name:
            cursor.execute('UPDATE teams SET team_name = %s WHERE team_id = %s', (new_name, team_id))
        cursor.execute('UPDATE teams SET pokemon_uuids = %s WHERE team_id = %s', (json.dumps(pokemon_uuids), team_id))
        conn.commit()
        cursor.close()
        conn.close()
        
    def delete_team(self, team_id: int):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM teams WHERE team_id = %s', (team_id,))
        conn.commit()
        cursor.close()
        conn.close()

    def get_active_team(self, user_id: int) -> Optional[Any]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT active_team_id FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        active_id = result[0] if result and result[0] else None
        if not active_id:
            cursor.execute('SELECT team_id FROM teams WHERE user_id = %s ORDER BY team_id LIMIT 1', (user_id,))
            first_team = cursor.fetchone()
            if first_team:
                active_id = first_team[0]
                self.set_active_team(user_id, active_id)
        if not active_id:
            cursor.close()
            conn.close()
            return None
        cursor.execute('SELECT * FROM teams WHERE team_id = %s', (active_id,))
        active_team = cursor.fetchone()
        cursor.close()
        conn.close()
        return active_team

    def set_active_team(self, user_id: int, team_id: int):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET active_team_id = %s WHERE user_id = %s', (team_id, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_battle_mode(self, user_id: int) -> str:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT battle_mode FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else 'turn-based'
    
    def set_battle_mode(self, user_id: int, mode: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET battle_mode = %s WHERE user_id = %s', (mode, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_all_statuses(self) -> dict[str, dict[str, bool]]:
        """Fetches all implementation statuses from the DB."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT category, item_id, is_implemented FROM implementation_status')
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        statuses = {}
        for category, item_id, is_implemented in rows:
            if category not in statuses:
                statuses[category] = {}
            statuses[category][item_id] = is_implemented
        return statuses

    def set_status(self, category: str, item_id: str, status: bool):
        """Adds or updates an implementation status in the DB."""
        conn = self._get_connection()
        cursor = conn.cursor()
        sql = '''
            INSERT INTO implementation_status (category, item_id, is_implemented)
            VALUES (%s, %s, %s)
            ON CONFLICT (category, item_id)
            DO UPDATE SET is_implemented = EXCLUDED.is_implemented;
        '''
        cursor.execute(sql, (category, item_id, status))
        conn.commit()
        cursor.close()
        conn.close()

    def get_team_by_id(self, team_id: int) -> Optional[Any]:
        """Fetches a single team by its primary key."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM teams WHERE team_id = %s', (team_id,))
        team_data = cursor.fetchone()
        cursor.close()
        conn.close()
        return team_data

    def get_mega_setting(self, user_id: int) -> bool:
        """Gets the user's Mega Evolution setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT mega_enabled FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        # Default to True if for some reason the setting is not found
        return result[0] if result else True

    def set_mega_setting(self, user_id: int, is_enabled: bool):
        """Sets the user's Mega Evolution setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET mega_enabled = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_gmax_setting(self, user_id: int) -> bool:
        """Gets the user's G-Max setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT gmax_enabled FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else True
    
    def set_gmax_setting(self, user_id: int, is_enabled: bool):
        """Sets the user's G-Max setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET gmax_enabled = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_user_stats(self, user_id: int) -> Optional[tuple]:
        """Fetches a user's elo_score, wins, losses, and draws."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT elo_score, wins, losses, draws FROM users WHERE user_id = %s', (user_id,))
        stats = cursor.fetchone()
        cursor.close()
        conn.close()
        return stats
    
    def update_user_stats(self, user_id: int, new_elo: int, win: int, loss: int, draw: int):
        """Updates a user's battle stats."""
        conn = self._get_connection()
        cursor = conn.cursor()
        sql = '''
            UPDATE users 
            SET 
                elo_score = %s, 
                wins = wins + %s, 
                losses = losses + %s, 
                draws = draws + %s
            WHERE user_id = %s
        '''
        cursor.execute(sql, (new_elo, win, loss, draw, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    
    def get_leaderboard(self, mode: str = 'overall', limit: int = 10, offset: int = 0) -> List[tuple]:
        """Fetches top players. mode can be 'overall' (by wins) or 'ranked' (by Elo)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Require at least 1 match played to be on the board
        if mode == 'ranked':
            order_clause = "elo_score DESC, wins DESC"
        else: # 'overall'
            order_clause = "wins DESC, elo_score DESC"
            
        sql = f'''
            SELECT first_name, elo_score, wins, losses, draws 
            FROM users 
            WHERE (wins + losses + draws) > 0
            ORDER BY {order_clause} 
            LIMIT %s OFFSET %s
        '''
        cursor.execute(sql, (limit, offset))
        leaderboard = cursor.fetchall()
        cursor.close()
        conn.close()
        return leaderboard

    def get_ranking_setting(self, user_id: int) -> bool:
        """Gets the user's preference for ranked battles."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT ranking_enabled FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else False
    
    def set_ranking_setting(self, user_id: int, is_enabled: bool):
        """Sets the user's preference for ranked battles."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET ranking_enabled = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_user_card_prefs(self, user_id: int) -> tuple:
        """Fetches the user's card template, trainer sprite, and font color."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT card_template, trainer_sprite, card_font_color FROM users WHERE user_id = %s', (user_id,))
        prefs = cursor.fetchone()
        cursor.close()
        conn.close()
        return prefs or ('normalcard/card1.png', 'ethan.png', 'white')

    def set_user_card_pref(self, user_id: int, pref_type: str, value: str):
        """Sets the card_template, trainer_sprite, or card_font_color for a user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        # Use a safe way to format the column name
        if pref_type not in ['card_template', 'trainer_sprite', 'card_font_color']:
            return
        sql = f"UPDATE users SET {pref_type} = %s WHERE user_id = %s"
        cursor.execute(sql, (value, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_legendary_setting(self, user_id: int) -> bool:
        """Gets the user's Legendary Mode setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT legendary_mode FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else False

    def set_legendary_setting(self, user_id: int, is_enabled: bool):
        """Sets the user's Legendary Mode setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET legendary_mode = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_non_legendary_setting(self, user_id: int) -> bool:
        """Gets the user's Non-Legendary Mode setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT non_legendary_mode FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else False

    def set_non_legendary_setting(self, user_id: int, is_enabled: bool):
        """Sets the user's Non-Legendary Mode setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET non_legendary_mode = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_sleep_clause_setting(self, user_id: int) -> bool:
        """Gets the user's Sleep Clause setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT sleep_clause_enabled FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        # Default to True if the setting is somehow not found
        return result[0] if result is not None else True

    def set_sleep_clause_setting(self, user_id: int, is_enabled: bool):
        """Sets the user's Sleep Clause setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET sleep_clause_enabled = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_random_battle_setting(self, user_id: int) -> int:
        """Gets the user's saved Random Battle generation (0 means off)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT random_battle_generation FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        # Return the generation number if it exists, otherwise return 0 (off)
        return result[0] if result else 0

    def set_random_battle_setting(self, user_id: int, generation: int):
        """Sets the user's Random Battle generation preference (0 means off)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET random_battle_generation = %s WHERE user_id = %s', (generation, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_battle_visuals_setting(self, user_id: int) -> bool:
        """Gets whether the user wants Showdown battle visuals enabled."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT battle_visuals FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else False

    def set_battle_visuals_setting(self, user_id: int, is_enabled: bool):
        """Sets whether the user wants Showdown battle visuals enabled."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET battle_visuals = %s WHERE user_id = %s', (is_enabled, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def _showdown_preference_columns(self, battle_kind: str) -> tuple[str, str]:
        normalized = str(battle_kind or '').strip().lower()
        mapping = {
            'singles': ('showdown_singles_mode', 'showdown_singles_format'),
            'doubles': ('showdown_doubles_mode', 'showdown_doubles_format'),
            'freeforall': ('showdown_ffa_mode', 'showdown_ffa_format'),
        }
        return mapping.get(normalized, mapping['singles'])

    def get_showdown_challenge_preferences(self, user_id: int, battle_kind: str) -> tuple[Optional[str], Optional[str]]:
        """Gets the saved Showdown challenge mode and format for a battle kind."""
        mode_column, format_column = self._showdown_preference_columns(battle_kind)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT {mode_column}, {format_column} FROM users WHERE user_id = %s',
            (user_id,),
        )
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        if not result:
            return None, None
        return result[0], result[1]

    def set_showdown_challenge_preferences(
        self,
        user_id: int,
        battle_kind: str,
        *,
        mode: Optional[str] = None,
        format_key: Optional[str] = None,
    ) -> None:
        """Saves the Showdown challenge mode and format for a battle kind."""
        updates: list[str] = []
        values: list[Any] = []
        mode_column, format_column = self._showdown_preference_columns(battle_kind)

        if mode is not None:
            updates.append(f'{mode_column} = %s')
            values.append(mode)
        if format_key is not None:
            updates.append(f'{format_column} = %s')
            values.append(format_key)
        if not updates:
            return

        values.append(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f'UPDATE users SET {", ".join(updates)} WHERE user_id = %s',
            tuple(values),
        )
        conn.commit()
        cursor.close()
        conn.close()

    def pokemon_uuid_exists(self, pokemon_uuid: str) -> bool:
        """Checks if a Pokémon with the given UUID exists in any user's collection."""
        conn = self._get_connection()
        cursor = conn.cursor()
        # This query efficiently checks the JSONB data for the UUID
        sql = """
            SELECT 1 FROM collections 
            WHERE pokemon_data @> %s 
            LIMIT 1;
        """
        # The format for the JSONB query is '[{"pokemon_uuid": "your_uuid"}]'
        cursor.execute(sql, (json.dumps([{"pokemon_uuid": pokemon_uuid}]),))
        exists = cursor.fetchone()
        cursor.close()
        conn.close()
        return exists is not None

    def get_shiny_pass_count(self, user_id: int) -> int:
        """Fetches the user's current shiny pass count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT shiny_pass_count FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else 0

    def update_shiny_pass_count(self, user_id: int, new_count: int):
        """Updates the user's shiny pass count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET shiny_pass_count = GREATEST(0, %s) WHERE user_id = %s',
            (new_count, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def add_shiny_passes(self, user_id: int, amount: int):
        """Adds a specified amount of shiny passes to a user's total."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET shiny_pass_count = GREATEST(0, shiny_pass_count + %s) WHERE user_id = %s',
            (amount, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def get_legendary_pass_count(self, user_id: int) -> int:
        """Fetches the user's current legendary shiny pass count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT legendary_pass_count FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else 0

    def update_legendary_pass_count(self, user_id: int, new_count: int):
        """Updates the user's legendary shiny pass count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET legendary_pass_count = GREATEST(0, %s) WHERE user_id = %s',
            (new_count, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def add_legendary_passes(self, user_id: int, amount: int):
        """Adds a specified amount of legendary shiny passes to a user's total."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET legendary_pass_count = GREATEST(0, legendary_pass_count + %s) WHERE user_id = %s',
            (amount, user_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

    def get_clash_coin_count(self, user_id: int) -> int:
        """Fetches the user's current Clash Coin count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT clash_coins FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else 0

    def add_clash_coins(self, user_id: int, amount: int):
        """Adds a specified amount of Clash Coins to a user's total."""
        conn = self._get_connection()
        cursor = conn.cursor()
        sql = 'UPDATE users SET clash_coins = GREATEST(0, clash_coins + %s) WHERE user_id = %s'
        cursor.execute(sql, (amount, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def set_user_favorite_pokemon(self, user_id: int, pokemon_uuid: str):
        """Sets the user's favorite Pokémon UUID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET favorite_pokemon_uuid = %s WHERE user_id = %s', (pokemon_uuid, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_max_slots(self, user_id: int) -> int:
        """Fetches the user's current maximum Pokémon slot count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT max_pokemon_slots FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result else 12
    
    def set_max_slots(self, user_id: int, new_limit: int):
        """Updates the user's maximum Pokémon slot count."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET max_pokemon_slots = %s WHERE user_id = %s', (new_limit, user_id))
        conn.commit()
        cursor.close()
        conn.close()

    def get_display_setting(self, user_id: int) -> str:
        """Fetches the user's display setting (Level/Nature/Ability/Type/Tier/BST)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT display_setting FROM users WHERE user_id = %s', (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result[0] if result and result[0] else 'Level'

    def set_display_setting(self, user_id: int, setting: str):
        """Sets the user's display setting."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET display_setting = %s WHERE user_id = %s', (setting, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    
    # --- NEW ADMIN FUNCTIONS ---
    
    def get_admin_stats(self) -> Dict[str, Any]:
        """Fetches aggregate statistics for the admin panel."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            # Total users
            cursor.execute("SELECT COUNT(*) FROM users")
            stats['total_users'] = cursor.fetchone()[0]
            
            # New users in last 24 hours
            cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= %s", (datetime.now() - timedelta(days=1),))
            stats['new_users_24h'] = cursor.fetchone()[0]
            
            # Total Pokemon (This is slow, consider optimization later if needed)
            cursor.execute("SELECT jsonb_array_length(pokemon_data) FROM collections")
            stats['total_pokemon'] = sum(row[0] for row in cursor.fetchall() if row[0])
            
            # Total teams
            cursor.execute("SELECT COUNT(*) FROM teams")
            stats['total_teams'] = cursor.fetchone()[0]
            
            # Total battles, coins, passes
            cursor.execute(
                "SELECT SUM(wins + losses + draws), SUM(clash_coins), SUM(shiny_pass_count), SUM(legendary_pass_count) FROM users"
            )
            battle_stats = cursor.fetchone()
            stats['total_battles'] = battle_stats[0] or 0
            stats['total_coins'] = battle_stats[1] or 0
            stats['total_passes'] = battle_stats[2] or 0
            stats['total_legendary_passes'] = battle_stats[3] or 0
            
        finally:
            cursor.close()
            conn.close()
            
        return stats

    def search_users(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Searches for users by name or ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if query is a number (for user_id search)
        try:
            user_id_query = int(query)
            sql = "SELECT user_id, first_name, is_banned, is_battle_banned FROM users WHERE user_id = %s LIMIT %s"
            params = (user_id_query, limit)
        except ValueError:
            # It's a name search
            sql = "SELECT user_id, first_name, is_banned, is_battle_banned FROM users WHERE first_name ILIKE %s LIMIT %s"
            params = (f"%{query}%", limit)
            
        cursor.execute(sql, params)
        users = [{"user_id": row[0], "first_name": row[1], "is_banned": row[2], "is_battle_banned": row[3]} for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        return users

    def get_user_admin_details(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Gets detailed info for a single user for the admin panel."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, first_name, clash_coins, shiny_pass_count, legendary_pass_count, max_pokemon_slots, is_banned, is_battle_banned FROM users WHERE user_id = %s",
            (user_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row:
            return {
                "user_id": row[0],
                "first_name": row[1],
                "clash_coins": row[2],
                "shiny_pass_count": row[3],
                "legendary_pass_count": row[4],
                "max_pokemon_slots": row[5],
                "is_banned": row[6],
                "is_battle_banned": row[7]
            }
        return None

    def update_user_admin(self, user_id: int, updates: Dict[str, Any]):
        """Applies admin updates to a user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Use COALESCE to keep the existing value if a new one isn't provided
            cursor.execute(
                """
                UPDATE users SET
                    is_banned = COALESCE(%(is_banned)s, is_banned),
                    is_battle_banned = COALESCE(%(is_battle_banned)s, is_battle_banned),
                    clash_coins = GREATEST(0, clash_coins + %(add_coins)s),
                    shiny_pass_count = GREATEST(0, shiny_pass_count + %(add_passes)s),
                    legendary_pass_count = GREATEST(0, legendary_pass_count + %(add_legendary_passes)s),
                    max_pokemon_slots = COALESCE(%(set_slots)s, max_pokemon_slots)
                WHERE user_id = %(user_id)s
                """,
                {
                    "user_id": user_id,
                    "is_banned": updates.get("is_banned"),
                    "is_battle_banned": updates.get("is_battle_banned"),
                    "add_coins": updates.get("add_coins", 0),
                    "add_passes": updates.get("add_passes", 0),
                    "add_legendary_passes": updates.get("add_legendary_passes", 0),
                    "set_slots": updates.get("set_slots")
                }
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def get_all_user_ids(self) -> List[int]:
        """Fetches all user IDs for broadcast."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE is_banned = FALSE")
        user_ids = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return user_ids

    def admin_reset_user(self, user_id: int):
        """Wipes progress for a single user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # 1. Delete from collections
            cursor.execute("DELETE FROM collections WHERE user_id = %s", (user_id,))
            # 2. Delete from teams
            cursor.execute("DELETE FROM teams WHERE user_id = %s", (user_id,))
            # 3. Reset user table stats
            cursor.execute(
                """
                UPDATE users SET
                    active_team_id = NULL,
                    elo_score = 1000,
                    wins = 0,
                    losses = 0,
                    draws = 0,
                    shiny_pass_count = 1,
                    legendary_pass_count = 0,
                    clash_coins = 1000,
                    favorite_pokemon_uuid = NULL,
                    max_pokemon_slots = 12
                WHERE user_id = %s
                """,
                (user_id,)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
            
    def get_user_ban_status(self, user_id: int) -> dict:
        """Fetches a user's ban status."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_banned, is_battle_banned FROM users WHERE user_id = %s", (user_id,))
        status = cursor.fetchone()
        cursor.close()
        conn.close()
        if status:
            return {"is_banned": status[0], "is_battle_banned": status[1]}
        return {"is_banned": False, "is_battle_banned": False} # Default for non-existent user

    def create_redeem_code(
        self,
        *,
        reward_clash_coins: int = 0,
        reward_shiny_passes: int = 0,
        reward_legendary_passes: int = 0,
        max_uses: int = 1,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates a redeem code with the specified rewards and use limit."""
        if max_uses < 1:
            raise ValueError("max_uses must be at least 1")
        if reward_clash_coins < 0 or reward_shiny_passes < 0 or reward_legendary_passes < 0:
            raise ValueError("redeem rewards cannot be negative")
        if reward_clash_coins == 0 and reward_shiny_passes == 0 and reward_legendary_passes == 0:
            raise ValueError("redeem code must include at least one reward")

        alphabet = string.ascii_uppercase + string.digits

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            code = None
            for _ in range(10):
                candidate = f"PC-{''.join(secrets.choice(alphabet) for _ in range(8))}"
                cursor.execute("SELECT 1 FROM redeem_codes WHERE code = %s", (candidate,))
                if not cursor.fetchone():
                    code = candidate
                    break

            if code is None:
                raise RuntimeError("failed to generate a unique redeem code")

            cursor.execute(
                """
                INSERT INTO redeem_codes (
                    code, reward_clash_coins, reward_shiny_passes, reward_legendary_passes,
                    max_uses, remaining_uses, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    code,
                    reward_clash_coins,
                    reward_shiny_passes,
                    reward_legendary_passes,
                    max_uses,
                    max_uses,
                    created_by,
                )
            )
            conn.commit()
            return {
                "code": code,
                "reward_clash_coins": reward_clash_coins,
                "reward_shiny_passes": reward_shiny_passes,
                "reward_legendary_passes": reward_legendary_passes,
                "max_uses": max_uses,
                "remaining_uses": max_uses,
                "created_by": created_by,
            }
        finally:
            cursor.close()
            conn.close()

    def claim_redeem_code(self, user_id: int, code: str) -> Dict[str, Any]:
        """Claims a redeem code for a user exactly once."""
        normalized_code = code.strip().upper()
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT code, reward_clash_coins, reward_shiny_passes, reward_legendary_passes,
                       max_uses, remaining_uses
                FROM redeem_codes
                WHERE code = %s
                FOR UPDATE
                """,
                (normalized_code,)
            )
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return {"ok": False, "error": "invalid_code"}

            if row[5] <= 0:
                conn.rollback()
                return {"ok": False, "error": "no_uses_left"}

            cursor.execute(
                "SELECT 1 FROM redeem_code_claims WHERE code = %s AND user_id = %s",
                (normalized_code, user_id)
            )
            if cursor.fetchone():
                conn.rollback()
                return {"ok": False, "error": "already_claimed"}

            cursor.execute(
                "INSERT INTO redeem_code_claims (code, user_id) VALUES (%s, %s)",
                (normalized_code, user_id)
            )
            cursor.execute(
                "UPDATE redeem_codes SET remaining_uses = remaining_uses - 1 WHERE code = %s",
                (normalized_code,)
            )
            cursor.execute(
                """
                UPDATE users
                SET clash_coins = GREATEST(0, clash_coins + %s),
                    shiny_pass_count = GREATEST(0, shiny_pass_count + %s),
                    legendary_pass_count = GREATEST(0, legendary_pass_count + %s)
                WHERE user_id = %s
                """,
                (row[1], row[2], row[3], user_id)
            )
            conn.commit()
            return {
                "ok": True,
                "code": row[0],
                "reward_clash_coins": row[1],
                "reward_shiny_passes": row[2],
                "reward_legendary_passes": row[3],
                "max_uses": row[4],
                "remaining_uses": row[5] - 1,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()
    
    # --- END ADMIN FUNCTIONS ---

db = PokemonDatabase()
