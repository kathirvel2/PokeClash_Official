# In ./bot/battle/z_move_data.py

from bot.mechanics.moves_loader import MOVE_BY_ID

# Maps a base move's power to the corresponding Z-Move power
Z_MOVE_POWER = {
    (1, 55): 100,
    (60, 65): 120,
    (70, 75): 140,
    (80, 85): 160,
    (90, 95): 175,
    (100, 100): 180,
    (110, 110): 185,
    (120, 120): 190,
    (130, 130): 195,
    (140, 250): 200,
}

Z_CRYSTAL_TYPE_MAP = {
    'normaliumz': 'Normal', 'firiumz': 'Fire', 'wateriumz': 'Water',
    'electriumz': 'Electric', 'grassiumz': 'Grass', 'iciumz': 'Ice',
    'fightiniumz': 'Fighting', 'poisoniumz': 'Poison', 'groundiumz': 'Ground',
    'flyiniumz': 'Flying', 'psychiumz': 'Psychic', 'buginiumz': 'Bug',
    'rockiumz': 'Rock', 'ghostiumz': 'Ghost', 'dragoniumz': 'Dragon',
    'darkiniumz': 'Dark', 'steeliumz': 'Steel', 'fairiumz': 'Fairy'
}

# Maps a move type to its generic Z-Move
TYPE_TO_Z_MOVE = {
    "Normal": {"id": "breakneckblitz", "name": "Breakneck Blitz"},
    "Fire": {"id": "infernooverdrive", "name": "Inferno Overdrive"},
    "Water": {"id": "hydrovortex", "name": "Hydro Vortex"},
    "Grass": {"id": "bloomdoom", "name": "Bloom Doom"},
    "Electric": {"id": "gigavolthavoc", "name": "Gigavolt Havoc"},
    "Ice": {"id": "subzeroslash", "name": "Subzero Slammer"},
    "Fighting": {"id": "alloutpummeling", "name": "All-Out Pummeling"},
    "Poison": {"id": "aciddownpour", "name": "Acid Downpour"},
    "Ground": {"id": "tectonicrage", "name": "Tectonic Rage"},
    "Flying": {"id": "supersonicskystrike", "name": "Supersonic Skystrike"},
    "Psychic": {"id": "shatteredpsyche", "name": "Shattered Psyche"},
    "Bug": {"id": "savagespinout", "name": "Savage Spin-Out"},
    "Rock": {"id": "continentalcrush", "name": "Continental Crush"},
    "Ghost": {"id": "neverendingnightmare", "name": "Never-Ending Nightmare"},
    "Dragon": {"id": "devastatingdrake", "name": "Devastating Drake"},
    "Dark": {"id": "blackholeeclipse", "name": "Black Hole Eclipse"},
    "Steel": {"id": "corkscrewcrash", "name": "Corkscrew Crash"},
    "Fairy": {"id": "twinkletackle", "name": "Twinkle Tackle"}
}

