from i18n import t
from db_compat import connect_db, DBError, IntegrityError
import asyncio
import logging
from logger import logger
import uuid
import hendlers
import register
from aiogram import types
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.fsm.context import FSMContext
from aiogram.utils.deep_linking import create_start_link
from config import *
from keyboards.keyboard import *
from states.state import registration, registration_game, new_game
from keyboards.inline import *
from db import *
from aiogram.types import Update
import admin_panel
import game.tournaments
from game.group import (
    JOIN_PREFIX, LANGUAGE_KB, LANGUAGE_PROMPT, bot_username, join_from_link, join_link,
    lobby_kb, lobby_text,
)
from db_setup import setup_database

setup_database(MAIN_ADMIN_IDS)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, lang=0, user=None):
    # `user` is passed when re-entering from the language callback: there
    # `message` is the bot's own prompt, so message.from_user is the bot.
    user = user or message.from_user
    if message.chat.type != "private":
        await send_group_intro(message.chat.id)
        return
    user_id = user.id
    payload = message.text.split(" ", 1)[-1] if " " in message.text else ""
    if not "/start" in (message.text or ""):
        user_data = await state.get_data()
        payload = user_data.get("payload", "")
    if "game_" not in payload:
        await state.clear()
    await state.update_data(payload=payload)
    ln = lang
    if not (lang in ["uz", "en", "ru"]) and not is_user_registered(user_id):
        await message.answer(
            "🟣 Please select your language: \n\n🔴 Пожалуйста, выберите язык: \n\n🔵 Iltimos, tilni tanlang:",
            reply_markup=select_language_button,
        )
        return
    if is_user_registered(user_id):
        if lang == 0:
            ln = get_user_language(user_id)
        else:
            ln = lang
    if "game_" in payload:
        if not is_user_registered(user_id):
            ms = t("welcome", ln)
            await message.answer(ms, reply_markup=get_username_button(ln))
            await state.set_state(registration_game.pref1_name)
            return

        game_id = payload.split("game_")[1]
        if get_player_count(game_id) == 0:
            ms = t("game_finished_or_stopped", ln)
            await message.answer(ms)
            return
        if game_id == get_game_id_by_user(user_id):
            if user_id == get_game_inviter_id(game_id):
                ms = t("already_in_game_as_creator", ln)
                await message.answer(ms)
            else:
                ms = t("already_in_game", ln)
                await message.answer(ms)
            return
        if get_needed_players(game_id) <= get_player_count(game_id):
            ms = t("no_space_in_game", ln)
            await message.answer(ms)
            await state.clear()
            return

        inviter_id = get_game_inviter_id(game_id)
        if not inviter_id:
            ms = t("game_stopped_by_creator", ln)
            await message.answer(ms)
            await state.clear()
            return
        if inviter_id and inviter_id == user.id:
            ms = t("already_in_game_as_creator", ln)
            await message.answer(ms)
            return
        if is_user_in_game(game_id, user.id):
            ms = t("already_in_game", ln)
            await message.answer(ms)
            return
        if not inviter_id:
            ms = t("game_stopped_by_creator", ln)
            await message.answer(ms)
            await state.clear()
            return
        if has_incomplete_games(user_id):
            ms = t("incomplete_games", ln)
            kb = kb_variant(ln, en=stop_incomplete_games, ru=stop_incomplete_games_ru, uz=stop_incomplete_games_uz)
            await message.answer(
                ms,
                reply_markup=kb,
            )
            await state.clear()
            return

        insert_invitation(inviter_id, user.id, game_id)
        player_count = get_player_count(game_id)
        if player_count < 2:
            ms = t("game_stopped_by_creator", ln)
            await message.answer(ms)
            await state.clear()
            return
        name = get_user_nfgame(user.id)
        ln1 = get_user_language(inviter_id)
        ms1 = t("player_p0_has_joined_the", ln1, p0=name, p1=player_count)
        ms = t("you_have_successfully_joined_the", ln, p0=player_count)

        await message.answer(ms)
        await bot.send_message(inviter_id, ms1)
        if get_needed_players(game_id) == get_player_count(game_id):
            ms = t("all_players_ready", ln1)
            kb = kb_variant(ln1, en=start_stop_game, ru=start_stop_game_ru, uz=start_stop_game_uz)
            await bot.send_message(
                inviter_id,
                ms,
                reply_markup=kb,
            )
        await state.clear()
    elif payload.startswith(JOIN_PREFIX) and is_user_registered(user.id):
        await state.clear()
        await message.answer(t("main_menu", ln), reply_markup=get_main_menu(user.id))
        await join_from_link(user.id, payload[len(JOIN_PREFIX):])
    else:
        if is_user_registered(user.id):
            ms = t("main_menu", ln)
            await message.answer(
                ms,
                reply_markup=get_main_menu(user.id),
            )
        else:
            ms = t("welcome", ln)
            await message.answer(ms, reply_markup=get_username_button(ln))
            await state.set_state(registration.pref_name)


