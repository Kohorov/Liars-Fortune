from i18n import t
from db_compat import connect_db, DBError, IntegrityError
from logger import logger
import uuid
import asyncio
from aiogram import types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from config import *
from keyboards.keyboard import *
from middlewares.registered import admin_required
from db import *
from states.state import (
    AddTournaments,
    EditStartAndEndTimes,
)
from datetime import datetime, timezone, timedelta
from game.game_state import notify_groups


@dp.message(F.text == "🏆 tournaments")
@admin_required()
async def tournaments_admin_panel(message: types.Message):
    await message.answer(
        f"You are in tournaments section. \nPlease choose on of these options 👇",
        reply_markup=tournaments_admin_panel_button,
    )


@dp.message(F.text == "🚫 delete this tournament")
@admin_required()
async def deleteeee_tourinit(message: types.Message, state: FSMContext):
    ongoing_tournament = get_ongoing_tournaments()
    if ongoing_tournament:
        tournament = ongoing_tournament[0]
        nop = get_current_players(tournament["name"])
        tournament_id = tournament["name"]
        response = (
            f"🌟 Tournament ID: {tournament['id']}\n\n"
            f"🗓 Started: {tournament['start_time']}\n"
            f"🏁 Ends: {tournament['end_time']}\n\n"
            f"👥 Registered Players: {nop}\n"
            f"🏆 Prize: \n\n{tournament['prize']}\n\n"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Yes", callback_data=f"confirm_delete:{tournament_id}"
                    ),
                    InlineKeyboardButton(text="❌ No", callback_data="cancel_delete"),
                ]
            ]
        )
        await message.answer(response, reply_markup=keyboard)
    else:
        await message.reply("There is no upcoming tournament to delete.")


@dp.message(F.text == "back to tournaments panel 🔙")
@admin_required()
async def back_to_tournaments_section(message: types.Message, state: FSMContext):
    await message.answer(
        f"You are in tournaments section. \nPlease choose on of these options.",
        reply_markup=tournaments_admin_panel_button,
    )
    await state.clear()


@dp.message(F.text == "⚡️ Ongoing")
@admin_required()
async def ongoing_tournaments_sekshn(message: types.Message):
    ongoing_tournaments = get_ongoing_tournaments()
    if not ongoing_tournaments:
        await message.answer(
            f"There are no ongoing tournaments 🤷‍♂️",
            reply_markup=tournaments_admin_panel_button,
        )
        return
    await message.answer(
        f"Here what you can do with ongoing tournaments.",
        reply_markup=ongoing_tournaments_button,
    )


@dp.message(F.text == "⏳ Upcoming")
@admin_required()
async def upcoming_tournaments_sekshn(message: types.Message):
    turnir = get_upcoming_tournaments()

    if not turnir:
        await message.answer(
            f"There are no upcoming tournaments 🤷‍♂️",
            reply_markup=tournaments_admin_panel_button,
        )
        return

    response = "🌟 *Upcoming Tournaments:*\n\n"
    for tournament in turnir:
        # escaped: free-text prizes with _ or * broke the Markdown message
        response += (
            f"🌟 Tournament ID: *{tournament['id']}*\n"
            f"🗓 Starts: {md_escape(tournament['start_time'])}\n"
            f"🏁 Ends: {md_escape(tournament['end_time'])}\n\n"
            f"🏆 Prizes: \n\n{md_escape(tournament['prize'])}\n\n"
        )
    await message.answer(
        response,
        parse_mode="Markdown",
        reply_markup=upcoming_tournaments_button,
    )


@dp.message(F.text == "🗂 Archive")
@admin_required()
async def archive_tournaments_sekcsh(message: types.Message):
    tournaments = get_tournament_archive()
    if not tournaments:
        await message.answer(
            "No tournaments in the archive.",
            reply_markup=tournaments_admin_panel_button,
        )
        return

    response = "📑 *Tournament Archive:*\n\n"
    for tournament in tournaments:
        response += f"🏆 ID: {tournament['id']}\n🌟 Started: {md_escape(tournament['start_time'])}\n📅 Ended: {md_escape(tournament['end_time'])}\n🥇 Winner: {md_escape(get_user_nfgame(tournament['winner']) if tournament['winner'] else '-')} ({md_escape(tournament['winner'])})\n\n"
    await message.answer(response, parse_mode="Markdown")


