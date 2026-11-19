from i18n import t
from db_compat import connect_db, DBError, IntegrityError
from logger import logger
import asyncio
import random
import re
from config import bot, dp
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from keyboards.keyboard import get_main_menu
from datetime import datetime, timezone, timedelta


def md_escape(text) -> str:
    """Escape user/admin text for Telegram's legacy Markdown parse mode."""
    s = "" if text is None else str(text)
    for ch in ("\\", "_", "*", "`", "["):
        s = s.replace(ch, "\\" + ch)
    return s


def uz_now():
    """Current Uzbekistan time (UTC+5) as a naive datetime, matching stored timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5)


def award_coins(user_id, amount):
    with connect_db() as conn:
        conn.cursor().execute(
            "UPDATE users_database SET unity_coin = COALESCE(unity_coin, 0) + ? WHERE user_id = ?",
            (amount, user_id),
        )


async def safe_send(chat_id: int, **kwargs):
    from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
    try:
        return await bot.send_message(chat_id=chat_id, **kwargs)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logger.warning(f"Could not send to {chat_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected send error to {chat_id}: {e}")
        return None


def is_user_in_tournament_and_active(user_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tournament_id, user_status FROM tournament_users WHERE user_id = ?",
        (user_id,),
    )
    tournament_data = cursor.fetchone()
    if not tournament_data:
        conn.close()
        return False
    tournament_id, user_status = tournament_data
    if user_status != "alive":
        conn.close()
        return False

    cursor.execute(
        "SELECT tournament_start_time, tournament_end_time FROM tournaments_table WHERE tournament_id = ?",
        (tournament_id,),
    )
    tournament = cursor.fetchone()

    if not tournament:
        conn.close()
        return False

    tournament_start, tournament_end = tournament
    uzbekistan_tz = timezone(timedelta(hours=5))
    try:
        tournament_start = datetime.strptime(
            tournament_start, "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=uzbekistan_tz)
    except ValueError:
        tournament_start = datetime.strptime(
            tournament_start, "%Y-%m-%d %H:%M"
        ).replace(tzinfo=uzbekistan_tz)
    try:
        tournament_end = datetime.strptime(tournament_end, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=uzbekistan_tz
        )
    except ValueError:
        tournament_end = datetime.strptime(tournament_end, "%Y-%m-%d %H:%M").replace(
            tzinfo=uzbekistan_tz
        )
    current_time = datetime.now(uzbekistan_tz)

    # Compare the timezone-aware datetimes
    if tournament_start <= current_time <= tournament_end:
        conn.close()
        return True

    conn.close()
    return False


def register_user(user_id, username, first_name, last_name, preferred_name):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO users_database (user_id, username, first_name, last_name, nfgame, registration_date)
                VALUES (?, ?, ?, ?, ?, datetime('now',  '+5 hours'))
                """,
                (user_id, username, first_name, last_name, preferred_name),
            )
            conn.commit()
    except DBError as e:
        logger.error(f"Error registering user: {e}")


def is_user_registered(user_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users_database WHERE user_id = ?",
                (user_id,),
            )
            user = cursor.fetchone()
        return user
    except DBError as e:
        logger.error(f"Error checking if user is registered: {e}")
        return None


