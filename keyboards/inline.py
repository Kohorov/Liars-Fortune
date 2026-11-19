from i18n import t
from db_compat import connect_db, DBError, IntegrityError
from logger import logger
import asyncio
import random
from config import bot, dp, F
from keyboards.keyboard import get_main_menu
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.handlers import CallbackQueryHandler
from db import *
from game.game_state import (
    send_random_cards_to_players,
    get_current_turn_user_id,
    get_next_player_id,
    eliminate_player,
    _game_lock,
)

# games whose start countdown is running (is_started is only set after it)
_starting_games = set()
from datetime import datetime, timezone, timedelta

start_stop_game = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Start the game ✅", callback_data="start_game"),
        ],
        [
            InlineKeyboardButton(text="Delete the game 🚫", callback_data="stop_game"),
        ],
    ]
)

start_stop_game_uz = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="O'yinni boshlash ✅", callback_data="start_game"
            ),
        ],
        [
            InlineKeyboardButton(
                text="O'yinni o'chirib tashlash 🚫", callback_data="stop_game"
            ),
        ],
    ]
)

start_stop_game_ru = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Начать игру ✅", callback_data="start_game"),
        ],
        [
            InlineKeyboardButton(text="Удалить игру 🚫", callback_data="stop_game"),
        ],
    ]
)


# cancel_g = InlineKeyboardMarkup(
#     inline_keyboard=[
#         [
#             InlineKeyboardButton(text="quit game 🚀", callback_data="cancel_game"),
#         ]
#     ]
# )


@dp.callback_query(lambda c: c.data == "start_game")
async def inline_star_game_inline(callback_query: types.CallbackQuery):
    game_id = get_game_id_by_user(callback_query.from_user.id)
    # A second "all players ready" message (player left and rejoined) or a
    # double tap used to restart a running game: redealing cards and bullets.
    if (
        not game_id
        or callback_query.from_user.id != get_game_inviter_id(game_id)
        or is_game_started(game_id)
        or game_id in _starting_games
    ):
        await callback_query.answer(
            t("game_finished_or_stopped", get_user_language(callback_query.from_user.id)),
            show_alert=True,
        )
        return
    try:
        await bot.delete_message(
            callback_query.from_user.id, callback_query.message.message_id
        )
    except Exception:
        pass
    gn = get_needed_players(game_id)
    gp = get_player_count(game_id)
    suits = ["heart ❤️", "diamond ♦️", "spade ♠️", "club ♣️"]
    current_table = random.choice(suits)
    global cur_table
    cur_table = set_current_table(game_id, current_table)
    ln = get_user_language(callback_query.from_user.id)
    if gn == gp:
        _starting_games.add(game_id)
        players = get_all_players_in_game(game_id)
        ms1 = t("game_starts_in", ln)
        ms2 = "3️⃣"
        tasks = []
        cr_id = get_game_creator_id(game_id)
        players.remove(cr_id)
        for player in players:
            if player is None:
                continue
            reset_exclusion_count(game_id, player)
            create_game_record_if_not_exists(game_id, player)
            tasks.append(send_game_start_messages(player, ms1, ms2, len(players)))
        create_game_record_if_not_exists(game_id, cr_id)
        if callback_query.from_user.id is None:
            await callback_query.answer("Invalid creator ID.", show_alert=True)
            return
        creator_sec = await bot.send_message(callback_query.from_user.id, ms1)
        creator_msg = await bot.send_message(callback_query.from_user.id, ms2)
        await asyncio.gather(
            periodically_edit_message(
                callback_query.from_user.id,
                creator_msg.message_id,
                creator_sec.message_id,
                len(players) + 1,
                cur_table,
                interval=1,
            ),
            *tasks,
        )
        _starting_games.discard(game_id)
        arr = [i for i in get_all_players_in_game(game_id) if i]
        for play in arr:
            set_real_bullet_for_player(game_id, play)
        set_current_turn(game_id, random.choice(arr))
        save_player_cards(game_id)
        await send_random_cards_to_players(game_id)
        await callback_query.answer()
    else:
        dif = gn - gp
        ms1 = t("p0_players_are_needed_to", ln, p0=dif)
        await bot.send_message(callback_query.from_user.id, ms1)
        return