@dp.callback_query(lambda c: c.data.startswith("lan_"))
async def set_language(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    language = callback.data.split("lan_")[1]
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO user_languages (user_id, language) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET language = ?
        """,
        (user_id, language, language),
    )
    conn.commit()
    conn.close()

    await callback.message.delete()
    await cmd_start(callback.message, state, lang=language, user=callback.from_user)


@dp.message(F.text.in_(["start game 🎮", "o'yinni boshlash 🎮", "новая игра 🎮"]))
async def start_game_handler(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    ms = t("tournament_restriction", ln)
    if is_user_in_tournament_and_active(message.from_user.id):
        await message.answer(ms)
        return
    ms = t("incomplete_games_warning", ln)
    ms1 = t("choose_players", ln)
    kb = kb_variant(ln, en=stop_incomplete_games, ru=stop_incomplete_games_ru, uz=stop_incomplete_games_uz)
    kb1 = kb_variant(ln, en=count_players, ru=count_players_ru, uz=count_players_uz)
    if message.chat.type == "private":
        if has_incomplete_games(message.from_user.id):
            await message.answer(ms, reply_markup=kb)
            return
        username = await bot_username()
        group_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t("btn_add_to_group", ln),
                url=f"https://t.me/{username}?startgroup=true",
            )
        ]])
        await message.answer(t("play_in_group_hint", ln), reply_markup=group_kb)
        await message.answer(ms1, reply_markup=kb1)
        await state.set_state(new_game.number_of_players)
    else:
        await message.answer(t("use_newgame_in_group", ln))


@dp.message(
    F.text.in_(
        [
            "back to main menu 🔙",
            "вернуться в главное меню 🔙",
            "bosh menuga qaytish 🔙",
        ]
    )
)
async def start_game_handler(message: types.Message, state: FSMContext):
    await state.clear()
    ln = get_user_language(message.from_user.id)
    ms = t("main_menu", ln)
    await message.answer(
        ms,
        reply_markup=get_main_menu(message.from_user.id),
    )


@dp.message(new_game.number_of_players)
async def get_name(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    ms = t("invalid_info", ln)
    kb = kb_variant(ln, en=count_players, ru=count_players_ru, uz=count_players_uz)
    cnt = 0
    if message.text == "2️⃣":
        cnt = 2
    elif message.text == "3️⃣":
        cnt = 3
    elif message.text == "4️⃣":
        cnt = 4
    else:
        await message.answer(
            ms,
            reply_markup=kb,
        )
        await state.set_state(new_game.number_of_players)
        return

    user = message.from_user
    game_id = str(uuid.uuid4())
    invite_link = await create_start_link(bot, payload=f"game_{game_id}")
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO invitations (inviter_id, game_id, needed_players)
        VALUES (?, ?, ?)
        """,
        (user.id, game_id, cnt),
    )
    conn.commit()
    conn.close()
    ms = t("invitation_link_text", ln)
    await message.answer(
        ms,
        reply_markup=get_main_menu(user.id),
    )
    sharable_message = t("join_the_game_i_just", ln, p0=invite_link)

    await message.answer(
        sharable_message,
    )
    await state.clear()


# @dp.message(F.text == "game status 🌟")
# async def start_game_handler(message: types.Message, state: FSMContext):
#     if is_user_in_tournament_and_active(message.from_user.id):
#         await message.answer(f"You are participating in a tournament and can't use this button until the tournament ends!")
#         return
#     game_id = get_game_id_by_user(message.from_user.id)
#     if not has_incomplete_games(message.from_user.id):
#         await message.answer(
#             f"You are not participating in any game currently.",
#             reply_markup=get_main_menu(message.from_user.id),
#         )
#     else:
#         msg = f"Current game status: active ✅\n"
#         if message.from_user.id == get_game_inviter_id(game_id):
#             msg += f"You are creator of this game 👨‍💻\nNumber of participants: {get_player_count(game_id)}"
#             await message.answer(msg, reply_markup=generate_exclude_keyboard(game_id))
#         else:
#             msg += f"You are participant in this game 👤\nNumber of participants: {get_player_count(game_id)}"
#             await message.answer(msg, reply_markup=cancel_g)


import random


async def send_group_intro(chat_id):
    lang = get_group_language(chat_id)
    if lang:
        await bot.send_message(chat_id, t("group_welcome", lang))
    else:
        await bot.send_message(chat_id, LANGUAGE_PROMPT, reply_markup=LANGUAGE_KB)