def add_admin(user_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_alive_number(game_id):
    players = get_all_players_in_game(game_id)
    alive = []
    for i in players:
        if not i or is_player_dead(game_id, i):
            continue
        alive.append(i)
    if len(alive) == 1:
        return alive[0]
    return 0


def get_game_inviter_id(game_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT inviter_id FROM invitations WHERE game_id = ?", (game_id,)
            )
            inviter_id = cursor.fetchone()
        return inviter_id[0] if inviter_id else None
    except DBError as e:
        logger.error(f"Error retrieving inviter ID: {e}")
        return None


def insert_invitation(inviter_id, invitee_id, game_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM invitations WHERE inviter_id = ? AND invitee_id = ? AND game_id = ?
                """,
                (inviter_id, invitee_id, game_id),
            )
            if cursor.fetchone():
                logger.debug("Invitation already exists. Skipping insertion.")
                return

            # copy per-game metadata onto the new row: it is otherwise stored only
            # on the creator's row, which is deleted when the creator dies/leaves
            cursor.execute(
                """
                INSERT INTO invitations (inviter_id, invitee_id, game_id, needed_players, group_chat_id)
                VALUES (?, ?, ?,
                    (SELECT MAX(needed_players) FROM invitations WHERE game_id = ?),
                    (SELECT MAX(group_chat_id) FROM invitations WHERE game_id = ?))
                """,
                (inviter_id, invitee_id, game_id, game_id, game_id),
            )
            conn.commit()
    except DBError as e:
        logger.error(f"Error inserting invitation: {e}")


def get_player_count(game_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM invitations WHERE game_id = ?", (game_id,)
            )
            player_count = cursor.fetchone()[0]
        return player_count
    except DBError as e:
        logger.error(f"Error getting player count: {e}")
        return 0


def is_user_in_game(game_id, user_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT invitee_id FROM invitations WHERE game_id = ? AND invitee_id = ?",
                (game_id, user_id),
            )
            result = cursor.fetchone()
        return result is not None
    except DBError as e:
        logger.error(f"Error checking if user is in game: {e}")
        return False


def get_user_nfgame(user_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT nfgame FROM users_database WHERE user_id = ?", (user_id,)
            )
            result = cursor.fetchone()
        return result[0] if result else None
    except DBError as e:
        logger.error(f"Error retrieving user 'nfgame': {e}")
        return None


def has_incomplete_games(user_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT game_id FROM invitations WHERE inviter_id = ? AND invitee_id IS NULL",
                (user_id,),
            )
            creator_game = cursor.fetchone()

            cursor.execute(
                "SELECT game_id FROM invitations WHERE invitee_id = ?", (user_id,)
            )
            participant_game = cursor.fetchone()

        return bool(creator_game or participant_game)
    except DBError as e:
        logger.error(f"Error checking incomplete games: {e}")
        return False


def delete_user_from_all_games(user_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM invitations WHERE inviter_id = ? AND invitee_id IS NULL",
                (user_id,),
            )
            cursor.execute("DELETE FROM invitations WHERE invitee_id = ?", (user_id,))
            conn.commit()
    except DBError as e:
        logger.error(f"Error deleting user from games: {e}")


def get_all_players_in_game(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT inviter_id, invitee_id
            FROM invitations
            WHERE game_id = ?
            ORDER BY id
            """,
            (game_id,),
        )
        result = cursor.fetchall()
    players = []
    for inviter_id, invitee_id in result:
        if inviter_id and inviter_id not in players:
            players.append(inviter_id)
        if invitee_id and invitee_id not in players:
            players.append(invitee_id)
    return [p for p in players if p and not is_player_dead(game_id, p)]


def delete_game(game_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM invitations WHERE game_id = ?", (game_id,))
            # per-game rows were never cleaned up and grew without bound
            cursor.execute("DELETE FROM game_state WHERE game_id = ?", (game_id,))
            cursor.execute("DELETE FROM excludeds WHERE game_id = ?", (game_id,))
            cursor.execute("DELETE FROM group_lobbies WHERE game_id = ?", (game_id,))
            conn.commit()
    except DBError as e:
        logger.error(f"Error deleting game: {e}")


def get_games_by_user(user_id):
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            # only rows that represent the user's own seat: a creator who died
            # still appears as inviter_id on the other players' rows
            cursor.execute(
                "SELECT DISTINCT game_id, inviter_id FROM invitations "
                "WHERE invitee_id = ? OR (inviter_id = ? AND invitee_id IS NULL)",
                (user_id, user_id),
            )
            games = cursor.fetchall()
        return [{"game_id": game[0], "creator_id": game[1]} for game in games]
    except DBError as e:
        logger.error(f"Error getting games for user {user_id}: {e}")
        return []


def get_game_id_by_user(user_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        # The user's own seat (creator row or invitee row), newest first. Matching
        # any row with inviter_id = user returned an old game in which a creator
        # had already died, hijacking every action in the game they joined next.
        cursor.execute(
            "SELECT game_id FROM invitations "
            "WHERE invitee_id = ? OR (inviter_id = ? AND invitee_id IS NULL) "
            "ORDER BY id DESC LIMIT 1",
            (user_id, user_id),
        )
        game_id = cursor.fetchone()
        if game_id:
            return game_id[0]
    return None


def get_id_by_nfgame(nfgame):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users_database WHERE nfgame = ?", (nfgame,))
        result = cursor.fetchone()
        if result:
            return result[0]
    return None


def get_needed_players(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT MAX(needed_players)
            FROM invitations
            WHERE game_id = ?
            """,
            (game_id,),
        )
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else 0


def get_game_creator_id(game_id):
    """Fetch the creator's user ID for a specific game."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT inviter_id 
            FROM invitations 
            WHERE game_id = ?
            LIMIT 1
        """,
            (game_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else None


def set_group_chat_id(game_id, chat_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE invitations SET group_chat_id = ? WHERE game_id = ?",
            (chat_id, game_id),
        )
        conn.commit()


def get_group_chat_id(game_id):
    """Returns the group chat id for group games, None for private (DM) games."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT group_chat_id FROM invitations WHERE game_id = ? "
            "AND group_chat_id IS NOT NULL LIMIT 1",
            (game_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def get_group_active_game(chat_id):
    """game_id of the lobby/running game in this group, or None."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT game_id FROM invitations WHERE group_chat_id = ? LIMIT 1",
            (chat_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def get_group_language(chat_id):
    """Language picked for a group chat, or None if nobody picked one yet."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM group_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return row[0] if row else None


def set_group_language(chat_id, language):
    with connect_db() as conn:
        conn.cursor().execute(
            "INSERT INTO group_settings (chat_id, language) VALUES (?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET language = EXCLUDED.language",
            (chat_id, language),
        )
        conn.commit()


def save_lobby_message(game_id, chat_id, message_id):
    with connect_db() as conn:
        conn.cursor().execute(
            "INSERT INTO group_lobbies (game_id, chat_id, message_id) VALUES (?, ?, ?) "
            "ON CONFLICT (game_id) DO UPDATE SET chat_id = EXCLUDED.chat_id, "
            "message_id = EXCLUDED.message_id",
            (game_id, chat_id, message_id),
        )
        conn.commit()


def get_lobby_message(game_id):
    """(chat_id, message_id) of a group game's lobby card, or None."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT chat_id, message_id FROM group_lobbies WHERE game_id = ?", (game_id,)
        )
        return cursor.fetchone()


def get_game_language(game_id):
    """Group games speak the group's language (falling back to the creator's);
    DM games translate per player."""
    group_id = get_group_chat_id(game_id)
    if group_id:
        lang = get_group_language(group_id)
        if lang:
            return lang
    return get_user_language(get_game_creator_id(game_id))


def _alive_players_in_game(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT invitee_id FROM invitations WHERE game_id = ? AND invitee_id IS NOT NULL",
            (game_id,),
        )
        players = [row[0] for row in cursor.fetchall()]
    cr_id = get_game_creator_id(game_id)
    if cr_id not in players:
        players.append(cr_id)
    return [p for p in players if p and not is_player_dead(game_id, p)]


async def broadcast_t(game_id, key, **kwargs):
    """Public game event: one message to the group for group games,
    otherwise a translated DM to every alive player."""
    from i18n import t
    group_id = get_group_chat_id(game_id)
    if group_id:
        try:
            msg = await bot.send_message(group_id, t(key, get_game_language(game_id), **kwargs))
            save_message(group_id, game_id, msg.message_id)
        except Exception as e:
            logger.error(f"Failed to send group message to {group_id}: {e}")
        return
    for player_id in _alive_players_in_game(game_id):
        try:
            msg = await bot.send_message(
                player_id, t(key, get_user_language(player_id), **kwargs)
            )
            save_message(player_id, game_id, msg.message_id)
        except Exception as e:
            logger.error(f"Failed to send message to player {player_id}: {e}")


async def broadcast_photo(game_id, png, key, **kwargs):
    """Like broadcast_t, but sends an image with the text as its caption."""
    from i18n import t
    from aiogram.types import BufferedInputFile
    group_id = get_group_chat_id(game_id)
    if group_id:
        targets = [(group_id, get_game_language(game_id))]
    else:
        targets = [(p, get_user_language(p)) for p in _alive_players_in_game(game_id)]
    for chat_id, lang in targets:
        try:
            msg = await bot.send_photo(
                chat_id, BufferedInputFile(png, "event.png"), caption=t(key, lang, **kwargs)
            )
            save_message(chat_id, game_id, msg.message_id)
        except Exception as e:
            logger.error(f"Failed to send photo to {chat_id}: {e}")


def is_game_started(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_started FROM invitations WHERE game_id = ?", (game_id,)
        )
        result = cursor.fetchone()
        return result[0] == 1 if result else False


def mark_game_as_started(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE invitations SET is_started = 1 WHERE game_id = ?", (game_id,)
        )
        conn.commit()


def is_name_valid(name):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users_database WHERE nfgame = ?", (name,))
    if cursor.fetchone()[0] > 0:
        return 2
    if len(name) > 30 or len(name) < 1:
        return 0
    if re.match(r"^[a-zA-Z0-9_]+$", name[1:]) and name[0] == "@":
        return 1
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        return 0
    return 1


def get_all_players_nfgame(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.nfgame 
            FROM users_database u
            INNER JOIN invitations i ON u.user_id = i.invitee_id
            WHERE i.game_id = ?
        """,
            (game_id,),
        )
        s = []
        for row in cursor.fetchall():
            s.append(row[0])
        cr_name = get_user_nfgame(get_game_creator_id(game_id))
        if not cr_name in s:
            s.append(cr_name)
        return s


def set_current_turn(game_id, user_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE invitations SET current_turn_user_id = ? WHERE game_id = ?",
            (user_id, game_id),
        )
        conn.commit()


def insert_number_of_cards(game_id, number_of_cards):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE invitations
            SET number_of_cards = ?
            WHERE game_id = ?
            """,
            (number_of_cards, game_id),
        )

        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO invitations (game_id, number_of_cards)
                VALUES (?, ?)
                """,
                (game_id, number_of_cards),
            )

        conn.commit()


def set_current_table(game_id, current_table):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(game_state)")
        columns = [row[1] for row in cursor.fetchall()]
        if "current_table" not in columns:
            cursor.execute(
                """
                ALTER TABLE game_state
                ADD COLUMN current_table TEXT
                """
            )
            conn.commit()

        # player_id is NULL here, so the UNIQUE constraint never fired and
        # INSERT OR IGNORE added a junk row on every call
        cursor.execute("SELECT 1 FROM game_state WHERE game_id = ? LIMIT 1", (game_id,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO game_state (game_id) VALUES (?)", (game_id,))

        cursor.execute(
            """
            UPDATE game_state
            SET current_table = ?
            WHERE game_id = ?
            """,
            (current_table, game_id),
        )
        conn.commit()

    return current_table


def get_current_table(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(game_state)")
        columns = [row[1] for row in cursor.fetchall()]
        if "current_table" not in columns:
            raise ValueError(
                "The 'current_table' column does not exist in the game_state table."
            )
        cursor.execute(
            """
            SELECT current_table
            FROM game_state
            WHERE game_id = ? AND current_table IS NOT NULL
            LIMIT 1
            """,
            (game_id,),
        )
        # Only the rows that existed when the table was set carry it; player
        # rows created later have NULL. Without the filter, row order (which
        # changes after every UPDATE) decided whether the table was found.
        result = cursor.fetchone()
        if result is None:
            logger.debug(f"No entry found for game_id: {game_id}.")
        elif result[0] is None:
            logger.debug(f"'current_table' is not set for game_id: {game_id}.")
        return result[0] if result else None


async def periodically_edit_message(
    chat_id,
    message_id,
    s_message_id,
    lent,
    cur_table,
    interval,
):
    try:
        seconds = ["2️⃣", "1️⃣"]
        for i in range(2):
            new_text = seconds[i]
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=new_text
            )
            await asyncio.sleep(interval)

        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        await bot.delete_message(chat_id=chat_id, message_id=s_message_id)
        if lent == 2:
            number = 19
        elif lent == 3:
            number = 23
        else:
            number = 27
        game_id = get_game_id_by_user(chat_id)
        insert_number_of_cards(game_id, number)
        mark_game_as_started(game_id)
        massiv = get_all_players_nfgame(game_id)
        s = ""
        rang = ["🔴", "🟠", "🟡", "🟢", "⚪️"]
        for row in range(len(massiv)):
            s += rang[row] + " " + massiv[row] + "\n"
        ln = get_user_language(chat_id)
        ims = t("game_has_started_there_are", ln, p0=number, p1=number//4, p2=s, p3=cur_table)
        await bot.send_message(chat_id=chat_id, text=ims)
    except Exception as e:
        await bot.send_message(
            chat_id,
            f"Something went wrong. Plase try again.",
            reply_markup=get_main_menu(chat_id),
        )
        logger.error(f"An error occurred: {e}")


def get_number_of_cards(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT number_of_cards 
            FROM invitations 
            WHERE game_id = ?
            """,
            (game_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else 0


def generate_random_cards(deck):
    random_cards = random.sample(deck, 5)
    for card in random_cards:
        deck.remove(card)
    return random_cards


def create_cards(game_id):
    nm = get_number_of_cards(game_id)
    cards = ["❤️", "♦️", "♠️", "♣️"]
    deck = cards * (nm // 4)
    deck.append("🃏")
    deck.append("🎴")
    deck.append("🎴")
    return deck


def save_player_cards(game_id):
    players = get_all_players_in_game(game_id)
    if not players:
        logger.debug("No players found for this game.")
        return
    players = [
        player for player in players if player and not is_player_dead(game_id, player)
    ]

    deck = create_cards(game_id)
    if len(deck) < len(players) * 5:
        logger.debug("Not enough cards remaining in the deck for all players.")
        return
    player_cards = {player: generate_random_cards(deck) for player in players}
    with connect_db() as conn:
        cursor = conn.cursor()
        for player, cards in player_cards.items():
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM game_state
                WHERE game_id = ? AND player_id = ?
                """,
                (game_id, player),
            )
            exists = cursor.fetchone()[0] > 0

            if exists:
                cursor.execute(
                    """
                    UPDATE game_state
                    SET cards = ?
                    WHERE game_id = ? AND player_id = ?
                    """,
                    (",".join(cards), game_id, player),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO game_state (game_id, player_id, cards)
                    VALUES (?, ?, ?)
                    """,
                    (game_id, player, ",".join(cards)),
                )
        conn.commit()

    logger.debug(f"Cards saved for game {game_id}: {player_cards}")


def set_real_bullet_for_player(game_id, player_id):
    # Weighted chamber: instant first-pull deaths (0) and near-immortal late
    # chambers (5) are possible but rare, so most deaths land on pulls 2-5
    # where the tension builds. Uniform 0-5 made games feel "1 shot or never"
    # because real games rarely last 5+ pulls per player.
    real_bullet = random.choices([0, 1, 2, 3, 4, 5], weights=[1, 3, 4, 4, 3, 1])[0]

    with connect_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(game_state)")
            columns = [row[1] for row in cursor.fetchall()]

            if "player_id" not in columns:
                cursor.execute(
                    """
                    ALTER TABLE game_state
                    ADD COLUMN player_id TEXT
                    """
                )
                conn.commit()
                logger.debug("Added 'player_id' column to game_state table.")

            if "real_bullet" not in columns:
                cursor.execute(
                    """
                    ALTER TABLE game_state
                    ADD COLUMN real_bullet INTEGER
                    """
                )
                conn.commit()
                logger.debug("Added 'real_bullet' column to game_state table.")

            if "blanks_count" not in columns:
                cursor.execute(
                    """
                    ALTER TABLE game_state
                    ADD COLUMN blanks_count INTEGER DEFAULT 0
                    """
                )
                conn.commit()
                logger.debug("Added 'blanks_count' column to game_state table.")
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM game_state
                WHERE game_id = ? AND player_id = ?
                """,
                (game_id, player_id),
            )
            exists = cursor.fetchone()[0] > 0

            if exists:
                cursor.execute(
                    """
                    UPDATE game_state
                    SET real_bullet = ?, blanks_count = 0
                    WHERE game_id = ? AND player_id = ?
                    """,
                    (real_bullet, game_id, player_id),
                )
            else:
                # Insert new record
                cursor.execute(
                    """
                    INSERT INTO game_state (game_id, player_id, real_bullet, blanks_count)
                    VALUES (?, ?, ?, 0)
                    """,
                    (game_id, player_id, real_bullet),
                )
            conn.commit()
            logger.debug(f"Set 'real_bullet' for player {player_id} in game {game_id} to {real_bullet}.")
            return real_bullet

        except DBError as e:
            logger.error(f"SQLite error: {e}")
            return None


def is_player_dead(game_id, player_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT life_status
            FROM game_state
            WHERE game_id = ? AND player_id = ?
            """,
            (game_id, player_id),
        )
        result = cursor.fetchone()
        if result and result[0] == "dead":
            return True
    return False


def set_user_status(user_id, status):
    if is_user_in_tournament_and_active(user_id):
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tournament_users SET user_status = ? WHERE user_id = ?",
            (status, user_id),
        )
        conn.commit()
        conn.close()


async def shoot_self(game_id, player_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT real_bullet, blanks_count
            FROM game_state
            WHERE game_id = ? AND player_id = ?
            """,
            (game_id, player_id),
        )
        result = cursor.fetchone()
        if result is None:
            return None

        real_bullet_position, blanks_count = result
        if int(blanks_count) == int(real_bullet_position):
            if is_user_turn(player_id, game_id):
                update_current_turn(game_id)
            cursor.execute(
                """
                UPDATE game_state
                SET life_status = 'dead'
                WHERE game_id = ? AND player_id = ?
                """,
                (game_id, player_id),
            )
            conn.commit()
            if get_tournament_id_by_user(player_id) and is_user_in_tournament(
                get_tournament_id_by_user(player_id), player_id
            ):
                set_user_status(player_id, "died")
            return True
        else:
            blanks_count += 1
            cursor.execute(
                """
                UPDATE game_state
                SET blanks_count = ?
                WHERE game_id = ? AND player_id = ?
                """,
                (blanks_count, game_id, player_id),
            )
            conn.commit()
            elimination_chance = blanks_count
            return elimination_chance


def is_user_turn(user_id, game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT current_turn_user_id FROM invitations WHERE game_id = ?",
            (game_id,),
        )
        result = cursor.fetchone()
        return result[0] == user_id if result else False


def update_current_turn(game_id):
    with connect_db() as conn:
        cursor = conn.cursor()
        players = get_all_players_in_game(game_id)
        cursor.execute(
            "SELECT current_turn_user_id FROM invitations WHERE game_id = ?", (game_id,)
        )
        current_turn = cursor.fetchone()
        if not current_turn or len(players) == 0:
            logger.error("erooooooooooooooooooooooooooooooooooooooooooooor")
            return
        if current_turn[0] in players:
            next_turn = players[(players.index(current_turn[0]) + 1) % len(players)]
        else:
            # turn holder left or was removed: hand the turn to the first seat
            next_turn = players[0]
        cursor.execute(
            "UPDATE invitations SET current_turn_user_id = ? WHERE game_id = ?",
            (next_turn, game_id),
        )
        conn.commit()


def save_message(user_id, game_id, message_id):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO user_game_messages (user_id, game_id, message_id)
            VALUES (?, ?, ?)
            """,
            (user_id, game_id, message_id),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


async def _delete_message_quietly(user_id, message_id):
    from aiogram.exceptions import TelegramBadRequest
    try:
        await bot.delete_message(chat_id=user_id, message_id=message_id)
    except TelegramBadRequest:
        pass  # already deleted or older than 48h — nothing to do
    except Exception as e:
        logger.warning(f"Could not delete message {message_id} for {user_id}: {e}")


async def _delete_in_parallel(rows):
    # Telegram tolerates ~30 requests/sec; delete in bursts instead of one by one.
    for i in range(0, len(rows), 25):
        await asyncio.gather(
            *(_delete_message_quietly(u, m) for u, m in rows[i : i + 25])
        )


async def delete_all_game_messages(game_id):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT user_id, message_id FROM user_game_messages WHERE game_id = ?",
            (game_id,),
        )
        rows = cursor.fetchall()
        # remove rows first so a concurrent/second call never re-deletes
        cursor.execute("DELETE FROM user_game_messages WHERE game_id = ?", (game_id,))
        conn.commit()
    except DBError as e:
        logger.error(f"Database error: {e}")
        rows = []
    finally:
        conn.close()
    await _delete_in_parallel(rows)


async def delete_user_messages(game_id, userid):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT user_id, message_id FROM user_game_messages "
            "WHERE game_id = ? AND user_id = ?",
            (game_id, userid),
        )
        rows = cursor.fetchall()
        cursor.execute(
            "DELETE FROM user_game_messages WHERE game_id = ? AND user_id = ?",
            (game_id, userid),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"Database error: {e}")
        rows = []
    finally:
        conn.close()
    await _delete_in_parallel(rows)


def get_all_user_ids():
    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT user_id FROM users_database")
        user_ids = [row[0] for row in cursor.fetchall()]
    except DBError as e:
        logger.error(f"Database error occurred: {e}")
        user_ids = []
    finally:
        conn.close()
    return user_ids


def create_game_record_if_not_exists(game_id: str, user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        start_time = uz_now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO game_archive (game_id, user_id, game_start_time)
            VALUES (?, ?, ?)
            """,
            (game_id, user_id, start_time),
        )
        conn.commit()
        logger.debug(f"Game record created for {user_id}, game_id: {game_id}")
    except DBError as e:
        logger.error(f"❌ Database error occurred while creating game record: {e}")
    finally:
        conn.close()


def update_game_details(game_id: str, user_id: int, winner: str):
    end_time = uz_now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect_db()
    try:
        cursor = conn.cursor()

        if not winner:
            winner = "Game had not been finished"

        cursor.execute(
            """
            UPDATE game_archive 
            SET game_end_time = ?, game_winner = ?
            WHERE game_id = ? AND user_id = ?
            """,
            (end_time, winner, game_id, user_id),
        )

        conn.commit()
        if cursor.rowcount == 0:
            logger.error(f"❌ Failed to update game details for ID '{game_id}'.")
            return f"❌ Failed to update game details for ID '{game_id}'."

        logger.debug(f"Game details updated for {user_id}, game_id: {game_id}")
        return "Game details updated successfully."

    except DBError as e:
        logger.error(f"❌ Database error occurred: {e}")
        return f"❌ Database error occurred: {e}"
    finally:
        conn.close()


def get_upcoming_tournaments():
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, tournament_id, tournament_prize, tournament_start_time, tournament_end_time 
            FROM tournaments_table
            WHERE tournament_start_time > datetime('now',  '+5 hours')
            """
        )
        tournaments = [
            {
                "id": row[0],
                "name": row[1],
                "prize": row[2],
                "start_time": row[3],
                "end_time": row[4],
            }
            for row in cursor.fetchall()
        ]
        return tournaments
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return []
    finally:
        conn.close()


def get_tournament_id_by_user(user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT tournament_id
            FROM tournament_rounds_users
            WHERE round_user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else None
    except DBError as e:
        logger.error(f"Database error: {e}")
        return None
    finally:
        conn.close()


from datetime import datetime, timedelta


def set_tournament_end_time(tournament_id):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        end_time = datetime.now(timezone.utc) + timedelta(hours=5)
        formatted_time = end_time.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            UPDATE tournaments_table
            SET tournament_end_time = ?
            WHERE tournament_id = ?
            """,
            (formatted_time, tournament_id),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
    finally:
        conn.close()


def get_tournament_archive():
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, tournament_prize, tournament_winner, tournament_start_time, tournament_end_time
            FROM tournaments_table
            WHERE tournament_end_time <= datetime('now',  '+5 hours')
            """
        )
        tournaments = [
            {
                "id": row[0],
                "prize": row[1],
                "winner": row[2],
                "start_time": row[3],
                "end_time": row[4],
            }
            for row in cursor.fetchall()
        ]
        return tournaments
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return []
    finally:
        conn.close()


def is_user_in_tournament(tournament_id: str, user_id: int) -> bool:
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT 1 FROM tournament_users
            WHERE tournament_id = ? AND user_id = ?
            """,
            (tournament_id, user_id),
        )
        result = cursor.fetchone()
        return result is not None
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return False
    finally:
        conn.close()


def add_user_to_tournament(tournament_id: str, user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO tournament_users (tournament_id, user_id, user_status)
            VALUES (?, ?, 'alive')
            ON CONFLICT(tournament_id, user_id) DO UPDATE SET user_status = 'alive'
            """,
            (tournament_id, user_id),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        raise
    finally:
        conn.close()


def get_current_players(tournament_id: str) -> int:
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*) 
            FROM tournament_users
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )
        current_players = cursor.fetchone()[0]
        return current_players
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return 0
    finally:
        conn.close()


def get_tournament_users_list(tournament_id: str) -> list:
    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT user_id 
            FROM tournament_users
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )
        users = [row[0] for row in cursor.fetchall()]
        return users

    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return []

    finally:
        conn.close()


def delete_tournament(tournament_id):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT user_id FROM tournament_users WHERE tournament_id = ?",
            (tournament_id,),
        )
        users = cursor.fetchall()

        for user in users:
            user_id = user[0]
            delete_user_from_all_games(user_id)

        cursor.execute(
            "DELETE FROM tournament_users WHERE tournament_id = ?", (tournament_id,)
        )
        cursor.execute(
            "DELETE FROM tournaments_table WHERE tournament_id = ?", (tournament_id,)
        )

        conn.commit()
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


def get_ongoing_tournaments():
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT t.id, t.tournament_id, t.tournament_prize, t.tournament_start_time, t.tournament_end_time, 
                   (SELECT COUNT(*) FROM tournament_users tu WHERE tu.tournament_id = t.tournament_id) AS current_players
            FROM tournaments_table t
            WHERE t.tournament_start_time <= datetime('now', '+5 hours') 
              AND t.tournament_end_time >= datetime('now',  '+5 hours')
            """
        )
        tournaments = [
            {
                "id": row[0],
                "name": row[1],
                "prize": row[2],
                "start_time": row[3],
                "end_time": row[4],
            }
            for row in cursor.fetchall()
        ]
        return tournaments
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return []
    finally:
        conn.close()


def determine_round_winners(tournament_id, round_number):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT round_winner
            FROM tournament_rounds_users
            WHERE tournament_id = ? AND round_number = ?
            """,
            (tournament_id, round_number),
        )
        winners = cursor.fetchall()
        if winners:
            winners_ids = list(set([winner[0] for winner in winners if winner]))
            return winners_ids
        else:
            logger.debug(f"No winners found for round {round_number} in tournament {tournament_id}.")
            return []
    except DBError as e:
        logger.error(f"Database error: {e}")
        return []
    finally:
        conn.close()


def save_tournament_round_info(
    tournament_id, round_number, round_user_id, group_number
):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO tournament_rounds_users (tournament_id, round_number, round_user_id, group_number, round_winner)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (tournament_id, round_number, round_user_id, group_number),
        )
        conn.commit()
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


async def save_round_winner(tournament_id: str, round_user_id, round_winner):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT round_number, group_number
            FROM tournament_rounds_users
            WHERE tournament_id = ? AND round_user_id = ?
            ORDER BY round_number DESC
            LIMIT 1
            """,
            (tournament_id, round_user_id),
        )
        result = cursor.fetchone()
        if result:
            round_number, group_number = result
            group_number = int(group_number)
            cursor.execute(
                """
                UPDATE tournament_rounds_users
                SET round_winner = ?
                WHERE tournament_id = ? AND round_number = ? AND group_number = ?
                """,
                (round_winner, tournament_id, round_number, group_number),
            )
            conn.commit()
        else:
            logger.debug("Round and group not found for the given user.")
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


def get_current_round_number(tournament_id: str) -> str:
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT round_number
            FROM tournament_rounds_users
            WHERE tournament_id = ?
            ORDER BY CAST(round_number AS INTEGER) DESC
            LIMIT 1
            """,
            (tournament_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else "0"
    except DBError as e:
        logger.error(f"Database error: {e}")
        return "0"
    finally:
        conn.close()


def get_number_of_winners(tournament_id: str, round_number: str) -> int:
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(DISTINCT round_winner)
            FROM tournament_rounds_users
            WHERE tournament_id = ? AND round_number = ? AND round_winner IS NOT NULL
            """,
            (tournament_id, round_number),
        )
        result = cursor.fetchone()
        return result[0] if result else 0
    except DBError as e:
        logger.error(f"Database error: {e}")
        return 0
    finally:
        conn.close()


async def notify_round_results(tournament_id: str, round_number: str):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT group_number, round_winner
            FROM tournament_rounds_users
            WHERE tournament_id = ? AND round_number = ?
            """,
            (tournament_id, round_number),
        )
        group_results = cursor.fetchall()
        if not group_results:
            return f"No results found for round {round_number} in tournament {tournament_id}."

        results_message = f"🏆 Round {round_number} Results 🏆\n"
        unique_groups = set()
        for group_number, winner_id in group_results:
            if group_number not in unique_groups:
                unique_groups.add(group_number)
                if winner_id:
                    results_message += f"| - Winner from Group {group_number}: {get_user_nfgame(winner_id)} (ID: {winner_id})\n"
                else:
                    results_message += f"| - Group {group_number}: No winner yet\n"

        cursor.execute(
            """
            SELECT user_id
            FROM tournament_users
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )
        all_users = cursor.fetchall()
        user_ids = [row[0] for row in all_users]
        for user_id in user_ids:
            try:
                # plain text: nicknames like john_doe broke Markdown parsing
                await bot.send_message(chat_id=user_id, text=results_message)
            except Exception as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")

        return f"Round {round_number} results sent to all players in tournament {tournament_id}."

    except DBError as e:
        logger.error(f"Database error: {e}")
        return f"Error fetching round results for tournament {tournament_id}."
    finally:
        conn.close()


