from db_compat import connect_db, DBError, IntegrityError
from aiogram.types import Update, Message, ChatMember
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from functools import wraps
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Callable, Dict, Any
from aiogram import types
from aiogram.types import CallbackQuery
from aiogram import Bot, Dispatcher, F

from aiogram.fsm.context import FSMContext
class RegistrationMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data: dict):
        # imported lazily: db.py imports config.py, which imports this module
        from db import is_user_registered
        user_id = None
        state: FSMContext = data.get("state")
        current_state = await state.get_state() if state else None

        if event.message:
            # In groups the bot must stay silent for unregistered users —
            # group handlers (/newgame, lobby buttons) do their own checks.
            if event.message.chat.type != "private":
                return await handler(event, data)
            user_id = event.message.from_user.id
            command = event.message.text.strip() if event.message.text else None
            if not command or command == "/start" or command.startswith("/start "):
                return await handler(event, data)

        elif event.callback_query:
            user_id = event.callback_query.from_user.id

        if user_id and not event.callback_query:
            registered = is_user_registered(user_id)
            if not registered and current_state not in ("registration:pref_name", "registration_game:pref1_name"):
                if event.message:
                    from keyboards.keyboard import get_user_language
                    from i18n import t
                    ln = get_user_language(user_id)
                    await event.message.answer(t("register_first", ln))
                return
        return await handler(event, data)
def get_admins():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins")
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    return admins
def admin_required():
    def decorator(handler):
        @wraps(handler)
        async def wrapper(message: types.Message, *args, **kwargs):
            admin_list = list(get_admins())
            user_id = message.from_user.id
            if not user_id in admin_list:
                await message.answer("Siz noto'g'ri buyruq yubordingiz!")
                return
            return await handler(message, *args, **kwargs)
        return wrapper
    return decorator
