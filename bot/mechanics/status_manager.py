import os
import json
from bot.mechanics.moves_loader import MOVE_BY_ID, ABILITIES_BY_ID
from bot.mechanics.item_data import ITEM_ID_BY_NAME
from bot.mechanics.db import db

# --- THIS IS THE FIX ---
# Build an absolute path to the status file relative to your project's root directory.
# This makes sure the bot always knows where to find and save the file.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
STATUS_FILE = os.path.join(PROJECT_ROOT, 'implementation_status.json')
# --- END OF FIX ---

class StatusManager:
    def __init__(self):
        self.data = self._load_statuses()

    def _load_statuses(self):
        """Load statuses from DB, create if non-existent, and sync to JSON."""
        statuses = db.get_all_statuses()
        
        if not statuses:
            print("Implementation status table is empty. Populating from source...")
            initial_data = {
                "moves": {move_id: False for move_id in MOVE_BY_ID},
                "abilities": {ability_id: False for ability_id in ABILITIES_BY_ID},
                "items": {item_id: False for item_id in ITEM_ID_BY_NAME.values()}
            }
            for category, items in initial_data.items():
                for item_id, status in items.items():
                    db.set_status(category, item_id, status)
            statuses = initial_data

        self._save_to_json(statuses)
        return statuses

    def _save_to_json(self, data):
        """Saves the current state to the JSON file."""
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"!!! CRITICAL ERROR: Could not write to {STATUS_FILE}. Reason: {e}")

    def get_status(self, category: str, item_id: str) -> bool:
        return self.data.get(category, {}).get(item_id, False)

    def set_status(self, category: str, item_id: str, status: bool):
        # 1. Update the DB (primary source)
        db.set_status(category, item_id, status)
        
        # 2. Update in-memory data
        if category in self.data and item_id in self.data[category]:
            self.data[category][item_id] = status
            
        # 3. Update the JSON backup file
        self._save_to_json(self.data)

# Create a single instance
status_manager = StatusManager()