def get_number_of_groups_in_round(tournament_id: str, round_number: str):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(DISTINCT group_number)
            FROM tournament_rounds_users
            WHERE tournament_id = ? AND round_number = ?
            """,
            (tournament_id, round_number),
        )
        result = cursor.fetchone()
        return result[0] if result else 0
    except DBError as e:
        logger.error(f"Database error: {e}")
        return 0
    finally:
        conn.close()


def delete_tournament_from_tables(tournament_id: str):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        # cursor.execute(
        #     "DELETE FROM tournaments_table WHERE tournament_id = ?",
        #     (tournament_id,),
        # )
        cursor.execute(
            "DELETE FROM tournament_users WHERE tournament_id = ?",
            (tournament_id,),
        )
        cursor.execute(
            "DELETE FROM tournament_rounds_users WHERE tournament_id = ?",
            (tournament_id,),
        )
        conn.commit()
        logger.debug(f"Tournament with ID {tournament_id} has been deleted.")
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


async def update_tournament_winner_if_round_finished(tournament_id: str, winner: str):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE tournaments_table
            SET tournament_winner = ?
            WHERE tournament_id = ?
            """,
            (winner, tournament_id),
        )
        conn.commit()
        await inform_all_users_tournament_ended(tournament_id, winner)
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
    return 0


