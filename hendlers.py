from i18n import t
from db_compat import connect_db, DBError, IntegrityError
import asyncio
import html
from logger import logger
from config import dp, F, bot, SUPPORT_CHAT_ID, MAIN_ADMIN_ID
from aiogram import types
from aiogram.fsm.context import FSMContext
from keyboards.keyboard import *
from keyboards.inline import *
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from states.state import NewGameState, MessagetoAdmin, awaiting_game_number
from db import *


@dp.message(F.text.in_(["settings ⚙️", "sozlamalar ⚙️", "настройки ⚙️"]))
async def settingxcyvus(message: types.Message):
    ln = get_user_language(message.from_user.id)
    ms = t("settings", ln)
    kb = kb_variant(ln, en=change_name, ru=change_name_ru, uz=change_name_uz)
    await message.answer(ms, reply_markup=kb)


@dp.message(F.text.in_(["❓ help", "❓ yordam", "❓ помощь"]))
async def help_butn(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    ms = t("help_prompt", ln)
    kb = kb_variant(ln, en=cancel_button, ru=cancel_button_ru, uz=cancel_button_uz)
    await message.answer(ms, reply_markup=kb)

    await state.set_state(MessagetoAdmin.msgt)


@dp.message(MessagetoAdmin.msgt)
async def help_button_state(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    if not message.text in [
        "back to main menu 🔙",
        "вернуться в главное меню 🔙",
        "bosh menuga qaytish 🔙",
    ]:
        if not message.text:
            await message.answer(t("help_prompt", ln))
            return
        # escaped: any "<" or "&" in the user's name or text made Telegram
        # reject the message, and the user still got no confirmation
        try:
            await bot.send_message(
                chat_id=SUPPORT_CHAT_ID,
                text=f"User — {html.escape(message.from_user.first_name or '')} (<a href='tg://openmessage?user_id={message.from_user.id}'>{message.from_user.id}</a>) sent you message: \n{html.escape(message.text)}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Support message from {message.from_user.id} not delivered: {e}")

        ms = t("message_sent", ln)
        await message.answer(ms, reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
    else:
        await state.clear()
        ms = t("main_menu", ln)
        await message.answer(ms, reply_markup=get_main_menu(message.from_user.id))


@dp.message(
    F.text.in_(
        [
            "изменить имя пользователя 🖌",
            "change username 🖌",
            "usernameni o'zgartirish  🖌",
        ]
    )
)
async def changeee(message: types.Message, state: FSMContext):
    await state.clear()
    ln = get_user_language(message.from_user.id)
    ms = t("your_current_username_is_p0", ln, p0=get_user_nfgame(message.from_user.id))
    ms1 = t("if_you_d_like_to", ln)
    kb = kb_variant(ln, en=cancel_button, ru=cancel_button_ru, uz=cancel_button_uz)
    await message.answer(ms, reply_markup=kb)
    await message.answer(ms1, reply_markup=get_username_button(ln))
    await state.set_state(NewGameState.waiting_for_nfgame)


@dp.message(NewGameState.waiting_for_nfgame)
async def set_new_nfgame(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    if not message.text:
        await message.answer(t("username_invalid", ln))
        return
    new_nfgame = message.text.strip()
    if is_game_started(get_game_id_by_user(message.from_user.id)):
        ms = t("username_in_game_locked", ln)
        await message.answer(ms, reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
    if new_nfgame in [
        "back to main menu 🔙",
        "вернуться в главное меню 🔙",
        "bosh menuga qaytish 🔙",
    ]:
        await state.clear()
        ms = t("main_menu", ln)
        await message.answer(ms, reply_markup=get_main_menu(message.from_user.id))
        return
    h = is_name_valid(new_nfgame)
    if not h:
        ms = t("username_invalid", ln)
        kb = kb_variant(ln, en=cancel_button, ru=cancel_button_ru, uz=cancel_button_uz)
        await message.answer(ms, reply_markup=kb)
    elif h == 2:
        ms = t("username_taken", ln)
        kb = kb_variant(ln, en=cancel_button, ru=cancel_button_ru, uz=cancel_button_uz)
        await message.answer(ms, reply_markup=kb)
    else:
        user_id = message.from_user.id
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users_database SET nfgame = ? WHERE user_id = ?",
                (new_nfgame, user_id),
            )
            conn.commit()

        ms = t("your_name_has_been_successfully", ln, p0=new_nfgame)
        await message.answer(ms, reply_markup=get_main_menu(message.from_user.id))
        await state.clear()


@dp.message(F.text.in_(["cancel 🚫", "отмена 🚫", "bekor qilish 🚫"]))
async def cancel(message: types.Message, state: FSMContext):
    await state.clear()
    ln = get_user_language(message.from_user.id)
    ms = t("you_have_canceled_the_operation", ln)
    await message.answer(ms, reply_markup=get_main_menu(message.from_user.id))


@dp.message(F.text.in_(["game rules 📜", "o'yin qoidalari 📜", "правила игры 📜"]))
async def how_to_play(message: types.Message, state: FSMContext):
    await state.clear()
    ln = get_user_language(message.from_user.id)
    msg = t("game_rules_players_2_4", ln)
    await message.answer(msg, parse_mode="Markdown")


def get_user_game_archive(user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT game_id, game_start_time, game_end_time, game_winner
            FROM game_archive
            WHERE user_id = ?
            """,
            (user_id,),
        )
        games = cursor.fetchall()
        return games
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return []
    finally:
        conn.close()


@dp.message(F.text.in_(["bonus 🚀", "bonus 🚀", "бонус 🚀"]))
async def get_daily_bonus_function(message: types.Message):
    user_id = message.from_user.id
    ln = get_user_language(user_id)
    bn = t("claim_bonus", ln)
    msg = t("daily_bonus_claim_your_reward", ln)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=bn, callback_data=f"bonus_cb_{user_id}")]
        ]
    )

    await message.answer(
        msg,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


def get_start_of_week():
    # stored times are UTC+5, so the week boundary must be too
    today = datetime.now(timezone.utc) + timedelta(hours=5)
    start_of_week = today - timedelta(days=today.weekday())
    return start_of_week.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%d 00:00:00"
    )


def get_weekly_leaderboard():
    conn = connect_db()
    cursor = conn.cursor()

    start_of_week = get_start_of_week()
    cursor.execute(
        """
        SELECT user_id, game_winner
        FROM game_archive
        WHERE game_end_time >= ?
        """,
        (start_of_week,),
    )
    records = cursor.fetchall()
    conn.close()

    totals = {}
    wins = {}
    for user_id, game_winner in records:
        totals[user_id] = totals.get(user_id, 0) + 1
        winner_id = None
        if game_winner and " - " in game_winner:
            try:
                winner_id = int(game_winner.rsplit(" - ", 1)[1])
            except (TypeError, ValueError):
                winner_id = None
        if winner_id == user_id:
            wins[user_id] = wins.get(user_id, 0) + 1

    leaderboard = [
        (user_id, total_games, wins.get(user_id, 0))
        for user_id, total_games in totals.items()
    ]
    leaderboard.sort(key=lambda row: (-row[2], -row[1], row[0]))
    return leaderboard[:10]


def format_weekly_leaderboard(user_id):
    leaderboard = get_weekly_leaderboard()
    ln = get_user_language(user_id)
    msg = t("no_games_played_since_monday", ln)
    leaderboard_text = t("weekly_leaderboard", ln)
    if not leaderboard:
        return msg

    medals = ["🥇", "🥈", "🥉"]

    for rank, (user_id, total_games, games_won) in enumerate(leaderboard, start=1):
        username = get_user_nfgame(user_id)
        medal = f"{medals[rank - 1]}. " if rank <= 3 else f"{rank}."
        leaderboard_text += f"{medal} {username} — 🎮 {total_games} | 🏆 {games_won}\n"

    return leaderboard_text


@dp.message(F.text.in_(["🏅 Leaderboard", "🏅 Лидербоард", "🏅 Liderbord"]))
async def show_weekly_leaderboard(message: types.Message):
    leaderboard_text = format_weekly_leaderboard(message.from_user.id)
    await message.answer(leaderboard_text)


@dp.message(F.text.in_(["📱 kabinet", "📱 cabinet", "📱 кабинет"]))
async def my_cabinet(message: types.Message):
    user_id = message.from_user.id
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT registration_date, nfgame, unity_coin FROM users_database WHERE user_id = ?",
        (user_id,),
    )
    user_info = cursor.fetchone()
    if not user_info:
        await message.answer("❌ You are not registered in the database.")
        conn.close()
        return
    registration_date, nfgame, unity_coins = user_info
    cursor.execute("SELECT COUNT(*) FROM game_archive WHERE user_id = ?", (user_id,))
    games_played = cursor.fetchone()[0]
    conn.close()
    ln = get_user_language(message.from_user.id)
    user_cabinet_message = t("your_cabinet_username_p0_registration", ln, p0=nfgame, p1=registration_date, p2=games_played, p3=get_number_of_referrals(message.from_user.id), p4=unity_coins)
    await message.answer(user_cabinet_message)


@dp.message(F.text.in_(["🤩 tournaments", "🤩 turnirlar", "🤩 турниры"]))
async def show_tournaments_menu(message: types.Message):
    get_o = get_ongoing_tournaments()
    ln = get_user_language(message.from_user.id)
    ong = t("there_is_an_ongoing_tournament", ln)
    upc = t("no_upcoming_tournaments_are_scheduled", ln)
    if get_o:
        await message.answer(ong, reply_markup=archive_tournamnets)
        return
    tournaments = get_upcoming_tournaments()
    if not tournaments:
        await message.answer(upc, reply_markup=archive_tournamnets)
        return
    # accumulate: the loop used to overwrite, showing only the last tournament
    response = "\n\n".join(
        t("tournament_id_p0_starts_p1", ln, p0=tr['id'], p1=tr['start_time'], p2=tr['end_time'], p3=tr['prize'])
        for tr in tournaments
    )
    await message.answer(
        response,
        reply_markup=archive_tournamnets,
    )


@dp.message(F.text.in_(["❄️ referal", "❄️ referral", "❄️ реферал"]))
async def tournaments_users_button(message: types.Message):
    referral_link = await generate_referral_link(message.from_user.id)
    u_coins = get_unity_coin_referral()
    ln = get_user_language(message.from_user.id)
    ms = t("here_is_your_refferal_link", ln, p0=u_coins)
    ref = t("hey_join_this_bot_to", ln, p0=referral_link)
    await message.answer(ms)
    await message.answer(ref)


@dp.message(
    F.text.in_(["change Language 🇺🇸", "изменить язык 🇷🇺", "Tilni o'zgartirish 🇺🇿"])
)
async def change_langguage(message: types.Message):
    ln = get_user_language(message.from_user.id)
    ms = t("please_select_your_language", ln)
    await message.answer(ms, reply_markup=select_language_button_2)


# @dp.message(F.text == "🎯 game archive")
# async def show_game_archive(message: types.Message, state: FSMContext):
#     user_id = message.from_user.id
#     games = get_user_game_archive(user_id)

#     if not games:
#         await message.answer("No games found in your archive.")
#         return
#     response = "📜 Your Game Archive:\n\n"
#     for idx, (_, start_time, _, _) in enumerate(games, start=1):
#         response += f"{idx}. game — {start_time.split(' ')[0]} 📅\n"

#     response += "\n📋 Send the game number to view its details."
#     await message.answer(response, reply_markup=cancel_button)
#     await state.set_state(awaiting_game_number.waiting)

# @dp.message(awaiting_game_number.waiting)
# async def send_game_statistics(message: types.Message, state: FSMContext):
#     if message.text == "back to main menu 🔙":
#         await state.clear()
#         await message.answer(
#             f"You are in main menu.", reply_markup=get_main_menu(message.from_user.id)
#         )
#         return
#     user_id = message.from_user.id
#     games = get_user_game_archive(user_id)

#     if not message.text.isdigit():
#         await message.answer(
#             "❌ Please send a valid game number.", reply_markup=get_main_menu(user_id)
#         )
#         await state.clear()
#         return
#     game_number = int(message.text)
#     if game_number < 1 or game_number > len(games):
#         await message.answer(
#             "❌ Invalid game number. Please try again.",
#             reply_markup=get_main_menu(user_id),
#         )
#         await state.clear()
#         return
#     record_id, start_time, end_time, winner = games[game_number - 1]
#     game_status = (
#         f"🕹 Game Details:\n"
#         f"🆔 Game ID: {record_id}\n"
#         f"⏰ Start Time: {start_time}\n"
#         f"🏁 End Time: {end_time if end_time else 'Has not finished'}\n"
#         f"🏆 Winner: {winner if winner else 'No Winner'}"
#     )
#     await message.answer(
#         game_status,
#         reply_markup=get_main_menu(message.from_user.id),
#     )
#     await state.clear()


@dp.message(F.text.in_(["pul ishlash 💸", "зарабатывать 💸", "earn 💸"]))
async def earn_feature_for_users(message: types.Message):
    user_id = message.from_user.id
    ln = get_user_language(user_id)
    msg = t("here_you_can_find_all", ln)
    kb = kb_variant(ln, en=main_earn_button, ru=main_earn_button_ru, uz=main_earn_button_uz)
    await message.answer(msg, reply_markup=kb)


from aiogram.utils.keyboard import InlineKeyboardBuilder


@dp.message(F.text.in_(["Join channels 💎", "Подписаться 💎", "obuna bo'lish 💎"]))
async def join_channels_to_earn(message: types.Message):
    user_id = message.from_user.id
    channels = get_unsubscribed_channels(user_id)
    if not channels:
        await message.answer("There are no channels to subscribe to yet 😓")
        return
    channel_id, channel_link = channels
    ln = get_user_language(user_id)
    ms1 = t("subscribe", ln)
    ms2 = t("check", ln)
    ms3 = t("skip", ln)
    ms4 = t("join_this_channel_and_receive", ln)
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=ms1, url=channel_link)
    keyboard.button(text=ms2, callback_data=f"check_sub:{channel_id}")
    keyboard.button(text=ms3, callback_data=f"skip_sub:{channel_id}")
    keyboard.adjust(1)

    await message.answer(ms4, reply_markup=keyboard.as_markup())


@dp.callback_query(lambda c: c.data.startswith("check_sub:"))
async def check_subscription(callback: types.CallbackQuery):
    channel_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    ln = get_user_language(user_id)
    ms12 = t("you_have_been_awarded_5", ln)
    ms22 = t("there_are_no_channels_to", ln)
    ms1 = t("subscribe", ln)
    ms2 = t("check", ln)
    ms3 = t("skip", ln)
    ms4 = t("join_this_channel_and_receive", ln)
    ms5 = t("you_are_not_subscribed_yet", ln)
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    except Exception as e:  # bot removed from channel / channel deleted
        logger.warning(f"Subscription check failed for {channel_id}: {e}")
        await callback.answer(ms5, show_alert=True)
        return

    if member.status in ["member", "administrator", "creator"]:
        if not save_subscription(user_id, channel_id):
            await callback.answer("You have already received the reward for this channel.", show_alert=True)
            return
        award_coins(user_id, 5)
        await callback.answer()
        await callback.message.edit_text(ms12)
        channels = get_unsubscribed_channels(user_id)
        if not channels:
            await callback.message.answer(ms22)
            return

        channel_id, channel_link = channels

        keyboard = InlineKeyboardBuilder()
        keyboard.button(text=ms1, url=channel_link)
        keyboard.button(text=ms2, callback_data=f"check_sub:{channel_id}")
        keyboard.button(text=ms3, callback_data=f"skip_sub:{channel_id}")
        keyboard.adjust(1)

        await callback.message.answer(
            ms4,
            reply_markup=keyboard.as_markup(),
        )

    else:
        await callback.answer(ms5, show_alert=True)


@dp.callback_query(lambda c: c.data.startswith("skip_sub:"))
async def skip_subscription(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    channel_id = callback.data.split(":", 1)[1]
    await callback.answer()

    save_subscription(user_id, channel_id)
    await callback.message.delete()
    ln = get_user_language(user_id)
    ms12 = t("you_have_been_awarded_5", ln)
    ms22 = t("there_are_no_channels_to", ln)
    ms1 = t("subscribe", ln)
    ms2 = t("check", ln)
    ms3 = t("skip", ln)
    ms4 = t("join_this_channel_and_receive", ln)
    ms5 = t("you_are_not_subscribed_yet", ln)
    channels = get_unsubscribed_channels(user_id)
    if not channels:
        await callback.message.answer(ms22)
        return

    channel_id, channel_link = channels

    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=ms1, url=channel_link)
    keyboard.button(text=ms2, callback_data=f"check_sub:{channel_id}")
    keyboard.button(text=ms3, callback_data=f"skip_sub:{channel_id}")
    keyboard.adjust(1)

    await callback.message.answer(
        ms4,
        reply_markup=keyboard.as_markup(),
    )
