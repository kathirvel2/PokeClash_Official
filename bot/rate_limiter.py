import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from aiolimiter import AsyncLimiter
from telebot import asyncio_helper
from telebot.async_telebot import AsyncTeleBot

logger = logging.getLogger(__name__)

# Global Telegram Bot API traffic cap.
GLOBAL_RATE_LIMIT = 25
GLOBAL_TIME_PERIOD = 1

# Conservative per-chat throttle for non-DM chats.
PER_CHAT_RATE_LIMIT = 18
PER_CHAT_TIME_PERIOD = 60


class RateLimitedAsyncTeleBot(AsyncTeleBot):
    """
    AsyncTeleBot with adaptive Telegram API flood handling.

    Group chats keep the conservative per-chat limiter. Private chats skip that
    proactive limit and only enter flood-control mode after Telegram returns a
    real 429/retry_after for that DM.
    """

    _patch_installed = False
    _original_process_request = None
    _active_instance: "RateLimitedAsyncTeleBot | None" = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.global_limiter = AsyncLimiter(GLOBAL_RATE_LIMIT, GLOBAL_TIME_PERIOD)
        self.per_chat_limiters = defaultdict(
            lambda: AsyncLimiter(PER_CHAT_RATE_LIMIT, PER_CHAT_TIME_PERIOD)
        )
        self.chat_limiter_lock = asyncio.Lock()
        self.dm_flood_until: dict[int, float] = {}
        self.dm_flood_lock = asyncio.Lock()
        self._install_request_patch()

    @classmethod
    def _install_request_patch(cls) -> None:
        if cls._patch_installed:
            return

        cls._original_process_request = asyncio_helper._process_request

        async def patched_process_request(token, url, method="get", params=None, files=None, **kwargs):
            bot = cls._active_instance
            if not bot:
                return await cls._original_process_request(
                    token, url, method=method, params=params, files=files, **kwargs
                )
            return await bot._process_request_with_limits(
                token, url, method=method, params=params, files=files, **kwargs
            )

        asyncio_helper._process_request = patched_process_request
        cls._patch_installed = True

    async def _process_request_with_limits(
        self, token, url, method="get", params=None, files=None, **kwargs
    ):
        RateLimitedAsyncTeleBot._active_instance = self
        params_copy = dict(params) if params else None
        chat_id = self._extract_chat_id(params_copy)

        async with self.global_limiter:
            await self._wait_for_private_dm_cooldown(chat_id)

            if self._should_apply_proactive_chat_limit(chat_id):
                async with self.chat_limiter_lock:
                    chat_limiter = self.per_chat_limiters[chat_id]
                async with chat_limiter:
                    return await self._request_with_retry(
                        token, url, method=method, params=params_copy, files=files, chat_id=chat_id, **kwargs
                    )

            return await self._request_with_retry(
                token, url, method=method, params=params_copy, files=files, chat_id=chat_id, **kwargs
            )

    async def _request_with_retry(
        self, token, url, method="get", params=None, files=None, chat_id=None, **kwargs
    ):
        attempts = 0
        max_attempts = 2

        while True:
            try:
                attempt_params = dict(params) if params else None
                return await type(self)._original_process_request(
                    token, url, method=method, params=attempt_params, files=files, **kwargs
                )
            except asyncio_helper.ApiTelegramException as exc:
                retry_after = self._get_retry_after_seconds(exc)
                if not retry_after or not self._is_private_chat_id(chat_id) or attempts >= max_attempts - 1:
                    raise

                attempts += 1
                await self._activate_dm_flood_control(chat_id, retry_after, url)
                await asyncio.sleep(retry_after)

    def is_chat_flood_control_active(self, chat_id: int | None) -> bool:
        return self._is_private_chat_id(chat_id) and self.dm_flood_until.get(chat_id, 0.0) > time.monotonic()

    async def _wait_for_private_dm_cooldown(self, chat_id: int | None) -> None:
        if not self._is_private_chat_id(chat_id):
            return

        wait_for = self.dm_flood_until.get(chat_id, 0.0) - time.monotonic()
        if wait_for > 0:
            await asyncio.sleep(wait_for)

    async def _activate_dm_flood_control(self, chat_id: int, retry_after: int, url: str) -> None:
        buffer_seconds = 1
        flood_until = time.monotonic() + retry_after + buffer_seconds
        async with self.dm_flood_lock:
            self.dm_flood_until[chat_id] = max(self.dm_flood_until.get(chat_id, 0.0), flood_until)
        logger.warning(
            "Telegram flood control activated for DM chat %s after %s; retry_after=%ss",
            chat_id,
            url,
            retry_after,
        )

    @staticmethod
    def _extract_chat_id(params: dict[str, Any] | None) -> int | None:
        if not params:
            return None
        chat_id = params.get("chat_id")
        if chat_id is None:
            return None
        try:
            return int(chat_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_retry_after_seconds(exc: Exception) -> int | None:
        if not isinstance(exc, asyncio_helper.ApiTelegramException) or exc.error_code != 429:
            return None
        parameters = exc.result_json.get("parameters") or {}
        retry_after = parameters.get("retry_after")
        if retry_after is None:
            return None
        try:
            return max(1, int(retry_after))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_private_chat_id(chat_id: int | None) -> bool:
        return isinstance(chat_id, int) and chat_id > 0

    def _should_apply_proactive_chat_limit(self, chat_id: int | None) -> bool:
        if chat_id is None:
            return False
        if self._is_private_chat_id(chat_id):
            return self.is_chat_flood_control_active(chat_id)
        return True