async def inform_all_users_tournament_ended(tournament_id: str, winner_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT user_id
            FROM tournament_users
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )
        users = cursor.fetchall()
        winner_name = get_user_nfgame(winner_id)
        message = (
            f"🏁 Tournament Ended! 🏆\n\n"
            f"Thank you for participating in a Tournament 🎮\n\n"
            f"🥇 The Winner is: {winner_name} (ID: {winner_id}) 🎉\n\n"
            f"Congrats to the champion! Stay tuned for more tournaments. 🏅"
        )
        for user in users:
            user_id = user[0]
            try:
                await safe_send(chat_id=user_id, text=message)
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
        set_tournament_end_time(tournament_id)
        delete_tournament_from_tables(tournament_id)
    except DBError as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


def create_groups(participants):
    random.shuffle(participants)
    groups = []
    if not participants:
        return []
    if len(participants) <= 4:
        return [participants]
    nmb = len(participants) % 4
    nmd = len(participants) // 4
    if nmb == 0:
        for i in range(0, len(participants), 4):
            groups.append(participants[i : i + 4])
    elif nmb == 1:
        for i in range(0, nmd - 1):
            groups.append(participants[:4])
            participants = participants[4:]
        groups.append(participants[:2])
        groups.append(participants[2:])
    else:
        for i in range(0, nmd):
            groups.append(participants[:4])
            participants = participants[4:]
        if participants:
            groups.append(participants)
    return groups