@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def bot_added_to_group(event: types.ChatMemberUpdated):
    if event.chat.type in ("group", "supergroup"):
        await bot.send_message(event.chat.id, LANGUAGE_PROMPT, reply_markup=LANGUAGE_KB)


async def _is_group_admin(chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in ("creator", "administrator")


@dp.message(Command("language"))
async def group_language_command(message: types.Message):
    if message.chat.type == "private":
        return
    if not await _is_group_admin(message.chat.id, message.from_user.id):
        lang = get_group_language(message.chat.id) or get_user_language(message.from_user.id)
        await message.reply(t("group_lang_admin_only", lang))
        return
    await message.answer(LANGUAGE_PROMPT, reply_markup=LANGUAGE_KB)


@dp.callback_query(F.data.startswith("glang_"))
async def group_language_chosen(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    lang = callback.data[len("glang_"):]
    if lang not in ("en", "ru", "uz"):
        await callback.answer()
        return
    if not await _is_group_admin(chat_id, callback.from_user.id):
        current = get_group_language(chat_id) or get_user_language(callback.from_user.id)
        await callback.answer(t("group_lang_admin_only", current), show_alert=True)
        return
    set_group_language(chat_id, lang)
    try:
        await callback.message.edit_text(t("group_welcome", lang))
    except Exception:
        pass
    await callback.answer()


def _group_lang(chat_id, user_id):
    return get_group_language(chat_id) or get_user_language(user_id)


@dp.message(Command("newgame"))
async def newgame_in_group(message: types.Message):
    user_id = message.from_user.id
    if message.chat.type == "private":
        await message.answer(t("newgame_private_hint", get_user_language(user_id)))
        return
    ln = _group_lang(message.chat.id, user_id)
    if not is_user_registered(user_id):
        username = await bot_username()
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t("btn_open_bot", ln), url=f"https://t.me/{username}")
        ]])
        await message.reply(t("lobby_need_dm", ln), reply_markup=kb)
        return
    if get_group_active_game(message.chat.id):
        await message.reply(t("group_has_active_game", ln))
        return
    if has_incomplete_games(user_id):
        await message.reply(t("incomplete_games", ln))
        return
    game_id = str(uuid.uuid4())
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO invitations (inviter_id, game_id, needed_players, group_chat_id) "
        "VALUES (?, ?, ?, ?)",
        (user_id, game_id, 4, message.chat.id),
    )
    conn.commit()
    conn.close()
    gln = get_game_language(game_id)
    lobby_msg = await message.answer(
        lobby_text(game_id, gln), reply_markup=await lobby_kb(game_id, gln)
    )
    # tracked so the lobby card is wiped with the rest at game end
    save_message(message.chat.id, game_id, lobby_msg.message_id)
    save_lobby_message(game_id, message.chat.id, lobby_msg.message_id)


@dp.message(Command("stopgame"))
async def stopgame_in_group(message: types.Message):
    if message.chat.type == "private":
        return
    user_id = message.from_user.id
    ln = _group_lang(message.chat.id, user_id)
    game_id = get_group_active_game(message.chat.id)
    if not game_id:
        await message.reply(t("stopgame_none", ln))
        return
    if user_id != get_game_inviter_id(game_id) and not is_user_admin(user_id):
        await message.reply(t("lobby_not_creator", ln))
        return
    for p in get_all_players_in_game(game_id):
        if p:
            delete_user_from_all_games(p)
    delete_game(game_id)
    await delete_all_game_messages(game_id)
    await message.answer(t("stopgame_done", ln))


@dp.callback_query(lambda c: c.data.startswith("glj_"))
async def group_lobby_join(callback: types.CallbackQuery):
    """Lobby cards posted before joins moved to the private chat."""
    await callback.answer(url=await join_link(callback.data[4:]))


_starting_group_games = set()


@dp.callback_query(lambda c: c.data.startswith("gls_"))
async def group_lobby_start(callback: types.CallbackQuery):
    game_id = callback.data[4:]
    user_id = callback.from_user.id
    ln = get_user_language(user_id)
    if user_id != get_game_inviter_id(game_id):
        await callback.answer(t("lobby_not_creator", ln), show_alert=True)
        return
    # updates are handled concurrently: without the in-flight set a double tap
    # passed the is_started check twice and dealt the game twice
    if is_game_started(game_id) or game_id in _starting_group_games:
        await callback.answer(t("game_finished_or_stopped", ln), show_alert=True)
        return
    count = get_player_count(game_id)
    if count < 2:
        await callback.answer(t("lobby_need_two", ln), show_alert=True)
        return
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE invitations SET needed_players = ? WHERE game_id = ?",
        (count, game_id),
    )
    conn.commit()
    conn.close()
    gln = get_game_language(game_id)
    try:
        await callback.message.edit_text(lobby_text(game_id, gln))
    except Exception:
        pass
    await callback.answer()
    _starting_group_games.add(game_id)
    try:
        await _start_group_game(game_id, gln)
    finally:
        _starting_group_games.discard(game_id)


