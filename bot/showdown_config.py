from __future__ import annotations

import os
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BOT_DIR.parent
SHOWDOWN_DIR = Path(
    os.getenv("SHOWDOWN_DIR")
    or (PROJECT_DIR / "server" / "pokemon-showdown")
).resolve()

OWNED_BATTLE_FORMAT = os.getenv("SHOWDOWN_OWNED_FORMAT", "gen9pokeclashcompetitive")
RANDOM_BATTLE_FORMATS: dict[int, tuple[str, str]] = {
    9: ("gen9randombattle", "Gen 9 Random Battle"),
    8: ("gen8randombattle", "Gen 8 Random Battle"),
    7: ("gen7randombattle", "Gen 7 Random Battle"),
    6: ("gen6randombattle", "Gen 6 Random Battle"),
    5: ("gen5randombattle", "Gen 5 Random Battle"),
    4: ("gen4randombattle", "Gen 4 Random Battle"),
    3: ("gen3randombattle", "Gen 3 Random Battle"),
    2: ("gen2randombattle", "Gen 2 Random Battle"),
    1: ("gen1randombattle", "Gen 1 Random Battle"),
}