def get_round_results(tournament_id, round_number):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT group_number, round_winner
            FROM tournament_rounds_users
            WHERE tournament_id = ? AND round_number = ?
            """,
            (tournament_id, round_number),
        )
        group_results = cursor.fetchall()
        if not group_results:
            return f"No results found for round {round_number} in tournament {tournament_id}."

        results_message = f"🏆 Round {round_number} Results 🏆\n"
        unique_groups = set()
        for group_number, winner_id in group_results:
            if group_number not in unique_groups:
                unique_groups.add(group_number)
                if winner_id:
                    results_message += f"| - Winner from Group {group_number}: {get_user_nfgame(winner_id)} (ID: {winner_id})\n"
                else:
                    results_message += f"| - Group {group_number}: No winner yet\n"
        return results_message
    except DBError as e:
        logger.error(f"Database error: {e}")
        return f"Error fetching round results for tournament {tournament_id}."
    finally:
        conn.close()


def get_number_of_referrals(user_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) 
        FROM users_referral 
        WHERE referred_by = ?
        """,
        (user_id,),
    )

    result = cursor.fetchone()
    return result[0] if result else 0


async def generate_referral_link(user_id):
    # built from the running bot's username instead of a hard-coded one
    from aiogram.utils.deep_linking import create_start_link
    return await create_start_link(bot, payload=str(user_id))


