from db_compat import connect_db, DBError, IntegrityError
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def kb_variant(ln, en=None, ru=None, uz=None):
    """Pick the keyboard matching the user's language, falling back to English."""
    if ln == "ru" and ru is not None:
        return ru
    if ln == "uz" and uz is not None:
        return uz
    return en


def get_user_language(user_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT language FROM user_languages WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0]
    return "en"


def is_user_admin(user_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


main_earn_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="bonus 🚀"),
            KeyboardButton(text="Join channels 💎"),
        ],
        [
            KeyboardButton(text="❄️ referral"),
            KeyboardButton(text="🤩 tournaments"),
        ],
        [
            KeyboardButton(text="back to main menu 🔙"),
        ],
    ],
    resize_keyboard=True,
)

main_earn_button_ru = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="бонус 🚀"),
            KeyboardButton(text="Подписаться 💎"),
        ],
        [
            KeyboardButton(text="❄️ реферал"),
            KeyboardButton(text="🤩 турниры"),
        ],
        [
            KeyboardButton(text="вернуться в главное меню 🔙"),
        ],
    ],
    resize_keyboard=True,
)

main_earn_button_uz = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="bonus 🚀"),
            KeyboardButton(text="obuna bo'lish 💎"),
        ],
        [
            KeyboardButton(text="❄️ referal"),
            KeyboardButton(text="🤩 turnirlar"),
        ],
        [
            KeyboardButton(text="bosh menuga qaytish 🔙"),
        ],
    ],
    resize_keyboard=True,
)


def get_main_menu(user_id: int):
    # NOTE: label texts must stay exactly as stored in locales/*.json —
    # handlers match them with F.text.in_() filters.
    from i18n import t
    is_admin = is_user_admin(user_id)
    ln = get_user_language(user_id)
    keyboard = [
        [
            KeyboardButton(text=t("menu_start_game", ln)),
            KeyboardButton(text=t("menu_leaderboard", ln)),
        ],
        [
            KeyboardButton(text=t("menu_earn", ln)),
            KeyboardButton(text=t("menu_settings", ln)),
        ],
        [
            KeyboardButton(text=t("menu_cabinet", ln)),
            KeyboardButton(text=t("menu_rules", ln)),
        ],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="🧑‍💻 admin panel")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


change_name = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="change username 🖌"),
            KeyboardButton(text="change Language 🇺🇸"),
        ],
        [
            KeyboardButton(text="❓ help"),
            KeyboardButton(text="back to main menu 🔙"),
        ],
    ],
    resize_keyboard=True,
)

change_name_ru = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="изменить имя пользователя 🖌"),
            KeyboardButton(text="изменить язык 🇷🇺"),
        ],
        [
            KeyboardButton(text="❓ помощь"),
            KeyboardButton(text="вернуться в главное меню 🔙"),
        ],
    ],
    resize_keyboard=True,
)

change_name_uz = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="usernameni o'zgartirish  🖌"),
            KeyboardButton(text="Tilni o'zgartirish 🇺🇿"),
        ],
        [
            KeyboardButton(text="❓ yordam"),
            KeyboardButton(text="bosh menuga qaytish 🔙"),
        ],
    ],
    resize_keyboard=True,
)

count_players = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="2️⃣"),
            KeyboardButton(text="3️⃣"),
            KeyboardButton(text="4️⃣"),
        ],
        [KeyboardButton(text="back to main menu 🔙")],
    ],
    resize_keyboard=True,
)

count_players_ru = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="2️⃣"),
            KeyboardButton(text="3️⃣"),
            KeyboardButton(text="4️⃣"),
        ],
        [KeyboardButton(text="вернуться в главное меню 🔙")],
    ],
    resize_keyboard=True,
)

count_players_uz = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="2️⃣"),
            KeyboardButton(text="3️⃣"),
            KeyboardButton(text="4️⃣"),
        ],
        [KeyboardButton(text="bosh menuga qaytish 🔙")],
    ],
    resize_keyboard=True,
)

cancel_button = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="back to main menu 🔙")]],
    resize_keyboard=True,
)

cancel_button_ru = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="вернуться в главное меню 🔙")]],
    resize_keyboard=True,
)

cancel_button_uz = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="bosh menuga qaytish 🔙")]],
    resize_keyboard=True,
)

admin_panel_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🎯 Game archive"),
            KeyboardButton(text="🏆 tournaments"),
        ],
        [
            KeyboardButton(text="📊 statistics"),
            KeyboardButton(text="📤 send message"),
        ],
        [
            KeyboardButton(text="💳 user's balance"),
            KeyboardButton(text="👤 Admins"),
        ],
        [
            KeyboardButton(text="🧑‍🎓 users"),
            KeyboardButton(text="👨‍👩‍👦‍👦 refferals"),
        ],
        [
            KeyboardButton(text="🔗 channels"),
            KeyboardButton(text="🔙 main menu"),
        ],
    ],
    resize_keyboard=True,
)

channels_show_keyboards = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🍿 show channels"),
            KeyboardButton(text="➕ Add channel"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

referrals_section_buttons = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🔝 Top referrals"),
            KeyboardButton(text="🔄 change referral amount"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

users_balance_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="➕ Add Unity Coins to All Users"),
            KeyboardButton(text="👀 View User Unity Coins"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

change_users_balance = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="➕ Add Unity Coins"),
            KeyboardButton(text="➖ Subtract Unity Coins"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

admins_list_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="➕ add admin"),
            KeyboardButton(text="🧾 list of admins"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

back_to_admin_panel = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

send_messages = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📨 send message to all"),
            KeyboardButton(text="📩 send message to one"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

users_control_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🪪 List of users"),
        ],
        [
            KeyboardButton(text="🗒 information of user"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

tournaments_admin_panel_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="⚡️ Ongoing"),
            KeyboardButton(text="⏳ Upcoming"),
            KeyboardButton(text="🗂 Archive"),
        ],
        [
            KeyboardButton(text="➕ create a new Tournament"),
        ],
        [
            KeyboardButton(text="back to admin panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

upcoming_tournaments_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📝 edit starting"),
            KeyboardButton(text="🚫 delete the tournament"),
        ],
        [
            KeyboardButton(text="back to tournaments panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

ongoing_tournaments_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="✅ start the tournament"),
            KeyboardButton(text="👀 watch results"),
        ],
        [
            KeyboardButton(text="🚫 delete this tournament"),
            KeyboardButton(text="⛹️ players"),
        ],
        [
            KeyboardButton(text="back to tournaments panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

back_to_tournaments_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="back to tournaments panel 🔙"),
        ],
    ],
    resize_keyboard=True,
)