@dp.message(F.text == "➕ create a new Tournament")
@admin_required()
async def create_a_new_truine(message: types.Message, state: FSMContext):
    turnir = get_upcoming_tournaments()
    if turnir:
        await message.answer(
            f"⚠️ There is upcoming tournament and you can not create a new one unless you delete it.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    await message.answer(
        f"You are creating a new tournament ❗️\nPlease enter the tournament start date (YYYY-MM-DD HH:MM)",
        reply_markup=back_to_tournaments_button,
    )
    await state.set_state(AddTournaments.turnir_start_date)


@dp.message(AddTournaments.turnir_start_date)
async def set_tournament_start_date(message: types.Message, state: FSMContext):
    if message.text == "back to tournaments panel 🔙":
        await message.answer(
            f"You are in tournaments section.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    try:
        start_date = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M")
        # tournament times are Uzbekistan time; datetime.now() is server-local
        if start_date <= uz_now():
            await message.answer(
                "The tournament start date must be in the future.",
                reply_markup=back_to_tournaments_button,
            )
            return
        await state.update_data(tournament_start=start_date)
        await message.answer(
            "Please enter the tournament end date (YYYY-MM-DD HH:MM):",
            reply_markup=back_to_tournaments_button,
        )
        await state.set_state(AddTournaments.turnir_end_date)
    except ValueError:
        await message.answer(
            "Invalid date format. Please use YYYY-MM-DD HH:MM.",
            reply_markup=back_to_tournaments_button,
        )


@dp.message(AddTournaments.turnir_end_date)
async def set_tournament_end_date(message: types.Message, state: FSMContext):
    if message.text == "back to tournaments panel 🔙":
        await message.answer(
            f"You are in tournaments section.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    try:
        end_date = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M")
        data = await state.get_data()
        start_date = data["tournament_start"]
        if end_date <= start_date:
            await message.answer(
                "The tournament end date must be after the start date.",
                reply_markup=back_to_tournaments_button,
            )
            return
        await state.update_data(tournament_end=end_date)
        await message.answer(
            "Please enter the tournament prize:",
            reply_markup=back_to_tournaments_button,
        )
        await state.set_state(AddTournaments.turnir_prize)
    except ValueError:
        await message.answer(
            "Invalid date format. Please use YYYY-MM-DD HH:MM.",
            reply_markup=back_to_tournaments_button,
        )


@dp.message(AddTournaments.turnir_prize)
async def set_tournament_prize(message: types.Message, state: FSMContext):
    if message.text == "back to tournaments panel 🔙":
        await message.answer(
            "You are in tournaments section.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    if not message.text:
        await message.answer("Please send the prize as text.")
        return
    await state.update_data(prize=message.text)
    data = await state.get_data()
    unique_id = f"{uuid.uuid4().hex}"
    await state.update_data(tournament_link=unique_id)
    save_tournament_to_db(data, unique_id)
    await message.answer(
        f"✅ Tournament created successfully:\n\n"
        f"🕹 Start: {data['tournament_start']}\n"
        f"🔚 End: {data['tournament_end']}\n\n"
        f"🏆 Prize: \n{data['prize']}\n\n"
        f"🔗 tournament id: {unique_id}",
        reply_markup=admin_panel_button,
    )
    await state.clear()


def save_tournament_to_db(data, tournamnet_link):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO tournaments_table (
                tournament_start_time, 
                tournament_end_time, 
                tournament_prize, 
                tournament_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                data["tournament_start"].strftime("%Y-%m-%d %H:%M"),
                data["tournament_end"].strftime("%Y-%m-%d %H:%M"),
                data["prize"],
                tournamnet_link,
            ),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
    finally:
        conn.close()


@dp.message(F.text == "📝 edit starting")
@admin_required()
async def edit_start_and_end_times(message: types.Message, state: FSMContext):
    tournaments = get_upcoming_tournaments()
    if not tournaments:
        await message.answer(
            "No upcoming tournaments available to edit.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    await state.clear()
    tournament = tournaments[0]
    await state.update_data(tournament_id=tournament["name"])
    await message.answer(
        f"Editing the START time  for tournament.\n\n"
        f"📅 Current Start time: {tournament['start_time']}\n\n"
        "Please enter the new *start date* in the format `YYYY-MM-DD HH:MM`:",
        parse_mode="Markdown",
        reply_markup=back_to_tournaments_button,
    )
    await state.set_state(EditStartAndEndTimes.new_start_date)


@dp.message(EditStartAndEndTimes.new_start_date)
async def set_new_start_date(message: types.Message, state: FSMContext):
    if message.text == "back to tournaments panel 🔙":
        await message.answer(
            f"You are in tournaments section.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    new_start_date = message.text.strip()
    try:
        parsed_start = datetime.strptime(new_start_date, "%Y-%m-%d %H:%M")
        if parsed_start <= uz_now():
            await message.answer(
                "The tournament start date must be in the future.",
                reply_markup=back_to_tournaments_button,
            )
            return
    except ValueError:
        await message.answer(
            "Invalid date format. Please use `YYYY-MM-DD HH:MM`. Try again.",
            reply_markup=back_to_tournaments_button,
        )
        return
    await state.update_data(new_start_date=new_start_date)
    tournaments = get_upcoming_tournaments()
    tournament = tournaments[0]
    await message.answer(
        f"📅 Current End time: {tournament['end_time']}.\n\nNow, enter the new *end date* in the format `YYYY-MM-DD HH:MM`:",
        parse_mode="Markdown",
        reply_markup=back_to_tournaments_button,
    )
    await state.set_state(EditStartAndEndTimes.new_end_date)


@dp.message(EditStartAndEndTimes.new_end_date)
async def set_new_end_date(message: types.Message, state: FSMContext):
    if message.text == "back to tournaments panel 🔙":
        await message.answer(
            f"You are in tournaments section.",
            reply_markup=tournaments_admin_panel_button,
        )
        await state.clear()
        return
    new_end_date = message.text.strip()
    try:
        parsed_end = datetime.strptime(new_end_date, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer(
            "Invalid date format. Please use `YYYY-MM-DD HH:MM`. Try again.",
            reply_markup=back_to_tournaments_button,
        )
        return

    data = await state.get_data()
    tournament_id = data["tournament_id"]
    new_start_date = data["new_start_date"]
    parsed_start = datetime.strptime(new_start_date, "%Y-%m-%d %H:%M")
    if parsed_end <= parsed_start:
        await message.answer(
            "The tournament end date must be after the start date.",
            reply_markup=back_to_tournaments_button,
        )
        return
    update_start_and_end_dates(tournament_id, new_start_date, new_end_date)
    await message.answer(
        f"✅ Start and end times for the tournament have been updated!\n\n"
        f"🗓 Start: {new_start_date}\n"
        f"🗓 End: {new_end_date}",
        reply_markup=tournaments_admin_panel_button,
    )
    await state.clear()


def update_start_and_end_dates(tournament_id: str, start_date: str, end_date: str):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE tournaments_table
            SET tournament_start_time = ?, tournament_end_time = ?
            WHERE tournament_id = ?
            """,
            (start_date, end_date, tournament_id),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
    finally:
        conn.close()


@dp.callback_query(lambda c: c.data == "start_tournament_k")
async def start_turninr(callback_query: types.CallbackQuery):
    try:
        await bot.delete_message(
            chat_id=callback_query.from_user.id,
            message_id=callback_query.message.message_id,
        )
    except Exception:
        pass
    ongoing = get_ongoing_tournaments()
    if not ongoing:  # used to raise IndexError
        await callback_query.answer("There is no ongoing tournament.", show_alert=True)
        return
    turnir = ongoing[0]
    tournament_id = turnir["name"]
    # a second press created a second set of round-1 groups and games
    if tournament_id in _starting_tournaments or get_current_round_number(tournament_id) != "0":
        await callback_query.answer("This tournament has already started.", show_alert=True)
        return
    _starting_tournaments.add(tournament_id)
    try:
        await _start_tournament(callback_query, tournament_id)
    finally:
        _starting_tournaments.discard(tournament_id)


_starting_tournaments = set()


async def _start_tournament(callback_query, tournament_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tournament_id, tournament_start_time FROM tournaments_table WHERE tournament_id = ?",
        (tournament_id,),
    )
    tournament = cursor.fetchone()
    if not tournament:
        await callback_query.message.answer(
            f"Tournament with ID {tournament_id} not found.",
            reply_markup=tournaments_admin_panel_button,
        )
        return
    tournament_name, start_time = tournament
    uzbekistan_time = datetime.now(timezone.utc) + timedelta(hours=5)
    try:
        start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc
        )

    if uzbekistan_time < start_time:
        await callback_query.message.answer(
            "Tournament cannot start before the scheduled time.",
            reply_markup=tournaments_admin_panel_button,
        )
        return

    cursor.execute(
        "SELECT user_id FROM tournament_users WHERE tournament_id = ?", (tournament_id,)
    )
    participants = [row[0] for row in cursor.fetchall()]
    conn.close()
    if len(participants) < 2:
        await callback_query.message.answer(
            "Not enough participants to start the tournament.",
            reply_markup=tournaments_admin_panel_button,
        )
        return
    await notify_participants(participants, len(participants))
    await asyncio.sleep(5)
    round_number = 1
    groups = create_groups(participants)
    for nk in range(len(groups)):
        for jk in groups[nk]:
            save_tournament_round_info(tournament_id, round_number, jk, nk + 1)
    await notify_groups(groups, round_number)


async def notify_participants(participants, num_participants):
    for user_id in participants:
        try:
            ln = get_user_language(user_id)
            ims = t("the_tournament_is_starting_now", ln, p0=num_participants)
            await safe_send(chat_id=user_id, text=ims)
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")


@dp.message(F.text == "✅ start the tournament")
@admin_required()
async def show_upcoming_tournaments(message: types.Message):
    users = get_all_user_ids()
    tournaments = get_ongoing_tournaments()
    if not tournaments:
        return
    tournament = tournaments[0]
    if get_tournament_status(tournament["name"]):
        await message.answer(f"You have already begun the tournamnet ❗️")
        return
    set_tournament_status(tournament["name"], True)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 Join the Tournament 🔥",
                    callback_data=f"join_tournament:{tournament['name']}",
                )
            ]
        ]
    )
    cnt = 0
    message_list = []
    for user_id in users:
        ln = get_user_language(user_id)
        response = t("the_tournament_is_about_to", ln)

        if user_id == message.from_user.id:
            continue
        try:
            msg = await bot.send_message(
                chat_id=user_id,
                text=response,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            message_list.append([user_id, msg.message_id])
            cnt += 1
        except Exception:
            continue
    await message.answer(
        f"{cnt} players are given invitation link to the tournament ✅\n You will get the button to start the tournamnet in 5 minutes. ⏰"
    )
    await asyncio.sleep(5 * 60)
    for mid in message_list:
        try:
            await bot.delete_message(chat_id=mid[0], message_id=mid[1])
        except Exception:
            continue
    start_button = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶ Start Tournament",
                    callback_data=f"start_tournament_k",
                )
            ]
        ]
    )
    response = (
        f"🌟 *{tournament['id']}*\n\n"
        f"🗓 Started: {md_escape(tournament['start_time'])}\n"
        f"🏁 Ends: {md_escape(tournament['end_time'])}\n\n"
        f"👥 Registered Players: {get_current_players(tournament['name'])}\n\n"
        f"🏆 Prize: \n{md_escape(tournament['prize'])}\n\n"
    )
    await message.answer(
        response,
        reply_markup=start_button,
        parse_mode="Markdown",
    )