def get_top_referrals():
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT referred_by, COUNT(*) AS referral_count
            FROM users_referral
            WHERE referred_by IS NOT NULL
            GROUP BY referred_by
            ORDER BY referral_count DESC
            LIMIT 10
        """
        )
        top_referrals = cursor.fetchall()
        st = f""
        if not top_referrals:
            st += f"No referrals found."
            return st
        st += f"📌 Top {min(10, len(top_referrals))} Users with Most Referrals:\n"
        for rank, (user_id, count) in enumerate(top_referrals, start=1):
            st += f"{rank}. {get_user_nfgame(user_id)} - Referrals: {count}\n"
        return st
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
    finally:
        conn.close()


def update_unity_coin_referral(new_value):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE unity_coin_referral SET unity_coin_refferal = ?", (new_value,)
        )
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO unity_coin_referral (unity_coin_refferal) VALUES (?)",
                (new_value,),
            )
        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error: {e}")

    finally:
        conn.close()


def get_unity_coin_referral():
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT unity_coin_refferal FROM unity_coin_referral LIMIT 1")
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            return None

    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return None

    finally:
        conn.close()


def set_tournament_status(tournament_id: str, is_begin: bool):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tournament_begun (
                tournament_id TEXT PRIMARY KEY,
                is_begun INTEGER
            )
        """
        )

        cursor.execute(
            """
            INSERT INTO tournament_begun (tournament_id, is_begun)
            VALUES (?, ?)
            ON CONFLICT(tournament_id) DO UPDATE SET is_begun = excluded.is_begun
        """,
            (tournament_id, int(is_begin)),
        )

        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
    finally:
        conn.close()


