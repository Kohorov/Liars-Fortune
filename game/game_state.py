from i18n import t
from db_compat import connect_db, DBError, IntegrityError
from logger import logger
import asyncio
import html
import random
import uuid
from config import bot, dp, F
from aiogram import types
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from keyboards.keyboard import *
from db import *
from collections import Counter
from game import images

# seconds between game events, so a round reads as a story, not a burst
PAUSE = 2.5


# One lock per game serialises turn actions, so a double tap on "send" or
# "liar" can no longer advance the turn twice or resolve a bluff twice.
_game_locks = {}


def _game_lock(game_id):
    lock = _game_locks.get(game_id)
    if lock is None:
        lock = _game_locks[game_id] = asyncio.Lock()
    return lock


async def safe_send(chat_id: int, **kwargs):
    """Send a message, silently skipping users who blocked the bot."""
    try:
        return await bot.send_message(chat_id=chat_id, **kwargs)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logger.warning(f"Could not send message to {chat_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error sending to {chat_id}: {e}")
        return None


async def _send_and_track(chat_id, game_id, **kwargs):
    msg = await safe_send(chat_id=chat_id, **kwargs)
    if msg:
        save_message(chat_id, game_id, msg.message_id)
    return msg


async def announce_winner_in_group(game_id, winner):
    group_id = get_group_chat_id(game_id)
    if group_id:
        # deliberately NOT saved via save_message: survives end-of-game cleanup
        try:
            await bot.send_photo(
                group_id, BufferedInputFile(images.winner(), "winner.png"),
                caption=t("the_game_in_which_you", get_game_language(game_id),
                          p0=get_user_nfgame(winner), p1=winner),
            )
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            logger.warning(f"Could not announce winner in {group_id}: {e}")


def _mark_dead(game_id, player_id):
    with connect_db() as conn:
        conn.cursor().execute(
            "UPDATE game_state SET life_status = 'dead' WHERE game_id = ? AND player_id = ?",
            (game_id, player_id),
        )


async def _advance_tournament(tournament_id, winner):
    cur_round = int(get_current_round_number(tournament_id))
    await save_round_winner(tournament_id, str(winner), str(winner))
    groups = int(get_number_of_groups_in_round(tournament_id, cur_round))
    winners = int(get_number_of_winners(tournament_id, cur_round))
    if winners == groups and groups != 1:
        await notify_round_results(tournament_id, cur_round)
        await asyncio.sleep(5)
        await start_next_round(tournament_id, cur_round + 1)
    elif groups == 1 and winners == 1:
        await update_tournament_winner_if_round_finished(tournament_id, winner)


async def finish_game(game_id, winner):
    """The single end-of-game path (previously copy-pasted four times):
    notify, archive, tournament progress or coin reward, then cleanup."""
    winner_label = f"{get_user_nfgame(winner)} - {winner}"
    try:
        await bot.send_photo(
            winner, BufferedInputFile(images.winner(), "winner.png"),
            caption=t("game_over_winner", get_user_language(winner)),
            reply_markup=get_main_menu(winner),
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logger.warning(f"Could not send winner photo to {winner}: {e}")
    await announce_winner_in_group(game_id, winner)
    update_game_details(game_id, winner, winner_label)

    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT user_id FROM user_game_messages WHERE game_id = ?",
            (game_id,),
        )
        user_ids = [row[0] for row in cursor.fetchall()]
    for uid in user_ids:
        if uid and is_player_dead(game_id, uid):
            update_game_details(game_id, uid, winner_label)
            await safe_send(
                chat_id=uid,
                text=t("the_game_in_which_you", get_user_language(uid),
                       p0=get_user_nfgame(winner), p1=winner),
            )

    tournament_id = get_tournament_id_by_user(winner)
    if tournament_id and is_user_in_tournament(tournament_id, winner):
        await _advance_tournament(tournament_id, winner)
    # winning a game deliberately earns no coins
    delete_game(game_id)
    await delete_all_game_messages(game_id)


