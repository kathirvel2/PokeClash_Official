# ./bot/battle/item_effects/item_data.py

# This dictionary maps an item's ID (from item_data.py) to its battle effect data.
# Each key represents a "hook" in the battle logic where the item's effect can trigger.

ITEM_EFFECTS = {
    # === Choice Items ===
    "choiceband": {
        "on_stat_calculation": {"stat": "atk", "multiplier": 1.5},
        "on_move_choice": {"type": "lock"}
    },
    "choicescarf": {
        "on_stat_calculation": {"stat": "spe", "multiplier": 1.5},
        "on_move_choice": {"type": "lock"}
    },
    "choicespecs": {
        "on_stat_calculation": {"stat": "spa", "multiplier": 1.5},
        "on_move_choice": {"type": "lock"}
    },

    # === Battle Effect Items ===
    "lifeorb": {
        "on_damage_dealt": {"type": "multiplier", "value": 1.3},
        "on_after_attack": {"type": "recoil_hp_fraction", "value": 0.1, "target": "self"}
    },
    "focussash": {
        "on_before_damage": {"type": "survive_ohko"}
    },
    "assaultvest": {
        "on_stat_calculation": {"stat": "spd", "multiplier": 1.5},
        "on_move_choice": {"type": "block_status_moves"}
    },
    "eviolite": {
        "on_stat_calculation": {"stat": ["def", "spd"], "multiplier": 1.5, "condition": "not_fully_evolved"}
    },
    "rockyhelmet": {
        "on_taking_contact_damage": {"type": "recoil_hp_fraction", "value": 1/6, "target": "opponent"}
    },
    "expertbelt": {
        "on_damage_dealt": {"type": "super_effective_multiplier", "value": 1.2}
    },
    "leftovers": {
        "on_end_of_turn": {"type": "heal_hp_fraction", "value": 1/16}
    },
    "blacksludge": {
        "on_end_of_turn": {"type": "heal_or_damage_hp_fraction", "value": 1/16}
    },
    "airballoon": {
        "on_switch_in": {"type": "add_volatile", "volatile": "airballoon"},
        "on_taking_damage": {"type": "remove_volatile", "volatile": "airballoon"}
    },
    "heavydutyboots": {
        "on_switch_in": {"type": "block_hazards"}
    },
    "ejecttool": {
        "on_taking_damage": {"type": "force_switch_on_damage"}
    },
    "protectivepads": {
        "on_contact": {"type": "block_contact_effects"}
    },

    # === Status Orbs ===
    "toxicorb": {
        "on_end_of_turn": {"type": "apply_status", "status": "tox", "condition": "no_status"}
    },
    "flameorb": {
        "on_end_of_turn": {"type": "apply_status", "status": "brn", "condition": "no_status"}
    },

    # === Stat Boosters ===
    "muscleband": {
        "on_damage_dealt": {"type": "category_multiplier", "category": "Physical", "value": 1.1}
    },
    "wiseclasses": {
        "on_damage_dealt": {"type": "category_multiplier", "category": "Special", "value": 1.1}
    },
    "adamantorb": {"on_damage_dealt": {"type": "specific_pokemon_boost", "pokemon": "dialga", "value": 1.2}},
    "lustrousorb": {"on_damage_dealt": {"type": "specific_pokemon_boost", "pokemon": "palkia", "value": 1.2}},
    "griseousorb": {"on_damage_dealt": {"type": "specific_pokemon_boost", "pokemon": "giratina", "value": 1.2}},
    "redorb": {"on_switch_in": {"type": "primal_reversion", "pokemon": "groudon"}},
    "blueorb": {"on_switch_in": {"type": "primal_reversion", "pokemon": "kyogre"}},

    # === Type Enhancing Items ===
    "silkscarf": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Normal", "value": 1.2}},
    "charcoal": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Fire", "value": 1.2}},
    "mysticwater": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Water", "value": 1.2}},
    "miracleseed": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Grass", "value": 1.2}},
    "magnet": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Electric", "value": 1.2}},
    "nevermeltice": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Ice", "value": 1.2}},
    "blackbelt": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Fighting", "value": 1.2}},
    "poisonbarb": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Poison", "value": 1.2}},
    "softsand": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Ground", "value": 1.2}},
    "sharpbeak": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Flying", "value": 1.2}},
    "twistedspoon": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Psychic", "value": 1.2}},
    "silverpowder": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Bug", "value": 1.2}},
    "hardstone": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Rock", "value": 1.2}},
    "spelltag": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Ghost", "value": 1.2}},
    "dragonfang": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Dragon", "value": 1.2}},
    "blackglasses": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Dark", "value": 1.2}},
    "metalcoat": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Steel", "value": 1.2}},
    "fairyfeather": {"on_damage_dealt": {"type": "type_multiplier", "move_type": "Fairy", "value": 1.2}},

    # === Berries ===
    "sitrusberry": {"on_below_hp_threshold": {"type": "heal_hp_fraction", "threshold": 0.5, "value": 0.25}},
    "lumberry": {"on_status_inflicted": {"type": "cure_status"}},
    "aguavberry": {"on_below_hp_threshold": {"type": "heal_hp_fraction", "threshold": 0.25, "value": 1/3, "confuse_nature": ["Modest", "Timid", "Jolly", "Adamant"]}},
    "figyberry": {"on_below_hp_threshold": {"type": "heal_hp_fraction", "threshold": 0.25, "value": 1/3, "confuse_nature": ["Bold", "Timid", "Modest", "Calm"]}},
    "iapapaberry": {"on_below_hp_threshold": {"type": "heal_hp_fraction", "threshold": 0.25, "value": 1/3, "confuse_nature": ["Lonely", "Hasty", "Mild", "Gentle"]}},
    "magoberry": {"on_below_hp_threshold": {"type": "heal_hp_fraction", "threshold": 0.25, "value": 1/3, "confuse_nature": ["Brave", "Quiet", "Relaxed", "Sassy"]}},
    "wikiberry": {"on_below_hp_threshold": {"type": "heal_hp_fraction", "threshold": 0.25, "value": 1/3, "confuse_nature": ["Adamant", "Impish", "Jolly", "Careful"]}},
    "liechiberry": {"on_below_hp_threshold": {"type": "consume_and_boost", "threshold": 0.25, "boosts": {"atk": 1}}},
    "salacberry": {"on_below_hp_threshold": {"type": "consume_and_boost", "threshold": 0.25, "boosts": {"spe": 1}}},
    "petayaberry": {"on_below_hp_threshold": {"type": "consume_and_boost", "threshold": 0.25, "boosts": {"spa": 1}}},
    "apicotberry": {"on_below_hp_threshold": {"type": "consume_and_boost", "threshold": 0.25, "boosts": {"spd": 1}}},


    # === Weather & Terrain Items ===
    "damprock": {"on_weather_creation": {"type": "extend_duration", "weather": "raindance", "turns": 8}},
    "heatrock": {"on_weather_creation": {"type": "extend_duration", "weather": "sunnyday", "turns": 8}},
    "icyrock": {"on_weather_creation": {"type": "extend_duration", "weather": "hail", "turns": 8}},
    "smoothrock": {"on_weather_creation": {"type": "extend_duration", "weather": "sandstorm", "turns": 8}},
    "electricseed": {"on_terrain_contact": {"type": "consume_and_boost", "terrain": "electricterrain", "boosts": {"def": 1}}},
    "grassyseed": {"on_terrain_contact": {"type": "consume_and_boost", "terrain": "grassyterrain", "boosts": {"def": 1}}},
    "mistyseed": {"on_terrain_contact": {"type": "consume_and_boost", "terrain": "mistyterrain", "boosts": {"spd": 1}}},
    "psychicseed": {"on_terrain_contact": {"type": "consume_and_boost", "terrain": "psychicterrain", "boosts": {"spd": 1}}},
}