SIGNATURE_Z_MOVES = {
    # Base Move ID: { Z-Move details }
    "volttackle": {
        "item_id": "pikaniumz", "pokemon_id": "pikachu",
        "z_move_id": "catastropika", "z_move_name": "Catastropika", "power": 210
    },
    "thunderbolt": { # For Pikachu with Pikashunium Z
        "item_id": "pikashuniumz", "pokemon_id": "pikachu",
        "z_move_id": "10000000voltthunderbolt", "z_move_name": "10,000,000 Volt Thunderbolt", "power": 195
    },
    "thunderbolt": { # This needs to come AFTER the Pikashunium Z entry for Thunderbolt
        "item_id": "aloraichiumz", "pokemon_id": "raichualola",
        "z_move_id": "stokedsparksurfer", "z_move_name": "Stoked Sparksurfer", "power": 175,
        "secondary": { "status": "par", "chance": 100 }
    },
    "spiritshackle": {
        "item_id": "decidiumz", "pokemon_id": "decidueye",
        "z_move_id": "sinisterarrowraid", "z_move_name": "Sinister Arrow Raid", "power": 180
    },
    "darkestlariat": {
        "item_id": "inciniumz", "pokemon_id": "incineroar",
        "z_move_id": "maliciousmoonsault", "z_move_name": "Malicious Moonsault", "power": 180
    },
    "sparklingaria": {
        "item_id": "primariumz", "pokemon_id": "primarina",
        "z_move_id": "oceanicoperetta", "z_move_name": "Oceanic Operetta", "power": 195
    },
    "psychic": { # For Mew with Mewnium Z
        "item_id": "mewniumz", "pokemon_id": "mew",
        "z_move_id": "genesissupernova", "z_move_name": "Genesis Supernova", "power": 185,
        "secondary": { "terrain": "psychicterrain" }
    },
    "phantomforce": { # For Marshadow with Marshadium Z
        "item_id": "marshadiumz", "pokemon_id": "marshadow",
        "z_move_id": "soulstealing7starstrike", "z_move_name": "Soul-Stealing 7-Star Strike", "power": 195
    },
    "sunsteelstrike": {
        "item_id": "solganiumz", "pokemon_id": "solgaleo",
        "z_move_id": "searingsunrazesmash", "z_move_name": "Searing Sunraze Smash", "power": 200
    },
    "moongeistbeam": {
        "item_id": "lunaliumz", "pokemon_id": "lunala",
        "z_move_id": "menacingmoonrazemaelstrom", "z_move_name": "Menacing Moonraze Maelstrom", "power": 200
    },
    "playrough": {
        "item_id": "mimikiumz", "pokemon_id": "mimikyu",
        "z_move_id": "letssnuggleforever", "z_move_name": "Let's Snuggle Forever", "power": 190
    },
    "stoneedge": {
        "item_id": "lycaniumz", "pokemon_id": "lycanroc", # Also works for dusk/midnight forms
        "z_move_id": "splinteredstormshards", "z_move_name": "Splintered Stormshards", "power": 190
    },
    "clangingscales": {
        "item_id": "kommoniumz", "pokemon_id": "kommoo",
        "z_move_id": "clangoroussoulblaze", "z_move_name": "Clangorous Soulblaze", "power": 185,
        "self": {"boosts": {"atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1}}
    },
    "photongeyser": {
        "item_id": "ultranecroziumz", "pokemon_id": "necrozmaultra",
        "z_move_id": "lightthatburnsthesky", "z_move_name": "Light That Burns the Sky", "power": 200
    },
    "gigaimpact": { # For Snorlax with Snorlium Z
        "item_id": "snorliumz", "pokemon_id": "snorlax",
        "z_move_id": "pulverizingpancake", "z_move_name": "Pulverizing Pancake", "power": 210
    },
    "lastresort": { # For Eevee with Eevium Z
        "item_id": "eeviumz", "pokemon_id": "eevee",
        "z_move_id": "extremeevoboost", "z_move_name": "Extreme Evoboost", "power": 0 # This one is a status move
    },
    "naturesmadness": {
        "item_id": "tapuniumz", "pokemon_id": "tapukoko",
        "z_move_id": "guardianofalola", "z_move_name": "Guardian of Alola", "power": 0 # Power is calculated specially
    }
}

def get_z_move_details(base_move_id: str) -> dict | None:
    """
    Calculates the power and gets the name of a damaging Z-Move.
    """
    base_move_data = MOVE_BY_ID.get(base_move_id)
    if not base_move_data or base_move_data['category'] == 'Status':
        return None

    power = base_move_data.get('basePower', 0)
    z_power = 100 # Default for moves with no power

    if power > 0:
        for (min_p, max_p), z_p in Z_MOVE_POWER.items():
            if min_p <= power <= max_p:
                z_power = z_p
                break
    
    move_type = base_move_data['type']
    z_move_info = TYPE_TO_Z_MOVE.get(move_type, {"name": "Z-Move", "id": "zmove"})
    
    return {"name": z_move_info['name'], "power": z_power}