async def eliminate_player(game_id, player_id, voluntary=False):
    """Remove a player from a running game (admin removal or voluntary leave).
    Keeps the turn order valid and ends the game if one player is left."""
    was_turn = is_user_turn(player_id, game_id)
    if was_turn:
        update_current_turn(game_id)  # while the player is still seated
    _mark_dead(game_id, player_id)
    delete_user_from_all_games(player_id)
    name = get_user_nfgame(player_id)
    remaining = get_all_players_in_game(game_id)
    for play in remaining:
        pln = get_user_language(play)
        text = (
            t("a_player_p0_has_left", pln, p0=name, p1=len(remaining))
            if voluntary
            else t("player_p0_excluded_from_game", pln, p0=name)
        )
        await _send_and_track(play, game_id, text=text)
    winner = get_alive_number(game_id)
    if winner:
        await finish_game(game_id, winner)
        return
    if was_turn:
        await reset_game_for_all_players(game_id)


@dp.callback_query(lambda c: c.data.startswith("confirm_remove_"))
async def remove_player_confirm(callback: types.CallbackQuery):
    player_id = int(callback.data.split("_")[2])
    game_id = get_game_id_by_user(player_id)
    await safe_send(
        chat_id=player_id,
        text=t("you_are_elimitanated_from_the", get_user_language(player_id)),
    )
    remove_player(player_id)
    if game_id and is_game_started(game_id):
        async with _game_lock(game_id):
            await eliminate_player(game_id, player_id)
    elif game_id:
        delete_user_from_all_games(player_id)
    await callback.message.edit_text("✅ Player removed successfully.")
    await callback.answer()


def get_current_turn_user_id(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT current_turn_user_id FROM invitations WHERE game_id = ?", (game_id,)
        )
        result = cursor.fetchone()
        return result[0] if result else None


