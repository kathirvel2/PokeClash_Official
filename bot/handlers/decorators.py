# ./bot/handlers/decorators.py
from functools import wraps
from telebot.async_telebot import AsyncTeleBot
from bot.mechanics.db import db
from telebot.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
import os

ADMIN_IDS_RAW = os.getenv('ADMIN_USER_IDS', '')
ADMIN_USER_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_RAW.split(',') if admin_id.strip()]

def admin_only(bot: AsyncTeleBot):
    """Decorator to allow only configured Telegram admins to run a handler."""
    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_call, *args, **kwargs):
            user_id = getattr(getattr(message_or_call, "from_user", None), "id", None)

            if user_id not in ADMIN_USER_IDS:
                if isinstance(message_or_call, Message):
                    await bot.reply_to(message_or_call, "Access denied. Admins only.")
                elif isinstance(message_or_call, CallbackQuery):
                    await bot.answer_callback_query(
                        message_or_call.id,
                        "Access denied. Admins only.",
                        show_alert=True
                    )
                return

            return await func(message_or_call, *args, **kwargs)
        return wrapper
    return decorator

def owner_only(bot: AsyncTeleBot):
    """
    A decorator that ensures only the designated user can interact with an inline keyboard.
    It checks for ownership in two ways, in order of priority:
    1. An owner ID embedded in the callback data (e.g., "action_param_ownerID").
    2. The user who sent the original command that the message is a reply to.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(call: CallbackQuery, *args, **kwargs):
            callback_user_id = call.from_user.id
            owner_id = None

            # --- NEW: Method 1: Check for an owner ID in the callback data ---
            parts = call.data.split('_')
            try:
                # Check if the last part of the callback data is a valid integer (user ID)
                last_part = int(parts[-1])
                # Simple sanity check for a valid-looking user ID
                if last_part > 100000:
                    owner_id = last_part
            except (ValueError, IndexError):
                # Last part is not an ID, so we'll try the next method
                pass
            
            # --- Method 2: Fallback to checking the reply_to_message ---
            if not owner_id and call.message.reply_to_message:
                owner_id = call.message.reply_to_message.from_user.id

            # --- Final Verification ---
            if owner_id:
                if callback_user_id == owner_id:
                    return await func(call, *args, **kwargs) # Success! Execute the function.
                else:
                    await bot.answer_callback_query(call.id, "These buttons are not for you.", show_alert=False)
                    return
            
            # If no owner could be determined by any method, show an error
            await bot.answer_callback_query(call.id, "Cannot verify the owner of this message.", show_alert=True)
            return
        return wrapper
    return decorator

def user_registered(bot: AsyncTeleBot):
    """
    A decorator that checks if the user has started the bot (/start).
    If not, it sends a message with a button to start the bot.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(message: Message, *args, **kwargs):
            user_id = message.from_user.id
            
            if not db.get_user_by_id(user_id):
                start_url = f"https://t.me/PokeClash_bot?start=start"
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("Start the Bot", url=start_url))
                
                await bot.reply_to(
                    message,
                    "👋 Before using this command, please start the bot first!",
                    reply_markup=markup
                )
                return
            
            return await func(message, *args, **kwargs)
        return wrapper
    return decorator

# --- NEW: Ban Enforcement Decorator ---
def user_not_banned(bot: AsyncTeleBot):
    """
    Decorator to check if a user is hard-banned before executing any command.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(message_or_call, *args, **kwargs):
            user_id = message_or_call.from_user.id
            
            ban_status = db.get_user_ban_status(user_id)
            
            if ban_status.get('is_banned', False):
                # User is hard-banned. Send a message if it's a Message.
                if isinstance(message_or_call, Message):
                    await bot.reply_to(
                        message_or_call,
                        "❌ You are currently banned from using this bot."
                    )
                # Answer callback if it's a CallbackQuery
                elif isinstance(message_or_call, CallbackQuery):
                    await bot.answer_callback_query(
                        message_or_call.id,
                        "You are banned from using this bot.",
                        show_alert=True
                    )
                return # Stop execution
            
            # User is not banned, proceed with the original function
            return await func(message_or_call, *args, **kwargs)
        
        return wrapper
    
    return decorator
