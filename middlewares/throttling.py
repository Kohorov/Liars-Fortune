import time
from typing import Callable, Dict, Any
from aiogram import BaseMiddleware
from aiogram.types import Update, Message, CallbackQuery

_last_call: dict[int, float] = {}
RATE_LIMIT_SECONDS = 0.5


class ThrottlingMiddleware(BaseMiddleware):
    """Block users who send more than 2 requests per second."""

    async def __call__(self, handler: Callable, event: Update, data: dict):
        user_id = None
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id

        if user_id:
            now = time.monotonic()
            last = _last_call.get(user_id, 0)
            if now - last < RATE_LIMIT_SECONDS:
                if event.callback_query:
                    await event.callback_query.answer("⏳ Too fast! Please slow down.", show_alert=False)
                return
            _last_call[user_id] = now

        return await handler(event, data)