def get_player_cards(game_id, player_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT cards
            FROM game_state
            WHERE game_id = ? AND player_id = ?
            """,
            (game_id, player_id),
        )
        result = cursor.fetchone()
        if result and result[0]:
            return result
        return []


def _turn_keyboard(user_id, cards, is_turn=True):
    ln = get_user_language(user_id)
    keyboard = [[
        InlineKeyboardButton(
            text=card,
            callback_data=f"select_card:{index}:{card}:unselected" if is_turn else "disabled",
        )
        for index, card in enumerate(cards)
    ]]
    if is_turn:
        keyboard.append([InlineKeyboardButton(text=t("send_cards_btn", ln), callback_data="send_cards")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def send_random_cards_to_players(game_id):
    players = get_all_players_in_game(game_id)
    for player_id in players:
        if not player_id or is_player_dead(game_id, player_id):
            continue
        ln = get_user_language(player_id)
        pc = get_player_cards(game_id, player_id)
        if not pc:
            logger.warning(f"No cards dealt to {player_id} in game {game_id}")
            continue
        player_cards = pc[0].split(",")
        is_turn = is_user_turn(player_id, game_id)
        tms = (
            t("now_it_s_your_turn", ln, p0=get_current_table(game_id))
            if is_turn
            else t("wait_turn_cards", ln, p0=get_user_nfgame(get_current_turn_user_id(game_id)))
        )
        await asyncio.sleep(2)
        # safe_send: one player who blocked the bot no longer stops the deal
        await _send_and_track(
            player_id, game_id, text=tms,
            reply_markup=_turn_keyboard(player_id, player_cards, is_turn),
        )


def _selected(keyboard, prefix):
    """Selections live in the message's own buttons, so they can never leak
    between players or games (the old module-wide dicts did both)."""
    return [
        b for row in keyboard for b in row
        if b.callback_data and b.callback_data.startswith(prefix)
        and b.callback_data.endswith(":selected")
    ]


@dp.callback_query(lambda c: c.data.startswith("select_card"))
async def toggle_card_selection(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    game_id = get_game_id_by_user(user_id)
    ln = get_user_language(user_id)
    if not is_user_turn(user_id, game_id):
        await callback_query.answer(t("not_your_turn", ln), show_alert=True)
        return
    _, index, card, current_state = callback_query.data.split(":")
    index = int(index)
    keyboard = callback_query.message.reply_markup.inline_keyboard
    if current_state == "unselected" and len(_selected(keyboard, "select_card:")) >= 3:
        await callback_query.answer(t("you_can_only_select_up", ln), show_alert=True)
        return
    new_state = "selected" if current_state == "unselected" else "unselected"
    button = keyboard[0][index]
    button.text = f"{card} ✅" if new_state == "selected" else card
    button.callback_data = f"select_card:{index}:{card}:{new_state}"
    await callback_query.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback_query.answer(f"Card {card} is now {new_state}.")


def insert_or_update_last_cards(game_id, selected_cards):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM game_state WHERE game_id = ? LIMIT 1", (game_id,))
        if cursor.fetchone():
            cursor.execute(
                "UPDATE game_state SET last_cards = ? WHERE game_id = ?",
                (",".join(selected_cards), game_id),
            )
        else:
            cursor.execute(
                "INSERT INTO game_state (game_id, last_cards) VALUES (?, ?)",
                (game_id, ",".join(selected_cards)),
            )
        conn.commit()


def get_last_cards(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT last_cards
            FROM game_state
            WHERE game_id = ?
            AND last_cards IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (game_id,),
        )
        result = cursor.fetchone()
        return result if result else None


async def _delete_quietly(chat_id, message_id):
    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except TelegramBadRequest:
        return False


@dp.callback_query(lambda c: c.data == "send_cards")
async def send_cards(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    game_id = get_game_id_by_user(user_id)
    ln = get_user_language(user_id)
    if not game_id:
        await callback_query.answer(t("not_your_turn", ln), show_alert=True)
        return
    async with _game_lock(game_id):
        await _send_cards_locked(callback_query, user_id, game_id, ln)


async def _send_cards_locked(callback_query, user_id, game_id, ln):
    if not is_user_turn(user_id, game_id):
        await callback_query.answer(t("not_your_turn", ln), show_alert=True)
        return
    keyboard = callback_query.message.reply_markup.inline_keyboard
    selected_cards = [b.text.replace(" ✅", "") for b in _selected(keyboard, "select_card:")]

    if not selected_cards:
        await callback_query.answer(t("no_cards_selected", ln), show_alert=True)
        return
    pc = get_player_cards(game_id, user_id)
    current_cards = pc[0].split(",") if pc else []
    if Counter(selected_cards) - Counter(current_cards):
        # keyboard from an earlier round: those cards are no longer in hand
        await _delete_quietly(user_id, callback_query.message.message_id)
        await callback_query.answer(t("stale_cards", ln), show_alert=True)
        return

    await _delete_quietly(user_id, callback_query.message.message_id)
    await _send_and_track(
        user_id, game_id,
        text=t("you_sent_the_following_cards", ln, p0=", ".join(selected_cards)),
    )
    remaining_cards = list((Counter(current_cards) - Counter(selected_cards)).elements())
    with connect_db() as conn:
        conn.cursor().execute(
            "UPDATE game_state SET cards = ?, last_cards = ? WHERE game_id = ? AND player_id = ?",
            (",".join(remaining_cards), ",".join(selected_cards), game_id, user_id),
        )
    insert_or_update_last_cards(game_id, selected_cards)
    update_current_turn(game_id)

    players = get_all_players_in_game(game_id)
    actor_id = user_id
    next_player_id = get_next_player_id(game_id, actor_id)
    actor_name = get_user_nfgame(actor_id)
    next_name = get_user_nfgame(next_player_id)

    # one combined update: to the group for group games, else per spectator
    group_id = get_group_chat_id(game_id)
    if group_id:
        gln = get_game_language(game_id)
        # clickable mention so the next player gets a notification
        next_mention = (
            f'<a href="tg://user?id={next_player_id}">{html.escape(next_name or "")}</a>'
        )
        tn = t("turn_update", gln, p0=html.escape(actor_name or ""),
               p1=len(selected_cards), p2=next_mention)
        await _send_and_track(group_id, game_id, text=tn, parse_mode="HTML")
    else:
        for p_id in players:
            if not p_id or p_id == actor_id or p_id == next_player_id:
                continue
            tn = t("turn_update", get_user_language(p_id), p0=actor_name,
                   p1=len(selected_cards), p2=next_name)
            await _send_and_track(p_id, game_id, text=tn)

    nln = get_user_language(next_player_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("continue", nln), callback_data="continue_game"),
        InlineKeyboardButton(text=t("liar", nln), callback_data="liar_game"),
    ]])
    await _send_and_track(
        next_player_id, game_id,
        text=t("your_move", nln, p0=actor_name, p1=len(selected_cards)),
        reply_markup=keyboard,
    )
    await callback_query.answer()


async def _shot_dead_message(game_id, player_id, key):
    await _send_and_track(player_id, game_id, text=t(key, get_user_language(player_id)))
    delete_user_from_all_games(player_id)


@dp.callback_query(lambda c: c.data in ["continue_game", "liar_game"])
async def handle_continue_or_liar(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    game_id = get_game_id_by_user(user_id)
    if not game_id:
        await callback_query.answer()
        return
    async with _game_lock(game_id):
        # the prompt is single-use: if it is already gone this is a double tap
        if not await _delete_quietly(user_id, callback_query.message.message_id):
            await callback_query.answer()
            return
        # answer now: resolving a round takes longer than Telegram's callback window
        await callback_query.answer()
        if callback_query.data == "liar_game":
            await _resolve_liar(game_id, user_id)
        else:
            await _continue_turn(game_id, user_id)


async def _pull_trigger(game_id, player_id, dead_key=None):
    """Spin for one player and show the revolver. Returns True if they died."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT blanks_count FROM game_state WHERE game_id = ? AND player_id = ?",
            (game_id, player_id),
        )
        row = cursor.fetchone()
    pulls = (int(row[0]) if row and row[0] is not None else 0) + 1
    result = await shoot_self(game_id, player_id)
    if result is None:
        return False
    name = get_user_nfgame(player_id)
    if result is True:
        await broadcast_photo(game_id, images.revolver(pulls, dead=True), "bc_shot_dead", name=name)
        if dead_key:
            await _shot_dead_message(game_id, player_id, dead_key)
        return True
    await broadcast_photo(game_id, images.revolver(pulls, dead=False), "bc_shot_blank",
                          name=name, odds=6 - result)
    return False