async def send_game_start_messages(player_id, ms1, ms2, lent):
    sec = await bot.send_message(player_id, ms1)
    msg = await bot.send_message(player_id, ms2)
    await periodically_edit_message(
        player_id, msg.message_id, sec.message_id, lent + 1, cur_table, interval=1
    )


# def generate_exclude_keyboard(game_id):
#     with connect_db() as conn:
#         cursor = conn.cursor()
#         cursor.execute(
#             """
#             SELECT invitee_id, (SELECT nfgame FROM users_database WHERE user_id = invitee_id) AS player_name
#             FROM invitations
#             WHERE game_id = ? AND invitee_id IS NOT NULL
#             """,
#             (game_id,),
#         )
#         players = cursor.fetchall()

#     if not players:
#         return InlineKeyboardMarkup(
#             inline_keyboard=[
#                 [
#                     InlineKeyboardButton(
#                         text="Delete the game 🚫", callback_data="stop_game"
#                     )
#                 ]
#             ],
#         )

#     keyboard = InlineKeyboardMarkup(
#         inline_keyboard=[
#             [
#                 InlineKeyboardButton(
#                     text=f"Exclude {player_name} 🚀",
#                     callback_data=f"exclude_player:{invitee_id}",
#                 )
#             ]
#             for invitee_id, player_name in players
#         ]
#         + [
#             [InlineKeyboardButton(text="Delete the game 🚫", callback_data="stop_game")]
#         ],
#     )

#     return keyboard


@dp.callback_query(lambda c: c.data == "stop_game")
async def can_game(callback_query: types.CallbackQuery):
    user = callback_query.from_user
    with connect_db() as conn:
        ln = get_user_language(user.id)
        ms1 = t("you_are_not_currently_the", ln)
        ms3 = t("you_have_canceled_the_game", ln)
        cursor = conn.cursor()
        game_id = get_game_id_by_user(user.id)
        if not game_id or get_game_inviter_id(game_id) != user.id:
            await callback_query.answer(ms1)
            return
        increase_exclusion_count(game_id, user.id)
        cursor.execute(
            "SELECT invitee_id FROM invitations WHERE game_id = ?", (game_id,)
        )
        players = cursor.fetchall()
        for player in players:
            player_id = player[0]
            if player_id is not None:
                ln = get_user_language(player_id)
                ms2 = t("the_game_has_been_stopped", ln)
                update_game_details(game_id, player_id, None)
                delete_user_from_all_games(player_id)
                try:
                    await bot.send_message(
                        player_id, ms2, reply_markup=get_main_menu(player_id)
                    )
                except Exception as e:
                    logger.error(f"Error sending message to player {player_id}: {e}")
        # the old "game_id = (SELECT ...)" subquery raised CardinalityViolation
        # whenever the creator had more than one lobby row
        cursor.execute("DELETE FROM invitations WHERE game_id = ?", (game_id,))
        conn.commit()
        delete_game(game_id)
        update_game_details(game_id, callback_query.from_user.id, None)
        await callback_query.message.answer(
            ms3, reply_markup=get_main_menu(callback_query.from_user.id)
        )
        await delete_all_game_messages(game_id)
        await callback_query.answer()


# async def player_quit_game(user_id, game_id, inviter_id):
#     with connect_db() as conn:
#         cursor = conn.cursor()
#         update_game_details(game_id, user_id, None)
#         cursor.execute(
#             "DELETE FROM invitations WHERE invitee_id = ? AND game_id = ?",
#             (user_id, game_id),
#         )
#         conn.commit()
#         cursor.execute(
#             "SELECT nfgame FROM users_database WHERE user_id = ?", (user_id,)
#         )

#         player_name = cursor.fetchone()
#         if player_name:
#             player_name = get_user_nfgame(user_id)
#             try:
#                 await bot.send_message(
#                     inviter_id,
#                     f"Player {player_name} has quit the game.\nPlayers left in the game: {get_player_count(game_id)}",
#                 )
#             except Exception as e:
#                 logger.error(f"Error sending message to creator {inviter_id}: {e}")


