import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to your .env file.")

def _int_list(name):
    raw = os.getenv(name, "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit()]


MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "0"))
# Main admins can remove other admins and cannot be removed themselves.
# MAIN_ADMIN_ID stays supported; MAIN_ADMIN_IDS adds more (comma-separated).
MAIN_ADMIN_IDS = frozenset(i for i in [MAIN_ADMIN_ID, *_int_list("MAIN_ADMIN_IDS")] if i)
SUPPORT_CHAT_ID = int(os.getenv("SUPPORT_CHAT_ID", "0"))
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/liars_fortune_channel")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

from middlewares.registered import RegistrationMiddleware
from middlewares.throttling import ThrottlingMiddleware
dp.update.middleware(ThrottlingMiddleware())
dp.update.middleware(RegistrationMiddleware())