async def _resolve_liar(game_id, user_id):
    previous_player_id = get_previous_player_id(game_id, user_id)
    last_cards_result = get_last_cards(game_id)
    if not last_cards_result or previous_player_id is None:
        await safe_send(chat_id=user_id, text="Game state error. Please restart the game.")
        return
    previous_player_cards = last_cards_result[0]
    played = previous_player_cards.split(",")
    table_current = get_current_table(game_id).split(" ")[-1]
    all_shoot = played == ["🃏"]
    honest = all(c == table_current or c == "🎴" for c in played)

    if all_shoot:
        await broadcast_photo(game_id, images.reveal(played, table_current, bluff=False),
                              "player_p0_opened_the_last", p0=get_user_nfgame(user_id))
        await asyncio.sleep(PAUSE)
        for player in [p for p in get_all_players_in_game(game_id) if p != previous_player_id]:
            await _pull_trigger(game_id, player, "you_shot_yourself_and_dead")
            winner = get_alive_number(game_id)
            if winner:
                await asyncio.sleep(PAUSE)
                await finish_game(game_id, winner)
                return
            await asyncio.sleep(PAUSE)
        await reset_game_for_all_players(game_id)
        return

    if honest:
        key, shooter, dead_key = "bc_liar_wrong", user_id, "you_shot_yourselef_because_of"
    else:
        key, shooter, dead_key = "bc_liar_right", previous_player_id, "now_you_shot_yourself_and"
    await broadcast_photo(game_id, images.reveal(played, table_current, bluff=not honest), key,
                          caller=get_user_nfgame(user_id),
                          target=get_user_nfgame(previous_player_id))
    await asyncio.sleep(PAUSE)
    await _pull_trigger(game_id, shooter, dead_key)

    while is_player_dead(game_id, get_current_turn_user_id(game_id)):
        set_current_turn(game_id, get_next_player_id(game_id, get_current_turn_user_id(game_id)))
    winner = get_alive_number(game_id)
    await asyncio.sleep(PAUSE)
    if winner:
        await finish_game(game_id, winner)
        return
    await reset_game_for_all_players(game_id)


