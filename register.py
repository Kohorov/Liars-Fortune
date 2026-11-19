from i18n import t
from logger import logger
from db_compat import connect_db, DBError, IntegrityError
from config import bot, dp
from aiogram import types
from aiogram.fsm.context import FSMContext
from states.state import registration, registration_game
from keyboards.keyboard import get_main_menu, kb_variant
from keyboards.inline import *
from game.group import JOIN_PREFIX, join_from_link
from db import (
    register_user,
    is_user_registered,
    insert_invitation,
    get_game_inviter_id,
    get_player_count,
    get_needed_players,
    get_game_id_by_user,
    get_game_inviter_id,
    is_name_valid,
    get_unity_coin_referral,
    get_user_language,
)
def add_user(user_id, referred_by):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users_referral (user_id, referred_by) VALUES (?, ?)",
        (user_id, referred_by),
    )
    conn.commit()
    inserted = cursor.rowcount > 0
    conn.close()
    return inserted


@dp.message(registration.pref_name)
async def get_name_fem(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    
    user_data = await state.get_data()
    payload = user_data.get("payload", "")
    if not message.text:  # sticker/photo: .strip() on None crashed the handler
        await message.answer(t("username_invalid", ln))
        return
    preferred_name = message.text.strip()
    m1 = t("please_enter_your_username_first", ln)
    m2 = t("username_invalid", ln)
    m3 = t("username_taken", ln)
    m4 = t("congratulations_on_successfully_registering_p0", ln, p0=preferred_name)
    if "/start" in message.text:
        await message.answer(m1)
        return
    h = is_name_valid(preferred_name)
    if not h:
        await message.answer(m2)
    elif h == 2:
        await message.answer(m3)
    else:
        user = message.from_user
        register_user(
            user.id, user.username, user.first_name, user.last_name, preferred_name
        )
        await message.answer(m4, reply_markup=get_main_menu(message.from_user.id))
        if payload.startswith(JOIN_PREFIX):
            # came from a group lobby's Join button: seat them now
            await state.clear()
            await join_from_link(message.from_user.id, payload[len(JOIN_PREFIX):])
            return
        if payload.isdigit() and int(payload) != message.from_user.id:
            try:
                referred_by = int(payload)
                if not is_user_registered(referred_by):
                    raise ValueError(f"referrer {referred_by} is not a registered user")
                if not add_user(message.from_user.id, referred_by):
                    raise ValueError("referral already recorded")
                u_coin = get_unity_coin_referral()
                conn = connect_db()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users_database SET unity_coin = unity_coin + ? WHERE user_id = ?",
                    (u_coin, referred_by),
                )
                conn.commit()
                conn.close()
                ln = get_user_language(referred_by)
                ms = t("p0_has_successfully_registered_via", ln, p0=preferred_name, p1=u_coin)
                await bot.send_message(chat_id=referred_by, text=ms)
            except Exception as e:
                logger.warning(f"Referral bonus failed for payload {payload}: {e}")
        await state.clear()


@dp.message(registration_game.pref1_name)
async def get_name(message: types.Message, state: FSMContext):
    ln = get_user_language(message.from_user.id)
    if not message.text:
        await message.answer(t("username_invalid", ln))
        return
    preferred_name = message.text.strip()
    m1 = t("please_enter_your_username_first", ln)
    m2 = t("username_invalid", ln)
    m3 = t("username_taken", ln)
    m4 = t("congratulations_on_successfully_registering_p0_2", ln, p0=preferred_name)
    m5 = t("no_game_found_with_that", ln)
    m6 = t("already_in_game_as_creator", ln)
    m7 = t("already_in_game", ln)
    user_data = await state.get_data()
    payload = user_data.get("payload", "")
    if "/start" in message.text:
        await message.answer(m1)
        return
    if payload.startswith("game_"):
        game_id = payload.split("game_")[1]
        inviter_id = get_game_inviter_id(game_id)
        user = message.from_user
        h = is_name_valid(preferred_name)
        if not h:
            await message.answer(m2)
        elif h == 2:
            await message.answer(m3)
        else:
            register_user(
                user.id, user.username, user.first_name, user.last_name, preferred_name
            )
            # the user is registered from here on, so every exit must leave the
            # registration state (it used to trap them in this handler)
            await state.clear()
            if not inviter_id:
                await message.answer(
                    m5, reply_markup=get_main_menu(message.from_user.id)
                )
                return
            if game_id == get_game_id_by_user(message.from_user.id):
                if message.from_user.id == get_game_inviter_id(game_id):
                    await message.answer(
                        m6, reply_markup=get_main_menu(message.from_user.id)
                    )
                else:
                    await message.answer(m7)
                return
            if get_player_count(game_id) == 0:
                ms = t("game_finished_or_stopped", ln)
                await message.answer(
                    ms, reply_markup=get_main_menu(message.from_user.id)
                )
                return

            if get_needed_players(game_id) <= get_player_count(game_id):
                ms = t("no_space_in_game", ln)
                await message.answer(
                    ms, reply_markup=get_main_menu(message.from_user.id)
                )

                await state.clear()
                return
            insert_invitation(inviter_id, user.id, game_id)
            player_count = get_player_count(game_id)
            ms = t("you_have_successfully_joined_the", ln, p0=player_count)
            await message.answer(f"{m4}\n\n{ms}", reply_markup=get_main_menu(message.from_user.id))
            ln1 = get_user_language(inviter_id)
            ms1 = t("player_p0_has_joined_the", ln1, p0=preferred_name, p1=player_count)
            await bot.send_message(inviter_id, ms1)
            ms = t("all_players_ready", ln1)
            kb = kb_variant(ln1, en=start_stop_game, ru=start_stop_game_ru, uz=start_stop_game_uz)
            if get_needed_players(game_id) == get_player_count(game_id):
                await bot.send_message(inviter_id, ms, reply_markup=kb)

            await state.clear()
    else:
        await message.answer(t("invalid_game_link", ln))
