"""
PostgreSQL schema initialization. Call setup_database() once at startup.

Notes vs the old sqlite schema:
  - All Telegram user/chat ids are BIGINT (they exceed 32-bit since 2021).
  - life_status is TEXT (sqlite declared INTEGER but stored 'alive'/'dead').
  - Columns the old code added via runtime ALTER TABLE are included upfront.
  - No FK constraints: sqlite never actually enforced them, and the existing
    data contains rows that would violate them.
"""
from logger import logger
from db_compat import raw_connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS users_database (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    registration_date TEXT,
    nfgame TEXT,
    language TEXT,
    unity_coin BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_game_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    game_id TEXT NOT NULL,
    message_id BIGINT NOT NULL,
    UNIQUE(user_id, game_id, message_id)
);

CREATE TABLE IF NOT EXISTS game_archive (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    game_id TEXT,
    game_start_time TEXT,
    game_end_time TEXT,
    game_winner TEXT
);

CREATE TABLE IF NOT EXISTS invitations (
    id BIGSERIAL PRIMARY KEY,
    inviter_id BIGINT,
    invitee_id BIGINT,
    game_id TEXT,
    players_cnt INTEGER,
    needed_players INTEGER,
    is_started INTEGER,
    current_turn_user_id BIGINT,
    number_of_cards INTEGER,
    group_chat_id BIGINT,
    UNIQUE(inviter_id, invitee_id, game_id)
);
ALTER TABLE invitations ADD COLUMN IF NOT EXISTS group_chat_id BIGINT;

CREATE TABLE IF NOT EXISTS group_settings (
    chat_id BIGINT PRIMARY KEY,
    language TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_lobbies (
    game_id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT UNIQUE
);

CREATE TABLE IF NOT EXISTS game_state (
    id BIGSERIAL PRIMARY KEY,
    game_id TEXT,
    player_id TEXT,
    cards TEXT,
    last_cards TEXT,
    current_table TEXT,
    real_bullet TEXT,
    blanks_count INTEGER DEFAULT 0,
    life_status TEXT DEFAULT 'alive',
    UNIQUE(game_id, player_id)
);

CREATE TABLE IF NOT EXISTS tournaments_table (
    id BIGSERIAL PRIMARY KEY,
    tournament_id TEXT,
    tournament_prize TEXT,
    tournament_start_time TEXT,
    tournament_end_time TEXT,
    tournament_register_start_time TEXT,
    tournament_register_end_time TEXT,
    tournament_winner TEXT,
    maximum_players INTEGER
);

CREATE TABLE IF NOT EXISTS tournament_users (
    id BIGSERIAL PRIMARY KEY,
    tournament_id TEXT,
    user_id BIGINT,
    user_status TEXT,
    UNIQUE(tournament_id, user_id)
);

CREATE TABLE IF NOT EXISTS tournament_rounds_users (
    id BIGSERIAL PRIMARY KEY,
    tournament_id TEXT,
    round_number TEXT,
    round_user_id TEXT,
    group_number TEXT,
    round_winner TEXT,
    UNIQUE (tournament_id, round_number, group_number, round_user_id, round_winner)
);

CREATE TABLE IF NOT EXISTS tournament_begun (
    tournament_id TEXT PRIMARY KEY,
    is_begun INTEGER
);

CREATE TABLE IF NOT EXISTS users_referral (
    user_id BIGINT PRIMARY KEY,
    referred_by BIGINT
);

CREATE TABLE IF NOT EXISTS unity_coin_referral (
    unity_coin_refferal INTEGER
);

CREATE TABLE IF NOT EXISTS excludeds (
    id BIGSERIAL PRIMARY KEY,
    game_id TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    number_of_excluded INTEGER DEFAULT 0,
    UNIQUE(game_id, user_id)
);

CREATE TABLE IF NOT EXISTS daily_bonus (
    user_id BIGINT PRIMARY KEY,
    last_claim TEXT
);

CREATE TABLE IF NOT EXISTS user_languages (
    user_id BIGINT PRIMARY KEY,
    language TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_earn (
    channel_id TEXT PRIMARY KEY,
    channel_link TEXT
);

CREATE TABLE IF NOT EXISTS channel_subscription (
    user_id TEXT,
    channel_id TEXT,
    PRIMARY KEY (user_id, channel_id)
);

-- Legacy tables kept only so existing rows survive the migration.
CREATE TABLE IF NOT EXISTS channel_subscriptions (
    user_id TEXT,
    channel_id TEXT,
    PRIMARY KEY (user_id, channel_id)
);
CREATE TABLE IF NOT EXISTS channels_earn (
    channel_id TEXT PRIMARY KEY,
    channel_link TEXT
);
CREATE TABLE IF NOT EXISTS users_game_states (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    game_id_user TEXT,
    messages_ingame TEXT
);
CREATE TABLE IF NOT EXISTS tournament_begin (
    tournament_id TEXT,
    is_begun INTEGER
);

CREATE INDEX IF NOT EXISTS idx_invitations_game_id ON invitations(game_id);
CREATE INDEX IF NOT EXISTS idx_invitations_inviter ON invitations(inviter_id);
CREATE INDEX IF NOT EXISTS idx_invitations_invitee ON invitations(invitee_id);
CREATE INDEX IF NOT EXISTS idx_game_state_game_id ON game_state(game_id);
CREATE INDEX IF NOT EXISTS idx_game_state_player ON game_state(player_id);
CREATE INDEX IF NOT EXISTS idx_user_game_messages_game ON user_game_messages(game_id);
CREATE INDEX IF NOT EXISTS idx_user_game_messages_user ON user_game_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_tournament_users_tournament ON tournament_users(tournament_id);
CREATE INDEX IF NOT EXISTS idx_tournament_users_user ON tournament_users(user_id);
CREATE INDEX IF NOT EXISTS idx_game_archive_user ON game_archive(user_id);
CREATE INDEX IF NOT EXISTS idx_game_archive_game ON game_archive(game_id);
"""


# The old sqlite code freely compares/stores integers against TEXT columns
# (player_id, nfgame, ...). PostgreSQL refuses
# `text = integer`, so restore sqlite's behavior with implicit casts.
_COMPAT_CASTS = """
DO $$ BEGIN
    CREATE CAST (integer AS text) WITH INOUT AS IMPLICIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE CAST (bigint AS text) WITH INOUT AS IMPLICIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""


def setup_database(admin_ids):
    """admin_ids: one id or an iterable of ids to seed into the admins table."""
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    conn = raw_connect()
    cursor = conn.cursor()
    cursor.execute(SCHEMA)
    cursor.execute(_COMPAT_CASTS)

    for admin_id in admin_ids:
        if admin_id:  # 0 means "not configured"
            cursor.execute(
                "INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (admin_id,)
            )
    cursor.execute("SELECT COUNT(*) FROM unity_coin_referral")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO unity_coin_referral (unity_coin_refferal) VALUES (10)")

    conn.commit()
    conn.close()
    logger.info("PostgreSQL database initialized successfully.")