stop_incomplete_games = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Stop/leave current game 🛑", callback_data="stop_incomplete_games"
            )
        ]
    ]
)
stop_incomplete_games_uz = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Davom etayotgan o'yinni tark etish/to'xtatish 🛑",
                callback_data="stop_incomplete_games",
            )
        ]
    ]
)
stop_incomplete_games_ru = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Остановить/покинуть текущую игру 🛑",
                callback_data="stop_incomplete_games",
            )
        ]
    ]
)


@dp.callback_query(lambda c: c.data == "stop_incomplete_games")
async def handle_stop_incomplete_games(callback_query: types.CallbackQuery):
    try:
        await bot.delete_message(
            callback_query.from_user.id, callback_query.message.message_id
        )
    except Exception:
        pass  # double tap or message too old: the work below is idempotent
    user_id = callback_query.from_user.id
    games = get_games_by_user(user_id)
    ln = get_user_language(user_id)
    ms1 = t("you_have_no_incomplete_games", ln)
    ms4 = t("your_incomplete_games_have_been", ln)
    if not games:
        await callback_query.message.answer(ms1, reply_markup=get_main_menu(user_id))
        await callback_query.answer()
        return
    for game in games:
        creator_id = get_game_inviter_id(game["game_id"])
        if user_id == creator_id:
            players = [i for i in get_all_players_in_game(game["game_id"]) if i]
            delete_game(game["game_id"])
            for player_id in players:
                delete_user_from_all_games(player_id)
                await delete_user_messages(game["game_id"], player_id)
                ln = get_user_language(player_id)
                ms2 = t("the_game_has_been_stopped_2", ln)
                try:
                    await bot.send_message(
                        player_id,
                        ms2,
                        reply_markup=get_main_menu(player_id),
                    )
                except Exception as e:
                    logger.error(f"Failed to send message to player {player_id}: {e}")
        elif is_game_started(game["game_id"]):
            # Leaving a running game used to just delete the seat: if it was the
            # leaver's turn the game froze, and a last remaining player never won.
            update_game_details(game["game_id"], user_id, None)
            async with _game_lock(game["game_id"]):
                await eliminate_player(game["game_id"], user_id, voluntary=True)
            continue
        else:
            update_game_details(game["game_id"], user_id, None)
            delete_user_from_all_games(user_id)
            try:
                ln = get_user_language(creator_id)
                ms3 = t("a_player_p0_has_left", ln, p0=get_user_nfgame(callback_query.from_user.id), p1=get_player_count(get_game_id_by_user(creator_id)))
                await bot.send_message(
                    creator_id, ms3, reply_markup=get_main_menu(creator_id)
                )
            except Exception as e:
                logger.error(f"Failed to send message to creator {creator_id}: {e}")
    await callback_query.message.answer(
        ms4,
        reply_markup=get_main_menu(callback_query.from_user.id),
    )
    for game in games:
        if user_id == game["creator_id"]:
            await delete_all_game_messages(game["game_id"])
        else:
            await delete_user_messages(game["game_id"], user_id)
    await callback_query.answer()


# @dp.callback_query(lambda c: c.data.startswith("exclude_player:"))
# async def exclude_player_querriy(callback_query: types.CallbackQuery):
#     # await bot.delete_message(
#     #     callback_query.from_user.id, callback_query.message.message_id
#     # )
#     user = callback_query.from_user
#     data = callback_query.data.split(":")
#     if len(data) != 2:
#         await callback_query.answer("Invalid data.")
#         return
#     player_to_remove = int(data[1])

#     game_id = get_game_id_by_user(user.id)
#     increase_exclusion_count(game_id, user.id)

