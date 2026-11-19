"""Group chat lobbies: language picker, lobby card, and joining via the bot.

Joining always goes through the private chat (a t.me/<bot>?start=gj_<id>
link), because the bot can only send cards to people who have started it,
and new players have to register first.
"""
import asyncio
import html

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import bot
from db import (
    get_all_players_in_game,
    get_game_creator_id,
    get_game_inviter_id,
    get_game_language,
    get_group_chat_id,
    get_lobby_message,
    get_player_count,
    get_user_language,
    get_user_nfgame,
    has_incomplete_games,
    insert_invitation,
    is_game_started,
    is_user_in_game,
    save_message,
)
from i18n import t
from logger import logger

JOIN_PREFIX = "gj_"
MAX_PLAYERS = 4

LANGUAGE_PROMPT = (
    "Choose the language for this group\n"
    "Выберите язык для этой группы\n"
    "Guruh uchun tilni tanlang"
)
LANGUAGE_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🇬🇧 English", callback_data="glang_en"),
    InlineKeyboardButton(text="🇷🇺 Русский", callback_data="glang_ru"),
    InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="glang_uz"),
]])

_bot_username = None
_join_locks = {}


async def bot_username():
    global _bot_username
    if _bot_username is None:
        _bot_username = (await bot.get_me()).username
    return _bot_username


async def join_link(game_id):
    return f"https://t.me/{await bot_username()}?start={JOIN_PREFIX}{game_id}"


def lobby_text(game_id, ln):
    players = [p for p in get_all_players_in_game(game_id) if p]
    roster = "\n".join(f"• {get_user_nfgame(p)}" for p in players)
    return t("group_lobby", ln, name=get_user_nfgame(get_game_creator_id(game_id)),
             count=len(players), roster=roster)


async def lobby_kb(game_id, ln):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("btn_join", ln), url=await join_link(game_id))],
        [
            InlineKeyboardButton(text=t("btn_start_game", ln), callback_data=f"gls_{game_id}"),
            InlineKeyboardButton(text=t("btn_cancel_game", ln), callback_data=f"glc_{game_id}"),
        ],
    ])


async def refresh_lobby(game_id):
    """Redraw the lobby card in the group with the current roster."""
    lobby = get_lobby_message(game_id)
    if not lobby:
        return
    chat_id, message_id = lobby
    ln = get_game_language(game_id)
    try:
        await bot.edit_message_text(
            lobby_text(game_id, ln), chat_id=chat_id, message_id=message_id,
            reply_markup=await lobby_kb(game_id, ln),
        )
    except TelegramBadRequest:
        pass  # roster unchanged or card deleted


async def _group_title(chat_id):
    try:
        return (await bot.get_chat(chat_id)).title or ""
    except Exception:
        return ""


async def join_from_link(user_id, game_id):
    """Seat a registered user in a group lobby and tell them how it went."""
    ln = get_user_language(user_id)
    lock = _join_locks.setdefault(game_id, asyncio.Lock())
    async with lock:
        creator = get_game_inviter_id(game_id)
        group_id = get_group_chat_id(game_id)
        if not creator or not group_id or is_game_started(game_id):
            key = "game_finished_or_stopped"
        elif user_id == creator or is_user_in_game(game_id, user_id):
            key = "already_in_game"
        elif has_incomplete_games(user_id):
            key = "incomplete_games"
        elif get_player_count(game_id) >= MAX_PLAYERS:
            key = "no_space_in_game"
        else:
            insert_invitation(creator, user_id, game_id)
            key = None
    if key:
        await bot.send_message(user_id, t(key, ln))
        return False

    await refresh_lobby(game_id)
    title = html.escape(await _group_title(group_id))
    await bot.send_message(user_id, t("group_joined_dm", ln, group=f"<b>{title}</b>"),
                           parse_mode="HTML")
    gln = get_game_language(game_id)
    try:
        msg = await bot.send_message(
            group_id,
            t("group_player_joined", gln, name=get_user_nfgame(user_id),
              count=get_player_count(game_id)),
        )
        save_message(group_id, game_id, msg.message_id)
    except Exception as e:
        logger.warning(f"Could not post join notice in {group_id}: {e}")
    return True
