# ./bot/handlers/handler_utils.py
import time
import math
from typing import Dict
from telebot import types
from telebot.async_telebot import AsyncTeleBot

# We base this on the per-chat limit (20 messages/minute), which is 1 message every 3 seconds.
# We'll use a slightly shorter interval to be responsive.
MIN_INTERVAL_PER_USER = 2.0  # seconds

class CallbackRateLimiter:
    """
    Manages rate limits for individual users on callback queries to provide feedback.
    This is separate from the main API rate limiter and is purely for UX.
    """
    def __init__(self):
        self.user_timestamps: Dict[int, float] = {}

    async def is_limited(self, call: types.CallbackQuery, bot: AsyncTeleBot, *, bypass: bool = False) -> bool:
        """
        Checks if a user is clicking buttons too fast. If so, it answers the
        callback with a wait message and returns True. Otherwise, it updates
        the timestamp and returns False.
        """
        if bypass:
            return False
        message = getattr(call, "message", None)
        chat = getattr(message, "chat", None)
        if chat and chat.type == "private":
            flood_check = getattr(bot, "is_chat_flood_control_active", None)
            if not callable(flood_check) or not flood_check(chat.id):
                return False

        user_id = call.from_user.id
        current_time = time.time()

        last_call_time = self.user_timestamps.get(user_id, 0)
        time_since_last_call = current_time - last_call_time

        if time_since_last_call < MIN_INTERVAL_PER_USER:
            time_to_wait = MIN_INTERVAL_PER_USER - time_since_last_call
            # Use math.ceil to give a user-friendly whole number (e.g., "3s" instead of "2.7s")
            wait_seconds = math.ceil(time_to_wait)
            
            try:
                await bot.answer_callback_query(
                    call.id,
                    f"⏳ Flood prevention active. Please wait {wait_seconds}s.",
                    show_alert=False # This makes it a small toast notification
                )
            except Exception:
                # Ignore if answering the callback fails for any reason
                pass
                
            return True # Yes, the user is limited

        # If not limited, update their last call time and allow the action
        self.user_timestamps[user_id] = current_time
        return False # No, the user is not limited
