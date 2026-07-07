from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOUBLES_BATTLE_KIND = "doubles"
DOUBLES_RANDOM_BATTLE_FORMAT_ID = "gen9randomdoublesbattle"
DOUBLES_RANDOM_BATTLE_FORMAT_LABEL = "Gen 9 Random Doubles Battle"


def is_doubles_battle_kind(value: str | None) -> bool:
    return str(value or "").strip().lower() == DOUBLES_BATTLE_KIND


def doubles_slot_label(index: int) -> str:
    return chr(ord("A") + max(0, int(index)))


def encode_target_location(target_loc: int) -> str:
    return f"n{abs(int(target_loc))}" if int(target_loc) < 0 else str(int(target_loc))


def decode_target_location(code: str) -> int:
    text = str(code or "").strip().lower()
    if not text:
        return 0
    if text.startswith("n"):
        return -int(text[1:] or 0)
    return int(text)


@dataclass
class DoublesDraft:
    token: int = 0
    phase: str = ""
    focus: int = 0
    choices: list[str | None] = field(default_factory=list)
    descriptions: list[str | None] = field(default_factory=list)
    primed_actions: list[str | None] = field(default_factory=list)
    pending_target: dict[str, Any] | None = None

    def clear(self) -> None:
        self.token = 0
        self.phase = ""
        self.focus = 0
        self.choices.clear()
        self.descriptions.clear()
        self.primed_actions.clear()
        self.pending_target = None

    def ensure_size(self, size: int) -> None:
        while len(self.choices) < size:
            self.choices.append(None)
        while len(self.descriptions) < size:
            self.descriptions.append(None)
        while len(self.primed_actions) < size:
            self.primed_actions.append(None)
        if len(self.choices) > size:
            del self.choices[size:]
        if len(self.descriptions) > size:
            del self.descriptions[size:]
        if len(self.primed_actions) > size:
            del self.primed_actions[size:]
