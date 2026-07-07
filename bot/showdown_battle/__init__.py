from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from telebot.async_telebot import AsyncTeleBot


def register_showdown_challenge_handlers(bot: "AsyncTeleBot"):
    from bot.showdown_battle.service import register_showdown_challenge_handlers as _register

    return _register(bot)


__all__ = ["register_showdown_challenge_handlers"]