#     with connect_db() as conn:
#         cursor = conn.cursor()
#         cursor.execute(
#             "SELECT inviter_id FROM invitations WHERE game_id = ? AND invitee_id IS NULL",
#             (game_id,),
#         )
#         inviter_id = cursor.fetchone()
#         if not inviter_id or inviter_id[0] != user.id:
#             await callback_query.answer("Only the game creator can exclude players.")
#             return
#         if is_game_started(game_id) and is_user_turn(player_to_remove, game_id):
#             await bot.send_message(
#                 chat_id=user.id,
#                 text=f"Now it's {get_user_nfgame(player_to_remove)}'s turn❗️\nYou can not exclude this player when it is his turn.",
#             )
#             return
#         cursor.execute(
#             "DELETE FROM invitations WHERE invitee_id = ? AND game_id = ?",
#             (player_to_remove, game_id),
#         )
#         conn.commit()
#         update_game_details(game_id, player_to_remove, None)
#         winner = get_alive_number(game_id)
#         if winner != 0 and is_game_started(game_id):
#             await bot.send_message(
#                 chat_id=winner,
#                 text=f"Game has finished. \nYou are winner. 🥳🥳🥳🥳🥳\nConguratulation on winning in the game. \n🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉",
#                 reply_markup=get_main_menu(winner),
#             )
#             update_game_details(
#                 game_id, winner, get_user_nfgame(winner) + " - " + str(winner)
#             )
#             conn = connect_db()
#             cursor = conn.cursor()
#             cursor.execute(
#                 """
#                 SELECT user_id
#                 FROM user_game_messages
#                 WHERE game_id = ?
#                 """,
#                 (game_id,),
#             )
#             user_ids = cursor.fetchall()
#             user_ids = list(set([user for user in user_ids]))
#             for users in user_ids:
#                 users = users[0]
#                 if users and is_player_dead(game_id, users):
#                     update_game_details(
#                         game_id, users, get_user_nfgame(winner) + " - " + str(winner)
#                     )
#                     await bot.send_message(
#                         chat_id=users,
#                         text=f"The game in which you died has ended ⭐️\nWinner: {get_user_nfgame(winner)} — {winner} 🏆",
#                     )
#             delete_game(game_id)
#             await delete_all_game_messages(game_id)
#     try:
#         await bot.send_message(
#             player_to_remove,
#             "Game has finished or been stopped by the creator.",
#             reply_markup=get_main_menu(player_to_remove),
#         )
#         await delete_user_messages(game_id, player_to_remove)
#     except Exception as e:
#         logger.error(f"Failed to send message to player {player_to_remove}: {e}")

#     await callback_query.message.edit_text(
#         f"Player excluded successfully. Remaining players: {get_player_count(game_id)}",
#         reply_markup=generate_exclude_keyboard(game_id),
#     )


# user_tournaments_keyboard = InlineKeyboardMarkup(
#     inline_keyboard=[
#         [
#             InlineKeyboardButton(
#                 text="⚡️ Ongoing Tournaments", callback_data="view_ongoing"
#             )
#         ],
#         [
#             InlineKeyboardButton(
#                 text="🌟 Upcoming Tournaments", callback_data="view_upcoming"
#             )
#         ],
#         [
#             InlineKeyboardButton(
#                 text="📑 Tournament Archive", callback_data="view_archive"
#             )
#         ],
#     ]
# )

archive_tournamnets = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📑 Tournaments Archive", callback_data="view_archive"
            )
        ],
    ]
)
@dp.callback_query(lambda c: c.data.startswith("view_"))
async def handle_tournament_action(callback_query: types.CallbackQuery):
    action = callback_query.data.split("_")[1]
    if action == "archive":
        await show_archive_tournaments(callback_query)


# async def show_ongoing_tournaments(callback_query: types.CallbackQuery):
#     tournaments = get_ongoing_tournaments()
#     if not tournaments:
#         await callback_query.answer(
#             "No ongoing tournaments right now 🤷‍♂️",
#             show_alert=True,
#             reply_markup=get_main_menu(callback_query.from_user.id),
#         )
#         return
#     response = "⚡️ *Ongoing Tournaments:*\n\n"
#     for tournament in tournaments:
#         response += f"🏆 {tournament['id']} (Ends: {tournament['end_time']})\n"
#     await callback_query.message.answer(response, parse_mode="Markdown")


async def show_archive_tournaments(callback_query: types.CallbackQuery):
    tournaments = get_tournament_archive()
    ln = get_user_language(callback_query.from_user.id)
    ms = t("no_tournaments_in_the_archive", ln)
    response = t("tournament_archive", ln)
    if not tournaments:
        await callback_query.answer(ms, show_alert=True)
        return

    for tournament in tournaments:
        response += t(
            "tournament_archive_row", ln,
            id=tournament['id'], start=md_escape(tournament['start_time']),
            end=md_escape(tournament['end_time']),
            # escaped: a nickname like john_doe broke the Markdown message
            winner_name=md_escape(get_user_nfgame(tournament['winner']) or "-"),
            winner_id=md_escape(tournament['winner'] or "-"),
        )
    await callback_query.message.answer(response, parse_mode="Markdown")
    await callback_query.answer()