@dp.callback_query(lambda c: c.data.startswith("glc_"))
async def group_lobby_cancel(callback: types.CallbackQuery):
    game_id = callback.data[4:]
    user_id = callback.from_user.id
    ln = get_user_language(user_id)
    if user_id != get_game_inviter_id(game_id):
        await callback.answer(t("lobby_not_creator", ln), show_alert=True)
        return
    for p in get_all_players_in_game(game_id):
        if p:
            delete_user_from_all_games(p)
    delete_game(game_id)
    gln = get_game_language(game_id) if get_game_inviter_id(game_id) else ln
    try:
        await callback.message.edit_text(t("lobby_cancelled", gln))
    except Exception:
        pass
    await callback.answer()


async def _start_group_game(game_id, gln):
    from game.game_state import send_random_cards_to_players
    group_id = get_group_chat_id(game_id)
    players = [p for p in get_all_players_in_game(game_id) if p]
    suits = ["heart ❤️", "diamond ♦️", "spade ♠️", "club ♣️"]
    cur_table = set_current_table(game_id, random.choice(suits))
    number = 19 if len(players) == 2 else 23 if len(players) == 3 else 27
    for p in players:
        reset_exclusion_count(game_id, p)
        create_game_record_if_not_exists(game_id, p)
    insert_number_of_cards(game_id, number)
    mark_game_as_started(game_id)
    rang = ["🔴", "🟠", "🟡", "🟢", "⚪️"]
    roster = "".join(f"{rang[i]} {get_user_nfgame(p)}\n" for i, p in enumerate(players))
    for p in players:
        set_real_bullet_for_player(game_id, p)
    first_player = random.choice(players)
    set_current_turn(game_id, first_player)
    ims = (
        t("game_has_started_there_are", gln, p0=number, p1=number // 4,
          p2=roster, p3=cur_table)
        + "\n\n" + t("first_move", gln, p0=get_user_nfgame(first_player))
        + "\n" + t("group_cards_in_dm", gln)
    )
    msg = await bot.send_message(group_id, ims)
    save_message(group_id, game_id, msg.message_id)
    save_player_cards(game_id)
    await send_random_cards_to_players(game_id)


@dp.message()
async def any_word(msg: types.Message):
    if msg.chat.type != "private":
        return  # never react to (or delete!) regular group conversation
    if not is_user_registered(msg.from_user.id):
        await msg.delete()
    else:
        ln = get_user_language(msg.from_user.id)
        ms = t("wrong_input", ln)
        await msg.answer(ms)


async def _register_commands():
    from aiogram.types import (
        BotCommand,
        BotCommandScopeAllPrivateChats,
        BotCommandScopeAllGroupChats,
    )
    group_cmds = {
        None: [  # default (English)
            BotCommand(command="newgame", description="🎮 Start a Liar's Fortune game"),
            BotCommand(command="stopgame", description="🚫 Stop the current game (creator)"),
            BotCommand(command="language", description="🌐 Group language (admins)"),
        ],
        "ru": [
            BotCommand(command="newgame", description="🎮 Начать игру Liar's Fortune"),
            BotCommand(command="stopgame", description="🚫 Остановить игру (создатель)"),
            BotCommand(command="language", description="🌐 Язык группы (админы)"),
        ],
        "uz": [
            BotCommand(command="newgame", description="🎮 Liar's Fortune o'yinini boshlash"),
            BotCommand(command="stopgame", description="🚫 O'yinni to'xtatish (yaratuvchi)"),
            BotCommand(command="language", description="🌐 Guruh tili (adminlar)"),
        ],
    }
    private_cmds = {
        None: [BotCommand(command="start", description="🏠 Main menu / restart")],
        "ru": [BotCommand(command="start", description="🏠 Главное меню / перезапуск")],
        "uz": [BotCommand(command="start", description="🏠 Bosh menu / qayta boshlash")],
    }
    for lang, cmds in group_cmds.items():
        await bot.set_my_commands(cmds, scope=BotCommandScopeAllGroupChats(), language_code=lang)
    for lang, cmds in private_cmds.items():
        await bot.set_my_commands(cmds, scope=BotCommandScopeAllPrivateChats(), language_code=lang)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await _register_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    import os
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