async def _continue_turn(game_id, user_id):
    seated = [p for p in get_all_players_in_game(game_id) if p]
    current = user_id
    rm = get_player_cards(game_id, current)
    passes = 0
    # Players without cards pass. Previously the turn advanced once per OTHER
    # player inside the notification loop, skipping people in 3-4 player games.
    while not rm and passes < len(seated):
        name = get_user_nfgame(current)
        for other in seated:
            if other != current:
                await _send_and_track(
                    other, game_id,
                    text=t("player_p0_has_no_other", get_user_language(other), p0=name),
                )
        await _send_and_track(current, game_id, text=t("no_other_cards", get_user_language(current)))
        update_current_turn(game_id)
        current = get_current_turn_user_id(game_id)
        rm = get_player_cards(game_id, current)
        passes += 1

    if not rm:
        await reset_game_for_all_players(game_id)
        return
    ln = get_user_language(current)
    await _send_and_track(
        current, game_id,
        text=t("now_it_s_your_turn", ln, p0=get_current_table(game_id)),
        reply_markup=_turn_keyboard(current, rm[0].split(",")),
    )


def get_previous_player_id(game_id, current_player_id):
    alive_players = get_all_players_in_game(game_id)
    if not alive_players or current_player_id not in alive_players:
        return None
    current_index = alive_players.index(current_player_id)
    return alive_players[current_index - 1]


def get_next_player_id(game_id, current_player_id):
    players = [
        p for p in get_all_players_in_game(game_id)
        if p and not is_player_dead(game_id, p)
    ]
    if not players:
        return None
    if current_player_id not in players:
        # current player just died or left — continue from the top of the order
        return players[0]
    return players[(players.index(current_player_id) + 1) % len(players)]


async def reset_game_for_all_players(game_id):
    """Deal a new round. Revolvers are NOT reloaded: the chamber count carries
    over for the whole game, so the odds rise with every blank. Reloading here
    used to reset everyone to 1/6 each round."""
    table = get_current_table(game_id).split(" ")[-1]
    await broadcast_photo(game_id, images.new_round(table), "game_has_restarted_you_all",
                          p0=get_user_nfgame(get_current_turn_user_id(game_id)))
    save_player_cards(game_id)
    await send_random_cards_to_players(game_id)


async def start_next_round(tournament_id, round_number):
    groups = create_groups(determine_round_winners(tournament_id, round_number - 1))
    for nk in range(len(groups)):
        for jk in groups[nk]:
            save_tournament_round_info(tournament_id, round_number, jk, nk + 1)
    await notify_groups(groups, round_number)


async def notify_groups(groups, round_number):
    for idx, group in enumerate(groups, start=1):
        group_text = " ".join(
            f"\n{get_user_nfgame(user_id)} - {user_id}" for user_id in group
        )
        for user_id in group:
            ln = get_user_language(user_id)
            rn = t("round_p0_group_p1_players", ln, p0=round_number, p1=idx, p2=group_text)
            await safe_send(chat_id=user_id, text=rn)
    await asyncio.sleep(3)
    rang = ["🔴", "🟠", "🟡", "🟢", "⚪️"]
    for gn in groups:
        players = gn
        for gt in players:
            delete_user_from_all_games(gt)
        game_id = str(uuid.uuid4())
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO invitations (inviter_id, game_id, needed_players) VALUES (?, ?, ?)",
            (players[0], game_id, len(players)),
        )
        conn.commit()
        conn.close()
        for us in players[1:]:
            insert_invitation(players[0], us, game_id)
        cur_table = set_current_table(game_id, random.choice(
            ["heart ❤️", "diamond ♦️", "spade ♠️", "club ♣️"]))
        number = 19 if len(players) == 2 else 23 if len(players) == 3 else 27
        insert_number_of_cards(game_id, number)
        mark_game_as_started(game_id)
        roster = "".join(f"{rang[i]} {get_user_nfgame(p)}\n" for i, p in enumerate(players))
        for player in players:
            create_game_record_if_not_exists(game_id, player)
            ln = get_user_language(player)
            ims = t("game_has_started_there_are", ln, p0=number, p1=number // 4, p2=roster, p3=cur_table)
            await safe_send(chat_id=player, text=ims)
        for player in players:
            set_real_bullet_for_player(game_id, player)
        set_current_turn(game_id, random.choice(players))
        save_player_cards(game_id)
        await send_random_cards_to_players(game_id)