@dp.callback_query(lambda c: c.data.startswith("join_tournament:"))
async def join_tournament(callback_query: types.CallbackQuery):
    tournament_id = callback_query.data.split(":")[1]
    user_id = callback_query.from_user.id
    tournament = get_ongoing_tournaments()
    ln = get_user_language(user_id)
    ms = t("tournament_not_found_or_already", ln)
    ms2 = t("you_are_already_registered_for", ln)
    ms3 = t("you_have_successfully_joined_the_2", ln)
    response = t("you_have_successfully_joined_the_3", ln)
    if not tournament:
        await callback_query.answer(ms, show_alert=True)
        return
    tournament = tournament[0]
    if is_user_in_tournament(tournament_id, user_id):
        await callback_query.answer(ms2, show_alert=True)
        return
    try:
        add_user_to_tournament(tournament_id, user_id)
        await callback_query.answer(ms3)
        message_id = callback_query.message.message_id
        chat_id = callback_query.message.chat.id

        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=response, parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"❌ Error adding user to tournament: {e}")
        await callback_query.answer(
            "❌ Failed to join the tournament. Please try again later.", show_alert=True
        )


@dp.callback_query(lambda c: c.data.startswith("remove_"))
async def confirm_remove_player(callback: types.CallbackQuery):
    player_id = callback.data.split("_")[1]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Yes", callback_data=f"confirm_remove_{player_id}"
                ),
                InlineKeyboardButton(text="❌ No", callback_data="cancel_remove"),
            ],
        ]
    )

    await callback.message.edit_text(
        f"Do you want to remove {get_user_nfgame(int(player_id))} from the tournament?",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "cancel_remove")
async def cancel_remove(callback: types.CallbackQuery):
    await callback.message.edit_text("Player removal canceled ❌")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("bonus_cb_"))
async def claim_bonus(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ln = get_user_language(user_id)
    ms1 = t("you_ve_already_claimed_your", ln)
    # atomic claim: check-then-update paid out twice on a double tap
    if not claim_daily_bonus(user_id):
        await callback.answer(ms1, show_alert=True)
        return
    coins = random.randint(1, 20)
    award_coins(user_id, coins)
    ln = get_user_language(user_id)
    ms1 = t("you_received_p0_coins_come", ln, p0=coins)
    await callback.answer(ms1, show_alert=True)


select_language_button = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="English 🇺🇸", callback_data="lan_en"),
        ],
        [
            InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lan_ru"),
        ],
        [
            InlineKeyboardButton(text="O'zbek 🇺🇿", callback_data="lan_uz"),
        ],
    ]
)

select_language_button_2 = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="English 🇺🇸", callback_data="changelan_en"),
        ],
        [
            InlineKeyboardButton(text="Русский 🇷🇺", callback_data="changelan_ru"),
        ],
        [
            InlineKeyboardButton(text="O'zbek 🇺🇿", callback_data="changelan_uz"),
        ],
    ]
)


def get_username_button(lang: str):
    text = t("instruction", lang)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=text, callback_data="username_rules"),
            ],
        ]
    )


@dp.callback_query(F.data == "username_rules")
async def cancel_remove(callback: types.CallbackQuery):
    ln = get_user_language(callback.from_user.id)

    ms = t("your_username_must_be_unique", ln)

    await callback.answer(ms, show_alert=True)


