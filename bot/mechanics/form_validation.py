from __future__ import annotations

from typing import Any


ALLOWED_BATTLE_ONLY_COLLECTION_FORMS = {"miniormeteor"}
EXPLICITLY_BLOCKED_COLLECTION_FORMS = {
    "greninjabond",
    "greninjaash",
    "eternatuseternamax",
}


def get_collection_form_block_reason(species_data: dict[str, Any] | None) -> str | None:
    if not species_data:
        return None

    species_id = str(species_data.get("id") or "").strip().lower()
    species_name = str(species_data.get("name") or "").strip().lower()
    forme = str(species_data.get("forme") or "").strip().lower()
    is_nonstandard = species_data.get("isNonstandard")
    battle_only = species_data.get("battleOnly")

    if (
        "gmax" in species_id
        or "gmax" in species_name
        or forme == "gmax"
        or is_nonstandard == "Gigantamax"
    ):
        return "Gigantamax form"

    if "totem" in species_id or "totem" in forme:
        return "Totem form"

    if "mega" in species_id or "mega" in forme or "primal" in species_id or "primal" in forme:
        return "temporary battle form"

    if species_data.get("requiredItem") or species_data.get("requiredItems"):
        return "item-dependent form"

    if species_id in EXPLICITLY_BLOCKED_COLLECTION_FORMS or forme in {"bond", "ash", "eternamax"}:
        return "battle-only form"

    if species_id in ALLOWED_BATTLE_ONLY_COLLECTION_FORMS:
        return None

    if battle_only and species_id not in ALLOWED_BATTLE_ONLY_COLLECTION_FORMS:
        return "battle-only form"

    if species_data.get("requiredAbility"):
        return "ability-dependent form"

    if is_nonstandard and is_nonstandard not in {"Past", None}:
        return "special form"

    return None


def is_collection_form_allowed(species_data: dict[str, Any] | None) -> bool:
    return get_collection_form_block_reason(species_data) is None