def get_tournament_status(tournament_id) -> bool:
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT CAST(is_begun AS INTEGER) FROM tournament_begun WHERE tournament_id = ?
        """,
            (tournament_id,),
        )
        result = cursor.fetchone()
        return bool(result[0]) if result else False
    except DBError as e:
        logger.error(f"❌ Database error: {e}")
        return False
    finally:
        conn.close()


def remove_player(player_id):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM tournament_users WHERE user_id = ?", (player_id,))
        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error check 4: {e}")
    finally:
        conn.close()


def reset_exclusion_count(game_id: str, user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO excludeds (game_id, user_id, number_of_excluded)
            VALUES (?, ?, 0)
            ON CONFLICT(game_id, user_id) DO UPDATE SET number_of_excluded = 0
        """,
            (game_id, user_id),
        )

        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error check 3: {e}")
    finally:
        conn.close()


def increase_exclusion_count(game_id: str, user_id: int):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE excludeds
            SET number_of_excluded = number_of_excluded + 1
            WHERE game_id = ? AND user_id = ?
        """,
            (game_id, user_id),
        )

        conn.commit()
    except DBError as e:
        logger.error(f"❌ Database error check 2: {e}")
    finally:
        conn.close()


def is_any_user_excluded(game_id: str) -> bool:
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*) FROM excludeds
            WHERE game_id = ? AND number_of_excluded > 0
        """,
            (game_id,),
        )
        result = cursor.fetchone()
        return result[0] > 0
    except DBError as e:
        logger.error(f"❌ Database error check 1: {e}")
        return False
    finally:
        conn.close()