@dp.callback_query(F.data.startswith("changelan_"))
async def change_language(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    language_code = callback.data.split("_")[1]

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO user_languages (user_id, language) 
        VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
        """,
        (user_id, language_code),
    )
    conn.commit()
    conn.close()

    # Confirmation messages in selected languages
    messages = {
        "en": "✅ Language set to English!",
        "ru": "✅ Язык установлен на русский!",
        "uz": "✅ Til o'zbek tiliga o'zgartirildi!",
    }

    await callback.message.delete()
    await callback.message.answer(
        messages[language_code], reply_markup=get_main_menu(user_id)
    )


def generate_courses_keyboard():
    courses = getall_channels()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for curs in courses:
        curs = list(curs)
        channel_id, channel_link = curs[0], curs[1]
        row = [
            InlineKeyboardButton(
                text=f"{channel_id}", callback_data=f"channel_review:{channel_id}"
            ),
            InlineKeyboardButton(
                text="🚫", callback_data=f"delete_course:{channel_id}"
            ),
        ]
        keyboard.inline_keyboard.append(row)
    return keyboard


@dp.callback_query(F.data.startswith("delete_course:"))
async def delete_course_callback(call: types.CallbackQuery):
    channel_identifier = call.data.split(":")[1]
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM channel_earn WHERE channel_id = ?", (channel_identifier,)
    )
    conn.commit()
    conn.close()
    await call.answer("Channel has been successfully deleted ✅", show_alert=True)

    keyboard = generate_courses_keyboard()
    await call.message.edit_reply_markup(reply_markup=keyboard)


@dp.callback_query(F.data.startswith("channel_review:"))
async def view_course_callbackfef(call: types.CallbackQuery):
    chid = call.data.split(":")[1]
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT channel_link FROM channel_earn WHERE channel_id = ?",
        (chid,),
    )
    chn = cursor.fetchall()
    conn.close()
    if not chn:
        await call.answer("Channel not found (already deleted).", show_alert=True)
        return
    await call.message.answer(chn[0][0])
    await call.answer()


# @dp.callback_query(lambda c: c.data == "cancel_game")
# async def handle_quit_game(callback_query: types.CallbackQuery):
#     await bot.delete_message(
#         callback_query.from_user.id, callback_query.message.message_id
#     )
#     user = callback_query.from_user
#     with connect_db() as conn:
#         cursor = conn.cursor()
#         game_id = get_game_id_by_user(user.id)
#         increase_exclusion_count(game_id, user.id)
#         if not game_id:
#             await callback_query.answer("You are not currently in any game.")
#             return
#         if has_incomplete_games(user.id):
#             if (
#                 is_user_in_game(game_id, user.id)
#                 and get_current_turn_user_id(game_id) == user.id
#             ):
#                 await callback_query.message.answer(
#                     f"Now it is your turn! You can't leave the game at that time🙅‍♂️"
#                 )
#                 return
#             update_game_details(game_id, user.id, None)
#             cursor.execute(
#                 "DELETE FROM invitations WHERE invitee_id = ? AND game_id = ?",
#                 (user.id, game_id),
#             )
#             conn.commit()
#             inviter_id = get_game_inviter_id(game_id)
#             await player_quit_game(user.id, game_id, inviter_id)
#             await callback_query.message.answer(
#                 f"You have quit the current game.",
#                 reply_markup=get_main_menu(callback_query.from_user.id),
#             )
#             await delete_user_messages(game_id, user.id)
#             delete_user_from_all_games(user.id)
#             winner = get_alive_number(game_id)
#             if winner != 0 and is_game_started(game_id):
#                 await bot.send_message(
#                     chat_id=winner,
#                     text=f"Game has finished. \nYou are winner. 🥳🥳🥳🥳🥳\nConguratulation on winning in the game. \n🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉",
#                     reply_markup=get_main_menu(winner),
#                 )
#                 update_game_details(
#                     game_id, winner, get_user_nfgame(winner) + " - " + str(winner)
#                 )
#                 conn = connect_db()
#                 cursor = conn.cursor()
#                 cursor.execute(
#                     """
#                     SELECT user_id
#                     FROM user_game_messages
#                     WHERE game_id = ?
#                     """,
#                     (game_id,),
#                 )
#                 user_ids = cursor.fetchall()
#                 user_ids = list(set([user for user in user_ids]))
#                 for users in user_ids:
#                     users = users[0]
#                     if users and is_player_dead(game_id, users):
#                         update_game_details(
#                             game_id,
#                             users,
#                             get_user_nfgame(winner) + " - " + str(winner),
#                         )
#                         await bot.send_message(
#                             chat_id=users,
#                             text=f"The game in which you died has ended ⭐️\nWinner: {get_user_nfgame(winner)} — {winner} 🏆",
#                         )
#                 delete_game(game_id)
#                 await delete_all_game_messages(game_id)
#         else:
#             await callback_query.message.answer("You have already quit the game.")
