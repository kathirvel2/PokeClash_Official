from __future__ import annotations

from pathlib import Path
from typing import Any
import re


ITEMS_TS_PATH = (
    Path(__file__).resolve().parents[2]
    / "server"
    / "pokemon-showdown"
    / "data"
    / "items.ts"
)
ITEM_TEXT_TS_PATH = (
    Path(__file__).resolve().parents[2]
    / "server"
    / "pokemon-showdown"
    / "data"
    / "text"
    / "items.ts"
)


def _to_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _top_level_item_blocks(content: str) -> list[str]:
    blocks: list[str] = []
    start_pattern = re.compile(r"^\t[a-z0-9]+:\s*\{$", re.MULTILINE)
    for match in start_pattern.finditer(content):
        brace_start = content.find("{", match.start())
        if brace_start < 0:
            continue
        depth = 0
        end = None
        for index in range(brace_start, len(content)):
            char = content[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is not None:
            blocks.append(content[match.start(): end + 1])
    return blocks


def _extract_string(block: str, field: str) -> str:
    match = re.search(rf'\b{re.escape(field)}:\s*"([^"]*)"', block)
    if not match:
        match = re.search(rf"\b{re.escape(field)}:\s*'([^']*)'", block)
    return match.group(1).strip() if match else ""


def _extract_number(block: str, field: str) -> int | None:
    match = re.search(rf"\b{re.escape(field)}:\s*(-?\d+)", block)
    return int(match.group(1)) if match else None


def _extract_string_list(block: str, field: str) -> list[str]:
    match = re.search(rf"\b{re.escape(field)}:\s*\[([^\]]*)\]", block, re.DOTALL)
    if not match:
        return []
    return [
        item.strip()
        for item in re.findall(r'"([^"]+)"|\'([^\']+)\'', match.group(1))
        for item in item
        if item.strip()
    ]


def _extract_object_strings(block: str, field: str) -> dict[str, str]:
    match = re.search(rf"\b{re.escape(field)}:\s*\{{([^}}]*)\}}", block, re.DOTALL)
    if not match:
        return {}
    return {
        first_key or second_key: first_value or second_value
        for first_key, first_value, second_key, second_value in re.findall(
            r'"([^"]+)"\s*:\s*"([^"]+)"|(\w+)\s*:\s*"([^"]+)"',
            match.group(1),
        )
    }


def _extract_nested_object(block: str, field: str) -> dict[str, Any]:
    field_match = re.search(rf"\b{re.escape(field)}:\s*\{{", block)
    if not field_match:
        return {}
    brace_start = block.find("{", field_match.start())
    depth = 0
    end = None
    for index in range(brace_start, len(block)):
        char = block[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return {}
    nested = block[brace_start + 1:end]
    data: dict[str, Any] = {}
    for key in ("basePower", "type", "status", "volatileStatus"):
        string_value = _extract_string(nested, key)
        if string_value:
            data[key] = string_value
            continue
        number_value = _extract_number(nested, key)
        if number_value is not None:
            data[key] = number_value
    return data


def _categorize_item(name: str, block: str) -> str:
    lowered = name.lower()
    if "isBerry: true" in block:
        return "Berries"
    if "megaStone:" in block:
        return "Mega Stones"
    if "onPlate:" in block or lowered.endswith(" memory"):
        return "Plates & Memories"
    if re.search(r"\bzMove\s*:", block):
        return "Z-Crystals"
    if lowered.endswith(" gem"):
        return "Gems"
    if lowered.startswith("choice "):
        return "Choice Items"
    if lowered.endswith(" drive"):
        return "Drives"
    if lowered.endswith(" mask"):
        return "Masks"
    if lowered.endswith(" seed") or lowered == "terrain extender":
        return "Terrain & Seeds"
    if lowered.endswith(" orb"):
        return "Orbs"
    if "forcedForme:" in block or "itemUser:" in block:
        return "Form & Signature Items"
    if any(token in lowered for token in ("leftovers", "boots", "helmet", "vest", "sash", "band", "cloak", "policy", "claw", "lens", "amulet", "berry juice", "light clay", "life orb", "eviolite", "rocky helmet", "assault vest")):
        return "Competitive Items"
    return "Other Items"


def _load_item_categories() -> dict[str, list[str]]:
    if not ITEMS_TS_PATH.exists():
        return {"Other Items": []}

    content = ITEMS_TS_PATH.read_text(encoding="utf-8")
    category_map: dict[str, list[str]] = {}
    seen_names: set[str] = set()

    for block in _top_level_item_blocks(content):
        name_match = re.search(r'\bname:\s*"([^"]+)"', block)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        category = _categorize_item(name, block)
        category_map.setdefault(category, []).append(name)

    preferred_order = [
        "Competitive Items",
        "Choice Items",
        "Berries",
        "Mega Stones",
        "Z-Crystals",
        "Plates & Memories",
        "Gems",
        "Terrain & Seeds",
        "Drives",
        "Masks",
        "Orbs",
        "Form & Signature Items",
        "Other Items",
    ]

    ordered_categories: dict[str, list[str]] = {}
    for category in preferred_order:
        if category in category_map:
            ordered_categories[category] = sorted(category_map.pop(category))
    for category in sorted(category_map):
        ordered_categories[category] = sorted(category_map[category])
    return ordered_categories


def _load_item_text() -> dict[str, dict[str, str]]:
    if not ITEM_TEXT_TS_PATH.exists():
        return {}
    content = ITEM_TEXT_TS_PATH.read_text(encoding="utf-8")
    text_by_id: dict[str, dict[str, str]] = {}
    for block in _top_level_item_blocks(content):
        key_match = re.match(r"\t([a-z0-9]+):\s*\{", block)
        if not key_match:
            continue
        item_id = key_match.group(1)
        text_by_id[item_id] = {
            "name": _extract_string(block, "name"),
            "desc": _extract_string(block, "desc"),
            "shortDesc": _extract_string(block, "shortDesc"),
        }
    return text_by_id


def _load_item_details() -> dict[str, dict[str, Any]]:
    if not ITEMS_TS_PATH.exists():
        return {}
    content = ITEMS_TS_PATH.read_text(encoding="utf-8")
    text_by_id = _load_item_text()
    item_by_id: dict[str, dict[str, Any]] = {}

    for block in _top_level_item_blocks(content):
        key_match = re.match(r"\t([a-z0-9]+):\s*\{", block)
        name = _extract_string(block, "name")
        if not key_match or not name:
            continue
        item_id = key_match.group(1)
        text_data = text_by_id.get(item_id, {})
        data: dict[str, Any] = {
            "id": item_id,
            "name": text_data.get("name") or name,
            "category": _categorize_item(name, block),
            "desc": text_data.get("desc") or _extract_string(block, "desc"),
            "shortDesc": text_data.get("shortDesc") or _extract_string(block, "shortDesc"),
            "gen": _extract_number(block, "gen"),
            "num": _extract_number(block, "num"),
            "spritenum": _extract_number(block, "spritenum"),
            "isBerry": "isBerry: true" in block,
            "isNonstandard": _extract_string(block, "isNonstandard"),
            "megaStone": _extract_object_strings(block, "megaStone"),
            "itemUser": _extract_string_list(block, "itemUser"),
            "zMove": _extract_string(block, "zMove"),
            "zMoveType": _extract_string(block, "zMoveType"),
            "onPlate": _extract_string(block, "onPlate"),
            "forcedForme": _extract_string(block, "forcedForme"),
            "naturalGift": _extract_nested_object(block, "naturalGift"),
            "fling": _extract_nested_object(block, "fling"),
        }
        item_by_id[item_id] = {key: value for key, value in data.items() if value not in (None, "", [], {})}
    return item_by_id


ITEM_CATEGORIES = _load_item_categories()
CATEGORY_NAMES = list(ITEM_CATEGORIES.keys())
ALL_ITEMS = [item for category_items in ITEM_CATEGORIES.values() for item in category_items]
ITEM_ID_BY_NAME = {item: _to_id(item) for item in ALL_ITEMS}
ITEM_NAME_BY_ID = {item_id: item_name for item_name, item_id in ITEM_ID_BY_NAME.items()}
ITEM_BY_ID = _load_item_details()
ITEMS_BY_NORMALIZED_NAME = {_to_id(item.get("name", item_id)): item for item_id, item in ITEM_BY_ID.items()}