def get_utc_plus_5_date():
    utc_plus_5 = datetime.now(timezone.utc) + timedelta(hours=5)
    return utc_plus_5.strftime("%Y-%m-%d")


def claim_daily_bonus(user_id: int) -> bool:
    """Atomically record today's claim. False if already claimed today
    (the old check-then-update let a double tap pay out twice)."""
    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO daily_bonus (user_id, last_claim) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_claim = excluded.last_claim
            WHERE daily_bonus.last_claim IS DISTINCT FROM excluded.last_claim
            RETURNING user_id
            """,
            (user_id, get_utc_plus_5_date()),
        )
        return cursor.fetchone() is not None


def can_claim_bonus(user_id: int):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT last_claim FROM daily_bonus WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        last_claim = datetime.strptime(row[0], "%Y-%m-%d").date()
        current_date = (datetime.now(timezone.utc) + timedelta(hours=5)).date()

        if last_claim == current_date:
            return False

    return True


def update_claim_time(user_id: int):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO daily_bonus (user_id, last_claim) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_claim = excluded.last_claim
        """,
        (user_id, get_utc_plus_5_date()),
    )

    conn.commit()
    conn.close()


def get_user_language(user_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT language FROM user_languages WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0]
    return None


def get_unsubscribed_channels(user_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ce.channel_id, ce.channel_link
        FROM channel_earn ce
        LEFT JOIN channel_subscription cs 
        ON ce.channel_id = cs.channel_id AND cs.user_id = ?
        WHERE cs.channel_id IS NULL
        """,
        (user_id,),
    )
    
    result = cursor.fetchall()
    conn.close()
    
    logger.debug(f"Unsubscribed channels for user {user_id}: {result}") 
    
    if not result:
        return None  
    
    return [(channel_id, link) for channel_id, link in result][0]


def save_subscription(user_id, channel_id):
    conn = connect_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO channel_subscription (user_id, channel_id) VALUES (?, ?)",
            (user_id, channel_id)
        )
        conn.commit()
        logger.debug(f"Subscription saved: user={user_id}, channel={channel_id}")
        return cursor.rowcount > 0
    except IntegrityError as e:
        logger.error(f"Database Error: {e} for user={user_id}, channel={channel_id}")
        return False
    finally:
        conn.close()
        

def getall_channels():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT channel_id, channel_link FROM channel_earn"
    )
    courses = cursor.fetchall()
    conn.close()
    return courses
